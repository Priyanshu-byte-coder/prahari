"""The worker: cameras in, [C1] sighting rows out. This is where I1-I6 become one process.

    decode (I1)  ->  bounded queue (I1)  ->  batched detect (I2)  ->  ByteTrack per camera (I3)
                 ->  sighting builder (I3)  ->  plate candidates + readers + vote (I4)
                 ->  Redis XADD + MinIO PUT (I6)                      /metrics throughout (I6)

Two loops, not one thread per stage. Decoding is blocking I/O and gets a thread per camera;
everything after it is GPU work and runs on one loop, because two threads taking turns on one
GPU is slower than one thread using it properly. The batcher is what makes the single loop fast
enough: frames from every camera go into one forward pass.

OCR is the exception, and it had to be: two readers over one crop cost about 0.8 s, which is
four frames at 5 fps. Run inline, it emptied the depth-2 queues and the pipeline processed two
frames of a thirty-frame pass - the plate was decoded, detected, tracked, and then dropped on
the floor. So OCR runs on its own thread with a bounded queue, and a sighting waits (briefly)
for its outstanding reads when it closes. The budget is still the ticket's: a crop is only
queued when the track has no CONFIRMED read and this crop is sharper than the last one read.
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import threading
import time
from collections import Counter

from services.worker import metrics
from services.worker.backend import Batcher, LocalBackend
from services.worker.decode import FPS, decode, resolve_source
from services.worker.plate import read_all, readers
from services.worker.publish import Publisher
from services.worker.queues import FrameQueue
from services.worker.sighting import SightingBuilder, sharpness
from services.worker.tracker import Trackers

logger = logging.getLogger("prahari.worker.run")

MIN_CROP_PX = 48         # a vehicle box smaller than this has no readable plate at any upscale
# Crops waiting to be read; full means the budget is spent, skip one. Queue depth multiplied
# by the cost of a read *is* the tail latency of a sighting: at four deep and ~1.6 s a read
# with the trained detector and two engines, the last crop of a track landed 6.5 s after
# the vehicle passed, against a 3 s budget. Two deep fits, and a track that needs more than
# two looks at the same plate is a track the vote is not going to settle anyway. Measured on the
# selftest clip: depth 4 -> 6.5 s, depth 2 -> 5.7 s, depth 1 -> 0.68 s, all reading the plate
# correctly and landing CONFIRMED. One in flight it is; raise it where reads are cheaper (a GPU)
# or the budget is looser.
OCR_QUEUE = int(os.getenv("PRAHARI_OCR_QUEUE", "1"))
# How long a closing sighting waits for its outstanding reads. Tunable because the cost of a
# read is not fixed: one fast reader on one crop is milliseconds, while super-resolution
# over a fused track with two readers is seconds. Too low and the row publishes with
# plate=NONE while the answer was moments away - which reads as "the OCR failed" and is
# really "nobody waited".
OCR_DRAIN_S = float(os.getenv("PRAHARI_OCR_DRAIN_S", "6.0"))

# --- grid-measured preprocessing (services/worker/preprocess.py) ----------------------------
# On the real grid a lot of cameras give a vehicle box too small for a readable plate, and the
# 960->640 detector letterbox loses the small ones entirely. `prepare_frame` conditions the
# frame for the detector; `feasibility` refuses an OCR pass whose glyphs were never sampled -
# tracking the vehicle and saying "plate not resolvable here" beats four confident characters
# of noise. Both are on by default and each has an env kill-switch in case they regress.
_PREP_FRAMES = os.getenv("PRAHARI_PREPROCESS_FRAMES", "1").strip().lower() not in ("0", "false", "no")
_FEAS_GATE = os.getenv("PRAHARI_FEASIBILITY_GATE", "1").strip().lower() not in ("0", "false", "no")
# Multi-frame fusion: align + average several crops of one tracked plate before OCR. Adds
# information from other frames (unlike a generative SR model, which invents it), so it lifts
# a borderline read without risking a confident-wrong. On by default; PRAHARI_OCR_FUSION=0 off.
_FUSE = os.getenv("PRAHARI_OCR_FUSION", "1").strip().lower() not in ("0", "false", "no")
# SR-ensemble + majority vote by character position (mvcp.py). Costs several reconstructions
# and an OCR pass over each, so it is gated on a track having enough crops to be worth it.
_MVCP = os.getenv("PRAHARI_MVCP", "1").strip().lower() not in ("0", "false", "no")
_MVCP_MIN_CROPS = int(os.getenv("PRAHARI_MVCP_MIN_CROPS", "4"))

try:
    from services.worker.preprocess import feasibility as _feasibility
    from services.worker.preprocess import prepare_frame as _prepare_frame
    from services.worker.preprocess import prepare_for_ocr as _prepare_for_ocr
except Exception as _exc:                     # pragma: no cover - preprocess deps missing
    _feasibility = _prepare_frame = _prepare_for_ocr = None
    logging.getLogger("prahari.worker.run").warning(
        "preprocess.py not importable (%s) - frame conditioning, feasibility gate and OCR "
        "fusion are off", _exc)


def _settled(readings):
    """True when two readers already agree on a plate-shaped string.

    That is the vote's own bar for a confident answer, so anything beyond it can only cost
    latency: a further reconstruction cannot outvote an existing majority, it can only delay the
    row. When this is False the plate is hard - small, skewed, dark - and the expensive
    multi-reconstruction path is exactly what should run next.
    """
    from common.plate import grammar_fix, normalise
    from services.worker.vote import VALID

    seen = {}
    for reading in readings:
        text = grammar_fix(normalise(reading.text or "")) or ""
        if not VALID.match(text):
            continue
        seen[text] = seen.get(text, 0) + 1
        if seen[text] >= 2:
            return True
    return False


class OcrPool:
    """OCR on its own threads, with a per-sighting wait for the close path.

    Bounded on purpose: when the readers fall behind, new crops are refused rather than
    queued. A queue that grows is a queue that reads a plate two minutes after the vehicle
    left, and the sighting it belongs to closed long ago.
    """

    def __init__(self, workers=1, depth=OCR_QUEUE, read=read_all):
        self._read = read
        self._queue = queue.Queue(maxsize=depth)
        self._pending = Counter()
        self._done = threading.Condition()
        self._threads = [threading.Thread(target=self._loop, daemon=True, name=f"ocr-{i}")
                         for i in range(workers)]
        for thread in self._threads:
            thread.start()

    def submit(self, sighting, crops):
        """Queue a crop, or a list of a track's crops to fuse. False when the queue is full."""
        if crops is None:
            return False
        if not isinstance(crops, (list, tuple)):
            crops = [crops]
        crops = [c for c in crops if c is not None and getattr(c, "size", 0)]
        if not crops:
            return False
        with self._done:
            if self._queue.full():
                return False
            self._pending[id(sighting)] += 1
        self._queue.put((sighting, crops))
        return True

    def _loop(self):
        try:
            readers()          # loading the engines costs ~20 s; overlap it with decoding
        except Exception as exc:
            logger.warning("no OCR reader loaded: %s", exc)
        while True:
            item = self._queue.get()
            if item is None:
                return
            sighting, crops = item
            best = crops[0]
            try:
                with metrics.timed("ocr"):
                    readings = list(self._read(best))
                    # Multi-frame fusion aligns and super-resolves the track's crops. Measured on
                    # this laptop it costs about nine seconds a track - worth every one of them on
                    # a distant plate that no single frame resolves, and pure latency on a plate
                    # two readers have already agreed on. Escalate, do not always run: with this
                    # gate the selftest is 0.8 s, without it 10.3 s against a 3 s budget.
                    if (_FUSE and _prepare_for_ocr is not None and len(crops) > 1
                            and not _settled(readings)):
                        fused = self._fused(crops)
                        if fused is not None:
                            readings += list(self._read(fused))
                    # On a small, degraded plate one reconstruction is a guess. Build several
                    # and let the character-position majority decide - the step that takes the
                    # published LR benchmark from ~31% to ~45% (mvcp.py). Only when the track
                    # has enough crops to make the variants genuinely independent.
                    #
                    # And only when the cheap path has not already answered. MVCP reads several
                    # reconstructions with every engine; on a plate that two readers have already
                    # agreed on it buys nothing and costs seconds - measured, it took the
                    # selftest from 1.9 s to 11.6 s against a 3 s budget. Escalate to it when the
                    # easy path failed, which is the case it was built for.
                    if _MVCP and len(crops) >= _MVCP_MIN_CROPS and not _settled(readings):
                        readings += self._mvcp_readings(crops)
                sighting.add_readings(readings, sharpness(best))
            except Exception as exc:
                logger.warning("OCR failed on a crop: %s", exc)
            finally:
                with self._done:
                    self._pending[id(sighting)] -= 1
                    self._done.notify_all()

    @staticmethod
    def _fused(crops):
        """Align + average the track's crops into one cleaner plate image, or None."""
        try:
            return _prepare_for_ocr(crops)
        except Exception as exc:
            logger.debug("fusion failed (%s) - reading the sharpest crop only", exc)
            return None

    @staticmethod
    def _mvcp_readings(crops):
        """The SR-ensemble majority verdict, as one extra high-confidence Reading, or [].

        Returned as a Reading rather than applied directly so the existing per-track vote
        still owns the final call: MVCP is a strong opinion, not an override.
        """
        try:
            from services.worker.backend import Reading
            from services.worker.mvcp import decode_track
            text, conf, detail = decode_track(crops)
            if not text:
                return []
            logger.debug("mvcp %s conf=%.2f over %d variants", text, conf, detail["variants"])
            return [Reading(text, float(conf), reader="mvcp")]
        except Exception as exc:
            logger.debug("mvcp failed (%s)", exc)
            return []

    def drain(self, sighting, timeout=OCR_DRAIN_S):
        """Wait for this sighting's reads before its row is built. Bounded: a stuck reader
        delays one row by `timeout`, it does not hold the stream."""
        with self._done:
            if not self._done.wait_for(lambda: not self._pending[id(sighting)], timeout):
                logger.warning("publishing %s with an OCR read still outstanding",
                               sighting.sighting_id[:10])
            self._pending.pop(id(sighting), None)

    def close(self):
        """Stop the readers. Queued crops are dropped, not drained.

        Every sighting that mattered has already had its own `drain()`; what is left in the
        queue belongs to rows that are published. Draining it at shutdown made a 6 s replay
        take a minute to exit - and made I8's latency measurement a measurement of the
        shutdown path.
        """
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        if dropped:
            logger.info("dropped %d queued crops at shutdown", dropped)
        for _ in self._threads:
            self._queue.put(None)
        for thread in self._threads:
            thread.join(timeout=5.0)


