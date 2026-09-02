"""[I7]/[I8] Synthetic vehicles with known plates - ground truth without a labelling week.

Salvaged from `4d0c945:simgrid/plate_render.py` and extended into a clip generator, because two
tickets need the same thing from opposite ends: I8 wants a clip whose plate we already know so
the replay harness can assert it came out the other side, and I7 wants labelled crops to score
readers against before any hand-labelled grid footage exists.

What is honest about this and what is not, stated plainly so no number gets quoted wrongly:

- The plate glyphs are rendered, so the ground truth is exact and free. Grime, uneven
  illumination, perspective, blur and JPEG loss are applied on purpose - a clean render scores
  near 100% and teaches nothing.
- Synthetic scores are an upper bound, never the deck's accuracy figure. `accuracy_report.py`
  labels every number with the split it came from, and the model card says which is which.
  The deck quotes the hand-labelled grid split (I7) once the clips arrive.
- The vehicle underneath is a real photograph, so the detector's job stays real: a drawn
  rectangle is not a car to YOLO, and a pipeline test that skips the detector is not a test.
"""

from __future__ import annotations

import logging
import random
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("prahari.worker.synth")

ROOT = Path(__file__).resolve().parents[2]
CLIPS = ROOT / "fixtures" / "clips"
VEHICLE_ASSET_URL = "https://ultralytics.com/images/bus.jpg"

STATE_CODES = ["GJ", "MH", "RJ", "MP", "DL", "KA", "TN", "UP", "HR", "PB"]
SERIES_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"      # I and O are not issued, as on real plates
_FONT_CANDIDATES = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\ARLRDBD.TTF",
                    r"C:\Windows\Fonts\seguisb.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def _font(size):
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def random_plate(rng=None, state="GJ"):
    """A plate in the spaced form, e.g. 'GJ 01 AB 1234'. `normalise` strips it for comparison."""
    rng = rng or random.Random()
    district = rng.randint(1, 38) if state == "GJ" else rng.randint(1, 45)
    series = "".join(rng.choice(SERIES_LETTERS) for _ in range(rng.choice([1, 2, 2, 2])))
    return f"{state} {district:02d} {series} {rng.randint(1, 9999):04d}"


