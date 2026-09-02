"""I5's verify: every [C7] vector, plus what the vectors do not cover but D relies on.

The C7 table is the contract and is asserted verbatim. The extra cases are the ones
`common/plate_compat.py` actually exercises - it feeds nulls, and it canons strings that may
already be canon - so they are as binding in practice as the table is on paper.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.plate import canon, grammar_fix, normalise, weighted_levenshtein  # noqa: E402


# --- [C7] test vectors, verbatim ------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("GJ 01 AB-1234", "GJ01AB1234"),
    ("ind gj01ab1234", "GJ01AB1234"),
])
def test_normalise_c7_vectors(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("GJ01AB1234", "6J01A81234"),
    ("6J01A81234", "6J01A81234"),
])
def test_canon_c7_vectors(raw, expected):
    assert canon(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("GJ0IAB1234", "GJ01AB1234"),   # digit slot: I -> 1
    ("6J01AB1234", "GJ01AB1234"),   # letter slot: 6 -> G
])
def test_grammar_fix_c7_vectors(raw, expected):
    assert grammar_fix(raw) == expected


@pytest.mark.parametrize("a, b, expected", [
    ("GJ01AB1234", "GJ01A81234", 0.5),   # confusion pair -> band PROBABLE
    ("GJ01AB1234", "GJ01AC1234", 1.0),   # real difference -> band POSSIBLE
])
def test_weighted_levenshtein_c7_vectors(a, b, expected):
    assert weighted_levenshtein(a, b) == expected


# --- what D needs and C7 does not state -----------------------------------------------------

@pytest.mark.parametrize("fn", [normalise, canon, grammar_fix])
def test_none_passes_through(fn):
    """plate_text is null whenever the vote fails; D's persister feeds it straight in."""
    assert fn(None) is None


def test_weighted_levenshtein_none_is_infinitely_far():
    """Never a match, never a crash - D4's band comparison simply fails."""
    assert weighted_levenshtein("GJ01AB1234", None) == float("inf")


@pytest.mark.parametrize("raw", ["GJ01AB1234", "22BH1234AB", "0ODQ1IL8B5S2Z6G"])
def test_canon_is_idempotent(raw):
    """D may canon a row that arrived already canon'd. A second pass must be a no-op."""
    assert canon(canon(raw)) == canon(raw)


@pytest.mark.parametrize("raw, expected", [
    ("GJ01A1234", "GJ01A1234"),       # 1-letter series
    ("GJ01ABC1234", "GJ01ABC1234"),   # 3-letter series
])
def test_grammar_fix_handles_every_series_length(raw, expected):
    """The series is 1-3 letters, so the slot layout shifts with total length."""
    assert grammar_fix(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("22BH1234AB", "22BH1234AB"),
    ("2Z8H1Z34AB", "22BH1234AB"),   # Z->2 in digit slots, 8->B in the literal BH
])
def test_grammar_fix_handles_bharat_series(raw, expected):
    assert grammar_fix(raw) == expected


@pytest.mark.parametrize("raw", ["", "GJ01", "GJ01AB1234567"])
def test_grammar_fix_leaves_malformed_lengths_alone(raw):
    """Emit nothing rather than a guess - a forced shape invents a registration."""
    assert grammar_fix(raw) == raw


def test_norm_then_canon_is_the_documented_pipeline():
    """plate_norm -> plate_canon, the two fields C1 carries side by side."""
    norm = grammar_fix(normalise("IND GJ-0I-AB 1234"))
    assert norm == "GJ01AB1234"
    assert canon(norm) == "6J01A81234"


# --- the slot tables: only the wrong *kind* of character is converted -------------------------
#
# Added after I7's first accuracy run: 13 of 66 tracks were CONFIRMED and wrong, and in every
# one of them both readers had read the plate correctly and grammar_fix had broken it. D and Q
# live in the "0ODQ" class and L lives in "1IL", so a letter slot was rewriting a correctly read
# D into an O and an L into an I - at 0.99 confidence, in the band an officer acts on.

@pytest.mark.parametrize("plate", [
    "GJ10DZ1209",     # D in a letter slot: a real series letter, not a misread zero
    "GJ28XL8167",     # L in a letter slot
    "GJ16ZL0910",     # Z and L together
    "GJ26KD7833",
    "GJ05Q1234",      # Q, the other member of the "0ODQ" class
    "GJ01SB5566",     # S in a letter slot, 5s in the number
    "GJ02IB1234",     # I in a letter slot
])
def test_grammar_fix_leaves_a_correctly_read_letter_alone(plate):
    assert grammar_fix(plate) == plate


@pytest.mark.parametrize("raw, expected", [
    ("GJO1AB1234", "GJ01AB1234"),     # O in a digit slot -> 0
    ("GJ0IAB1234", "GJ01AB1234"),     # I in a digit slot -> 1
    ("GJ01ABI234", "GJ01AB1234"),     # I in the number
    ("GJ01ABS234", "GJ01AB5234"),     # S in the number -> 5
    ("6J01AB1234", "GJ01AB1234"),     # 6 in a letter slot -> G
    ("0J01AB1234", "OJ01AB1234"),     # 0 in a letter slot -> O
    ("2ZBH4321AB", "22BH4321AB"),     # Z in a BH digit slot -> 2
])
def test_grammar_fix_converts_the_wrong_kind_of_character(raw, expected):
    assert grammar_fix(raw) == expected


def test_canon_still_collapses_every_class():
    """canon() is unchanged by the slot fix - it must stay lossy on purpose, and idempotent."""
    assert canon("GJ10DZ1209") == canon("6J100Z1209") == "6J10021209"
