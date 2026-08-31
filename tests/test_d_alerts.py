"""D4's verify: the whole band table, and every illegal transition refused with 409.

The band table is the part a judge can argue with, so it is walked row by row rather than
spot-checked. The state machine is the part an inquiry would lean on: an alert whose state can
be set arbitrarily cannot answer "who dismissed this, when, and why".
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import fake_sightings as fs                                                    # noqa: E402
from alerts import (ACKNOWLEDGED, ACTIONED, AlertRepo, DISMISSED,              # noqa: E402
                    IllegalTransition, NEW)
from common import plate_compat                                                # noqa: E402
from matcher import Matcher, band_for, best_match                              # noqa: E402
from store import Store                                                        # noqa: E402
from watchlist import WatchlistRepo, validate_row                              # noqa: E402

DSN = os.environ.get("TEST_POSTGRES_DSN",
                     os.environ.get("POSTGRES_DSN",
                                    "postgresql://sentinel:sentinel@localhost:5432/sentinel"))
REDIS_URL = os.environ.get("TEST_REDIS_URL",
                           os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

needs_i5 = pytest.mark.skipif(not plate_compat.USING_I5,
                              reason="common/plate.py (I5) is not merged yet - PR #38")

WATCHED = "GJ01AB1234"


# --- the band table: pure, no database ------------------------------------------------------

@needs_i5
@pytest.mark.parametrize("plate, sighting_band, expected", [
    (WATCHED,      "CONFIRMED", "CONFIRMED"),   # exact, and the read was confident
    (WATCHED,      "PROBABLE",  "PROBABLE"),    # exact string, unconfident read
    (WATCHED,      "POSSIBLE",  "PROBABLE"),    # ... never CONFIRMED off a POSSIBLE read
    ("GJ01A81234", "CONFIRMED", "PROBABLE"),    # one confusion edit  B<->8, cost 0.5
    ("GJ01AB1Z34", "CONFIRMED", "PROBABLE"),    # one confusion edit  2<->Z
    ("GJ01AC1234", "CONFIRMED", "POSSIBLE"),    # one plain edit      B->C, cost 1.0
    ("GJ01A81Z34", "CONFIRMED", "POSSIBLE"),    # two confusion edits, cost 1.0
    ("GJ01ACD234", "CONFIRMED", "POSSIBLE"),    # two plain edits,     cost 2.0
    ("MH04XY9999", "CONFIRMED", None),          # a different vehicle
])
def test_band_table(plate, sighting_band, expected):
    cost = plate_compat.weighted_levenshtein(plate, WATCHED)
    assert band_for(cost, sighting_band) == expected


@needs_i5
def test_a_confusion_edit_scores_below_a_plain_one():
    # This ordering is what makes 0.5 mean PROBABLE and 1.0 mean POSSIBLE; if [C7]'s cost table
    # ever changes, this fails before the band table does and says why.
    confusion = plate_compat.weighted_levenshtein(WATCHED, "GJ01A81234")
    plain = plate_compat.weighted_levenshtein(WATCHED, "GJ01AC1234")
    assert confusion == 0.5 and plain == 1.0


# --- fixtures --------------------------------------------------------------------------------

@pytest.fixture
def rig():
    store = Store(dsn=DSN, redis_url=REDIS_URL)
    try:
        store.redis.ping()
        with store.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM alerts LIMIT 1")
    except Exception as exc:
        pytest.skip(f"needs a live Redis and a migrated Postgres: {exc}")

    tag = uuid.uuid4().hex[:8]
    camera = f"GJ-TEST-{tag}"
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO cameras (camera_id, name) VALUES (%s,%s)", (camera, "alert rig"))

    watchlist = WatchlistRepo(store)
    entry = validate_row({"kind": "plate", "plate": WATCHED, "category": "stolen vehicle",
                          "reason": f"rig {tag}", "severity": "HIGH"})
    entry.source = tag
    watchlist_id = watchlist.add(entry)

    alerts = AlertRepo(store)
    yield store, alerts, watchlist_id, camera, tag

    with store.conn as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM alert_events WHERE alert_id IN "
                    "(SELECT id FROM alerts WHERE camera_id = %s)", (camera,))
        cur.execute("DELETE FROM alerts WHERE camera_id = %s", (camera,))
        cur.execute("DELETE FROM sightings WHERE camera_id = %s", (camera,))
        cur.execute("DELETE FROM cameras WHERE camera_id = %s", (camera,))
        cur.execute("DELETE FROM watchlist WHERE id = %s", (watchlist_id,))
    for key in store.redis.scan_iter("alert:dedup:*"):
        store.redis.delete(key)
    store.close()


def a_sighting(camera, plate=WATCHED, band="CONFIRMED", at=None):
    import random
    row = fs.sighting(random.Random(5), camera, at or datetime.now(fs.IST), plate)
    row["plate_band"] = band
    return fs.finish_bbox(row, random.Random(5))


# --- the state machine -----------------------------------------------------------------------

def test_the_legal_path_runs_end_to_end(rig):
    store, alerts, watchlist_id, camera, _ = rig
    alert_id, created = alerts.raise_alert(watchlist_id=watchlist_id,
                                           sighting=a_sighting(camera), band="CONFIRMED")
    assert created and alerts.get(alert_id)["state"] == NEW
    assert alerts.transition(alert_id, ACKNOWLEDGED, by_user=None)["state"] == ACKNOWLEDGED
    assert alerts.transition(alert_id, ACTIONED)["state"] == ACTIONED
    states = [(e["from_state"], e["to_state"]) for e in alerts.events(alert_id)]
    assert states == [(None, NEW), (NEW, ACKNOWLEDGED), (ACKNOWLEDGED, ACTIONED)]


@pytest.mark.parametrize("path, illegal", [
    ([], ACTIONED),                       # NEW -> ACTIONED, skipping the acknowledgement
    ([], DISMISSED),                      # NEW -> DISMISSED, same
    ([], NEW),                            # NEW -> NEW
    ([ACKNOWLEDGED], NEW),                # backwards
    ([ACKNOWLEDGED], ACKNOWLEDGED),       # sideways
    ([ACKNOWLEDGED, ACTIONED], DISMISSED),   # ACTIONED is terminal
    ([ACKNOWLEDGED, ACTIONED], ACKNOWLEDGED),
])
def test_every_illegal_transition_is_409(rig, path, illegal):
    _store, alerts, watchlist_id, camera, _ = rig
    alert_id, _ = alerts.raise_alert(watchlist_id=watchlist_id,
                                     sighting=a_sighting(camera), band="CONFIRMED")
    for step in path:
        alerts.transition(alert_id, step, reason="walking to the start state")
    before = alerts.get(alert_id)["state"]
    with pytest.raises(IllegalTransition) as caught:
        alerts.transition(alert_id, illegal, reason="whatever")
    assert caught.value.status_code == 409
    assert alerts.get(alert_id)["state"] == before      # refused, and nothing was written


def test_dismissed_without_a_reason_is_refused(rig):
    _store, alerts, watchlist_id, camera, _ = rig
    alert_id, _ = alerts.raise_alert(watchlist_id=watchlist_id,
                                     sighting=a_sighting(camera), band="CONFIRMED")
    alerts.transition(alert_id, ACKNOWLEDGED)
    for empty in (None, "", "   "):
        with pytest.raises(IllegalTransition) as caught:
            alerts.transition(alert_id, DISMISSED, reason=empty)
        assert caught.value.status_code == 409
    assert alerts.transition(alert_id, DISMISSED, reason="plate misread, wrong vehicle")[
        "state"] == DISMISSED


def test_transitioning_an_alert_that_does_not_exist_is_409(rig):
    _store, alerts, _watchlist_id, _camera, _ = rig
    with pytest.raises(IllegalTransition) as caught:
        alerts.transition(9_999_999, ACKNOWLEDGED)
    assert caught.value.status_code == 409


def test_every_transition_leaves_an_audit_row(rig):
    store, alerts, watchlist_id, camera, _ = rig
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log")
        before = cur.fetchone()[0]
    alert_id, _ = alerts.raise_alert(watchlist_id=watchlist_id,
                                     sighting=a_sighting(camera), band="CONFIRMED")
    alerts.transition(alert_id, ACKNOWLEDGED)
    alerts.transition(alert_id, DISMISSED, reason="duplicate of an earlier alert")
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log")
        assert cur.fetchone()[0] == before + 3          # raise, acknowledge, dismiss
        cur.execute("""SELECT prev_hash, hash FROM audit_log ORDER BY seq DESC LIMIT 2""")
        newest, previous = cur.fetchall()
        assert bytes(newest[0]) == bytes(previous[1])   # the chain links backwards


# --- dedup and the matcher --------------------------------------------------------------------

def test_a_repeat_on_the_same_camera_bumps_the_count(rig):
    # A car at a red light is seen on twenty frames. Twenty alerts is how an operator learns to
    # ignore the panel.
    _store, alerts, watchlist_id, camera, _ = rig
    first, created_first = alerts.raise_alert(watchlist_id=watchlist_id,
                                              sighting=a_sighting(camera), band="CONFIRMED")
    second, created_second = alerts.raise_alert(watchlist_id=watchlist_id,
                                                sighting=a_sighting(camera), band="CONFIRMED")
    assert created_first and not created_second and first == second
    assert alerts.get(first)["count"] == 2


def test_the_dedup_window_is_per_camera(rig):
    store, alerts, watchlist_id, camera, tag = rig
    other = f"GJ-TEST-{tag}-b"
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO cameras (camera_id, name) VALUES (%s,%s)", (other, "second"))
    try:
        first, _ = alerts.raise_alert(watchlist_id=watchlist_id,
                                      sighting=a_sighting(camera), band="CONFIRMED")
        second, created = alerts.raise_alert(watchlist_id=watchlist_id,
                                             sighting=a_sighting(other), band="CONFIRMED")
        assert created and second != first          # the same car on the next camera is news
    finally:
        with store.conn as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM alerts WHERE camera_id = %s", (other,))
            cur.execute("DELETE FROM cameras WHERE camera_id = %s", (other,))


@needs_i5
def test_matcher_raises_an_alert_and_publishes_it(rig):
    store, _alerts, watchlist_id, camera, tag = rig
    matcher = Matcher(store=store, stream=f"sightings-test-{tag}", group="matcher")
    matcher.ensure_group()
    matcher.index.load()
    before = store.redis.xlen("alerts")

    alert_id = matcher.check(a_sighting(camera, plate="GJ01A81234"))   # one confusion edit
    assert alert_id is not None
    assert store.redis.xlen("alerts") == before + 1
    frame = json.loads(store.redis.xrevrange("alerts", count=1)[0][1]["data"])
    assert frame["alert_id"] == alert_id and frame["band"] == "PROBABLE"
    assert frame["camera_id"] == camera and frame["state"] == NEW


@needs_i5
def test_matcher_ignores_a_sighting_with_no_plate(rig):
    store, _alerts, _watchlist_id, camera, _ = rig
    matcher = Matcher(store=store)
    matcher.index.load()
    assert matcher.check(a_sighting(camera, plate=None, band="NONE")) is None


@needs_i5
def test_matcher_ignores_an_unwatched_plate(rig):
    store, _alerts, _watchlist_id, camera, _ = rig
    matcher = Matcher(store=store)
    matcher.index.load()
    assert matcher.check(a_sighting(camera, plate="MH04XY9999")) is None


@needs_i5
def test_an_expired_watchlist_entry_does_not_match(rig):
    # An expired entry that still fires is how a watchlist stops being trusted.
    store, _alerts, _watchlist_id, camera, tag = rig
    repo = WatchlistRepo(store)
    now = datetime.now(fs.IST)
    expired = validate_row({"kind": "plate", "plate": "GJ77QQ8888",
                            "category": "stolen vehicle", "reason": f"expired {tag}",
                            "severity": "HIGH",
                            "valid_from": (now - timedelta(days=3)).isoformat(),
                            "valid_until": (now - timedelta(days=1)).isoformat()})
    expired_id = repo.add(expired)
    try:
        matcher = Matcher(store=store)
        matcher.index.load()
        assert matcher.check(a_sighting(camera, plate="GJ77QQ8888")) is None
    finally:
        with store.conn as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM watchlist WHERE id = %s", (expired_id,))


@needs_i5
def test_trigram_fallback_finds_a_plain_misread(rig):
    # canon() cannot see a plain edit: GJ01AC1234 canonises differently from the watched plate,
    # so the dict lookup misses and the trigram query is what finds it.
    store, _alerts, _watchlist_id, camera, _ = rig
    matcher = Matcher(store=store)
    matcher.index.load()
    assert matcher.index.candidates("GJ01AC1234") == []
    hit = best_match(a_sighting(camera, plate="GJ01AC1234"), matcher.index)
    assert hit is not None and hit[1] == "POSSIBLE"
