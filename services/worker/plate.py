"""[I4] Plate detection and reading. Runs on vehicle crops, never on the full frame.

Scale is the whole argument. A plate 20 px wide in a 1920 px frame is 20 px wide to a detector
that letterboxes the frame to 640 - about 7 px, below anything a recogniser was trained on. The
same plate inside a 300 px vehicle crop, upscaled to a 640 px input, is a readable band. So
detection runs twice: vehicles on the frame (I2), plates inside each vehicle crop (here).

Plate localisation has two paths and one call site:

- a plate detector, when `PRAHARI_PLATE_WEIGHTS` points at one (I11 trains it);
- otherwise `propose()`, a classical blackhat/Sobel/close pipeline. Plates are the highest
  contrast rectangle on a vehicle and sit in a narrow aspect band, which is exactly what
  classical morphology is good at. It is not as good as a trained detector; it needs no
  labelled data, which on day one is the difference between a pipeline and a plan.

The candidate list always ends with the whole vehicle crop, because both deep readers ship
their own text detector (EasyOCR's CRAFT, Paddle's DB) and will find a plate the morphology
missed. Voting over candidates costs OCR time, so `candidates()` returns at most three.

Readers are pluggable and every one of them is optional: `readers()` returns whichever are
installed, and the vote (`vote.py`) weights them by confidence. Two is the ticket's minimum;
one still produces sightings, with a wider band and a loud log line.
"""

from __future__ import annotations

import logging
import os
import re
import threading

import cv2
import numpy as np

logger = logging.getLogger("prahari.worker.plate")

ALLOW = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MIN_PLATE_H = 8              # px in the vehicle crop; below this no reader has a chance
OCR_MIN_H = 64               # upscale target - recognisers are trained on tall text lines
ASPECT = (1.8, 9.0)          # w/h of the glyph row, which is wider than the plate face
MAX_CANDIDATES = 3
MAX_CANDIDATE_W = 640        # a reader gains nothing above this and PaddleOCR loses seconds
_JUNK = re.compile(r"[^A-Z0-9]")


# --- localisation ----------------------------------------------------------------------

