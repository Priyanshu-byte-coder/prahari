"""PTS-driven camera stream reader.

Every frame carries its true presentation timestamp, from the decoder's PTS
-- never frame-arrival time and never the burned-in overlay clock. See
CONTEXT.md §3: overlays are per-camera source time and loop backwards, so
cross-camera correlation must use stream PTS.

Reconnects with jittered exponential backoff (2s -> 30s cap), tolerates
non-uniform inter-frame gaps, treats decoder warnings from mid-GOP joins as
non-fatal, and flags PTS regression (the grid's recordings loop) so the
caller can reset per-camera track state without losing event history.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Iterator

import av
import numpy as np

logger = logging.getLogger("prahari.worker.stream")

BACKOFF_MIN = 2.0
BACKOFF_MAX = 30.0
LOOP_REGRESSION_S = 1.0  # PTS drop larger than this means the recording looped, not jitter


@dataclass
class Frame:
    camera_id: str
    image: np.ndarray  # BGR
    pts_seconds: float
    wall_clock: float
    discontinuous: bool = False  # True on the first frame after a detected PTS loop


def _open(url: str) -> av.container.InputContainer:
    options = {"rtsp_transport": "tcp"} if url.startswith("rtsp://") else {}
    return av.open(url, options=options, timeout=25.0)


def read_frames(camera_id: str, url: str) -> Iterator[Frame]:
    """Yield frames forever. Never raises past this generator for stream errors."""
    backoff = BACKOFF_MIN
    last_pts: float | None = None

    while True:
        container = None
        try:
            container = _open(url)
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            backoff = BACKOFF_MIN  # reset once connected

            for packet in container.demux(stream):
                try:
                    for av_frame in packet.decode():
                        if av_frame.pts is None:
                            continue
                        pts_seconds = float(av_frame.pts * stream.time_base)

                        discontinuous = False
                        if last_pts is not None and (pts_seconds - last_pts) < -LOOP_REGRESSION_S:
                            logger.warning(
                                "cam %s: PTS regressed (%.2fs -> %.2fs) -- recording looped, "
                                "flagging discontinuity",
                                camera_id, last_pts, pts_seconds,
                            )
                            discontinuous = True
                        last_pts = pts_seconds

                        yield Frame(
                            camera_id=camera_id,
                            image=av_frame.to_ndarray(format="bgr24"),
                            pts_seconds=pts_seconds,
                            wall_clock=time.time(),
                            discontinuous=discontinuous,
                        )
                except av.error.FFmpegError as exc:
                    # RPS/POC-style decoder warnings from joining mid-stream -- never fatal.
                    logger.debug("cam %s: decoder warning (non-fatal): %s", camera_id, exc)
                    continue
        except (av.error.FFmpegError, OSError, TimeoutError, ValueError) as exc:
            logger.warning(
                "cam %s: stream error: %s -- reconnecting in %.1fs", camera_id, exc, backoff
            )
            time.sleep(backoff + random.uniform(0, backoff * 0.25))
            backoff = min(backoff * 2, BACKOFF_MAX)
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass
