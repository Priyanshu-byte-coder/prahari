"""load_registry joins two files lane G owns and that routinely disagree with each other.

The join is the whole ticket: what it must never do is fail because G6 has not surveyed a
camera yet, and what it must always do is say which cameras it could not place on the map.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import load_registry as lr  # noqa: E402

SEED = [
    {"camera_id": "GJ-AHD-0001", "name": "CG Road junction", "district_code": "AHD",
     "install_type": "FIX", "driver": "mediamtx",
     "transports": {"rtsp": "rtsp://h:8554/s/1", "hls": "http://h/live/s/1/index.m3u8"}},
    {"camera_id": "GJ-AHD-0002", "name": "Ashram Road", "district_code": "AHD",
     "install_type": "PTZ", "driver": "rtsp", "transports": {"rtsp": "rtsp://h:8554/s/2"}},
]
GEO = {
    "GJ-AHD-0001": {"lat": 23.0225, "lon": 72.5714, "bearing_deg": 135, "fov_deg": 70,
                    "range_m": 60, "coord_source": "manual", "coord_conf": "HIGH"},
}


def test_joins_geo_onto_the_seed():
    rows, _ = lr.build_rows(SEED, GEO)
    first = {r["camera_id"]: r for r in rows}["GJ-AHD-0001"]
    assert (first["lat"], first["lon"], first["bearing_deg"]) == (23.0225, 72.5714, 135)
    assert json.loads(first["transports"])["rtsp"] == "rtsp://h:8554/s/1"


def test_camera_without_geo_still_loads_but_is_warned_about():
    rows, warnings = lr.build_rows(SEED, GEO)
    assert len(rows) == 2                                   # nothing is dropped
    second = {r["camera_id"]: r for r in rows}["GJ-AHD-0002"]
    assert second["lat"] is None and second["name"] == "Ashram Road"
    assert any("GJ-AHD-0002" in w and "no coordinates" in w for w in warnings)


def test_missing_geo_file_is_not_an_error():
    rows, warnings = lr.build_rows(SEED, {})
    assert len(rows) == 2
    assert sum("no coordinates" in w for w in warnings) == 2


def test_stale_geo_ids_are_named():
    _, warnings = lr.build_rows(SEED, {**GEO, "GJ-SUR-9999": {"lat": 21.1, "lon": 72.8}})
    assert any("GJ-SUR-9999" in w for w in warnings)


def test_district_centroid_coordinates_are_flagged():
    # G6's gotcha: a centroid places every camera in a district on the same pixel, and the
    # route demo then draws a car teleporting. Storing it is fine; demoing on it is not.
    geo = {"GJ-AHD-0001": {"lat": 23.0, "lon": 72.5,
                           "coord_source": "district_centroid", "coord_conf": "LOW"}}
    rows, warnings = lr.build_rows(SEED[:1], geo)
    assert rows[0]["lat"] == 23.0                            # still loaded
    assert any("district_centroid" in w for w in warnings)


def test_seed_entry_without_an_id_is_skipped_not_fatal():
    rows, warnings = lr.build_rows(SEED + [{"name": "nameless"}], GEO)
    assert len(rows) == 2
    assert any("without camera_id" in w for w in warnings)


def test_unreadable_files_are_reported_as_absent(tmp_path, capsys):
    bad = tmp_path / "cameras.seed.json"
    bad.write_text("{not json", encoding="utf-8")
    assert lr.read_json(bad, list, "cameras.seed.json") is None
    assert lr.read_json(tmp_path / "gone.json", dict, "camera_geo.json") is None
    assert "not valid JSON" in capsys.readouterr().out


def test_wrong_shape_is_reported(tmp_path, capsys):
    # [C8] says the seed is a list and the geo is a dict. A swapped pair is a G-side mistake
    # worth naming, not a traceback.
    p = tmp_path / "cameras.seed.json"
    p.write_text('{"GJ-AHD-0001": {}}', encoding="utf-8")
    assert lr.read_json(p, list, "cameras.seed.json") is None
    assert "expected list" in capsys.readouterr().out
