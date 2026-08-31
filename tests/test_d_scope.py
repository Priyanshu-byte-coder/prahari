"""D7's verify: log in as a Transport viewer and get back Transport's rows and nothing else.

Cameras, watchlist and alerts each get the same treatment, because the failure this test exists
to catch is per-endpoint: a scope applied in three places out of four is a system with a hole in
it, and the hole is discovered by whoever finds it first.

The tests go through HTTP with a real token rather than calling the repositories directly. That
is the point - the question is not "does the SQL filter" but "can a logged-in user reach another
department's rows", and only the whole path answers that.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import audit as audit_module                                          # noqa: E402
import fake_sightings as fs                                           # noqa: E402
from alerts import AlertRepo                                          # noqa: E402
from auth import (ACCESS_TTL_S, REFRESH_TTL_S, AuthError, UserRepo,   # noqa: E402
                  hash_password, issue_tokens, scope_from_token, verify_password)
from main import create_app                                           # noqa: E402
from scope import (DEPT_ADMIN, INVESTIGATOR, OPERATOR, SYSTEM_ADMIN,  # noqa: E402
                   VIEWER, Scope)
from store import Store                                               # noqa: E402
from watchlist import WatchlistRepo, validate_row                     # noqa: E402

DSN = os.environ.get("TEST_POSTGRES_DSN",
                     os.environ.get("POSTGRES_DSN", "postgresql://localhost:5432/sentinel"))
REDIS_URL = os.environ.get("TEST_REDIS_URL",
                           os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

PASSWORD = "correct-horse-battery"


@pytest.fixture
def world():
    """Two departments - Transport and Police - each with a camera, a watchlist entry, an alert
    and a viewer. Everything a scope could leak across."""
    store = Store(dsn=DSN, redis_url=REDIS_URL)
    try:
        store.redis.ping()
        with store.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users LIMIT 1")
    except Exception as exc:
        pytest.skip(f"needs a live Redis and a migrated Postgres: {exc}")

    tag = uuid.uuid4().hex[:6]
    made = {"tag": tag, "store": store}
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO departments (code,name) VALUES (%s,%s) RETURNING id",
                    (f"TRN{tag}", "Transport"))
        made["transport"] = cur.fetchone()[0]
        cur.execute("INSERT INTO departments (code,name) VALUES (%s,%s) RETURNING id",
                    (f"POL{tag}", "Police"))
        made["police"] = cur.fetchone()[0]
        for label, dept in (("TRN", made["transport"]), ("POL", made["police"])):
            cur.execute("""INSERT INTO cameras (camera_id, name, owner_dept_id, district_code)
                           VALUES (%s,%s,%s,%s)""",
                        (f"{label}-{tag}", f"{label} camera", dept, "AHD"))

    users = UserRepo(store)
    made["viewer"] = users.create(f"trn-viewer-{tag}", PASSWORD, VIEWER,
                                  dept_id=made["transport"], district_code="AHD")
    made["operator"] = users.create(f"trn-op-{tag}", PASSWORD, OPERATOR,
                                    dept_id=made["transport"], district_code="AHD")
    made["police_op"] = users.create(f"pol-op-{tag}", PASSWORD, OPERATOR,
                                     dept_id=made["police"], district_code="AHD")
    made["investigator"] = users.create(f"inv-{tag}", PASSWORD, INVESTIGATOR)
    made["sysadmin"] = users.create(f"sys-{tag}", PASSWORD, SYSTEM_ADMIN)

    watchlist = WatchlistRepo(store)
    made["wl_transport"] = watchlist.add(
        validate_row({"kind": "plate", "plate": "GJ01TR0001", "category": "stolen vehicle",
                      "reason": f"transport {tag}", "severity": "HIGH"}),
        owner_dept_id=made["transport"])
    made["wl_police"] = watchlist.add(
        validate_row({"kind": "plate", "plate": "GJ01PL0002", "category": "wanted person",
                      "reason": f"police {tag}", "severity": "CRITICAL"}),
        owner_dept_id=made["police"])

    alerts = AlertRepo(store)
    import random
    rng = random.Random(9)
    for label, watchlist_id in (("TRN", made["wl_transport"]), ("POL", made["wl_police"])):
        sighting = fs.finish_bbox(
            fs.sighting(rng, f"{label}-{tag}", datetime.now(fs.IST), "GJ01AB1234"), rng)
        alerts.raise_alert(watchlist_id=watchlist_id, sighting=sighting, band="CONFIRMED")

    yield made

    with store.conn as conn, conn.cursor() as cur:
        cameras = [f"TRN-{tag}", f"POL-{tag}"]
        cur.execute("DELETE FROM alert_events WHERE alert_id IN "
                    "(SELECT id FROM alerts WHERE camera_id = ANY(%s))", (cameras,))
        cur.execute("DELETE FROM alerts WHERE camera_id = ANY(%s)", (cameras,))
        cur.execute("DELETE FROM cameras WHERE camera_id = ANY(%s)", (cameras,))
        cur.execute("DELETE FROM watchlist WHERE id = ANY(%s)",
                    ([made["wl_transport"], made["wl_police"]],))
        cur.execute("DELETE FROM users WHERE username LIKE %s", (f"%-{tag}",))
        cur.execute("DELETE FROM departments WHERE id = ANY(%s)",
                    ([made["transport"], made["police"]],))
    for key in store.redis.scan_iter("alert:dedup:*"):
        store.redis.delete(key)
    store.close()


@pytest.fixture
def client(world):
    return TestClient(create_app(store=world["store"]))


def login(client, username, password=PASSWORD):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --- the ticket's verify -----------------------------------------------------------------------

def test_a_transport_viewer_sees_only_transport_cameras(client, world):
    tokens = login(client, f"trn-viewer-{world['tag']}")
    rows = client.get("/api/cameras", headers=bearer(tokens["access"])).json()
    ids = [row["camera_id"] for row in rows]
    assert f"TRN-{world['tag']}" in ids
    assert f"POL-{world['tag']}" not in ids
    assert all(row["owner_dept_id"] == world["transport"] for row in rows)


def test_a_transport_operator_sees_only_transport_watchlist_entries(client, world):
    tokens = login(client, f"trn-op-{world['tag']}")
    rows = client.get("/api/watchlist", headers=bearer(tokens["access"])).json()
    ids = [row["id"] for row in rows]
    assert world["wl_transport"] in ids
    assert world["wl_police"] not in ids


def test_a_transport_operator_sees_only_alerts_from_transport_cameras(client, world):
    tokens = login(client, f"trn-op-{world['tag']}")
    rows = client.get("/api/alerts", headers=bearer(tokens["access"])).json()
    cameras = {row["camera_id"] for row in rows}
    assert f"POL-{world['tag']}" not in cameras


def test_an_investigator_sees_both_departments(client, world):
    tokens = login(client, f"inv-{world['tag']}")
    ids = [row["camera_id"] for row in
           client.get("/api/cameras", headers=bearer(tokens["access"])).json()]
    assert {f"TRN-{world['tag']}", f"POL-{world['tag']}"} <= set(ids)


def test_the_system_admin_cannot_view_video_or_detections(client, world):
    # [C10]'s deliberate last row, and the one worth saying on a slide: the most privileged
    # account in the system administers it and cannot watch it.
    tokens = login(client, f"sys-{world['tag']}")
    assert client.get("/api/cameras", headers=bearer(tokens["access"])).status_code == 403
    assert client.get("/api/alerts", headers=bearer(tokens["access"])).status_code == 403
    assert client.get("/api/admin/audit", headers=bearer(tokens["access"])).status_code == 200


def test_a_viewer_cannot_read_or_write_the_watchlist(client, world):
    tokens = login(client, f"trn-viewer-{world['tag']}")
    assert client.get("/api/watchlist", headers=bearer(tokens["access"])).status_code == 403
    response = client.post("/api/watchlist", headers=bearer(tokens["access"]),
                           json={"kind": "plate", "plate": "GJ01XX0001",
                                 "category": "suspect", "reason": "x", "severity": "LOW"})
    assert response.status_code == 403


def test_an_operator_cannot_write_the_watchlist_but_can_read_it(client, world):
    # [C10]: Operator has WL read, no WL write.
    tokens = login(client, f"trn-op-{world['tag']}")
    assert client.get("/api/watchlist", headers=bearer(tokens["access"])).status_code == 200
    assert client.post("/api/watchlist", headers=bearer(tokens["access"]),
                       json={"kind": "plate", "plate": "GJ01XX0002", "category": "suspect",
                             "reason": "x", "severity": "LOW"}).status_code == 403


# --- tokens --------------------------------------------------------------------------------

def test_no_token_is_401_not_an_empty_list(client):
    # An unauthenticated request that returns [] looks like "nothing to see" and hides the bug.
    assert client.get("/api/cameras").status_code == 401


def test_a_refresh_token_is_not_an_access_token(client, world):
    tokens = login(client, f"trn-op-{world['tag']}")
    assert client.get("/api/cameras",
                      headers=bearer(tokens["refresh"])).status_code == 401


def test_refresh_returns_a_fresh_access_token(client, world):
    tokens = login(client, f"trn-op-{world['tag']}")
    response = client.post("/api/auth/refresh", json={"refresh": tokens["refresh"]})
    assert response.status_code == 200
    assert client.get("/api/cameras",
                      headers=bearer(response.json()["access"])).status_code == 200


def test_the_access_token_is_short_and_the_refresh_token_is_one_shift():
    assert ACCESS_TTL_S == 15 * 60
    assert REFRESH_TTL_S == 8 * 3600


def test_a_wrong_password_is_401(client, world):
    response = client.post("/api/auth/login",
                           json={"username": f"trn-op-{world['tag']}", "password": "wrong"})
    assert response.status_code == 401


def test_an_unknown_user_and_a_wrong_password_are_indistinguishable(client, world):
    unknown = client.post("/api/auth/login",
                          json={"username": "nobody-at-all", "password": "wrong"})
    wrong = client.post("/api/auth/login",
                        json={"username": f"trn-op-{world['tag']}", "password": "wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_passwords_are_argon2_hashes_not_the_password():
    stored = hash_password(PASSWORD)
    assert stored.startswith("$argon2")
    assert PASSWORD not in stored
    assert verify_password(stored, PASSWORD) and not verify_password(stored, PASSWORD + "!")


def test_a_short_password_is_refused():
    with pytest.raises(ValueError):
        hash_password("short")


def test_a_forged_token_does_not_open_anything(client):
    import jwt
    forged = jwt.encode({"sub": "1", "role": "INVESTIGATOR", "typ": "access"},
                        "not-the-secret", algorithm="HS256")
    assert client.get("/api/cameras", headers=bearer(forged)).status_code == 401


def test_a_disabled_account_cannot_log_in(client, world):
    store = world["store"]
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET active = false WHERE username = %s",
                    (f"trn-op-{world['tag']}",))
    response = client.post("/api/auth/login",
                           json={"username": f"trn-op-{world['tag']}", "password": PASSWORD})
    assert response.status_code == 401


# --- the scope object itself ------------------------------------------------------------------

def test_a_user_with_no_department_matches_nothing():
    # A misconfigured account should see nothing, not everything.
    lost = Scope(user_id="1", role=OPERATOR, dept_id=None)
    filters = lost.department_filter()
    assert filters == {"all_departments": False, "departments": []}
    assert lost.allows_department(7) is False


def test_capabilities_follow_c10():
    assert Scope(role=VIEWER).can("live") and not Scope(role=VIEWER).can("watchlist:read")
    assert Scope(role=OPERATOR).can("watchlist:read")
    assert not Scope(role=OPERATOR).can("watchlist:write")
    assert Scope(role=INVESTIGATOR).can("export")
    assert not Scope(role=OPERATOR).can("export")
    assert Scope(role=DEPT_ADMIN).can("admin:users")
    assert not Scope(role=DEPT_ADMIN).can("admin:audit")
    assert Scope(role=SYSTEM_ADMIN).can("admin:audit")
    assert not Scope(role=SYSTEM_ADMIN).can("live")


# --- audit ------------------------------------------------------------------------------------

def test_a_live_view_is_audited(client, world):
    # Reading is the abuse worth catching: an officer looking up an ex-partner's car leaves no
    # other trace.
    store = world["store"]
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log WHERE action = 'camera.list'")
        before = cur.fetchone()[0]
    tokens = login(client, f"trn-op-{world['tag']}")
    client.get("/api/cameras", headers=bearer(tokens["access"]))
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log WHERE action = 'camera.list'")
        assert cur.fetchone()[0] == before + 1


def test_the_audit_chain_verifies(client, world):
    tokens = login(client, f"sys-{world['tag']}")
    body = client.get("/api/admin/audit/verify", headers=bearer(tokens["access"])).json()
    assert body["ok"] is True and body["first_broken_seq"] is None and body["checked"] > 0


def test_a_tampered_row_is_found_by_the_verifier(world):
    # The chain does not prevent tampering; it makes tampering visible, which is the achievable
    # property. D10 is this endpoint.
    store = world["store"]
    audit_module.record(store, action="test.marker", object_type="test", object_id="1",
                        reason="an untampered row")
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT seq, reason FROM audit_log ORDER BY seq DESC LIMIT 1")
        seq, original = cur.fetchone()
        cur.execute("UPDATE audit_log SET reason = 'edited afterwards' WHERE seq = %s", (seq,))
    try:
        result = audit_module.AuditLog(store).verify()
        assert result["ok"] is False and result["first_broken_seq"] == seq
    finally:
        # Restore rather than delete: deleting a row breaks the chain for every later run, which
        # is the same failure this test is checking for.
        with store.conn as conn, conn.cursor() as cur:
            cur.execute("UPDATE audit_log SET reason = %s WHERE seq = %s", (original, seq))


def test_an_action_that_needs_a_reason_cannot_be_logged_without_one(world):
    with pytest.raises(ValueError, match="requires a reason"):
        audit_module.record(world["store"], action="route.export", object_type="route",
                            object_id="GJ01AB1234")
