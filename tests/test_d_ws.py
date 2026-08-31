"""D5's verify: connect, inject an alert, assert the push - then reconnect and assert the gap.

The reconnect half matters as much as the push. Consoles run on station wifi and on a laptop in
a car; a socket that drops and comes back with an empty panel is worse than polling, because the
operator cannot tell the difference between "nothing happened" and "I missed it".
"""

import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))

from websockets.exceptions import ConnectionClosed                    # noqa: E402
from websockets.sync.client import connect                            # noqa: E402

import ws as wsmod                                                    # noqa: E402
from store import Store                                              # noqa: E402
from ws import Hub, Scope, create_app, issue_token                    # noqa: E402

DSN = os.environ.get("TEST_POSTGRES_DSN",
                     os.environ.get("POSTGRES_DSN",
                                    "postgresql://sentinel:sentinel@localhost:5432/sentinel"))
REDIS_URL = os.environ.get("TEST_REDIS_URL",
                           os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


@pytest.fixture
def rig():
    """Two cameras in two departments, so scope has something to actually filter."""
    store = Store(dsn=DSN, redis_url=REDIS_URL)
    try:
        store.redis.ping()
        with store.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM cameras LIMIT 1")
    except Exception as exc:
        pytest.skip(f"needs a live Redis and a migrated Postgres: {exc}")

    tag = uuid.uuid4().hex[:8]
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO departments (code, name) VALUES (%s,%s) RETURNING id",
                    (f"D1{tag[:4]}", "traffic"))
        dept_a = cur.fetchone()[0]
        cur.execute("INSERT INTO departments (code, name) VALUES (%s,%s) RETURNING id",
                    (f"D2{tag[:4]}", "city police"))
        dept_b = cur.fetchone()[0]
        cur.execute("""INSERT INTO cameras (camera_id, name, owner_dept_id, district_code)
                       VALUES (%s,%s,%s,%s)""", (f"CAM-A-{tag}", "a", dept_a, "AHD"))
        cur.execute("""INSERT INTO cameras (camera_id, name, owner_dept_id, district_code)
                       VALUES (%s,%s,%s,%s)""", (f"CAM-B-{tag}", "b", dept_b, "SUR"))

    yield store, tag, dept_a, dept_b

    with store.conn as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM cameras WHERE camera_id IN (%s,%s)",
                    (f"CAM-A-{tag}", f"CAM-B-{tag}"))
        cur.execute("DELETE FROM departments WHERE id IN (%s,%s)", (dept_a, dept_b))
    store.close()


@contextmanager
def serving(store, hub=None):
    """Run the app on a real uvicorn server, in a thread, on a free port.

    Not starlette TestClient: it drives the app through a blocking portal, and a client thread
    parked in receive() starves the background task that reads Redis - the socket then only
    ever sees heartbeats. That is a property of the harness rather than of the app, but a test
    that cannot see a pushed frame proves nothing either way. A real server on a real event
    loop is also what the console will actually connect to.
    """
    import uvicorn

    app = create_app(store=store, hub=hub)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}/ws", app
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@contextmanager
def socket_at(url, token, timeout=10):
    with connect(url, open_timeout=timeout) as socket:
        socket.send(json.dumps({"token": token}))
        yield socket


def recv(socket, timeout=10):
    return json.loads(socket.recv(timeout=timeout))


def drain_until(socket, wanted, tries=20, timeout=10):
    """Read frames until one of the wanted type arrives. Heartbeats are noise here."""
    for _ in range(tries):
        frame = recv(socket, timeout=timeout)
        if frame["type"] in wanted:
            return frame
    raise AssertionError(f"no {wanted} frame arrived")


# --- scope, without a socket -------------------------------------------------------------

def test_scope_confines_an_operator_to_their_department():
    operator = Scope(user_id="1", role="OPERATOR", dept_id=7, district_code="AHD")
    assert operator.allows(7, "AHD") is True
    assert operator.allows(9, "AHD") is False           # another department, same district


def test_an_investigator_sees_the_state():
    assert Scope(user_id="2", role="INVESTIGATOR").allows(99, "SUR") is True


def test_a_system_admin_sees_no_live_data():
    # [C10]: config and audit only. The most privileged account is not the most visible one.
    assert Scope(user_id="3", role="SYSTEM_ADMIN", dept_id=7).allows(7, "AHD") is False


def test_an_unplaceable_camera_is_withheld():
    # No department on the camera and no district match: withhold. Showing it and apologising
    # afterwards is not available - the frame is already in the browser.
    assert Scope(user_id="4", role="OPERATOR", dept_id=7).allows(None, None) is False


# --- the socket ---------------------------------------------------------------------------

def test_a_socket_without_a_token_is_closed(rig):
    store, _tag, _a, _b = rig
    with serving(store) as (url, _app):
        with connect(url) as socket:
            socket.send(json.dumps({"hello": "no token here"}))
            with pytest.raises(ConnectionClosed):
                recv(socket)


def test_a_forged_token_is_closed(rig):
    # Signed, well formed, wrong key. This is the case that matters: a rejected socket must be
    # closed, not merely left receiving nothing.
    store, _tag, _a, _b = rig
    import jwt
    forged = jwt.encode({"sub": "9", "role": "INVESTIGATOR"}, "not-the-secret",
                        algorithm="HS256")
    with serving(store) as (url, _app):
        with socket_at(url, forged) as socket:
            with pytest.raises(ConnectionClosed):
                recv(socket)


