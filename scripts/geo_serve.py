"""[G6] Serve the repo and proxy the grid, so HLS actually plays in a browser.

    python scripts/geo_serve.py          # then open http://localhost:5173/web/geo_helper.html

Why a proxy is necessary, not a convenience:

The grid gates every stream behind Cloudflare. The first request 302s to
`?cookieCheck=1` and sets `cookieCheck=1; Secure; SameSite=None; Partitioned`.
A browser page on another origin cannot use that cookie: sending it needs
`credentials:'include'`, and the grid answers `Access-Control-Allow-Origin: *`,
which the browser rejects for credentialed requests. So `fetch()` and hls.js
both fail with a bare "Failed to fetch" even though curl works fine.

Proxying moves the cookie handling server-side, where there is no CORS and no
partitioning: one `requests.Session` negotiates the gate once and every
segment rides the same cookie jar.

**This applies to G11's video wall too.** Any browser-side player pointed
straight at the grid will hit this. The console needs the same proxy path.
"""
from __future__ import annotations

import argparse
import http.server
import io
import socketserver
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.gateway.probe import safe_url  # noqa: E402

GRID_BASE = "https://live.corp8.cloud"
PREFIX = "/grid/"
SNAPSHOT_PREFIX = "/snapshot/"

_SESSION = requests.Session()

# Streamed straight through; playlists are tiny, segments are a few hundred KB.
CHUNK = 64 * 1024
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-encoding", "content-length"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):  # quieter: one line per proxied miss only
        if "grid" in (self.path or "") and "200" not in (args[1] if len(args) > 1 else ""):
            sys.stderr.write(f"{self.path} -> {args[1] if len(args) > 1 else '?'}\n")

    def do_GET(self):
        if self.path.startswith(SNAPSHOT_PREFIX):
            return self._snapshot()
        if self.path.startswith(PREFIX):
            return self._proxy()
        return super().do_GET()

    def _snapshot(self):
        """One decoded frame as JPEG.

        Browser-side HLS playback of this grid does not work: the streams are
        low-latency fMP4 (EXT-X-PART-INF, EXT-X-MAP) and the vendored hls.js
        never paints a frame, even with the playlist proxied same-origin. PyAV
        decodes them without complaint, so the frame is grabbed server-side.
        A still is all G6 needs -- you are matching a landmark, not watching.
        """
        # Strip the cache-buster query before parsing: "/snapshot/1.jpg?t=123"
        # must still resolve to camera 1.
        path = self.path.split("?", 1)[0]
        cam_id = path[len(SNAPSHOT_PREFIX):].removesuffix(".jpg")
        if not cam_id.isdigit():
            self.send_error(400, "camera id must be numeric")
            return
        try:
            import av
            from PIL import Image
        except ImportError:
            self.send_error(501, "pip install av pillow")
            return

        url = f"{GRID_BASE}/live/stream/{cam_id}/index.m3u8"
        try:
            container = av.open(url, timeout=20)
            try:
                frame = next(container.decode(video=0))
                img = Image.fromarray(frame.to_ndarray(format="rgb24"))
            finally:
                container.close()
        except Exception as exc:  # unreachable camera is normal here
            self.send_error(502, f"{type(exc).__name__}: {exc}")
            return

        img.thumbnail((960, 960))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        data = buf.getvalue()

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self):
        target = safe_url(urljoin(GRID_BASE + "/", self.path[len(PREFIX):]))
        if target is None:
            self.send_error(400, "proxy target not on allowed host")
            return
        try:
            upstream = _SESSION.get(target, stream=True, timeout=20, allow_redirects=False)
            # Follow same-host redirects only (Cloudflare cookieCheck is 1 hop)
            hops = 0
            while upstream.is_redirect and hops < 3:
                location = upstream.headers.get("Location", "")
                next_url = safe_url(
                    location if location.startswith("http") else urljoin(GRID_BASE + "/", location)
                )
                if not next_url:
                    self.send_error(502, "redirect to off-grid host rejected")
                    return
                upstream.close()
                upstream = _SESSION.get(next_url, stream=True, timeout=20, allow_redirects=False)
                hops += 1
        except requests.RequestException as exc:
            self.send_error(502, f"grid unreachable: {type(exc).__name__}")
            return

        self.send_response(upstream.status_code)
        for k, v in upstream.headers.items():
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        # Same-origin from the page's point of view, but be explicit.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for chunk in upstream.iter_content(CHUNK):
                if chunk:
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the player seeked or closed the tab; normal
        finally:
            upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5173)
    args = ap.parse_args()
    with Server(("127.0.0.1", args.port), Handler) as httpd:
        print(f"repo   http://localhost:{args.port}/web/geo_helper.html")
        print(f"grid   http://localhost:{args.port}{PREFIX}... -> {GRID_BASE}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
