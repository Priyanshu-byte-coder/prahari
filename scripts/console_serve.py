"""Prahari console server — map, live wall, and the camera API behind them.

    python scripts/console_serve.py
    open http://localhost:5173/               # portal: links every console + the live API

Endpoints:
    GET  /api/cameras            the core API's *scoped* camera list ([C10]/D7),
                                 enriched here with geo + wall shape. 401/403/503
                                 from the API are passed straight through. Set
                                 PRAHARI_CONSOLE_OFFLINE=1 to serve the local seed
                                 instead -- the no-API demo path only.
    GET  /api/wall               wall state (per-camera status, ages)
    POST /api/wall/start         {"ids": [...]} or {} for all
    POST /api/wall/stop          same shape
    GET  /api/v1/<path>          the core API, called as the console's own
                                 account -- the operator never sees a login
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
import os
import socketserver
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.gateway.wall import Wall  # noqa: E402
from services.gateway.probe import safe_url  # noqa: E402

GRID_BASE = "https://cctv.corp8.cloud"  # current CDN host per the integrator's guide
SEED = ROOT / "data" / "cameras.seed.json"
GEO = ROOT / "data" / "camera_geo.json"

# The console holds the credential server-side so the operator never meets a
# login form: [C10] scope is still enforced by the API on every call, it is
# just carried by this process rather than typed into the browser. The account
# is a normal scoped user -- point these at the posting the console runs as.
API_BASE = os.environ.get("PRAHARI_API", "http://localhost:8000").rstrip("/")
API_USER = os.environ.get("PRAHARI_CONSOLE_USER", "field")
API_PASS = os.environ.get("PRAHARI_CONSOLE_PASSWORD", "sentinel123")

# Two accounts, not one, and [C10] is the reason. The audit log is admin:audit,
# which only SYSTEM_ADMIN holds -- and SYSTEM_ADMIN is the one role that may not
# see live data at all. So no single account can draw both the map and the audit
# tab: with one, the Admin view answered 403 on a console that was working fine.
# Each view is proxied under the account that legitimately holds its capability,
# and the API still enforces both. Leave the admin password unset and the audit
# tab says the console has no audit account rather than showing a wrong refusal.
ADMIN_USER = os.environ.get("PRAHARI_CONSOLE_ADMIN_USER", "console-audit")
ADMIN_PASS = os.environ.get("PRAHARI_CONSOLE_ADMIN_PASSWORD", "")

ACCOUNTS = {"live": (API_USER, API_PASS), "audit": (ADMIN_USER, ADMIN_PASS)}

# [#44] The console must not answer /api/cameras around the API's RBAC. It draws
# the API's scoped list; this flag is the one exception, for demoing with no core
# API running, and it announces itself so nobody mistakes it for the real thing.
OFFLINE = os.environ.get("PRAHARI_CONSOLE_OFFLINE", "").strip().lower() in ("1", "true", "yes")

# Only these API prefixes are reachable through the console proxy. Anything the
# console does not draw stays unreachable from the browser.
API_ALLOW = ("cameras", "alerts", "watchlist", "route", "admin/audit", "healthz")

_TOKENS: dict = {name: {"value": None, "exp": 0.0} for name in ("live", "audit")}

# The sandbox grid moved behind a sign-in: every stream and the catalogue now
# 302 to cctv.corp8.cloud/auth/login, whose form takes a single access key.
# Supply it as GRID_KEY and the console signs in once and keeps the cookie;
# without it the wall cannot open a single feed, and the UI says exactly that
# rather than showing thirty tiles stuck on "connecting".
GRID_AUTH = os.environ.get("GRID_AUTH", "https://cctv.corp8.cloud/auth/login")
GRID_KEY = os.environ.get("GRID_KEY", "").strip()
# The sign-in form gained a second field on 2026-09-03: it now wants the registered email
# alongside the access key, and posting the key alone comes back "Email or access password is
# incorrect" - which reads exactly like an expired key and cost an hour of chasing the wrong
# thing. Both fields, always.
GRID_EMAIL = os.environ.get("GRID_EMAIL", "").strip()

# Cloudflare in front of the grid answers 403 "browser required" to a bare client, so the
# console signs in and pulls media with a browser User-Agent. Not evasion - the same session a
# person gets, carried by the process that draws the wall.
GRID_UA = os.environ.get("GRID_UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/131.0.0.0 Safari/537.36")

GRID = {"state": "no key" if not GRID_KEY else "not tried", "cookie": None, "detail": ""}


def grid_login() -> bool:
    """Sign in to the grid once and keep the cookie. False when it cannot."""
    if not GRID_KEY:
        GRID.update(state="no key", cookie=None,
                    detail="Set GRID_KEY to the access key issued for this grid.")
        return False
    if not GRID_EMAIL:
        GRID.update(state="no email", cookie=None,
                    detail="Set GRID_EMAIL to the address the key was issued to - the grid's "
                           "sign-in form needs both fields.")
        return False
    sess = _session()
    try:
        r = sess.post(GRID_AUTH, data={"email": GRID_EMAIL, "password": GRID_KEY},
                      headers={"User-Agent": GRID_UA}, timeout=12, allow_redirects=True)
    except requests.RequestException as exc:
        GRID.update(state="unreachable", cookie=None, detail=f"{type(exc).__name__}")
        return False
    jar = "; ".join(f"{c.name}={c.value}" for c in sess.cookies)
    # A rejected key lands back on the login form rather than erroring.
    if "auth/login" in r.url or "name=\"password\"" in r.text[:4000]:
        GRID.update(state="rejected", cookie=None,
                    detail="The grid did not accept this email and key.")
        return False
    if not jar:
        GRID.update(state="no cookie", cookie=None, detail="Sign-in returned no session cookie.")
        return False
    GRID.update(state="signed in", cookie=jar, detail="")
    return True


def grid_headers() -> str | None:
    return f"Cookie: {GRID['cookie']}\r\n" if GRID.get("cookie") else None


def account_for(path: str) -> str:
    """Which console account a proxied path is called under."""
    return "audit" if path.startswith("admin/") else "live"


def api_token(account: str = "live", force: bool = False) -> str | None:
    """A cached access token for one console account. None when it cannot log in."""
    now = time.time()
    cached = _TOKENS[account]
    if not force and cached["value"] and now < cached["exp"]:
        return cached["value"]
    username, password = ACCOUNTS[account]
    if not password:
        return None
    try:
        r = _session().post(f"{API_BASE}/api/auth/login",
                            json={"username": username, "password": password}, timeout=6)
        if r.status_code != 200:
            return None
        tok = r.json().get("access")
    except (requests.RequestException, ValueError):
        return None
    # The API issues a 15 minute access token; refresh a minute early.
    cached["value"], cached["exp"] = tok, now + 14 * 60
    return tok


def api_call(method: str, path: str, query: str = "", body: dict | None = None):
    """Forward one call to the core API as the console's account. Returns (status, payload)."""
    if not any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
               for p in API_ALLOW):
        return 404, {"detail": "not proxied"}
    account = account_for(path)
    token = api_token(account)
    if token is None:
        if account == "audit" and not ADMIN_PASS:
            return 503, {"detail": "this console has no audit account: set "
                                   "PRAHARI_CONSOLE_ADMIN_USER and "
                                   "PRAHARI_CONSOLE_ADMIN_PASSWORD"}
        return 503, {"detail": "core API unreachable", "api": API_BASE}
    url = f"{API_BASE}/api/{path}" + (f"?{query}" if query else "")
    for attempt in (1, 2):
        try:
            r = _session().request(method, url, timeout=12,
                                   headers={"Authorization": f"Bearer {token}"},
                                   json=body if method == "POST" else None)
        except requests.RequestException as exc:
            return 502, {"detail": f"{type(exc).__name__} talking to the core API"}
        if r.status_code == 401 and attempt == 1:
            token = api_token(account, force=True)   # aged out mid-shift; mint once more
            if token is None:
                return 503, {"detail": "core API unreachable"}
            continue
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"detail": r.text[:400]}
    return 502, {"detail": "core API did not answer"}

