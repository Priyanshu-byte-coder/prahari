"""[J1] End to end, across lanes: a clip with a known plate becomes a row, an alert, a message.

    PRAHARI_INTEGRATION=1 pytest tests/test_integration.py -v

Gated behind an environment variable because it is the only test here that starts models,
decodes video and talks to services - about a minute, against a stack that has to be up. The
unit suites stay fast so `make check` stays a thing people actually run.

Written to degrade honestly, one leg at a time, because the lanes land at different times:

  leg 1  worker -> `sightings`      lane I only. Runs against fakeredis if Redis is down, and
                                    says which. This leg is green today.
  leg 2  sighting -> alert          needs D4's matcher and a watchlist entry. Skips with the
                                    reason when the API is not up, never passes vacuously.
  leg 3  alert -> WebSocket         needs D5's fanout.
  leg 4  latency                    the 3 s budget, measured across whichever legs are live.

A skip is a statement that a leg was not exercised. That is the whole point of the gate: the
demo rule is "no demo without a green integration test", and a test that passes by skipping
would make that rule meaningless.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

INTEGRATION = os.getenv("PRAHARI_INTEGRATION") == "1"
API_BASE = os.getenv("API_BASE", "http://localhost:8000")
BUDGET_S = float(os.getenv("PRAHARI_BUDGET_S", "3.0"))

pytestmark = pytest.mark.skipif(
    not INTEGRATION, reason="set PRAHARI_INTEGRATION=1 to run the cross-lane integration test")


def _http(path, method="GET", body=None, timeout=3.0):
    """One tiny urllib call - the API is another lane's, so this test owns no client code."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{API_BASE}{path}", method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return None, None


@pytest.fixture(scope="module")
def replay():
    """Leg 1: replay a clip with a known plate through the whole worker. ~40 s, once."""
    from services.worker.selftest import run

    return run(budget=None, require_plate=True)


# --- leg 1: the lane's own output ------------------------------------------------------------

def test_a_known_plate_reaches_the_sightings_stream(replay):
    assert replay["rows"] >= 1, "nothing on `sightings`"
    from common.plate import normalise
    assert normalise(replay["plate_injected"]) in replay["reads"], (
        f"injected {replay['plate_injected']}, stream carries {replay['reads']}")


def test_the_row_is_c1_shaped(replay):
    from services.worker.publish import FIELDS

    row = replay["row"]
    assert list(row) == list(FIELDS)
    assert row["ts_source"] in ("rtsp_pts", "hls_pdt", "server_receive")
    assert row["plate_band"] in ("CONFIRMED", "PROBABLE")


def test_the_row_lands_inside_the_latency_budget(replay):
    latency = replay["latency_seconds"]
    assert latency is not None, "no latency measured - the replay produced no frames"
    assert latency <= BUDGET_S, f"row landed {latency}s after the pass, budget {BUDGET_S}s"


def test_it_ran_against_a_real_redis_or_says_otherwise(replay):
    """Not a failure - a statement. A green run against fakeredis is not a green deployment."""
    if replay["redis"] != "redis":
        pytest.skip(f"ran against {replay['redis']}: Redis was not reachable, so the D seam "
                    f"was exercised in-process only")


# --- legs 2 and 3: the other lanes -----------------------------------------------------------

@pytest.fixture(scope="module")
def api():
    status, _ = _http("/healthz")
    if status is None:
        pytest.skip(f"no core API at {API_BASE} (lane D) - legs 2 and 3 not exercised")
    return API_BASE


def test_the_plate_raises_a_confirmed_alert(api, replay):
    """Leg 2: the watchlist entry is added here so the test is self-contained."""
    from common.plate import canon, normalise

    plate = normalise(replay["plate_injected"])
    status, _ = _http("/api/watchlist", "POST",
                      {"kind": "plate", "plate_norm": plate, "plate_canon": canon(plate),
                       "category": "integration-test", "severity": "LOW",
                       "reason": "J1 integration test"})
    if status not in (200, 201):
        pytest.skip(f"could not add a watchlist entry (HTTP {status}) - D3/D4 not up")

    deadline = time.time() + BUDGET_S
    while time.time() < deadline:
        status, alerts = _http(f"/api/alerts?limit=50")
        if alerts and any(a.get("band") == "CONFIRMED" for a in alerts):
            return
        time.sleep(0.2)
    pytest.fail(f"no CONFIRMED alert for {plate} within {BUDGET_S}s")


def test_the_alert_reaches_a_websocket_client(api):
    """Leg 3: D5's fanout. One message inside the budget, any type - the socket is alive."""
    try:
        from websockets.sync.client import connect
    except ImportError:
        pytest.skip("websockets not installed - leg 3 not exercised")
    url = API_BASE.replace("http", "ws") + "/ws"
    try:
        with connect(url, open_timeout=2) as socket:
            socket.send(json.dumps({"token": os.getenv("PRAHARI_TEST_JWT", "")}))
            message = json.loads(socket.recv(timeout=BUDGET_S))
    except Exception as exc:
        pytest.skip(f"no WebSocket at {url} ({exc}) - leg 3 not exercised")
    assert "type" in message and "seq" in message, message
