"""I3's verify: track ids survive, sightings close once, and PTS is the only clock.

The ticket's Done-when is "a 60 s clip gives one sighting per vehicle pass and track ids do not
churn". A clip cannot fail that cleanly - a dropped detection and a reset tracker look identical
in the output - so the churn half is asserted directly against the rule it comes from: one
tracker instance per camera, kept alive. `test_fresh_instance_per_frame_churns_ids` is the
control; it is what the code would do if somebody moved the constructor into the loop.

No model, no clip, no GPU: detections are synthesised, so this runs in CI in under a second.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.worker.backend import Detection  # noqa: E402
from services.worker.publish import FIELDS, validate  # noqa: E402
from services.worker.sighting import (SightingBuilder, colour_of,  # noqa: E402
                                      sharpness, ulid)
from services.worker.tracker import CameraTracker, Track, Trackers  # noqa: E402


def det(x, y, w=80, h=60, conf=0.9, label="car"):
    return Detection((float(x), float(y), float(x + w), float(y + h)), conf, label)


def pass_by(steps=10, dx=12, start=100):
    """One vehicle crossing the view, one detection per frame."""
    return [[det(start + i * dx, 200)] for i in range(steps)]


# --- track identity ------------------------------------------------------------------------

def test_ids_are_stable_across_frames():
    tracker = CameraTracker("GJ-AHD-0001")
    ids = set()
    for i, dets in enumerate(pass_by(12)):
        for track in tracker.update(dets, pts_seconds=i * 0.2):
            ids.add(track.track_id)
    assert len(ids) == 1, f"one vehicle produced {len(ids)} track ids: {ids}"


def test_sequential_vehicles_get_distinct_ids():
    """Two passes, one after the other, are two vehicles - and the ids have to say so."""
    tracker = CameraTracker("GJ-AHD-0001")
    ids = set()
    for i, dets in enumerate(pass_by(8)):
        ids |= {t.track_id for t in tracker.update(dets, i * 0.2)}
    for _ in range(40):                       # the first vehicle leaves and its track expires
        tracker.update([], 10.0)
    for i, dets in enumerate(pass_by(8, start=600)):
        ids |= {t.track_id for t in tracker.update(dets, 20.0 + i * 0.2)}
    assert len(ids) == 2, f"two vehicle passes produced ids {ids}"


def test_fresh_instance_per_frame_loses_identity():
    """The control case, and the bug the ticket's first bullet exists to prevent.

    ultralytics restarts its track-id counter with every tracker it builds, so the churn does
    not show up as *more* ids - it shows up as fewer: two different vehicles both come back as
    track 1, and the route stitches them into one journey.
    """
    ids = set()
    for i, dets in enumerate(pass_by(8)):
        ids |= {t.track_id for t in CameraTracker("GJ-AHD-0001").update(dets, i * 0.2)}
    for i, dets in enumerate(pass_by(8, start=600)):
        ids |= {t.track_id for t in CameraTracker("GJ-AHD-0001").update(dets, 20.0 + i * 0.2)}
    assert ids == {1}, f"the control is broken - fresh trackers should collapse to one id: {ids}"


def test_two_cameras_do_not_share_track_state():
    trackers = Trackers()
    for i, dets in enumerate(pass_by(8)):
        trackers.update("CAM-A", dets, i * 0.2)
        trackers.update("CAM-B", [det(700 - i * 12, 400)], i * 0.2)
    assert len(trackers) == 2


def _second_pass_id(discontinuous):
    trackers = Trackers()
    for i, dets in enumerate(pass_by(8)):
        trackers.update("CAM-A", dets, i * 0.2)
    ids = set()
    for i, dets in enumerate(pass_by(8, start=600)):
        ids |= {t.track_id for t in trackers.update("CAM-A", dets, 100 + i * 0.2,
                                                    discontinuous=discontinuous and i == 0)}
    return ids


def test_discontinuity_resets_ids():
    """A looped recording is a new scene: the tracker starts over instead of carrying tracks
    (and their Kalman state) across the loop point into a different vehicle."""
    assert _second_pass_id(discontinuous=False) == {2}, "ids must advance within one scene"
    assert _second_pass_id(discontinuous=True) == {1}, "a discontinuity must reset the tracker"


def test_label_survives_association():
    tracker = CameraTracker("CAM")
    labels = set()
    for i, dets in enumerate(pass_by(6)):
        dets[0].label = "truck"
        labels |= {t.label for t in tracker.update(dets, i * 0.2)}
    assert labels == {"truck"}


# --- sighting builder ----------------------------------------------------------------------

def track_at(pts, tid=1, box=(10, 10, 90, 90), label="car"):
    return Track("GJ-AHD-0001", tid, label, 0.9, box, pts)


def test_one_pass_makes_one_sighting():
    b = SightingBuilder("GJ-AHD-0001", vote_factory=lambda: None)
    for i in range(15):
        b.observe(track_at(100.0 + i * 0.2))
    assert b.tick(101.9) == [], "closed while the vehicle was still in frame"
    closed = b.tick(110.0)
    assert len(closed) == 1 and closed[0].frames == 15


def test_two_vehicles_make_two_sightings():
    b = SightingBuilder("GJ-AHD-0001", vote_factory=lambda: None)
    for i in range(6):
        b.observe(track_at(10.0 + i * 0.2, tid=1))
        b.observe(track_at(10.0 + i * 0.2, tid=2))
    assert len(b.flush()) == 2


def test_close_window_is_six_seconds_of_stream_time():
    b = SightingBuilder("CAM", close_after=6.0, vote_factory=lambda: None)
    b.observe(track_at(50.0))
    assert b.tick(55.9) == []
    assert len(b.tick(56.1)) == 1


def test_timestamps_come_from_pts_not_now():
    """The gap between the first and last frame must be the PTS gap, to the millisecond."""
    b = SightingBuilder("CAM", vote_factory=lambda: None)
    b.observe(track_at(1000.0), wall_clock=1_757_000_000.0)
    b.observe(track_at(1007.5))
    s = b.flush()[0]
    assert s.pts_last - s.pts_first == pytest.approx(7.5, abs=1e-6)
    assert s.pts_first == pytest.approx(1_757_000_000.0, abs=1e-6)
    assert s.row()["ts_source"] == "rtsp_pts"


def test_row_matches_the_c1_contract():
    b = SightingBuilder("GJ-AHD-0123", vote_factory=lambda: None)
    b.observe(track_at(12.0), crop=np.full((60, 80, 3), 200, np.uint8))
    row = b.flush()[0].row()
    assert list(row) == list(FIELDS), "row drifted from [C1] field order"
    validate(row)
    assert row["plate_text"] is None and row["plate_band"] == "NONE"
    assert row["pts_first"].endswith("+05:30")
    assert len(row["sighting_id"]) == 26


def test_best_crop_is_the_sharpest_one():
    rng = np.random.default_rng(0)
    blurred = np.full((60, 80, 3), 128, np.uint8)
    detailed = rng.integers(0, 255, (60, 80, 3), dtype=np.uint8)
    b = SightingBuilder("CAM", vote_factory=lambda: None)
    b.observe(track_at(1.0), crop=blurred)
    b.observe(track_at(1.2), crop=detailed)
    b.observe(track_at(1.4), crop=blurred)
    s = b.flush()[0]
    assert s.crop_sharpness == pytest.approx(sharpness(detailed))


def test_ulid_sorts_by_time_and_is_26_chars():
    ids = [ulid(1_700_000_000_000 + i * 1000) for i in range(20)]
    assert ids == sorted(ids) and len(set(ids)) == 20
    assert all(len(i) == 26 for i in ids)


@pytest.mark.parametrize("value, expected", [(10, "black"), (140, "grey"), (250, "white")])
def test_colour_of_greyscale_vehicles(value, expected):
    assert colour_of(np.full((40, 40, 3), value, np.uint8)) == expected


def test_colour_of_a_red_vehicle():
    red = np.zeros((40, 40, 3), np.uint8)
    red[:, :] = (30, 30, 200)          # BGR
    assert colour_of(red) == "red"
