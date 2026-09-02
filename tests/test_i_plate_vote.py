"""I4's verify: the vote says nothing when it does not know, and says it for the right reason.

The ticket's Done-when is "exact-match >= 70% and **zero** confident-wrong reads at CONFIRMED".
The first half is a measurement (`scripts/accuracy_report.py`, I7); the second half is a
property of this code and is asserted here - CONFIRMED requires a 2/3 per-character majority,
a plate-shaped string, and at least three independent reads, and no combination of inputs is
allowed to produce it otherwise.

No OCR engine runs here. Readings are constructed directly, which is the only way to test what
the vote does with a disagreement we chose.
"""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.worker.backend import Reading  # noqa: E402
from services.worker.plate import candidates, clean, propose, read_all, upscale  # noqa: E402
from services.worker.publish import validate  # noqa: E402
from services.worker.sighting import SightingBuilder  # noqa: E402
from services.worker.synth import render_plate, stamp_plate  # noqa: E402
from services.worker.tracker import Track  # noqa: E402
from services.worker.vote import MAX_CROPS, PlateVote  # noqa: E402

PLATE = "GJ01AB1234"


def reading(text, conf=0.9, name="easyocr"):
    return Reading(text, conf, reader=name)


# --- the 2/3 rule ---------------------------------------------------------------------------

def test_three_agreeing_readers_confirm():
    vote = PlateVote()
    vote.add([reading(PLATE), reading(PLATE, name="paddleocr"),
              reading(PLATE, name="tesseract")], sharpness=100)
    assert vote.result() == (PLATE, pytest.approx(0.9, abs=0.01), "CONFIRMED")


def test_two_agreeing_readers_are_probable_not_confirmed():
    """Two is a majority but not corroboration. CONFIRMED is what an officer acts on."""
    vote = PlateVote()
    vote.add([reading(PLATE), reading(PLATE, name="paddleocr")], sharpness=100)
    text, _conf, band = vote.result()
    assert (text, band) == (PLATE, "PROBABLE")


def test_a_single_read_is_never_a_vote():
    vote = PlateVote()
    vote.add([reading(PLATE)], sharpness=100)
    text, _conf, band = vote.result()
    assert text is None and band == "POSSIBLE", "one opinion must not become a plate_text"


def test_no_majority_emits_null_and_keeps_the_band():
    """Three readers, three different characters in slot 8: nothing reaches 2/3."""
    vote = PlateVote()
    vote.add([reading("GJ01AB1234"), reading("GJ01AB1734", name="paddleocr"),
              reading("GJ01AB1934", name="tesseract")], sharpness=100)
    text, _conf, band = vote.result()
    assert text is None and band == "POSSIBLE"


def test_two_thirds_exactly_is_enough():
    vote = PlateVote()
    vote.add([reading("GJ01AB1234"), reading("GJ01AB1234", name="paddleocr"),
              reading("GJ01AB1734", name="tesseract")], sharpness=100)
    text, _conf, band = vote.result()
    assert (text, band) == (PLATE, "CONFIRMED")


def test_confidence_weights_the_vote():
    """A hesitant reader does not outvote two sure ones just by being present."""
    vote = PlateVote()
    vote.add([reading(PLATE, conf=0.95), reading(PLATE, conf=0.9, name="paddleocr"),
              reading("GJ01AB1235", conf=0.1, name="tesseract")], sharpness=100)
    assert vote.result()[0] == PLATE


def test_grammar_runs_before_the_vote():
    """`GJ0IAB1234` and `6J01A81234` are the same plate once the slots are enforced ([C7])."""
    vote = PlateVote()
    vote.add([reading("GJ0IAB1234"), reading("6J01A81234", name="paddleocr"),
              reading("GJ01AB1Z34", name="tesseract")], sharpness=100)
    text, _conf, band = vote.result()
    assert (text, band) == (PLATE, "CONFIRMED")


def test_malformed_reads_never_confirm():
    """Plate-shaped is a requirement of CONFIRMED, not a nice-to-have."""
    vote = PlateVote()
    for _ in range(3):
        vote.add([reading("ABCDEFGHI"), reading("ABCDEFGHI", name="paddleocr"),
                  reading("ABCDEFGHI", name="tesseract")], sharpness=50)
    text, _conf, band = vote.result()
    assert band != "CONFIRMED" and text is not None and band == "PROBABLE"


def test_no_reads_is_none_not_empty_string():
    vote = PlateVote()
    assert vote.add([reading("", 0.0)]) is False
    assert vote.result() == (None, 0.0, "NONE")


def test_length_disagreement_picks_the_plate_shaped_one():
    vote = PlateVote()
    vote.add([reading("GJ01AB1234"), reading("GJ01AB1234", name="paddleocr"),
              reading("EMISIONES", name="tesseract"),
              reading("EMISIONES", name="extra")], sharpness=100)
    assert vote.result()[0] == PLATE


# --- the eight sharpest crops ----------------------------------------------------------------

def test_keeps_only_the_sharpest_crops():
    vote = PlateVote()
    for i in range(MAX_CROPS + 6):
        vote.add([reading(PLATE)], sharpness=float(i))
    assert len(vote) == MAX_CROPS
    assert min(s for s, _ in vote._entries) == 6.0, "the blurriest crops must be the ones dropped"


def test_band_is_live_while_the_track_is_open():
    vote = PlateVote()
    assert vote.band == "NONE"
    vote.add([reading(PLATE), reading(PLATE, name="paddleocr"),
              reading(PLATE, name="tesseract")], sharpness=10)
    assert vote.band == "CONFIRMED"


