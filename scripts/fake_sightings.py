#!/usr/bin/env python3
"""Publish synthetic [C1] sightings onto the Redis `sightings` stream.

    python scripts/fake_sightings.py --rate 50 --duration 300
    python scripts/fake_sightings.py --rate 5 --duration 60 --print   # look before you persist

This exists so lane D can be finished before lane I's worker produces a single frame. Every
consumer downstream of the stream - persister, matcher, WebSocket fanout, the route API -
can be built and load-tested against it.

Two kinds of traffic come out of it:

  * background noise: random plates on random cameras, which is what the persister's batching
    and the matcher's miss path get exercised by;
  * one scripted vehicle that crosses five cameras in a fixed order with realistic travel gaps.
    That is the route test case D6 is graded on, and it is why the generator is written first.

Timestamps are the frame's, not now(): pts_first leads the wall clock by the same offset a
real feed's PTS does, so nothing downstream can quietly start trusting arrival order.
"""

import argparse
import json
import os
import random
import secrets
import string
import sys
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
STREAM = "sightings"
DEFAULT_REDIS = "redis://localhost:6379/0"

# The five cameras the scripted vehicle crosses, in order, with the seconds it takes to get
# from the previous one. Ids are placeholders until G1 publishes data/cameras.seed.json; the
# route only needs them to be stable and in order.
ROUTE = [("GJ-AHD-0001", 0), ("GJ-AHD-0002", 47), ("GJ-AHD-0005", 63),
         ("GJ-AHD-0009", 52), ("GJ-AHD-0012", 71)]
ROUTE_PLATE = "GJ01AB1234"

CAMERAS = [f"GJ-AHD-{i:04d}" for i in range(1, 31)]
CLASSES = ["two_wheeler", "three_wheeler", "car", "lcv", "bus", "truck", "tractor"]
COLOURS = ["white", "silver", "black", "blue", "red", "grey", "yellow"]
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# canon() belongs to lane I ([C7], ticket I5). common/plate_compat.py is the single place that
# prefers the real implementation and falls back until it lands - see the note in that file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.plate_compat import canon  # noqa: E402


def ulid(when):
    """ULID: 48-bit millisecond timestamp then 80 random bits, Crockford base32.

    [C1] wants sighting ids that sort by time. A uuid4 does not, and the persister's batched
    inserts would then scatter across hypertable chunks instead of landing in one.
    """
    value = (int(when.timestamp() * 1000) << 80) | secrets.randbits(80)
    return "".join(CROCKFORD[(value >> shift) & 31] for shift in range(125, -5, -5))


def plate(rng):
    return (f"GJ{rng.randint(1, 38):02d}"
            + "".join(rng.choice(string.ascii_uppercase) for _ in range(2))
            + f"{rng.randint(0, 9999):04d}")


def sighting(rng, camera_id, pts_first, plate_text):
    """One [C1] record. plate_text None models a failed vote, which is correct behaviour."""
    dwell = rng.uniform(1.5, 4.0)
    band = "NONE" if plate_text is None else rng.choices(
        ["CONFIRMED", "PROBABLE", "POSSIBLE"], weights=[70, 20, 10])[0]
    return {
        "sighting_id": ulid(pts_first),
        "camera_id": camera_id,
        "track_id": rng.randint(1, 99999),
        "pts_first": pts_first.isoformat(),
        "pts_last": (pts_first + timedelta(seconds=dwell)).isoformat(),
        "ts_source": "rtsp_pts",
        "plate_text": plate_text,
        "plate_norm": plate_text,
        "plate_canon": canon(plate_text) if plate_text else None,
        "plate_conf": round(rng.uniform(0.62, 0.98), 2) if plate_text else 0.0,
        "plate_band": band,
        "vehicle_class": rng.choice(CLASSES),
        "colour": rng.choice(COLOURS),
        "bbox": [rng.randint(0, 900), rng.randint(0, 500), 0, 0],
        "reid_vec": None,
        "crop_uri": None,
    }


def finish_bbox(row, rng):
    x, y = row["bbox"][0], row["bbox"][1]
    row["bbox"] = [x, y, x + rng.randint(60, 320), y + rng.randint(40, 220)]
    day = row["pts_first"][:10].replace("-", "/")
    row["crop_uri"] = f"s3://crops/{row['camera_id']}/{day}/{row['sighting_id']}.jpg"
    return row


def route_schedule(start, gap_scale=1.0):
    """The scripted vehicle's five hops, as (camera_id, pts) in order.

    gap_scale shrinks the travel gaps so a short run still sees the whole route: at 1.0 the
    vehicle takes 233 s to cross five cameras, which is longer than most test runs.
    """
    at, hops = start, []
    for camera_id, gap in ROUTE:
        at += timedelta(seconds=gap * gap_scale)
        hops.append((camera_id, at))
    return hops


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rate", type=float, default=50.0, help="background rows per second")
    ap.add_argument("--duration", type=float, default=300.0, help="seconds to run")
    ap.add_argument("--redis", default=os.environ.get("REDIS_URL", DEFAULT_REDIS))
    ap.add_argument("--stream", default=STREAM)
    ap.add_argument("--seed", type=int, default=None, help="fix the RNG for a repeatable run")
    ap.add_argument("--route", "--route-plate", dest="route_plate", default=ROUTE_PLATE,
                    help="the plate that crosses all five cameras in order")
    ap.add_argument("--no-route", action="store_true", help="background noise only")
    ap.add_argument("--route-gap-scale", type=float, default=1.0,
                    help="compress the travel gaps, so a short run still crosses all five")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print rows to stdout instead of publishing")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    start = datetime.now(IST)
    hops = [] if args.no_route else route_schedule(start, args.route_gap_scale)
    if hops:
        # stderr, so --print stays a clean stream of JSON rows a pipe can read
        print(f"scripted route: {args.route_plate} across "
              + " -> ".join(c for c, _ in hops)
              + f" over {(hops[-1][1] - hops[0][1]).total_seconds():.0f}s", file=sys.stderr)

    client = None
    if not args.show:
        import redis  # late import so --print needs no server and no driver
        client = redis.Redis.from_url(args.redis)
        client.ping()

    published, deadline, next_at = 0, start + timedelta(seconds=args.duration), time.monotonic()
    while datetime.now(IST) < deadline:
        now, rows = datetime.now(IST), []
        while hops and hops[0][1] <= now:           # a hop is due: it goes out this tick
            camera_id, pts = hops.pop(0)
            rows.append(finish_bbox(sighting(rng, camera_id, pts, args.route_plate), rng))
        if not rows:
            rows.append(finish_bbox(sighting(rng, rng.choice(CAMERAS), now,
                                             None if rng.random() < 0.08 else plate(rng)), rng))
        for row in rows:
            if client:
                client.xadd(args.stream, {"data": json.dumps(row)})
            else:
                print(json.dumps(row))
            published += 1
        next_at += 1.0 / args.rate
        time.sleep(max(0.0, next_at - time.monotonic()))

    where = "stdout" if args.show else f"{args.stream} on {args.redis}"
    print(f"published {published} sighting(s) to {where} over {args.duration:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
