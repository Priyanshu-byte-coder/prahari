"""Run vehicle detection + tracking against one camera on the live grid.

Reads through our own stream gateway (not directly from upstream) so the
cookie session and LL-HLS stripping are already handled -- see
services/api/gateway.py.

Usage:
    python -m services.worker.run_worker --camera 4
    python -m services.worker.run_worker --camera 4 --gateway http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from services.worker.plate_reader import PlateReader
from services.worker.stream_reader import read_frames
from services.worker.vehicle_tracker import VehicleTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prahari.worker")

DATA = Path(__file__).resolve().parents[2] / "data" / "detections"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", required=True)
    ap.add_argument("--gateway", default="http://127.0.0.1:8080")
    ap.add_argument("--weights", default="yolov8s.pt", help="larger model = more accurate boxes, slower")
    args = ap.parse_args()

    url = f"{args.gateway}/stream/{args.camera}/index.m3u8"
    tracker = VehicleTracker(weights=args.weights)
    plates = PlateReader()

    DATA.mkdir(parents=True, exist_ok=True)
    out_path = DATA / f"cam_{args.camera}.jsonl"

    n_frames = 0

    with out_path.open("a", encoding="utf-8") as f:
        for frame in read_frames(args.camera, url):
            if frame.discontinuous:
                tracker.reset()
                plates.reset()

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
                            "plate": plate,
                        }
                    )
                    + "\n"
                )
            f.flush()

            n_frames += 1
            if n_frames % 50 == 0:
                logger.info("cam %s: %d frames processed, %d active tracks", args.camera, n_frames, len(tracks))


if __name__ == "__main__":
    main()
