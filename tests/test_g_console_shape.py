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
