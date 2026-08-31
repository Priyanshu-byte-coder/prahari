"""One stand-in for `common/plate.py` until lane I ships it (I5), and one place to delete after.

[C7] gives lane I ownership of the plate functions and tells lane D to import them. D's tickets
sit in wave 1, I5 has not landed, and copying the functions into two D modules would leave two
copies to reconcile later. So: every D module imports from here, this module prefers the real
implementation the moment it exists, and the fallback below is deleted with this file.

The fallback is deliberately the minimum D needs - canon() and the grammar regexes. It does not
implement weighted_levenshtein: that function decides whether two plates are the same vehicle,
and a second implementation of it would eventually disagree with the one lane I ships. Asking
for it without I5 raises, naming the ticket, instead of guessing.
"""

import re

# [C7]: {0,O,D,Q}->0 {1,I,L}->1 {8,B}->8 {5,S}->5 {2,Z}->2 {6,G}->6. Every class collapses,
# including G->6 - the plan's own example skipped it, and knowledge_base.md logs why G2 wins.
CONFUSION = {**dict.fromkeys("0ODQ", "0"), **dict.fromkeys("1IL", "1"),
             **dict.fromkeys("8B", "8"), **dict.fromkeys("5S", "5"),
             **dict.fromkeys("2Z", "2"), **dict.fromkeys("6G", "6")}

# [C7] grammar: the standard series, and the BH (Bharat) series.
STANDARD = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$")
BHARAT = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")

USING_I5 = False

try:
    from common.plate import canon, normalise, weighted_levenshtein  # noqa: F401  (I5)
    USING_I5 = True
except ImportError:
    def weighted_levenshtein(a, b):
        raise RuntimeError(
            "weighted_levenshtein lives in common/plate.py, which lane I owns (ticket I5). "
            "It is not merged yet - see PR #38. [C7] says D imports it; D does not reimplement "
            "it, because two edit-distance functions disagreeing is a wrong plate shown to an "
            "officer.")

    def normalise(s):
        """Upper-case, strip separators and a leading IND."""
        if s is None:
            return None
        s = re.sub(r"[\s.\-]", "", s).upper()
        return s[3:] if s.startswith("IND") else s

    def canon(s):
        return None if s is None else "".join(CONFUSION.get(c, c) for c in s)


def is_valid_plate(s):
    """True when the string matches either [C7] series. Used to reject watchlist rows early."""
    return bool(s) and bool(STANDARD.match(s) or BHARAT.match(s))