class Worker:
    """One process, N cameras. `cameras` maps camera_id -> source (URL or file path)."""

    def __init__(self, cameras, backend=None, publisher=None, fps=FPS, hwaccel=False,
                 once=False, reid=False, analytics=None, motion_gate=True, pace=None,
                 ocr=None):
        self.cameras = dict(cameras)
        self.backend = backend if backend is not None else LocalBackend()
        self.publisher = publisher if publisher is not None else Publisher()
        self.fps = fps
        self.hwaccel = hwaccel
        self.once = once
        self.reid = reid
        self.analytics = analytics
        self.motion_gate = motion_gate
        # A file decodes as fast as the disk allows, so an unpaced replay hands the queues
        # hundreds of frames a second and the depth-2 drop rule throws away nine out of ten -
        # correct for a live camera that is ahead of the GPU, wrong for a clip we are asking
        # the pipeline to actually process. Replays are paced to their own PTS; live sources
        # arrive paced already.
        self.pace = once if pace is None else pace
        self.queues = {cid: FrameQueue(cid) for cid in self.cameras}
        self.trackers = Trackers()
        self.builders = {cid: SightingBuilder(cid) for cid in self.cameras}
        self.batcher = Batcher()
        self.ocr = ocr if ocr is not None else OcrPool()
        self.published = 0
        self.last_frame_wall = None       # I8 measures publish latency against this
        self._stop = threading.Event()
        self._threads = []

    def warm(self):
        """Load every model before the clock starts.

        Weight loading, the CUDA context and the OCR engines are seconds of one-off cost that
        have nothing to do with steady-state latency - and a pass that happens during them gets
        no plate read at all, which is how I8 measured a CONFIRMED plate as NONE.
        """
        import numpy as np
        blank = np.zeros((544, 960, 3), dtype=np.uint8)
        self.backend.detect([blank])
        engines = readers()
        # The trained plate detector loads lazily on its first call, and so does each OCR engine's
        # graph. Left cold, that cost lands inside the first sighting's OCR drain instead of here:
        # measured 23 s for the first read_all against 1.6 s warm, which published the first
        # vehicle with plate=NONE and looked exactly like an OCR failure.
        try:
            from services.worker.plate import detect_plate_boxes
            detect_plate_boxes(np.zeros((128, 256, 3), dtype=np.uint8))
        except Exception as exc:                       # optional dependency; never fatal
            logger.debug("plate detector not warmed: %s", exc)
        for engine in engines:
            try:
                engine.read(np.zeros((64, 192, 3), dtype=np.uint8))
            except Exception as exc:
                logger.debug("reader %s not warmed: %s", engine.name, exc)
        if hasattr(self.publisher, "warm"):
            self.publisher.warm()

    # --- decode side --------------------------------------------------------------------

    def _produce(self, camera_id):
        source = self.cameras[camera_id]
        started = time.time()
        for frame in decode(camera_id, source, fps=self.fps, hwaccel=self.hwaccel,
                            once=self.once, motion_gate=self.motion_gate):
            if self.pace:
                lag = frame.pts_seconds - (time.time() - started)
                if lag > 0:
                    time.sleep(min(lag, 1.0))
            self.queues[camera_id].put(frame)
            if self._stop.is_set():
                return

    def start(self):
        for camera_id in self.cameras:
            t = threading.Thread(target=self._produce, args=(camera_id,), daemon=True,
                                 name=f"decode-{camera_id}")
            t.start()
            self._threads.append(t)

    # --- inference side -----------------------------------------------------------------

    def _collect(self):
        """One pass over every camera's queue. Returns a batch when one is ready."""
        batch = None
        for q in self.queues.values():
            frame = q.get(timeout=0.0 if len(self.queues) > 1 else 0.05)
            if frame is not None:
                batch = self.batcher.add(frame) or batch
        return batch or self.batcher.due()

    def _detector_images(self, frames):
        """Frame images conditioned for the detector. Never resizes - the backend owns scaling."""
        if not (_PREP_FRAMES and _prepare_frame is not None):
            return [f.image for f in frames]
        out = []
        for f in frames:
            try:
                out.append(_prepare_frame(f.image))
            except Exception as exc:          # a filter must never take the pipeline down
                logger.debug("prepare_frame failed on cam %s (%s) - using the raw frame",
                             f.camera_id, exc)
                out.append(f.image)
        return out

    def process(self, frames):
        """Detect, track, build sightings, spend the OCR budget, publish what closed."""
        with metrics.timed("detect"):
            detections = self.backend.detect(self._detector_images(frames))
        self.last_frame_wall = max(f.wall_clock for f in frames)
        for frame, dets in zip(frames, detections):
            builder = self.builders[frame.camera_id]
            if frame.discontinuous:
                for sighting in builder.flush():
                    self._publish(sighting)
            tracks = self.trackers.update(frame.camera_id, dets, frame.pts_seconds,
                                          discontinuous=frame.discontinuous)
            for track in tracks:
                self._observe(builder, track, frame)
            if self.analytics is not None:
                self.analytics.observe(frame.camera_id, tracks, builder.epoch(frame.pts_seconds))
            for sighting in builder.tick(frame.pts_seconds):
                self._publish(sighting)

    def _observe(self, builder, track, frame):
        x1, y1, x2, y2 = (int(v) for v in track.xyxy)
        h, w = frame.image.shape[:2]
        crop = frame.image[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        sighting = builder.observe(track, crop=crop, wall_clock=frame.wall_clock)
        if min(crop.shape[:2]) < MIN_CROP_PX or not sighting.wants_ocr:
            return
        if not self._ocr_feasible(sighting, x2 - x1):
            return
        self.ocr.submit(sighting, sighting.claim_ocr_crops())

    def _ocr_feasible(self, sighting, vehicle_w_px):
        """The grid-measured gate: is a plate on a vehicle this wide readable at all?

        `verdict == "no"` means the glyph strokes were never sampled at this camera - we keep
        tracking the vehicle (the sighting still publishes, plate_band NONE) but spend no OCR
        pass guessing. Logged once per track so the demo can point at the honest refusal.
        """
        if not (_FEAS_GATE and _feasibility is not None):
            return True
        try:
            verdict = _feasibility(vehicle_w_px)
        except Exception:
            return True
        if verdict.readable:
            return True
        if not getattr(sighting, "_feasibility_logged", False):
            logger.info("sighting %s cam=%s track=%s: plate not resolvable here (%s) - "
                        "tracking without OCR", sighting.sighting_id[:10], sighting.camera_id,
                        sighting.track_id, verdict.reason)
            try:
                sighting._feasibility_logged = True
            except Exception:
                pass
        return False

    def _publish(self, sighting):
        self.ocr.drain(sighting)
        if self.reid and sighting.crop is not None:
            try:
                with metrics.timed("reid"):
                    sighting.reid_vec = [float(v) for v in self.backend.reid([sighting.crop])[0]]
            except Exception as exc:
                logger.warning("re-id unavailable (%s) - publishing without a vector", exc)
        self.publisher.publish(sighting)
        self.published += 1
        text, _conf, band = (sighting.vote.result() if sighting.vote else (None, 0, "NONE"))
        logger.info("sighting %s cam=%s track=%s %s plate=%s [%s] frames=%d",
                    sighting.sighting_id[:10], sighting.camera_id, sighting.track_id,
                    sighting.label, text or "-", band, sighting.frames)

    def run(self, seconds=None):
        """Run until `seconds` elapse, the clips end (`once`), or stop() is called."""
        self.start()
        started = time.time()
        idle = 0
        try:
            while not self._stop.is_set():
                if seconds is not None and time.time() - started >= seconds:
                    break
                batch = self._collect()
                if batch:
                    idle = 0
                    self.process(batch)
                else:
                    idle += 1
                    time.sleep(0.005)
                    if self.once and idle > 2 and self._drained():
                        break
                metrics.record_queues(self.queues.values())
        finally:
            self.stop()
        return self.published

    def _drained(self):
        """True when a replay has nothing left anywhere: no decoder, no queue, no batch.

        Checked instead of waiting out a fixed idle timeout, because the timeout is measured
        by I8 as pipeline latency - the row is not late, the loop was.
        """
        return (not any(t.is_alive() for t in self._threads)
                and not any(q.depth for q in self.queues.values())
                and not len(self.batcher))

    def stop(self):
        self._stop.set()
        for batch in (self.batcher.flush(),):
            if batch:
                self.process(batch)
        for builder in self.builders.values():
            for sighting in builder.flush():
                self._publish(sighting)
        self.ocr.close()
        self.publisher.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prahari inference worker: cameras -> sightings")
    ap.add_argument("--camera", action="append", default=[],
                    help="camera_id[=source]; source falls back to camera:transport:<id> [C2]")
    ap.add_argument("--file", help="one local clip, this lane's independence from the gateway")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--fps", type=float, default=FPS)
    ap.add_argument("--hwaccel", action="store_true")
    ap.add_argument("--reid", action="store_true", help="[I10] attach a 512-d vector")
    ap.add_argument("--analytics", action="store_true", help="[I12] crowd, wrong-way, loitering")
    ap.add_argument("--metrics-port", type=int, default=metrics.PORT)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s %(message)s")

    cameras = {}
    for spec in args.camera:
        camera_id, _, source = spec.partition("=")
        cameras[camera_id] = source or None
    if args.file:
        cameras.setdefault("CLIP-000", args.file)
    if not cameras:
        ap.error("no cameras: pass --camera <id>[=<url>] or --file <clip>")

    redis_client = getattr(Publisher(), "redis", None)
    for camera_id, source in list(cameras.items()):
        if source is None:
            cameras[camera_id] = resolve_source(camera_id, redis_client)
            if cameras[camera_id] is None:
                ap.error(f"no source for {camera_id}: set camera:transport:{camera_id} or "
                         f"pass {camera_id}=<url>")

    analytics = None
    if args.analytics:
        from services.worker.analytics import Analytics
        analytics = Analytics()

    metrics.serve(args.metrics_port)
    worker = Worker(cameras, fps=args.fps, hwaccel=args.hwaccel, once=bool(args.file),
                    reid=args.reid, analytics=analytics)
    published = worker.run(seconds=args.seconds)
    print(f"published {published} sightings")
    if analytics is not None:
        for event in analytics.events:
            print(f"  analytics: {event}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("YOLO_VERBOSE", "0")
    raise SystemExit(main())
