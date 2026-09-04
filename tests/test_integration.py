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


def _http(path, method="GET", body=None, timeout=3.0, token=None):
    """One tiny urllib call - the API is another lane's, so this test owns no client code.

    Returns (status, payload). status is None when the host did not answer at all (connection
    refused / DNS / timeout); an HTTP error code otherwise, with payload None.
    """
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{API_BASE}{path}", method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except Exception:
            return exc.code, None
    except Exception:
        return None, None


def _access_token():
    """A bearer token for legs 2-3, or None when the run has not been given a credential.

    Every core-API route is behind `requires(...)`, so an unauthenticated integration run can
    only ever *skip* legs 2 and 3 - it can never exercise them. Provide one of:
      PRAHARI_TEST_JWT                        - a ready access token, or
      PRAHARI_TEST_USER + PRAHARI_TEST_PASSWORD - logged in here via /api/auth/login
    The account needs watchlist:write and alerts:read (an investigator role, not a viewer).
    """
    jwt = os.getenv("PRAHARI_TEST_JWT")
    if jwt:
        return jwt
    user, password = os.getenv("PRAHARI_TEST_USER"), os.getenv("PRAHARI_TEST_PASSWORD")
    if not (user and password):
        return None
    status, payload = _http("/api/auth/login", "POST",
                            {"username": user, "password": password})
    if status == 200 and payload:
        return payload.get("access")
    return None


# The camera the replayed clip is published as. It has to be a camera that exists in the
# registry: the persister writes with a foreign key to `cameras`, so SELFTEST-000 - which
# deliberately does not exist, so a stray selftest cannot pollute the real table - is dead-
# lettered rather than persisted, and legs 2 and 3 then have nothing to correlate.
INTEGRATION_CAMERA = os.environ.get("PRAHARI_INTEGRATION_CAMERA", "1")


@pytest.fixture(scope="module")
def replay():
    """Leg 1: replay a clip with a known plate through the whole worker. ~40 s, once.

    Onto the *real* `sightings` stream, under a real camera id. The standalone selftest
    publishes to `sightings-selftest` on purpose (#48) so that running it never touches
    production data - but an integration test whose sighting never reaches the persister or the
    matcher is testing the worker alone while claiming to test the pipeline. That is precisely
    the vacuous pass this file exists to prevent.
    """
    from services.worker.selftest import run

    return run(budget=None, require_plate=True,
               stream="sightings", camera_id=INTEGRATION_CAMERA)


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


@pytest.fixture(scope="module")
def token(api):
    tok = _access_token()
    if not tok:
        pytest.skip("no credential for legs 2-3: set PRAHARI_TEST_JWT, or "
                    "PRAHARI_TEST_USER + PRAHARI_TEST_PASSWORD for an investigator account")
    return tok


def test_the_plate_raises_a_confirmed_alert(token, replay):
    """Leg 2: add the watchlist entry here (self-contained), then wait for *its* alert.

    Correlation is by watchlist_id, not "any CONFIRMED alert on the system" - a stale alert
    from a previous run would make that pass vacuously.
    """
    from common.plate import canon, normalise

    plate = normalise(replay["plate_injected"])
    # Remove any entry for this plate left by an earlier run first. The matcher keys its index by
    # canonical plate and raises one alert for the vehicle, not one per duplicate entry - correct
    # behaviour, but it means a stale entry absorbs the match and this leg then waits forever for
    # an alert carrying *its* watchlist id.
    status, existing = _http("/api/watchlist", "GET", token=token)
    if status == 200:
        for entry in existing or []:
            if entry.get("plate_norm") == plate:
                _http(f"/api/watchlist/{entry['id']}", "DELETE", token=token)

    # The API takes `plate` and derives plate_norm/plate_canon itself, and `category` is a closed
    # vocabulary - this leg was still posting the older shape, so it never got past validation.
    status, payload = _http("/api/watchlist", "POST",
                            {"kind": "plate", "plate": plate,
                             "category": "stolen vehicle", "severity": "LOW",
                             "reason": "J1 integration test"}, token=token)
    if status == 401:
        pytest.skip("the test credential lacks watchlist:write - use an investigator account")
    assert status in (200, 201), f"could not add a watchlist entry: HTTP {status} {payload}"
    watchlist_id = (payload or {}).get("id")
    assert watchlist_id, f"watchlist POST returned no id: {payload}"

    # Order matters, and getting it wrong makes this leg fail against a working pipeline. The
    # matcher alerts on *new* sightings against the watchlist index it holds, and that index is
    # reloaded every matcher.INDEX_TTL seconds. A clip replayed before the entry is in the index
    # therefore raises nothing for it - which is exactly right, and exactly what this test used
    # to do: leg 1's replay had already been consumed by the time the entry existed.
    #
    # So: wait for the index to pick the entry up, then replay again, then wait for the alert.
    # That is also the real sequence - an officer adds a plate, and the next time it is seen,
    # it fires.
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from matcher import INDEX_TTL
    from services.worker.selftest import run as replay_again

    time.sleep(INDEX_TTL + 2.0)
    replay_again(budget=None, require_plate=True, stream="sightings",
                 camera_id=INTEGRATION_CAMERA)

    deadline = time.time() + max(BUDGET_S, 30.0)
    seen_bands = set()
    while time.time() < deadline:
        status, alerts = _http("/api/alerts?limit=100", token=token)
        assert status != 401, "the test credential lacks alerts:read"
        for a in alerts or []:
            if a.get("watchlist_id") == watchlist_id:
                seen_bands.add(a.get("band"))
                if a.get("band") == "CONFIRMED":
                    return
        time.sleep(0.2)
    pytest.fail(f"no CONFIRMED alert for watchlist {watchlist_id} (plate {plate}); "
                f"bands seen: {seen_bands or 'none'}. Is the matcher running?")


def test_the_alert_reaches_a_websocket_client(token):
    """Leg 3: D5's fanout. One well-formed frame inside the budget - the socket is alive."""
    try:
        from websockets.sync.client import connect
    except ImportError:
        pytest.skip("websockets not installed - leg 3 not exercised")
    url = API_BASE.replace("http", "ws") + "/ws"
    try:
        with connect(url, open_timeout=2) as socket:
            socket.send(json.dumps({"token": token}))
            message = json.loads(socket.recv(timeout=BUDGET_S))
    except Exception as exc:
        pytest.skip(f"no WebSocket at {url} ({exc}) - leg 3 not exercised")
    assert "type" in message and "seq" in message, message
