"""Probe the Sentinel sandbox grid and record exactly what we are dealing with.

Run this the moment we have the sandbox host. It answers the questions that
decide the architecture:
  - does /api/ingest respond, and what is its exact schema?
  - is RTSP 8554 reachable from this network, or do we need the HLS fallback?
  - what codecs / resolutions / REAL frame rates are on the grid?

Usage:
    python scripts/probe_grid.py --host <host-or-ip>
    python scripts/probe_grid.py --host <host> --user <u> --password <p>
    python scripts/probe_grid.py --host localhost --cameras 4      # local simgrid

Writes data/catalogue/ingest.json and data/catalogue/probe_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_DIR = ROOT / "data" / "catalogue"


def _log(sym: str, msg: str) -> None:
    print(f"[{sym}] {msg}", flush=True)


def normalise_base(host: str) -> str:
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.rstrip("/")


def port_open(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_catalogue(base: str, session: requests.Session) -> list[dict] | None:
    """The camera catalogue is the contract -- endpoints are not."""
    for path in ("/api/ingest", "/api/ingest/", "/api/cameras", "/api/streams"):
        url = base + path
        try:
            resp = session.get(url, timeout=20)
        except requests.RequestException as exc:
            _log("!", f"{url} -> {type(exc).__name__}: {exc}")
            continue
        if resp.status_code != 200:
            _log("!", f"{url} -> HTTP {resp.status_code}")
            continue
        try:
            data = resp.json()
        except ValueError:
            _log("!", f"{url} -> 200 but not JSON (login wall?)")
            continue
        _log("+", f"catalogue from {url}")
        CATALOGUE_DIR.mkdir(parents=True, exist_ok=True)
        (CATALOGUE_DIR / "ingest.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        # Accept {"cameras": [...]}, {"data": [...]} or a bare list.
        if isinstance(data, dict):
            for key in ("cameras", "data", "streams", "items", "results"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        return data if isinstance(data, list) else None
    return None


def pick_url(cam: dict, kind: str) -> str | None:
    """Find the rtsp/hls/whep URL in a camera record without assuming key names."""
    wants = {
        "rtsp": ("rtsp",),
        "hls": ("hls", "m3u8"),
        "whep": ("whep", "webrtc"),
    }[kind]
    for key, value in cam.items():
        if not isinstance(value, str):
            continue
        blob = f"{key} {value}".lower()
        if any(w in blob for w in wants) and ("://" in value or value.startswith("/")):
            return value
    return None


def ffprobe_stream(url: str, timeout: int = 25) -> dict:
    """Probe one stream over RTSP/TCP. Never trust the declared frame rate."""
    if not shutil.which("ffprobe"):
        return {"ok": False, "error": "ffprobe not on PATH"}
    cmd = [
        "ffprobe", "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", "tcp",
        "-print_format", "json", "-show_streams", "-show_format",
        "-analyzeduration", "4000000", "-probesize", "6000000",
        url,
    ]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or "").strip()[:400]}
    try:
        info = json.loads(proc.stdout)
    except ValueError:
        return {"ok": False, "error": "unparseable ffprobe output"}

    video = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    declared = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/0"
    try:
        num, den = (float(x) for x in declared.split("/"))
        declared_fps = round(num / den, 2) if den else None
    except (ValueError, ZeroDivisionError):
        declared_fps = None

    return {
        "ok": True,
        "codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "pix_fmt": video.get("pix_fmt"),
        "declared_fps": declared_fps,
        "connect_seconds": round(time.time() - started, 2),
    }


def measure_real_fps(url: str, seconds: int = 8) -> dict:
    """Measure delivered frame rate from PTS, because the declared value lies."""
    if not shutil.which("ffmpeg"):
        return {"ok": False, "error": "ffmpeg not on PATH"}
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info",
        "-rtsp_transport", "tcp", "-i", url,
        "-t", str(seconds), "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 25)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    stderr = proc.stderr or ""
    frames = None
    for match in re.finditer(r"frame=\s*(\d+)", stderr):
        frames = int(match.group(1))
    if frames is None:
        return {"ok": False, "error": (stderr.strip()[-300:] or "no frame counter")}
    warnings = sorted(
        {
            line.strip()[:120]
            for line in stderr.splitlines()
            if any(k in line for k in ("RPS", "POC", "corrupt", "missing", "error"))
        }
    )
    return {
        "ok": True,
        "frames": frames,
        "window_s": seconds,
        "measured_fps": round(frames / seconds, 2),
        "decoder_warnings": warnings[:5],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True, help="sandbox host or full base URL")
    ap.add_argument("--user", default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--token", default=None, help="bearer token if the portal issues one")
    ap.add_argument("--cookie", default=None, help="raw Cookie header from a logged-in browser")
    ap.add_argument("--cameras", type=int, default=3, help="how many to deep-probe")
    args = ap.parse_args()

    base = normalise_base(args.host)
    hostname = urlparse(base).hostname or args.host
    report: dict = {"base": base, "hostname": hostname, "checked_at": time.time()}

    _log("*", f"target {base}")

    # 1. Ports. This is the single most important early answer: if 8554 is
    #    blocked on this network we must build the HLS path instead.
    ports = {"http": 80, "rtsp": 8554, "hls": 8888, "whep": 8889, "api": 9997}
    report["ports"] = {}
    for name, port in ports.items():
        is_open = port_open(hostname, port)
        report["ports"][name] = {"port": port, "open": is_open}
        _log("+" if is_open else "-", f"port {port:<5} ({name}) {'open' if is_open else 'closed/filtered'}")

    if not report["ports"]["rtsp"]["open"]:
        _log("!", "RTSP 8554 not reachable -> plan on the HLS/WHEP fallback path")

    # 2. Catalogue.
    session = requests.Session()
    if args.user and args.password:
        session.auth = (args.user, args.password)
    if args.token:
        session.headers["Authorization"] = f"Bearer {args.token}"
    if args.cookie:
        session.headers["Cookie"] = args.cookie

    cameras = fetch_catalogue(base, session)
    if not cameras:
        _log("!", "no catalogue. If the portal needs a session, pass --cookie or --token.")
        report["cameras"] = []
    else:
        _log("+", f"{len(cameras)} cameras in catalogue")
        report["camera_count"] = len(cameras)
        report["camera_keys"] = sorted({k for c in cameras if isinstance(c, dict) for k in c})
        _log("*", "record fields: " + ", ".join(report["camera_keys"]))

    # 3. Deep-probe a sample.
    probes = []
    for cam in (cameras or [])[: args.cameras]:
        if not isinstance(cam, dict):
            continue
        cam_id = cam.get("id") or cam.get("camera_id") or cam.get("name") or "?"
        rtsp = pick_url(cam, "rtsp")
        if not rtsp:
            continue
        _log("*", f"probing camera {cam_id}: {rtsp}")
        entry = {"id": cam_id, "rtsp": rtsp, "probe": ffprobe_stream(rtsp)}
        if entry["probe"].get("ok"):
            p = entry["probe"]
            _log("+", f"  {p['codec']} {p['width']}x{p['height']} declared={p['declared_fps']}fps")
            entry["measured"] = measure_real_fps(rtsp)
            m = entry["measured"]
            if m.get("ok"):
                delta = ""
                if p.get("declared_fps"):
                    drift = abs(m["measured_fps"] - p["declared_fps"])
                    delta = f"  (declared off by {drift:.2f})" if drift > 0.75 else ""
                _log("+", f"  measured={m['measured_fps']}fps over {m['window_s']}s{delta}")
                for w in m.get("decoder_warnings", []):
                    _log("!", f"  decoder: {w}")
        else:
            _log("-", f"  failed: {entry['probe'].get('error')}")
        probes.append(entry)

    report["probes"] = probes
    CATALOGUE_DIR.mkdir(parents=True, exist_ok=True)
    out = CATALOGUE_DIR / "probe_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log("+", f"report -> {out.relative_to(ROOT)}")

    codecs = {p["probe"].get("codec") for p in probes if p.get("probe", {}).get("ok")}
    if len(codecs) > 1:
        _log("*", f"mixed codecs confirmed: {codecs} -- decoder must handle both")
    return 0


if __name__ == "__main__":
    sys.exit(main())