# --- the OCR budget --------------------------------------------------------------------------

def sharp(seed=0, size=(80, 120)):
    return np.random.default_rng(seed).integers(0, 255, (*size, 3), dtype=np.uint8)


def test_ocr_is_requested_only_for_sharper_crops():
    b = SightingBuilder("CAM")
    s = b.observe(Track("CAM", 1, "car", 0.9, (0, 0, 120, 80), 1.0), crop=sharp(1))
    assert s.wants_ocr
    s.add_readings([reading(PLATE)])
    assert not s.wants_ocr, "the same crop must not be read twice"
    b.observe(Track("CAM", 1, "car", 0.9, (0, 0, 120, 80), 1.2),
              crop=np.full((80, 120, 3), 128, np.uint8))
    assert not s.wants_ocr, "a blurrier crop is not worth an OCR pass"


def test_a_confirmed_track_stops_asking_for_ocr():
    b = SightingBuilder("CAM")
    s = b.observe(Track("CAM", 1, "car", 0.9, (0, 0, 120, 80), 1.0), crop=sharp(1))
    s.add_readings([reading(PLATE), reading(PLATE, name="paddleocr"),
                    reading(PLATE, name="tesseract")])
    assert s.vote.band == "CONFIRMED"
    b.observe(Track("CAM", 1, "car", 0.9, (0, 0, 120, 80), 1.2), crop=sharp(2))
    assert not s.wants_ocr, "OCR budget spent on a track that is already confirmed"


def test_confirmed_row_carries_the_plate_and_passes_c1():
    b = SightingBuilder("GJ-AHD-0007")
    s = b.observe(Track("GJ-AHD-0007", 5, "car", 0.9, (10, 20, 130, 100), 4.0), crop=sharp(3))
    s.add_readings([reading(PLATE), reading(PLATE, name="paddleocr"),
                    reading(PLATE, name="tesseract")])
    row = validate(b.flush()[0].row())
    assert row["plate_text"] == PLATE and row["plate_band"] == "CONFIRMED"
    assert row["plate_canon"] == "6J01A81234", "canon collapses every class, including G->6"


def test_a_row_below_the_majority_is_rejected_by_the_contract():
    """publish.validate is the backstop: a plate_text under POSSIBLE must never reach D."""
    b = SightingBuilder("CAM")
    row = b.observe(Track("CAM", 1, "car", 0.9, (0, 0, 10, 10), 1.0)).row()
    row["plate_text"] = "GJ01AB1234"
    with pytest.raises(ValueError, match="2/3 vote"):
        validate(row)


# --- localisation ----------------------------------------------------------------------------

def vehicle_with_plate(plate=PLATE, size=(300, 220)):
    """A crude vehicle: a body, a windscreen, and a real rendered plate low on the front."""
    rng = np.random.default_rng(0)
    body = rng.integers(90, 120, (size[1], size[0], 3), dtype=np.uint8)
    cv2.rectangle(body, (30, 20), (size[0] - 30, 90), (60, 60, 65), -1)
    return stamp_plate(body, plate, scale=0.45, dirty=0.1, y_fraction=0.72)


def test_propose_finds_the_plate_band():
    crop = vehicle_with_plate()
    boxes = propose(crop)
    assert boxes, "the classical proposal found nothing on a plate that is plainly there"
    x1, y1, x2, y2 = boxes[0]
    from services.worker.plate import ASPECT
    assert ASPECT[0] <= (x2 - x1) / max(1, y2 - y1) <= ASPECT[1]
    assert y1 > crop.shape[0] * 0.25, "a plate does not sit on the roof"
    # It has to be the plate, not just plate-shaped: the stamp is centred at 72% of the height.
    assert abs((y1 + y2) / 2 - crop.shape[0] * 0.75) < crop.shape[0] * 0.15
    assert abs((x1 + x2) / 2 - crop.shape[1] / 2) < crop.shape[1] * 0.15


def test_candidates_always_end_with_the_whole_vehicle_crop():
    crop = vehicle_with_plate()
    out = candidates(crop)
    assert 1 <= len(out) <= 3
    assert out[-1].shape[0] >= crop.shape[0], "the fallback candidate must be the vehicle crop"


def test_candidates_of_an_empty_crop_are_empty():
    assert candidates(np.zeros((0, 0, 3), np.uint8)) == []


def test_upscale_lifts_a_tiny_plate_to_a_readable_height():
    tiny = render_plate(PLATE)[:, :][:12, :53]
    assert upscale(tiny).shape[0] == 64


def test_clean_strips_everything_a_plate_cannot_contain():
    assert clean(" gj-01 ab.1234 ") == "GJ01AB1234"
    assert clean(None) == ""


def test_read_all_prefers_a_plate_shaped_reading():
    """The whole-vehicle candidate reads the operator's signage; shape has to beat length."""

    class FakeEngine:
        name = "fake"

        def __init__(self, answers):
            self.answers = answers
            self.calls = 0

        def read(self, crop):
            self.calls += 1
            return reading(self.answers[min(self.calls - 1, len(self.answers) - 1)],
                           conf=0.99, name="fake")

    engine = FakeEngine(["GJ01AB1234", "EMISIONESX"])
    out = read_all(vehicle_with_plate(), engines=[engine])
    assert [r.text for r in out] == ["GJ01AB1234"]
