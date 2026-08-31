"""Watchlist CRUD and CSV import ([C4] endpoints, [D3]).

The import is the part with teeth. A police user uploads a spreadsheet somebody else typed, and
the useful answer is not "invalid file" - it is "line 14: GJ01AB123 is not a plate". So the
import validates every row first and writes nothing unless all of them pass. A half-imported
watchlist is worse than a rejected one: the operator believes the vehicle is being watched, and
for the rows that failed, it is not.

Plate grammar comes from [C7] via common/plate_compat, so the same rule rejects a bad row here
and matches a sighting in D4. Two copies of that regex would eventually disagree.
"""

import csv
import io
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from common.plate_compat import canon, is_valid_plate, normalise  # noqa: E402
from scope import DEPARTMENT_PREDICATE  # noqa: E402

KINDS = {"plate", "face", "description"}
CATEGORIES = {"stolen vehicle", "wanted person", "missing person",
              "blacklisted vehicle", "suspect"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
CLASSIFICATIONS = {"PUBLIC", "RESTRICTED", "CONFIDENTIAL"}

# The columns a CSV must carry. Extra columns are ignored; a missing one is a header error,
# reported once instead of once per row.
REQUIRED_COLUMNS = ["kind", "plate", "description", "category", "reason", "severity"]
OPTIONAL_COLUMNS = ["classification", "valid_from", "valid_until", "source"]


class ImportRejected(Exception):
    """Raised with the per-line errors when a CSV is not importable. Nothing was written."""

    def __init__(self, errors):
        super().__init__(f"{len(errors)} row(s) rejected")
        self.errors = errors


@dataclass
class WatchlistEntry:
    kind: str
    category: str
    reason: str
    severity: str
    plate_norm: str = None
    plate_canon: str = None
    description: str = None
    owner_dept_id: int = None
    classification: str = "RESTRICTED"
    added_by: int = None
    valid_from: datetime = None
    valid_until: datetime = None
    source: str = "manual"


def _parse_ts(value, label):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} is not an ISO timestamp: {value!r}") from exc


def validate_row(row):
    """Return a WatchlistEntry, or raise ValueError with a reason a human can act on."""
    kind = (row.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}, got {kind!r}")

    plate = normalise((row.get("plate") or "").strip()) or None
    description = (row.get("description") or "").strip() or None
    if kind == "plate":
        if not plate:
            raise ValueError("kind is plate but no plate was given")
        if not is_valid_plate(plate):
            raise ValueError(f"{plate} does not match either plate series in [C7]")
    elif not description:
        raise ValueError(f"kind is {kind} but no description was given")

    category = (row.get("category") or "").strip().lower()
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {sorted(CATEGORIES)}, got {category!r}")

    severity = (row.get("severity") or "").strip().upper()
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(SEVERITIES)}, got {severity!r}")

    reason = (row.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is empty - every entry has to say why it is being watched")

    classification = (row.get("classification") or "RESTRICTED").strip().upper()
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")

    valid_from = _parse_ts(row.get("valid_from"), "valid_from")
    valid_until = _parse_ts(row.get("valid_until"), "valid_until")
    if valid_from and valid_until and valid_until <= valid_from:
        raise ValueError("valid_until is not after valid_from")

    return WatchlistEntry(
        kind=kind, category=category, reason=reason, severity=severity,
        plate_norm=plate, plate_canon=canon(plate) if plate else None,
        description=description, classification=classification,
        valid_from=valid_from, valid_until=valid_until,
        source=(row.get("source") or "manual").strip() or "manual")


INSERT = """
INSERT INTO watchlist (kind, plate_norm, plate_canon, description, category, reason, severity,
                       owner_dept_id, classification, added_by, valid_from, valid_until, source)
VALUES (%(kind)s, %(plate_norm)s, %(plate_canon)s, %(description)s, %(category)s, %(reason)s,
        %(severity)s, %(owner_dept_id)s, %(classification)s, %(added_by)s, %(valid_from)s,
        %(valid_until)s, %(source)s)
RETURNING id
"""

# Static SQL with optional predicates. Both filters are parameters, so the statement never
# changes shape and there is no string building to get wrong later.
SELECT = """
SELECT id, kind, plate_norm, plate_canon, description, category, reason, severity,
       owner_dept_id, classification, added_by, valid_from, valid_until, source
FROM watchlist
WHERE (%(owner_dept_id)s::int IS NULL OR owner_dept_id = %(owner_dept_id)s)
  AND (%(active_at)s::timestamptz IS NULL
       OR ((valid_from IS NULL OR valid_from <= %(active_at)s)
       AND (valid_until IS NULL OR valid_until > %(active_at)s)))
  AND """ + DEPARTMENT_PREDICATE + """
ORDER BY id
"""


class WatchlistRepo:
    def __init__(self, store):
        self.store = store

    def add(self, entry, added_by=None, owner_dept_id=None):
        params = dict(entry.__dict__)
        params["added_by"] = entry.added_by or added_by
        params["owner_dept_id"] = entry.owner_dept_id or owner_dept_id
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute(INSERT, params)
            return cur.fetchone()[0]

    def list(self, owner_dept_id=None, active_at=None, scope=None):
        """Entries, narrowed to the caller's scope, optionally to a department, and
        optionally to a moment they are valid at.

        The validity window is not decoration: an expired entry that still matches produces an
        alert an officer has to dismiss, which is how a watchlist stops being trusted.

        scope=None means "no user asked for this" - the matcher and the persister run as the
        system, not as a person. Every path that serves a request passes a real Scope.
        """
        params = {"owner_dept_id": owner_dept_id, "active_at": active_at}
        params.update(scope.department_filter() if scope is not None
                      else {"all_departments": True, "departments": []})
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute(SELECT, params)
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def delete(self, entry_id):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM watchlist WHERE id = %s", (entry_id,))
            return cur.rowcount

    def import_csv(self, text, added_by=None, owner_dept_id=None):
        """Validate every row, then write them all or none.

        Returns the count added. Line numbers in the rejection are the ones the user sees in
        their spreadsheet: the header is line 1, so the first data row is line 2.
        """
        reader = csv.DictReader(io.StringIO(text))
        header = [h.strip().lower() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ImportRejected([{"line": 1, "reason": f"header is missing: {', '.join(missing)}"}])

        entries, errors = [], []
        for line, row in enumerate(reader, start=2):
            clean = {(k or "").strip().lower(): v for k, v in row.items()}
            try:
                entries.append(validate_row(clean))
            except ValueError as exc:
                errors.append({"line": line, "reason": str(exc)})

        if errors:
            raise ImportRejected(errors)                # nothing written, by design
        if not entries:
            raise ImportRejected([{"line": 1, "reason": "no data rows"}])

        with self.store.conn as conn, conn.cursor() as cur:
            for entry in entries:
                params = dict(entry.__dict__)
                params["added_by"] = added_by
                params["owner_dept_id"] = owner_dept_id
                cur.execute(INSERT, params)
        return {"added": len(entries), "errors": []}
