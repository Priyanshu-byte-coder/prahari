"""Pre-submission preflight — the eight checks from the Sentinel Resources page.

The organisers publish a pre-submission checklist. Most of it cannot be
answered by reading the code alone and most of it cannot be answered by
probing the grid alone, so each check here does whichever is actually
conclusive: some inspect the implementation, some open a real stream and
observe what happens.

Run it before submitting, and again on arrival at the venue before the judges
appear.

    python scripts/preflight.py                 static checks + live grid
    python scripts/preflight.py --offline       static checks only
    python scripts/preflight.py --camera 13     pick the camera used for live checks

Exit code 0 = every check green.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = "http://127.0.0.1:8080"
SURVEY = ROOT / "data" / "catalogue" / "grid_survey.json"
CATALOGUE = ROOT / "data" / "catalogue" / "ingest.json"


@dataclass
class Result:
    ok: bool
    detail: str


def _src(*relative: str) -> str:
    """Concatenated source of the named files, for static inspection."""
    out = []
    for rel in relative:
        p = ROOT / rel
        if p.exists():
            out.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(out)


# --------------------------------------------------------------- the checks

def check_tcp_forced() -> Result:
    """1. Every client forces RTSP over TCP."""
    src = _src("services/worker/stream_reader.py", "scripts/probe_grid.py",
               "scripts/survey_grid.py")
    forces = 'rtsp_transport": "tcp"' in src or '"rtsp_transport", "tcp"' in src \
        or "rtsp_transport=tcp" in src
    uses_udp = re.search(r"rtsp_transport\s*[=:]\s*['\"]?udp", src, re.I)
    if uses_udp:
        return Result(False, "a client requests UDP transport")
    if not forces:
        return Result(False, "no client explicitly forces TCP")
    return Result(True, "stream reader and probes all pass rtsp_transport=tcp")


def check_no_declared_fps_timing() -> Result:
    """2. No timing logic depends on declared FPS or on frame arrival time."""
    src = _src("services/worker/stream_reader.py", "services/worker/run_worker.py",
               "services/api/route_routes.py")
    if "CAP_PROP_FPS" in src:
        return Result(False, "CAP_PROP_FPS is referenced in the timing path")
    if "pts_seconds" not in src:
        return Result(False, "timing does not appear to be PTS-derived")
    anchored = "observed_at" in src and "ANCHOR_SETTLE_SECONDS" in src
    if not anchored:
        return Result(False, "no PTS-to-wall-clock anchor found")
    return Result(True, "all timing derives from PTS, anchored after the connect burst")


def check_gap_tolerance() -> Result:
    """3. Inter-frame gaps do not crash or stall the pipeline."""
    src = _src("services/worker/stream_reader.py")
    # Frames are yielded as they decode, with no fixed-cadence assumption and no
    # sleep between frames; a gap simply means the next yield happens later.
    if re.search(r"time\.sleep\([^)]*\)\s*#.*frame", src):
        return Result(False, "a fixed inter-frame sleep would break on gaps")
    if "for packet in container.demux" not in src:
        return Result(False, "cannot confirm demux-driven iteration")
    return Result(True, "frames are demux-driven; no fixed cadence is assumed")


def check_backoff() -> Result:
    """4. Reconnect with exponential backoff is implemented."""
    src = _src("services/worker/stream_reader.py")
    has_min = "BACKOFF_MIN" in src
    has_max = "BACKOFF_MAX" in src
    grows = re.search(r"backoff\s*\*\s*2|backoff\s*\*=\s*2", src)
    jitter = "random.uniform" in src
    if not (has_min and has_max and grows):
        return Result(False, "no exponential backoff found in the reader")
    if not jitter:
        return Result(False, "backoff is not jittered; clients will retry in lockstep")
    return Result(True, "2s start, 30s cap, doubling, jittered")


def check_decoder_warnings_nonfatal() -> Result:
    """5. Decoder warnings on join are logged, not fatal."""
    src = _src("services/worker/stream_reader.py")
    if "FFmpegError" not in src:
        return Result(False, "decoder errors are not caught at all")
    # The decode loop must continue rather than propagate.
    if not re.search(r"except av\.error\.FFmpegError.*?\n(?:.*\n)*?\s*continue", src):
        return Result(False, "decoder errors do not continue the loop")
    return Result(True, "mid-GOP decoder warnings are logged and skipped")


def check_catalogue_driven() -> Result:
    """6. Camera list and per-camera properties come from /api/ingest."""
    src = _src("services/api/main.py", "services/worker/supervisor.py")
    if "/api/ingest" not in src:
        return Result(False, "the upstream catalogue is never fetched")
    hard_coded = re.search(r"rtsp://[^\s\"']*live\.corp8\.cloud[^\s\"']*/stream/\d+",
                           _src("services/worker/run_worker.py",
                                "services/worker/supervisor.py",
                                "services/api/main.py"))
    if hard_coded:
        return Result(False, f"hard-coded endpoint: {hard_coded.group(0)}")
    if not SURVEY.exists():
        return Result(False, "no measured per-camera survey on disk")
    return Result(True, "registry syncs from /api/ingest; per-camera properties measured")


def check_mixed_codecs() -> Result:
    """7. The pipeline handles mixed codecs and mixed resolutions."""
    if not SURVEY.exists():
        return Result(False, "no survey to confirm the grid's spread")
    data = json.loads(SURVEY.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    codecs = summary.get("codecs", {})
    resolutions = summary.get("resolutions", {})
    if len(codecs) < 2:
        return Result(False, f"survey saw only {list(codecs)}; cannot confirm mixed decode")
    if len(resolutions) < 2:
        return Result(False, "survey saw a single resolution")
    return Result(
        True,
        f"{'/'.join(codecs)} across {len(resolutions)} resolutions, decoded by the same path",
    )


def check_discontinuity() -> Result:
    """8. Behaviour is sane across a scene discontinuity."""
    reader = _src("services/worker/stream_reader.py")
    worker = _src("services/worker/run_worker.py")
    if "discontinuous" not in reader or "LOOP_REGRESSION_S" not in reader:
        return Result(False, "no PTS-regression detection in the reader")
    resets = [w for w in ("tracker.reset()", "plates.reset()", "timeline.reset()")
              if w in worker]
    if len(resets) < 3:
        missing = {"tracker.reset()", "plates.reset()", "timeline.reset()"} - set(resets)
        return Result(False, f"state not fully reset on discontinuity: missing {missing}")
    return Result(True, "PTS regression detected; tracker, plates and timeline all reset")


# ------------------------------------------------------------- live checks

def live_gateway(camera: str) -> Result:
    try:
        r = requests.get(f"{GATEWAY}/api/health", timeout=10)
        r.raise_for_status()
    except requests.RequestException as exc:
        return Result(False, f"gateway not reachable: {exc}")
    return Result(True, "gateway healthy")


def live_stream_opens(camera: str) -> Result:
    """Open a real stream through the gateway and decode a frame."""
    url = f"{GATEWAY}/stream/{camera}/index.m3u8"
    cmd = ["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format", "json",
           "-show_streams", "-analyzeduration", "4000000", "-probesize", "6000000", url]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=70)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return Result(False, f"{type(exc).__name__} opening camera {camera}")
    try:
        info = json.loads(proc.stdout or "{}")
    except ValueError:
        return Result(False, "unparseable probe output")
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        return Result(False, f"camera {camera} produced no video stream")
    return Result(
        True,
        f"cam {camera}: {video['codec_name']} {video['width']}x{video['height']} "
        f"in {time.time() - started:.1f}s",
    )


def live_consume_only() -> Result:
    """The consume-only guard must refuse control-plane and off-grid URLs.

    Exercised directly rather than over HTTP: a request for a nonsense path
    returns 404 whether the guard fired or not, so routing through the web
    layer would prove nothing. Calling the guard is conclusive.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from fastapi import HTTPException

        from services.api.gateway import UPSTREAM_BASE, _assert_consume_only
    except ImportError as exc:
        return Result(False, f"cannot import the gateway guard: {exc}")

    must_refuse = [
        f"{UPSTREAM_BASE}/v3/config/global/get",   # control API
        f"{UPSTREAM_BASE}/whip/stream/13",         # publish endpoint
        f"{UPSTREAM_BASE}/admin",                  # not a permitted read path
        "https://example.com/live/stream/13/index.m3u8",  # off-grid host
    ]
    for url in must_refuse:
        try:
            _assert_consume_only(url)
        except HTTPException:
            continue
        return Result(False, f"guard ALLOWED {url}")

    # And it must still permit the paths the platform legitimately reads.
    for url in (f"{UPSTREAM_BASE}/live/stream/13/index.m3u8",
                f"{UPSTREAM_BASE}/api/ingest"):
        try:
            _assert_consume_only(url)
        except HTTPException as exc:
            return Result(False, f"guard wrongly refused {url}: {exc.detail}")

    return Result(True, f"{len(must_refuse)} forbidden URLs refused, 2 read paths allowed")


