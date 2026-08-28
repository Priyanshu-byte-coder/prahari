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
from collections import Counter, defaultdict
from pathlib import Path

from services.worker.plate_reader import read_plate
from services.worker.stream_reader import read_frames
from services.worker.vehicle_tracker import VehicleTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prahari.worker")

DATA = Path(__file__).resolve().parents[2] / "data" / "detections"

# OCR is far more expensive than detection; only attempt it every N frames.
OCR_EVERY_N_FRAMES = 5

# PLAN.md §4.2: don't trust a single frame's read. Collect reads across a
# track's life and vote -- OCR noise on individual frames (glare, motion
# blur, partial occlusion) rarely repeats the same wrong string twice, so a
# majority vote across several reads is far more reliable than the first hit.
VOTES_PER_TRACK = 5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", required=True)
    ap.add_argument("--gateway", default="http://127.0.0.1:8080")
    ap.add_argument("--weights", default="yolov8s.pt", help="larger model = more accurate boxes, slower")
    args = ap.parse_args()

    url = f"{args.gateway}/stream/{args.camera}/index.m3u8"
    tracker = VehicleTracker(weights=args.weights)

    DATA.mkdir(parents=True, exist_ok=True)
    out_path = DATA / f"cam_{args.camera}.jsonl"

    n_frames = 0
    track_votes: dict[int, Counter] = defaultdict(Counter)
    track_final: dict[int, str] = {}

    with out_path.open("a", encoding="utf-8") as f:
        for frame in read_frames(args.camera, url):
            if frame.discontinuous:
                tracker.reset()
                track_votes.clear()
                track_final.clear()

            tracks = tracker.update(frame.camera_id, frame.image, frame.pts_seconds)
            for t in tracks:
                votes = track_votes[t.track_id]
                if sum(votes.values()) < VOTES_PER_TRACK and n_frames % OCR_EVERY_N_FRAMES == 0:
                    candidate = read_plate(frame.image, t.bbox)
                    if candidate:
                        votes[candidate] += 1
                        winner, count = votes.most_common(1)[0]
                        if winner != track_final.get(t.track_id):
                            track_final[t.track_id] = winner
                            logger.info(
                                "cam %s: track %d plate vote -> %s (%d/%d reads)",
                                args.camera, t.track_id, winner, count, sum(votes.values()),
                            )

                plate = track_final.get(t.track_id)
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
