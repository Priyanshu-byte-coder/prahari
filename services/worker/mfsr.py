"""[I] Multi-frame super-resolution for plate crops.

The single-frame problem on wide CCTV is real: a 25 px plate has no readable glyphs and no
single-image trick (Lanczos, FSRCNN, a GAN) can add information that was never sampled. But a
vehicle stopped at a signal is in *dozens* of frames, and the camera jitter / vehicle creep
between them means each frame samples the plate on a slightly different sub-pixel grid. Fusing
those samples on a finer grid recovers detail that is genuinely in the data - it redistributes
measured photons, it does not invent strokes, so it is safe to show a police officer.

Pipeline (Irani-Peleg iterative back-projection + robust fusion):

  1. upsample every LR crop to the HR grid (scale x)
  2. sub-pixel register each to a reference (ECC, translation+rotation)
  3. robust median fuse the aligned stack  -> HR estimate H0
  4. for a few iterations: for each LR frame, simulate LR' = downsample(blur(warp(H))),
     back-project (LR - LR') onto H through the same operators
  5. light unsharp finish

Nothing here is learned; the only priors are "the blur is roughly Gaussian" and "the frames
are the same plate", and step 2 drops any frame that is not.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

SCALE = int(os.getenv("PRAHARI_MFSR_SCALE", "4"))
MAX_FRAMES = int(os.getenv("PRAHARI_MFSR_MAX_FRAMES", "20"))
IBP_ITERS = int(os.getenv("PRAHARI_MFSR_ITERS", "6"))
MIN_ALIGN_CC = float(os.getenv("PRAHARI_MFSR_MIN_CC", "0.55"))
_PSF_SIGMA = 1.1


def _grey(img):
    if img is None:
        return None
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _detail_score(g):
    """Laplacian variance with the sensor-noise floor removed; a frame of static scores ~0."""
    lap = cv2.Laplacian(g, cv2.CV_64F).var()
    m = cv2.medianBlur(g, 3).astype(np.float32)
    sigma = float(np.median(np.abs(g.astype(np.float32) - m))) * 1.4826
    return max(lap - 20.0 * sigma * sigma, 0.0)


def _blur(hr):
    return cv2.GaussianBlur(hr, (0, 0), _PSF_SIGMA)


def _down(hr, size_lr):
    return cv2.resize(hr, size_lr, interpolation=cv2.INTER_AREA)


def _up(lr, size_hr):
    return cv2.resize(lr, size_hr, interpolation=cv2.INTER_CUBIC)


def super_resolve(crops, scale: int = SCALE):
    """N low-res plate crops -> one super-resolved grey plate, or None.

    Returns None when fewer than 2 usable frames survive registration - callers should then
    fall back to the single best crop.
    """
    frames = [_grey(c) for c in crops if c is not None and getattr(c, "size", 0)]
    frames = [f for f in frames if f is not None and min(f.shape[:2]) >= 6]
    if len(frames) < 2:
        return None

    # keep the most-detailed frames, cap the count, pick the reference among the survivors
    frames.sort(key=_detail_score, reverse=True)
    frames = frames[:MAX_FRAMES]
    ref_idx = 0
    h, w = frames[ref_idx].shape[:2]
    lr_size = (w, h)
    frames = [cv2.resize(f, lr_size, interpolation=cv2.INTER_AREA) if f.shape[:2] != (h, w) else f
              for f in frames]

    hr_size = (w * scale, h * scale)
    ref_hr = _up(frames[ref_idx].astype(np.float32), hr_size)

    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
    aligned, warps = [], []
    for i, f in enumerate(frames):
        up = _up(f.astype(np.float32), hr_size)
        warp = np.eye(2, 3, dtype=np.float32)
        if i != ref_idx:
            try:
                cc, warp = cv2.findTransformECC(ref_hr, up, warp, cv2.MOTION_EUCLIDEAN,
                                                criteria, None, 5)
            except cv2.error:
                continue
            if cc < MIN_ALIGN_CC:
                continue
            up = cv2.warpAffine(up, warp, hr_size,
                                flags=cv2.INTER_CUBIC + cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_REPLICATE)
        aligned.append(up)
        warps.append(warp)

    if len(aligned) < 2:
        return None

    # robust fuse: per-pixel median beats mean when one frame mis-registers slightly
    stack = np.stack(aligned, axis=0)
    hr = np.median(stack, axis=0).astype(np.float32)

    # iterative back-projection: pull the HR estimate towards every observed LR frame
    for _ in range(max(0, IBP_ITERS)):
        grad = np.zeros_like(hr)
        n = 0
        for up, warp in zip(aligned, warps):
            sim_lr = _down(_blur(hr), lr_size)
            obs_lr = _down(up, lr_size)          # `up` already warped into HR ref frame
            err_lr = obs_lr - sim_lr
            err_hr = _blur(_up(err_lr, hr_size))
            grad += err_hr
            n += 1
        hr += grad / max(n, 1)
        hr = np.clip(hr, 0, 255)

    hr8 = np.clip(hr, 0, 255).astype(np.uint8)
    # light edge lift; bilateral first so we do not amplify residual noise into speckle
    sm = cv2.bilateralFilter(hr8, d=5, sigmaColor=30, sigmaSpace=5)
    blur = cv2.GaussianBlur(sm, (0, 0), 1.4)
    hr8 = cv2.addWeighted(sm, 1.9, blur, -0.9, 0)
    return hr8
