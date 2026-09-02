"""[G3] Drive the health monitor off a real camera, no Redis required.

Decodes a live grid camera, feeds the observed fps into HealthMonitor the
way the worker would via `camera:fps:<id>`, then stops feeding it and shows
the LIVE -> DEGRADED -> DOWN transition happening on the real clock.

    python scripts/g3_health_check.py --camera 1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.gateway.health import HealthMonitor  # noqa: E402
from services.gateway.probe import resolve_transport  # noqa: E402
from services.gateway.sources.mediamtx import MediaMTXSource  # noqa: E402
from services.gateway.sources.rtsp import RTSPSource  # noqa: E402

SEED = ROOT / "data" / "cameras.seed.json"


async def measure_fps(source, seconds: float, open_grace: float = 40.0) -> float:
    """Frames per second *once flowing* -- the connect cost is not a frame rate.

    Opening an HLS stream on this grid has taken anywhere from 1.6 s to 18 s,
    so a window that starts at connect time measures the handshake, not the
    stream, and reports ~0 fps for a perfectly healthy camera.

    The generator is closed before the container it reads from: cancelling the
    pull and tearing down the container underneath a live generator crashes
    PyAV rather than raising.
    """
    n = 0
    first_at: float | None = None
    last_at: float | None = None
    gen = source.frames()

    async def pull():
        nonlocal n, first_at, last_at
        async for _ in gen:
            now = time.time()
            if first_at is None:
                first_at = now
                print(f"    (first frame after {now - started:.1f}s)", flush=True)
            last_at = now
            n += 1
            if first_at is not None and now - first_at >= seconds:
                return

    started = time.time()
    try:
        await asyncio.wait_for(pull(), timeout=seconds + open_grace)
    except asyncio.TimeoutError:
        pass
    finally:
        await gen.aclose()      # generator first
        await source.close()    # then the container it was reading

    if first_at is None or last_at is None or n < 2:
        return 0.0
    span = last_at - first_at
    return (n - 1) / span if span > 0 else 0.0


async def run(camera_id: str, window: float) -> int:
    cameras = json.loads(SEED.read_text(encoding="utf-8"))
    cam = next((c for c in cameras if str(c.get("camera_id")) == camera_id), None)
    if cam is None:
        print(f"camera {camera_id} not in the seed")
        return 2

    result = resolve_transport(cam)
    if not result.url:
        print(f"[-] cam {camera_id} unreachable: {result.reason}")
        return 1
    print(f"[*] cam {camera_id} via {result.transport}", flush=True)

    monitor = HealthMonitor.from_seed([cam])
    monitor.cameras[camera_id].transport_in_use = result.transport

    source = (
        RTSPSource(camera_id, result.url)
        if result.transport == "rtsp"
        else MediaMTXSource(camera_id, result.url)
    )
    fps = await measure_fps(source, window)
    print(f"[+] measured {fps:.2f} fps over {window:.0f}s "
          f"(expected {monitor.cameras[camera_id].expected:.1f})", flush=True)

    t = time.time()
    monitor.observe_fps(camera_id, fps, now=t)
    for event in monitor.evaluate(now=t):
        print(f"    -> {event['health']}  fps={event['fps']:.2f} age={event['last_frame_age_s']}s")

    # Now stop feeding it: this is the "kill the stream" case.
    print("[*] stream stopped; advancing the clock", flush=True)
    for offset, label in ((4.0, "+4s"), (16.0, "+16s")):
        for event in monitor.evaluate(now=t + offset):
            print(f"    {label} -> {event['health']}  age={event['last_frame_age_s']}s")

    final = monitor.cameras[camera_id].state.value
    print(f"[+] final state {final}")
    return 0 if final == "DOWN" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="1")
    ap.add_argument("--window", type=float, default=10.0)
    args = ap.parse_args()
    return asyncio.run(run(args.camera, args.window))


if __name__ == "__main__":
    sys.exit(main())
