"""[I] SR-ensemble + Majority Vote by Character Position.

The published state of the art on low-resolution plates (Nascimento et al., *Toward Advancing
License Plate Super-Resolution in Real-World Scenarios*, JBCS 2025, UFPR-SR-Plates) measures
exactly our regime -- LR plates of median height 18-21 px -- and reports:

    LR crop straight to OCR ............................  1.7 %
    + best single-image SR (LCDNet) .................... 31.1 %
    + majority vote by character position over 5 SR images  44.7 %

The jump from 31 % to 45 % comes from *not trusting one reconstruction*. Different
super-resolvers hallucinate differently; the character a majority of them agree on at a given
position is far more likely to be the one that was photographed. That is the idea this module
implements, with two changes that fit our situation better than the paper's:

  * They had five LR frames per track. A vehicle stopped at a signal gives us dozens, so the
    ensemble includes multi-frame reconstructions (mfsr.super_resolve) at several scales and
    frame budgets -- these add real measured detail rather than a prior.
  * The vote is grammar-aware. An Indian plate is [A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}; at a
    position that must be a digit, O/D/Q cannot win, and at a letter position 0/1/5 cannot.
    This is free precision: it removes the confusion pairs that SR artefacts create.

`decode_track` is the entry point: crops of one tracked plate in, (text, confidence, per-
position agreement) out. It never returns a string the grammar rejects, and it returns None
when the ensemble does not agree -- refusing beats a confident wrong plate.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict

import cv2
import numpy as np

logger = logging.getLogger("prahari.worker.mvcp")

# Positional character classes for the Indian formats [C7] recognises.
LETTERS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS = set("0123456789")

# Glyph pairs that low-resolution reconstruction confuses. Used only to *move probability
# mass*, never to rewrite a character the readers agreed on.
CONFUSABLE = {
    "0": "ODQ", "O": "0DQ", "D": "0O", "Q": "0O",
    "1": "IL", "I": "1L", "L": "1I",
    "2": "Z", "Z": "2",
    "5": "S", "S": "5",
    "8": "B", "B": "8",
    "6": "G", "G": "6",
    "4": "A", "A": "4",
    "7": "T", "T": "7",
}

MIN_VARIANT_AGREE = float(os.getenv("PRAHARI_MVCP_MIN_AGREE", "0.55"))
MIN_VARIANTS = int(os.getenv("PRAHARI_MVCP_MIN_VARIANTS", "3"))


# --- the reconstruction ensemble ----------------------------------------------------------

def _enhance(img):
    from services.worker.preprocess import enhance_plate_crop
    try:
        return enhance_plate_crop(img)
    except Exception:
        return img


def reconstructions(crops, max_variants: int = 8):
    """Several independent reconstructions of one plate from its track's crops.

    Diversity is the point: a multi-frame estimate, a single-frame learned upscale and a plain
    interpolation fail in different ways, so a character all three produce is evidence, while
    one only the GAN-ish path produces is suspicion.
    """
    usable = [c for c in crops if c is not None and getattr(c, "size", 0)]
    if not usable:
        return []
    from services.worker.mfsr import super_resolve
    from services.worker.preprocess import best_of, fuse, superres

    out = []

    # 1-3. multi-frame super-resolution at several scales / frame budgets. Each uses a
    # different reference frame and a different HR grid, so they are genuinely independent
    # estimates rather than one estimate resized.
    if len(usable) >= 3:
        for scale, budget in ((4, len(usable)), (6, min(12, len(usable))), (3, min(24, len(usable)))):
            try:
                hr = super_resolve(usable[:budget], scale=scale)
            except Exception:
                hr = None
            if hr is not None:
                out.append(_enhance(hr))

    # 4. align-and-average fusion (no back-projection): conservative, never rings.
    try:
        f = fuse(usable)
        if f is not None:
            out.append(_enhance(f))
    except Exception:
        pass

    best = best_of(usable) if len(usable) > 1 else usable[0]
    if best is not None and best.size:
        # 5. learned single-image SR on the sharpest frame.
        try:
            out.append(_enhance(superres(best, scale=4)))
        except Exception:
            pass
        # 6. plain Lanczos: the no-prior control. If it agrees with the learned paths, the
        #    character was in the pixels.
        try:
            lz = cv2.resize(best, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
            out.append(_enhance(lz))
        except Exception:
            pass
        # 7. the raw sharpest crop, enhanced only. Guards against SR making things worse.
        out.append(_enhance(best))

    return [o for o in out if o is not None and getattr(o, "size", 0)][:max_variants]


# --- the vote -------------------------------------------------------------------------------

def _positional_class(length, index):
    """What a character at this position may be, for the plate layouts we accept.

    Indian format is AA NN X{1,3} NNNN, so the first two are letters, the next two digits and
    the last four digits whatever the middle series length is. The middle is left unconstrained
    because its length varies.
    """
    if length < 9 or length > 11:
        return None
    if index < 2:
        return LETTERS
    if index < 4:
        return DIGITS
    if index >= length - 4:
        return DIGITS
    return LETTERS


def mvcp(readings, min_agree: float = MIN_VARIANT_AGREE):
    """Majority vote by character position over many (text, confidence) opinions.

    Returns (text, confidence, agreement) or (None, conf, agreement) when the vote does not
    clear `min_agree` at every position. Modelled on the MVCP strategy that took the UFPR
    benchmark from 31 % to 45 %, plus the positional grammar constraint.
    """
    from common.plate import grammar_fix, normalise

    cands = []
    for text, conf in readings:
        t = grammar_fix(normalise(text)) or ""
        if t:
            cands.append((t, max(float(conf), 1e-3)))
    if len(cands) < 2:
        return None, 0.0, 0.0

    # 1. length: only plate-plausible lengths compete, weighted by confidence and by how many
    #    distinct reconstructions produced them.
    lengths = defaultdict(float)
    for t, w in cands:
        lengths[len(t)] += w
    plausible = {n: v for n, v in lengths.items() if 9 <= n <= 11}
    length = max(plausible or lengths, key=(plausible or lengths).get)
    voters = [(t, w) for t, w in cands if len(t) == length]
    if len(voters) < 2:
        return None, 0.0, 0.0

    # 2. per position: weighted vote, with confusable mass folded into the class the position
    #    allows. A digit position seeing 'O' counts that as evidence for '0'.
    text, agreements = [], []
    for i in range(length):
        allowed = _positional_class(length, i)
        per_char = defaultdict(float)
        for t, w in voters:
            ch = t[i]
            if allowed and ch not in allowed:
                # redirect the vote to the allowed twin of this glyph, if there is one
                twin = next((c for c in CONFUSABLE.get(ch, "") if c in allowed), None)
                if twin is None:
                    continue            # this reader cannot be talking about a plate here
                per_char[twin] += w * 0.8
            else:
                per_char[ch] += w
        if not per_char:
            return None, 0.0, 0.0
        total = sum(per_char.values())
        ch = max(per_char, key=per_char.get)
        text.append(ch)
        agreements.append(per_char[ch] / total)

    plate = grammar_fix("".join(text)) or ""
    agreement = min(agreements) if agreements else 0.0
    mean_conf = sum(w for _, w in voters) / len(voters)
    conf = round(agreement * mean_conf, 3)

    from services.worker.vote import VALID
    if not VALID.match(plate):
        return None, conf, agreement
    if agreement < min_agree or len(voters) < MIN_VARIANTS:
        return None, conf, agreement
    return plate, conf, round(agreement, 3)


def decode_track(crops, engines=None):
    """One tracked plate's crops -> (text | None, confidence, detail dict).

    Builds the reconstruction ensemble, reads every variant with every OCR engine, and decides
    by character-position majority. `detail` carries what the deck and the audit row want:
    how many variants were built, how many produced a read, and the weakest position's
    agreement.
    """
    from services.worker.plate import read_all

    variants = reconstructions(crops)
    readings = []
    for v in variants:
        for r in read_all(v, engines=engines):
            if r.text:
                readings.append((r.text, r.conf))
    text, conf, agreement = mvcp(readings)
    return text, conf, {
        "variants": len(variants),
        "reads": len(readings),
        "agreement": agreement,
    }
