"""What each grid camera actually delivers, and whether a plate on it can be read.

    python scripts/grid_survey.py --probe                 # codec, resolution, fps per camera
    python scripts/grid_survey.py --frames --cameras cam17,cam04
    python scripts/grid_survey.py --report                # the feasibility table

This exists because every ANPR number in the deck has to come from a measurement. The survey
answers three questions per camera, in this order:

    1. what does the stream carry            ffprobe: codec, resolution, frame rate
    2. how big is a vehicle in it            YOLO on sampled frames: box widths
    3. can its plate be read at all          services.worker.preprocess.feasibility()

Step 3 is the one that matters. A camera whose median vehicle box is 55 px wide puts a two
pixel glyph in front of the recogniser, and no preprocessing recovers a stroke that was never
sampled. The survey says so per camera rather than letting the pipeline guess and the deck
quote the guess.

Access, per the integrator's guide: RTSP and WHEP are served on the public IP directly, HLS
through the CDN behind the access key. Set GRID_KEY for the HLS path; RTSP needs no key but
is rate limited - open a few cameras at a time and close them, which is what --workers is for.
"""

import argparse
import json
import os
import statistics as st
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CDN = os.environ.get("GRID_CDN", "https://cctv.corp8.cloud")
PUBLIC_IP = os.environ.get("GRID_IP", "103.250.160.189")
RTSP = f"rtsp://{PUBLIC_IP}:8554/stream/{{id}}"
HLS = CDN + "/{id}/index.m3u8"
CATALOGUE = CDN + "/cameras.json"

VEHICLE_LABELS = {"car", "bus", "truck", "motorcycle"}


def catalogue(session=None):
    """The camera list, from the grid rather than hard-coded - the guide says it can change."""
    import requests

    sess = session or requests.Session()
    key = os.environ.get("GRID_KEY", "").strip()
    if key:
        sess.post(f"{CDN}/auth/login", data={"password": key}, timeout=15)
    r = sess.get(CATALOGUE, timeout=20)
    r.raise_for_status()
    return r.json()


def probe_one(camera_id, timeout=45):
    """ffprobe over RTSP/TCP. UDP across NAT gives corrupt frames that look like model bugs."""
    cmd = ["ffprobe", "-v", "error", "-rtsp_transport", "tcp",
           "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt",
           "-of", "json", RTSP.format(id=camera_id)]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        stream = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
        if not stream:
            return {"id": camera_id, "error": out.stderr.strip().splitlines()[-1][:90]
                    if out.stderr.strip() else "no video stream"}
        return {"id": camera_id, "codec": stream.get("codec_name"),
                "width": stream.get("width"), "height": stream.get("height"),
                "fps": stream.get("r_frame_rate"), "pix_fmt": stream.get("pix_fmt")}
    except subprocess.TimeoutExpired:
        return {"id": camera_id, "error": "timed out"}
    except (ValueError, OSError) as exc:
        return {"id": camera_id, "error": f"{type(exc).__name__}"}


def grab_frames(camera_id, out_dir, count=8, fps=1, timeout=90, use_hls=False):
    """Sample frames to disk. One second of video takes one second: this is a live capture."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    url = HLS.format(id=camera_id) if use_hls else RTSP.format(id=camera_id)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if not use_hls:
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url, "-vf", f"fps={fps}", "-frames:v", str(count), "-q:v", "2",
            str(out_dir / f"{camera_id}_%02d.jpg")]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
    except subprocess.TimeoutExpired:
        pass
    return sorted(out_dir.glob(f"{camera_id}_*.jpg"))


def measure_frames(paths, weights=None):
    """Vehicle box widths and frame quality over sampled frames of one camera."""
    import cv2
    from ultralytics import YOLO

    from services.worker.preprocess import measure

    model = YOLO(weights or os.environ.get("PRAHARI_VEHICLE_WEIGHTS",
                                           str(ROOT / "models" / "yolov8s.pt")))
    names = model.names
    widths, quality = [], []
    for path in paths:
        frame = cv2.imread(str(path))
        if frame is None:
            continue
        quality.append(measure(frame))
        for box in model.predict(frame, conf=0.25, verbose=False)[0].boxes:
            if names[int(box.cls)] not in VEHICLE_LABELS:
                continue
            x1, _, x2, _ = [float(v) for v in box.xyxy[0]]
            widths.append(x2 - x1)
    return widths, quality


def verdict(widths):
    from services.worker.preprocess import feasibility, min_vehicle_width_for_ocr

    if not widths:
        return None, "no vehicle in the sample - re-sample at a busier minute"
    p90 = sorted(widths)[int(0.9 * (len(widths) - 1))]
    f = feasibility(p90)
    need = min_vehicle_width_for_ocr()
    return f, (f"{f.verdict}: p90 vehicle {p90:.0f}px -> glyph {f.glyph_px:.1f}px "
               f"(needs {need:.0f}px of vehicle). {f.reason}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true", help="codec/resolution/fps per camera")
    ap.add_argument("--frames", action="store_true", help="sample frames to --out")
    ap.add_argument("--report", action="store_true", help="feasibility table from sampled frames")
    ap.add_argument("--cameras", default="", help="comma-separated ids; default all")
    ap.add_argument("--out", default=str(ROOT / "fixtures" / "grid"), help="frame directory")
    ap.add_argument("--count", type=int, default=8, help="frames per camera")
    ap.add_argument("--workers", type=int, default=4,
                    help="cameras opened at once - the grid is rate limited, keep it small")
    ap.add_argument("--hls", action="store_true", help="capture over the CDN instead of RTSP")
    args = ap.parse_args()

    ids = [c.strip() for c in args.cameras.split(",") if c.strip()]
    if not ids:
        ids = [c["id"] for c in catalogue()]

    if args.probe:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(probe_one, ids))
        for r in rows:
            if "error" in r:
                print(f"{r['id']:7} UNREACHABLE  {r['error']}")
            else:
                print(f"{r['id']:7} {r['codec']:5} {r['width']}x{r['height']:<5} {r['fps']:>6}")
        ok = [r for r in rows if "error" not in r]
        print("\nresolutions:", dict(Counter(f"{r['width']}x{r['height']}" for r in ok)))
        print("codecs:", dict(Counter(r["codec"] for r in ok)))
        print("frame rates:", dict(Counter(r["fps"] for r in ok)))

    if args.frames:
        for camera_id in ids:
            paths = grab_frames(camera_id, args.out, count=args.count, use_hls=args.hls)
            print(f"{camera_id:7} {len(paths)} frame(s) -> {args.out}")

    if args.report:
        print(f"{'cam':7} {'sharp':>7} {'bright':>7} {'sigma':>6} {'veh':>4} {'medW':>6} "
              f"{'glyph':>6}  verdict")
        for camera_id in ids:
            paths = sorted(Path(args.out).glob(f"{camera_id}_*.jpg"))
            if not paths:
                print(f"{camera_id:7} -- no sampled frames; run --frames first")
                continue
            widths, quality = measure_frames(paths)
            f, note = verdict(widths)
            sharp = st.mean([q.sharpness for q in quality]) if quality else 0
            bright = st.mean([q.brightness for q in quality]) if quality else 0
            sigma = st.mean([q.sigma for q in quality]) if quality else 0
            med = st.median(widths) if widths else 0
            print(f"{camera_id:7} {sharp:7.0f} {bright:7.0f} {sigma:6.1f} {len(widths):4d} "
                  f"{med:6.0f} {(f.glyph_px if f else 0):6.1f}  {note}")


if __name__ == "__main__":
    main()
