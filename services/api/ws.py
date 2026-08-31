"""`/ws` - one socket per console, every push the console will ever need ([C5], ticket D5).

This ticket exists to kill polling. A console that polls at 800 ms shows an alert up to 800 ms
late, asks for everything to get the one thing that changed, and does that once per operator per
second for the whole demo. One socket, server-pushed, is both faster and quieter.

Three rules the design turns on:

  * **the server filters, never the client.** Scope is computed once, at connect, from the JWT.
    A console that receives frames it must not show and hides them in JavaScript has already
    leaked them - the frames were on the wire, and the browser devtools show them.
  * **seq is monotonic and survives a reconnect.** Every frame gets the next number from one
    counter, and the last few thousand stay in a ring buffer. A console that drops off a train's
    wifi reconnects with {"type":"resume","since":N} and gets exactly what it missed, filtered
    through its own scope again. Without that, a reconnect is a blank panel.
  * **heartbeat every 15 s.** A dead TCP connection looks exactly like a quiet one, and "quiet"
    is the normal state of a camera grid at 3 a.m.

Fanout reads the Redis streams with XREAD rather than the `ws-fanout` consumer group named in
[C2]. A consumer group splits messages between its members: with two API replicas, half the
alerts would reach half the consoles. Broadcast is the requirement, so every process reads the
whole stream. Logged as a decision in knowledge_base.md.
"""

import asyncio
import json
import logging
import os
import secrets
import time
from collections import deque
from dataclasses import dataclass, field

import jwt
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

log = logging.getLogger("ws")

HEARTBEAT_S = 15
BUFFER_FRAMES = 5000            # a few minutes of a busy grid; the resume window
BACKFILL_MAX = 500              # never dump the whole buffer into a fresh socket

# Redis stream -> [C5] frame type.
STREAMS = {
    "alerts": "alert.new",
    "camera.health": "camera.health",
    "sightings": "sighting",
}

CLOSE_UNAUTHORISED = 4401       # application close code: the first frame was not a valid token

ALL_DEPARTMENTS = {"INVESTIGATOR", "SYSTEM_ADMIN"}   # [C10]: statewide roles
NO_LIVE_DATA = {"SYSTEM_ADMIN"}                      # config and audit only


def _secret():
    """JWT signing key. Falling back to a process-local random key is deliberate.

    D7 issues real tokens. Until then an unset JWT_SECRET must not mean "accept anything" - a
    socket that trusts an unsigned token is an open door to every camera in the state. A random
    per-process key means only tokens this process issued work, which is what a dev run needs.
    """
    configured = os.environ.get("JWT_SECRET")
    if configured:
        return configured
    if not hasattr(_secret, "_dev"):
        _secret._dev = secrets.token_urlsafe(32)
        log.warning("JWT_SECRET is unset - using a random per-process key (dev only)")
    return _secret._dev


def issue_token(user_id, role, dept_id=None, district_code=None, ttl_s=900):
    """Mint a token. D7 replaces this with the real login flow; the shape stays."""
    return jwt.encode({"sub": str(user_id), "role": role, "dept_id": dept_id,
                       "district_code": district_code, "exp": int(time.time()) + ttl_s},
                      _secret(), algorithm="HS256")


@dataclass
class Scope:
    user_id: str
    role: str
    dept_id: int = None
    district_code: str = None

    @classmethod
    def from_token(cls, token):
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
        return cls(user_id=claims.get("sub"), role=(claims.get("role") or "").upper(),
                   dept_id=claims.get("dept_id"), district_code=claims.get("district_code"))

    def allows(self, camera_dept_id, camera_district):
        """[C10], in the only place it can be enforced: before the frame reaches the wire."""
        if self.role in NO_LIVE_DATA:
            return False
        if self.role in ALL_DEPARTMENTS:
            return True
        if self.dept_id is not None and camera_dept_id is not None:
            return self.dept_id == camera_dept_id
        # A camera with no department yet (G1 seeds before D7 assigns them) falls back to the
        # district. Neither known: withhold. Showing it and apologising later is not an option.
        if self.district_code and camera_district:
            return self.district_code == camera_district
        return False


@dataclass(eq=False)                    # identity, not value: subscribers live in a set
class Subscriber:
    scope: Scope
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))
    dropped: int = 0

    def offer(self, frame):
        """Never block the fanout on one slow console."""
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            self.dropped += 1


