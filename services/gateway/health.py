"""[G3] Health monitor — the gateway is the only producer of `camera.health`.

Signals (plan A4): connected, fps over the last 10 s, age of the last frame,
decode errors.

    LIVE      fps >= 60% of expected AND last frame < 3 s old
    DEGRADED  below that, or last frame 3-15 s old
    DOWN      no frame for 15 s, or repeated connect failures
    UNKNOWN   before the first observation

Two things that are easy to get wrong here:

**Expected fps is the worker's sampling rate, not the camera's native rate.**
The worker decodes at FRAME_FPS (5), so `camera:fps:<id>` reports ~5 even
when the source runs at 25. Comparing that against 25 marks every healthy
camera DEGRADED -- an amber wall at the demo, with nothing actually wrong.

**We infer frame age from the freshness of `camera:fps:<id>`,** because the
gateway does not decode: the worker does, and the seam between us is that
key [C2]. The key carries a 30 s TTL, so its disappearance is itself the
DOWN signal. That makes the worker's liveness part of the camera's health,
which is honest -- from the console's point of view a camera whose worker
died is not delivering frames either.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .source import Health

# Thresholds, straight from the ticket / plan A4.
LIVE_FPS_RATIO = 0.6
LIVE_MAX_AGE_S = 3.0
DEGRADED_MAX_AGE_S = 15.0
DOWN_CONNECT_FAILURES = 3

# What the worker targets, not what the camera emits. See the module docstring.
DEFAULT_EXPECTED_FPS = float(os.environ.get("FRAME_FPS", "5"))

HEALTH_STREAM = "camera.health"


def expected_fps(camera: dict) -> float:
    """Never above the worker's sampling rate -- it cannot deliver more."""
    native = camera.get("fps") or 0
    try:
        native = float(native)
    except (TypeError, ValueError):
        native = 0.0
    if native > 0:
        return min(native, DEFAULT_EXPECTED_FPS)
    return DEFAULT_EXPECTED_FPS


def classify(
    *,
    fps: float | None,
    last_frame_age_s: float | None,
    connect_failures: int,
    expected: float,
) -> Health:
    """Pure. Every threshold decision lives here so it can be tested directly."""
    if connect_failures >= DOWN_CONNECT_FAILURES:
        return Health.DOWN
    if fps is None and last_frame_age_s is None:
        return Health.UNKNOWN
    if last_frame_age_s is not None and last_frame_age_s >= DEGRADED_MAX_AGE_S:
        return Health.DOWN
    fps_ok = fps is not None and expected > 0 and fps >= LIVE_FPS_RATIO * expected
    age_ok = last_frame_age_s is not None and last_frame_age_s < LIVE_MAX_AGE_S
    if fps_ok and age_ok:
        return Health.LIVE
    return Health.DEGRADED


@dataclass(slots=True)
class CameraHealth:
    camera_id: str
    expected: float
    state: Health = Health.UNKNOWN
    fps: float | None = None
    last_fps_at: float | None = None
    connect_failures: int = 0
    transport_in_use: str | None = None
    changed_at: float | None = None

    def age(self, now: float) -> float | None:
        if self.last_fps_at is None:
            return None
        return now - self.last_fps_at


@dataclass
class HealthMonitor:
    """Evaluates every camera on a tick and emits one event per change."""

    cameras: dict[str, CameraHealth] = field(default_factory=dict)

    @classmethod
    def from_seed(cls, seed: list[dict]) -> "HealthMonitor":
        return cls(
            cameras={
                str(c["camera_id"]): CameraHealth(
                    camera_id=str(c["camera_id"]), expected=expected_fps(c)
                )
                for c in seed
            }
        )

    def observe_fps(self, camera_id: str, fps: float | None, now: float | None = None) -> None:
        """Record a reading of `camera:fps:<id>`. A missing key is not a reading."""
        now = time.time() if now is None else now
        cam = self.cameras.get(camera_id)
        if cam is None:
            return
        if fps is not None and fps > 0:
            cam.fps = fps
            cam.last_fps_at = now
            cam.connect_failures = 0

    def observe_connect_failure(self, camera_id: str) -> None:
        cam = self.cameras.get(camera_id)
        if cam is not None:
            cam.connect_failures += 1

    def evaluate(self, now: float | None = None) -> list[dict]:
        """Return one event per camera whose state actually changed."""
        now = time.time() if now is None else now
        events: list[dict] = []
        for cam in self.cameras.values():
            age = cam.age(now)
            new_state = classify(
                fps=cam.fps,
                last_frame_age_s=age,
                connect_failures=cam.connect_failures,
                expected=cam.expected,
            )
            if new_state is cam.state:
                continue  # exactly one event per change, never a heartbeat
            cam.state = new_state
            cam.changed_at = now
            events.append(
                {
                    "camera_id": cam.camera_id,
                    "health": new_state.value,
                    "fps": cam.fps,
                    "last_frame_age_s": round(age, 2) if age is not None else None,
                    "transport_in_use": cam.transport_in_use,
                    "at": now,
                }
            )
        return events


def read_fps(redis_client, camera_id: str) -> float | None:
    raw = redis_client.get(f"camera:fps:{camera_id}")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def publish(events: list[dict], redis_client) -> None:
    """[C2]: one field `data`, a JSON string, on stream `camera.health`."""
    for event in events:
        redis_client.xadd(HEALTH_STREAM, {"data": json.dumps(event)})


def tick(monitor: HealthMonitor, redis_client, now: float | None = None) -> list[dict]:
    """One pass: read the seam, evaluate, publish only what changed."""
    for camera_id in monitor.cameras:
        monitor.observe_fps(camera_id, read_fps(redis_client, camera_id), now=now)
    events = monitor.evaluate(now=now)
    if events and redis_client is not None:
        publish(events, redis_client)
    return events
