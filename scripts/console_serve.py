"""Prahari console server — map, live wall, and the camera API behind them.

    python scripts/console_serve.py
    open http://localhost:5173/web/console.html

Endpoints:
    GET  /api/cameras            merged seed + geo + wall status
    GET  /api/wall               wall state (per-camera status, ages)
    POST /api/wall/start         {"ids": [...]} or {} for all
    POST /api/wall/stop          same shape
    GET  /tile/<id>.jpg          cached frame, served instantly
    GET  /grid/<path>            proxy past the Cloudflare gate
    GET  /web/...                static files

Why tiles come from a server-side cache rather than a <video> per camera:
the grid's cookie is Partitioned with ACAO:*, which a browser page cannot
use, and even proxied same-origin its low-latency fMP4 will not paint in
hls.js. PyAV decodes it fine, so the frames are pulled here (services/
gateway/wall.py) and the page just shows images.
"""
from __future__ import annotations

import argparse
import http.server
import io
import json
import socketserver
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.gateway.wall import Wall  # noqa: E402
from services.gateway.probe import safe_url  # noqa: E402

GRID_BASE = "https://live.corp8.cloud"
SEED = ROOT / "data" / "cameras.seed.json"
GEO = ROOT / "data" / "camera_geo.json"

_SESSION = requests.Session()
CHUNK = 64 * 1024
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
              "content-encoding", "content-length"}

WALL: Wall | None = None


def load_cameras() -> list[dict]:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    geo = json.loads(GEO.read_text(encoding="utf-8")) if GEO.exists() else {}
    for cam in seed:
        cam["geo"] = geo.get(str(cam["camera_id"]), {})
    return seed


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):
        pass  # the wall is chatty enough

    # -- helpers ---------------------------------------------------------

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    # -- routes ----------------------------------------------------------

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/wall/start":
            self._json(WALL.start(self._body().get("ids")))
        elif path == "/api/wall/stop":
            self._json(WALL.stop(self._body().get("ids")))
        else:
            self.send_error(404)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/cameras":
            return self._json(load_cameras())
        if path == "/api/wall":
            return self._json(WALL.state())
        if path.startswith("/tile/"):
            return self._tile(path)
        if path.startswith("/grid/"):
            return self._proxy(path)
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/web/console.html")
            self.end_headers()
            return
        return super().do_GET()

    def _tile(self, path: str):
        cam_id = path[len("/tile/"):].removesuffix(".jpg")
        data = WALL.jpeg(cam_id) if WALL else None
        if not data:
            # 204: the page keeps its placeholder instead of showing a broken
            # image while a camera is still connecting.
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, path: str):
        target = safe_url(urljoin(GRID_BASE + "/", path[len("/grid/"):]))
        if target is None:
            self.send_error(400, "proxy target not on allowed host")
            return
        try:
            upstream = _SESSION.get(target, stream=True, timeout=20, allow_redirects=True)
        except requests.RequestException as exc:
            return self.send_error(502, f"grid unreachable: {type(exc).__name__}")
        self.send_response(upstream.status_code)
        for k, v in upstream.headers.items():
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for chunk in upstream.iter_content(CHUNK):
                if chunk:
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    global WALL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5173)
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between cached frames per camera")
    ap.add_argument("--autostart", action="store_true",
                    help="begin pulling every camera immediately")
    args = ap.parse_args()

    cameras = load_cameras()
    WALL = Wall(cameras, interval=args.interval)
    print(f"cameras with an HLS url: {len(WALL.feeds)}/{len(cameras)}")
    if args.autostart:
        WALL.start()
        print("wall: starting all pullers")

    with Server(("127.0.0.1", args.port), Handler) as httpd:
        print(f"console  http://localhost:{args.port}/web/console.html")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            WALL.stop()
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
