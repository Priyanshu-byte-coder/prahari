"""Consumer group `matcher`: every sighting is checked against the watchlist as it arrives.

    python services/api/matcher.py --duration 300

Runs beside the persister on the same stream, in its own consumer group, so a slow match never
delays a write and a database hiccup never loses an alert - both groups see every message.

How a candidate is found, in the order that keeps it O(1) in the common case:

  1. `plate_canon` lookup. [C7]'s canon() collapses every confusion class, so any single
     confusion-pair edit lands on the same canon key. One dict hit, no scan.
  2. exact `plate_norm`, which is a subset of the above but distinguishes CONFIRMED from the
     rest.
  3. trigram similarity in Postgres, for the edits canon cannot catch - a plain misread that
     changes the canon key. This is the distance-2 fallback, and it is a query, so it only runs
     when the first two find nothing.

The band comes from the weighted distance alone, and that is not a shortcut - it falls out of
[C7]'s cost table:

    cost 0      exact match         -> CONFIRMED if the sighting itself was CONFIRMED
    cost 0.5    one confusion edit  -> PROBABLE
    cost 1.0    one plain edit, or two confusion edits (both "distance 2" or "distance 1
                outside the pairs" in D4's wording)                      -> POSSIBLE
    cost <= 2.0 anything else within two edits                           -> POSSIBLE
    cost > 2.0  not the same plate                                       -> no alert

weighted_levenshtein comes from common/plate.py (I5). There is no second copy: two edit-distance
functions that disagree is a wrong plate shown to a police officer.
"""

import argparse
import json
import logging
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from alerts import AlertRepo                                          # noqa: E402
from common.plate_compat import canon, weighted_levenshtein           # noqa: E402
from store import Store                                               # noqa: E402

log = logging.getLogger("matcher")

STREAM = "sightings"
GROUP = "matcher"

CONFIRMED, PROBABLE, POSSIBLE = "CONFIRMED", "PROBABLE", "POSSIBLE"
MAX_COST = 2.0                  # beyond two edits it is a different vehicle
# Retrieval floor, not a decision threshold. Measured on Postgres pg_trgm: one plain edit in a
# ten-character plate scores 0.57, two edits 0.47, an unrelated plate 0.0. A 0.7 floor - D6's
# number for user-facing fuzzy search, where precision matters - would return nothing here and
# the fallback would be dead code. This query only narrows the field; weighted_levenshtein
# still decides the band, so a loose floor costs a few extra comparisons and nothing else.
TRIGRAM_FLOOR = 0.4
INDEX_TTL = 30.0                # seconds before the watchlist index is reloaded


def band_for(cost, sighting_band):
    """The [D4] band table, in one place so the test can walk it row by row."""
    if cost is None or cost > MAX_COST:
        return None
    if cost == 0:
        # An exact string match is only CONFIRMED if the read itself was confident. A POSSIBLE
        # read that happens to spell a watched plate is exactly the case that should not put
        # CONFIRMED in front of an officer.
        return CONFIRMED if sighting_band == CONFIRMED else PROBABLE
    if cost == 0.5:
        return PROBABLE
    return POSSIBLE