def test_an_alert_on_the_stream_reaches_the_console(rig):
    store, tag, dept_a, _b = rig
    with serving(store) as (url, _app):
        with socket_at(url, issue_token(1, "OPERATOR", dept_id=dept_a)) as socket:
            assert recv(socket)["type"] == "ready"

            store.redis.xadd("alerts", {"data": json.dumps({
                "alert_id": 1, "watchlist_id": 1, "sighting_id": "01J6",
                "camera_id": f"CAM-A-{tag}", "band": "CONFIRMED", "state": "NEW",
                "count": 1, "pts": "2026-09-01T10:00:00+05:30"})})

            frame = drain_until(socket, {"alert.new"})
            assert frame["data"]["camera_id"] == f"CAM-A-{tag}"
            assert frame["seq"] >= 1


def test_the_server_filters_by_scope_not_the_client(rig):
    # An operator in department B must never see department A's camera on the wire. Filtering
    # in the browser would mean the frame was already delivered.
    store, tag, dept_a, dept_b = rig
    hub = Hub(store)
    hub.load_cameras()
    in_a = hub.subscribe(Scope(user_id="1", role="OPERATOR", dept_id=dept_a))
    in_b = hub.subscribe(Scope(user_id="2", role="OPERATOR", dept_id=dept_b))
    investigator = hub.subscribe(Scope(user_id="3", role="INVESTIGATOR"))

    hub.publish("alert.new", {"camera_id": f"CAM-A-{tag}", "alert_id": 1})

    assert in_a.queue.qsize() == 1
    assert in_b.queue.qsize() == 0
    assert investigator.queue.qsize() == 1


def test_resume_backfills_only_the_gap_and_only_in_scope(rig):
    store, tag, dept_a, dept_b = rig
    hub = Hub(store)
    hub.load_cameras()

    hub.publish("alert.new", {"camera_id": f"CAM-A-{tag}", "alert_id": 1})
    seen_up_to = hub.seq                                   # the console goes offline here
    hub.publish("alert.new", {"camera_id": f"CAM-A-{tag}", "alert_id": 2})
    hub.publish("alert.new", {"camera_id": f"CAM-B-{tag}", "alert_id": 3})
    hub.publish("camera.health", {"camera_id": f"CAM-A-{tag}", "health": "DOWN"})

    reconnected = hub.subscribe(Scope(user_id="1", role="OPERATOR", dept_id=dept_a))
    missed = hub.backfill(reconnected, since=seen_up_to)

    assert [f["seq"] for f in missed] == [seen_up_to + 1, seen_up_to + 3]
    assert [f["type"] for f in missed] == ["alert.new", "camera.health"]
    assert all(f["data"]["camera_id"] == f"CAM-A-{tag}" for f in missed)


def test_resume_over_a_real_socket(rig):
    store, tag, dept_a, _b = rig
    with serving(store) as (url, app):
        hub = app.state.hub
        token = issue_token(1, "OPERATOR", dept_id=dept_a)
        with socket_at(url, token) as socket:
            recv(socket)                                   # ready
            seen_up_to = hub.seq                           # the console drops off here

        store.redis.xadd("alerts", {"data": json.dumps({
            "alert_id": 42, "camera_id": f"CAM-A-{tag}", "band": "CONFIRMED",
            "state": "NEW", "count": 1, "pts": "2026-09-01T10:05:00+05:30"})})
        deadline = time.time() + 10
        while hub.seq == seen_up_to and time.time() < deadline:
            time.sleep(0.05)                               # it happened while nobody listened

        with socket_at(url, token) as socket:
            recv(socket)                                   # ready
            socket.send(json.dumps({"type": "resume", "since": seen_up_to}))
            frame = drain_until(socket, {"alert.new"})
            assert frame["data"]["alert_id"] == 42


def test_a_quiet_socket_still_gets_a_heartbeat(rig, monkeypatch):
    # 15 s in production; a quiet grid at 3 a.m. is indistinguishable from a dead TCP connection
    # without it. Shortened here so the test is not a 15-second wait.
    store, _tag, dept_a, _b = rig
    monkeypatch.setattr(wsmod, "HEARTBEAT_S", 0.2)
    with serving(store) as (url, _app):
        with socket_at(url, issue_token(1, "OPERATOR", dept_id=dept_a)) as socket:
            assert recv(socket)["type"] == "ready"
            assert recv(socket)["type"] == "ping"


def test_a_slow_console_is_dropped_not_waited_on(rig):
    # One console on a bad link must not stall the fanout for everyone else.
    store, tag, dept_a, _b = rig
    hub = Hub(store)
    hub.load_cameras()
    slow = hub.subscribe(Scope(user_id="1", role="INVESTIGATOR"))
    slow.queue._maxsize = 2
    for i in range(5):
        hub.publish("alert.new", {"camera_id": f"CAM-A-{tag}", "alert_id": i})
    assert slow.dropped >= 1
    assert hub.seq >= 5                                    # the hub kept going
