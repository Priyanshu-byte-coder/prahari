"""I12's check: each analytics rule fires once, on time, and never without its geometry.

The rules are time-based, so the tests are too - they feed synthetic tracks at chosen PTS
values rather than sleeping. A rule that fires twice is as wrong as one that never fires: an
operator who sees the same stopped vehicle every frame stops reading the alerts.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.worker.analytics import Analytics, expected_sign  # noqa: E402
from services.worker.tracker import Track  # noqa: E402


def track(tid, cx, cy, h, at, label="car"):
    return Track("C1", tid, label, 0.9, (cx - 30, cy - h / 2, cx + 30, cy + h / 2), at)


def test_the_module_self_check_holds():
    """`python -m services.worker.analytics` is the ticket's runnable check; run it here too."""
    from services.worker.analytics import demo
    demo()


def test_a_stopped_vehicle_fires_once_after_sixty_seconds():
    a = Analytics(config={"C1": {"no_stop": True}})
    for i in range(0, 120, 2):
        a.observe("C1", [track(1, 100, 300, 80, float(i))], float(i))
    stopped = [e for e in a.events if e.kind == "STOPPED"]
    assert len(stopped) == 1 and stopped[0].at >= 60


def test_a_stop_is_only_an_event_where_stopping_is_banned():
    a = Analytics(config={"C1": {}})
    for i in range(0, 120, 2):
        a.observe("C1", [track(1, 100, 300, 80, float(i))], float(i))
    assert not [e for e in a.events if e.kind == "STOPPED"]


def test_moving_traffic_is_not_stopped():
    a = Analytics(config={"C1": {"no_stop": True}})
    for i in range(0, 120, 2):
        a.observe("C1", [track(1, 100 + i * 4, 300, 80, float(i))], float(i))
    assert not [e for e in a.events if e.kind == "STOPPED"]


def test_crowding_needs_the_threshold_held_for_thirty_seconds():
    a = Analytics(config={}, crowd_min=3, crowd_seconds=30)
    for i in range(20):                       # 20 s of crowd, then it clears
        a.observe("C1", [track(t, 50 * t, 300, 60, float(i)) for t in range(4)], float(i))
    assert not a.events, "a traffic light makes a 20 s crowd every cycle"
    for i in range(20, 60):
        a.observe("C1", [track(t, 50 * t, 300, 60, float(i)) for t in range(4)], float(i))
    assert [e.kind for e in a.events] == ["CROWD"], "one event per episode, not per frame"


def test_loitering_is_presence_not_stillness():
    a = Analytics(config={})
    for i in range(0, 400, 4):
        a.observe("C1", [track(3, 100 + (i % 40), 300, 80, float(i))], float(i))
    assert [e.kind for e in a.events] == ["LOITERING"]


def test_wrong_way_needs_both_bearings():
    """No surveyed `lane_bearing_deg` (G6) means no wrong-way events at all - not half of them."""
    a = Analytics(config={"C1": {"lane_bearing_deg": 90}})
    for i in range(12):
        a.observe("C1", [track(2, 100 + i * 30, 300 + i * 20, 80 + i * 14, float(i))], float(i))
    assert not a.events


def test_wrong_way_fires_against_the_expected_direction():
    a = Analytics(config={"C1": {"lane_bearing_deg": 90, "bearing_deg": 90}})
    for i in range(12):
        a.observe("C1", [track(2, 100 + i * 30, 300 + i * 20, 80 + i * 14, float(i))], float(i))
    assert [e.kind for e in a.events] == ["WRONG_WAY"]


def test_right_way_traffic_is_silent():
    a = Analytics(config={"C1": {"lane_bearing_deg": 90, "bearing_deg": 90}})
    for i in range(12):
        a.observe("C1", [track(2, 400 - i * 20, 500 - i * 25, 200 - i * 12, float(i))],
                  float(i))
    assert not a.events


@pytest.mark.parametrize("lane, bearing, expected", [
    (90, 90, 1),        # traffic flows away from a camera looking the same way
    (270, 90, -1),      # head-on
    (0, 90, 0),         # crossing the view: no sign to test
    (None, 90, 0),      # unsurveyed camera
])
def test_expected_sign(lane, bearing, expected):
    assert expected_sign({"lane_bearing_deg": lane, "bearing_deg": bearing}) == expected
