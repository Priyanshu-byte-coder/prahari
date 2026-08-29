"""Watchlist feeds ([C6] `WatchlistFeed`, ticket D3).

Two feeds are real - what an operator types, and what they upload. Two are stubs for the state
systems Prahari would consume in production: VAHAN (the national vehicle registry, where a
stolen-vehicle flag lives) and e-GujCop (Gujarat Police's own case system, where an FIR does).

The stubs exist because the brief asks for integration readiness, and the honest way to show it
is a written-down request and response shape behind the same protocol the live feeds implement,
returning clearly labelled sample rows. What is NOT honest is a stub that looks live in a demo:
every stub row carries source="STUB:<feed>", every stub logs a warning when pulled, and
`is_stub` is True so the console can badge it.

The field names in the stub shapes are placeholders drawn from what those systems publicly
expose. They are not a contract. Nobody should build a parser against them until the department
issues real API documentation and credentials - `TASK.md` tracks that as the open dependency.
"""

import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Protocol, runtime_checkable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchlist import WatchlistEntry, validate_row  # noqa: E402

log = logging.getLogger(__name__)


@runtime_checkable
class WatchlistFeed(Protocol):
    """[C6]. Every feed answers one question: what is new since this moment."""

    def pull(self, since: datetime) -> List[WatchlistEntry]:
        ...


class ManualFeed:
    """What operators typed into the console. The database is the source; this is the view of it.

    `since` filters on valid_from rather than a separate created_at: an entry backdated by an
    operator is new information the moment it is entered, and the matcher should see it.
    """

    is_stub = False
    name = "manual"

    def __init__(self, repo):
        self.repo = repo

    def pull(self, since):
        return [e for e in self.repo.list()
                if e.get("source") == "manual"
                and (e.get("valid_from") is None or e["valid_from"] >= since)]


class CSVFeed:
    """A CSV drop directory or a single file - the way a district sends a list today.

    Rows are validated with the same `validate_row` the API import uses. A bad row is skipped
    and logged rather than raised: a scheduled feed that dies on one malformed line stops
    delivering the other nine hundred, and nobody notices until an alert never fires.
    """

    is_stub = False
    name = "csv"

    def __init__(self, path):
        self.path = Path(path)

    def pull(self, since=None):
        entries = []
        for line, row in enumerate(self._rows(), start=2):
            try:
                entry = validate_row({(k or "").strip().lower(): v for k, v in row.items()})
            except ValueError as exc:
                log.warning("%s line %d skipped: %s", self.path, line, exc)
                continue
            entry.source = "csv"
            if since is None or entry.valid_from is None or entry.valid_from >= since:
                entries.append(entry)
        return entries

    def _rows(self) -> Iterable[dict]:
        if self.path.is_dir():
            for f in sorted(self.path.glob("*.csv")):
                yield from csv.DictReader(f.open(encoding="utf-8-sig"))
        elif self.path.exists():
            yield from csv.DictReader(self.path.open(encoding="utf-8-sig"))
        else:
            log.warning("csv feed path does not exist: %s", self.path)


class _StubFeed:
    """Shared behaviour for the two state-system stubs: sample rows, loudly labelled."""

    is_stub = True
    name = "stub"
    request_shape: dict = {}
    response_shape: dict = {}
    samples: List[dict] = []

    def pull(self, since=None):
        log.warning("%s is a STUB - sample rows only, no live connection", self.name)
        entries = []
        for sample in self.samples:
            entry = validate_row(sample)
            entry.source = f"STUB:{self.name}"
            entries.append(entry)
        return entries


class VahanFeed(_StubFeed):
    """VAHAN - the national vehicle registry. Where a theft flag against a plate lives.

    Access is per-agency and issued by the transport department; there is no public endpoint to
    develop against, so this stub carries the shape and nothing else.
    """

    name = "vahan"
    # POST, agency credentials in the header, one registration number per call.
    request_shape = {
        "endpoint": "POST {VAHAN_BASE}/vahanservice/vehicle/status",
        "headers": {"Authorization": "Bearer <agency token>", "X-Agency-Code": "<code>"},
        "body": {"regnNo": "GJ01AB1234", "consent": "Y", "purpose": "LAW_ENFORCEMENT"},
    }
    response_shape = {
        "regnNo": "GJ01AB1234",
        "ownerName": "<masked unless the requesting role permits it>",
        "vehicleClass": "MOTOR CAR",
        "makerModel": "<make model>",
        "regnDate": "2019-04-11",
        "rcStatus": "ACTIVE | SUSPENDED | SCRAPPED",
        "theftStatus": {"flag": "Y | N", "firNo": "0123/2026", "reportedOn": "2026-08-02"},
        "blacklistStatus": {"flag": "Y | N", "reason": "<text>"},
    }
    samples = [{
        "kind": "plate", "plate": "GJ01AB1234", "category": "stolen vehicle",
        "reason": "STUB sample - theftStatus.flag=Y, FIR 0123/2026",
        "severity": "HIGH", "classification": "RESTRICTED",
    }]


class EGujCopFeed(_StubFeed):
    """e-GujCop - Gujarat Police's case system. Where an FIR and its wanted persons live.

    The useful pull is "entities attached to FIRs raised since X", which is why the request
    shape is a window and not a single lookup.
    """

    name = "egujcop"
    request_shape = {
        "endpoint": "GET {EGUJCOP_BASE}/api/v1/fir/entities",
        "headers": {"Authorization": "Bearer <officer token>"},
        "query": {"since": "2026-09-01T00:00:00+05:30", "district": "AHD", "page": 1},
    }
    response_shape = {
        "page": 1, "pages": 4,
        "entities": [{
            "firNo": "0123/2026", "psCode": "AHD-NAVRANGPURA",
            "entityType": "VEHICLE | PERSON",
            "regnNo": "GJ01AB1234",
            "personName": "<name>", "personDescription": "<text>",
            "sectionsOfLaw": ["379"], "severity": "HIGH",
            "raisedOn": "2026-09-01T14:22:00+05:30",
        }],
    }
    samples = [
        {"kind": "plate", "plate": "GJ18CD5678", "category": "wanted person",
         "reason": "STUB sample - FIR 0456/2026, IPC 379",
         "severity": "CRITICAL", "classification": "CONFIDENTIAL"},
        {"kind": "description", "description": "male, approx 30, red jacket, black helmet",
         "category": "suspect", "reason": "STUB sample - FIR 0456/2026 rider description",
         "severity": "MEDIUM", "classification": "CONFIDENTIAL"},
    ]


def all_feeds(repo=None, csv_path=None):
    """Every feed the system knows about, live ones first. Stubs are still returned - the
    console shows them badged, which is the integration-readiness point the brief asks for."""
    feeds = []
    if repo is not None:
        feeds.append(ManualFeed(repo))
    if csv_path is not None:
        feeds.append(CSVFeed(csv_path))
    feeds += [VahanFeed(), EGujCopFeed()]
    return feeds


def pull_all(feeds, since=None):
    """Pull every feed, tolerating one that is down. Returns (entries, failures)."""
    since = since or datetime.now(timezone.utc)
    entries, failures = [], []
    for feed in feeds:
        try:
            entries.extend(feed.pull(since))
        except Exception as exc:                        # a feed being down is not our outage
            log.error("feed %s failed: %s", getattr(feed, "name", feed), exc)
            failures.append((getattr(feed, "name", str(feed)), str(exc)))
    return entries, failures
