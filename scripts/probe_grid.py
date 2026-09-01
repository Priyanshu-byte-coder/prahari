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

Security note: --host and every URL in the catalogue response are untrusted
input. `_validated_host` rejects anything that isn't a bare hostname/IP
before it is used to build a request URL (blocks SSRF via a crafted host
argument), and `_resolve_camera_url` refuses any catalogue URL that does not
point at that same host (blocks SSRF via a compromised catalogue response).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
SEED_OUT = ROOT / "data" / "cameras.seed.json"
BOOTSTRAP = ROOT / "data" / "catalogue" / "ingest.json.bootstrap"

TRANSPORT_PORTS = {"rtsp": 8554, "hls": 80, "whep": 8889}

# One Session so the Cloudflare cookieCheck cookie is set once, not per camera.
_SESSION = requests.Session()

# Bare hostname or IPv4, no scheme/path/userinfo/query -- one shape only.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-\.]{0,253}[A-Za-z0-9])?$")

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


def _validated_host(raw: str) -> str:
    """Reject anything that isn't a bare hostname/IP before it touches a URL."""
    candidate = raw.strip()
    if candidate.startswith(("http://", "https://")):
        candidate = urlparse(candidate).hostname or ""
    if not candidate or not _HOSTNAME_RE.match(candidate):
        raise ValueError(f"refusing to probe an invalid --host value: {raw!r}")
    return candidate


def base_url(hostname: str) -> str:
    return f"https://{hostname}"


def _resolve_camera_url(raw: str | None, base: str, expected_host: str) -> str | None:
    """Accept a catalogue URL only if it's relative or points at our own host."""
    if not raw:
        return None
    if raw.startswith("/"):
        return base + raw
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https") and parsed.hostname == expected_host:
        return raw
    _log("!", f"ignoring catalogue URL off expected host {expected_host!r}: {raw!r}")
    return None


def fetch_live_catalogue(hostname: str, timeout: float = 10.0) -> list[dict] | None:
    base = base_url(hostname)
    for path in ("/api/ingest", "/api/ingest/"):
        url = base + path
        try:
            resp = _SESSION.get(url, timeout=timeout)
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


def port_open(hostname: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


ALLOWED_SCHEMES = frozenset({"http", "https"})


def _safe_url(url: str | None, hostname: str) -> str | None:
    """http(s) on the expected host only -- catalogue URLs are untrusted input."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or parsed.hostname != hostname:
        return None
    return url


def hls_reachable(url: str | None, hostname: str, timeout: float = 8.0) -> bool:
    """GET, never HEAD.

    The grid sits behind a Cloudflare cookie gate: the first request 302s to
    `?cookieCheck=1` with a Set-Cookie, and only then serves the playlist.
    HEAD against that path answers 404 (not 405), so a HEAD probe reports every
    live camera as down. A streamed GET through a cookie-carrying Session is
    the only probe that tells the truth here -- and we read the first bytes to
    confirm it really is a playlist rather than an error page served as 200.
    """
    target = _safe_url(url, hostname)
    if target is None:
        return False
    try:
        resp = _SESSION.get(target, timeout=timeout, stream=True, allow_redirects=True)
        if resp.status_code >= 400:
            return False
        head = next(resp.iter_content(chunk_size=64), b"") or b""
        resp.close()
        return head.lstrip().startswith(b"#EXTM3U")
    except requests.RequestException:
        return False


def _camera_transports(cam: dict, base: str, hostname: str) -> dict:
    rtsp_url = cam.get("rtsp_url") or cam.get("rtsp")
    hls_url = _resolve_camera_url(cam.get("hls_live_url") or cam.get("hls"), base, hostname)
    whep_url = _resolve_camera_url(cam.get("webrtc_url") or cam.get("whep"), base, hostname)
    return {"rtsp": rtsp_url, "hls": hls_url, "whep": whep_url}


def _camera_resolution(cam: dict) -> str | None:
    if cam.get("width") and cam.get("height"):
        return f"{cam['width']}x{cam['height']}"
    return None


def _build_entry(cam: dict, base: str, hostname: str, rtsp_port_open: bool) -> dict:
    cam_id = str(cam.get("id") or cam.get("camera_id") or cam.get("number") or "?")
    transports = _camera_transports(cam, base, hostname)
    rtsp_ok = bool(transports["rtsp"]) and rtsp_port_open
    hls_ok = hls_reachable(transports["hls"], hostname)
    return {
        "camera_id": cam_id,
        "name": cam.get("name") or f"Camera {cam_id}",
        "district_code": guess_district(cam.get("location", "")),
        "install_type": "FIX",
        "driver": "mediamtx",
        "codec": cam.get("codec") or None,
        "resolution": _camera_resolution(cam),
        "fps": cam.get("fps") or None,
        "transports": transports,
        "transport_probe": {"rtsp": rtsp_ok, "hls": hls_ok},
        "location_raw": cam.get("location"),
    }


def build_seed(cams: list[dict], hostname: str) -> list[dict]:
    base = base_url(hostname)
    # Dial 8554 once at the host, not once per camera: if the port is filtered
    # every per-camera probe burns a full timeout to learn the same fact.
    rtsp_port_open = port_open(hostname, TRANSPORT_PORTS["rtsp"])
    if not rtsp_port_open:
        _log("!", f"port {TRANSPORT_PORTS['rtsp']} filtered at {hostname} -- RTSP unavailable, HLS is the path")
    return [_build_entry(cam, base, hostname, rtsp_port_open) for cam in cams]


def _write_seed(text: str) -> None:
    """Writes only SEED_OUT, a module constant -- no caller-supplied path."""
    SEED_OUT.parent.mkdir(parents=True, exist_ok=True)
    SEED_OUT.write_text(text, encoding="utf-8")


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

    try:
        hostname = _validated_host(args.host)
    except ValueError as exc:
        _log("!", str(exc))
        return 2

    _log("*", f"target {hostname}")
    cams = fetch_live_catalogue(hostname)
    if not cams:
        cams = load_bootstrap()

    seed = build_seed(cams, hostname)
    _write_seed(json.dumps(seed, indent=2))
    _log("+", f"wrote {len(seed)} cameras -> {SEED_OUT.relative_to(ROOT)}")

    reachable = sum(1 for c in seed if any(c["transport_probe"].values()))
    _log("+", f"{reachable}/{len(seed)} cameras have at least one reachable transport")
    unknown_district = sum(1 for c in seed if c["district_code"] == "UNKNOWN")
    if unknown_district:
        _log("!", f"{unknown_district} cameras have district_code=UNKNOWN -- G6 should resolve these")
    return 0 if reachable == len(seed) else 1


if __name__ == "__main__":
    sys.exit(main())
