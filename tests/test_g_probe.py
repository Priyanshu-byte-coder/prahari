"""[G2] Transport resolution: order, fallback, and the shape of the G->I seam.

No network. Every probe is stubbed, so this runs in CI on a laptop with the
grid unreachable -- which is most of the time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.gateway import probe as probe_mod  # noqa: E402

CAMERA = {
    "camera_id": "7",
    "transports": {
        "rtsp": "rtsp://grid.example:8554/stream/7",
        "hls": "https://grid.example/live/stream/7/index.m3u8",
    },
}


def _stub(monkeypatch, *, rtsp, hls):
    monkeypatch.setattr(probe_mod, "probe_rtsp", lambda url, timeout=2.0: rtsp)
    monkeypatch.setattr(probe_mod, "probe_hls", lambda url, timeout=8.0: hls)


def test_rtsp_wins_when_available(monkeypatch):
    _stub(monkeypatch, rtsp=(True, "rtsp DESCRIBE 200"), hls=(True, "hls playlist served"))
    r = probe_mod.resolve_transport(CAMERA)
    assert r.transport == "rtsp"
    assert r.driver == "rtsp"
    assert r.url == CAMERA["transports"]["rtsp"]


def test_falls_back_to_hls_when_8554_blocked(monkeypatch):
    """The ticket's 'Done when': blocking 8554 moves the camera to HLS."""
    _stub(
        monkeypatch,
        rtsp=(False, "rtsp 8554 timeout after 2.0s (filtered)"),
        hls=(True, "hls playlist served"),
    )
    r = probe_mod.resolve_transport(CAMERA)
    assert r.transport == "hls"
    assert r.driver == "mediamtx"
    assert r.url == CAMERA["transports"]["hls"]


def test_hls_fallback_keeps_the_rtsp_reason(monkeypatch):
    """'came in on HLS because RTSP was blocked' -- both halves must survive."""
    _stub(
        monkeypatch,
        rtsp=(False, "rtsp 8554 timeout after 2.0s (filtered)"),
        hls=(True, "hls playlist served"),
    )
    r = probe_mod.resolve_transport(CAMERA)
    assert "filtered" in r.reason
    assert "hls playlist served" in r.reason


def test_unreachable_camera_resolves_to_nothing(monkeypatch):
    _stub(monkeypatch, rtsp=(False, "rtsp filtered"), hls=(False, "hls HTTP 500"))
    r = probe_mod.resolve_transport(CAMERA)
    assert r.transport is None
    assert r.url is None
    assert "rtsp filtered" in r.reason and "hls HTTP 500" in r.reason


def test_redis_value_is_exactly_the_c2_contract(monkeypatch):
    """[C2] promises four fields. `reason` is ours, it must not leak into the seam."""
    _stub(monkeypatch, rtsp=(True, "rtsp DESCRIBE 200"), hls=(False, "unused"))
    payload = json.loads(probe_mod.resolve_transport(CAMERA).redis_value())
    assert set(payload) == {"url", "transport", "driver", "probed_at"}


def test_missing_urls_are_reported_not_crashed(monkeypatch):
    _stub(monkeypatch, rtsp=(False, "x"), hls=(False, "y"))
    r = probe_mod.resolve_transport({"camera_id": "9", "transports": {}})
    assert r.transport is None
    assert "no rtsp url" in r.reason and "no hls url" in r.reason


@pytest.mark.parametrize(
    "reply,expected",
    [
        (b"RTSP/1.0 200 OK\r\n", True),
        (b"RTSP/1.0 401 Unauthorized\r\n", True),   # server is there, needs auth
        (b"RTSP/1.0 404 Not Found\r\n", False),
        (b"HTTP/1.1 200 OK\r\n", False),            # open port, not an RTSP server
    ],
)
def test_probe_rtsp_reads_the_describe_reply(monkeypatch, reply, expected):
    class FakeSock:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def settimeout(self, *a): pass
        def sendall(self, *a): pass
        def recv(self, *a): return reply

    # Allow the test hostname through the SSRF guard so the mock socket is reached.
    monkeypatch.setattr(probe_mod, "allowed_hosts", lambda: frozenset({"grid.example"}))
    monkeypatch.setattr(probe_mod.socket, "create_connection", lambda *a, **k: FakeSock())
    ok, _ = probe_mod.probe_rtsp("rtsp://grid.example:8554/stream/7")
    assert ok is expected
