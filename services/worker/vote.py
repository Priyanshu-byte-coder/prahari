"""[I4] The multi-frame, multi-reader character vote. The place where we decide to say nothing.

One track produces up to eight sharp crops, each read by every available reader. That is up to
24 opinions about one registration, and they disagree in a specific, exploitable way: readers
confuse characters inside a confusion class (8/B, 0/O, 1/I) far more often than across it, and
they confuse different characters on different frames. Voting per character position instead of
per whole string turns "three readers, three different strings" into "ten of eleven characters
are unanimous and one is 50/50" - which is a plate we must not report.

Order matters and it is the ticket's: grammar first, vote second. `grammar_fix` forces each
character into the class its slot demands before any counting happens, so the vote is not spent
re-deciding 0-versus-O in a digit slot where the answer is already known. What reaches the vote
is genuine ambiguity.

The 2/3 rule is a refusal, not a threshold to tune. Below it `plate_text` is null and the crop
is kept, so an officer sees a vehicle with no registration rather than a registration that
belongs to somebody else's vehicle.
"""

from __future__ import annotations

import re
from collections import defaultdict

from common.plate import grammar_fix, normalise

MAX_CROPS = 8
MAJORITY = 2.0 / 3.0
MIN_READS_FOR_TEXT = 2        # one opinion is a read, not a vote
MIN_READS_FOR_CONFIRMED = 3

VALID = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")
BANDS = ("NONE", "POSSIBLE", "PROBABLE", "CONFIRMED")


class PlateVote:
    """Per-track plate evidence. `add` on every OCR'd crop, `result` whenever you need an answer.

    Keeps the `max_crops` sharpest crops' readings, not the most recent: a track's last frames
    are usually its blurriest (the vehicle is leaving), and a blurry read that outvotes two
    sharp ones is how a vote makes accuracy worse than no vote at all.
    """

    def __init__(self, max_crops=MAX_CROPS, majority=MAJORITY):
        self.max_crops = max_crops
        self.majority = majority
        self._entries = []                  # (sharpness, [Reading, ...])
        self._cache = None

    def add(self, readings, sharpness=0.0):
        """Add one crop's readings. Returns True when they were kept."""
        readings = [r for r in readings if r and r.text]
        if not readings:
            return False
        self._cache = None
        self._entries.append((float(sharpness), readings))
        if len(self._entries) > self.max_crops:
            self._entries.sort(key=lambda e: e[0], reverse=True)
            self._entries = self._entries[:self.max_crops]
        return True

    @property
    def reads(self):
        return sum(len(rs) for _, rs in self._entries)

    @property
    def band(self):
        return self.result()[2]

    def candidates(self):
        """(text, weight) per reading, grammar-fixed. Weight is the reader's own confidence.

        Sharpness deliberately does not enter the weight: it already decided which crops are
        here at all, and multiplying by it a second time lets one very sharp frame with a
        misread outvote three merely-good frames that agree.
        """
        out = []
        for _sharp, readings in self._entries:
            for r in readings:
                text = grammar_fix(normalise(r.text))
                if text:
                    out.append((text, max(float(r.conf), 1e-3)))
        return out

    def result(self):
        """(plate_text | None, confidence, band). The only method the sighting row calls."""
        if self._cache is None:
            self._cache = self._tally()
        return self._cache

    def _tally(self):
        cands = self.candidates()
        if not cands:
            return None, 0.0, "NONE"

        # 1. Length. Only plate-shaped lengths compete; if nothing is plate-shaped the modal
        #    length still wins, so a consistent 8-character read is POSSIBLE rather than lost.
        lengths = defaultdict(float)
        for text, weight in cands:
            lengths[len(text)] += weight
        plate_shaped = {n: w for n, w in lengths.items() if 9 <= n <= 11}
        length = max(plate_shaped or lengths, key=(plate_shaped or lengths).get)
        voters = [(t, w) for t, w in cands if len(t) == length]

        # 2. Per-character weighted vote, aligned by position.
        text, ratios, weights = [], [], []
        for i in range(length):
            per_char = defaultdict(float)
            for candidate, weight in voters:
                per_char[candidate[i]] += weight
            total = sum(per_char.values())
            char = max(per_char, key=per_char.get)
            text.append(char)
            ratios.append(per_char[char] / total)
            weights.append(per_char[char] / sum(1 for c, _ in voters if c[i] == char))

        plate = grammar_fix("".join(text))          # the winners came from different readers
        agreement = min(ratios)
        conf = agreement * (sum(weights) / len(weights))
        valid = bool(VALID.match(plate))
        reads = len(voters)

        if agreement < self.majority or reads < MIN_READS_FOR_TEXT:
            # Enough evidence that something was there, not enough to name it.
            return None, round(conf, 3), "POSSIBLE"
        if not (valid or 9 <= len(plate) <= 11):
            # Corroborated across readers, but not a plate-shaped string: bus livery ("GSRTC"),
            # a shop board, a road sign the whole-vehicle candidate happened to catch. Seen on
            # every wide-area grid camera. Publish the crop and a null plate, not a PROBABLE.
            return None, round(conf, 3), "POSSIBLE"
        if valid and reads >= MIN_READS_FOR_CONFIRMED:
            return plate, round(conf, 3), "CONFIRMED"
        return plate, round(conf, 3), "PROBABLE"

    def __len__(self):
        return len(self._entries)
