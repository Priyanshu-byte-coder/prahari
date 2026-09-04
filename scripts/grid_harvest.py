"""One-off: sign in to the live grid, capture every camera's HLS feed to a local
clip, run the worker pipeline over each clip, and print every plate tracked per
camera.

    GRID_EMAIL=... GRID_KEY=... python scripts/grid_harvest.py --seconds 90

Why it captures to a local file first: the gateway (probe.py / MediaMTXSource)
only knows the old Cloudflare cookieCheck gate, and handing ffmpeg's HLS demuxer
a cookie-gated, flaky playlist churns through AVERROR_EXIT / "invalid data"
reconnects. Pulling the segments over `requests` (cookie attached, retried,
AES-128 handled) into one MPEG-TS clip removes ffmpeg's networking and auth from
the path entirely; the worker then decodes a plain local file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import requests

import scripts.console_serve as console

GRID_BASE = "https://cctv.corp8.cloud"


# --- sign-in ------------------------------------------------------------------------------

def sign_in() -> tuple[str, str]:
    for attempt in range(1, 8):
        try:
            if console.grid_login():
                return console.GRID["cookie"], console.GRID_UA
        except Exception as exc:  # pragma: no cover
            console.GRID["detail"] = f"{type(exc).__name__}: {exc}"
        print(f"    sign-in attempt {attempt}: {console.GRID['state']} "
              f"- {console.GRID['detail']}; retrying", flush=True)
        time.sleep(min(4 * attempt, 20))
    raise SystemExit(f"grid sign-in failed: {console.GRID['state']} - {console.GRID['detail']}")


def _get(sess, url, ua, cookie, tries=5, **kw):
    last = None
    for i in range(1, tries + 1):
        try:
            r = sess.get(url, headers={"User-Agent": ua, "Cookie": cookie},
                         timeout=kw.pop("timeout", 25), **kw)
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            time.sleep(min(3 * i, 15))
    raise RuntimeError(f"GET {url} failed after {tries}: {last}")


def catalogue(sess, cookie, ua) -> list[dict]:
    return json.loads(_get(sess, f"{GRID_BASE}/cameras.json", ua, cookie).text)


# --- HLS capture -------------------------------------------------------------------------

def _parse_playlist(text: str, base_url: str):
    """Return (is_master, entries). entries for master: [(bandwidth, url)];
    for media: dict(target, seq, key, segments=[(url, seq)])."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if any(ln.startswith("#EXT-X-STREAM-INF") for ln in lines):
        variants = []
        for i, ln in enumerate(lines):
            if ln.startswith("#EXT-X-STREAM-INF"):
                bw = 0
                for part in ln.split(":", 1)[1].split(","):
                    if part.strip().startswith("BANDWIDTH="):
                        bw = int(part.split("=", 1)[1])
                if i + 1 < len(lines):
                    variants.append((bw, urllib.parse.urljoin(base_url, lines[i + 1])))
        return True, variants
    seq = 0
    target = 6.0
    key = None
    segs = []
    cur = seq
    for ln in lines:
        if ln.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            seq = int(ln.split(":", 1)[1]); cur = seq
        elif ln.startswith("#EXT-X-TARGETDURATION:"):
            target = float(ln.split(":", 1)[1])
        elif ln.startswith("#EXT-X-KEY:"):
            attrs = {}
            for part in ln.split(":", 1)[1].split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    attrs[k.strip()] = v.strip().strip('"')
            key = attrs
        elif not ln.startswith("#"):
            segs.append((urllib.parse.urljoin(base_url, ln), cur))
            cur += 1
    return False, {"target": target, "seq": seq, "key": key, "segments": segs}


def _decrypt(data: bytes, key_bytes: bytes, seq: int, iv_hex: str | None) -> bytes:
    from Crypto.Cipher import AES
    if iv_hex:
        iv = bytes.fromhex(iv_hex[2:] if iv_hex.lower().startswith("0x") else iv_hex)
    else:
        iv = seq.to_bytes(16, "big")
    return AES.new(key_bytes, AES.MODE_CBC, iv).decrypt(data)


FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def capture_hls(cid, cookie, ua, seconds, outdir) -> Path | None:
    """Capture `seconds` of the camera's HLS to a local MPEG-TS with the ffmpeg CLI.

    ffmpeg handles the cookie-gated playlist, AES-128, and mid-stream reconnects, and
    `-t` + a subprocess timeout give a hard wall-clock bound so one stalled feed can
    never wedge the run (which the PyAV interrupt-callback path did).
    """
    out = Path(outdir) / f"{cid}.ts"
    out.unlink(missing_ok=True)
    url = f"{GRID_BASE}/{cid}/index.m3u8"
    cmd = [
        FFMPEG, "-nostdin", "-loglevel", "error", "-y",
        "-headers", f"Cookie: {cookie}\r\nUser-Agent: {ua}\r\n",
        "-user_agent", ua,
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "8",
        "-rw_timeout", "15000000", "-fflags", "+genpts",
        "-i", url,
        "-map", "0:v:0",                     # grid clips carry a duplicate video stream
        "-t", str(int(seconds)), "-c", "copy", "-f", "mpegts", str(out),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 45)
    except subprocess.TimeoutExpired:
        print(f"  [{cid}] ffmpeg timed out (kept partial)", flush=True)
    else:
        if p.returncode != 0 and not out.exists():
            print(f"  [{cid}] ffmpeg failed: {(p.stderr or '').strip()[:200]}", flush=True)
            return None
    if not out.exists() or out.stat().st_size < 8192:
        out.unlink(missing_ok=True)
        print(f"  [{cid}] no usable feed", flush=True)
        return None
    print(f"  [{cid}] captured {out.stat().st_size // 1024} KiB", flush=True)
    return out


# --- pipeline ---------------------------------------------------------------------------

