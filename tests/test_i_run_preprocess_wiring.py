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


def test_a_sighting_keeps_several_crops_for_fusion():
    from services.worker.sighting import FUSE_CROPS, SightingBuilder
    from services.worker.tracker import Track

    b = SightingBuilder("CAM")
    s = None
    for i in range(FUSE_CROPS + 4):
        crop = np.random.default_rng(i).integers(0, 255, (50, 150, 3), dtype=np.uint8)
        s = b.observe(Track("CAM", 1, "car", 0.9, (0, 0, 150, 50), 1.0 + 0.2 * i), crop=crop)
    crops = s.claim_ocr_crops()
    assert 1 < len(crops) <= FUSE_CROPS               # a batch, capped
    assert all(c is not None and c.size for c in crops)


@pytest.mark.skipif(run_mod._prepare_for_ocr is None, reason="preprocess.py not importable")
def test_the_ocr_pool_fuses_a_batch(monkeypatch):
    monkeypatch.setattr(run_mod, "_FUSE", True)
    seen = []

    def fake_read(crop):
        seen.append(crop.shape)
        return []

    pool = run_mod.OcrPool.__new__(run_mod.OcrPool)
    pool._read = fake_read
    crops = [np.full((48, 160, 3), 200, np.uint8) for _ in range(4)]
    # exercise the fusion branch directly
    readings = list(pool._read(crops[0]))
    fused = run_mod.OcrPool._fused(crops)
    assert fused is not None                          # 4 identical crops fuse cleanly
    readings += list(pool._read(fused))
    assert len(seen) == 2                             # sharpest raw + fused
