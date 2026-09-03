"""[I2] The inference seam. One protocol, one local implementation, one batcher.

Everything that touches a GPU in this lane goes through `InferenceBackend` ([C6]). The rest of
the worker - tracker, plate vote, publisher - holds a backend and never imports ultralytics,
torch or onnxruntime. That is what makes I11 (fine-tune + TensorRT) a config path instead of a
rewrite: swap `PRAHARI_VEHICLE_WEIGHTS` and the callers do not change.

Class names are the other half of that promise. COCO gives us four of the seven classes the
brief asks for, so `COCO_TO_CLASS` maps them and the three it cannot supply
(three_wheeler, lcv, tractor) stay absent rather than guessed - a rickshaw reported as a car is
worse than a rickshaw reported as nothing. A fine-tuned model that emits our names natively
passes through the same table unchanged (identity entries), so I11 changes weights, not code.

Batching is the throughput trick: one forward pass over 16 frames from 16 different cameras
costs far less than 16 passes over one frame each, because the fixed per-call overhead
(preprocess, H2D copy, kernel launch, NMS setup) is paid once. The 20 ms flush is the latency
floor that keeps a half-empty batch from waiting for traffic that is not coming.
"""

from __future__ import annotations

import argparse
import logging
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

logger = logging.getLogger("prahari.worker.backend")

ROOT = Path(__file__).resolve().parents[2]
WEIGHTS_DIR = Path(os.getenv("PRAHARI_WEIGHTS_DIR", ROOT / "models"))
VEHICLE_WEIGHTS = os.getenv("PRAHARI_VEHICLE_WEIGHTS", str(WEIGHTS_DIR / "yolov8s.pt"))
PLATE_WEIGHTS = os.getenv("PRAHARI_PLATE_WEIGHTS", "")     # I11 fills this in; empty = classical
MAX_BATCH = 16
FLUSH_MS = 20.0
# CONF matches ByteTrack's track_thresh: the tracker sees the low band too. IMGSZ 640 is the
# YOLO default; on the real grid's wide night junctions a 1280 (or 1536) inference size finds
# several times more vehicles - measured on cam12, 2 dets -> 11 - at a linear cost in latency.
# Both env-tunable per deployment: an ANPR-sited camera wants 640/0.25, a wide-area feed 1280/0.2.
CONF = float(os.getenv("PRAHARI_DETECT_CONF", "0.25"))
IMGSZ = int(os.getenv("PRAHARI_DETECT_IMGSZ", "640"))

# The seven classes the brief names.
CLASSES = ("two_wheeler", "three_wheeler", "car", "lcv", "bus", "truck", "tractor")

# COCO -> ours. Identity entries let a fine-tuned model that already emits our names through
# untouched. Missing on purpose: three_wheeler, lcv, tractor - COCO has no such categories and
# inventing them from box geometry would put a wrong class on a police report.
COCO_TO_CLASS = {
    "motorcycle": "two_wheeler", "car": "car", "bus": "bus", "truck": "truck",
    **{c: c for c in CLASSES},
}


@dataclass
class Detection:
    xyxy: tuple[float, float, float, float]
    conf: float
    label: str


@dataclass
class Reading:
    """One OCR reader's opinion of one crop. `char_conf` is per character, aligned to `text`."""
    text: str
    conf: float
    char_conf: list[float] = field(default_factory=list)
    reader: str = ""

    def confidences(self):
        """Per-character confidence, padded from the whole-string confidence when a reader
        does not expose one. Length always matches `text`, which is what the vote indexes."""
        if len(self.char_conf) == len(self.text):
            return list(self.char_conf)
        return [self.conf] * len(self.text)


class InferenceBackend(Protocol):                          # [C6]
    def detect(self, frames) -> list[list[Detection]]: ...
    def plates(self, crops) -> list[list[Detection]]: ...
    def ocr(self, crops) -> list[Reading]: ...
    def reid(self, crops) -> np.ndarray: ...


