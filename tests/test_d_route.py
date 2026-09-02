"""D6's verify: five ordered hops from the generator's scripted plate, one flagged implausible.

The flag is the point of the ticket. Two cameras 200 km apart 90 seconds apart means one of the
two plate reads is wrong, and the honest response is to show both hops and mark the doubtful
one - not to quietly drop it and hand the operator a clean-looking route with a hole in it.
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

import export                                                          # noqa: E402
import fake_sightings as fs                                            # noqa: E402
from route import (IMPLAUSIBLE_KMH, RouteBuilder, collapse,            # noqa: E402
                   flag_implausible, haversine_km, snap)
from store import Store                                                # noqa: E402

DSN = os.environ.get("TEST_POSTGRES_DSN",
                     os.environ.get("POSTGRES_DSN", "postgresql://localhost:5432/sentinel"))
REDIS_URL = os.environ.get("TEST_REDIS_URL",
                           os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

ROUTE_PLATE = fs.ROUTE_PLATE

# Four cameras along CG Road in Ahmedabad, then one in Surat. The Surat hop is 200 km away
# roughly a minute later: physically impossible, and exactly the misread the flag exists for.
GEO = [
    (23.0225, 72.5714),
    (23.0270, 72.5680),
    (23.0310, 72.5650),
    (23.0355, 72.5620),
    (21.1702, 72.8311),
]


@pytest.fixture
def rig():
    store = Store(dsn=DSN, redis_url=REDIS_URL)
    try:
        with store.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM sightings LIMIT 1")
    except Exception as exc:
        pytest.skip(f"needs a migrated Postgres: {exc}")

    tag = uuid.uuid4().hex[:8]
    cameras = [f"RT-{tag}-{i}" for i in range(5)]
    with store.conn as conn, conn.cursor() as cur:
        for camera, (lat, lon) in zip(cameras, GEO):
            cur.execute("""INSERT INTO cameras (camera_id, name, lat, lon, district_code)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (camera, f"camera {camera[-1]}", lat, lon, "AHD"))
    yield store, tag, cameras
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sightings WHERE camera_id = ANY(%s)", (cameras,))
        cur.execute("DELETE FROM cameras WHERE camera_id = ANY(%s)", (cameras,))
    store.close()


def lay_route(store, cameras, plate=ROUTE_PLATE, band="CONFIRMED", repeats=1, bands=None):
    """Publish the generator's scripted route through the real persistence path.

    `bands` overrides the read confidence per camera, which is how the "which end of an
    impossible pair do we suspect" case is set up deterministically.
    """
    import random

    rng = random.Random(3)
    start = datetime.now(fs.IST) - timedelta(hours=1)
    hops = fs.route_schedule(start)
    rows = []
    for index, (camera, (_generated_camera, pts)) in enumerate(zip(cameras, hops)):
        for repeat in range(repeats):
            row = fs.sighting(rng, camera, pts + timedelta(seconds=repeat * 2), plate)
            row["plate_band"] = (bands or {}).get(index, band)
            row["plate_conf"] = 0.95 if row["plate_band"] == "CONFIRMED" else 0.61
            rows.append(fs.finish_bbox(row, rng))
    store.insert_sightings(rows)
    return rows


def test_the_scripted_plate_comes_back_as_five_ordered_hops(rig):
    store, _tag, cameras = rig
    lay_route(store, cameras)
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))

    assert [h["camera_id"] for h in route["hops"]] == cameras
    assert [h["n"] for h in route["hops"]] == [1, 2, 3, 4, 5]
    assert route["fuzzy"] is False and route["note"] is None


