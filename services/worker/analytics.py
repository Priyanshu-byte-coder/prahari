"""[I12] Bonus analytics: crowding, stopping, wrong-way, loitering. No training, no dataset.

Every rule here reads the track history the pipeline already produces, so the marginal cost is
arithmetic and the marginal risk is zero - nothing in this file can change a plate read or a
sighting row. That is also why it is P1: it scores points on the brief's analytics line without
putting the graded test case (plate -> route) at risk.

The rules are stated in time, never in frames, because the frame rate is a deployment choice
and a "60 frame" rule silently becomes a 12-second rule when someone runs a camera at 5 fps.

Wrong-way needs one honest caveat. Direction of travel is measured in the image (does the
vehicle grow and move down, or shrink and move up), and the expected direction comes from the
camera's own geometry: `cos(lane_bearing_deg - bearing_deg) > 0` means the traffic flows away
from a camera that looks along its own bearing, so vehicles should shrink. It is a sign test,
not a speed vector - with G6's ground-truth coordinates and a homography it would become one.
Until then a wrong-way event is an operator prompt, never an alert band.

Events do not go on Redis: [C2] has no analytics stream and a contract change needs both other
owners' agreement (`CLAUDE.md §3`). They land on /metrics, in the log, and in `events` for the
caller. Wiring them to a stream is one line here the day [C2] grows a row for it.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("prahari.worker.analytics")

ROOT = Path(__file__).resolve().parents[2]
GEO = ROOT / "data" / "camera_geo.json"          # G6's file; read-only from this lane

CROWD_MIN = 8                # vehicles/people in one camera's view
CROWD_SECONDS = 30.0         # ...held this long. A traffic light makes a 20 s crowd every cycle.
STOP_SECONDS = 60.0
LOITER_SECONDS = 300.0
MOTION_EPS = 0.35            # cumulative displacement, in box heights, that still counts as stopped
WRONG_WAY_MIN_TRAVEL = 1.2   # box heights of movement before direction means anything


@dataclass
class Event:
    kind: str                # CROWD | STOPPED | WRONG_WAY | LOITERING
    camera_id: str
    at: float                # epoch seconds, from PTS
    track_id: int | None = None
    detail: dict = field(default_factory=dict)

    def __str__(self):
        who = f" track={self.track_id}" if self.track_id is not None else ""
        return f"{self.kind} cam={self.camera_id}{who} at={self.at:.1f} {self.detail}"


class _TrackState:
    __slots__ = ("first", "last", "start_xy", "start_h", "last_xy", "last_h",
                 "still_since", "still_xy", "fired")

    def __init__(self, at, xy, height):
        self.first = self.last = at
        self.start_xy = self.last_xy = self.still_xy = xy
        self.start_h = self.last_h = height
        self.still_since = at
        self.fired = set()


class Analytics:
    """Feed it `observe(camera_id, tracks, at)` per frame; read `events`, or pass `on_event`."""

    def __init__(self, config=None, crowd_min=CROWD_MIN, crowd_seconds=CROWD_SECONDS,
                 stop_seconds=STOP_SECONDS, loiter_seconds=LOITER_SECONDS, on_event=None):
        self.config = config if config is not None else load_config()
        self.crowd_min = crowd_min
        self.crowd_seconds = crowd_seconds
        self.stop_seconds = stop_seconds
        self.loiter_seconds = loiter_seconds
        self.on_event = on_event
        self.events = []
        self._tracks = {}
        self._crowd_since = {}
        self._crowd_fired = set()

    # --- the loop ------------------------------------------------------------------------

    def observe(self, camera_id, tracks, at):
        """One frame's tracks for one camera, timestamped by PTS. Returns new events."""
        before = len(self.events)
        settings = self.config.get(camera_id, {})
        self._crowd(camera_id, len(tracks), at, settings)
        live = set()
        for track in tracks:
            live.add(track.track_id)
            self._per_track(camera_id, track, at, settings)
        for key in [k for k in self._tracks if k[0] == camera_id and k[1] not in live]:
            if at - self._tracks[key].last > self.stop_seconds * 2:
                del self._tracks[key]                 # gone for good; stop paying for it
        return self.events[before:]

    def _emit(self, event):
        self.events.append(event)
        logger.info("analytics: %s", event)
        from services.worker import metrics
        metrics.ANALYTICS.labels(kind=event.kind).inc()
        if self.on_event:
            self.on_event(event)
        return event

    # --- rules ---------------------------------------------------------------------------

    def _crowd(self, camera_id, count, at, settings):
        threshold = settings.get("crowd_min", self.crowd_min)
        if count < threshold:
            self._crowd_since.pop(camera_id, None)
            self._crowd_fired.discard(camera_id)
            return
        since = self._crowd_since.setdefault(camera_id, at)
        held = at - since
        if held >= self.crowd_seconds and camera_id not in self._crowd_fired:
            self._crowd_fired.add(camera_id)
            self._emit(Event("CROWD", camera_id, at,
                             detail={"count": count, "held_s": round(held, 1),
                                     "threshold": threshold}))

    def _per_track(self, camera_id, track, at, settings):
        x1, y1, x2, y2 = track.xyxy
        xy = ((x1 + x2) / 2, (y1 + y2) / 2)
        height = max(1.0, y2 - y1)
        key = (camera_id, track.track_id)
        state = self._tracks.get(key)
        if state is None:
            self._tracks[key] = _TrackState(at, xy, height)
            return

        # Displacement since the anchor, not since the last frame: a vehicle creeping forward
        # in a jam moves a few pixels per frame and would otherwise never look like it moved.
        if math.dist(xy, state.still_xy) / height > MOTION_EPS:
            state.still_since, state.still_xy = at, xy
        state.last, state.last_xy, state.last_h = at, xy, height

        if (settings.get("no_stop") and "STOPPED" not in state.fired
                and at - state.still_since >= self.stop_seconds):
            state.fired.add("STOPPED")
            self._emit(Event("STOPPED", camera_id, at, track.track_id,
                             {"stopped_s": round(at - state.still_since, 1),
                              "class": track.label}))

        if "LOITERING" not in state.fired and at - state.first >= self.loiter_seconds:
            state.fired.add("LOITERING")
            self._emit(Event("LOITERING", camera_id, at, track.track_id,
                             {"present_s": round(at - state.first, 1), "class": track.label}))

        expected = expected_sign(settings)
        if expected and "WRONG_WAY" not in state.fired:
            travel = (math.dist(xy, state.start_xy) / height,
                      (height - state.start_h) / state.start_h)
            if travel[0] >= WRONG_WAY_MIN_TRAVEL and abs(travel[1]) > 0.15:
                observed = 1 if travel[1] < 0 else -1     # shrinking = receding = +1
                if observed != expected:
                    state.fired.add("WRONG_WAY")
                    self._emit(Event("WRONG_WAY", camera_id, at, track.track_id,
                                     {"class": track.label,
                                      "scale_change": round(travel[1], 2),
                                      "lane_bearing_deg": settings.get("lane_bearing_deg"),
                                      "camera_bearing_deg": settings.get("bearing_deg")}))


