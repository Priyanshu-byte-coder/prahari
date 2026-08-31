"""Lane D's one import point for the plate functions, plus the grammar check D adds on top.

[C7] gives lane I ownership of `common/plate.py`, and I5 has landed, so the fallback this module
used to carry is gone: `canon`, `normalise` and `weighted_levenshtein` are re-exported from the
real implementation and nothing here reimplements them. Two edit-distance functions that
disagree is a wrong plate shown to a police officer.

`is_valid_plate` stays here because it is a D-side question - "should this watchlist row be
accepted" - expressed against [C7]'s two series. It reads the grammar, it does not redefine it.
"""

import re

from common.plate import canon, grammar_fix, normalise, weighted_levenshtein  # noqa: F401

# [C7] grammar: the standard series, and the BH (Bharat) series.
STANDARD = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$")
BHARAT = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")

# True once common/plate.py exists, which is now always. Kept because tests and D4's skip
# markers read it, and because it is the honest way to say where these functions came from.
USING_I5 = True


def is_valid_plate(s):
    """True when the string matches either [C7] series. Used to reject watchlist rows early."""
    return bool(s) and bool(STANDARD.match(s) or BHARAT.match(s))
