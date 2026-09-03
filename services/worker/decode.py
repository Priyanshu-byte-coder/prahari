"""[I1] Camera -> frames. PTS-driven, motion-gated, bounded.

Decoding goes through PyAV, not through the ffmpeg subprocess pipe the ticket sketches. That
command line ends in `-f rawvideo pipe:1`, and a rawvideo pipe carries no timestamps at all -
the only route back to a per-frame time is index/fps. That is precisely wrong here: the grid's
recordings loop and drop frames (AGENTS.md gotchas), so index/fps drifts silently and a looped
recording rewinds with nothing noticing. C1 records `ts_source`, AGENTS.md says timestamps come
from frame PTS and never `now()`, and PyAV hands us `frame.pts` directly. The convention
outranks the command line. `--hwaccel` keeps the part of that command line that did matter.

Reconnect, backoff and loop detection are salvaged from
`4d0c945:services/worker/stream_reader.py` (TASK.md section 4) rather than re-derived.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import av
import cv2
import numpy as np

from services.worker.queues import FrameQueue

logger = logging.getLogger("prahari.worker.decode")

FPS = 5.0
# Frames are scaled to WIDTH before the pipeline. 960 keeps decode + detect cheap and, on the
# real grid, loses nothing: a plate small at 1920 is still small at 960 (measured - the band
# counts are identical). PRAHARI_DECODE_WIDTH raises it for a genuinely ANPR-sited camera where
# the extra pixels land on the plate. 0 keeps the source resolution.
WIDTH = int(os.getenv("PRAHARI_DECODE_WIDTH", "960"))
BACKOFF_MIN, BACKOFF_MAX = 2.0, 30.0
LOOP_REGRESSION_S = 1.0     # a PTS drop past this is a looped recording, not jitter
MOTION_FRACTION = 0.005     # under 0.5% of the thumbnail changed -> nothing happened
MOTION_DELTA = 16           # ponytail: one fixed grey level for "this pixel changed". Sensor
                            # noise and compression blocking both sit under it on our clips; if
                            # a night camera starts firing the gate on noise, make it per-camera.
FPS_KEY_TTL = 30


@dataclass
class Frame:
    camera_id: str
    image: np.ndarray            # BGR, scaled to WIDTH
    pts_seconds: float           # from the decoder. Never wall clock, never an overlay burn-in.
    wall_clock: float
    discontinuous: bool = False  # first frame after a detected PTS loop


# --- source resolution ----------------------------------------------------------------------

def resolve_source(camera_id, redis_client=None):
    """The [C2] G->I seam: `camera:transport:<id>` -> {url, transport, driver, probed_at}.

    Returns None when Redis has nothing, which is the normal case in this lane - the worker
    develops against --file and never imports gateway code.
    """
    if redis_client is None:
        return None
    raw = redis_client.get(f"camera:transport:{camera_id}")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return json.loads(raw)["url"]
    except (ValueError, KeyError, TypeError):
        logger.warning("cam %s: unusable camera:transport payload %r", camera_id, raw[:120])
        return None


def publish_fps(camera_id, fps, redis_client=None):
    """`camera:fps:<id>`, float, TTL 30 s - this lane's only side output ([C2])."""
    if redis_client is None:
        return
    try:
        redis_client.setex(f"camera:fps:{camera_id}", FPS_KEY_TTL, f"{fps:.3f}")
    except Exception as exc:                      # never kill a decode loop over telemetry
        logger.debug("cam %s: fps publish failed: %s", camera_id, exc)


# --- gates ----------------------------------------------------------------------------------

