"""Render Indian-format number plates as images.

Used by the scene generator to stamp known plates onto synthetic vehicles so the
ANPR pipeline can be scored against exact ground truth.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Real RTO state codes; GJ districts run 01-38.
STATE_CODES = ["GJ", "MH", "RJ", "MP", "DL", "KA", "TN", "UP", "HR", "PB"]
SERIES_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # I and O omitted, as on real plates

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\ARLRDBD.TTF",
    r"C:\Windows\Fonts\seguisb.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def random_plate(rng: random.Random, state: str = "GJ") -> str:
    """Return a plate string in the canonical spaced form, e.g. 'GJ 01 AB 1234'."""
    district = rng.randint(1, 38) if state == "GJ" else rng.randint(1, 45)
    series = "".join(rng.choice(SERIES_LETTERS) for _ in range(rng.choice([1, 2, 2, 2])))
    number = rng.randint(1, 9999)
    return f"{state} {district:02d} {series} {number:04d}"


def normalise(plate: str) -> str:
    """Strip separators for comparison: 'GJ 01 AB 1234' -> 'GJ01AB1234'."""
    return "".join(ch for ch in plate.upper() if ch.isalnum())


def render_plate(plate: str, width: int = 440, height: int = 100, *,
                 hsrp: bool = True, dirty: float = 0.0) -> np.ndarray:
    """Render a plate to a BGR numpy array.

    hsrp   -- draw the blue IND strip found on High Security Registration Plates
    dirty  -- 0..1, adds grime//uneven lighting so OCR is not trivially easy
    """
    img = Image.new("RGB", (width, height), (252, 252, 248))
    draw = ImageDraw.Draw(img)

    # Outer black border, as embossed on real plates.
    border = max(2, height // 22)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(15, 15, 15), width=border)

    text_left = border + 6
    if hsrp:
        strip_w = int(width * 0.085)
        draw.rectangle(
            [border + 2, border + 2, border + 2 + strip_w, height - border - 3],
            fill=(20, 60, 160),
        )
        ind_font = _font(max(9, height // 7))
        draw.text(
            (border + 4 + strip_w // 2, height // 2),
            "IND",
            font=ind_font,
            fill=(245, 245, 245),
            anchor="mm",
        )
        text_left = border + 8 + strip_w

    # Fit the plate text into the remaining space.
    avail_w = width - text_left - border - 6
    size = int(height * 0.62)
    font = _font(size)
    while size > 10:
        bbox = draw.textbbox((0, 0), plate, font=font)
        if (bbox[2] - bbox[0]) <= avail_w:
            break
        size -= 2
        font = _font(size)

    draw.text(
        (text_left + avail_w // 2, height // 2 + 1),
        plate,
        font=font,
        fill=(18, 18, 18),
        anchor="mm",
    )

    arr = np.array(img)[:, :, ::-1].copy()  # RGB -> BGR

    if dirty > 0:
        h, w = arr.shape[:2]
        # Uneven illumination across the plate face.
        grad = np.linspace(1.0 - 0.35 * dirty, 1.0, w, dtype=np.float32)
        arr = np.clip(arr.astype(np.float32) * grad[None, :, None], 0, 255)
        # Grime speckle.
        noise = np.random.default_rng(abs(hash(plate)) % (2**32)).normal(
            0, 14 * dirty, arr.shape
        )
        arr = np.clip(arr + noise, 0, 255).astype(np.uint8)

    return arr
