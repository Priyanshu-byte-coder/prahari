"""[I] Multi-frame super-resolution: it must add real detail from sub-pixel-shifted frames
and never invent it, and it must degrade gracefully to None when there is nothing to fuse.
"""
import cv2
import numpy as np
import pytest

from services.worker.mfsr import super_resolve


def _plate_image(text="GJ01AB1234", w=440, h=110):
    img = np.full((h, w), 235, np.uint8)
    cv2.putText(img, text, (12, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 4, cv2.LINE_AA)
    return img


def _degrade(img, target_h, n, jitter=1.5, noise=6.0, seed=0):
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    tw = max(8, round(w * target_h / h))
    out = []
    for _ in range(n):
        M = np.float32([[1, 0, rng.uniform(-jitter, jitter)],
                        [0, 1, rng.uniform(-jitter, jitter)]])
        s = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        s = cv2.resize(s, (tw, target_h), interpolation=cv2.INTER_AREA)
        s = np.clip(s.astype(np.float32) + rng.normal(0, noise, s.shape), 0, 255).astype(np.uint8)
        out.append(s)
    return out


def test_returns_none_without_enough_frames():
    assert super_resolve([]) is None
    assert super_resolve([np.zeros((10, 20), np.uint8)]) is None


def test_output_is_larger_and_bounded():
    frames = _degrade(_plate_image(), target_h=24, n=8)
    hr = super_resolve(frames, scale=4)
    assert hr is not None
    assert hr.shape[0] > frames[0].shape[0] * 2          # genuinely upscaled
    assert hr.dtype == np.uint8 and hr.min() >= 0 and hr.max() <= 255


def test_recovers_detail_a_single_frame_lost():
    """The fused image must be sharper (higher Laplacian energy, noise-corrected) than the
    best single degraded frame upscaled the same amount."""
    truth = _plate_image()
    frames = _degrade(truth, target_h=22, n=16, noise=8.0)
    scale = 5
    single = cv2.resize(frames[0], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    hr = super_resolve(frames, scale=scale)
    assert hr is not None
    hr = cv2.resize(hr, single.shape[::-1])

    def energy(g):
        lap = cv2.Laplacian(g, cv2.CV_64F).var()
        sigma = np.median(np.abs(g.astype(float) - cv2.medianBlur(g, 3))) * 1.4826
        return max(lap - 20 * sigma * sigma, 0.0)

    assert energy(hr) > energy(single) * 1.15


def test_does_not_hallucinate_on_a_blank_plate():
    blank = np.full((90, 360), 220, np.uint8)
    frames = _degrade(blank, target_h=20, n=12, noise=5.0)
    hr = super_resolve(frames, scale=4)
    # either it declines (nothing to align on a featureless plate) or it stays blank -
    # what it must never do is invent strokes
    assert hr is None or hr.std() < 25