class LocalBackend:
    """In-process GPU (or CPU) inference. Models load lazily - importing this module must stay
    free, because the tests, the metrics endpoint and `--help` all import it."""

    def __init__(self, vehicle_weights=VEHICLE_WEIGHTS, plate_weights=PLATE_WEIGHTS,
                 device=None, conf=CONF, imgsz=IMGSZ, half=None):
        self.vehicle_weights = str(vehicle_weights)
        self.plate_weights = str(plate_weights or "")
        self.conf = conf
        self.imgsz = imgsz
        self.device = device or self._pick_device()
        self.half = self.device.startswith("cuda") if half is None else half
        self._vehicle = None
        self._plate = None
        self._readers = None
        self._embedder = None

    @staticmethod
    def _pick_device():
        try:
            import torch
            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _yolo(self, weights):
        from ultralytics import YOLO
        model = YOLO(weights)
        model.to(self.device)
        return model

    # --- [C6] ---------------------------------------------------------------------------

    def detect(self, frames):
        """Vehicles in each frame. One forward pass for the whole list - that is the point."""
        if not frames:
            return []
        if self._vehicle is None:
            self._vehicle = self._yolo(self.vehicle_weights)
        results = self._vehicle.predict(list(frames), imgsz=self.imgsz, conf=self.conf,
                                        half=self.half, device=self.device, verbose=False)
        return [self._boxes(r, COCO_TO_CLASS) for r in results]

    def plates(self, crops):
        """Plate boxes inside vehicle crops ([I4]: never on the full frame).

        With no plate weights configured this returns [] per crop and `plate.propose()` takes
        over with the classical proposal. Two paths, one call site.
        """
        if not crops:
            return []
        if not self.plate_weights:
            return [[] for _ in crops]
        if self._plate is None:
            self._plate = self._yolo(self.plate_weights)
        results = self._plate.predict(list(crops), imgsz=320, conf=0.2, half=self.half,
                                      device=self.device, verbose=False)
        return [self._boxes(r, None, default="plate") for r in results]

    def ocr(self, crops):
        """Every configured reader's opinion of every crop, flattened per crop by best conf.

        The vote (I4) wants all of them, so `ocr_all` is the real entry point; this one keeps
        the [C6] signature honest for a caller that just wants one string.
        """
        return [max(rs, key=lambda r: r.conf) if rs else Reading("", 0.0)
                for rs in self.ocr_all(crops)]

    def ocr_all(self, crops):
        """list[list[Reading]] - one list per crop, one Reading per available reader."""
        if not crops:
            return []
        if self._readers is None:
            from services.worker.plate import readers
            self._readers = readers()
        return [[r.read(c) for r in self._readers] for c in crops]

    def reid(self, crops):
        """512-d appearance vectors ([I10]). Corroboration only, never identity."""
        if self._embedder is None:
            from services.worker.reid import Embedder
            self._embedder = Embedder(device=self.device)
        return self._embedder.embed(crops)

    # --- helpers ------------------------------------------------------------------------

    @staticmethod
    def _boxes(result, mapping, default=None):
        boxes = getattr(result, "boxes", None)
        if boxes is None or boxes.xyxy is None or not len(boxes):
            return []
        names = result.names
        out = []
        for xyxy, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(),
                                   boxes.cls.tolist()):
            raw = names.get(int(cls), str(int(cls))) if isinstance(names, dict) else str(cls)
            label = default if mapping is None else mapping.get(raw)
            if label is None:
                continue                       # not one of ours - drop it, never guess
            out.append(Detection(tuple(float(v) for v in xyxy), float(conf), label))
        return out


class Batcher:
    """Accumulate work items across cameras; hand back a batch at 16 items or 20 ms.

    Deliberately not a thread or a queue: the caller owns the loop, so the batcher is a pure
    accumulator that can be unit-tested with a fake clock and cannot deadlock a decode thread.
    """

    def __init__(self, max_batch=MAX_BATCH, flush_ms=FLUSH_MS, clock=time.monotonic):
        self.max_batch = max_batch
        self.flush_s = flush_ms / 1000.0
        self._clock = clock
        self._items = []
        self._opened = None

    def add(self, item):
        """Queue one item. Returns the batch when this item filled it, else None."""
        if not self._items:
            self._opened = self._clock()
        self._items.append(item)
        return self.flush() if len(self._items) >= self.max_batch else None

    def due(self):
        """The batch if it has waited long enough, else None. Call when no frame arrived."""
        if self._items and self._clock() - self._opened >= self.flush_s:
            return self.flush()
        return None

    def flush(self):
        items, self._items, self._opened = self._items, [], None
        return items or None

    def __len__(self):
        return len(self._items)


# --- bench ------------------------------------------------------------------------------

def _percentiles(samples):
    ordered = sorted(samples)
    p = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
    return p(0.50) * 1e3, p(0.95) * 1e3


def _bench_one(name, fn, warmup=3, runs=20):
    for _ in range(warmup):                 # first call loads weights and builds kernels
        fn()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    p50, p95 = _percentiles(samples)
    print(f"  {name:<28} p50={p50:7.1f} ms  p95={p95:7.1f} ms  "
          f"mean={statistics.mean(samples) * 1e3:7.1f} ms")
    return p50, p95


def bench(batch=MAX_BATCH, device=None, width=960, height=544):
    """Ticket verify: p50/p95 per model, and the batched frames/s the pipeline can sustain.

    Frames are noise, not a clip: the timings measure the forward pass and NMS, and NMS cost
    tracks the number of boxes, which noise keeps low and constant. A real clip would make the
    number prettier and less repeatable.
    """
    rng = np.random.default_rng(0)
    frames = [rng.integers(0, 255, (height, width, 3), dtype=np.uint8) for _ in range(batch)]
    crops = [rng.integers(0, 255, (192, 256, 3), dtype=np.uint8) for _ in range(batch)]
    b = LocalBackend(device=device)
    print(f"device={b.device} half={b.half} batch={batch} frame={width}x{height} "
          f"weights={Path(b.vehicle_weights).name}")

    p50_1, _ = _bench_one("detect batch=1", lambda: b.detect(frames[:1]))
    p50, p95 = _bench_one(f"detect batch={batch}", lambda: b.detect(frames))
    _bench_one("plates (vehicle crops)", lambda: b.plates(crops))
    try:
        _bench_one("reid 512-d", lambda: b.reid(crops), warmup=1, runs=5)
    except Exception as exc:
        print(f"  {'reid 512-d':<28} unavailable: {exc}")
    try:
        _bench_one("ocr (all readers)", lambda: b.ocr_all(crops[:4]), warmup=1, runs=3)
    except Exception as exc:
        print(f"  {'ocr (all readers)':<28} unavailable: {exc}")

    fps = batch / (p50 / 1e3)
    print(f"\nbatched throughput = {fps:.0f} frames/s "
          f"({batch} frames in {p50:.1f} ms at p50, p95 {p95:.1f} ms)")
    print(f"batching gain = {p50_1 * batch / p50:.1f}x over one-frame-at-a-time")
    print(f"at 5 fps/camera that is {fps / 5:.0f} cameras of detector headroom on this device")
    return fps


def main(argv=None):
    ap = argparse.ArgumentParser(description="[I2] inference backend")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--batch", type=int, default=MAX_BATCH)
    ap.add_argument("--device", help="cuda:0 | cpu (default: cuda when torch sees one)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if args.bench:
        bench(batch=args.batch, device=args.device)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