def run_pipeline(clips: dict[str, Path], publisher, backend):
    from services.worker.run import Worker
    per_cam: dict[str, list[dict]] = defaultdict(list)
    for cid, clip in clips.items():
        worker = Worker({cid: str(clip)}, backend=backend, publisher=publisher,
                        once=True, motion_gate=True)
        try:
            worker.run(seconds=600)
        except Exception as exc:
            print(f"  [{cid}] pipeline error: {type(exc).__name__}: {exc}", flush=True)
    return per_cam


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90.0, help="capture window per camera")
    ap.add_argument("--workers", type=int, default=6, help="cameras captured in parallel")
    ap.add_argument("--fps", type=float, default=8.0,
                    help="frames/sec sampled for OCR (higher = more frames per track for MFSR; "
                         "0 = native)")
    ap.add_argument("--max-crops", type=int, default=24,
                    help="max crops kept per track for the reconstruction ensemble")
    ap.add_argument("--reuse", action="store_true", help="skip capture, use existing clips")
    ap.add_argument("--only", help="comma-separated camera ids")
    ap.add_argument("--clipdir", default=str(ROOT / "runs" / "grid_clips"))
    ap.add_argument("--out", default=str(ROOT / "runs" / "grid_plates.json"))
    args = ap.parse_args()

    Path(args.clipdir).mkdir(parents=True, exist_ok=True)
    cat_cache = Path(args.clipdir) / "cameras.json"
    sess = requests.Session()
    if args.reuse and cat_cache.exists():
        cookie, ua = "", ""
        cams = json.loads(cat_cache.read_text())
        print(f"[+] reuse: {len(cams)} cameras from cache", flush=True)
    else:
        cookie, ua = sign_in()
        print(f"[+] signed in; cookie {cookie[:32]}...", flush=True)
        cams = catalogue(sess, cookie, ua)
        cat_cache.write_text(json.dumps(cams))
    if args.only:
        want = set(args.only.split(","))
        cams = [c for c in cams if c["id"] in want]
    names = {c["id"]: c["name"] for c in cams}
    print(f"[+] {len(cams)} cameras; capturing {args.seconds:.0f}s each, "
          f"{args.workers} in parallel", flush=True)

    Path(args.clipdir).mkdir(parents=True, exist_ok=True)
    clips: dict[str, Path] = {}
    if args.reuse:
        for c in cams:
            p = Path(args.clipdir) / f"{c['id']}.ts"
            if p.exists() and p.stat().st_size > 8192:
                clips[c["id"]] = p
        print(f"[+] reusing {len(clips)} existing clips", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(capture_hls, c["id"], cookie, ua, args.seconds,
                              args.clipdir): c["id"] for c in cams}
            for fut in as_completed(futs):
                cid = futs[fut]
                try:
                    p = fut.result()
                    if p:
                        clips[cid] = p
                except Exception as exc:
                    print(f"  [{cid}] capture crashed: {exc}", flush=True)

    print(f"\n[+] captured {len(clips)}/{len(cams)} cameras; running detect + OCR", flush=True)

    import numpy as np
    from services.worker.backend import LocalBackend
    from services.worker.plate import read_all, readers
    from services.worker.sighting import sharpness
    from services.worker.vote import PlateVote
    from services.worker.preprocess import prepare_frame
    from services.worker.plate import detect_plate_boxes, propose
    from services.worker.mvcp import decode_track

    MAX_TRACK_CROPS = args.max_crops
    VEHICLE = {"car", "truck", "bus", "motorcycle", "motorbike", "van", "vehicle"}
    imgsz = int(os.getenv("PRAHARI_DETECT_IMGSZ", "960"))
    backend = LocalBackend(imgsz=imgsz)
    print(f"[*] warming detector (imgsz={imgsz}) + OCR readers", flush=True)
    backend.detect([np.zeros((544, 960, 3), np.uint8)])
    print(f"[*] readers: {', '.join(r.name for r in readers())}", flush=True)

    def iou(a, b):
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / ua if ua else 0.0

    per_cam: dict[str, dict[str, dict]] = {}
    for cid, clip in sorted(clips.items()):
        t0 = time.time()
        framedir = Path(args.clipdir) / f"{cid}_frames"
        framedir.mkdir(exist_ok=True)
        for old in framedir.glob("f*.jpg"):
            old.unlink()
        vf = ["-vf", f"fps={args.fps}"] if args.fps and args.fps > 0 else []
        subprocess.run([FFMPEG, "-nostdin", "-loglevel", "error", "-y", "-i", str(clip),
                        "-map", "0:v:0", *vf, "-q:v", "2",
                        str(framedir / "f%05d.jpg")], capture_output=True, timeout=240)
        frames = sorted(framedir.glob("f*.jpg"))

        # frame -> conditioned frame -> vehicle detect -> IoU-link into tracks, keeping the
        # sharpest few crops per track (a vehicle is plate-readable for only 1-2 frames of
        # its pass).
        tracks: list[dict] = []
        vehicles = 0
        for fi, fp in enumerate(frames):
            img = cv2.imread(str(fp))
            if img is None:
                continue
            try:
                cond = prepare_frame(img)
            except Exception:
                cond = img
            dets = [d for d in backend.detect([cond])[0] if d.label in VEHICLE]
            live = []
            for d in dets:
                vehicles += 1
                x1, y1, x2, y2 = (max(0, int(v)) for v in d.xyxy)
                if x2 - x1 < 24 or y2 - y1 < 24:
                    continue
                box = (x1, y1, x2, y2)
                crop = cond[y1:y2, x1:x2]
                sh = sharpness(crop)
                best = max((t for t in tracks if t["last"] >= fi - 2),
                           key=lambda t: iou(t["box"], box), default=None)
                if best is not None and iou(best["box"], box) >= 0.3:
                    tr = best
                else:
                    tr = {"box": box, "crops": [], "last": fi}
                    tracks.append(tr)
                tr["box"], tr["last"] = box, fi
                tr["crops"].append((sh, crop))
                live.append(tr)

        # Per track: localise the plate in every frame first, then reconstruct from the plate
        # patches -- not from the vehicle crops. Registering a 500 px bus aligns the bus; what
        # the fusion needs aligned is the 20 px glyph row, and a sub-pixel error there is a
        # whole stroke. Then MVCP decides across the reconstruction ensemble.
        hits: dict[str, dict] = {}
        name_chars = re.sub(r"[^A-Z0-9]", "", names.get(cid, "").upper())
        plate_px = []
        for tr in tracks:
            tr["crops"].sort(key=lambda sc: -sc[0])
            keep = tr["crops"][:MAX_TRACK_CROPS]

            # The plate detector fires on roughly 6 % of night vehicle crops (measured on
            # cam01). Requiring it to fire on every frame of a track would mean it never
            # accumulates enough patches to fuse. So detect *once*, on the sharpest frame it
            # works on, then carry that box to every other frame of the track by relative
            # coordinates -- the vehicle is the same object in the same part of its own crop,
            # so one detection yields as many patches as the track has frames.
            rel = None
            for sh, crop in keep:
                boxes = detect_plate_boxes(crop) or propose(crop)
                if not boxes:
                    continue
                x1, y1, x2, y2 = boxes[0]
                ch, cw = crop.shape[:2]
                if not (0 < x2 - x1 <= cw and 0 < y2 - y1 <= ch):
                    continue
                rel = (x1 / cw, y1 / ch, x2 / cw, y2 / ch)
                plate_px.append(y2 - y1)
                break

            patches = []
            if rel is not None:
                rx1, ry1, rx2, ry2 = rel
                for sh, crop in keep:
                    ch, cw = crop.shape[:2]
                    x1, y1 = int(rx1 * cw), int(ry1 * ch)
                    x2, y2 = int(rx2 * cw), int(ry2 * ch)
                    pad_x, pad_y = int((x2 - x1) * 0.10) + 2, int((y2 - y1) * 0.35) + 2
                    p = crop[max(0, y1 - pad_y):min(ch, y2 + pad_y),
                             max(0, x1 - pad_x):min(cw, x2 + pad_x)]
                    if p.size and p.shape[0] >= 6:
                        patches.append(p)

            text = conf = None
            if len(patches) >= 2:
                # the ensemble + character-position majority (mvcp.py)
                text, conf, _detail = decode_track(patches)
            if not text:
                # no localised plate, or the ensemble refused: fall back to the per-crop vote
                vote = PlateVote()
                for sh, crop in tr["crops"][:6]:
                    r = read_all(crop)
                    if r:
                        vote.add(r, sharpness=sh)
                t, c, band = vote.result()
                if t and band == "CONFIRMED":
                    text, conf = t, c

            # never a substring of the camera's burned-in name overlay (cam01 reads
            # "01 Chiman bhai Bridge" off the caption as "CH1MAN8HA")
            if text and text not in name_chars:
                h = hits.setdefault(text, {"conf": 0.0, "tracks": 0})
                h["conf"] = max(h["conf"], round(float(conf or 0.0), 3))
                h["tracks"] += 1
        per_cam[cid] = {g: {"conf": v["conf"], "band": "CONFIRMED", "seen": v["tracks"]}
                        for g, v in hits.items()}
        if plate_px:
            arr = sorted(plate_px)
            med = arr[len(arr) // 2]
            print(f"    plate heights seen: median {med}px, max {arr[-1]}px "
                  f"({len(arr)} localised)", flush=True)
        print(f"  [{cid}] {len(frames)} frames, {vehicles} vehicle dets, "
              f"{len(tracks)} tracks, {len(hits)} plate(s), {time.time()-t0:.0f}s", flush=True)

    # report
    print("\n" + "=" * 96)
    print(f"{'cam':<7} {'name':<44} plates tracked (band, conf, x seen)")
    print("-" * 96)
    result = []
    for c in cams:
        cid = c["id"]
        plates = per_cam.get(cid, {})
        if cid not in clips:
            listing = "[no feed captured]"
        elif not plates:
            listing = "-  (no plate resolved)"
        else:
            listing = "   ".join(f"{g} ({v['band']}, {v['conf']}, x{v['seen']})"
                                  for g, v in plates.items())
        print(f"{cid:<7} {c['name'][:44]:<44} {listing}")
        result.append({"camera_id": cid, "name": c["name"], "captured": cid in clips,
                       "plates": [{"plate": g, **v} for g, v in plates.items()]})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))
    tp = sum(len(r["plates"]) for r in result)
    print("-" * 96)
    print(f"{tp} plates tracked across {len(clips)}/{len(cams)} captured cameras -> {args.out}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("YOLO_VERBOSE", "0")
    raise SystemExit(main())
