"""Run vehicle workers across many cameras at once, and keep them alive.

Until now a worker was one process per camera, started by hand. Cross-camera
route reconstruction needs several cameras producing detections simultaneously,
and the finale demo needs that to survive a camera dropping out mid-run without
anybody touching a terminal.

Process-per-camera rather than threads, deliberately:

- Ultralytics' tracker state lives on the model instance, so a shared model
  cannot track two cameras independently. Separate processes keep each
  camera's ByteTrack state genuinely isolated.
- A hard failure in one camera's decoder cannot take the other cameras with it.
- GPU memory is the real limit, not CPU. Each process loads its own weights,
  so `--max-cameras` is a VRAM budget knob. Measure with `--load-test` before
  assuming a number.

Load is paced: cameras start staggered, and a camera that keeps dying backs off
rather than being restarted in a tight loop. The grid gives every client its own
copy of each stream, and the organisers' integration guide asks integrators not
to hammer it.

Usage:
    python -m services.worker.supervisor --cameras 4,13,16
    python -m services.worker.supervisor --auto --max-cameras 4
    python -m services.worker.supervisor --auto --max-cameras 6 --load-test 180
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prahari.supervisor")

ROOT = Path(__file__).resolve().parents[2]
DETECTIONS = ROOT / "data" / "detections"
HEALTH_FILE = ROOT / "data" / "worker_health.json"

STAGGER_SECONDS = 4.0        # gap between starting consecutive cameras
RESTART_BACKOFF_MIN = 5.0
RESTART_BACKOFF_MAX = 120.0
HEALTH_INTERVAL = 5.0


@dataclass
class Worker:
    camera_id: str
    proc: subprocess.Popen | None = None
    started_at: float = 0.0
    restarts: int = 0
    backoff: float = RESTART_BACKOFF_MIN
    next_start_at: float = 0.0
    last_exit_code: int | None = None
    detections_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.detections_path = DETECTIONS / f"cam_{self.camera_id}.jsonl"

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def rows(self) -> int:
        """Detection rows written so far -- the only real evidence of progress."""
        if not self.detections_path.exists():
            return 0
        try:
            with self.detections_path.open("rb") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0


def discover_cameras(gateway: str, limit: int) -> list[str]:
    """Ask the registry which cameras are actually reachable."""
    resp = requests.get(f"{gateway}/api/cameras", timeout=30)
    resp.raise_for_status()
    cameras = resp.json()["cameras"]
    reachable = [c["id"] for c in cameras if c.get("reachable")]
    logger.info("registry reports %d reachable of %d cameras", len(reachable), len(cameras))
    return reachable[:limit]


def spawn(camera_id: str, gateway: str, weights: str, device: str | None,
          fps: float | None = None) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "services.worker.run_worker",
        "--camera", camera_id,
        "--gateway", gateway,
        "--weights", weights,
    ]
    if device:
        cmd += ["--device", device]
    if fps is not None:
        cmd += ["--fps", str(fps)]

    # Workers are chatty on stdout; keep the supervisor's own log readable by
    # sending each camera's output to its own file.
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"worker_cam{camera_id}.log"
    handle = log_path.open("a", encoding="utf-8")

    creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(
        cmd, cwd=str(ROOT), stdout=handle, stderr=subprocess.STDOUT,
        creationflags=creation,
    )


def write_health(workers: dict[str, Worker], started_at: float) -> None:
    """Health snapshot for the NOC dashboard and the API to read."""
    now = time.time()
    payload = {
        "supervisor_started_at": started_at,
        "uptime_seconds": round(now - started_at, 1),
        "updated_at": now,
        "workers": [
            {
                "camera_id": w.camera_id,
                "alive": w.alive,
                "pid": w.proc.pid if w.proc else None,
                "uptime_seconds": round(now - w.started_at, 1) if w.alive else 0.0,
                "restarts": w.restarts,
                "last_exit_code": w.last_exit_code,
                "detection_rows": w.rows(),
            }
            for w in workers.values()
        ],
    }
    payload["alive_count"] = sum(1 for w in payload["workers"] if w["alive"])
    payload["total_detection_rows"] = sum(w["detection_rows"] for w in payload["workers"])
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(HEALTH_FILE)


def stop_all(workers: dict[str, Worker]) -> None:
    logger.info("stopping %d workers", len(workers))
    for w in workers.values():
        if w.alive and w.proc is not None:
            try:
                w.proc.terminate()
            except OSError:
                pass
    deadline = time.time() + 12
    for w in workers.values():
        if w.proc is None:
            continue
        remaining = max(0.0, deadline - time.time())
        try:
            w.proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            logger.warning("cam %s did not exit, killing", w.camera_id)
            try:
                w.proc.kill()
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cameras", help="comma-separated camera ids")
    ap.add_argument("--auto", action="store_true", help="take reachable cameras from the registry")
    ap.add_argument("--max-cameras", type=int, default=4,
                    help="VRAM budget: each worker loads its own weights")
    ap.add_argument("--gateway", default="http://127.0.0.1:8080")
    ap.add_argument("--weights", default="yolov8n.pt",
                    help="yolov8n for many cameras, yolov8s for accuracy on few")
    ap.add_argument("--device", default=None, help="cuda / cpu; default lets ultralytics choose")
    ap.add_argument("--fps", type=float, default=None,
                    help="inference rate per camera; 0 means every decoded frame")
    ap.add_argument("--load-test", type=int, default=0,
                    help="run for N seconds, then print throughput and exit")
    args = ap.parse_args()

    if args.cameras:
        camera_ids = [c.strip() for c in args.cameras.split(",") if c.strip()]
    elif args.auto:
        camera_ids = discover_cameras(args.gateway, args.max_cameras)
    else:
        ap.error("pass --cameras 4,13,16 or --auto")
        return 2

    if not camera_ids:
        logger.error("no cameras to run")
        return 1

    camera_ids = camera_ids[: args.max_cameras]
    logger.info("supervising %d cameras: %s", len(camera_ids), ", ".join(camera_ids))
    logger.info("weights=%s device=%s inference_fps=%s", args.weights,
                args.device or "auto", args.fps if args.fps is not None else "default")

    workers = {cid: Worker(camera_id=cid) for cid in camera_ids}
    started_at = time.time()
    rows_at_start = {cid: workers[cid].rows() for cid in camera_ids}
    stopping = False

    def handle_signal(_sig, _frm):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Staggered cold start so the gateway is not hit by N simultaneous joins.
    for i, cid in enumerate(camera_ids):
        w = workers[cid]
        w.proc = spawn(cid, args.gateway, args.weights, args.device, args.fps)
        w.started_at = time.time()
        logger.info("cam %s started (pid %d)", cid, w.proc.pid)
        if i < len(camera_ids) - 1:
            time.sleep(STAGGER_SECONDS)

    last_health = 0.0
    try:
        while not stopping:
            now = time.time()

            for w in workers.values():
                if w.alive:
                    # A worker that has stayed up earns its backoff back.
                    if now - w.started_at > 120:
                        w.backoff = RESTART_BACKOFF_MIN
                    continue

                if w.proc is not None and w.last_exit_code is None:
                    w.last_exit_code = w.proc.poll()
                    logger.warning("cam %s exited with code %s", w.camera_id, w.last_exit_code)
                    w.next_start_at = now + w.backoff

                if now >= w.next_start_at:
                    w.restarts += 1
                    w.proc = spawn(w.camera_id, args.gateway, args.weights, args.device, args.fps)
                    w.started_at = now
                    w.last_exit_code = None
                    logger.info("cam %s restarted (pid %d, restart #%d, next backoff %.0fs)",
                                w.camera_id, w.proc.pid, w.restarts, w.backoff)
                    w.backoff = min(w.backoff * 2, RESTART_BACKOFF_MAX)

            if now - last_health >= HEALTH_INTERVAL:
                write_health(workers, started_at)
                last_health = now
                alive = sum(1 for w in workers.values() if w.alive)
                total = sum(w.rows() for w in workers.values())
                logger.info("health: %d/%d alive, %d detection rows total",
                            alive, len(workers), total)

            if args.load_test and (now - started_at) >= args.load_test:
                break

            time.sleep(1.0)
    finally:
        stop_all(workers)
        write_health(workers, started_at)

    if args.load_test:
        elapsed = time.time() - started_at
        print("\n" + "=" * 64)
        print(f"LOAD TEST — {len(camera_ids)} cameras, {elapsed:.0f}s, "
              f"weights={args.weights}, fps={args.fps if args.fps is not None else 'default'}")
        print("=" * 64)
        grand = 0
        for cid in camera_ids:
            w = workers[cid]
            produced = w.rows() - rows_at_start[cid]
            grand += produced
            print(f"  cam {cid:>3}  {produced:>7} detection rows  "
                  f"{produced / elapsed:>7.1f} rows/s  restarts={w.restarts}")
        print(f"  {'total':>7}  {grand:>7} detection rows  {grand / elapsed:>7.1f} rows/s")
        print("\nRecord this number in CONTEXT.md — judges ask how many cameras a node holds.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
