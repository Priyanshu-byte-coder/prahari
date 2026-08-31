"""[C7] plate string functions. Pure, stdlib only, no I/O.

Lane I owns this file; lane D imports it (`common/plate_compat.py` prefers it the moment it
exists, so landing this file flips D onto the real implementation with no change on his side).

Every function is None-safe. `plate_text` is null whenever the multi-frame vote fails - about
13% of reads by I7's estimate - and D's persister feeds it straight in, so a raising
normalise() would turn "no plate" into a crash on the hot path.

Two forms come out of here and they are not interchangeable:
  plate_norm  - grammar_fix(normalise(s)); human-facing, what an officer reads off the map pin.
  plate_canon - canon(plate_norm); deliberately lossy, the indexed join key, never displayed.
"""

import re

# [C7]: {0,O,D,Q}->0 {1,I,L}->1 {8,B}->8 {5,S}->5 {2,Z}->2 {6,G}->6. Every class collapses,
# including G->6 - the plan's own example skipped it, knowledge_base.md logs why G2's rule wins.
# In each class the first character is the digit form and the second is the letter form, which
# is what lets one table drive canon(), both grammar slots and the substitution cost.
CLASSES = ("0ODQ", "1IL", "8B", "5S", "2Z", "6G")
TO_DIGIT = {c: k[0] for k in CLASSES for c in k}
TO_ALPHA = {c: k[1] for k in CLASSES for c in k}

_CANON = str.maketrans(TO_DIGIT)
_SEPARATORS = re.compile(r"[^A-Z0-9]")
_SAME_CLASS = {frozenset((a, b)) for k in CLASSES for a in k for b in k if a != b}


def normalise(s):
    """Upper-case, drop every separator, strip the HSRP "IND" prefix.

    The prefix is real: an HSRP carries a blue band reading IND next to the chakra hologram, a
    generous plate crop includes it, and the reader transcribes it. It is never part of the
    registration.
    """
    if s is None:
        return None
    return _SEPARATORS.sub("", s.upper()).removeprefix("IND")


def canon(s):
    """Collapse every confusion class to one representative. The matching key, never displayed.

    Idempotent by construction: each class's representative is itself a member of that class.
    D may canon a watchlist row that arrived already canon'd, and the worker canons its own
    output; without that property the second pass would silently corrupt the first.

    It over-collapses on purpose - GJ01DB1234 and GJ01OB1234 share a key. canon widens the
    candidate set cheaply; weighted_levenshtein ranks it and D4 decides. Never alert on a canon
    match alone.
    """
    return None if s is None else s.translate(_CANON)


def grammar_fix(s):
    """Force each character into the class its slot demands, per the [C7] grammars.

    Standard  ^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$ - state, RTO, series, number. The series is
    1-3 letters, so rather than matching a regex per length the slots are anchored from both
    ends: the first two and last four never move, and the series is whatever is left between.
    Bharat    ^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$ - the transferable-across-states series.

    This is accuracy for free, with no model and no inference cost, and it runs before the vote
    (I4) so the vote spends its power on genuinely ambiguous characters instead of on noise.

    A string outside 9-11 characters comes back untouched: forcing a malformed read into a
    plate shape invents a registration that was never on the vehicle.
    """
    if s is None:
        return None
    n = len(s)
    if not 9 <= n <= 11:
        return s
    # ponytail: BH detected by H at index 3 - H is in no confusion class so it cannot be a
    # corrupted RTO digit. Upgrade to trying both grammars and scoring them if a standard plate
    # ever OCRs an H into that slot.
    if n <= 10 and s[3] == "H":
        slots = ((0, 2, TO_DIGIT), (2, 4, TO_ALPHA), (4, 8, TO_DIGIT), (8, n, TO_ALPHA))
    else:
        slots = ((0, 2, TO_ALPHA), (2, 4, TO_DIGIT), (4, n - 4, TO_ALPHA), (n - 4, n, TO_DIGIT))
    out = list(s)
    for start, end, table in slots:
        for i in range(start, end):
            out[i] = table.get(out[i], out[i])
    return "".join(out)


def weighted_levenshtein(a, b):
    """Edit distance where a confusion-pair substitution costs 0.5 and anything else 1.0.

    The asymmetry is the whole point: B->8 is what a blurry camera does, B->C is a different
    vehicle. D4 turns this number into an alert band, so a cost that treated the two the same
    would either cry wolf or miss the car.

    A None operand is infinitely far - never a match, never a crash, and the band comparison at
    the call site just fails without needing to special-case nulls.
    """
    if a is None or b is None:
        return float("inf")
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            if ca == cb:
                sub = prev[j - 1]
            else:
                sub = prev[j - 1] + (0.5 if frozenset((ca, cb)) in _SAME_CLASS else 1.0)
            cur.append(min(prev[j] + 1.0, cur[j - 1] + 1.0, sub))
        prev = cur
    return float(prev[-1])
