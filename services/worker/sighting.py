"""[I3] Tracks -> sightings. One row per vehicle pass, in [C1] shape.

A track is per-frame state; a sighting is the thing the rest of the system stores, matches,
alerts on and draws on a map. The conversion is the whole ticket: open on the first frame of a
track, keep the best crop and the best plate read, close 6 s after the last frame, emit once.

Two details are load-bearing:

- **Time.** `pts_first`/`pts_last` come from the decoder's PTS, never `now()` (AGENTS.md). PTS
  is stream-relative, so the first frame of a camera anchors it to the wall clock once and
  every later timestamp is `anchor + pts`. Inter-sighting gaps - which is what a route is made
  of - then carry the decoder's precision instead of the scheduler's jitter, and `ts_source`
  records which clock it was.
- **The 6 s close.** Same number as the tracker's 30-frame buffer at 5 fps, on purpose: a
  vehicle occluded long enough for ByteTrack to drop the track is also long enough for this to
  close the sighting, so the two never disagree about whether a pass ended.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from common.plate import canon, grammar_fix, normalise

logger = logging.getLogger("prahari.worker.sighting")

CLOSE_AFTER_S = 6.0
FUSE_CROPS = 6           # sharpest crops kept per track for multi-frame OCR fusion
IST = timezone(timedelta(hours=5, minutes=30))
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(now_ms=None, rng=random):
    """26-char Crockford base32 ULID: 48 bits of ms timestamp, 80 bits of randomness.

    Written out rather than pulled in as a dependency - it is one line of arithmetic and one
    lookup table, and [C1] only asks that the id sorts by time.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    value = (now_ms << 80) | rng.getrandbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def sharpness(image):
    """Variance of the Laplacian - the sharper crop wins the OCR budget ([I4])."""
    if image is None or image.size == 0:
        return 0.0
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


# Coarse colour names an officer would use on a wireless call. Hue is in OpenCV's 0-179 scale.
_HUES = ((8, "red"), (20, "orange"), (33, "yellow"), (85, "green"), (100, "cyan"),
         (130, "blue"), (160, "violet"), (180, "red"))


