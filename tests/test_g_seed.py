"""G1 — the camera seed and the pure helpers that build it.

The seed is the file every other lane reads to learn which cameras exist, so a
row that drifts out of [C8] shape breaks two other people silently. These tests
pin the shape and the three judgement calls that are easy to "tidy" into
something wrong later: districts are never guessed, failed probes never
contribute properties, and the catalogue never overrides a measurement.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import probe_grid  # noqa: E402

SEED = ROOT / "data" / "cameras.seed.json"

# [C8], TASK.md §C. Every key here is load-bearing for another lane.
C8_KEYS = {
    "camera_id", "name", "district_code", "install_type", "driver",
    "codec", "resolution", "fps", "transports", "transport_probe",
}


@pytest.fixture(scope="module")
def seed() -> list[dict]:
    if not SEED.exists():
        pytest.skip("seed not built; run scripts/probe_grid.py")
    return json.loads(SEED.read_text(encoding="utf-8"))


# --- shape -----------------------------------------------------------------

def test_every_row_carries_the_c8_keys(seed):
    for row in seed:
        assert C8_KEYS <= set(row), f"cam {row.get('camera_id')} missing C8 keys"


def test_every_row_offers_all_three_transports(seed):
    for row in seed:
        assert set(row["transports"]) == {"rtsp", "hls", "whep"}
        for url in row["transports"].values():
            assert "://" in url


def test_camera_ids_are_unique(seed):
    ids = [r["camera_id"] for r in seed]
    assert len(ids) == len(set(ids))


def test_no_coordinates_in_the_seed(seed):
    """lat/lon belong to G6. Two producers for one field is how they diverge."""
    for row in seed:
        assert not {"lat", "lon"} & set(row)


def test_at_least_one_camera_is_reachable(seed):
    assert any(any(r["transport_probe"].values()) for r in seed)


def test_unreachable_rows_claim_no_measured_properties(seed):
    """A camera we could not open must not report a measured codec."""
    for row in seed:
        if not any(row["transport_probe"].values()):
            assert not str(row.get("properties_source", "")).startswith("measured")


# --- district_of: named districts only, never a guess ------------------------

@pytest.mark.parametrize("location,expected", [
    ("06 Timbavadi gate-Junagadh", "JUNAGADH"),
    ("07 hero-showroom-gir-somnath", "GIR_SOMNATH"),
    ("19 KHAPARIA GRAM PANCHAYAT , TALUKA GANDEVI, DISTRICT NAVSARI", "NAVSARI"),
    ("37 bilimora", "NAVSARI"),
    ("12 Tri Mandir Adalaj Tollnaka", "GANDHINAGAR"),
    ("Gandhidham Rambaugh p2", "KUTCH"),
    ("21 Patan Dethali Char Rasta", "PATAN"),
])
def test_district_recognised_when_the_text_names_one(location, expected):
    assert probe_grid.district_of(location) == expected


@pytest.mark.parametrize("location", [
    "01 Chiman bhai Bridge", "14 Delight", "20 Mohanpura", "35 TANKAL", "", None,
])
def test_district_is_unknown_rather_than_guessed(location):
    assert probe_grid.district_of(location) == "UNKNOWN"


# --- absolute(): the catalogue mixes absolute and root-relative URLs ---------

def test_relative_hls_path_is_joined_to_the_base():
    got = probe_grid.absolute("/live/stream/4/index.m3u8", "https://grid.example")
    assert got == "https://grid.example/live/stream/4/index.m3u8"


@pytest.mark.parametrize("url", [
    "rtsp://grid.example:8554/stream/4",
    "https://grid.example/live/stream/4/index.m3u8",
])
def test_absolute_urls_pass_through_untouched(url):
    assert probe_grid.absolute(url, "https://other.example") == url


def test_absolute_passes_none_through():
    assert probe_grid.absolute(None, "https://grid.example") is None


# --- apply_measurement: a failed probe contributes nothing -------------------

def _row() -> dict:
    return {
        "codec": "h264", "resolution": "1920x1080", "fps": 25.0,
        "transport_probe": {"rtsp": False, "hls": False},
        "properties_source": "catalogue",
    }


def test_failed_probe_marks_unreachable_and_keeps_catalogue_values():
    row = _row()
    probe_grid.apply_measurement(row, "hls", {"ok": False, "error": "timeout"})
    assert row["transport_probe"]["hls"] is False
    assert row["codec"] == "h264"
    assert row["properties_source"] == "catalogue"


def test_successful_probe_overrides_the_catalogue_and_records_provenance():
    row = _row()
    probe_grid.apply_measurement(row, "hls", {
        "ok": True, "codec": "hevc", "width": 1280, "height": 720, "fps": 10.0,
    })
    assert row["transport_probe"]["hls"] is True
    assert (row["codec"], row["resolution"], row["fps"]) == ("hevc", "1280x720", 10.0)
    assert row["properties_source"] == "measured"
    # fps from an opened container is still a declared number, not delivered.
    assert row["fps_source"] == "container-nominal"


# --- seed_row: built from a raw catalogue record -----------------------------

def test_seed_row_from_a_catalogue_record_with_empty_metadata():
    """19 of 30 catalogue entries report 0x0 and an empty codec."""
    row = probe_grid.seed_row(
        {"id": "9", "location": "09 new-bypass-near-by-circle-junagadh-2",
         "codec": "", "width": 0, "height": 0, "fps": 0.0,
         "rtsp_url": "rtsp://live.corp8.cloud:8554/stream/9",
         "webrtc_url": "http://live.corp8.cloud:8889/stream/9/whep",
         "hls_live_url": "/live/stream/9/index.m3u8"},
        "https://live.corp8.cloud", "live.corp8.cloud",
    )
    assert C8_KEYS <= set(row)
    assert row["camera_id"] == "9"
    assert row["district_code"] == "JUNAGADH"
    assert row["install_type"] == "UNKNOWN"   # burned into the overlay; G6 reads it
    assert (row["codec"], row["resolution"], row["fps"]) == (None, None, None)
    assert row["transports"]["hls"] == \
        "https://live.corp8.cloud/live/stream/9/index.m3u8"


def test_seed_row_synthesises_endpoints_the_catalogue_omits():
    row = probe_grid.seed_row(
        {"id": "30", "location": "Gandhidham Rambaugh p2"},
        "https://live.corp8.cloud", "live.corp8.cloud",
    )
    assert row["transports"]["rtsp"] == "rtsp://live.corp8.cloud:8554/stream/30"
    assert row["transports"]["whep"] == "http://live.corp8.cloud:8889/stream/30/whep"
