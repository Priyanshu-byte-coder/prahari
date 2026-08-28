"""Unified stream gateway — relay, session control, protocol normalisation.

The upstream grid guards its HLS endpoints with a cookie check: the first
request is answered with a 302 to `?cookieCheck=1` plus a Set-Cookie marked
`SameSite=None; Partitioned`, and the redirect target is plain http. Media
players (ffmpeg, VLC) follow that within a session and never notice. A browser
making a cross-origin request cannot: the cookie is not attached, and the
https -> http downgrade on the redirect is refused.

So the gateway terminates the upstream session on the server side, keeps the
cookie jar warm, and re-publishes each feed on our own origin. This is the
"unified stream gateway" box in the architecture rather than a workaround: it
is also where per-camera access control, connection pooling and audit logging
belong when departmental feeds arrive over four different protocols.

Endpoints:
    GET /stream/{camera_id}/index.m3u8    rewritten playlist
    GET /stream/{camera_id}/seg/{name}    proxied media segment
"""
from __future__ import annotations

import re
import threading
import time
from urllib.parse import urljoin, urlparse

import requests
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

router = APIRouter()

UPSTREAM_BASE = "https://live.corp8.cloud"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Prahari/0.1 StreamGateway"

_lock = threading.Lock()
_session: requests.Session | None = None
_session_created = 0.0
SESSION_TTL = 600.0  # re-warm the cookie jar every 10 minutes

# Politeness limits against the sandbox grid.
#
# Every connected client receives its own copy of each stream, and the
# integration guide asks integrators to pace their load. This is not just
# etiquette: hammering the grid with low-latency part requests already earned
# an "authentication error" response once (CONTEXT.md), and being throttled or
# blocked during the evaluation window would be unrecoverable.
MAX_CONCURRENT_UPSTREAM = 12
MIN_REQUEST_INTERVAL = 0.02  # seconds between upstream requests, globally

_upstream_slots = threading.Semaphore(MAX_CONCURRENT_UPSTREAM)
_pace_lock = threading.Lock()
_last_request_at = 0.0


def _throttle() -> None:
    """Global minimum spacing between upstream requests."""
    global _last_request_at
    with _pace_lock:
        now = time.monotonic()
        wait = _last_request_at + MIN_REQUEST_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _last_request_at = now

# Playlist lines that carry a URI in an attribute rather than on their own line.
_ATTR_URI = re.compile(r'URI="([^"]+)"')

# Low-latency HLS tags. We deliberately strip these and serve plain HLS.
#
# Left in place, players negotiate LL-HLS and issue blocking part-requests
# (?_HLS_msn=&_HLS_part=) several times per second per camera. Across a wall of
# tiles that is hundreds of held-open requests through the gateway, and any
# player that cannot complete the part handshake never advances to a media
# segment at all. Trading ~800ms of latency for ~1/10th the request volume is
# the right call for a monitoring wall: the analytics path reads the stream
# server-side and is unaffected.
_LL_TAGS = (
    "#EXT-X-PART",
    "#EXT-X-PART-INF",
    "#EXT-X-PRELOAD-HINT",
    "#EXT-X-RENDITION-REPORT",
    "#EXT-X-SKIP",
)


