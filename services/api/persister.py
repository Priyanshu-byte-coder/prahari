"""Consumer group `persister`: Redis `sightings` stream -> batched inserts into Postgres.

    python services/api/persister.py --duration 300

One process per box, several boxes if needed - the consumer group is what splits the stream
between them. Three behaviours are the whole ticket:

  * batch. One insert per message at 50 rows/s is 50 round trips a second, and the hypertable
    write amplifies that. Messages are read in blocks and inserted in one statement.
  * acknowledge only after the commit. A crash between the two redelivers the batch, which
    ON CONFLICT DO NOTHING in store.INSERT absorbs. The reverse order loses sightings silently.
  * reclaim. A consumer that dies leaves its messages pending forever - nobody else will ever
    read them, because they were delivered. XAUTOCLAIM moves anything idle past the threshold
    to this consumer. Without it a killed worker is a permanent hole in the timeline, which is
    exactly what J1's chaos drill kills a worker to check.

A payload that is not valid [C1] JSON is copied to `sightings.dead` and acked. Leaving it
pending would stall the group behind one bad message.
"""

import argparse
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store import Store  # noqa: E402

log = logging.getLogger("persister")

STREAM = "sightings"
GROUP = "persister"
DEAD_LETTER = "sightings.dead"


class Persister:
    def __init__(self, store=None, stream=STREAM, group=GROUP, consumer=None,
                 batch=200, block_ms=1000, claim_idle_ms=30_000):
        self.store = store or Store()
        self.stream = stream
        self.group = group
        self.consumer = consumer or f"{socket.gethostname()}-{os.getpid()}"
        self.batch = batch
        self.block_ms = block_ms
        self.claim_idle_ms = claim_idle_ms
        self.persisted = 0
        self.dead_lettered = 0
        self.reclaimed = 0
        self._claim_cursor = "0-0"

    @property
    def redis(self):
        return self.store.redis

    def ensure_group(self):
        """Create the group, tolerating the usual race of several persisters starting at once."""
        from redis.exceptions import ResponseError
        try:
            self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):            # anything else is a real failure
                raise

    def _handle(self, entries):
        """Insert one batch and ack it. Returns how many rows reached Postgres."""
        rows, acks, bad = [], [], []
        for msg_id, fields in entries:
            payload = fields.get("data")
            try:
                rows.append(json.loads(payload))
            except (TypeError, ValueError):
                bad.append((msg_id, payload))
                continue
            acks.append(msg_id)

        for msg_id, payload in bad:
            self.redis.xadd(DEAD_LETTER, {"id": msg_id, "data": payload or ""})
            self.redis.xack(self.stream, self.group, msg_id)
            self.dead_lettered += 1
            log.warning("message %s is not [C1] JSON - moved to %s", msg_id, DEAD_LETTER)

        if not rows:
            return 0
        written = self.store.insert_sightings(rows)     # commits
        self.store.cache_recent(rows)                   # cache after the commit, never before
        self.redis.xack(self.stream, self.group, *acks)
        self.persisted += len(rows)
        return written

    def reclaim(self):
        """Take over messages a dead consumer left pending. Returns how many were claimed."""
        cursor, entries, _ = self.redis.xautoclaim(
            self.stream, self.group, self.consumer,
            min_idle_time=self.claim_idle_ms, start_id=self._claim_cursor, count=self.batch)
        self._claim_cursor = cursor
        if entries:
            self.reclaimed += len(entries)
            log.info("reclaimed %d pending message(s) from a dead consumer", len(entries))
            self._handle(entries)
        return len(entries)

    def run_once(self):
        """One read-insert-ack cycle. Returns the number of messages handled."""
        response = self.redis.xreadgroup(self.group, self.consumer, {self.stream: ">"},
                                         count=self.batch, block=self.block_ms)
        if not response:
            self.reclaim()                              # idle time is the right time to reclaim
            return 0
        handled = 0
        for _stream, entries in response:
            self._handle(entries)
            handled += len(entries)
        return handled

    def lag(self):
        """Messages delivered to this group and not yet acked."""
        for info in self.redis.xinfo_groups(self.stream):
            if info["name"] == self.group:
                return info["pending"]
        return 0

    def run(self, duration=None, report_every=10.0):
        self.ensure_group()
        started = time.monotonic()
        next_report = started + report_every
        try:
            while duration is None or time.monotonic() - started < duration:
                self.run_once()
                if time.monotonic() >= next_report:
                    elapsed = time.monotonic() - started
                    log.info("%d persisted (%.1f/s), %d pending, %d reclaimed, %d dead-lettered",
                             self.persisted, self.persisted / elapsed, self.lag(),
                             self.reclaimed, self.dead_lettered)
                    next_report += report_every
        except KeyboardInterrupt:
            log.info("stopping on interrupt")
        return self.persisted


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duration", type=float, default=None, help="seconds to run, default forever")
    ap.add_argument("--batch", type=int, default=200, help="messages per read and per insert")
    ap.add_argument("--stream", default=STREAM)
    ap.add_argument("--group", default=GROUP)
    ap.add_argument("--consumer", default=None)
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--redis", default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    persister = Persister(store=Store(dsn=args.dsn, redis_url=args.redis),
                          stream=args.stream, group=args.group,
                          consumer=args.consumer, batch=args.batch)
    total = persister.run(duration=args.duration)
    print(f"persisted {total} sighting(s), {persister.lag()} still pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
