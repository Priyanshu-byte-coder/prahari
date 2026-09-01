"""[G2] Transport probe: decide how each camera is actually reachable.

Order is RTSP/TCP first, HLS second (plan A3). RTSP is preferred because it
gives real PTS and sub-second latency; HLS is the fallback that keeps a
camera usable when 8554 is filtered -- which on this grid it is, for all 30.

The winner is published to `camera:transport:<id>` [C2] as
`{url, transport, driver, probed_at}`. That key is the entire G->I seam.

Re-probe every REPROBE_INTERVAL_S so a network that gets fixed upgrades
itself back to RTSP without anyone restarting anything.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

RTSP_CONNECT_TIMEOUT_S = 2.0
HLS_TIMEOUT_S = 8.0
REPROBE_INTERVAL_S = 600  # 10 minutes

# The grid sits behind a Cloudflare cookie gate: the first request 302s to
# `?cookieCheck=1` with a Set-Cookie and only then serves. One Session so
# that cookie is negotiated once rather than per camera.
#
# Thread safety: requests.Session is NOT thread-safe. selftest.py probes
# cameras in a ThreadPoolExecutor, so we use thread-local storage so each
# worker thread gets its own Session (and its own cookie negotiation).
import threading as _threading
_SESSION_LOCAL = _threading.local()


def _session() -> requests.Session:
    """Return the Session for the current thread, creating it if needed."""
    s = getattr(_SESSION_LOCAL, "session", None)
    if s is None:
        s = _SESSION_LOCAL.session = requests.Session()
    return s

ALLOWED_SCHEMES = frozenset({"http", "https"})


def allowed_hosts() -> frozenset[str]:
    """The only hosts this process will ever make a request to.

    Camera URLs arrive from the grid catalogue, which is data we do not
    control: a tampered or mistaken record could point a probe at an internal
    address (a metadata endpoint, an admin port). Pinning every request to the
    configured GRID_HOST keeps that from being reachable.
    """
    raw = os.environ.get("GRID_HOST", "live.corp8.cloud").strip()
    host = urlparse(raw if "//" in raw else f"//{raw}").hostname or raw
    return frozenset({host})


def safe_url(url: str | None) -> str | None:
    """Return the URL only if it is http(s) and on an allowed host."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return None
    if parsed.hostname not in allowed_hosts():
        return None
    return url


@dataclass(slots=True)
class TransportResult:
    """What we publish, plus the reason -- the reason is for the demo."""

    camera_id: str
    url: str | None
    transport: str | None  # rtsp | hls | None
    driver: str | None  # rtsp | mediamtx | None
    probed_at: float
    reason: str

    def redis_value(self) -> str:
        """Only the four fields [C2] promises; `reason` stays out of the seam."""
        return json.dumps(
            {
                "url": self.url,
                "transport": self.transport,
                "driver": self.driver,
                "probed_at": self.probed_at,
            }
        )


def probe_rtsp(url: str, timeout: float = RTSP_CONNECT_TIMEOUT_S) -> tuple[bool, str]:
    """Open the RTSP port, then send DESCRIBE. A listening port is not enough."""
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port or 554
    if not host:
        return False, "unparseable rtsp url"
    if host not in allowed_hosts():
        return False, f"rtsp host {host!r} not in allowed_hosts (SSRF guard)"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            request = (
                f"DESCRIBE {url} RTSP/1.0\r\n"
                "CSeq: 1\r\n"
                "Accept: application/sdp\r\n"
                "User-Agent: prahari-gateway\r\n\r\n"
            )
            sock.sendall(request.encode())
            reply = sock.recv(512).decode(errors="replace")
    except socket.timeout:
        return False, f"rtsp {port} timeout after {timeout}s (filtered)"
    except OSError as exc:
        return False, f"rtsp {port} unreachable: {exc.__class__.__name__}"

    first = reply.split("\r\n", 1)[0].strip()
    if not first.startswith("RTSP/"):
        return False, f"rtsp {port} open but no RTSP reply"
    # 200 OK, or 401/403 which still prove an RTSP server is there.
    code = first.split()[1] if len(first.split()) > 1 else "?"
    if code == "200":
        return True, "rtsp DESCRIBE 200"
    if code in ("401", "403"):
        return True, f"rtsp DESCRIBE {code} (auth required, server present)"
    return False, f"rtsp DESCRIBE {code}"


def probe_hls(url: str, timeout: float = HLS_TIMEOUT_S) -> tuple[bool, str]:
    """GET, never HEAD.

    HEAD against the cookie-gated path answers 404, not 405, so a HEAD probe
    reports every live camera as down. Read the first bytes and require a real
    `#EXTM3U` header rather than trusting a 200 that might be an error page.

    Redirects are followed only when they stay on the same allowed host
    (the Cloudflare cookieCheck 302 always does). Off-host redirects are
    rejected to prevent SSRF via a compromised upstream.
    """
    target = safe_url(url)
    if target is None:
        return False, "hls url rejected (scheme or host not allowed)"
    try:
        sess = _session()
        resp = sess.get(target, timeout=timeout, stream=True, allow_redirects=False)
        # Follow at most 3 same-host redirects (Cloudflare cookieCheck is 1 hop)
        hops = 0
        while resp.is_redirect and hops < 3:
            location = resp.headers.get("Location", "")
            next_url = safe_url(location if location.startswith("http") else
                                urlparse(target)._replace(path=location).geturl())
            if not next_url:
                return False, "hls redirect to off-host URL rejected"
            resp.close()
            resp = sess.get(next_url, timeout=timeout, stream=True, allow_redirects=False)
            hops += 1
        if resp.status_code >= 400:
            return False, f"hls HTTP {resp.status_code}"
        head = next(resp.iter_content(chunk_size=64), b"") or b""
        resp.close()
        if head.lstrip().startswith(b"#EXTM3U"):
            return True, "hls playlist served"
        return False, "hls 200 but not a playlist"
    except requests.RequestException as exc:
        return False, f"hls {exc.__class__.__name__}"


def resolve_transport(camera: dict) -> TransportResult:
    """RTSP first, HLS second. Records why, not just what."""
    camera_id = str(camera.get("camera_id") or camera.get("id") or "?")
    transports = camera.get("transports") or {}
    reasons: list[str] = []

    rtsp_url = transports.get("rtsp")
    if rtsp_url:
        ok, why = probe_rtsp(rtsp_url)
        reasons.append(why)
        if ok:
            return TransportResult(camera_id, rtsp_url, "rtsp", "rtsp", time.time(), why)
    else:
        reasons.append("no rtsp url")

    hls_url = transports.get("hls")
    if hls_url:
        ok, why = probe_hls(hls_url)
        reasons.append(why)
        if ok:
            # Carry the RTSP failure too: "came in on HLS *because* RTSP was
            # blocked" is the demo sentence, and half of it lives in reasons[0].
            return TransportResult(
                camera_id, hls_url, "hls", "mediamtx", time.time(), "; ".join(reasons)
            )
    else:
        reasons.append("no hls url")

    return TransportResult(camera_id, None, None, None, time.time(), "; ".join(reasons))


def publish(result: TransportResult, redis_client) -> None:
    """Write the G->I seam key. No TTL: the worker must find it after a restart."""
    redis_client.set(f"camera:transport:{result.camera_id}", result.redis_value())


async def reprobe_forever(cameras: list[dict], redis_client, interval: float = REPROBE_INTERVAL_S):
    """Re-probe on a loop so a fixed network upgrades itself back to RTSP."""
    while True:
        for camera in cameras:
            result = await asyncio.to_thread(resolve_transport, camera)
            if redis_client is not None:
                publish(result, redis_client)
        await asyncio.sleep(interval)