def test_one_hop_is_flagged_implausible_and_still_shown(rig):
    # The Surat read is the weaker one, which is the realistic setup: a POSSIBLE read that
    # spells a watched plate is exactly what puts a car 200 km away in ninety seconds.
    store, _tag, cameras = rig
    lay_route(store, cameras, bands={4: "POSSIBLE"})
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))

    flagged = [h for h in route["hops"] if h["flag"] == "IMPLAUSIBLE"]
    assert len(flagged) == 1
    assert flagged[0]["camera_id"] == cameras[4]          # the Surat camera, the weaker read
    assert flagged[0]["implied_speed_kmh"] > IMPLAUSIBLE_KMH
    assert len(route["hops"]) == 5                        # flagged, never removed


def test_an_impossible_pair_of_equally_confident_reads_still_flags_one(rig):
    # Nothing distinguishes the two reads, so the rule cannot say which is wrong - but silence
    # is not an option either. Exactly one end of the pair is marked.
    store, _tag, cameras = rig
    lay_route(store, cameras)
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))
    flagged = [h["camera_id"] for h in route["hops"] if h["flag"] == "IMPLAUSIBLE"]
    assert len(flagged) == 1
    assert flagged[0] in (cameras[3], cameras[4])


def test_repeated_sightings_on_one_camera_collapse_into_one_hop(rig):
    # A car at a junction produces several sightings. A route that lists the same junction five
    # times is not a route.
    store, _tag, cameras = rig
    lay_route(store, cameras, repeats=4)
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))
    assert len(route["hops"]) == 5
    assert all(h["sightings"] == 4 for h in route["hops"])


def test_a_misread_plate_falls_back_to_fuzzy_and_says_so(rig):
    # The stored plate carries one confusion-pair edit. Nothing matches exactly, so the query
    # retries on the canon key - and the result set is labelled, because an unlabelled fuzzy
    # match is how somebody stops the wrong car.
    store, _tag, cameras = rig
    lay_route(store, cameras, plate="GJ01A81234")
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))

    assert route["fuzzy"] is True
    assert route["note"] == "fuzzy match; verify plate"
    assert len(route["hops"]) == 5


def test_an_unknown_plate_is_an_empty_route_not_an_error(rig):
    store, _tag, _cameras = rig
    route = RouteBuilder(store).build("MH04ZZ0001")
    assert route["hops"] == [] and route["fuzzy"] is False


def test_the_window_bounds_the_query(rig):
    store, _tag, cameras = rig
    lay_route(store, cameras)
    recent = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(minutes=1))
    assert recent["hops"] == []                            # the route was laid an hour ago


# --- the arithmetic, without a database ------------------------------------------------------

def test_haversine_matches_a_known_distance():
    # Ahmedabad to Surat is about 205 km great-circle.
    assert 200 < haversine_km(23.0225, 72.5714, 21.1702, 72.8311) < 215


def test_the_lower_confidence_hop_of_a_bad_pair_is_the_one_flagged():
    # One of the two reads is wrong; the one the system was less sure about is the suspect.
    now = datetime.now(fs.IST)
    hops = [
        {"camera_id": "A", "lat": 23.02, "lon": 72.57, "pts": now,
         "pts_last": now, "band": "CONFIRMED", "plate_conf": 0.95},
        {"camera_id": "B", "lat": 21.17, "lon": 72.83, "pts": now + timedelta(seconds=90),
         "pts_last": now + timedelta(seconds=90), "band": "POSSIBLE", "plate_conf": 0.61},
    ]
    flag_implausible(hops)
    assert hops[0]["flag"] is None
    assert hops[1]["flag"] == "IMPLAUSIBLE"


def test_a_plausible_pair_is_not_flagged():
    now = datetime.now(fs.IST)
    hops = [
        {"camera_id": "A", "lat": 23.0225, "lon": 72.5714, "pts": now, "pts_last": now,
         "band": "CONFIRMED", "plate_conf": 0.9},
        {"camera_id": "B", "lat": 23.0270, "lon": 72.5680, "pts": now + timedelta(seconds=60),
         "pts_last": now + timedelta(seconds=60), "band": "CONFIRMED", "plate_conf": 0.9},
    ]
    flag_implausible(hops)
    assert [h["flag"] for h in hops] == [None, None]
    assert hops[1]["implied_speed_kmh"] < IMPLAUSIBLE_KMH


