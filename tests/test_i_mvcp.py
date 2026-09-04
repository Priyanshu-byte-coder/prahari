"""[I] Majority vote by character position.

The property that matters is asymmetric: the vote must fix a character a minority of
reconstructions got wrong, and must refuse rather than invent when the reconstructions do not
agree. A confident wrong plate is the one failure mode this whole module exists to prevent.
"""
import numpy as np
import pytest

from services.worker.mvcp import mvcp, reconstructions


def test_majority_fixes_a_minority_error():
    """Four readers see GJ01AB1234, one sees a confusable digit. The majority wins."""
    reads = [("GJ01AB1234", 0.8), ("GJ01AB1234", 0.7), ("GJ01AB1284", 0.6),
             ("GJ01AB1234", 0.75), ("GJ01AB1234", 0.65)]
    text, conf, agreement = mvcp(reads)
    assert text == "GJ01AB1234"
    assert agreement > 0.6 and conf > 0


def test_refuses_when_reconstructions_disagree():
    """Five different strings is not a plate, it is five guesses."""
    reads = [("GJ01AB1234", 0.5), ("MH02XY9876", 0.5), ("DL03CD5555", 0.5),
             ("KA04EF7777", 0.5), ("TN05GH2222", 0.5)]
    text, _conf, _agree = mvcp(reads)
    assert text is None


def test_positional_grammar_redirects_a_confusable():
    """Position 4-5 must be letters; an 'O' read there is evidence for... nothing valid,
    but at a digit position an 'O' is evidence for '0'."""
    reads = [("GJO1AB1234", 0.8), ("GJ01AB1234", 0.8), ("GJO1AB1234", 0.7)]
    text, _c, _a = mvcp(reads)
    assert text == "GJ01AB1234"          # 'O' at a digit position folded into '0'


def test_single_opinion_is_not_a_vote():
    assert mvcp([("GJ01AB1234", 0.99)])[0] is None


def test_rejects_a_non_plate_string_the_readers_agree_on():
    """Bus livery and shop boards get read consistently; they are still not plates."""
    reads = [("GSRTCGSRTC", 0.9)] * 5
    text, _c, _a = mvcp(reads)
    assert text is None


def test_reconstructions_are_diverse_and_bounded():
    rng = np.random.default_rng(0)
    crops = [rng.integers(0, 255, (22, 90), dtype=np.uint8) for _ in range(6)]
    out = reconstructions(crops, max_variants=8)
    assert 1 <= len(out) <= 8
    assert all(o is not None and o.size for o in out)


def test_reconstructions_handles_empty_input():
    assert reconstructions([]) == []
