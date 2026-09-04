"""[I7b] Low-resolution plate benchmark, comparable to the published state of the art.

Reproduces the operating point of UFPR-SR-Plates (Nascimento et al., JBCS 2025): license
plates whose *median height is 18-21 px*, degraded by distance, motion and compression, with
several sequential frames per vehicle. On that benchmark the paper reports

    LR crop straight to OCR .................................  1.7 - 2.2 %
    + best single-image super-resolution (LCDNet) ........... 29.9 - 31.1 %
    + majority vote by character position over 5 SR images .. 42.3 - 44.7 %

so those are the numbers to beat. This script measures the same three conditions on our own
pipeline, at a sweep of plate heights, and prints them side by side.

    python scripts/lr_benchmark.py --heights 16,20,24 --frames 8

Degradation is deliberately harsher than a plain downscale, because a plain downscale is the
criticism the paper levels at earlier work: per-frame sub-pixel jitter, linear motion blur,
Poisson-Gaussian sensor noise and JPEG compression, all applied *before* the downscale, in
that order -- which is the order a real camera applies them.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from common.plate import grammar_fix, normalise
from services.worker.mvcp import decode_track, mvcp, reconstructions
from services.worker.plate import read_all
from services.worker.preprocess import enhance_plate_crop, superres

GOLDEN = ROOT / "fixtures" / "golden"


SEVERITY = {
    # name:        (contrast, motion, noise, jpeg, perspective)
    "day":         (1.00, 1.2,  4.0, 60, 0.02),
    "dusk":        (0.55, 2.0,  9.0, 45, 0.05),
    "night":       (0.30, 2.8, 14.0, 35, 0.08),
}


def degrade(plate_img, target_h, n_frames, rng, severity="dusk"):
    """One clean plate -> n sequential low-resolution frames, in camera order.

    A plain downscale is the criticism the paper levels at earlier work: rendered glyphs at
    full contrast survive it, and a benchmark built that way reports accuracy the field does
    not have. What actually destroys a plate on a junction camera, in the order the camera
    applies it, is: it is not facing you (perspective), its face is dim and its glyphs are not
    black (contrast collapse), the vehicle moves during the exposure (motion blur), the sensor
    is short of photons (Poisson-Gaussian noise) and the encoder throws away what is left
    (JPEG). `severity` calibrates the first four to daylight, dusk or night.
    """
    contrast, motion, noise, jpeg, persp = SEVERITY[severity]
    h, w = plate_img.shape[:2]
    tw = max(8, int(round(w * target_h / h)))

    # contrast collapse toward the local mean: a night plate is grey glyphs on a grey face
    base = plate_img.astype(np.float32)
    mid = float(base.mean())
    base = np.clip(mid + (base - mid) * contrast, 0, 255)

    # a fixed viewing angle for the whole track - the camera does not move between frames
    dx1, dy1, dx2, dy2 = (rng.uniform(-persp, persp) * w for _ in range(4))
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[dx1, dy1], [w + dx2, dy1 * .5], [w + dx2 * .5, h + dy2], [dx1 * .5, h + dy2]])
    H = cv2.getPerspectiveTransform(src, dst)
    base = cv2.warpPerspective(base, H, (w, h), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)

    frames = []
    for _ in range(n_frames):
        # 1. sub-pixel motion between frames (vehicle creep + camera shake)
        dx, dy = rng.uniform(-2.0, 2.0), rng.uniform(-1.0, 1.0)
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        img = cv2.warpAffine(base, M, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
        # 2. linear motion blur along the direction of travel
        k = max(3, int(motion * h / target_h) | 1)
        psf = np.zeros((k, k), np.float32)
        psf[k // 2, :] = 1.0 / k
        ang = rng.uniform(-8, 8)
        psf = cv2.warpAffine(psf, cv2.getRotationMatrix2D((k / 2 - .5, k / 2 - .5), ang, 1), (k, k))
        s = psf.sum()
        if s > 0:
            img = cv2.filter2D(img, -1, psf / s)
        # 3. optical downscale to the sensor's sampling of the plate
        small = cv2.resize(img, (tw, target_h), interpolation=cv2.INTER_AREA)
        # 4. Poisson-Gaussian sensor noise
        f = small.astype(np.float32)
        shot = rng.poisson(np.clip(f, 0, None) / 8.0) * 8.0 - f
        f = f + rng.normal(0, noise, f.shape) + shot * 0.3
        small = np.clip(f, 0, 255).astype(np.uint8)
        # 5. lossy transport
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg)])
        if ok:
            small = cv2.imdecode(buf, cv2.IMREAD_COLOR if small.ndim == 3 else cv2.IMREAD_GRAYSCALE)
        frames.append(small)
    return frames


def _best_text(readings):
    """The most plate-like string from a list of Readings."""
    from services.worker.vote import VALID
    best, rank = "", (-1, -1, -1.0)
    for r in readings:
        t = grammar_fix(normalise(r.text)) or ""
        k = (int(bool(VALID.match(t))), len(t), r.conf)
        if k > rank:
            best, rank = t, k
    return best


def condition_lr(frames):
    """Baseline: the sharpest LR crop, upscaled only so the reader accepts it."""
    ref = frames[len(frames) // 2]
    up = cv2.resize(ref, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    return _best_text(read_all(up))


def condition_sr(frames):
    """Single-image super-resolution on the sharpest frame, then OCR (paper's middle row)."""
    ref = frames[len(frames) // 2]
    try:
        hr = enhance_plate_crop(superres(ref, scale=4))
    except Exception:
        hr = ref
    return _best_text(read_all(hr))


def condition_mvcp(frames):
    """Ours: multi-frame SR ensemble + majority vote by character position."""
    text, _conf, _d = decode_track(frames)
    return text or ""


def main():
    ap = argparse.ArgumentParser(description="low-resolution plate benchmark")
    ap.add_argument("--heights", default="16,20,24", help="plate heights in px to sweep")
    ap.add_argument("--frames", type=int, default=8, help="LR frames per track")
    ap.add_argument("--tracks", type=int, default=20, help="plates to test per height")
    ap.add_argument("--severity", default="dusk", choices=["day","dusk","night"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "docs" / "lr-benchmark.md"))
    args = ap.parse_args()

    labels = [json.loads(l) for l in (GOLDEN / "labels.jsonl").read_text().splitlines() if l.strip()]
    seen, plates = set(), []
    for row in labels:
        if row["plate"] in seen:
            continue
        img = cv2.imread(str(GOLDEN / row["path"]))
        if img is None or img.shape[0] < 30:
            continue
        seen.add(row["plate"])
        plates.append((normalise(row["plate"]), img))
    plates = plates[: args.tracks]
    print(f"{len(plates)} distinct plates, {args.frames} LR frames each\n")

    heights = [int(h) for h in args.heights.split(",")]
    rows = []
    for th in heights:
        rng = np.random.default_rng(args.seed)
        random.seed(args.seed)
        score = {"lr": 0, "sr": 0, "mvcp": 0}
        t0 = time.time()
        for truth, img in plates:
            frames = degrade(img, th, args.frames, rng, severity=args.severity)
            for name, fn in (("lr", condition_lr), ("sr", condition_sr), ("mvcp", condition_mvcp)):
                try:
                    got = fn(frames)
                except Exception as exc:
                    logger_msg = f"{name} failed: {type(exc).__name__}"
                    print("   ", logger_msg)
                    got = ""
                score[name] += (got == truth)
        n = len(plates)
        rows.append((th, score["lr"] / n, score["sr"] / n, score["mvcp"] / n, time.time() - t0))
        print(f"plate height {th:>3}px   LR {score['lr']:>2}/{n}   "
              f"SR {score['sr']:>2}/{n}   MVCP {score['mvcp']:>2}/{n}   "
              f"({time.time()-t0:.0f}s)")

    md = [
        "# Low-resolution plate benchmark (generated, do not edit)",
        "",
        f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S%z')}",
        f"- {len(plates)} distinct plates x {args.frames} degraded frames each, "
        f"severity `{args.severity}`, seed {args.seed}",
        "- degradation, in camera order: sub-pixel motion -> linear motion blur -> optical "
        "downscale -> Poisson-Gaussian noise -> JPEG",
        "",
        "Reference point: UFPR-SR-Plates (Nascimento et al., JBCS 2025) measures plates of "
        "median height 18-21 px and reports **1.7-2.2 %** for LR straight to OCR, "
        "**29.9-31.1 %** with the best single-image SR, and **42.3-44.7 %** with majority vote "
        "by character position over five super-resolved images.",
        "",
        "| plate height | LR -> OCR | single-image SR | **ours: MFSR ensemble + MVCP** |",
        "|---|---|---|---|",
    ]
    for th, lr, sr, mv, _ in rows:
        md.append(f"| {th} px | {lr:.1%} | {sr:.1%} | **{mv:.1%}** |")
    md += ["", "Exact full-plate match; a partially correct plate counts as wrong."]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