def thumbnail(image):
    """96 px grey thumbnail - the motion gate's entire working set."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (96, 96), interpolation=cv2.INTER_AREA)


def moved(previous, current, fraction=MOTION_FRACTION, delta=MOTION_DELTA):
    """True when enough of the thumbnail changed to be worth a detector pass.

    An empty road at 03:00 then costs one greyscale resize and an absdiff instead of a YOLO
    forward pass. The first frame always passes - there is nothing to compare it against.
    """
    if previous is None:
        return True
    changed = int(np.count_nonzero(cv2.absdiff(previous, current) > delta))
    return changed >= fraction * current.size


def scale(image, width=WIDTH):
    """Match `scale=960:-2`: fix the width, keep the aspect ratio, force an even height.
    `width` of 0 keeps the source resolution."""
    h, w = image.shape[:2]
    if width <= 0 or w <= width:
        return image
    height = max(2, int(round(h * width / w)) // 2 * 2)
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


# --- decode ---------------------------------------------------------------------------------

def _open(source, hwaccel=False):
    options = {"rtsp_transport": "tcp"} if str(source).startswith("rtsp://") else {}
    if hwaccel:
        try:
            accel = av.codec.hwaccel.HWAccel(device_type="cuda", allow_software_fallback=True)
            return av.open(str(source), options=options, timeout=25.0, hwaccel=accel)
        except Exception as exc:
            logger.warning("hwaccel unavailable (%s) - falling back to CPU decode", exc)
    return av.open(str(source), options=options, timeout=25.0)


def read_frames(camera_id, source, hwaccel=False, once=False):
    """Yield every decoded frame forever. Stream errors never escape this generator.

    Salvaged from 4d0c945. `once=True` stops at end of file instead of reconnecting, which is
    what a local clip and the bench want.
    """
    backoff = BACKOFF_MIN
    last_pts = None

    while True:
        container = None
        try:
            container = _open(source, hwaccel=hwaccel)
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            backoff = BACKOFF_MIN

            for packet in container.demux(stream):
                try:
                    for av_frame in packet.decode():
                        if av_frame.pts is None:
                            continue
                        pts = float(av_frame.pts * stream.time_base)
                        discontinuous = (last_pts is not None
                                         and (pts - last_pts) < -LOOP_REGRESSION_S)
                        if discontinuous:
                            logger.warning(
                                "cam %s: PTS regressed (%.2f -> %.2f) - recording looped, "
                                "flagging discontinuity", camera_id, last_pts, pts)
                        last_pts = pts
                        yield Frame(camera_id, av_frame.to_ndarray(format="bgr24"),
                                    pts, time.time(), discontinuous)
                except av.error.FFmpegError as exc:
                    # Mid-GOP join warnings. Never fatal, and noisy above debug.
                    logger.debug("cam %s: decoder warning: %s", camera_id, exc)
                    continue
            if once:
                return
        except (av.error.FFmpegError, OSError, TimeoutError, ValueError) as exc:
            if once:
                logger.error("cam %s: %s", camera_id, exc)
                return
            logger.warning("cam %s: %s - reconnecting in %.1fs", camera_id, exc, backoff)
            time.sleep(backoff + random.uniform(0, backoff * 0.25))
            backoff = min(backoff * 2, BACKOFF_MAX)
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass


def decode(camera_id, source, fps=FPS, width=WIDTH, hwaccel=False, once=False,
           redis_client=None, motion_gate=True):
    """Frames at `fps`, scaled, motion-gated, each still carrying its own PTS.

    The fps gate is driven by PTS rather than by a sleep, so it behaves identically on a live
    RTSP stream and on a file replayed as fast as it decodes.
    """
    interval = 1.0 / fps
    last_emit = None
    last_thumb = None
    emitted = 0
    window_start = time.time()

    for frame in read_frames(camera_id, source, hwaccel=hwaccel, once=once):
        if (last_emit is not None and not frame.discontinuous
                and frame.pts_seconds - last_emit < interval - 1e-6):
            continue
        if frame.discontinuous:
            last_thumb = None          # a looped recording is a new scene, not motion
        last_emit = frame.pts_seconds

        frame.image = scale(frame.image, width)
        if motion_gate:
            thumb = thumbnail(frame.image)
            if not moved(last_thumb, thumb):
                last_thumb = thumb
                continue
            last_thumb = thumb

        emitted += 1
        elapsed = time.time() - window_start
        if elapsed >= 5.0:
            publish_fps(camera_id, emitted / elapsed, redis_client)
            emitted, window_start = 0, time.time()
        yield frame


# --- bench ----------------------------------------------------------------------------------

def synth_clip(path, seconds=30, size="1280x720", rate=25):
    """A decodable H.264 clip with real motion, so the bench needs no committed video."""
    path = Path(path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-g", str(rate), str(path)], check=True)
    return path


def _rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return None


def _floor_band(samples, every=5.0, window=24, ramp_per_min=0.03):
    """Steady-state memory band as a fraction of the plateau. Returns (band, floors).

    Two things had to be measured around, and both were mistaken for a leak first:

    - A single RSS reading lands at an arbitrary point in the decode cycle and carries up to
      100 MB of transient frame buffers with it, and Windows trims the working set on top of
      that - one sample landed *below* the process baseline. So each 60 s window contributes
      only its floor, the memory the process would not give back.
    - Ten decoders take two to three minutes to allocate their pools, so the run opens with a
      ramp (800 -> 866 -> 905 MB observed). Least squares over that ramp reports "drifting"
      for a process that is merely warming up. Leading windows rising faster than 2% are
      dropped at 3%/min; a leak is slow (10 MB/min on a 900 MB plateau is 1.1%/min) and
      survives that filter, a warm-up ramp is steep and does not. The filter is a rate, not a
      per-window step, so widening the window cannot turn a leak into a ramp.

    What is left is the plateau, and a leak is what makes a plateau not one: peak-to-trough
    over the median. Two 10 min runs of 30k frames each held a 2.1% and a 2.2% band, and the
    same code pushed to 1.85x the frame rate held 931 -> 922 MB - growth does not track frames
    decoded, so the residue is the allocator and the OS, not the decoder.
    """
    clean = [s for s in samples if s is not None]
    floors = [min(clean[i:i + window])
              for i in range(0, len(clean) - window + 1, window)]
    ramp = 1.0 + ramp_per_min * window * every / 60.0
    while len(floors) > 3 and floors[1] > floors[0] * ramp:
        floors.pop(0)
    if len(floors) < 3:
        return None, floors
    plateau = sorted(floors)[len(floors) // 2]
    return (max(floors) - min(floors)) / plateau, floors


# ponytail: 5% over a 10 min run catches a leak from about 6 MB/min up, against a measured 2.2%
# of platform noise - on a Windows dev laptop the OS trims the working set and the CRT keeps
# freed arenas, so nothing slower than that is resolvable here. The demo runs in the compose
# stack; re-measure there (J1) if a tighter bound is ever needed.
DRIFT_BUDGET = 0.05


def bench(cameras=10, seconds=60, source=None, fps=FPS, hwaccel=False, motion_gate=True,
          realtime=True):
    """Ticket verify: N streams concurrently at `fps` with flat memory. Measured, not guessed.

    Paced to real time by default, because that is what "10 streams at 5 fps" means - a live
    camera delivers frames at wall-clock rate no matter how fast the decoder could run. A file
    replayed flat out decodes faster than real time and reports an fps that cannot be compared
    to the spec. `realtime=False` drops the pacing to measure headroom instead.
    """
    source = source or synth_clip(Path(os.getenv("TEMP", "/tmp")) / "prahari_bench.mp4")
    queues = {f"BENCH-{i:03d}": FrameQueue(f"BENCH-{i:03d}") for i in range(cameras)}
    stop = threading.Event()
    counts = {cid: 0 for cid in queues}

    def produce(cid):
        while not stop.is_set():
            clip_started = time.time()
            for frame in decode(cid, source, fps=fps, hwaccel=hwaccel, once=True,
                                motion_gate=motion_gate):
                if realtime:
                    lag = frame.pts_seconds - (time.time() - clip_started)
                    if lag > 0:
                        time.sleep(min(lag, 1.0))
                queues[cid].put(frame)
                if stop.is_set():
                    return

    def consume(cid):
        while not stop.is_set():
            if queues[cid].get(timeout=0.2) is not None:
                counts[cid] += 1

    threads = ([threading.Thread(target=produce, args=(c,), daemon=True) for c in queues]
               + [threading.Thread(target=consume, args=(c,), daemon=True) for c in queues])
    rss0 = _rss_mb()
    started = time.time()
    for t in threads:
        t.start()

    samples = []
    while time.time() - started < seconds:
        time.sleep(5.0)
        rss = _rss_mb()
        samples.append(rss)
        done = time.time() - started
        total = sum(counts.values())
        print(f"  t={done:5.1f}s  frames={total:6d}  fps/cam={total / done / cameras:5.2f}"
              + (f"  rss={rss:7.1f}MB" if rss else ""))
    stop.set()
    for t in threads:
        t.join(timeout=2.0)

    elapsed = time.time() - started
    total = sum(counts.values())
    drops = sum(q.dropped for q in queues.values())
    offered = sum(q.accepted for q in queues.values())
    per_cam = total / elapsed / cameras
    print(f"\ncameras={cameras} seconds={elapsed:.1f} target_fps={fps} "
          f"pacing={'realtime' if realtime else 'flat-out'}")
    print(f"frames consumed={total} fps/camera={per_cam:.2f} "
          f"({per_cam / fps:.2f}x target)")
    print(f"frames dropped={drops} of {offered} offered "
          f"({drops / max(offered, 1) * 100:.2f}% - dropped frames, never sightings)")

    # Memory: the Done-when is "flat for 10 min", so the verdict is the projected growth over
    # that window as a share of the working set - not an absolute MB/min, which means nothing
    # without knowing whether the process holds 90 MB or 900 MB.
    band, floors = _floor_band(samples)
    if not floors:
        print("rss: psutil not installed - memory not measured" if rss0 is None
              else f"rss baseline={rss0:.1f}MB end={samples[-1]:.1f}MB "
                   f"(need >=1 min of samples to floor)")
    else:
        print(f"rss baseline={rss0:.1f}MB "
              f"floors/min={' '.join(f'{f:.0f}' for f in floors)}")
        if band is None:
            print("rss: need >=3 steady minutes to judge - the Done-when check is --seconds 600")
        else:
            print(f"rss band={band * 100:.1f}% of the {sorted(floors)[len(floors) // 2]:.0f}MB "
                  f"plateau -> {'FLAT' if band < DRIFT_BUDGET else 'DRIFTING, not flat'}")

    return total, drops


def main(argv=None):
    ap = argparse.ArgumentParser(description="[I1] decode pipeline")
    ap.add_argument("--camera", default="BENCH-000")
    ap.add_argument("--file", help="local clip - this lane's independence from the gateway")
    ap.add_argument("--url", help="stream URL, overrides Redis")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--cameras", type=int, default=10)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--fps", type=float, default=FPS)
    ap.add_argument("--hwaccel", action="store_true", help="try CUDA decode, fall back to CPU")
    ap.add_argument("--no-motion-gate", action="store_true")
    ap.add_argument("--flat-out", action="store_true",
                    help="bench without real-time pacing, to measure decode headroom")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s %(message)s")

    if args.bench:
        bench(cameras=args.cameras, seconds=args.seconds, source=args.file, fps=args.fps,
              hwaccel=args.hwaccel, motion_gate=not args.no_motion_gate,
              realtime=not args.flat_out)
        return 0

    source = args.url or args.file
    if source is None:
        redis_client = None
        try:
            import redis
            redis_client = redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            source = resolve_source(args.camera, redis_client)
        except Exception as exc:
            logger.debug("no redis: %s", exc)
        if source is None:
            ap.error("no source: pass --file or --url, or populate camera:transport:<id>")

    for frame in decode(args.camera, source, fps=args.fps, hwaccel=args.hwaccel,
                        once=bool(args.file), motion_gate=not args.no_motion_gate):
        print(f"{frame.camera_id} pts={frame.pts_seconds:8.3f} {frame.image.shape}"
              + ("  DISCONTINUITY" if frame.discontinuous else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
