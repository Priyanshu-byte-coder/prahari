"""A read that isn't plate-shaped is POSSIBLE, not PROBABLE - even when the readers agree.

Found running the pipeline on the real Sentinel grid: the whole-vehicle OCR candidate reads
large painted text ("GSRTC" on a state bus, a shop board) and both readers agree on it, which
used to surface as `plate_text="GSRTC" [PROBABLE]`. PROBABLE has to mean "a plausible plate,
not yet confirmed", so a non-plate-shaped string drops to POSSIBLE (crop + null plate).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.worker.vote import PlateVote  # noqa: E402


class _R:
    def __init__(self, text, conf=0.9, name="easyocr"):
        self.text, self.conf, self.name = text, conf, name


def test_bus_livery_agreed_by_both_readers_is_possible_not_probable():
    v = PlateVote()
    for _ in range(3):
        v.add([_R("GSRTC"), _R("GSRTC", name="paddleocr")], sharpness=40)
    text, _conf, band = v.result()
    assert band == "POSSIBLE" and text is None


def test_a_short_agreed_blob_is_possible():
    v = PlateVote()
    for _ in range(3):
        v.add([_R("D"), _R("D", name="paddleocr")], sharpness=30)
    assert v.result()[2] == "POSSIBLE"


def test_a_plate_shaped_but_imperfect_string_is_still_probable():
    # 10 chars, wrong classes in a couple of slots - a genuine hard read, keep it PROBABLE
    v = PlateVote()
    for _ in range(2):
        v.add([_R("GJO1AB12E4"), _R("GJO1AB12E4", name="paddleocr")], sharpness=60)
    text, _conf, band = v.result()
    assert band == "PROBABLE" and text is not None


def test_a_clean_plate_still_confirms():
    v = PlateVote()
    for _ in range(3):
        v.add([_R("GJ01AB1234"), _R("GJ01AB1234", name="paddleocr"),
               _R("GJ01AB1234", name="tesseract")], sharpness=80)
    text, _conf, band = v.result()
    assert band == "CONFIRMED" and text == "GJ01AB1234"