def render_plate(plate, width=440, height=100, hsrp=True, dirty=0.0):
    """Render one plate to BGR. `dirty` in 0..1 adds grime and uneven light so OCR is not free."""
    img = Image.new("RGB", (width, height), (252, 252, 248))
    draw = ImageDraw.Draw(img)
    border = max(2, height // 22)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(15, 15, 15), width=border)

    text_left = border + 6
    if hsrp:
        # The blue IND strip of a High Security Registration Plate. normalise() strips the
        # "IND" a generous crop picks up - that is why [C7] has a removeprefix in it.
        strip_w = int(width * 0.085)
        draw.rectangle([border + 2, border + 2, border + 2 + strip_w, height - border - 3],
                       fill=(20, 60, 160))
        draw.text((border + 4 + strip_w // 2, height // 2), "IND", font=_font(max(9, height // 7)),
                  fill=(245, 245, 245), anchor="mm")
        text_left = border + 8 + strip_w

    avail = width - text_left - border - 6
    size = int(height * 0.62)
    font = _font(size)
    while size > 10 and draw.textbbox((0, 0), plate, font=font)[2] > avail:
        size -= 2
        font = _font(size)
    draw.text((text_left + avail // 2, height // 2 + 1), plate, font=font, fill=(18, 18, 18),
              anchor="mm")

    arr = np.array(img)[:, :, ::-1].copy()
    if dirty > 0:
        h, w = arr.shape[:2]
        grad = np.linspace(1.0 - 0.35 * dirty, 1.0, w, dtype=np.float32)
        arr = np.clip(arr.astype(np.float32) * grad[None, :, None], 0, 255)
        noise = np.random.default_rng(abs(hash(plate)) % (2 ** 32)).normal(0, 14 * dirty,
                                                                          arr.shape)
        arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return arr


def vehicle_asset(path=None):
    """A real vehicle photograph, cached under fixtures/clips/. Downloaded once, never committed.

    The detector has to see a vehicle for any of this to test anything, and it will not see a
    drawn rectangle. One 130 KB photo is the smallest honest way to keep the detector in the loop.

    The download is cropped to the vehicle the detector actually finds, and that crop is what
    gets cached. Without it the plate lands on the photo's background: the stamp goes on at a
    fraction of the *image* height, the detector boxes the *vehicle*, and the crop the readers
    receive is then a vehicle with no plate on it - which is how this fixture failed the first
    time it ran.
    """
    path = Path(path or CLIPS / "vehicle.jpg")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        import urllib.request
        logger.info("fetching the vehicle asset once -> %s", path)
        urllib.request.urlretrieve(VEHICLE_ASSET_URL, path)
        image = cv2.imread(str(path))
        if image is not None:
            cv2.imwrite(str(path), _crop_to_vehicle(image))
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(f"unreadable vehicle asset: {path}")
    return image


def _crop_to_vehicle(image):
    """Crop to the largest vehicle the detector finds, or return the image unchanged."""
    try:
        from services.worker.backend import LocalBackend
        boxes = LocalBackend().detect([image])[0]
    except Exception as exc:
        logger.info("no detector for the asset crop (%s) - using the whole photo", exc)
        return image
    if not boxes:
        return image
    x1, y1, x2, y2 = max(boxes, key=lambda d: (d.xyxy[2] - d.xyxy[0]) *
                         (d.xyxy[3] - d.xyxy[1])).xyxy
    h, w = image.shape[:2]
    return image[max(0, int(y1)):min(h, int(y2)), max(0, int(x1)):min(w, int(x2))]


def stamp_plate(vehicle, plate, scale=0.32, dirty=0.25, y_fraction=0.68):
    """Composite a rendered plate onto the lower face of a vehicle image. Returns a copy.

    `y_fraction` puts the plate inside the *detector's* box, not just inside the picture. A
    stamp at 0.86 of a photo's height lands on the pavement below the vehicle; the detector
    boxes the vehicle, the pipeline crops to that box, and the readers get a plateless crop -
    which is exactly how this fixture passed detection and failed OCR on its first run.
    """
    out = vehicle.copy()
    h, w = out.shape[:2]
    pw = max(60, int(w * scale))
    ph = max(14, int(pw * 100 / 440))
    rendered = cv2.resize(render_plate(plate, dirty=dirty), (pw, ph),
                          interpolation=cv2.INTER_AREA)
    x = (w - pw) // 2
    y = min(h - ph - 1, int(h * y_fraction))
    out[y:y + ph, x:x + pw] = rendered
    return out


def frames(plate, count=60, size=(1280, 720), blur=True, seed=0):
    """A vehicle carrying `plate` crossing the frame - one pass, so one sighting.

    Movement matters twice: the motion gate (I1) drops static frames, and the tracker needs
    something to associate. Scale grows as it approaches, so later crops are sharper - which is
    exactly the situation I4's sharpness gate exists for.
    """
    rng = np.random.default_rng(seed)
    vehicle = stamp_plate(vehicle_asset(), plate)
    vh, vw = vehicle.shape[:2]
    w, h = size
    road = np.zeros((h, w, 3), np.uint8)
    road[:, :] = (70, 70, 72)
    road[: h // 3] = (120, 125, 130)
    for i in range(count):
        t = i / max(1, count - 1)
        frame = road.copy()
        frame += rng.integers(0, 6, frame.shape, dtype=np.uint8)     # sensor noise
        target_h = int(h * (0.55 + 0.40 * t))     # an ANPR camera frames the
                                                  # vehicle; a 20 px plate is a
                                                  # siting fault, not a test case
        target_w = max(8, int(vw * target_h / vh))
        car = cv2.resize(vehicle, (target_w, target_h), interpolation=cv2.INTER_AREA)
        if blur and t < 0.45:
            car = cv2.GaussianBlur(car, (5, 5), 1.2 * (0.45 - t) / 0.45 + 0.1)
        x = int((w - target_w) * (0.15 + 0.7 * t))
        y = h - target_h - int(h * 0.05 * (1 - t))
        x, y = max(0, min(w - target_w, x)), max(0, min(h - target_h, y))
        frame[y:y + target_h, x:x + target_w] = car
        yield frame


def make_clip(path, plate=None, seconds=8, fps=25, size=(1280, 720), seed=0):
    """Write an H.264 clip with one known plate. Returns (path, plate)."""
    plate = plate or random_plate(random.Random(seed))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = int(seconds * fps)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise RuntimeError(f"cannot open a writer for {path}")
    try:
        for frame in frames(plate, count=count, size=size, seed=seed):
            writer.write(frame)
    finally:
        writer.release()
    _to_h264(path, fps)
    return path, plate


def _to_h264(path, fps):
    """Re-encode to H.264 so the clip decodes through the same path a grid camera does.

    mp4v is what OpenCV can write without a licensed encoder; the grid is H.264/H.265, and a
    replay harness that exercises a codec we will never see in production tests the wrong thing.
    Silently keeps the mp4v file when ffmpeg is not installed - it still decodes.
    """
    tmp = path.with_suffix(".h264.mp4")
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-g", str(int(fps)), "-r", str(int(fps)), str(tmp)], check=True)
        tmp.replace(path)
    except (OSError, subprocess.CalledProcessError) as exc:
        tmp.unlink(missing_ok=True)
        logger.info("ffmpeg re-encode skipped (%s) - clip stays mp4v", exc)


def crops(count=200, seed=0, dirty=(0.05, 1.0), cameras=4, days=3, per_track=3):
    """Labelled plate crops for the golden set: dicts with the label and its split keys.

    Camera and day are carried because I7 splits on them - crops from one clip landing on both
    sides of a split inflate every number in the report. `track` groups the crops of one pass,
    which is what lets the report score the multi-frame vote and not just single reads: a vote
    over one crop is not the thing the pipeline does.
    """
    rng = random.Random(seed)
    tracks = max(1, count // max(1, per_track))
    for t in range(tracks):
        plate = random_plate(rng)
        camera_id = f"SYNTH-{t % cameras:03d}"
        day = f"2026-09-{10 + t % days:02d}"
        for k in range(per_track):
            grime = rng.uniform(*dirty)
            crop = render_plate(plate, dirty=grime)
            # Distance to the camera. The low end is deliberately past what any reader
            # can do - a golden set where everything is readable measures nothing, and
            # the refusal rate is the number I7 exists to report honestly.
            scale = rng.uniform(0.08, 0.55)
            small = cv2.resize(crop, (max(24, int(440 * scale)), max(8, int(100 * scale))),
                               interpolation=cv2.INTER_AREA)
            if rng.random() < 0.5:
                small = cv2.GaussianBlur(small, (3, 3), rng.uniform(0.3, 1.8))
            ok, buf = cv2.imencode(".jpg", small,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), rng.randint(45, 90)])
            if ok:
                small = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            yield {"image": small, "plate": normalise_label(plate), "camera_id": camera_id,
                   "day": day, "track": f"{camera_id}-{t:04d}", "frame": k,
                   "source": "synthetic"}


def normalise_label(plate):
    """The label as the pipeline would emit it: no spaces, no separators."""
    return "".join(ch for ch in plate.upper() if ch.isalnum())
