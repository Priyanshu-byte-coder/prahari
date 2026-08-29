"""[G1] Grid recon + camera seed.

Hits GET $GRID_HOST/api/ingest, records every camera (id, name, codec,
resolution, fps, and the three transport URLs), and writes
data/cameras.seed.json in the shape frozen at TASK.md [C8].

No lat/lon here -- that is G6.

Usage:
    python scripts/probe_grid.py                       # probe + write the seed
    python scripts/probe_grid.py --host live.corp8.cloud
    python scripts/probe_grid.py --check                # camera count + per-transport reachability

If $GRID_HOST / --host is unreachable (e.g. the sandbox is offline outside
the event window), falls back to the last catalogue snapshot salvaged from
commit 4d0c945 (data/catalogue/ingest.json.bootstrap) so the rest of the
team is never blocked on the grid being up. That fallback is logged loudly
-- it is a bootstrap, not a substitute for a live re-probe before the demo.
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
SEED_OUT = ROOT / "data" / "cameras.seed.json"
BOOTSTRAP = ROOT / "data" / "catalogue" / "ingest.json.bootstrap"

TRANSPORT_PORTS = {"rtsp": 8554, "hls": 80, "whep": 8889}

# ponytail: location -> district_code is a keyword guess against the real
# catalogue's free-text `location` field, confident only where the name is
# unambiguous (an explicit district, or a town with one well-known Gujarat
# district). Upgrade path: G6 replaces every UNKNOWN with a manually-placed
# pin and can correct any wrong guess here at the same time.
DISTRICT_KEYWORDS: dict[str, str] = {
    "junagadh": "JUNAGADH",
    "gir-somnath": "GIR_SOMNATH",
    "rajkot": "RAJKOT",
    "navsari": "NAVSARI",
    "bilimora": "NAVSARI",
    "gandevi": "NAVSARI",
    "patan": "PATAN",
    "dehgam": "GANDHINAGAR",
    "adalaj": "GANDHINAGAR",
    "gandhidham": "KUTCH",
    "paldi": "AHMEDABAD",
    "visat": "AHMEDABAD",
    "chiman bhai bridge": "AHMEDABAD",
}


def _log(sym: str, msg: str) -> None:
    print(f"[{sym}] {msg}", flush=True)


def guess_district(location: str) -> str:
    low = (location or "").lower()
    for kw, code in DISTRICT_KEYWORDS.items():
        if kw in low:
            return code
    return "UNKNOWN"


def normalise_base(host: str) -> str:
    if not host.startswith(("http://", "https://")):
        host = "https://" + host
    return host.rstrip("/")


def fetch_live_catalogue(host: str, timeout: float = 10.0) -> list[dict] | None:
    base = normalise_base(host)
    for path in ("/api/ingest", "/api/ingest/"):
        url = base + path
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException as exc:
            _log("!", f"{url} -> {type(exc).__name__}: {exc}")
            continue
        if resp.status_code != 200:
            _log("!", f"{url} -> HTTP {resp.status_code}")
            continue
        try:
            data = resp.json()
        except ValueError:
            _log("!", f"{url} -> 200 but not JSON")
            continue
        cams = data.get("cameras") if isinstance(data, dict) else data
        if isinstance(cams, list) and cams:
            _log("+", f"live catalogue from {url}: {len(cams)} cameras")
            return cams
    return None


def load_bootstrap() -> list[dict]:
    data = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    cams = data["cameras"] if isinstance(data, dict) else data
    _log("!", f"grid unreachable -- using salvaged snapshot ({BOOTSTRAP.name}), {len(cams)} cameras")
    _log("!", "re-run against a live host before the demo; codec/resolution/fps here are stale.")
    return cams


def port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def hls_reachable(url: str, base: str, timeout: float = 5.0) -> bool:
    full = url if url.startswith("http") else base + url
    try:
        resp = requests.head(full, timeout=timeout, allow_redirects=True)
        if resp.status_code == 405:  # some servers reject HEAD, retry GET
            resp = requests.get(full, timeout=timeout, stream=True)
        return resp.status_code < 400
    except requests.RequestException:
        return False


def build_seed(cams: list[dict], host: str) -> list[dict]:
    base = normalise_base(host)
    hostname = urlparse(base).hostname or host
    seed = []
    for cam in cams:
        cam_id = str(cam.get("id") or cam.get("camera_id") or cam.get("number") or "?")
        rtsp_url = cam.get("rtsp_url") or cam.get("rtsp")
        hls_raw = cam.get("hls_live_url") or cam.get("hls")
        hls_url = hls_raw if (hls_raw or "").startswith("http") else (base + hls_raw if hls_raw else None)
        whep_url = cam.get("webrtc_url") or cam.get("whep")

        rtsp_ok = port_open(hostname, TRANSPORT_PORTS["rtsp"]) if rtsp_url else False
        hls_ok = hls_reachable(hls_raw, base) if hls_raw else False

        entry = {
            "camera_id": cam_id,
            "name": cam.get("name") or f"Camera {cam_id}",
            "district_code": guess_district(cam.get("location", "")),
            "install_type": "FIX",
            "driver": "mediamtx",
            "codec": cam.get("codec") or None,
            "resolution": f"{cam['width']}x{cam['height']}" if cam.get("width") and cam.get("height") else None,
            "fps": cam.get("fps") or None,
            "transports": {
                "rtsp": rtsp_url,
                "hls": hls_url,
                "whep": whep_url,
            },
            "transport_probe": {"rtsp": rtsp_ok, "hls": hls_ok},
            "location_raw": cam.get("location"),
        }
        seed.append(entry)
    return seed


def do_check() -> int:
    if not SEED_OUT.exists():
        _log("!", f"{SEED_OUT.relative_to(ROOT)} does not exist yet -- run probe_grid.py first")
        return 1
    seed = json.loads(SEED_OUT.read_text(encoding="utf-8"))
    total = len(seed)
    by_transport = {"rtsp": 0, "hls": 0}
    reachable = 0
    for cam in seed:
        probe = cam.get("transport_probe", {})
        any_ok = False
        for t in ("rtsp", "hls"):
            if probe.get(t):
                by_transport[t] += 1
                any_ok = True
        if any_ok:
            reachable += 1
    print(f"cameras: {total}")
    print(f"reachable (>=1 transport): {reachable}/{total}")
    print(f"by transport: rtsp={by_transport['rtsp']} hls={by_transport['hls']}")
    unreachable = [c["camera_id"] for c in seed if not any(c.get("transport_probe", {}).values())]
    if unreachable:
        print(f"unreachable camera_ids: {', '.join(unreachable)}")
    return 0 if reachable == total else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("GRID_HOST", "live.corp8.cloud"))
    ap.add_argument("--check", action="store_true", help="print camera count + per-transport reachability from the last seed")
    args = ap.parse_args()

    if args.check:
        return do_check()

    _log("*", f"target {args.host}")
    cams = fetch_live_catalogue(args.host)
    if not cams:
        cams = load_bootstrap()

    seed = build_seed(cams, args.host)
    SEED_OUT.parent.mkdir(parents=True, exist_ok=True)
    SEED_OUT.write_text(json.dumps(seed, indent=2), encoding="utf-8")
    _log("+", f"wrote {len(seed)} cameras -> {SEED_OUT.relative_to(ROOT)}")

    reachable = sum(1 for c in seed if any(c["transport_probe"].values()))
    _log("+", f"{reachable}/{len(seed)} cameras have at least one reachable transport")
    unknown_district = sum(1 for c in seed if c["district_code"] == "UNKNOWN")
    if unknown_district:
        _log("!", f"{unknown_district} cameras have district_code=UNKNOWN -- G6 should resolve these")
    return 0 if reachable == len(seed) else 1


if __name__ == "__main__":
    sys.exit(main())