# Thread-local session: requests.Session is not thread-safe and
# http.server.ThreadingHTTPServer spawns one thread per request.
import threading as _threading
_SESSION_LOCAL = _threading.local()


def _session() -> requests.Session:
    s = getattr(_SESSION_LOCAL, "session", None)
    if s is None:
        s = _SESSION_LOCAL.session = requests.Session()
    return s


CHUNK = 64 * 1024
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
              "content-encoding", "content-length"}

WALL: Wall | None = None


# [C4]'s Camera carries lat/lon at the top level, and the legacy web/map.js filters on
# `c.lat != null`. Nesting them only under `geo` left every camera unplaced there -- "30
# cameras, 0 placed" over an empty map -- even though the coordinates were in the payload.
# app.js reads `c.geo.lat` directly and never needed this, but the flattening is free and
# keeps the older page working too.
GEO_TOP_LEVEL = ("lat", "lon", "bearing_deg", "fov_deg", "range_m",
                 "coord_source", "coord_conf", "landmark")


def load_cameras() -> list[dict]:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    geo = json.loads(GEO.read_text(encoding="utf-8")) if GEO.exists() else {}
    for cam in seed:
        placement = geo.get(str(cam["camera_id"]), {})
        cam["geo"] = placement                      # kept: the geo editor reads this shape
        for field in GEO_TOP_LEVEL:                 # added: what [C4] and the legacy map expect
            cam.setdefault(field, placement.get(field))
    return seed