def propose(crop, max_boxes=2):
    """Classical plate proposals inside a vehicle crop, best first. Boxes are (x1,y1,x2,y2).

    Blackhat pulls dark-on-light glyphs off a lighter plate face, the Sobel-x + close step
    turns a row of glyphs into one solid blob, and the aspect filter keeps the blobs shaped
    like a plate. Windows, grilles and bumpers fail the aspect test; shadows fail the contrast
    test.
    """
    if crop is None or crop.size == 0:
        return []
    h, w = crop.shape[:2]
    if h < 24 or w < 48:
        return []
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 15), max(3, h // 40)))
    blackhat = cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, kernel)

    # Bright regions: a plate face is light, its glyphs are dark. Masking by it drops the
    # grille and the shadow under the bumper, which pass the gradient test on their own.
    light = cv2.morphologyEx(grey, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    _, light = cv2.threshold(light, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    grad = np.absolute(cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=3))
    span = grad.max() - grad.min()
    if span < 1e-6:
        return []
    grad = (255 * (grad - grad.min()) / span).astype("uint8")
    grad = cv2.GaussianBlur(grad, (5, 5), 0)
    closed = cv2.morphologyEx(grad, cv2.MORPH_CLOSE, kernel)
    _, binary = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # Erode then dilate to break the plate away from whatever it touches, mask to the light
    # regions, then close the glyph row back into one blob.
    binary = cv2.dilate(cv2.erode(binary, None, iterations=2), None, iterations=2)
    binary = cv2.bitwise_and(binary, binary, mask=light)
    binary = cv2.erode(cv2.dilate(binary, None, iterations=2), None, iterations=1)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if ch < MIN_PLATE_H or cw < 3 * MIN_PLATE_H:
            continue
        aspect = cw / ch
        if not ASPECT[0] <= aspect <= ASPECT[1]:
            continue
        # Plates sit low on a vehicle and are never the whole crop.
        if y + ch < h * 0.25 or cw > 0.95 * w:
            continue
        boxes.append((_score(cw, ch, y, h), (x, y, x + cw, y + ch)))
    boxes.sort(reverse=True, key=lambda b: b[0])
    return [box for _, box in boxes[:max_boxes]]


def _score(cw, ch, y, h):
    """Rank a candidate blob: big, plate-shaped, and low on the vehicle.

    Area alone is not enough - a windscreen band and a light bar are both bigger than a plate
    and both survive the aspect filter on a bus. Shape and height are what separate them, and
    they cost one multiply each.
    """
    shape = max(0.2, 1.0 - abs(cw / ch - 4.4) / 6.0)       # 440x100 is the issued ratio
    low = 0.4 + 0.6 * min(1.0, (y + ch / 2) / h)
    return cw * ch * shape * low


def upscale(crop, min_h=OCR_MIN_H):
    """Cubic upscale to a readable height. Distant plates are a handful of pixels tall."""
    if crop is None or crop.size == 0:
        return crop
    h, w = crop.shape[:2]
    if h >= min_h or h == 0:
        return crop
    factor = min_h / h
    return cv2.resize(crop, (max(1, int(w * factor)), min_h), interpolation=cv2.INTER_CUBIC)


def candidates(vehicle_crop, boxes=None):
    """Plate crops to read, best first, whole vehicle crop last. At most MAX_CANDIDATES.

    `boxes` comes from a trained plate detector when there is one; otherwise `propose()`.
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return []
    if boxes is None:
        boxes = propose(vehicle_crop)
    out = []
    for x1, y1, x2, y2 in boxes[:MAX_CANDIDATES - 1]:
        pad_x, pad_y = int((x2 - x1) * 0.06) + 2, int((y2 - y1) * 0.25) + 2
        h, w = vehicle_crop.shape[:2]
        sub = vehicle_crop[max(0, int(y1) - pad_y): min(h, int(y2) + pad_y),
                           max(0, int(x1) - pad_x): min(w, int(x2) + pad_x)]
        if sub.size:
            out.append(upscale(sub))
    out.append(_fit(upscale(vehicle_crop, OCR_MIN_H * 2)))
    return out[:MAX_CANDIDATES]


def _fit(crop, max_w=MAX_CANDIDATE_W):
    """Cap the fallback candidate's width. A close vehicle fills 900 px of frame, and running
    a text detector over all of it costs seconds per crop for glyphs that were already legible
    at 640 - which, with OCR on one thread, is how the reader falls a whole pass behind."""
    h, w = crop.shape[:2]
    if w <= max_w:
        return crop
    return cv2.resize(crop, (max_w, max(1, int(h * max_w / w))), interpolation=cv2.INTER_AREA)


# --- readers ---------------------------------------------------------------------------

def clean(text):
    """A reader's raw string -> the character set a plate can contain."""
    return _JUNK.sub("", (text or "").upper())


class _Reader:
    """Lazy, thread-safe singleton around one OCR engine. Loading costs seconds and hundreds
    of MB, so it happens on the first crop, not on import - the metrics endpoint and the tests
    import this module and must not pay for it."""

    name = "base"
    # Rough milliseconds per crop on the demo CPU, used only for ordering. Readers run
    # cheapest-first so that two cheap agreeing opinions can settle the vote before an expensive
    # engine is asked at all: with paddle first the selftest landed at 6.35 s against a 3.0 s
    # budget, and with it last the same three readers come in comfortably under.
    cost_ms = 500

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def _load(self):
        raise NotImplementedError

    def engine(self):
        with self._lock:
            if self._engine is None:
                self._engine = self._load()
            return self._engine

    def read(self, crop):
        from services.worker.backend import Reading
        try:
            text, conf = self._read(crop)
        except Exception as exc:                     # a reader must never kill the pipeline
            logger.warning("%s failed on a crop: %s", self.name, exc)
            return Reading("", 0.0, reader=self.name)
        return Reading(clean(text), float(conf), reader=self.name)

    def _read(self, crop):
        raise NotImplementedError


class EasyOCRReader(_Reader):
    """The salvaged Awiros path (`4d0c945:services/worker/plate_reader.py`): CRAFT detector +
    CRNN recogniser, GPU when there is one. Its own detector runs over the crop, so it also
    covers plates the morphology proposal missed."""

    cost_ms = 300

    name = "easyocr"

    def _load(self):
        import easyocr
        gpu = os.getenv("PRAHARI_OCR_GPU", "1") != "0"
        try:
            import torch
            gpu = gpu and torch.cuda.is_available()
        except Exception:
            gpu = False
        return easyocr.Reader(["en"], gpu=gpu, verbose=False)

    def _read(self, crop):
        results = self.engine().readtext(crop, allowlist=ALLOW)
        if not results:
            return "", 0.0
        # Longest first, then confidence: a plate is the longest glyph run on a vehicle, and
        # a two-character fragment with 0.99 confidence is a bumper sticker, not a plate.
        text, conf = max(((t, c) for _, t, c in results),
                         key=lambda tc: (len(clean(tc[0])), tc[1]))
        return text, conf


class PaddleReader(_Reader):
    """PaddleOCR - the ticket's second reader. Different architecture (DB + SVTR/CRNN) and a
    different training set from EasyOCR, which is the point: two readers that fail the same
    way vote the same wrong answer with twice the confidence."""

    cost_ms = 2000

    name = "paddleocr"

    def _load(self):
        from paddleocr import PaddleOCR
        # 3.x dropped `show_log` and split the old pipeline flags. The document-orientation and
        # unwarping stages are for scans of paper; on a 40 px plate crop they cost latency and
        # occasionally rotate a plate into nonsense.
        # enable_mkldnn=False is not a performance choice: with oneDNN on, PaddleOCR 3.7 dies
        # inside the PIR executor ("ConvertPirAttribute2RuntimeAttribute not support
        # ArrayAttribute<DoubleAttribute>") on every crop, and the reader silently contributes
        # nothing to the vote. Off, it reads the same crop at 0.99.
        return PaddleOCR(lang="en", use_doc_orientation_classify=False,
                         use_doc_unwarping=False, use_textline_orientation=False,
                         enable_mkldnn=False)

    def _read(self, crop):
        engine = self.engine()
        # Paddle's pipeline needs three channels. Handed a greyscale crop it raises
        # "not enough values to unpack (expected 3, got 2)" from inside its own predict(), which
        # `_Reader.read` catches and turns into an empty reading - so the reader that scores best
        # on the golden set was contributing *nothing* to the live vote, silently, because the
        # worker hands on the greyscale crop that preprocessing produces. Convert here.
        if crop.ndim == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        # 3.x renamed ocr() to predict(); both ship in 3.x, only ocr() in 2.x.
        result = engine.predict(crop) if hasattr(engine, "predict") else engine.ocr(crop)
        best = ("", 0.0)
        for page in result or []:
            # Paddle has shipped two result shapes; handle both rather than pin a version.
            lines = page.get("rec_texts", []) if isinstance(page, dict) else page or []
            scores = page.get("rec_scores", []) if isinstance(page, dict) else []
            pairs = (zip(lines, scores) if scores
                     else ((ln[1][0], ln[1][1]) for ln in lines if len(ln) > 1))
            for text, conf in pairs:
                if (len(clean(text)), conf) > (len(clean(best[0])), best[1]):
                    best = (text, conf)
        return best


class FastPlateReader(_Reader):
    """fast-plate-ocr: a CTC recogniser trained on plates rather than on scene text.

    The third architecture in the vote, and the one that is actually about this problem. EasyOCR
    and PaddleOCR are general scene-text models that happen to be pointed at a plate; this one
    was trained on plate crops, ships as a 2 MB ONNX file, and reads a crop in single-digit
    milliseconds on CPU - which matters because it can be asked for a second opinion on every
    candidate rather than only the best one.

    It is here because the demo box could only ever load EasyOCR: paddlepaddle does not install
    on this machine and Tesseract needs a system binary. A "vote" of one reader is a single read
    wearing a vote's confidence, and that is the thing the accuracy target must not be built on.
    """

    cost_ms = 10

    name = "fastplate"

    def _load(self):
        from fast_plate_ocr import LicensePlateRecognizer

        # xs is the small model: 2 MB, and the accuracy difference against `cct-s` on plates this
        # size is inside the noise of the crops the grid gives us.
        return LicensePlateRecognizer(os.getenv("PRAHARI_FASTPLATE_MODEL",
                                                "cct-xs-v1-global-model"))

    def _read(self, crop):
        # The ONNX graph takes 3-channel input; a greyscale crop raises a dimension error rather
        # than being promoted, so the conversion has to happen here.
        if crop.ndim == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        results = self.engine().run(crop, return_confidence=True)
        if not results:
            return "", 0.0
        best = results[0]
        probs = getattr(best, "char_probs", None)
        # The *minimum* character probability, not the mean. A plate is only as right as its
        # worst character, and a mean lets eight confident characters carry one that is a guess.
        conf = float(min(probs)) if probs is not None and len(probs) else 0.0
        return getattr(best, "plate", "") or "", conf


class TesseractReader(_Reader):
    """A classical engine as a third opinion. Weakest of the three on dirty plates, and
    deliberately so - it fails differently, which is what a vote wants."""

    cost_ms = 120

    name = "tesseract"

    def _load(self):
        import pytesseract
        pytesseract.get_tesseract_version()          # raises when the binary is missing
        return pytesseract

    def _read(self, crop):
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        config = f"--psm 7 -c tessedit_char_whitelist={ALLOW}"
        data = self.engine().image_to_data(grey, config=config,
                                           output_type=self.engine().Output.DICT)
        text = "".join(data["text"])
        confs = [float(c) for c in data["conf"] if float(c) >= 0]
        return text, (sum(confs) / len(confs) / 100.0 if confs else 0.0)


# Cheapest first: see _Reader.cost_ms. Order is load order *and* vote order.
_AVAILABLE = tuple(sorted((EasyOCRReader, PaddleReader, FastPlateReader,
                           TesseractReader), key=lambda cls: cls.cost_ms))
_READERS = None
_READERS_LOCK = threading.Lock()


def readers(force=None):
    """Every reader that loads on this machine, in vote order. Cached - loading is expensive.

    A missing engine is a deployment fact, not an error: the demo box may have two, a laptop
    one. Fewer than two is logged at warning because the ticket's accuracy target assumes a
    vote, and a "vote" of one is just a read.
    """
    global _READERS
    if force is not None:
        with _READERS_LOCK:
            _READERS = list(force)
    if _READERS is None:
        # The warm-up and the OCR thread both ask on startup; loading twice costs 20 s twice.
        with _READERS_LOCK:
            return _READERS if _READERS is not None else _load_readers()
    return _READERS


# The live pipeline has a latency budget ([C1]: a sighting within seconds of the vehicle), and
# on a CPU-only box PaddleOCR alone costs about two seconds a crop. Readers whose cost exceeds
# this are loaded only when asked for by name - they are excellent for the offline accuracy
# report, where wall time does not matter, and wrong for the path an operator is waiting on.
# Set PRAHARI_OCR_BUDGET_MS=99999 (or PRAHARI_OCR_READERS=all) to use every engine present.
DEFAULT_READER_BUDGET_MS = 500


def _selected(classes):
    """Which reader classes this deployment should load, and why - both are logged."""
    wanted = os.getenv("PRAHARI_OCR_READERS", "").strip().lower()
    if wanted in ("all", "*"):
        return list(classes)
    if wanted:
        names = {n.strip() for n in wanted.split(",") if n.strip()}
        chosen = [c for c in classes if c.name in names]
        missing = names - {c.name for c in chosen}
        if missing:
            logger.warning("PRAHARI_OCR_READERS names unknown reader(s): %s",
                           ", ".join(sorted(missing)))
        return chosen
    budget = int(os.getenv("PRAHARI_OCR_BUDGET_MS", DEFAULT_READER_BUDGET_MS))
    within = [c for c in classes if c.cost_ms <= budget]
    skipped = [c for c in classes if c.cost_ms > budget]
    if skipped:
        logger.info("not loading %s: over the %d ms per-crop budget. "
                    "PRAHARI_OCR_READERS=all to include them.",
                    ", ".join(f"{c.name} (~{c.cost_ms} ms)" for c in skipped), budget)
    return within


def _load_readers():
    global _READERS
    if True:
        found = []
        for cls in _selected(_AVAILABLE):
            reader = cls()
            try:
                reader.engine()
                found.append(reader)
            except Exception as exc:
                logger.info("reader %s unavailable: %s", cls.name, str(exc).split("\n")[0])
        if len(found) < 2:
            logger.warning("only %d OCR reader(s) available (%s) - the multi-reader vote is "
                           "degraded; install fast-plate-ocr, paddleocr or tesseract for the accuracy target",
                           len(found), ", ".join(r.name for r in found) or "none")
        _READERS = found
    return _READERS


def _rank(reading):
    """How good a reading is, before any voting: plate-shaped first, then longer, then surer.

    Shape has to outrank length or the whole-vehicle candidate wins with the operator's name
    painted on the door - nine characters of confident nonsense beating ten characters of plate.
    """
    from services.worker.vote import VALID
    from common.plate import grammar_fix, normalise
    text = grammar_fix(normalise(reading.text)) or ""
    return (bool(VALID.match(text)), len(text), reading.conf)


def read_all(vehicle_crop, boxes=None, engines=None, stop_on_agreement=True):
    """Every reader's best opinion of this vehicle crop. One Reading per reader, or [].

    `stop_on_agreement` stops once two readers have produced the same plate-shaped string. That
    is not an optimisation bolted on: the vote needs a majority, and once two of three agree the
    third cannot change the answer - it can only cost latency. With three engines loaded the
    selftest was landing at 3.46 s against a 3.0 s budget; stopping at agreement puts it back
    under, and on a disagreement every reader still runs, which is the case where the third
    opinion is the one that matters.
    """
    from common.plate import grammar_fix, normalise

    engines = readers() if engines is None else engines
    crops = candidates(vehicle_crop, boxes)
    out = []
    agreed = {}
    for engine in engines:
        best = None
        for crop in crops:
            reading = engine.read(crop)
            if best is None or _rank(reading) > _rank(best):
                best = reading
            if best is not None and _rank(best)[0]:
                break        # plate-shaped already; the remaining candidates cost latency only
        if best is not None and best.text:
            out.append(best)
            if stop_on_agreement and _rank(best)[0]:
                key = grammar_fix(normalise(best.text)) or ""
                agreed[key] = agreed.get(key, 0) + 1
                if agreed[key] >= 2:
                    break
    return out