def test_two_sightings_at_the_same_instant_do_not_divide_by_zero():
    now = datetime.now(fs.IST)
    hops = [{"camera_id": "A", "lat": 23.0, "lon": 72.5, "pts": now, "pts_last": now,
             "band": "CONFIRMED", "plate_conf": 0.9},
            {"camera_id": "B", "lat": 23.1, "lon": 72.6, "pts": now, "pts_last": now,
             "band": "CONFIRMED", "plate_conf": 0.9}]
    flag_implausible(hops)
    assert hops[1]["implied_speed_kmh"] is None


def test_a_camera_without_coordinates_does_not_break_the_route():
    # G6 surveys coordinates after G1 seeds the cameras, so this is the normal state for days.
    now = datetime.now(fs.IST)
    hops = [{"camera_id": "A", "lat": None, "lon": None, "pts": now, "pts_last": now,
             "band": "CONFIRMED", "plate_conf": 0.9},
            {"camera_id": "B", "lat": 23.1, "lon": 72.6, "pts": now + timedelta(minutes=5),
             "pts_last": now, "band": "CONFIRMED", "plate_conf": 0.9}]
    flag_implausible(hops)
    assert hops[1]["implied_speed_kmh"] is None and hops[1]["flag"] is None


def test_collapse_keeps_the_best_read_of_a_run():
    rows = [
        {"camera_id": "A", "camera_name": "a", "lat": 1.0, "lon": 2.0,
         "pts_first": datetime(2026, 9, 1, 10, 0), "pts_last": datetime(2026, 9, 1, 10, 0),
         "plate_norm": "GJ01AB1234", "plate_band": "POSSIBLE", "plate_conf": 0.6,
         "crop_uri": "s3://crops/a.jpg"},
        {"camera_id": "A", "camera_name": "a", "lat": 1.0, "lon": 2.0,
         "pts_first": datetime(2026, 9, 1, 10, 0, 4), "pts_last": datetime(2026, 9, 1, 10, 0, 6),
         "plate_norm": "GJ01AB1234", "plate_band": "CONFIRMED", "plate_conf": 0.94,
         "crop_uri": "s3://crops/b.jpg"},
    ]
    hops = collapse(rows)
    assert len(hops) == 1
    assert hops[0]["band"] == "CONFIRMED" and hops[0]["crop_uri"] == "s3://crops/b.jpg"
    assert hops[0]["sightings"] == 2


def test_without_osrm_the_geometry_is_the_straight_line_and_says_so():
    # A fabricated road path would be a lie drawn on a map, and the map is what a judge looks at.
    hops = [{"lat": 23.0, "lon": 72.5}, {"lat": 23.1, "lon": 72.6}]
    geometry, snapped = snap(hops, osrm_url="http://127.0.0.1:1/never")
    assert snapped is False
    assert geometry["type"] == "LineString"
    assert geometry["coordinates"] == [[72.5, 23.0], [72.6, 23.1]]


# --- export -----------------------------------------------------------------------------------

def test_csv_export_carries_the_hops_and_the_flag(rig):
    store, _tag, cameras = rig
    lay_route(store, cameras)
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))
    body = export.to_csv(route).decode("utf-8")

    assert "IMPLAUSIBLE" in body
    assert all(camera in body for camera in cameras)
    assert "# match,exact" in body


def test_pdf_export_is_a_pdf(rig):
    store, _tag, cameras = rig
    lay_route(store, cameras)
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))
    body = export.to_pdf(route)
    assert body.startswith(b"%PDF") and len(body) > 2000