def colour_of(crop):
    """Dominant vehicle colour from the middle of the crop, or None when it is not decidable.

    The middle half only: the edges of a vehicle box are road, sky and the car behind. Low
    saturation is the common case on Indian roads (white, silver, grey, black) and it is
    decided on value alone, because hue is meaningless once saturation is near zero.
    """
    if crop is None or crop.size == 0:
        return None
    h, w = crop.shape[:2]
    core = crop[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    if core.size == 0:
        return None
    hsv = cv2.cvtColor(core, cv2.COLOR_BGR2HSV)
    hue, sat, val = (int(np.median(hsv[:, :, i])) for i in range(3))
    if sat < 60:
        return "black" if val < 60 else "grey" if val < 190 else "white"
    for edge, name in _HUES:
        if hue < edge:
            return name
    return None


@dataclass
class Sighting:
    """One vehicle pass on one camera. Mutable while open, frozen the moment it is emitted."""

    sighting_id: str
    camera_id: str
    track_id: int
    pts_first: float                       # epoch seconds, anchored PTS - never now()
    pts_last: float
    ts_source: str = "rtsp_pts"
    label: str = "car"
    conf: float = 0.0
    bbox: tuple = (0, 0, 0, 0)
    colour: str | None = None
    crop: np.ndarray | None = None         # best crop, by sharpness
    crop_sharpness: float = 0.0
    crop_uri: str | None = None            # I6 fills this after the MinIO PUT
    reid_vec: list | None = None           # I10, or None
    frames: int = 0
    vote: object | None = field(default=None, repr=False)
    _ocr_sharpness: float = 0.0
    _crops: list = field(default_factory=list, repr=False)   # (sharpness, crop), sharpest first

    @property
    def wants_ocr(self):
        """[I4]'s OCR budget rule: only tracks with no CONFIRMED read yet, and only when this
        crop is sharper than the one that produced the current best read."""
        if self.vote is None:
            return False
        return self.vote.band != "CONFIRMED" and self.crop_sharpness > self._ocr_sharpness

    def claim_ocr(self):
        """Reserve the current best crop for an OCR pass and return it.

        Claiming raises the bar `wants_ocr` measures against *before* the read happens, so a
        crop is never queued twice while its read is still in flight - the OCR runs on another
        thread and may take a second to come back.
        """
        self._ocr_sharpness = max(self._ocr_sharpness, self.crop_sharpness)
        return self.crop

    def claim_ocr_crops(self):
        """Like `claim_ocr`, but returns the track's sharpest crops (sharpest first) so the
        OCR pass can fuse several frames of the same plate. Falls back to `[self.crop]`."""
        self._ocr_sharpness = max(self._ocr_sharpness, self.crop_sharpness)
        crops = [c for _s, c in self._crops if c is not None and c.size]
        return crops or ([self.crop] if self.crop is not None else [])

    def add_readings(self, readings, crop_sharpness=None):
        """Feed one crop's readers into the vote and remember how sharp that crop was."""
        if self.vote is None or not readings:
            return
        self.vote.add(readings, crop_sharpness if crop_sharpness is not None
                      else self.crop_sharpness)
        self._ocr_sharpness = max(self._ocr_sharpness, self.crop_sharpness)

    def row(self):
        """The [C1] record. Field names are frozen; nulls are correct, guesses are not."""
        text, conf, band = (self.vote.result() if self.vote is not None
                            else (None, 0.0, "NONE"))
        norm = grammar_fix(normalise(text))
        return {
            "sighting_id": self.sighting_id,
            "camera_id": self.camera_id,
            "track_id": int(self.track_id),
            "pts_first": _iso(self.pts_first),
            "pts_last": _iso(self.pts_last),
            "ts_source": self.ts_source,
            "plate_text": norm,
            "plate_norm": norm,
            "plate_canon": canon(norm),
            "plate_conf": round(float(conf), 3),
            "plate_band": band,
            "vehicle_class": self.label,
            "colour": self.colour,
            "bbox": [int(round(v)) for v in self.bbox],
            "reid_vec": self.reid_vec,
            "crop_uri": self.crop_uri,
        }


def _iso(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, IST).isoformat(timespec="milliseconds")


class SightingBuilder:
    """Open, feed and close sightings for one camera.

    `observe` is called once per track per frame and returns the sighting, so the caller can
    check `wants_ocr` and spend its OCR budget where it will change an answer. `tick` closes
    what the stream has moved past; nothing closes on a wall clock, so a paused or replayed
    stream behaves exactly like a live one.
    """

    def __init__(self, camera_id, close_after=CLOSE_AFTER_S, vote_factory=None,
                 ts_source="rtsp_pts"):
        self.camera_id = camera_id
        self.close_after = close_after
        self.ts_source = ts_source
        self._vote_factory = vote_factory
        self._open = {}
        self._anchor = None                 # wall clock of pts 0.0, set by the first frame

    def _vote(self):
        if self._vote_factory is None:
            from services.worker.vote import PlateVote
            self._vote_factory = PlateVote
        return self._vote_factory()

    def epoch(self, pts_seconds):
        """PTS -> epoch seconds. Anchored once; the deltas are the decoder's, not the clock's."""
        return pts_seconds if self._anchor is None else self._anchor + pts_seconds

    def observe(self, track, crop=None, wall_clock=None):
        """Feed one track's frame. Returns the open Sighting (created on first sight)."""
        if self._anchor is None:
            self._anchor = (wall_clock if wall_clock is not None else time.time()) \
                - track.pts_seconds
        at = self.epoch(track.pts_seconds)
        s = self._open.get(track.track_id)
        if s is None:
            s = self._open[track.track_id] = Sighting(
                sighting_id=ulid(at * 1000), camera_id=self.camera_id,
                track_id=track.track_id, pts_first=at, pts_last=at,
                ts_source=self.ts_source, vote=self._vote())
        s.pts_last = max(s.pts_last, at)
        s.frames += 1
        s.label, s.conf, s.bbox = track.label, max(s.conf, track.conf), track.xyxy
        if crop is not None and crop.size:
            sharp = sharpness(crop)
            if sharp > s.crop_sharpness:
                s.crop, s.crop_sharpness = crop, sharp
                s.colour = colour_of(crop) or s.colour
            # Keep the FUSE_CROPS sharpest for multi-frame fusion; fuse() aligns them onto the
            # sharpest and drops any it cannot register, so size/scene mismatch is handled there.
            s._crops.append((sharp, crop))
            s._crops.sort(key=lambda e: e[0], reverse=True)
            del s._crops[FUSE_CROPS:]
        return s

    def tick(self, pts_seconds):
        """Close every sighting whose track has been gone for `close_after` of stream time."""
        cutoff = self.epoch(pts_seconds) - self.close_after
        done = [tid for tid, s in self._open.items() if s.pts_last < cutoff]
        return [self._open.pop(tid) for tid in done]

    def flush(self):
        """Close everything - end of clip, shutdown, or a stream discontinuity."""
        out = list(self._open.values())
        self._open.clear()
        return out

    def __len__(self):
        return len(self._open)


def demo():
    """Self-check: one track in, one sighting out, PTS preserved, ids sort by time."""
    from services.worker.tracker import Track

    b = SightingBuilder("GJ-AHD-0001", vote_factory=lambda: None)
    b._anchor = 1_757_000_000.0
    for i in range(10):
        b.observe(Track("GJ-AHD-0001", 7, "car", 0.9, (10, 10, 90, 90), 100.0 + i * 0.2))
    assert len(b) == 1 and not b.tick(101.8), "closed a track that is still in frame"
    closed = b.tick(110.0)
    assert len(closed) == 1, closed
    row = closed[0].row()
    assert row["pts_first"].endswith("+05:30") and row["plate_text"] is None
    assert row["pts_last"] > row["pts_first"] and row["track_id"] == 7
    ids = [ulid(1000 * i) for i in range(5)]
    assert ids == sorted(ids) and len(set(ids)) == 5, "ULIDs must sort by time and be unique"
    assert colour_of(np.zeros((40, 40, 3), np.uint8)) == "black"
    assert colour_of(np.full((40, 40, 3), 240, np.uint8)) == "white"
    print("sighting demo ok:", row["sighting_id"], row["pts_first"], "->", row["pts_last"])


if __name__ == "__main__":
    os.environ.setdefault("YOLO_VERBOSE", "0")
    demo()
