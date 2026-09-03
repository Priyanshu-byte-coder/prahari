"""What the preprocessing chain claims, checked one claim at a time.

The claims worth testing are the ones the demo rests on: that a camera whose vehicles are 55 px
wide is refused rather than guessed at, that a 1080p frame gets tiled instead of letterboxed
into uselessness, that four noisy crops of one plate average into a cleaner one, and that the
crop handed to a reader has glyphs at the height the reader was trained on.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

cv2 = pytest.importorskip("cv2")

from services.worker.preprocess import (          # noqa: E402
    GLYPH_OK_PX, TARGET_GLYPH_PX, deskew, enhance_plate_crop, estimate_sigma, feasibility,
    fuse, is_interlaced, measure, min_vehicle_width_for_ocr, prepare_frame, sharpness,
    smooth_then_sharpen, tile_plan, tiles, upscale_to_glyph,
)


def plate_image(width=440, height=110, text="GJ01AB1234"):
    """A plate face, drawn large enough that shrinking it models a distant camera."""
    img = np.full((height, width), 235, dtype=np.uint8)
    cv2.putText(img, text, (12, int(height * 0.75)), cv2.FONT_HERSHEY_SIMPLEX,
                height / 45.0, 20, 3, cv2.LINE_AA)
    return img


def noisy(img, sigma=12, seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(img.astype(np.float32) + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


# --- the refusal -------------------------------------------------------------------------

def test_a_wide_area_camera_is_refused_not_guessed_at():
    # cam04 Paldi Circle, measured 2026-09-03: median vehicle box 55 px in a 1920 px frame.
    f = feasibility(55)
    assert f.verdict == "no" and f.readable is False
    assert "never sampled" in f.reason


def test_a_close_camera_is_allowed():
    # cam17 Rajkot Bus Port, measured the same day: p90 vehicle box 614 px.
    assert feasibility(614).verdict == "ok"


def test_the_marginal_band_exists_and_says_so():
    f = feasibility(min_vehicle_width_for_ocr() * 0.75)
    assert f.verdict == "marginal"
    assert "unconfirmed" in f.reason


def test_feasibility_is_monotonic_in_vehicle_size():
    glyphs = [feasibility(w).glyph_px for w in (50, 100, 200, 400, 800)]
    assert glyphs == sorted(glyphs)


def test_the_stated_minimum_vehicle_width_actually_clears_the_gate():
    assert feasibility(min_vehicle_width_for_ocr()).glyph_px == pytest.approx(GLYPH_OK_PX, rel=1e-6)


# --- before detection ----------------------------------------------------------------------

def test_a_small_vehicle_in_a_1080p_frame_gets_tiled():
    tile, why = tile_plan(1920, expected_vehicle_w=55)
    assert tile > 0 and tile < 1920
    assert "letterbox" in why


def test_a_big_vehicle_is_left_whole():
    tile, why = tile_plan(1920, expected_vehicle_w=600)
    assert tile == 0 and "survives" in why


def test_tiles_cover_the_whole_frame():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    covered = np.zeros((1080, 1920), dtype=bool)
    for x, y, sub in tiles(frame, tile=640, overlap=0.2):
        assert sub.shape[:2] == (640, 640)
        covered[y:y + 640, x:x + 640] = True
    assert covered.all(), "a vehicle in an uncovered strip is a vehicle that never existed"


def test_a_frame_smaller_than_the_tile_is_yielded_once():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    assert len(list(tiles(frame, tile=960))) == 1


def test_conditioning_never_changes_the_frame_size():
    # The detector owns its own scaling; a preprocessing step that resizes silently moves
    # every box it later returns.
    frame = noisy(np.full((360, 640, 3), 40, dtype=np.uint8), sigma=14)
    assert prepare_frame(frame).shape == frame.shape


def test_a_dark_frame_is_lifted():
    frame = np.full((240, 320, 3), 25, dtype=np.uint8)
    frame[100:140, 100:200] = 60
    assert measure(prepare_frame(frame)).brightness > measure(frame).brightness


def test_noise_is_estimated_high_on_noise_and_low_on_a_clean_frame():
    clean = np.full((200, 200), 128, dtype=np.uint8)
    assert estimate_sigma(noisy(clean, sigma=15)) > estimate_sigma(clean) + 5


def test_a_combed_frame_is_recognised_as_interlaced():
    combed = np.zeros((200, 200), dtype=np.uint8)
    combed[::2] = 200                      # one field bright, the other dark
    assert is_interlaced(combed) is True
    assert is_interlaced(np.full((200, 200), 128, dtype=np.uint8)) is False


# --- after the crop --------------------------------------------------------------------------

def test_a_small_plate_is_upscaled_towards_the_readers_training_height():
    small = cv2.resize(plate_image(), (110, 28), interpolation=cv2.INTER_AREA)
    out = upscale_to_glyph(small)
    assert out.shape[0] > small.shape[0]
    assert out.shape[0] * 0.65 <= TARGET_GLYPH_PX * 1.05


def test_upscaling_is_capped_so_the_interpolator_stops_inventing():
    tiny = cv2.resize(plate_image(), (30, 8), interpolation=cv2.INTER_AREA)
    assert upscale_to_glyph(tiny).shape[0] <= tiny.shape[0] * 4


def test_smoothing_before_sharpening_beats_sharpening_noise_alone():
    # The claim in the module: bilateral first, unsharp second. Sharpening the noisy crop
    # directly multiplies the noise; this checks the flat plate face stays flat.
    plate = plate_image()
    dirty = noisy(plate, sigma=14)
    naive = cv2.filter2D(dirty, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], np.float32))
    ours = smooth_then_sharpen(dirty)
    flat = (slice(4, 24), slice(300, 420))          # a patch of empty plate, no glyphs
    assert ours[flat].std() < naive[flat].std()


def test_deskew_levels_a_tilted_plate():
    plate = plate_image()
    h, w = plate.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 8.0, 1.0)
    tilted = cv2.warpAffine(plate, m, (w, h), borderValue=235)

    def tilt(img):
        # Same fold as preprocess.deskew: minAreaRect reports (0, 90] on OpenCV 4.5+ and
        # [-90, 0) on older builds. Measuring without folding made this test read a level
        # plate as 90 degrees of tilt on the CI runner and 0 on a laptop.
        binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        angle = cv2.minAreaRect(cv2.findNonZero(binary))[-1] % 90
        return abs(angle - 90) if angle > 45 else abs(angle)

    assert tilt(deskew(tilted)) < tilt(tilted)


def test_the_full_chain_returns_a_reader_ready_crop():
    small = cv2.resize(plate_image(), (120, 30), interpolation=cv2.INTER_AREA)
    out = enhance_plate_crop(noisy(small, sigma=10))
    assert out.dtype == np.uint8 and out.ndim == 2
    assert out.shape[0] >= small.shape[0]


def test_the_chain_can_also_hand_tesseract_a_binary():
    small = cv2.resize(plate_image(), (150, 38), interpolation=cv2.INTER_AREA)
    grey, binary = enhance_plate_crop(small, want_binary=True)
    assert set(np.unique(binary)) <= {0, 255}
    assert grey.shape == binary.shape


def test_an_empty_crop_does_not_explode():
    assert enhance_plate_crop(np.zeros((0, 0), dtype=np.uint8)).size == 0
    assert enhance_plate_crop(None) is None


# --- across frames -----------------------------------------------------------------------------

def test_fusing_several_frames_removes_noise_a_single_frame_cannot():
    plate = plate_image()
    frames = [noisy(plate, sigma=18, seed=s) for s in range(6)]
    fused = fuse(frames)
    single_error = float(np.abs(frames[0].astype(float) - plate.astype(float)).mean())
    fused_error = float(np.abs(fused.astype(float) - plate.astype(float)).mean())
    assert fused_error < single_error * 0.75


def test_fusion_drops_a_frame_it_cannot_align_instead_of_smearing_it():
    plate = plate_image()
    junk = np.random.default_rng(3).integers(0, 255, plate.shape, dtype=np.uint8)
    fused = fuse([plate, plate, junk])
    assert float(np.abs(fused.astype(float) - plate.astype(float)).mean()) < 30


def test_the_sharpest_biggest_crop_is_the_one_chosen():
    from services.worker.preprocess import best_of

    sharp = plate_image()
    blurred = cv2.GaussianBlur(sharp, (9, 9), 0)
    tiny = cv2.resize(sharp, (60, 15), interpolation=cv2.INTER_AREA)
    chosen = best_of([blurred, tiny, sharp])
    assert sharpness(chosen) == sharpness(sharp)


def test_fuse_of_nothing_is_none_not_a_crash():
    assert fuse([]) is None
    assert fuse([None]) is None