def test_every_export_writes_an_audit_row(rig):
    # An export is surveillance data leaving the building.
    store, _tag, cameras = rig
    lay_route(store, cameras)
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))

    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log WHERE action = 'route.export'")
        before = cur.fetchone()[0]

    export.record_export(store, route, "csv", user_id=None, dept_id=None)

    with store.conn as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*), max(object_id) FROM audit_log
                       WHERE action = 'route.export'""")
        after, object_id = cur.fetchone()
    assert after == before + 1 and object_id == ROUTE_PLATE


def test_the_export_audit_row_stays_on_the_alert_chain(rig):
    # One chain for everything that has to be accounted for, so D10 can walk it end to end.
    store, _tag, cameras = rig
    lay_route(store, cameras)
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))
    export.record_export(store, route, "pdf")
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT prev_hash, hash FROM audit_log ORDER BY seq DESC LIMIT 2")
        newest, previous = cur.fetchall()
    assert bytes(newest[0]) == bytes(previous[1])


def test_render_rejects_a_format_nobody_asked_for():
    with pytest.raises(ValueError):
        export.render({"plate": "X", "from": "", "to": "", "fuzzy": False, "hops": []}, "docx")


def test_a_fuzzy_route_is_labelled_in_the_export_itself(rig):
    # The label has to survive the export: the CSV is what gets attached to a case file.
    store, _tag, cameras = rig
    lay_route(store, cameras, plate="GJ01A81234")
    route = RouteBuilder(store).build(ROUTE_PLATE, since=datetime.now(fs.IST) - timedelta(days=1))
    body = export.to_csv(route).decode("utf-8")
    assert "fuzzy - verify plate" in body
    assert json.loads(json.dumps(route))["fuzzy"] is True


# --- the HTTP surface -------------------------------------------------------------------------

def api_client(store):
    """Plain HTTP, so starlette's TestClient is fine here - no server-pushed frames involved."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from route import build_router

    app = FastAPI()
    app.include_router(build_router(store))
    return TestClient(app)


def test_the_route_endpoint_answers_c4(rig):
    store, _tag, cameras = rig
    lay_route(store, cameras, bands={4: "POSSIBLE"})
    response = api_client(store).get("/api/route", params={"plate": ROUTE_PLATE})
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"plate", "from", "to", "fuzzy", "hops", "snapped_geometry"}
    assert [hop["camera_id"] for hop in body["hops"]] == cameras
    assert any(hop["flag"] == "IMPLAUSIBLE" for hop in body["hops"])


def test_the_export_endpoint_returns_a_file_and_logs_it(rig):
    store, _tag, cameras = rig
    lay_route(store, cameras)
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log WHERE action = 'route.export'")
        before = cur.fetchone()[0]

    response = api_client(store).get("/api/route/export",
                                     params={"plate": ROUTE_PLATE, "fmt": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f"route-{ROUTE_PLATE}.csv" in response.headers["content-disposition"]

    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log WHERE action = 'route.export'")
        assert cur.fetchone()[0] == before + 1


def test_an_unsupported_export_format_is_a_400(rig):
    store, _tag, _cameras = rig
    response = api_client(store).get("/api/route/export",
                                     params={"plate": ROUTE_PLATE, "fmt": "docx"})
    assert response.status_code == 400


def test_a_malformed_window_is_a_400_not_a_traceback(rig):
    store, _tag, _cameras = rig
    response = api_client(store).get("/api/route",
                                     params={"plate": ROUTE_PLATE, "from": "last tuesday"})
    assert response.status_code == 400


def test_a_non_http_osrm_url_is_refused_rather_than_opened():
    # urlopen will fetch file:// happily. A routing URL that can be pointed at the local
    # filesystem is a file-read primitive wearing a map's clothes.
    hops = [{"lat": 23.0, "lon": 72.5}, {"lat": 23.1, "lon": 72.6}]
    geometry, snapped = snap(hops, osrm_url="file:///etc/passwd")
    assert snapped is False and geometry["type"] == "LineString"
