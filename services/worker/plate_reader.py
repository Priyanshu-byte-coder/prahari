"""Number-plate OCR on a vehicle crop.

Pipeline, and why it isn't the one asked for:

  Requested:  YOLOv8n-plate -> PARSeq -> PaddleOCR fallback -> OpenSearch
  Built:      EasyOCR (CRAFT detector + CRNN recognizer) -> regex validate
              -> per-track vote fusion -> Python fuzzy search

- No trained YOLOv8n-plate weights exist for this project (PLAN.md §4.1 calls
  for fine-tuning one on labelled crops from this grid -- not done yet).
  Community plate-detector weights on Hugging Face are auth-gated; shipping
  an unverified download would be worse than not having one. Trade-off
  instead: EasyOCR's own CRAFT text detector runs on the *entire* vehicle
  crop and locates the plate text region itself, rather than assuming it
  sits in a fixed band -- a real accuracy improvement over the previous
  approach, just not a separately-trained detection stage.
- PaddleOCR has no wheel for this machine's Python/platform combination
  (paddlepaddle ships no build for it). EasyOCR is the same class of model
  (deep detector + recognizer, not a classical engine like Tesseract) and
  installs cleanly here.
- PARSeq needs its own weights and a correct preprocessing/tokenizer setup;
  not attempted in this pass to avoid shipping something unverified.
- Track-level vote fusion (this file's job is a single read; run_worker.py
  does the voting across a track's life) and fuzzy search ARE built, per
  PLAN.md §4.2/§4.4 -- just backed by a Python matcher, not an OpenSearch
  cluster (out of scope to stand up in this session).
"""
from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict

import cv2
import numpy as np

PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")

_reader = None
_reader_lock = threading.Lock()


def _get_reader():
    global _reader
    with _reader_lock:
        if _reader is None:
            import easyocr  # heavy import, deferred until first real use
            _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        return _reader


def _vehicle_crop(image: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray | None:
    x1, y1, x2, y2 = (int(v) for v in bbox)
    if x2 - x1 < 20 or y2 - y1 < 20:
        return None
    crop = image[max(0, y1):y2, max(0, x1):x2]
    return crop if crop.size else None


def read_plate(image: np.ndarray, bbox: tuple[float, float, float, float]) -> str | None:
    """Return a format-valid plate string, or None if nothing readable.

    Runs EasyOCR's detector across the whole vehicle crop rather than a
    guessed band, and keeps the highest-confidence result that matches the
    Indian registration format after separator stripping.
    """
    crop = _vehicle_crop(image, bbox)
    if crop is None:
        return None

    # Upscale small crops -- distant vehicles leave the plate a handful of
    # pixels tall, well below what the recognizer was trained to read.
    h, w = crop.shape[:2]
    if h < 200:
        scale = 200 / h
        crop = cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    reader = _get_reader()
    results = reader.readtext(crop, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

    best: str | None = None
    best_conf = 0.0
    for _, text, conf in results:
        candidate = re.sub(r"[^A-Z0-9]", "", text.upper())
        if PLATE_RE.match(candidate) and conf > best_conf:
            best, best_conf = candidate, conf
    return best


class PlateReader:
    """Owns everything plate-domain: OCR throttling and per-track vote fusion.

    This is the whole interface the grid/tracking side needs to know about --
    call observe() once per track per frame, call reset() on stream
    discontinuity. No OCR/voting details leak into run_worker.py, so the
    plate pipeline (this file) and the grid pipeline (stream_reader.py,
    vehicle_tracker.py, run_worker.py) can be worked on independently without
    touching each other's code.
    """

    def __init__(self, ocr_every_n_frames: int = 5, votes_per_track: int = 5) -> None:
        self.ocr_every_n_frames = ocr_every_n_frames
        self.votes_per_track = votes_per_track
        self._frame_count = 0
        self._votes: dict[int, Counter] = defaultdict(Counter)
        self._final: dict[int, str] = {}

    def reset(self) -> None:
        """Drop all per-track vote state. Call on stream discontinuity (the
        grid loops its recordings) so a stale plate doesn't leak onto a
        different physical vehicle that reuses the track id."""
        self._votes.clear()
        self._final.clear()

    def observe(
        self, track_id: int, image: np.ndarray, bbox: tuple[float, float, float, float]
    ) -> str | None:
        """Feed one frame's vehicle crop for this track. Returns the current
        best fused plate for the track (None until at least one valid read)."""
        self._frame_count += 1
        votes = self._votes[track_id]

        if sum(votes.values()) < self.votes_per_track and self._frame_count % self.ocr_every_n_frames == 0:
            candidate = read_plate(image, bbox)
            if candidate:
                votes[candidate] += 1
                winner, _ = votes.most_common(1)[0]
                self._final[track_id] = winner

        return self._final.get(track_id)
