"""The worker actually uses preprocess.py, not just imports it.

Two wirings the demo rests on:
  * a vehicle box too small for a readable plate is tracked but never handed to OCR
    (`Worker._ocr_feasible`), and
  * frames go through `prepare_frame` before the detector, at the frame's own size
    (`Worker._detector_images`).
Both have an env kill-switch; that is checked too.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from services.worker import run as run_mod  # noqa: E402


class _FakeSighting:
    sighting_id = "01J6TESTTEST"
    camera_id = "CAM-TEST"
    track_id = 7


class _FakeFrame:
    def __init__(self, image):
        self.image = image
        self.camera_id = "CAM-TEST"


def _worker():
    """A Worker without its heavy __init__ - we only exercise two pure-ish methods."""
    return run_mod.Worker.__new__(run_mod.Worker)


@pytest.mark.skipif(run_mod._feasibility is None, reason="preprocess.py not importable")
def test_a_tiny_vehicle_is_not_sent_to_ocr(monkeypatch):
    monkeypatch.setattr(run_mod, "_FEAS_GATE", True)
    w = _worker()
    # ~40 px wide vehicle box: the glyph would be ~2 px, verdict "no"
    assert w._ocr_feasible(_FakeSighting(), 40) is False


@pytest.mark.skipif(run_mod._feasibility is None, reason="preprocess.py not importable")
def test_a_close_vehicle_is_sent_to_ocr(monkeypatch):
    monkeypatch.setattr(run_mod, "_FEAS_GATE", True)
    w = _worker()
    assert w._ocr_feasible(_FakeSighting(), 700) is True


def test_the_feasibility_gate_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(run_mod, "_FEAS_GATE", False)
    w = _worker()
    assert w._ocr_feasible(_FakeSighting(), 10) is True


def test_frames_are_conditioned_at_their_own_size(monkeypatch):
    monkeypatch.setattr(run_mod, "_PREP_FRAMES", True)
    w = _worker()
    frame = _FakeFrame(np.full((540, 960, 3), 40, dtype=np.uint8))  # a dark frame
    out = w._detector_images([frame])
    assert len(out) == 1
    assert out[0].shape == frame.image.shape          # never resized


def test_frame_conditioning_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(run_mod, "_PREP_FRAMES", False)
    w = _worker()
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    out = w._detector_images([_FakeFrame(img)])
    assert out[0] is img                              # the exact raw array, untouched
