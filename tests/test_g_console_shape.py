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


def test_no_admin_password_means_a_clear_answer_not_a_wrong_403(monkeypatch):
    monkeypatch.setattr(console_serve, "ADMIN_PASS", "")
    monkeypatch.setitem(console_serve.ACCOUNTS, "audit", ("console-audit", ""))
    monkeypatch.setitem(console_serve._TOKENS, "audit", {"value": None, "exp": 0.0})
    status, payload = console_serve.api_call("GET", "admin/audit")
    assert status == 503
    assert "audit account" in payload["detail"]
