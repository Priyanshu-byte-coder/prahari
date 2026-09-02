"""[G2] Gateway selftest.

    python -m services.gateway.selftest --probe-all

Prints the transport table with the reason per camera, which is the line the
demo is built on: "this camera came in on HLS because RTSP was blocked."

    --publish     also write `camera:transport:<id>` to Redis (the G->I seam)
    --only 1,2,3  probe a subset
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.gateway.probe import publish, resolve_transport  # noqa: E402

SEED = ROOT / "data" / "cameras.seed.json"


def load_cameras() -> list[dict]:
    if not SEED.exists():
        raise SystemExit(f"{SEED.relative_to(ROOT)} missing -- run scripts/probe_grid.py first (G1)")
    return json.loads(SEED.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-all", action="store_true")
    ap.add_argument("--publish", action="store_true", help="write camera:transport:<id> to Redis")
    ap.add_argument("--only", default=None, help="comma-separated camera ids")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if not args.probe_all:
        ap.print_help()
        return 0

    cameras = load_cameras()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        cameras = [c for c in cameras if str(c.get("camera_id")) in wanted]

    redis_client = None
    if args.publish:
        import redis  # imported only when asked for

        redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(resolve_transport, cameras))
    results.sort(key=lambda r: int(r.camera_id) if r.camera_id.isdigit() else 0)

    print(f"{'cam':>4}  {'transport':<10} {'driver':<10} reason")
    print("-" * 76)
    for r in results:
        print(f"{r.camera_id:>4}  {(r.transport or '-'):<10} {(r.driver or '-'):<10} {r.reason}")
        if redis_client is not None and r.url:
            publish(r, redis_client)

    by_transport: dict[str, int] = {}
    for r in results:
        by_transport[r.transport or "none"] = by_transport.get(r.transport or "none", 0) + 1
    resolved = sum(1 for r in results if r.transport)

    print("-" * 76)
    print(f"resolved  : {resolved}/{len(results)}")
    print(f"transport : {by_transport}")
    if redis_client is not None:
        print(f"published : {resolved} keys -> camera:transport:<id>")
    else:
        print("published : nothing (pass --publish to write the G->I seam)")
    return 0 if resolved else 1


if __name__ == "__main__":
    sys.exit(main())
