"""Frame and crop conditioning for the plate pipeline - measured against the real grid.

Why this file exists, in numbers taken off the live cameras on 2026-09-03 (see
`scripts/grid_survey.py`, which produced them):

    cam04 Paldi Circle   1920x1080  median vehicle box  55 px wide  -> plate ~16 px, glyph ~2 px
    cam17 Rajkot Bus Port 1920x1080 median vehicle box 378 px wide  -> plate ~106 px, glyph ~17 px

An Indian plate is 500 x 120 mm on a vehicle about 1800 mm wide, so the plate face is roughly
0.28 of the vehicle box width and the glyph row inside it about 0.65 of the plate height. On
cam04 that is a two-pixel character. No OCR engine, no super-resolution and no amount of
sharpening reads a two-pixel character; anything that claims to is inventing it. So the first
job of this module is to *refuse*, per camera, and say why - a wrong plate on a police report
is worse than no plate.

The second job is everything that is genuinely recoverable:

  before detection   deinterlace, flatten exposure, denoise only when the frame is actually
                     noisy, and - the big one - tile the frame instead of letterboxing it to
                     640, because a 55 px vehicle in a 1920 px frame is 18 px after the
                     letterbox and the detector never sees it at all.

  after the crop     upscale to a glyph height the recognisers were trained on, flatten the
                     plate's own illumination (sun on the top half, shadow on the bottom is
                     the normal case at a junction), deskew, correct perspective when the
                     plate face gives us four corners, then smooth *before* sharpening -
                     bilateral first so the sharpen amplifies glyph edges and not sensor
                     noise, which is the difference between a readable 8 and a readable B.

  across frames      a track gives us the same plate several times. Aligning and averaging
                     four crops removes independent noise and recovers real detail - it is
                     the only honest super-resolution here, because it adds information from
                     other frames rather than hallucinating it from a prior.

Nothing here is a model. It is all classical, it all runs on CPU in the low milliseconds on a
crop, and it is deliberately separate from `plate.py` so lane I can wire it in one call.
"""

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("prahari.worker.preprocess")

# --- plate geometry, in millimetres, so the pixel maths is checkable ----------------------

PLATE_W_MM = 500.0
PLATE_H_MM = 120.0
VEHICLE_W_MM = 1800.0            # a hatchback; a truck is wider, which only helps
GLYPH_FRACTION = 0.65            # glyph height inside the plate face

PLATE_W_FRACTION = PLATE_W_MM / VEHICLE_W_MM              # 0.28 of the vehicle box
GLYPH_H_FRACTION = PLATE_W_FRACTION * (PLATE_H_MM / PLATE_W_MM) * GLYPH_FRACTION

# Recogniser floors. EasyOCR's CRNN and PaddleOCR's SVTR are trained on 32-48 px text lines;
# below ~14 px of *native* glyph the upscale is interpolating strokes that were never sampled.
GLYPH_OK_PX = 14.0
# Measured, not guessed: scripts/lr_benchmark.py at night severity puts the cliff between a
# 20 px plate (13 px glyph, 65 % exact with the MVCP ensemble) and a 16 px plate (10 px glyph,
# 5 %). Below ~10 px of glyph the multi-frame path stops recovering characters, so that is
# where "marginal" ends and "do not guess" begins.
GLYPH_MARGINAL_PX = 10.0
TARGET_GLYPH_PX = 32.0           # what we upscale to before handing a crop to a reader
MAX_UPSCALE = 4.0                # past 4x the interpolation invents more than it recovers
MIN_ALIGN_CC = 0.55              # ECC correlation below which a frame is not this plate

# Frame conditioning thresholds, all measured on grid frames rather than guessed.
DARK_MEAN = 70.0                 # below this a night frame needs gamma before anything else
BRIGHT_MEAN = 195.0
LOW_CONTRAST_STD = 38.0
NOISY_SIGMA = 6.0                # estimated sensor sigma above which denoise earns its cost
COMB_RATIO = 1.35                # row-to-row vs 2-row difference: above this it is interlaced


# --- measurement -------------------------------------------------------------------------

@dataclass
class FrameQuality:
    """What a frame is, before anyone decides what to do to it."""
    width: int
    height: int
    sharpness: float             # variance of Laplacian
    brightness: float
    contrast: float              # std of the grey channel
    sigma: float                 # estimated noise sigma
    interlaced: bool

    @property
    def dark(self):
        return self.brightness < DARK_MEAN

    @property
    def blown(self):
        return self.brightness > BRIGHT_MEAN

    @property
    def flat(self):
        return self.contrast < LOW_CONTRAST_STD

    @property
    def noisy(self):
        return self.sigma > NOISY_SIGMA


