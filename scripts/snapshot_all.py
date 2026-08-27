"""Grab one frame from every reachable camera and build a contact sheet.

Purpose is survey, not decoration: before writing a single line of ANPR we need
to know what the grid actually looks like -- day or night, plate size in pixels,
glare, camera angle, and whether the burned-in timestamp overlay is readable.
Those facts decide the detector input resolution and whether we need a
region-of-interest crop per camera.

Requests are sequential with a pause. The grid gives every client its own copy
of each stream, and their guide asks integrators to pace their load.

Usage:
    python scripts/snapshot_all.py
    python scripts/snapshot_all.py --gateway http://127.0.0.1:8080 --delay 2
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "snapshots"


def grab(gateway: str, cam_id: str, dest: Path, timeout: int) -> bool:
    url = f"{gateway}/stream/{cam_id}/index.m3u8"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", url, "-frames:v", "1", "-q:v", "3", "-y", str(dest),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"  cam {cam_id:>2}  timeout")
        return False
    if dest.exists() and dest.stat().st_size > 5000:
        print(f"  cam {cam_id:>2}  ok  ({dest.stat().st_size // 1024} KB)")
        return True
    err = (proc.stderr or "").strip().splitlines()
    print(f"  cam {cam_id:>2}  failed: {err[-1][:110] if err else 'no frame'}")
    return False


def contact_sheet(paths: list[tuple[str, Path]], out: Path, cols: int = 4,
                  cell_w: int = 480) -> None:
    cell_h = int(cell_w * 9 / 16)
    rows = (len(paths) + cols - 1) // cols
    sheet = np.full((rows * cell_h, cols * cell_w, 3), 18, dtype=np.uint8)

    for idx, (cam_id, path) in enumerate(paths):
        img = cv2.imread(str(path))
        if img is None:
            continue
        h, w = img.shape[:2]
        scale = min(cell_w / w, cell_h / h)
        resized = cv2.resize(img, (int(w * scale), int(h * scale)))
        r, c = divmod(idx, cols)
        y0 = r * cell_h + (cell_h - resized.shape[0]) // 2
        x0 = c * cell_w + (cell_w - resized.shape[1]) // 2
        sheet[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized

        label = f"CAM {cam_id}"
        cv2.rectangle(sheet, (c * cell_w, r * cell_h),
                      (c * cell_w + 86, r * cell_h + 24), (0, 0, 0), -1)
        cv2.putText(sheet, label, (c * cell_w + 7, r * cell_h + 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 140, 255), 1, cv2.LINE_AA)
        cv2.rectangle(sheet, (c * cell_w, r * cell_h),
                      (c * cell_w + cell_w - 1, r * cell_h + cell_h - 1),
                      (45, 60, 80), 1)

    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"\n  contact sheet -> {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:8080")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--timeout", type=int, default=75)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cameras = requests.get(f"{args.gateway}/api/cameras", timeout=30).json()["cameras"]
    reachable = [c for c in cameras if c["reachable"]]
    print(f"grabbing a frame from {len(reachable)} reachable cameras\n")

    got: list[tuple[str, Path]] = []
    for cam in reachable:
        dest = OUT_DIR / f"cam{cam['id']}.jpg"
        if grab(args.gateway, cam["id"], dest, args.timeout):
            got.append((cam["id"], dest))
        time.sleep(args.delay)

    print(f"\n  {len(got)}/{len(reachable)} frames captured")
    if got:
        got.sort(key=lambda p: int(p[0]) if p[0].isdigit() else 0)
        contact_sheet(got, OUT_DIR / "grid_contact_sheet.jpg")

    (OUT_DIR / "captured.json").write_text(
        json.dumps({"captured": [c for c, _ in got],
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
