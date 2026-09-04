"""[I8]/[I6] The replay harness: inject a known plate, assert it comes out on the stream.

This is the command that answers "is the lane working right now" in one line, and it is what
J1's integration test drives. Everything it asserts is something a judge will see:

    a [C1]-shaped row on the `sightings-selftest` stream - shape-identical to the seam D
                                                          reads, but off it: SELFTEST-000 is
                                                          not a registry camera, so a synthetic
                                                          row must never reach production storage
                                                          ([#48]). Pass `--stream sightings`
                                                          with a real `--camera` for a live demo.
    the plate we injected, read back from the video    - the pipeline, end to end
    published within the latency budget                - it is a live system, not a batch job

The clip is generated, not committed (`synth.py`): a rendered plate on a real vehicle
photograph, so the detector still has to detect and the readers still have to read, but the
ground truth is exact and the repo carries no video.

**Latency, measured honestly.** The budget covers the last frame of the vehicle's pass reaching
the pipeline through to the row being readable on the stream. The 6 s close window (I3) is a
deliberate wait for the vehicle to leave, not pipeline cost, so it is subtracted when the source
runs in real time - a file decoded flat out has already paid it in stream time by then. Both
numbers are printed; the assertion is on the pipeline half.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# The repo root on sys.path, the way every script and test here does it. Without this,
# `python services/worker/selftest.py` from the repo root dies on the first import - and that is
# the one command a judge is most likely to run to prove the CV path works.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.worker.publish import FIELDS, Publisher, validate
from services.worker.sighting import CLOSE_AFTER_S
from services.worker.synth import CLIPS, make_clip

logger = logging.getLogger("prahari.worker.selftest")

BUDGET_S = 3.0
CAMERA_ID = "SELFTEST-000"
# [#48] Synthetic rows land here, not on `sightings`. SELFTEST-000 is not in `cameras`, so a
# live persister rejects it (FK violation) and dead-letters it since #46. Keeping the row off
# the real stream means J1 never has to reason about whether a fake sighting reached storage.
SELFTEST_STREAM = "sightings-selftest"


def _redis(url=None):
    """A real Redis when there is one, fakeredis otherwise - and say which, loudly.

    A green selftest against fakeredis proves the pipeline and the row shape, not the
    deployment. The line it prints is what stops that distinction being lost in a screenshot.
    """
    client = Publisher(redis_url=url).redis
    if client is not None:
        return client, "redis"
    try:
        import fakeredis
        return fakeredis.FakeRedis(), "fakeredis"
    except ImportError:
        return None, "none"


def run(clip=None, plate=None, source=None, camera_id=CAMERA_ID, budget=BUDGET_S,
        redis_url=None, stream=SELFTEST_STREAM, require_plate=True, reid=False, seconds=None):
    """Replay one clip through the whole worker and check what landed. Returns a report dict."""
    from services.worker.run import Worker         # heavy: torch, ultralytics

    if source is None:
        clip = Path(clip) if clip else CLIPS / "selftest.mp4"
        if not clip.exists() or plate is None:
            clip, plate = make_clip(clip, plate=plate, seconds=6)
        source = str(clip)
    realtime = str(source).startswith(("rtsp://", "http://", "https://"))

    client, kind = _redis(redis_url)
    if client is None:
        raise RuntimeError("no Redis and no fakeredis - install fakeredis or start Redis")
    last_id = _last_id(client, stream)

    publisher = Publisher(redis_client=client, stream=stream)
    worker = Worker({camera_id: source}, publisher=publisher, once=not realtime, reid=reid)
    worker.warm()

    started = time.time()
    published = worker.run(seconds=seconds)
    rows = _read(client, stream, last_id)
    finished = time.time()

    latency = None
    if worker.last_frame_wall:
        latency = finished - worker.last_frame_wall - (CLOSE_AFTER_S if realtime else 0.0)

    report = {
        "source": str(source), "redis": kind, "plate_injected": plate,
        "published": published, "rows": len(rows), "wall_seconds": round(finished - started, 2),
        "latency_seconds": None if latency is None else round(max(latency, 0.0), 2),
        "budget_seconds": budget, "reads": [], "row": rows[-1] if rows else None,
    }

    assert rows, (f"nothing on the `{stream}` stream: {published} sightings published, "
                  f"source={source}")
    for row in rows:
        validate(row)                                # [C1] shape, on every row, not just one
    report["reads"] = sorted({r["plate_text"] for r in rows if r["plate_text"]})

    if require_plate and plate:
        from common.plate import normalise
        wanted = normalise(plate)
        assert wanted in report["reads"], (
            f"injected {wanted} but the stream carries {report['reads'] or 'no read'} - "
            f"bands: {[r['plate_band'] for r in rows]}")
    if latency is not None and budget:
        assert latency <= budget, f"row landed {latency:.2f}s after the pass, budget {budget}s"
    return report


def _last_id(client, stream):
    try:
        entries = client.xrevrange(stream, count=1)
        return entries[0][0] if entries else "0-0"
    except Exception:
        return "0-0"


def _read(client, stream, after):
    """Rows added after `after`, decoded from the single `data` field ([C2])."""
    out = []
    start = after if isinstance(after, (bytes, str)) else "0-0"
    for _id, fields in client.xrange(stream, min=f"({_text(start)}", max="+"):
        raw = fields.get(b"data") or fields.get("data")
        out.append(json.loads(raw.decode() if isinstance(raw, bytes) else raw))
    return out


def _text(value):
    return value.decode() if isinstance(value, bytes) else str(value)


def main(argv=None):
    ap = argparse.ArgumentParser(description="[I8] worker selftest / replay harness")
    ap.add_argument("--assert-xadd", action="store_true",
                    help="[I6] verify: replay a clip and assert a valid [C1] row on "
                         "`sightings-selftest` (off the real stream - see --stream)")
    ap.add_argument("--clip", help="clip to replay (generated with a known plate if absent)")
    ap.add_argument("--plate", help="the plate the clip carries, when you brought your own clip")
    ap.add_argument("--source", help="stream URL instead of a clip - the RTSP replay path")
    ap.add_argument("--camera", default=CAMERA_ID)
    ap.add_argument("--budget", type=float, default=BUDGET_S)
    ap.add_argument("--seconds", type=float, help="stop after N seconds (live sources)")
    ap.add_argument("--stream", default=SELFTEST_STREAM,
                    help="stream to publish to; `sightings` (with a real --camera) for a live demo")
    ap.add_argument("--no-plate-check", action="store_true",
                    help="assert the row only, not the text - for clips with no known plate")
    ap.add_argument("--reid", action="store_true")
    ap.add_argument("--make-clip", metavar="PATH", help="just write a clip and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s %(message)s")

    if args.make_clip:
        path, plate = make_clip(args.make_clip, plate=args.plate)
        print(f"{path}  plate={plate}")
        return 0

    try:
        report = run(clip=args.clip, plate=args.plate, source=args.source,
                     camera_id=args.camera, budget=args.budget, stream=args.stream,
                     require_plate=not args.no_plate_check and not args.source,
                     reid=args.reid, seconds=args.seconds)
    except AssertionError as exc:
        print(f"SELFTEST FAILED: {exc}")
        return 1

    print(f"\nsource      {report['source']}")
    print(f"redis       {report['redis']}")
    print(f"injected    {report['plate_injected']}")
    print(f"read back   {', '.join(report['reads']) or '(none - vote refused)'}")
    print(f"rows        {report['rows']} on `{args.stream}`, {report['published']} published")
    print(f"latency     {report['latency_seconds']}s "
          f"(budget {report['budget_seconds']}s, wall {report['wall_seconds']}s)")
    row = report["row"]
    print(f"row         {json.dumps({k: row[k] for k in FIELDS if k != 'reid_vec'})}")
    print("\nSELFTEST OK")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("YOLO_VERBOSE", "0")
    raise SystemExit(main())
