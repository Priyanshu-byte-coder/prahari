"""[I3] One ByteTrack per camera, kept alive across frames.

The rule the ticket puts first is the one that is easiest to break by accident: a tracker is a
state machine, and constructing it inside the frame loop resets every track id on every frame.
The route view is keyed on "same track id = same vehicle pass", so that mistake does not show
up as a crash, it shows up as a car that appears to be thirty different cars. `Trackers` exists
so there is exactly one place where a tracker is created, and it is keyed by camera.

ByteTrack association only - no appearance model. Detections come from I2's backend, so the
tracker never loads a model and the two tickets never fight over a GPU.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from services.worker.backend import CLASSES

logger = logging.getLogger("prahari.worker.tracker")

TRACK_THRESH = 0.25       # ticket
TRACK_LOW_THRESH = 0.1    # ByteTrack's second association band, below the ticket's threshold
TRACK_BUFFER = 30         # frames, not seconds - see BUFFER_FRAME_RATE
MATCH_THRESH = 0.8        # ticket

# ultralytics scales the buffer as `int(frame_rate / 30 * track_buffer)`. We decode at 5 fps,
# so passing the real rate would turn the ticket's 30 frames into 5 - one second of occlusion
# tolerance at a junction where vehicles vanish behind a bus for four. 30 keeps the buffer at
# the 30 frames the ticket asks for, which at 5 fps is the 6 s the sighting builder also uses
# to close a track. The two windows are the same number on purpose.
BUFFER_FRAME_RATE = 30


@dataclass
class Track:
    camera_id: str
    track_id: int
    label: str
    conf: float
    xyxy: tuple[float, float, float, float]
    pts_seconds: float


class _Dets:
    """The shape ultralytics' BYTETracker expects from a `Results.boxes`: `xywh`, `conf`,
    `cls`, `len()` and boolean-mask indexing. Six lines here instead of constructing a full
    ultralytics Results object, which would drag a model and an image through the tracker."""

    def __init__(self, xyxy, conf, cls):
        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32).reshape(-1)
        self.cls = np.asarray(cls, dtype=np.float32).reshape(-1)

    @property
    def xywh(self):
        x = self.xyxy
        return np.stack([(x[:, 0] + x[:, 2]) / 2, (x[:, 1] + x[:, 3]) / 2,
                         x[:, 2] - x[:, 0], x[:, 3] - x[:, 1]], axis=1)

    def __len__(self):
        return len(self.conf)

    def __getitem__(self, mask):
        return _Dets(self.xyxy[mask], self.conf[mask], self.cls[mask])


class CameraTracker:
    """One camera's tracker. Construct once, call `update` per frame, `reset` on discontinuity."""

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.frames = 0
        self._tracker = self._new()

    @staticmethod
    def _new():
        from ultralytics.trackers.byte_tracker import BYTETracker
        args = SimpleNamespace(track_high_thresh=TRACK_THRESH, track_low_thresh=TRACK_LOW_THRESH,
                               new_track_thresh=TRACK_THRESH, track_buffer=TRACK_BUFFER,
                               match_thresh=MATCH_THRESH, fuse_score=True)
        try:
            return BYTETracker(args, frame_rate=BUFFER_FRAME_RATE)
        except TypeError:
            # ultralytics 8.4 dropped the frame_rate argument and uses args.track_buffer
            # directly as max_frames_lost, where 8.3 scaled it by frame_rate/30. TRACK_BUFFER is
            # already expressed at 30 fps, so the scaling is a no-op today - it is written out
            # so that changing BUFFER_FRAME_RATE keeps the same real-world memory on both.
            args.track_buffer = max(1, round(TRACK_BUFFER * BUFFER_FRAME_RATE / 30))
            return BYTETracker(args)

    def reset(self):
        """Drop every track. The grid loops its recordings, and a track id surviving the loop
        point would stitch two different vehicles into one route hop."""
        self._tracker = self._new()

    def update(self, detections, pts_seconds):
        """Associate this frame's detections. Returns the live tracks, ids stable across calls."""
        self.frames += 1
        labels = [d.label for d in detections]
        dets = _Dets([d.xyxy for d in detections] or np.zeros((0, 4)),
                     [d.conf for d in detections],
                     [CLASSES.index(lbl) if lbl in CLASSES else 0 for lbl in labels])
        rows = self._tracker.update(dets)
        out = []
        for row in np.asarray(rows).reshape(-1, 8):
            x1, y1, x2, y2, tid, score, cls, _idx = row.tolist()
            out.append(Track(self.camera_id, int(tid), CLASSES[int(cls) % len(CLASSES)],
                             float(score), (x1, y1, x2, y2), pts_seconds))
        return out


class Trackers:
    """camera_id -> CameraTracker. The only constructor of trackers in the worker."""

    def __init__(self):
        self._per_camera = {}

    def update(self, camera_id, detections, pts_seconds, discontinuous=False):
        tracker = self._per_camera.get(camera_id)
        if tracker is None:
            tracker = self._per_camera[camera_id] = CameraTracker(camera_id)
        if discontinuous:
            logger.info("cam %s: PTS discontinuity - resetting tracks", camera_id)
            tracker.reset()
        return tracker.update(detections, pts_seconds)

    def reset(self, camera_id):
        if camera_id in self._per_camera:
            self._per_camera[camera_id].reset()

    def __len__(self):
        return len(self._per_camera)
