"""Vehicle detection + within-camera tracking, PTS-driven.

Wraps Ultralytics YOLO's built-in ByteTrack. Track ids and the tracker's
internal motion state are per-camera and must be dropped on stream
discontinuity (see stream_reader.Frame.discontinuous) -- the grid loops its
recordings, and a track id surviving a loop point would silently corrupt
route reconstruction downstream.

Note: ultralytics is AGPL-3.0. Flagged in PLAN.md §11 as a question for the
organisers; keep a permissive-detector swap (YOLOX / RT-DETR) in mind if that
comes back as a blocker for a government deployment.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ultralytics import YOLO

# COCO vehicle classes only -- this grid is a traffic camera network.
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# See bytetrack_traffic.yaml for why this isn't the ultralytics default.
_TRACKER_CFG = str(Path(__file__).resolve().parent / "bytetrack_traffic.yaml")


@dataclass
class VehicleTrack:
    camera_id: str
    track_id: int
    cls_name: str
    conf: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    pts_seconds: float


class VehicleTracker:
    def __init__(self, weights: str = "yolov8n.pt", device: str | None = None):
        self.model = YOLO(weights)
        self.device = device

    def reset(self) -> None:
        """Drop ByteTrack's internal state. Call whenever the stream reader flags
        a PTS discontinuity, so track ids don't leak across a scene loop."""
        self.model.predictor = None

    def update(self, camera_id: str, image, pts_seconds: float) -> list[VehicleTrack]:
        results = self.model.track(
            image,
            persist=True,
            tracker=_TRACKER_CFG,
            classes=list(VEHICLE_CLASSES),
            verbose=False,
            device=self.device,
        )
        r = results[0]
        if r.boxes is None or r.boxes.id is None:
            return []

        out: list[VehicleTrack] = []
        for box, track_id, cls, conf in zip(
            r.boxes.xyxy.tolist(), r.boxes.id.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()
        ):
            out.append(
                VehicleTrack(
                    camera_id=camera_id,
                    track_id=int(track_id),
                    cls_name=VEHICLE_CLASSES.get(int(cls), "vehicle"),
                    conf=float(conf),
                    bbox=(box[0], box[1], box[2], box[3]),
                    pts_seconds=pts_seconds,
                )
            )
        return out