class WatchlistIndex:
    """Active plate entries, keyed by canon. Small enough to hold; reloaded on a timer.

    Only entries valid *now* are indexed. An expired entry that still matched would produce an
    alert an officer has to dismiss, and a watchlist that cries wolf stops being read.
    """

    def __init__(self, store, ttl=INDEX_TTL):
        self.store = store
        self.ttl = ttl
        self.by_canon = {}
        self.loaded_at = 0.0
        self.size = 0

    def load(self):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, plate_norm, plate_canon, severity, category, owner_dept_id
                           FROM watchlist
                           WHERE kind = 'plate' AND plate_norm IS NOT NULL
                             AND (valid_from  IS NULL OR valid_from  <= now())
                             AND (valid_until IS NULL OR valid_until >  now())""")
            cols = [c.name for c in cur.description]
            entries = [dict(zip(cols, r)) for r in cur.fetchall()]
        index = {}
        for entry in entries:
            index.setdefault(entry["plate_canon"] or canon(entry["plate_norm"]), []).append(entry)
        self.by_canon, self.size, self.loaded_at = index, len(entries), time.monotonic()
        log.info("watchlist index: %d active plate entr(ies)", self.size)

    def fresh(self):
        if time.monotonic() - self.loaded_at > self.ttl:
            self.load()
        return self

    def candidates(self, plate_norm):
        """Entries sharing a canon key with this plate. One dict hit, no scan."""
        return list(self.by_canon.get(canon(plate_norm), []))

    def trigram_candidates(self, plate_norm, floor=TRIGRAM_FLOOR, limit=5):
        """The fallback for edits canon cannot see. A query, so it runs only when needed."""
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, plate_norm, plate_canon, severity, category, owner_dept_id,
                                  similarity(plate_norm, %s) AS sim
                           FROM watchlist
                           WHERE kind = 'plate' AND plate_norm IS NOT NULL
                             AND (valid_from  IS NULL OR valid_from  <= now())
                             AND (valid_until IS NULL OR valid_until >  now())
                             AND similarity(plate_norm, %s) >= %s
                           ORDER BY sim DESC LIMIT %s""",
                        (plate_norm, plate_norm, floor, limit))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def best_match(sighting, index):
    """Return (entry, band, cost) for the closest watchlist entry, or None.

    Candidates are ranked by weighted distance and ties broken by severity: given two entries
    equally close, the one flagged CRITICAL is the one an operator needs to see.
    """
    plate = sighting.get("plate_norm")
    if not plate:
        return None                              # a failed vote is not a match, it is a gap

    candidates = index.candidates(plate) or index.trigram_candidates(plate)
    if not candidates:
        return None

    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    scored = []
    for entry in candidates:
        cost = weighted_levenshtein(plate, entry["plate_norm"])
        band = band_for(cost, sighting.get("plate_band"))
        if band is not None:
            scored.append((cost, severity_rank.get(entry.get("severity"), 9), entry, band))
    if not scored:
        return None
    cost, _, entry, band = min(scored, key=lambda s: (s[0], s[1]))
    return entry, band, cost


class Matcher:
    def __init__(self, store=None, stream=STREAM, group=GROUP, consumer=None,
                 batch=100, block_ms=1000):
        self.store = store or Store()
        self.alerts = AlertRepo(self.store)
        self.index = WatchlistIndex(self.store)
        self.stream = stream
        self.group = group
        self.consumer = consumer or f"{socket.gethostname()}-matcher"
        self.batch = batch
        self.block_ms = block_ms
        self.checked = 0
        self.raised = 0
        self.deduped = 0

    @property
    def redis(self):
        return self.store.redis

    def ensure_group(self):
        from redis.exceptions import ResponseError
        try:
            self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):            # already created by a sibling
                raise

    def check(self, sighting):
        """Match one sighting. Returns the alert id when one was raised or bumped."""
        self.checked += 1
        hit = best_match(sighting, self.index.fresh())
        if hit is None:
            return None
        entry, band, _cost = hit
        alert_id, created = self.alerts.raise_alert(watchlist_id=entry["id"],
                                                    sighting=sighting, band=band)
        if created:
            self.raised += 1
        else:
            self.deduped += 1
        return alert_id

    def run_once(self):
        response = self.redis.xreadgroup(self.group, self.consumer, {self.stream: ">"},
                                         count=self.batch, block=self.block_ms)
        if not response:
            return 0
        handled = 0
        for _stream, entries in response:
            for msg_id, fields in entries:
                try:
                    sighting = json.loads(fields.get("data"))
                except (TypeError, ValueError):
                    # The persister dead-letters these; the matcher only has to not die on one.
                    self.redis.xack(self.stream, self.group, msg_id)
                    continue
                try:
                    self.check(sighting)
                finally:
                    # Ack either way: a sighting that cannot be matched is not worth blocking
                    # the group for, and the row is already durable via the persister.
                    self.redis.xack(self.stream, self.group, msg_id)
                handled += 1
        return handled

    def run(self, duration=None, report_every=10.0):
        self.ensure_group()
        self.index.load()
        started = time.monotonic()
        next_report = started + report_every
        try:
            while duration is None or time.monotonic() - started < duration:
                self.run_once()
                if time.monotonic() >= next_report:
                    log.info("%d checked, %d alert(s) raised, %d deduped",
                             self.checked, self.raised, self.deduped)
                    next_report += report_every
        except KeyboardInterrupt:
            log.info("stopping on interrupt")
        return self.raised


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--stream", default=STREAM)
    ap.add_argument("--group", default=GROUP)
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--redis", default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    matcher = Matcher(store=Store(dsn=args.dsn, redis_url=args.redis),
                      stream=args.stream, group=args.group, batch=args.batch)
    raised = matcher.run(duration=args.duration)
    print(f"checked {matcher.checked} sighting(s), raised {raised} alert(s), "
          f"{matcher.deduped} deduped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
