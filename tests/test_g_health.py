"""[G3] Health state machine and the camera.health event stream.

Time is injected, never slept -- the 15 s DOWN rule is tested in
microseconds. No Redis, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.gateway.health import (  # noqa: E402
    DEFAULT_EXPECTED_FPS,
    HealthMonitor,
    classify,
    expected_fps,
    publish,
)
from services.gateway.source import Health  # noqa: E402

SEED = [{"camera_id": "1", "fps": 25}, {"camera_id": "2", "fps": None}]


class FakeRedis:
    """Enough Redis to exercise the read/publish path, and nothing more."""

    def __init__(self, kv: dict | None = None):
        self.kv = kv or {}
        self.entries: list[tuple[str, dict]] = []

    def get(self, key):
        return self.kv.get(key)

    def xadd(self, stream, fields):
        self.entries.append((stream, fields))


# --- expected fps -----------------------------------------------------------

def test_expected_fps_is_capped_at_the_workers_sampling_rate():
    """A 25 fps camera cannot deliver more than the worker samples.

    Comparing delivered fps against 25 would mark every healthy camera
    DEGRADED -- a wall of amber pins with nothing actually wrong.
    """
    assert expected_fps({"fps": 25}) == DEFAULT_EXPECTED_FPS
    assert expected_fps({"fps": None}) == DEFAULT_EXPECTED_FPS
    assert expected_fps({"fps": 0}) == DEFAULT_EXPECTED_FPS


def test_expected_fps_uses_native_when_slower_than_the_sampler():
    assert expected_fps({"fps": 2}) == 2.0


def test_expected_fps_survives_junk_in_the_seed():
    assert expected_fps({"fps": "n/a"}) == DEFAULT_EXPECTED_FPS


# --- the state machine ------------------------------------------------------

@pytest.mark.parametrize(
    "fps,age,failures,want",
    [
        (5.0, 0.5, 0, Health.LIVE),        # full rate, fresh
        (3.0, 0.5, 0, Health.LIVE),        # exactly 60% of 5
        (2.9, 0.5, 0, Health.DEGRADED),    # just under 60%
        (5.0, 5.0, 0, Health.DEGRADED),    # rate fine, frame stale
        (5.0, 15.0, 0, Health.DOWN),       # 15 s is the DOWN boundary
        (5.0, 20.0, 0, Health.DOWN),
        (None, None, 0, Health.UNKNOWN),   # never observed
        (5.0, 0.1, 3, Health.DOWN),        # repeated connect failures win
    ],
)
def test_classify(fps, age, failures, want):
    assert classify(
        fps=fps, last_frame_age_s=age, connect_failures=failures, expected=5.0
    ) is want


# --- the ticket's Done when -------------------------------------------------

def test_killing_a_stream_goes_red_within_15s_and_emits_exactly_one_event():
    m = HealthMonitor.from_seed(SEED)
    t = 1000.0

    m.observe_fps("1", 5.0, now=t)
    assert [e["health"] for e in m.evaluate(now=t)] == ["LIVE"]

    # stream dies: no more fps readings, only time passes
    assert m.evaluate(now=t + 2) == []            # still LIVE, nothing emitted
    degraded = m.evaluate(now=t + 5)
    assert [e["health"] for e in degraded] == ["DEGRADED"]

    events = m.evaluate(now=t + 15)
    assert [e["health"] for e in events] == ["DOWN"], "red within 15 s"
    assert len(events) == 1, "exactly one event"

    # and it stays quiet afterwards -- no repeats while it remains DOWN
    assert m.evaluate(now=t + 20) == []
    assert m.evaluate(now=t + 60) == []


def test_no_event_when_nothing_changed():
    m = HealthMonitor.from_seed(SEED)
    t = 1000.0
    m.observe_fps("1", 5.0, now=t)
    m.evaluate(now=t)
    assert m.evaluate(now=t + 0.5) == []
    assert m.evaluate(now=t + 1.0) == []


def test_recovery_emits_one_event_back_to_live():
    m = HealthMonitor.from_seed(SEED)
    t = 1000.0
    m.observe_fps("1", 5.0, now=t)
    m.evaluate(now=t)
    m.evaluate(now=t + 20)  # -> DOWN

    m.observe_fps("1", 5.0, now=t + 30)
    events = m.evaluate(now=t + 30)
    assert [e["health"] for e in events] == ["LIVE"]
    assert len(events) == 1


def test_a_new_reading_clears_connect_failures():
    m = HealthMonitor.from_seed(SEED)
    t = 1000.0
    for _ in range(3):
        m.observe_connect_failure("1")
    assert [e["health"] for e in m.evaluate(now=t)] == ["DOWN"]

    m.observe_fps("1", 5.0, now=t + 1)
    assert [e["health"] for e in m.evaluate(now=t + 1)] == ["LIVE"]


def test_a_missing_fps_key_is_not_a_reading():
    """`camera:fps:<id>` has a 30 s TTL; its absence must not look like fresh data."""
    m = HealthMonitor.from_seed(SEED)
    t = 1000.0
    m.observe_fps("1", None, now=t)
    assert m.cameras["1"].last_fps_at is None
    assert m.cameras["1"].fps is None
    # still UNKNOWN, so nothing to announce
    assert m.evaluate(now=t) == []
    assert m.cameras["1"].state is Health.UNKNOWN


def test_a_camera_that_never_reports_goes_down_not_unknown_forever(monkeypatch):
    """Once seen, silence means DOWN. Never seen at all stays UNKNOWN."""
    m = HealthMonitor.from_seed(SEED)
    t = 1000.0
    m.observe_fps("1", 5.0, now=t)
    m.evaluate(now=t)
    assert [e["health"] for e in m.evaluate(now=t + 16)] == ["DOWN"]
    # camera 2 was never observed at all
    assert m.cameras["2"].state is Health.UNKNOWN


def test_zero_fps_is_not_a_reading():
    m = HealthMonitor.from_seed(SEED)
    m.observe_fps("1", 0.0, now=1000.0)
    assert m.cameras["1"].last_fps_at is None


def test_unknown_camera_id_is_ignored():
    m = HealthMonitor.from_seed(SEED)
    m.observe_fps("999", 5.0, now=1000.0)  # must not raise
    assert "999" not in m.cameras


# --- the C2 payload ---------------------------------------------------------

def test_tick_reads_the_fps_seam_and_publishes(monkeypatch):
    """End to end over the seam: `camera:fps:<id>` in, `camera.health` out."""
    from services.gateway import health as health_mod

    m = HealthMonitor.from_seed(SEED)
    # bytes, because that is what redis-py hands back
    r = FakeRedis({"camera:fps:1": b"5.0"})
    t = 1000.0

    events = health_mod.tick(m, r, now=t)
    assert [e["health"] for e in events] == ["LIVE"]
    assert r.entries and r.entries[0][0] == "camera.health"

    # key expires (worker died / stream stopped)
    r.kv.clear()
    assert [e["health"] for e in health_mod.tick(m, r, now=t + 5)] == ["DEGRADED"]
    down = health_mod.tick(m, r, now=t + 16)
    assert [e["health"] for e in down] == ["DOWN"]
    assert len(down) == 1
    # three state changes so far, three events on the stream
    assert len(r.entries) == 3


def test_read_fps_tolerates_junk():
    from services.gateway.health import read_fps

    assert read_fps(FakeRedis({"camera:fps:1": b"junk"}), "1") is None
    assert read_fps(FakeRedis({}), "1") is None
    assert read_fps(FakeRedis({"camera:fps:1": b"4.5"}), "1") == 4.5


def test_published_event_matches_the_c2_shape():
    m = HealthMonitor.from_seed(SEED)
    t = 1000.0
    m.observe_fps("1", 5.0, now=t)
    events = m.evaluate(now=t)

    r = FakeRedis()
    publish(events, r)
    stream, fields = r.entries[0]
    assert stream == "camera.health"
    assert set(fields) == {"data"}, "[C2] carries one field, `data`"
    payload = json.loads(fields["data"])
    assert set(payload) == {
        "camera_id", "health", "fps", "last_frame_age_s", "transport_in_use", "at",
    }