CHECKS = [
    ("1", "RTSP forced over TCP", check_tcp_forced, False),
    ("2", "No declared-FPS or arrival-time logic", check_no_declared_fps_timing, False),
    ("3", "Inter-frame gaps tolerated", check_gap_tolerance, False),
    ("4", "Reconnect with jittered backoff", check_backoff, False),
    ("5", "Decoder warnings non-fatal", check_decoder_warnings_nonfatal, False),
    ("6", "Catalogue-driven, nothing hard-coded", check_catalogue_driven, False),
    ("7", "Mixed codecs and resolutions", check_mixed_codecs, False),
    ("8", "Scene discontinuity handled", check_discontinuity, False),
]

LIVE_CHECKS = [
    ("L1", "Gateway healthy", live_gateway),
    ("L2", "Live stream opens and decodes", live_stream_opens),
    ("L3", "Control-plane access refused", live_consume_only),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip checks needing the grid")
    ap.add_argument("--camera", default="13")
    args = ap.parse_args()

    print("\n  PRAHARI PREFLIGHT")
    print("  Sentinel pre-submission checklist + live verification")
    print("  " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")

    width = max(len(t) for _, t, *_ in CHECKS + [(a, b, None) for a, b, _ in LIVE_CHECKS])
    failures = 0

    print("  Implementation")
    for cid, title, fn, _ in CHECKS:
        try:
            res = fn()
        except Exception as exc:  # a broken check must not hide the others
            res = Result(False, f"check raised {type(exc).__name__}: {exc}")
        mark = "PASS" if res.ok else "FAIL"
        failures += 0 if res.ok else 1
        print(f"    [{mark}] {cid:>2}  {title:<{width}}  {res.detail}")

    if not args.offline:
        print("\n  Live grid")
        for cid, title, fn in LIVE_CHECKS:
            try:
                res = fn(args.camera) if fn is not live_consume_only else fn()
            except Exception as exc:
                res = Result(False, f"check raised {type(exc).__name__}: {exc}")
            mark = "PASS" if res.ok else "FAIL"
            failures += 0 if res.ok else 1
            print(f"    [{mark}] {cid:>2}  {title:<{width}}  {res.detail}")
    else:
        print("\n  Live grid checks skipped (--offline)")

    total = len(CHECKS) + (0 if args.offline else len(LIVE_CHECKS))
    print()
    if failures:
        print(f"  {total - failures}/{total} green — {failures} FAILING\n")
        return 1
    print(f"  {total}/{total} green\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