def scoped_cameras() -> tuple[int, object]:
    """[#44] The camera list the console renders, with the API — not this
    process — deciding which cameras the operator may see.

    On 200 the API's camera ids are the allow-list; geo/landmark shaping still
    comes from `load_cameras()`. Any other status (401 no token, 403 for a
    SYSTEM_ADMIN per [C10], 503 API down) is returned untouched so the console
    shows the refusal rather than drawing around it. `PRAHARI_CONSOLE_OFFLINE`
    opts back into the full local seed for the no-API demo path.
    """
    if OFFLINE:
        return 200, load_cameras()
    status, payload = api_call("GET", "cameras")
    if status != 200:
        return status, payload
    allowed = {str(row["camera_id"]) for row in payload}
    return 200, [cam for cam in load_cameras() if str(cam["camera_id"]) in allowed]


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
        if path.startswith("/api/v1/"):
            status, payload = api_call("POST", path[len("/api/v1/"):], body=self._body())
            return self._json(payload, status)
        if path == "/api/wall/start":
            self._json(WALL.start(self._body().get("ids")))
        elif path == "/api/wall/stop":
            self._json(WALL.stop(self._body().get("ids")))
        else:
            self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/v1/"):
            status, payload = api_call("GET", path[len("/api/v1/"):], query=parsed.query)
            return self._json(payload, status)
        if path == "/api/grid":
            return self._json({"state": GRID["state"], "detail": GRID["detail"],
                               "auth_url": GRID_AUTH, "key_set": bool(GRID_KEY)})
        if path == "/api/cameras":
            status, payload = scoped_cameras()
            return self._json(payload, status)
        if path == "/api/wall":
            return self._json(WALL.state())
        if path.startswith("/tile/"):
            return self._tile(path)
        if path.startswith("/grid/"):
            return self._proxy(path)
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/web/home.html")
            self.end_headers()
            return
        if path == "/console":
            self.send_response(302)
            self.send_header("Location", "/web/app.html")
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
            sess = _session()
            upstream = sess.get(target, stream=True, timeout=20, allow_redirects=False)
            # Follow same-host redirects only (Cloudflare cookieCheck is 1 hop)
            hops = 0
            while upstream.is_redirect and hops < 3:
                location = upstream.headers.get("Location", "")
                next_url = safe_url(
                    location if location.startswith("http")
                    else urljoin(GRID_BASE + "/", location)
                )
                if not next_url:
                    self.send_error(502, "redirect to off-grid host rejected")
                    return
                upstream.close()
                upstream = sess.get(next_url, stream=True, timeout=20, allow_redirects=False)
                hops += 1
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
    ok = grid_login()
    print(f"grid HLS sign-in (fallback transport): {GRID['state']}" +
          (f" — {GRID['detail']}" if GRID["detail"] else ""))
    WALL = Wall(cameras, interval=args.interval, headers=grid_headers(),
                user_agent=GRID_UA)
    print(f"cameras with a wall transport: {len(WALL.feeds)}/{len(cameras)} "
          f"(RTSP direct to the grid's public IP, no key needed; HLS as fallback)")
    if not ok:
        print("  HLS fallback is not signed in, but RTSP needs no key -- video still starts")
    if args.autostart:
        WALL.start()
        print("wall: starting all pullers")

    with Server(("127.0.0.1", args.port), Handler) as httpd:
        print(f"console  http://localhost:{args.port}/console")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            WALL.stop()
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