def _grey(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def estimate_sigma(grey):
    """Immerkaer's noise estimate: a Laplacian-like kernel whose response to real edges is
    small and to independent noise is not. Cheap enough to run per frame."""
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
    response = cv2.filter2D(grey.astype(np.float32), -1, kernel)
    h, w = grey.shape[:2]
    return float(np.abs(response).sum() * math.sqrt(0.5 * math.pi) / (6.0 * max(w - 2, 1) * max(h - 2, 1)))


def is_interlaced(grey):
    """Comb detection. An interlaced frame of moving traffic differs far more between
    neighbouring rows (different fields, 20 ms apart) than between rows two apart."""
    if grey.shape[0] < 8:
        return False
    near = float(np.abs(np.diff(grey.astype(np.int16), axis=0)).mean())
    far = float(np.abs(grey[2::2].astype(np.int16) - grey[:-2:2].astype(np.int16)).mean())
    if far < 0.5:
        # Rows two apart are identical: either a flat frame (near is 0 too, nothing to fix) or
        # a perfect comb, where every difference lives between the fields. Guarding on far > 0
        # alone made the textbook case - alternating bright and dark lines - report progressive.
        return near > 2.0
    return near / far > COMB_RATIO


def measure(frame):
    grey = _grey(frame)
    return FrameQuality(width=frame.shape[1], height=frame.shape[0],
                        sharpness=float(cv2.Laplacian(grey, cv2.CV_64F).var()),
                        brightness=float(grey.mean()), contrast=float(grey.std()),
                        sigma=estimate_sigma(grey), interlaced=is_interlaced(grey))


def sharpness(image):
    """One number for "is this crop worth reading". Used to pick the best frame of a track."""
    if image is None or image.size == 0:
        return 0.0
    return float(cv2.Laplacian(_grey(image), cv2.CV_64F).var())


# --- feasibility, per camera ---------------------------------------------------------------

@dataclass
class Feasibility:
    glyph_px: float
    verdict: str                 # "ok" | "marginal" | "no"
    reason: str

    @property
    def readable(self):
        return self.verdict != "no"


def feasibility(vehicle_box_w_px):
    """Can a plate on a vehicle this size be read at all? Answer before spending an OCR pass.

    This is the gate that keeps the demo honest. On the wide-area cameras the answer is no,
    and the right thing to do is track the vehicle and say "plate not resolvable at this
    camera" rather than hand an operator four confident characters of noise.
    """
    glyph = GLYPH_H_FRACTION * float(vehicle_box_w_px or 0)
    if glyph >= GLYPH_OK_PX:
        return Feasibility(glyph, "ok", "glyph height is inside the recognisers' training range")
    if glyph >= GLYPH_MARGINAL_PX:
        return Feasibility(glyph, "marginal",
                           "glyph is under-sampled; read only with multi-frame fusion and "
                           "treat a single-frame read as unconfirmed")
    return Feasibility(glyph, "no",
                       f"glyph would be {glyph:.1f}px; below {GLYPH_MARGINAL_PX:.0f}px the "
                       "strokes were never sampled - track the vehicle, do not guess the plate")


def min_vehicle_width_for_ocr(glyph_px=GLYPH_OK_PX):
    """The vehicle box width a camera must produce before ANPR is worth attempting on it."""
    return glyph_px / GLYPH_H_FRACTION


# --- before detection ------------------------------------------------------------------------

def deinterlace(frame):
    """Blend the two fields. Dropping one field halves vertical resolution, which on a plate
    is the resolution we are short of; blending keeps it and kills the comb."""
    blurred = cv2.GaussianBlur(frame, (1, 3), 0)
    return blurred


def flatten_exposure(frame, quality=None):
    """CLAHE on L only. Applied to BGR it shifts colour and the detector's confidences with
    it; on L it fixes the junction's usual problem, which is a sunlit road and a shaded
    underpass in the same frame."""
    q = quality or measure(frame)
    if not (q.dark or q.blown or q.flat):
        return frame
    if frame.ndim == 2:
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(frame)
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def gamma(frame, value):
    table = np.array([((i / 255.0) ** (1.0 / value)) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(frame, table)


def prepare_frame(frame, quality=None):
    """Condition a frame for the *detector*. Never resizes: the detector owns its own scaling.

    Order matters and is not arbitrary. Deinterlace first or every later filter smears the two
    fields together. Denoise before contrast, or CLAHE amplifies the noise it was meant to see
    past. Gamma last, because it is the only step that changes the mean the detector's
    normalisation assumes.
    """
    q = quality or measure(frame)
    out = frame
    if q.interlaced:
        out = deinterlace(out)
    if q.noisy:
        # Bilateral, not fastNlMeans: at 1080p25 fastNlMeans costs ~200 ms/frame and the whole
        # per-frame budget is 40 ms. Bilateral keeps the edges the detector keys on.
        out = cv2.bilateralFilter(out, d=5, sigmaColor=35, sigmaSpace=5)
    out = flatten_exposure(out, q)
    if q.dark:
        out = gamma(out, 1.6)
    elif q.blown:
        out = gamma(out, 0.8)
    return out


def tiles(frame, tile=960, overlap=0.2):
    """Yield (x_offset, y_offset, sub_frame) covering the frame with overlapping tiles.

    This is the fix for the measurement that started this file. A 55 px vehicle in a 1920 px
    frame becomes 18 px once the detector letterboxes to 640, which is below what YOLO's
    smallest stride can hold - the vehicle is not "missed", it is not represented. Detecting
    on 960 px tiles keeps it at 37 px and costs one extra forward pass per tile.

    Overlap exists so a vehicle on a tile seam is whole in at least one tile; the caller is
    expected to run NMS across the union of the boxes it gets back.
    """
    h, w = frame.shape[:2]
    if tile <= 0 or (w <= tile and h <= tile):
        yield 0, 0, frame
        return
    step = max(int(tile * (1.0 - overlap)), 1)
    ys = list(range(0, max(h - tile, 0) + 1, step)) or [0]
    xs = list(range(0, max(w - tile, 0) + 1, step)) or [0]
    if ys[-1] + tile < h:
        ys.append(h - tile)
    if xs[-1] + tile < w:
        xs.append(w - tile)
    for y in ys:
        for x in xs:
            yield x, y, frame[y:y + tile, x:x + tile]


def tile_plan(frame_w, expected_vehicle_w, detector_input=640):
    """Whether tiling is needed at all, and the tile size that puts the vehicle back in range.

    Returns (tile_px, reason). tile_px of 0 means "feed the whole frame, it is already fine".
    """
    if not expected_vehicle_w:
        return 0, "no measurement yet - start whole-frame and revisit once boxes exist"
    after_letterbox = expected_vehicle_w * (detector_input / float(frame_w))
    if after_letterbox >= 96:
        return 0, f"vehicle survives the letterbox at {after_letterbox:.0f}px"
    wanted = max(int(frame_w * expected_vehicle_w / 96.0 * (detector_input / float(frame_w))), 320)
    tile = min(int(round(wanted / 64.0) * 64), frame_w)
    return tile, (f"vehicle is {after_letterbox:.0f}px after a whole-frame letterbox; "
                  f"{tile}px tiles keep it near 96px")


# --- after the crop --------------------------------------------------------------------------

def upscale_to_glyph(crop, glyph_px=None, target=TARGET_GLYPH_PX):
    """Resize so the glyph row lands at the height recognisers were trained on.

    Lanczos, not cubic: on a plate the glyph strokes are one or two pixels wide and cubic
    rounds their corners into each other - 8 and B differ by exactly that. Capped at 4x
    because past that the interpolator is drawing, not recovering.
    """
    if crop is None or crop.size == 0:
        return crop
    h = crop.shape[0]
    current = glyph_px if glyph_px else h * GLYPH_FRACTION
    if current <= 0:
        return crop
    factor = float(np.clip(target / current, 1.0, MAX_UPSCALE))
    if factor <= 1.01:
        return crop
    return cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_LANCZOS4)


_ROOT = Path(__file__).resolve().parents[2]
_SR_DEFAULT = _ROOT / "models" / "FSRCNN_x4.pb"
_SR_CACHE = {}
SR_BELOW_PX = int(os.getenv("PRAHARI_SR_BELOW_PX", "40"))   # crop height under which SR earns its cost


def _sr_model():
    """Cached cv2.dnn_superres model + its scale, or None. Non-generative EDSR/FSRCNN/ESPCN."""
    if "m" in _SR_CACHE:
        return _SR_CACHE["m"]
    path = os.environ.get("PRAHARI_SR_MODEL", "") or (str(_SR_DEFAULT) if _SR_DEFAULT.exists() else "")
    if not path or not os.path.exists(path) or not hasattr(cv2, "dnn_superres"):
        _SR_CACHE["m"] = None
        return None
    try:
        base = os.path.basename(path)
        arch = base.split("_")[0].lower()
        scale = int(base.split("_x")[1].split(".")[0]) if "_x" in base else 4
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(path)
        sr.setModel(arch, scale)
        _SR_CACHE["m"] = (sr, scale)
        logger.info("super-resolution: %s x%d", arch, scale)
    except (cv2.error, ValueError, IndexError) as exc:
        logger.info("super-resolution unavailable (%s); Lanczos in use", exc)
        _SR_CACHE["m"] = None
    return _SR_CACHE["m"]


def superres(crop, scale=2):
    """Upscale a small plate crop. Uses cv2.dnn_superres (non-generative) when a model is on
    disk (models/FSRCNN_x4.pb by default, or PRAHARI_SR_MODEL), else Lanczos.

    # ponytail: a plate-specific SR net (LPSRGAN and friends) beats a generic one on glyph
    # strokes, but a generative SR model can and does invent characters that were never in
    # the pixels. Generic, non-generative is the version that is safe to show a police officer.
    """
    if crop is None or crop.size == 0:
        return crop
    m = _sr_model()
    if m is None:
        return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    sr, sscale = m
    try:
        bgr = crop if crop.ndim == 3 else cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        out = sr.upsample(bgr)
        if crop.ndim == 2:
            out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        if sscale != scale:  # model fixed at sscale; correct to the asked ratio
            f = scale / sscale
            out = cv2.resize(out, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LANCZOS4)
        return out
    except cv2.error:
        return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)


def flatten_plate_illumination(grey):
    """Divide out the plate's own lighting. A plate half in sun and half in shadow binarises
    into half a plate under any global threshold; dividing by a morphological estimate of the
    background removes the gradient and leaves the glyphs."""
    k = max(3, (grey.shape[0] // 2) | 1)
    background = cv2.morphologyEx(grey, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    flat = cv2.divide(grey, background, scale=255)
    return flat


DEBLUR = os.getenv("PRAHARI_DEBLUR", "").strip().lower() in ("1", "true", "yes")


def motion_deblur(grey, k=9, angle=0.0, nsr=0.02):
    """Bounded Wiener deconvolution against a linear motion kernel. Off by default
    (PRAHARI_DEBLUR=1). Non-generative -- it inverts a blur, it does not synthesise strokes --
    but it can ring on a wrong kernel, so it is opt-in and the vote still gates the result.
    """
    if grey is None or grey.size == 0 or min(grey.shape[:2]) < 12:
        return grey
    psf = np.zeros((k, k), np.float32)
    psf[k // 2, :] = 1.0
    M = cv2.getRotationMatrix2D((k / 2 - 0.5, k / 2 - 0.5), angle, 1.0)
    psf = cv2.warpAffine(psf, M, (k, k))
    psf /= psf.sum() or 1.0
    g = grey.astype(np.float32) / 255.0
    H = np.fft.fft2(psf, s=g.shape)
    G = np.fft.fft2(g)
    F = np.conj(H) / (np.abs(H) ** 2 + nsr)
    out = np.real(np.fft.ifft2(G * F))
    out = np.fft.fftshift(out)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def smooth_then_sharpen(grey, strength=1.4):
    """Bilateral first, unsharp second, and the order is the whole point.

    Sharpening a noisy crop multiplies the noise into speckle that OCR reads as punctuation.
    Bilateral smooths the flat plate face while leaving the glyph edges standing, and the
    unsharp mask then lifts exactly those edges. This is the step that turns a soft 40 px
    plate into one where the strokes have a definite side.
    """
    smoothed = cv2.bilateralFilter(grey, d=5, sigmaColor=40, sigmaSpace=5)
    blur = cv2.GaussianBlur(smoothed, (0, 0), 1.2)
    return cv2.addWeighted(smoothed, 1.0 + strength, blur, -strength, 0)


def deskew(grey, limit_deg=20.0):
    """Rotate the glyph row level. A 10-degree tilt costs a recogniser more than 20% of its
    accuracy because its receptive field is a horizontal strip."""
    binary = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    points = cv2.findNonZero(binary)
    if points is None or len(points) < 20:
        return grey
    # OpenCV has shipped two conventions for this angle: (0, 90] on 4.5+ and [-90, 0) before it,
    # and the CI runner does not necessarily have the same build as a laptop. Fold it into
    # [-45, 45] and the caller stops caring which one it got - without this, a level plate reads
    # as 90 degrees of tilt on one build and 0 on the other.
    angle = cv2.minAreaRect(points)[-1] % 90
    if angle > 45:
        angle -= 90
    if abs(angle) < 0.5 or abs(angle) > limit_deg:
        return grey                       # nothing to fix, or the estimate is not the text
    h, w = grey.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    return cv2.warpAffine(grey, m, (w, h), flags=cv2.INTER_LANCZOS4,
                          borderMode=cv2.BORDER_REPLICATE)


def _order_quad(pts):
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def unwarp(crop, min_area_ratio=0.25):
    """Perspective-correct the plate face when its four corners are findable.

    A plate photographed from the side of the road is a trapezium; a recogniser trained on
    rectangles reads the narrow end badly. When no convincing quad is found this returns the
    crop untouched - forcing a warp onto a wrong quad is worse than a slightly skewed plate.
    """
    grey = _grey(crop)
    edges = cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return crop
    area = grey.shape[0] * grey.shape[1]
    best = max(contours, key=cv2.contourArea)
    if cv2.contourArea(best) < min_area_ratio * area:
        return crop
    quad = cv2.approxPolyDP(best, 0.02 * cv2.arcLength(best, True), True)
    if len(quad) != 4:
        return crop
    src = _order_quad(quad.reshape(4, 2).astype(np.float32))
    w = int(max(np.linalg.norm(src[0] - src[1]), np.linalg.norm(src[3] - src[2])))
    h = int(max(np.linalg.norm(src[0] - src[3]), np.linalg.norm(src[1] - src[2])))
    if w < 16 or h < 8:
        return crop
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    return cv2.warpPerspective(crop, cv2.getPerspectiveTransform(src, dst), (w, h),
                               flags=cv2.INTER_LANCZOS4)


def enhance_plate_crop(crop, glyph_px=None, want_binary=False):
    """The full post-crop chain, in the order that survives contact with a real plate.

    unwarp -> grey -> upscale -> illumination flatten -> smooth+sharpen -> deskew -> CLAHE

    Upscaling before flattening and sharpening is deliberate: both of those work on
    neighbourhoods, and a 3x3 neighbourhood on a 40 px plate is a third of a character. After
    the upscale it is a stroke, which is what the filters were designed for.

    Returns the grey crop the CRNN/SVTR readers want. `want_binary` additionally returns the
    Sauvola-style adaptive threshold Tesseract prefers - it is a third opinion in the vote,
    and it fails differently, which is the only reason it is worth its latency.
    """
    if crop is None or crop.size == 0:
        return (crop, crop) if want_binary else crop
    face = unwarp(crop)
    grey = _grey(face)
    # A genuinely small plate crop (distant CCTV) gains more from a learned x2/x4 than from
    # Lanczos; run SR first, then upscale_to_glyph finishes to the exact target height.
    if grey.shape[0] < SR_BELOW_PX:
        grey = superres(grey, scale=2)
    grey = upscale_to_glyph(grey, glyph_px)
    grey = flatten_plate_illumination(grey)
    if DEBLUR:
        grey = motion_deblur(grey)
    grey = smooth_then_sharpen(grey)
    grey = deskew(grey)
    grey = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4)).apply(grey)
    if not want_binary:
        return grey
    block = max(15, (grey.shape[0] // 2) | 1)
    binary = cv2.adaptiveThreshold(grey, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, block, 12)
    return grey, binary


# --- across frames ---------------------------------------------------------------------------

LAPLACIAN_NOISE_GAIN = 20.0      # sum of squared taps in the 3x3 Laplacian: var_lap = 20*sigma^2


def detail(crop):
    """Sharpness with the noise floor taken out, which is the number we actually wanted.

    Variance of Laplacian is the usual focus measure and it is badly behaved twice over. A crop
    shrunk to 60x15 aliases, and aliasing scores higher than a clean 440x110 plate. Pure sensor
    noise scores higher still - a frame of static is the "sharpest" image there is. The 3x3
    Laplacian's response to independent noise is 20*sigma^2, so subtracting that leaves the
    part of the variance that came from edges. A frame of static lands at zero, where it
    belongs.
    """
    if crop is None or crop.size == 0:
        return 0.0
    grey = _grey(crop)
    return max(sharpness(grey) - LAPLACIAN_NOISE_GAIN * estimate_sigma(grey) ** 2, 0.0)


def _score(crop):
    """Detail weighted by how many pixels carry it: big and real beats small and aliased."""
    if crop is None or crop.size == 0:
        return 0.0
    return detail(crop) * float(crop.shape[0] * crop.shape[1])


def best_of(crops):
    """The crop worth spending an OCR pass on: sharpest, weighted by how big it is.

    Size alone picks the nearest frame, which at a junction is often the most motion-blurred;
    sharpness alone picks an aliased 20 px plate over a good 60 px one.
    """
    scored = [(_score(c), c) for c in crops if c is not None and c.size]
    return max(scored, key=lambda s: s[0])[1] if scored else None


def _fusion_reference(crops):
    """The frame everything else is aligned onto.

    Not simply the sharpest: a frame that is mostly sensor noise scores as very sharp, and
    aligning six good crops onto a noisy one makes the average worse than any input. `detail()`
    subtracts the noise floor first, so the reference is the frame with real edges in it.
    """
    return max(crops, key=_score)


def fuse(crops, reference=None, max_frames=6):
    """Align several crops of the same plate and average them.

    This is the honest super-resolution. Sensor noise is independent between frames, so it
    averages down as sqrt(n) while the glyph stays; sub-pixel shifts between frames mean the
    average also carries real detail no single frame had. Four frames of a tracked vehicle is
    typically worth more than any single-image SR model, and unlike a generative model it
    cannot invent a character.

    ECC alignment is used because the crops differ by a small translation plus a little scale,
    and it fails loudly (cv2.error) rather than silently mis-aligning, in which case that
    frame is dropped instead of smeared into the result.
    """
    usable = [c for c in crops if c is not None and c.size][:max_frames]
    if not usable:
        return None
    if len(usable) == 1:
        return usable[0]
    ref = _grey(reference if reference is not None else _fusion_reference(usable)).astype(np.float32)
    h, w = ref.shape[:2]
    stack = [ref]
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
    for crop in usable:
        grey = _grey(crop).astype(np.float32)
        if grey.shape[:2] != (h, w):
            grey = cv2.resize(grey, (w, h), interpolation=cv2.INTER_LANCZOS4)
        if grey is ref:
            continue
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            cc, warp = cv2.findTransformECC(ref, grey, warp, cv2.MOTION_EUCLIDEAN,
                                            criteria, None, 5)
        except cv2.error:
            continue                       # too different to align: drop it, do not smear it
        if cc < MIN_ALIGN_CC:
            # ECC converged on something, but not on this plate. A frame that "aligned" at a
            # correlation of 0.2 is a different scene - a decode artefact, a passing wiper, the
            # next vehicle - and averaging it in pulls the glyphs apart instead of cleaning
            # them. Dropping frames is free; a smeared average costs the read.
            continue
        stack.append(cv2.warpAffine(grey, warp, (w, h),
                                    flags=cv2.INTER_LANCZOS4 + cv2.WARP_INVERSE_MAP,
                                    borderMode=cv2.BORDER_REPLICATE))
    fused = np.mean(stack, axis=0)
    return np.clip(fused, 0, 255).astype(np.uint8)


_MFSR = os.getenv("PRAHARI_MFSR", "1").strip().lower() not in ("0", "false", "no")
_MFSR_MIN_FRAMES = int(os.getenv("PRAHARI_MFSR_MIN_FRAMES", "4"))


def prepare_for_ocr(crops, glyph_px=None, want_binary=False):
    """Track-level entry point: several crops of one vehicle in, one reader-ready image out.

    With enough frames, multi-frame super-resolution (mfsr.super_resolve) reconstructs the
    plate on a finer grid than any single frame sampled - the one operation that adds real
    information on a distant CCTV plate. Falls back to the align+average `fuse` otherwise.
    """
    usable = [c for c in crops if c is not None and getattr(c, "size", 0)]
    fused = None
    if _MFSR and len(usable) >= _MFSR_MIN_FRAMES:
        try:
            from services.worker.mfsr import super_resolve
            fused = super_resolve(usable)
        except Exception as exc:            # pragma: no cover
            logger.debug("mfsr failed (%s) - falling back to fuse()", exc)
    if fused is None:
        fused = fuse(usable)
    if fused is None:
        return None
    return enhance_plate_crop(fused, glyph_px=glyph_px, want_binary=want_binary)
