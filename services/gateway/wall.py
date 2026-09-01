"""[G11-prep] Background frame pullers — the thing that makes a live wall possible.

A wall cannot open a stream per request: this grid takes 2-18 s to open one,
so a 30-tile page would take minutes to paint. Instead a small pool of worker
threads holds the streams open and keeps one recent JPEG per camera in memory;
the HTTP layer then serves a tile in microseconds.

Two decisions that keep this from melting a laptop:

**Only keyframes are decoded.** `container.demux()` hands us every packet, but
we skip straight past anything that is not a keyframe. HLS segments here are
~2 s with a keyframe at the head, so this decodes ~0.5 fps per camera instead
of 30 -- roughly a 60x saving -- and a wall of stills does not need more.

**Failure is per camera and never fatal.** A camera that will not open backs
off and retries; the other 29 tiles carry on. `state()` reports what each
worker is actually doing, so the UI can say "connecting" rather than lie.
"""
from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field

try:
    import av
    from PIL import Image
except ImportError:  # pragma: no cover - the server reports this cleanly
    av = None
    Image = None

OPEN_TIMEOUT_S = 25
JPEG_QUALITY = 78
THUMB = (640, 640)
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
STALE_AFTER_S = 90.0


@dataclass
class CameraFeed:
    camera_id: str
    url: str
    jpeg: bytes | None = None
    updated_at: float | None = None
    frames: int = 0
    status: str = "idle"        # idle | connecting | live | retrying | stopped
    detail: str = ""
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def age(self) -> float | None:
        return None if self.updated_at is None else time.time() - self.updated_at

    def snapshot(self) -> dict:
        age = self.age()
        return {
            "camera_id": self.camera_id,
            "status": self.status,
            "detail": self.detail,
            "frames": self.frames,
            "age_s": round(age, 1) if age is not None else None,
            "stale": age is not None and age > STALE_AFTER_S,
            "has_frame": self.jpeg is not None,
        }


class Wall:
    """Owns one puller thread per camera. Start and stop are idempotent."""

    def __init__(self, cameras: list[dict], interval: float = 2.0):
        self.interval = interval
        self.feeds: dict[str, CameraFeed] = {}
        for cam in cameras:
            url = (cam.get("transports") or {}).get("hls")
            if url:
                cid = str(cam["camera_id"])
                self.feeds[cid] = CameraFeed(camera_id=cid, url=url)
        self._lock = threading.Lock()

    # -- control ---------------------------------------------------------

    def start(self, ids: list[str] | None = None) -> dict:
        if av is None:
            return {"ok": False, "error": "pip install av pillow"}
        targets = ids or list(self.feeds)
        started = []
        with self._lock:
            for cid in targets:
                feed = self.feeds.get(cid)
                if feed is None or (feed._thread and feed._thread.is_alive()):
                    continue
                feed._stop.clear()
                feed.status = "connecting"
                feed.detail = ""
                feed._thread = threading.Thread(
                    target=self._pull, args=(feed,), daemon=True, name=f"wall-{cid}"
                )
                feed._thread.start()
                started.append(cid)
        return {"ok": True, "started": started, "running": self.running()}

    def stop(self, ids: list[str] | None = None) -> dict:
        targets = ids or list(self.feeds)
        for cid in targets:
            feed = self.feeds.get(cid)
            if feed:
                feed._stop.set()
                feed.status = "stopped"
        return {"ok": True, "stopped": targets, "running": self.running()}

    def running(self) -> int:
        return sum(1 for f in self.feeds.values() if f._thread and f._thread.is_alive())

    def state(self) -> dict:
        return {
            "running": self.running(),
            "total": len(self.feeds),
            "interval": self.interval,
            "cameras": [f.snapshot() for f in self.feeds.values()],
        }

    def jpeg(self, camera_id: str) -> bytes | None:
        feed = self.feeds.get(str(camera_id))
        return feed.jpeg if feed else None

    # -- the worker ------------------------------------------------------

    def _pull(self, feed: CameraFeed) -> None:
        backoff = BACKOFF_START_S
        while not feed._stop.is_set():
            try:
                feed.status = "connecting"
                with av.open(feed.url, timeout=OPEN_TIMEOUT_S) as container:
                    stream = container.streams.video[0]
                    stream.thread_type = "AUTO"
                    feed.status = "live"
                    feed.detail = ""
                    backoff = BACKOFF_START_S
                    last_emit = 0.0

                    for packet in container.demux(stream):
                        if feed._stop.is_set():
                            break
                        # Keyframes only: ~0.5 fps of decode instead of 30.
                        if not packet.is_keyframe:
                            continue
                        now = time.time()
                        if now - last_emit < self.interval:
                            continue
                        for frame in packet.decode():
                            feed.jpeg = _encode(frame)
                            feed.updated_at = time.time()
                            feed.frames += 1
                            last_emit = now
                            break
            except Exception as exc:
                feed.status = "retrying"
                feed.detail = f"{type(exc).__name__}: {exc}"[:160]
            if feed._stop.is_set():
                break
            # Wait, but stay interruptible so Stop is immediate.
            feed._stop.wait(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
        feed.status = "stopped"


def _encode(frame) -> bytes:
    img = Image.fromarray(frame.to_ndarray(format="rgb24"))
    img.thumbnail(THUMB)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
