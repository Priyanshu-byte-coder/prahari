"""The console's camera payload has to be the shape the map and [C4] both expect.

The failure this catches is silent and looks like an outage: coordinates present in the payload,
nested one level too deep, so `web/map.js` filters every camera out as unplaced and the operator
sees "30 cameras, 0 placed" over an empty map.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

console_serve = pytest.importorskip("console_serve",
                                    reason="console_serve needs the gateway deps installed")


def test_cameras_carry_lat_and_lon_at_the_top_level():
    cameras = console_serve.load_cameras()
    assert cameras, "no cameras in data/cameras.seed.json"
    placed = [c for c in cameras if c.get("lat") is not None and c.get("lon") is not None]
    assert placed, "every camera came back unplaced - the map would draw nothing"
    assert len(placed) >= len(cameras) // 2


def test_the_nested_geo_block_is_still_there():
    # web/geo_helper.html edits `geo`; flattening must add fields, not move them.
    camera = console_serve.load_cameras()[0]
    assert "geo" in camera
    if camera["geo"].get("lat") is not None:
        assert camera["lat"] == camera["geo"]["lat"]


def test_the_audit_tab_is_proxied_under_the_admin_account():
    # [C10] splits these: admin:audit is SYSTEM_ADMIN only, and SYSTEM_ADMIN may not see live
    # data. One account for both is a console whose Admin view answers 403 forever.
    assert console_serve.account_for("admin/audit") == "audit"
    assert console_serve.account_for("admin/audit/verify") == "audit"
    assert console_serve.account_for("cameras") == "live"
    assert console_serve.account_for("route?plate=GJ01AB1234") == "live"


def test_scoped_cameras_passes_the_apis_refusal_through(monkeypatch):
    # [#44] a SYSTEM_ADMIN gets 403 on /api/cameras per [C10]; the console must
    # not answer around that with the full local seed.
    monkeypatch.setattr(console_serve, "OFFLINE", False)
    monkeypatch.setattr(console_serve, "api_call",
                        lambda *a, **k: (403, {"detail": "system admin may not view live data"}))
    status, payload = console_serve.scoped_cameras()
    assert status == 403
    assert payload["detail"]


def test_scoped_cameras_filters_the_seed_to_the_apis_allow_list(monkeypatch):
    monkeypatch.setattr(console_serve, "OFFLINE", False)
    seed = console_serve.load_cameras()
    keep = str(seed[0]["camera_id"])
    monkeypatch.setattr(console_serve, "api_call",
                        lambda *a, **k: (200, [{"camera_id": keep}]))
    status, payload = console_serve.scoped_cameras()
    assert status == 200
    assert [str(c["camera_id"]) for c in payload] == [keep]
    assert "geo" in payload[0]  # geo shaping survives the filter


def test_offline_flag_serves_the_full_local_seed(monkeypatch):
    monkeypatch.setattr(console_serve, "OFFLINE", True)
    status, payload = console_serve.scoped_cameras()
    assert status == 200
    assert len(payload) == len(console_serve.load_cameras())


def test_no_admin_password_means_a_clear_answer_not_a_wrong_403(monkeypatch):
    monkeypatch.setattr(console_serve, "ADMIN_PASS", "")
    monkeypatch.setitem(console_serve.ACCOUNTS, "audit", ("console-audit", ""))
    monkeypatch.setitem(console_serve._TOKENS, "audit", {"value": None, "exp": 0.0})
    status, payload = console_serve.api_call("GET", "admin/audit")
    assert status == 503
    assert "audit account" in payload["detail"]


def test_a_refused_rtsp_stops_being_retried():
    # [#57] The grid answers 401 on RTSP for our IP. Alternating into it anyway spends half of
    # every retry cycle on a guaranteed rejection, and the wall takes minutes to fill.
    from services.gateway.wall import RTSP_AUTH_GIVE_UP, _is_auth_failure

    assert _is_auth_failure(RuntimeError("Server returned 401 Unauthorized")) is True
    assert _is_auth_failure(Exception("HTTPUnauthorizedError: authorization failed")) is True
    assert _is_auth_failure(TimeoutError("Connection timed out")) is False
    assert RTSP_AUTH_GIVE_UP >= 1


def test_the_wall_holds_a_bounded_number_of_connections():
    # The grid gives every client its own copy of the stream and enforces one session per IP.
    # Asking it for thirty at once got most of them refused - which read as "22 cameras down"
    # and was really us being rude. Probed one at a time, all thirty answer.
    from services.gateway.wall import WALL_MAX_OPEN, WALL_SLOT_S, WALL_STAGGER_S

    assert 1 <= WALL_MAX_OPEN <= 12, "a whole 30-camera wall at once is what broke this"
    assert WALL_SLOT_S > 0 and WALL_STAGGER_S >= 0


def test_the_wall_can_re_authenticate_mid_run():
    # One session per IP means somebody else signing in takes ours, and a wall holding the dead
    # cookie retries forever against a session the server has forgotten. Headers are therefore
    # resolved per connection, not captured once at startup.
    from services.gateway.wall import Wall

    calls = []

    def headers():
        calls.append(1)
        return f"Cookie: session-{len(calls)}\r\n"

    wall = Wall([], headers=headers)
    assert wall.headers != wall.headers, "a callable must be re-resolved on every connection"
    assert len(calls) >= 2

    static = Wall([], headers="Cookie: fixed\r\n")
    assert static.headers == "Cookie: fixed\r\n"
