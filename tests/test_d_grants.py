"""D9: cross-department access that is purpose-bound, time-boxed, approved elsewhere, and logged.

Each of those four is a separate way this can go wrong, so each gets a test. The one that
matters most is the last: a grant that widens access without leaving a trail is the design this
ticket exists to replace.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))

from auth import UserRepo                                             # noqa: E402
from grants import MAX_DURATION, GrantError, GrantRepo, widen         # noqa: E402
from main import create_app                                           # noqa: E402
from scope import DEPT_ADMIN, INVESTIGATOR, OPERATOR                  # noqa: E402
from store import Store                                               # noqa: E402

DSN = os.environ.get("TEST_POSTGRES_DSN",
                     os.environ.get("POSTGRES_DSN", "postgresql://localhost:5432/sentinel"))
REDIS_URL = os.environ.get("TEST_REDIS_URL",
                           os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
PASSWORD = "correct-horse-battery"


@pytest.fixture
def world():
    store = Store(dsn=DSN, redis_url=REDIS_URL)
    try:
        with store.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM access_grants LIMIT 1")
    except Exception as exc:
        pytest.skip(f"needs a migrated Postgres: {exc}")

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
    made["trn_admin"] = users.create(f"trn-admin-{tag}", PASSWORD, DEPT_ADMIN,
                                     dept_id=made["transport"], district_code="AHD")
    made["pol_admin"] = users.create(f"pol-admin-{tag}", PASSWORD, DEPT_ADMIN,
                                     dept_id=made["police"], district_code="AHD")
    made["trn_op"] = users.create(f"trn-op-{tag}", PASSWORD, OPERATOR,
                                  dept_id=made["transport"], district_code="AHD")
    made["investigator"] = users.create(f"inv-{tag}", PASSWORD, INVESTIGATOR)

    yield made

    with store.conn as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM access_grants WHERE target_dept_id = ANY(%s)",
                    ([made["transport"], made["police"]],))
        cur.execute("DELETE FROM cameras WHERE camera_id = ANY(%s)",
                    ([f"TRN-{tag}", f"POL-{tag}"],))
        cur.execute("DELETE FROM users WHERE username LIKE %s", (f"%-{tag}",))
        cur.execute("DELETE FROM departments WHERE id = ANY(%s)",
                    ([made["transport"], made["police"]],))
    store.close()


@pytest.fixture
def client(world):
    return TestClient(create_app(store=world["store"]))


def login(client, username):
    response = client.post("/api/auth/login",
                           json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access']}"}


def camera_ids(client, headers):
    return [row["camera_id"] for row in client.get("/api/cameras", headers=headers).json()]


# --- the flow ---------------------------------------------------------------------------------

def test_a_request_alone_opens_nothing(client, world):
    admin = login(client, f"trn-admin-{world['tag']}")
    response = client.post("/api/grants", headers=admin,
                           json={"target_dept_id": world["police"], "case_no": "FIR 0123/2026",
                                 "reason": "vehicle seen leaving the scene", "hours": 24})
    assert response.status_code == 200
    assert response.json()["state"] == "REQUESTED"
    assert f"POL-{world['tag']}" not in camera_ids(client, admin)   # not yet, and not by asking


def test_approval_by_the_owning_department_opens_it(client, world):
    admin = login(client, f"trn-admin-{world['tag']}")
    grant = client.post("/api/grants", headers=admin,
                        json={"target_dept_id": world["police"], "case_no": "FIR 0123/2026",
                              "reason": "vehicle seen leaving the scene"}).json()

    police = login(client, f"pol-admin-{world['tag']}")
    approved = client.post(f"/api/grants/{grant['id']}/approve", headers=police)
    assert approved.status_code == 200 and approved.json()["state"] == "APPROVED"

    ids = camera_ids(client, admin)
    assert {f"TRN-{world['tag']}", f"POL-{world['tag']}"} <= set(ids)


def test_the_requester_cannot_approve_their_own_grant(client, world):
    admin = login(client, f"trn-admin-{world['tag']}")
    grant = client.post("/api/grants", headers=admin,
                        json={"target_dept_id": world["transport"], "case_no": "FIR 1/2026",
                              "reason": "self-approval attempt"}).json()
    assert client.post(f"/api/grants/{grant['id']}/approve", headers=admin).status_code == 403


def test_only_the_target_department_can_approve(client, world):
    investigator = login(client, f"inv-{world['tag']}")
    grant = client.post("/api/grants", headers=investigator,
                        json={"target_dept_id": world["police"], "case_no": "FIR 2/2026",
                              "reason": "cross-check"}).json()
    transport = login(client, f"trn-admin-{world['tag']}")
    assert client.post(f"/api/grants/{grant['id']}/approve",
                       headers=transport).status_code == 403


def test_an_operator_cannot_request_cross_department_access(client, world):
    operator = login(client, f"trn-op-{world['tag']}")
    assert client.post("/api/grants", headers=operator,
                       json={"target_dept_id": world["police"], "case_no": "FIR 3/2026",
                             "reason": "curiosity"}).status_code == 403


def test_a_grant_without_a_case_number_is_refused(client, world):
    admin = login(client, f"trn-admin-{world['tag']}")
    response = client.post("/api/grants", headers=admin,
                           json={"target_dept_id": world["police"], "case_no": "  ",
                                 "reason": "no case"})
    assert response.status_code == 400


def test_a_grant_without_a_reason_is_refused(client, world):
    admin = login(client, f"trn-admin-{world['tag']}")
    response = client.post("/api/grants", headers=admin,
                           json={"target_dept_id": world["police"], "case_no": "FIR 4/2026",
                                 "reason": ""})
    assert response.status_code == 400


def test_a_grant_longer_than_seventy_two_hours_is_refused(client, world):
    admin = login(client, f"trn-admin-{world['tag']}")
    response = client.post("/api/grants", headers=admin,
                           json={"target_dept_id": world["police"], "case_no": "FIR 5/2026",
                                 "reason": "long haul", "hours": 96})
    assert response.status_code == 400
    assert MAX_DURATION == timedelta(hours=72)


def test_approving_twice_is_a_409(client, world):
    admin = login(client, f"trn-admin-{world['tag']}")
    grant = client.post("/api/grants", headers=admin,
                        json={"target_dept_id": world["police"], "case_no": "FIR 6/2026",
                              "reason": "double approval"}).json()
    police = login(client, f"pol-admin-{world['tag']}")
    assert client.post(f"/api/grants/{grant['id']}/approve", headers=police).status_code == 200
    assert client.post(f"/api/grants/{grant['id']}/approve", headers=police).status_code == 409


# --- expiry and the trail ----------------------------------------------------------------------

def test_an_expired_grant_stops_widening_without_anybody_revoking_it(world):
    # Expiry is a query, not a cron job: nothing has to run for access to end.
    store = world["store"]
    repo = GrantRepo(store)
    grant_id = repo.request(requester=world["trn_admin"], target_dept_id=world["police"],
                            case_no="FIR 7/2026", reason="expiring soon", hours=1)
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("""UPDATE access_grants SET state = 'APPROVED', approved_by = %s,
                              expires = %s WHERE id = %s""",
                    (world["pol_admin"], datetime.now(timezone.utc) - timedelta(minutes=1),
                     grant_id))
    assert repo.active_for(world["trn_admin"]) == []


def test_every_read_under_a_grant_names_the_grant_and_the_case(client, world):
    store = world["store"]
    admin = login(client, f"trn-admin-{world['tag']}")
    grant = client.post("/api/grants", headers=admin,
                        json={"target_dept_id": world["police"], "case_no": "FIR 8/2026",
                              "reason": "audited read"}).json()
    police = login(client, f"pol-admin-{world['tag']}")
    client.post(f"/api/grants/{grant['id']}/approve", headers=police)

    client.get("/api/cameras", headers=admin)

    with store.conn as conn, conn.cursor() as cur:
        cur.execute("""SELECT grant_id, reason FROM audit_log
                       WHERE action = 'camera.list' AND grant_id = %s
                       ORDER BY seq DESC LIMIT 1""", (grant["id"],))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == grant["id"] and "FIR 8/2026" in row[1]


def test_a_grant_widens_departments_and_nothing_else(world):
    # An operator with a grant is still an operator: the grant moves the department boundary,
    # not the capability boundary.
    from scope import Scope

    store = world["store"]
    repo = GrantRepo(store)
    grant_id = repo.request(requester=world["trn_op"], target_dept_id=world["police"],
                            case_no="FIR 9/2026", reason="capability check", hours=2)
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("UPDATE access_grants SET state = 'APPROVED', approved_by = %s WHERE id = %s",
                    (world["pol_admin"], grant_id))

    operator = Scope(user_id=str(world["trn_op"]), role=OPERATOR, dept_id=world["transport"])
    widened, active = widen(operator, repo)
    assert [g["id"] for g in active] == [grant_id]
    assert set(widened.department_filter()["departments"]) == {world["transport"],
                                                               world["police"]}
    assert widened.can("watchlist:write") is False       # still an operator
    assert widened.can("export") is False


def test_the_repository_refuses_a_grant_for_a_missing_id(world):
    repo = GrantRepo(world["store"])
    from scope import Scope
    admin = Scope(user_id=str(world["pol_admin"]), role=DEPT_ADMIN, dept_id=world["police"])
    with pytest.raises(GrantError) as caught:
        repo.decide(9_999_999, approver_scope=admin)
    assert caught.value.status_code == 404