class Hub:
    """Reads the Redis streams once and hands each frame to every socket allowed to see it."""

    def __init__(self, store, streams=None, buffer_frames=BUFFER_FRAMES):
        self.store = store
        self.streams = streams or dict(STREAMS)
        self.subscribers = set()
        self.buffer = deque(maxlen=buffer_frames)
        self.seq = 0
        self.cameras = {}                      # camera_id -> (dept_id, district_code)
        self._task = None
        self._stop = asyncio.Event()

    # -- camera scope table ---------------------------------------------------------------

    def load_cameras(self):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("SELECT camera_id, owner_dept_id, district_code FROM cameras")
            self.cameras = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        return self.cameras

    def _visible_to(self, subscriber, frame):
        camera_id = (frame.get("data") or {}).get("camera_id")
        if camera_id is None:
            return True                        # not camera-bound: nothing to scope it by
        dept, district = self.cameras.get(camera_id, (None, None))
        return subscriber.scope.allows(dept, district)

    # -- fanout ---------------------------------------------------------------------------

    def publish(self, kind, data):
        """Number a frame, buffer it, and offer it to everyone whose scope allows it."""
        self.seq += 1
        frame = {"type": kind, "seq": self.seq, "data": data}
        self.buffer.append(frame)
        for subscriber in list(self.subscribers):
            if self._visible_to(subscriber, frame):
                subscriber.offer(frame)
        return frame

    def backfill(self, subscriber, since, limit=BACKFILL_MAX):
        """The frames this socket missed, in order, filtered through its own scope again."""
        missed = [f for f in self.buffer
                  if f["seq"] > since and self._visible_to(subscriber, f)]
        return missed[-limit:]

    def subscribe(self, scope):
        subscriber = Subscriber(scope=scope)
        self.subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        self.subscribers.discard(subscriber)

    # -- redis loop -------------------------------------------------------------------------

    async def run(self, poll_ms=250):
        """XREAD every stream from now on. One reader, however many sockets."""
        import redis.asyncio as aioredis
        client = aioredis.Redis.from_url(self.store.redis_url, decode_responses=True)
        cursors = {name: "$" for name in self.streams}
        try:
            while not self._stop.is_set():
                response = await client.xread(cursors, count=200, block=poll_ms)
                for stream, entries in response or []:
                    for msg_id, fields in entries:
                        cursors[stream] = msg_id
                        try:
                            data = json.loads(fields.get("data", "{}"))
                        except ValueError:
                            log.warning("%s carried a non-JSON payload at %s", stream, msg_id)
                            continue
                        self.publish(self.streams[stream], data)
        finally:
            await client.aclose()

    def start(self):
        self._stop.clear()
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass                               # cancelling is how we stop it


async def _pump(websocket, subscriber):
    """Drain the queue to the socket, with a heartbeat when it is quiet."""
    while True:
        try:
            frame = await asyncio.wait_for(subscriber.queue.get(), timeout=HEARTBEAT_S)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "ping"})
            continue
        await websocket.send_json(frame)


def create_app(store=None, hub=None):
    from store import Store

    resolved_store = store or Store()
    resolved_hub = hub or Hub(resolved_store)

    @asynccontextmanager
    async def lifespan(app):
        app.state.hub.load_cameras()
        app.state.hub.start()
        yield
        await app.state.hub.stop()

    app = FastAPI(title="prahari ws", lifespan=lifespan)
    app.state.store = resolved_store
    app.state.hub = resolved_hub

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        hub = app.state.hub
        try:
            first = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        except (asyncio.TimeoutError, ValueError):
            await websocket.close(code=CLOSE_UNAUTHORISED)
            return

        try:
            scope = Scope.from_token(first["token"])       # [C5]: token first, always
        except (KeyError, TypeError, jwt.PyJWTError) as exc:
            log.info("socket rejected: %s", exc)
            await websocket.close(code=CLOSE_UNAUTHORISED)
            return

        subscriber = hub.subscribe(scope)
        await websocket.send_json({"type": "ready", "seq": hub.seq,
                                   "data": {"role": scope.role, "dept_id": scope.dept_id}})
        pump = asyncio.create_task(_pump(websocket, subscriber))
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "resume":
                    for frame in hub.backfill(subscriber, int(message.get("since", 0))):
                        await websocket.send_json(frame)
        except (WebSocketDisconnect, ValueError, RuntimeError):
            pass
        finally:
            pump.cancel()
            hub.unsubscribe(subscriber)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "sockets": len(app.state.hub.subscribers), "seq": app.state.hub.seq}

    return app
