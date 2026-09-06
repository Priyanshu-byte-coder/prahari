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


# --- the scripted demo vehicle ---------------------------------------------------------------

def test_the_demo_vehicle_plate_cannot_collide_with_a_real_registration():
    # This plate ends up in a video shown to a police audience. "DM" is not an issued Gujarat
    # letter pair, so the demo cannot accidentally name somebody's actual vehicle.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import demo_vehicle

    assert demo_vehicle.DEMO_PLATE.startswith("GJ01DM")
    from common.plate_compat import is_valid_plate

    assert is_valid_plate(demo_vehicle.DEMO_PLATE), "must still satisfy the [C7] plate grammar"


def test_the_demo_route_is_ordered_and_ends_somewhere_impossible():
    import sys
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import demo_vehicle

    start = datetime(2026, 9, 6, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    rows = demo_vehicle.rows(start)

    stamps = [datetime.fromisoformat(r["pts_first"]) for r in rows]
    assert stamps == sorted(stamps), "a route the judge reads must be in order"
    assert len({r["camera_id"] for r in rows}) == len(rows), "one hop per camera"
    assert all(r["plate_norm"] == demo_vehicle.DEMO_PLATE for r in rows)
    # The last hop is the deliberate misread the implausibility flag exists to catch.
    assert rows[-1]["camera_id"] == demo_vehicle.IMPLAUSIBLE[0]
    assert rows[-1]["plate_band"] == "POSSIBLE", "the impossible hop is the least confident one"


def test_the_demo_vehicle_can_be_laid_down_without_the_impossible_hop():
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import demo_vehicle

    rows = demo_vehicle.rows(datetime(2026, 9, 6, tzinfo=timezone.utc), include_implausible=False)
    assert demo_vehicle.IMPLAUSIBLE[0] not in {r["camera_id"] for r in rows}
