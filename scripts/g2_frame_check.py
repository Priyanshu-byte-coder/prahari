"""[G2] Exercise the real frame path against a live grid camera.

The probe layer is proven by tests/test_g_probe.py; this is the part that
needs actual pixels: does MediaMTXSource open a cookie-gated HLS playlist,
decode frames, carry a usable pts, and label ts_source honestly?

    python scripts/g2_frame_check.py --camera 1 --frames 15
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

from services.gateway.probe import resolve_transport  # noqa: E402
from services.gateway.sources.mediamtx import MediaMTXSource  # noqa: E402
from services.gateway.sources.rtsp import RTSPSource  # noqa: E402

SEED = ROOT / "data" / "cameras.seed.json"


async def run(camera_id: str, want_frames: int, timeout_s: float) -> int:
    try:
        cameras = json.loads(SEED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[-] cannot read seed: {exc}")
        return 2
    cam = next((c for c in cameras if str(c.get("camera_id")) == camera_id), None)
    if cam is None:
        print(f"camera {camera_id} not in the seed")
        return 2

    result = resolve_transport(cam)
    print(f"[*] cam {camera_id}: transport={result.transport} driver={result.driver}", flush=True)
    print(f"[*] reason: {result.reason}", flush=True)
    if not result.url:
        print("[-] no transport resolved; nothing to decode")
        return 1

    source = (
        RTSPSource(camera_id, result.url)
        if result.transport == "rtsp"
        else MediaMTXSource(camera_id, result.url)
    )

    started = time.time()
    state = {"seen": 0, "shape": None, "pts": [], "ts_source": None}

    async def pull() -> None:
        async for frame in source.frames():
            state["seen"] += 1
            if state["shape"] is None:
                state["shape"] = getattr(frame.image, "shape", None)
                state["ts_source"] = frame.ts_source
                print(f"[+] first frame after {time.time() - started:.1f}s "
                      f"shape={state['shape']} ts_source={frame.ts_source.value}", flush=True)
            if frame.pts is not None:
                state["pts"].append(frame.pts)
            if state["seen"] >= want_frames:
                return

    # The whole pull is bounded, not just the per-frame loop. `frames()`
    # reconnects forever by design, so a camera that never yields a first
    # frame would otherwise hang here indefinitely -- which is exactly what
    # happened the first time this was run.
    try:
        await asyncio.wait_for(pull(), timeout=timeout_s)
    except asyncio.TimeoutError:
        print(f"[-] timed out after {timeout_s:.0f}s with {state['seen']} frames", flush=True)
    except Exception as exc:
        print(f"[-] frame loop raised {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        await source.close()

    seen = state["seen"]
    pts_values = state["pts"]
    ts_source = state["ts_source"]

    elapsed = time.time() - started
    print(f"[+] {seen} frames in {elapsed:.1f}s ({seen / elapsed:.1f} fps decoded)")
    print(f"[+] health after run: {source.health().value}")

    if seen == 0:
        print("[-] decoded nothing")
        return 1
    if pts_values:
        span = pts_values[-1] - pts_values[0]
        monotonic = all(b >= a for a, b in zip(pts_values, pts_values[1:]))
        print(f"[+] pts: {len(pts_values)} values, span {span:.2f}s, monotonic={monotonic}")
        if not monotonic:
            print("[!] pts went backwards -- the grid loops its feeds, expect discontinuities")
    else:
        print("[!] no pts on any frame -- timestamps would fall back to server_receive")
    print(f"[+] ts_source recorded as {ts_source.value if ts_source else '?'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="1")
    ap.add_argument("--frames", type=int, default=15)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    return asyncio.run(run(args.camera, args.frames, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