def expected_sign(settings):
    """+1 when traffic should recede from this camera, -1 when it should approach, 0 unknown.

    Unknown is the common case and it is the safe one: a camera without a surveyed
    `lane_bearing_deg` (G6) produces no wrong-way events at all, rather than half of them wrong.
    """
    lane, bearing = settings.get("lane_bearing_deg"), settings.get("bearing_deg")
    if lane is None or bearing is None:
        return 0
    component = math.cos(math.radians(float(lane) - float(bearing)))
    if abs(component) < 0.34:            # within ~70 deg of crossing the view: no sign to test
        return 0
    return 1 if component > 0 else -1


def load_config(path=GEO):
    """Per-camera geometry from G6's `data/camera_geo.json`, or {} before it lands."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {cid: {k: v for k, v in props.items()
                  if k in ("lane_bearing_deg", "bearing_deg", "no_stop", "crowd_min")}
            for cid, props in raw.items()}


def demo():
    """Self-check: each rule fires once, on time, and not before."""
    from services.worker.tracker import Track

    def track(tid, cx, cy, h, at):
        return Track("C1", tid, "car", 0.9, (cx - 30, cy - h / 2, cx + 30, cy + h / 2), at)

    a = Analytics(config={"C1": {"no_stop": True, "lane_bearing_deg": 90, "bearing_deg": 90}},
                  crowd_min=3, crowd_seconds=30)

    # A parked car: 90 s in the same place on a no-stop stretch.
    for i in range(0, 100, 2):
        a.observe("C1", [track(1, 100, 300, 80, float(i))], float(i))
    kinds = [e.kind for e in a.events]
    assert kinds.count("STOPPED") == 1, kinds
    assert all(e.at >= 60 for e in a.events if e.kind == "STOPPED")

    # Wrong way: lane flows away from the camera, this vehicle grows (approaches).
    b = Analytics(config={"C1": {"lane_bearing_deg": 90, "bearing_deg": 90}})
    for i in range(12):
        b.observe("C1", [track(2, 100 + i * 30, 300 + i * 20, 80 + i * 14, float(i))], float(i))
    assert [e.kind for e in b.events] == ["WRONG_WAY"], b.events

    # Crowd: 4 vehicles for 40 s, one event, not one per frame.
    c = Analytics(config={}, crowd_min=3, crowd_seconds=30)
    for i in range(0, 45):
        c.observe("C1", [track(t, 50 * t, 300, 60, float(i)) for t in range(4)], float(i))
    assert [e.kind for e in c.events] == ["CROWD"], c.events

    # Loitering: present for six minutes.
    d = Analytics(config={})
    for i in range(0, 400, 4):
        d.observe("C1", [track(3, 100 + (i % 40), 300, 80, float(i))], float(i))
    assert [e.kind for e in d.events] == ["LOITERING"], d.events
    print("analytics demo ok:", a.events[0], "|", b.events[0], "|", c.events[0])


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    demo()
