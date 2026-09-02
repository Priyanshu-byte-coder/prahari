"""The generator is lane D's stand-in for lane I's worker, so it has to be exactly [C1].

If a field name here drifts from the contract, every consumer D builds against it drifts too,
and nobody notices until the day the real worker publishes and nothing matches.
"""

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fake_sightings as fs  # noqa: E402

C1_FIELDS = {"sighting_id", "camera_id", "track_id", "pts_first", "pts_last", "ts_source",
             "plate_text", "plate_norm", "plate_canon", "plate_conf", "plate_band",
             "vehicle_class", "colour", "bbox", "reid_vec", "crop_uri"}


def one(plate_text="GJ01AB1234", seed=1):
    rng = random.Random(seed)
    return fs.finish_bbox(fs.sighting(rng, "GJ-AHD-0001", datetime.now(fs.IST), plate_text), rng)


def test_row_is_exactly_the_c1_field_set():
    assert set(one()) == C1_FIELDS


def test_failed_vote_is_a_null_plate_not_a_dropped_row():
    row = one(plate_text=None)
    assert row["plate_text"] is None and row["plate_norm"] is None
    assert row["plate_canon"] is None and row["plate_band"] == "NONE"
    assert row["camera_id"] and row["pts_first"]        # the sighting itself still happened


def test_ulids_sort_by_time():
    base = datetime.now(fs.IST)
    ids = [fs.ulid(base + timedelta(milliseconds=i * 250)) for i in range(50)]
    assert ids == sorted(ids)
    assert all(len(i) == 26 for i in ids)


def test_bbox_is_x1_y1_x2_y2():
    x1, y1, x2, y2 = one()["bbox"]
    assert x2 > x1 and y2 > y1


def test_route_crosses_five_cameras_in_order():
    hops = fs.route_schedule(datetime.now(fs.IST))
    assert [c for c, _ in hops] == [c for c, _ in fs.ROUTE]
    assert len(hops) == 5
    times = [t for _, t in hops]
    assert times == sorted(times)                       # a route that goes backwards is not one


def test_route_gaps_are_travel_time_not_zero():
    # D6 scores plausibility on speed between hops. Hops at the same instant would make every
    # implausible route look plausible, and the graded test case would prove nothing.
    hops = fs.route_schedule(datetime.now(fs.IST))
    gaps = [(b - a).total_seconds() for (_, a), (_, b) in zip(hops, hops[1:])]
    assert all(g > 30 for g in gaps), gaps


def test_canon_collapses_every_confusion_class():
    # [C7]'s vector, including G->6 which the plan's own example got wrong.
    assert fs.canon("GJ01AB1234") == "6J01A81234"
    assert fs.canon("6J01A81234") == "6J01A81234"       # idempotent


def test_canon_fallback_matches_i5_once_it_lands():
    # The fallback map in the generator is a stand-in until common/plate.py exists. The moment
    # it does, this test starts comparing them and fails if they disagree.
    from common import plate_compat
    if not plate_compat.USING_I5:
        import pytest
        pytest.skip("common/plate.py (I5) not written yet")
    from common.plate import canon as real
    for s in ("GJ01AB1234", "GJ38BS9593", "MH12DQ0000", "6J01A81234"):
        assert fs.canon(s) == real(s), s
