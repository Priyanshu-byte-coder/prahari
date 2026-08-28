"""Run vehicle detection + tracking against one camera on the live grid.

Reads through our own stream gateway (not directly from upstream) so the
cookie session and LL-HLS stripping are already handled -- see
services/api/gateway.py.

Usage:
    python -m services.worker.run_worker --camera 4
    python -m services.worker.run_worker --camera 4 --gateway http://127.0.0.1:8080

For several cameras at once, use the supervisor rather than starting this by
hand per camera:
    python -m services.worker.supervisor --auto --max-cameras 4
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from services.worker.plate_reader import PlateReader
from services.worker.stream_reader import read_frames
from services.worker.vehicle_tracker import VehicleTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prahari.worker")

DATA = Path(__file__).resolve().parents[2] / "data" / "detections"

# The gateway replays a buffered group-of-pictures on connect, so the first
# frames arrive faster than real time. Anchoring the timeline during that burst
# would skew every timestamp on the camera, so wait for the stream to settle.
ANCHOR_SETTLE_SECONDS = 3.0


class Timeline:
    """Maps per-camera stream PTS onto a shared wall clock.

    Cross-camera route reconstruction needs one timeline, and neither available
    clock gives it directly: PTS is monotonic but its origin is per-stream, and
    the burned-in overlay is per-camera source time that runs backwards when the
    recording loops (CONTEXT.md §3). Frame arrival time is shared but distorted
    by the GOP replay burst on every connect.

    So: let the stream settle, take one (pts, wall) anchor pair, then derive
    every later timestamp as anchor_wall + (pts - anchor_pts). The result is
    shared across cameras, immune to the connect burst, and drift-free within a
    connection because PTS advances at true media rate.
    """

    def __init__(self) -> None:
        self.anchor_pts: float | None = None
        self.anchor_wall: float | None = None
        self._first_seen: float | None = None

    def reset(self) -> None:
        """Re-anchor after a reconnect or a recording loop."""
        self.anchor_pts = None
        self.anchor_wall = None
        self._first_seen = None

    def observed_at(self, pts_seconds: float, wall_clock: float) -> float:
        if self._first_seen is None:
            self._first_seen = wall_clock

        if self.anchor_pts is None:
            if wall_clock - self._first_seen < ANCHOR_SETTLE_SECONDS:
                return wall_clock  # still in the replay burst; do not anchor yet
            self.anchor_pts = pts_seconds
            self.anchor_wall = wall_clock

        return self.anchor_wall + (pts_seconds - self.anchor_pts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", required=True)
    ap.add_argument("--gateway", default="http://127.0.0.1:8080")
    ap.add_argument("--weights", default="yolov8s.pt",
                    help="larger model = more accurate boxes, slower")
    ap.add_argument("--device", default=None, help="cuda / cpu; default lets ultralytics choose")
    ap.add_argument(
        "--fps", type=float, default=float(os.environ.get("INFERENCE_FPS", "5")),
        help="inference rate; 0 runs on every decoded frame",
    )
    args = ap.parse_args()

    url = f"{args.gateway}/stream/{args.camera}/index.m3u8"
    tracker = VehicleTracker(weights=args.weights, device=args.device)
    plates = PlateReader()
    timeline = Timeline()

    DATA.mkdir(parents=True, exist_ok=True)
    out_path = DATA / f"cam_{args.camera}.jsonl"

    n_frames = 0
    n_inferred = 0
    n_rows = 0
    last_log = time.time()

    # Inference is sampled, not run on every decoded frame. The grid delivers
    # 10-30 fps depending on the camera, and ANPR gains nothing from the extra
    # frames while the GPU pays for all of them -- sampling is what decides how
    # many cameras one node can carry. The interval is measured in PTS, not
    # wall time, so a decode stall or the GOP replay burst on connect cannot
    # skew the sampling rate.
    min_interval = (1.0 / args.fps) if args.fps > 0 else 0.0
    last_inference_pts: float | None = None

    with out_path.open("a", encoding="utf-8") as f:
        for frame in read_frames(args.camera, url):
            if frame.discontinuous:
                # The recording looped. Track ids and the tracker's motion state
                # must not survive that, and the timeline needs re-anchoring
                # because PTS has jumped backwards.
                tracker.reset()
                plates.reset()
                timeline.reset()
                last_inference_pts = None

            observed_at = timeline.observed_at(frame.pts_seconds, frame.wall_clock)
            n_frames += 1

            if min_interval:
                if last_inference_pts is not None:
                    elapsed = frame.pts_seconds - last_inference_pts
                    # A backwards jump means the recording looped; the reset
                    # above already fired, so take this frame and re-anchor.
                    if 0 <= elapsed < min_interval:
                        continue
                last_inference_pts = frame.pts_seconds

            n_inferred += 1
            tracks = tracker.update(frame.camera_id, frame.image, frame.pts_seconds)
            for t in tracks:
                plate = plates.observe(t.track_id, frame.image, t.bbox)
                f.write(
                    json.dumps(
                        {
                            "camera_id": t.camera_id,
                            "track_id": t.track_id,
                            "class": t.cls_name,
                            "conf": round(t.conf, 3),
                            "bbox": [round(v, 1) for v in t.bbox],
                            "pts_seconds": round(t.pts_seconds, 3),
                            # Shared cross-camera timeline; see Timeline above.
                            "observed_at": round(observed_at, 3),
                            "plate": plate,
                        }
                    )
                    + "\n"
                )
                n_rows += 1
            f.flush()

            if time.time() - last_log >= 30:
                logger.info(
                    "cam %s: %d frames decoded, %d inferred (%.0f%%), %d rows, "
                    "%d active tracks, anchored=%s",
                    args.camera, n_frames, n_inferred,
                    100.0 * n_inferred / max(n_frames, 1), n_rows, len(tracks),
                    timeline.anchor_pts is not None,
                )
                last_log = time.time()


if __name__ == "__main__":
    main()