def _rewrite_playlist(text: str, prefix: str) -> str:
    """Point every URI at our origin and drop the low-latency tags."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(_LL_TAGS):
            continue
        if stripped.startswith("#EXT-X-SERVER-CONTROL"):
            # Keep the tag but remove the blocking-reload advertisement.
            out.append("#EXT-X-SERVER-CONTROL:CAN-BLOCK-RELOAD=NO")
            continue
        if not stripped:
            out.append(line)
        elif stripped.startswith("#"):
            out.append(_ATTR_URI.sub(lambda m: f'URI="{prefix}{m.group(1)}"', line))
        else:
            out.append(prefix + stripped)
    return "\n".join(out) + "\n"


def _get_session() -> requests.Session:
    """One shared upstream session, holding the cookieCheck cookie."""
    global _session, _session_created
    with _lock:
        if _session is None or (time.time() - _session_created) > SESSION_TTL:
            session = requests.Session()
            session.headers.update({
                "User-Agent": UA,
                "Referer": f"{UPSTREAM_BASE}/",
                "Accept": "*/*",
            })
            _session = session
            _session_created = time.time()
        return _session


def _assert_consume_only(url: str) -> None:
    """Refuse anything that is not a read of a media path on the sandbox grid.

    The organisers' integration guide is explicit: consume only, never publish
    to the gateway, never call its control API. Breaching that is the clearest
    disqualification risk in the whole project, so it is enforced here in code
    rather than left as a rule somebody remembers. Every upstream request in
    Prahari funnels through this function.
    """
    parsed = urlparse(url)
    if parsed.netloc != urlparse(UPSTREAM_BASE).netloc:
        raise HTTPException(status_code=400, detail=f"refusing off-grid host {parsed.netloc}")

    allowed_prefixes = ("/live/", "/api/ingest")
    if not parsed.path.startswith(allowed_prefixes):
        raise HTTPException(
            status_code=403,
            detail=f"consume-only: {parsed.path} is not a permitted read path",
        )

    # MediaMTX exposes its control API under these; touching them is forbidden.
    forbidden = ("/v1/config", "/v2/config", "/v3/config", "/whip", "/publish")  # compliance-allow: enforcement
    if any(token in parsed.path for token in forbidden):
        detail = "consume-only: control or publish path refused"  # compliance-allow: enforcement
        raise HTTPException(status_code=403, detail=detail)


def _upstream_get(url: str, *, stream: bool = False) -> requests.Response:
    """Fetch from upstream, following the cookie-check redirect.

    The redirect target downgrades to http; we force it back to https so the
    hop stays encrypted, which a plain allow_redirects would not do.

    Only ever issues GET. There is no companion post/put/delete helper in this
    module, and that is deliberate.
    """
    _assert_consume_only(url)
    _throttle()
    session = _get_session()
    current = url
    if not _upstream_slots.acquire(timeout=20):
        raise HTTPException(status_code=503, detail="upstream connection budget exhausted")

    # A streamed response keeps the connection open past this function, so the
    # slot travels with it and the caller releases via release_slot(). Every
    # other exit path -- buffered response, redirect loop, exception -- must
    # give the slot back here, or the budget bleeds away to zero.
    slot_handed_off = False
    try:
        for _ in range(4):
            resp = session.get(current, allow_redirects=False, timeout=25, stream=stream)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    slot_handed_off = stream
                    return resp
                nxt = urljoin(current, location)
                parsed = urlparse(nxt)
                if parsed.scheme == "http" and parsed.netloc == urlparse(UPSTREAM_BASE).netloc:
                    nxt = parsed._replace(scheme="https").geturl()
                resp.close()
                current = nxt
                continue
            slot_handed_off = stream
            return resp
        raise HTTPException(status_code=502, detail="too many upstream redirects")
    finally:
        if not slot_handed_off:
            _upstream_slots.release()


def release_slot() -> None:
    """Give back a connection slot handed off with a streamed response."""
    _upstream_slots.release()


def _playlist_url(camera_id: str) -> str:
    return f"{UPSTREAM_BASE}/live/stream/{camera_id}/index.m3u8"


@router.get("/stream/{camera_id}/index.m3u8")
def playlist(camera_id: str) -> Response:
    """Fetch the upstream playlist and rewrite every URI onto our origin."""
    url = _playlist_url(camera_id)
    try:
        resp = _upstream_get(url)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"upstream: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="camera requires upstream credentials")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"upstream {resp.status_code}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="upstream refused playlist")

    return Response(
        content=_rewrite_playlist(resp.text, f"/stream/{camera_id}/seg/"),
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/stream/{camera_id}/seg/{name:path}")
def segment(camera_id: str, name: str) -> StreamingResponse:
    """Relay one media segment. Streamed, never buffered whole."""
    # A nested playlist (variant) must be rewritten too, not passed through.
    if name.endswith(".m3u8"):
        base = f"{UPSTREAM_BASE}/live/stream/{camera_id}/"
        try:
            resp = _upstream_get(urljoin(base, name))
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"upstream: {exc}")
        body = _rewrite_playlist(resp.text, f"/stream/{camera_id}/seg/")
        return StreamingResponse(
            iter([body.encode()]),
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        )

    url = f"{UPSTREAM_BASE}/live/stream/{camera_id}/{name}"
    try:
        resp = _upstream_get(url, stream=True)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"upstream: {exc}")

    if resp.status_code != 200:
        resp.close()
        release_slot()
        raise HTTPException(status_code=502, detail=f"segment upstream {resp.status_code}")

    media_type = resp.headers.get("content-type", "video/mp4")

    def body():
        try:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            resp.close()
            release_slot()

    return StreamingResponse(
        body(),
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
    )
