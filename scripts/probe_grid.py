"""Grid recon: read the catalogue, probe every transport, emit the camera seed.

Ticket G1. Produces `data/cameras.seed.json` in the shape of TASK.md [C8] --
the file every other lane reads to learn which cameras exist and how to reach
them. No lat/lon here; coordinates are G6.

Two rules this script exists to enforce:

  * Read per-camera properties before anything else touches a stream. The
    published catalogue leaves codec/resolution/fps empty for 19 of 30 cameras
    and misreports fps on 4, so the seed carries measured values and records
    which of the two it used.
  * Pace the load. Every client gets its own copy of each stream and the
    organisers throttled us once already, so probes run sequentially with a
    pause between them -- never a tight retry loop.

Probing uses PyAV rather than an ffprobe subprocess: PyAV ships its own ffmpeg
libraries, so this runs on all three laptops without a system ffmpeg install.

Usage:
    python scripts/probe_grid.py                    # live probe, writes the seed
    python scripts/probe_grid.py --transport hls    # skip the RTSP dial
    python scripts/probe_grid.py --from-cache data/catalogue/grid_survey.json
    python scripts/probe_grid.py --check            # verify + print the seed
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_DIR = ROOT / "data" / "catalogue"
SEED = ROOT / "data" / "cameras.seed.json"

GRID_HOST = os.environ.get("GRID_HOST", "live.corp8.cloud")
RTSP_PORT = 8554
WHEP_PORT = 8889

# Seconds between probes. The grid hands every client its own copy of the
# stream; hammering it is how we got throttled the first time.
PACE_S = 1.5

# Location strings are free text typed by whoever installed the camera, so a
# district is only assigned where the text names one outright. Everything else
# stays UNKNOWN and is resolved by G6, which opens each frame to place a pin
# anyway. Guessing here would put a wrong district on a police record.
DISTRICT_TOKENS = {
    "junagadh": "JUNAGADH",
    "gir-somnath": "GIR_SOMNATH",
    "gir somnath": "GIR_SOMNATH",
    "rajkot": "RAJKOT",
    "navsari": "NAVSARI",
    "gandevi": "NAVSARI",
    "bilimora": "NAVSARI",
    "patan": "PATAN",
    "adalaj": "GANDHINAGAR",
    "dehgam": "GANDHINAGAR",
    "gandhidham": "KUTCH",
}


def _log(sym: str, msg: str) -> None:
    print(f"[{sym}] {msg}", flush=True)


def base_url(host: str) -> str:
    if not host.startswith(("http://", "https://")):
        host = "https://" + host
    return host.rstrip("/")


def district_of(location: str) -> str:
    blob = (location or "").lower()
    for token, code in DISTRICT_TOKENS.items():
        if token in blob:
            return code
    return "UNKNOWN"


def port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def absolute(url: str | None, base: str) -> str | None:
    if not url:
        return None
    return url if url.startswith(("http://", "https://", "rtsp://")) else base + url


def fetch_catalogue(base: str, session: requests.Session) -> list[dict] | None:
    """GET /api/ingest. The catalogue is the contract; endpoint paths are not."""
    for path in ("/api/ingest", "/api/ingest/", "/api/cameras"):
        url = base + path
        try:
            resp = session.get(url, timeout=25)
        except requests.RequestException as exc:
            _log("!", f"{url} -> {type(exc).__name__}: {exc}")
            continue
        if resp.status_code != 200:
            hint = ""
            if resp.status_code in (502, 503, 504):
                hint = "  (origin down behind Cloudflare, not our request)"
            _log("!", f"{url} -> HTTP {resp.status_code}{hint}")
            continue
        try:
            data = resp.json()
        except ValueError:
            _log("!", f"{url} -> 200 but not JSON (login wall?)")
            continue
        CATALOGUE_DIR.mkdir(parents=True, exist_ok=True)
        (CATALOGUE_DIR / "ingest.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        cams = data.get("cameras") if isinstance(data, dict) else data
        if isinstance(cams, list):
            _log("+", f"catalogue from {url}: {len(cams)} cameras")
            return cams
    return None


def probe_stream(url: str, *, rtsp: bool, timeout: int = 25) -> dict:
    """Open one stream and read what is actually served, not what is declared."""
    import av  # imported late: pulling it in for --check costs a second for nothing

    options = {"rtsp_transport": "tcp"} if rtsp else {}
    started = time.time()
    try:
        with av.open(url, options=options, timeout=float(timeout)) as container:
            stream = next(
                (s for s in container.streams if s.type == "video"), None
            )
            if stream is None:
                return {"ok": False, "error": "no video stream"}
            rate = stream.average_rate or stream.base_rate or stream.guessed_rate
            ctx = stream.codec_context
            return {
                "ok": True,
                "codec": ctx.name if ctx else None,
                "width": ctx.width if ctx else None,
                "height": ctx.height if ctx else None,
                "fps": round(float(rate), 2) if rate else None,
                "connect_s": round(time.time() - started, 1),
            }
    except Exception as exc:  # PyAV raises a wide family; the message is the value
        msg = str(exc).strip().splitlines()
        return {"ok": False, "error": (msg[-1][:160] if msg else type(exc).__name__)}


def seed_row(cam: dict, base: str, host: str) -> dict:
    """One camera in [C8] shape, before any probe result is attached."""
    cid = str(cam.get("id"))
    return {
        "camera_id": cid,
        "name": cam.get("location") or cam.get("name") or f"Camera {cid}",
        "district_code": district_of(cam.get("location", "")),
        # FIX | PTZ | RLVD is burned into the video overlay, not carried in the
        # catalogue. G6 opens every frame to place its pin and fills this in.
        "install_type": "UNKNOWN",
        "driver": "mediamtx",
        "codec": cam.get("codec") or None,
        "resolution": (
            f"{cam['width']}x{cam['height']}"
            if cam.get("width") and cam.get("height")
            else None
        ),
        "fps": cam.get("fps") or None,
        "transports": {
            "rtsp": absolute(cam.get("rtsp_url"), base)
            or f"rtsp://{host}:{RTSP_PORT}/stream/{cid}",
            "hls": absolute(cam.get("hls_live_url"), base)
            or f"{base}/live/stream/{cid}/index.m3u8",
            "whep": absolute(cam.get("webrtc_url"), base)
            or f"http://{host}:{WHEP_PORT}/stream/{cid}/whep",
        },
        "transport_probe": {"rtsp": False, "hls": False},
    }


def apply_measurement(row: dict, transport: str, probe: dict) -> None:
    """Measured properties beat catalogue properties, and say so."""
    row["transport_probe"][transport] = bool(probe.get("ok"))
    if not probe.get("ok"):
        return
    if probe.get("codec"):
        row["codec"] = probe["codec"]
    if probe.get("width") and probe.get("height"):
        row["resolution"] = f"{probe['width']}x{probe['height']}"
    if probe.get("fps"):
        row["fps"] = probe["fps"]
        # Opening a stream gives the rate the container claims, which is still a
        # declared number -- the grid's real delivered rate has been measured as
        # low as 9.92 fps on a stream nominally at 25. Delivered fps is counted
        # over a window by the worker and read back by G3's health monitor; this
        # field only sizes the decoder.
        row["fps_source"] = "container-nominal"
    row["properties_source"] = "measured"


def build_live(args) -> list[dict] | None:
    base = base_url(args.host)
    host = urlparse(base).hostname or args.host
    session = requests.Session()
    session.headers["User-Agent"] = "prahari-probe/1.0"

    _log("*", f"grid {base}")
    cameras = fetch_catalogue(base, session)
    if not cameras:
        _log("-", "no catalogue -- cannot build a live seed")
        return None

    # Dial 8554 once at the host, not thirty times. If the port is filtered the
    # per-camera RTSP probes would each burn a full timeout to learn the same
    # thing.
    do_rtsp = args.transport in ("both", "rtsp")
    if do_rtsp and not port_open(host, RTSP_PORT):
        _log("!", f"port {RTSP_PORT} closed/filtered from this network -> HLS only")
        do_rtsp = False

    rows = []
    for cam in cameras:
        if not isinstance(cam, dict):
            continue
        row = seed_row(cam, base, host)
        row["properties_source"] = "catalogue"
        cid = row["camera_id"]

        if args.transport in ("both", "hls"):
            probe = probe_stream(row["transports"]["hls"], rtsp=False,
                                 timeout=args.timeout)
            apply_measurement(row, "hls", probe)
            time.sleep(PACE_S)
        if do_rtsp:
            probe = probe_stream(row["transports"]["rtsp"], rtsp=True,
                                 timeout=args.timeout)
            apply_measurement(row, "rtsp", probe)
            time.sleep(PACE_S)

        reach = [t for t, ok in row["transport_probe"].items() if ok]
        if reach:
            _log("+", f"cam {cid:>2}  {'+'.join(reach):<9} "
                      f"{row['codec']} {row['resolution']} @{row['fps']}fps")
        else:
            _log("-", f"cam {cid:>2}  unreachable")
        rows.append(row)
    return rows


def build_from_cache(args) -> list[dict] | None:
    """Rebuild the seed from a previous survey when the grid is unreachable.

    Honest by construction: rows carry the survey's timestamp and are marked
    stale, so nobody downstream mistakes a day-old reachability flag for a
    live one.
    """
    survey_path = Path(args.from_cache)
    if not survey_path.is_absolute():
        survey_path = ROOT / survey_path
    if not survey_path.exists():
        _log("-", f"no cache at {survey_path}")
        return None

    survey = json.loads(survey_path.read_text(encoding="utf-8"))
    base = base_url(survey.get("base") or args.host)
    host = urlparse(base).hostname or args.host
    surveyed_at = survey.get("summary", {}).get("surveyed_at", "unknown")
    _log("!", f"building from cache surveyed {surveyed_at} -- reachability is STALE")

    rows = []
    for entry in survey.get("cameras", []):
        cam = {
            "id": entry.get("id"),
            "location": entry.get("location"),
            "name": entry.get("name"),
            "rtsp_url": entry.get("rtsp_url"),
            "hls_live_url": entry.get("hls_url"),
            **{k: v for k, v in (entry.get("catalogue") or {}).items() if v},
        }
        row = seed_row(cam, base, host)
        row["properties_source"] = "catalogue"
        for transport in ("hls", "rtsp"):
            probe = entry.get(transport)
            if isinstance(probe, dict):
                apply_measurement(row, transport, {
                    "ok": probe.get("ok"),
                    "codec": probe.get("codec"),
                    "width": probe.get("width"),
                    "height": probe.get("height"),
                    # r_frame_rate is the container's nominal rate. The survey's
                    # declared_fps is an average over a short probe, which the
                    # GOP replay on connect skews downward -- so the nominal
                    # value is the more honest of the two bad options here.
                    "fps": probe.get("r_frame_rate") or probe.get("declared_fps"),
                })
        if row.get("properties_source") == "measured":
            row["properties_source"] = f"measured@{surveyed_at}"
        row["stale"] = True
        rows.append(row)
    return rows


def write_seed(rows: list[dict], source: str) -> None:
    rows.sort(key=lambda r: int(r["camera_id"]) if r["camera_id"].isdigit() else 0)
    SEED.parent.mkdir(parents=True, exist_ok=True)
    SEED.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    _log("+", f"seed -> {SEED.relative_to(ROOT)}  ({len(rows)} cameras, {source})")


def check() -> int:
    """The Verify line: camera count and per-transport reachability."""
    if not SEED.exists():
        _log("-", f"{SEED.relative_to(ROOT)} missing -- run probe_grid.py first")
        return 1
    rows = json.loads(SEED.read_text(encoding="utf-8"))

    required = {"camera_id", "name", "district_code", "install_type", "driver",
                "codec", "resolution", "fps", "transports", "transport_probe"}
    bad = [r.get("camera_id") for r in rows if not required <= set(r)]
    if bad:
        _log("-", f"rows missing [C8] fields: {bad}")
        return 1

    by_transport = {
        t: sum(1 for r in rows if r["transport_probe"].get(t)) for t in ("rtsp", "hls")
    }
    reachable = [r for r in rows if any(r["transport_probe"].values())]
    unreachable = [r for r in rows if not any(r["transport_probe"].values())]
    stale = [r for r in rows if r.get("stale")]

    print(f"cameras          : {len(rows)}")
    print(f"reachable        : {len(reachable)}/{len(rows)} "
          f"(at least one transport)")
    for transport, count in by_transport.items():
        print(f"  via {transport:<12}: {count}")
    districts = {}
    for r in rows:
        districts[r["district_code"]] = districts.get(r["district_code"], 0) + 1
    print(f"districts        : {districts}")
    if unreachable:
        print(f"unreachable      : {[r['camera_id'] for r in unreachable]}")
    if stale:
        srcs = {r.get("properties_source") for r in stale}
        print(f"STALE            : {len(stale)} rows from a cached survey {srcs}")
        print("                   re-run without --from-cache once the grid is up")

    if not reachable:
        _log("-", "no camera has a reachable transport")
        return 1
    _log("+", "seed is valid [C8]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=GRID_HOST, help="grid host or base URL ($GRID_HOST)")
    ap.add_argument("--transport", choices=["hls", "rtsp", "both"], default="both")
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--from-cache", default=None,
                    help="build from a previous grid_survey.json instead of probing")
    ap.add_argument("--check", action="store_true", help="verify and print the seed")
    args = ap.parse_args()

    if args.check:
        return check()

    if args.from_cache:
        rows = build_from_cache(args)
        source = "cached"
    else:
        rows = build_live(args)
        source = "live"
        if rows is None:
            _log("!", "grid unreachable; retry with "
                      "--from-cache data/catalogue/grid_survey.json")
    if not rows:
        return 1
    write_seed(rows, source)
    return check()


if __name__ == "__main__":
    sys.exit(main())
