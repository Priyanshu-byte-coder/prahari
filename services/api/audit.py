"""The audit log: append-only, hash-chained, and the thing an inquiry actually reads.

Every row answers who, what, when, from where, and - when the action requires one - why. Exports
and live views are logged as well as writes, because in a surveillance system the interesting
abuse is reading, not editing: an officer looking up an ex-partner's car leaves no trace anywhere
else.

The chain is one sha256 per row over the previous row's hash and this row's fields. It does not
stop tampering; it makes tampering *visible*, which is the achievable property. Change one row
and every hash after it stops matching, and `GET /api/admin/audit/verify` names the first break
(ticket D10).

This module owns `append_audit`; alerts.py and export.py call it so there is exactly one chain.
"""

import hashlib
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

log = logging.getLogger("audit")

# Actions that must carry a reason. A dismissal or an export with no stated why is the case an
# audit log exists to catch, so it is refused rather than recorded as a blank.
REASON_REQUIRED = {"alert.dismissed", "route.export", "grant.request", "grant.approve"}


def _as_int(value):
    """Postgres will store an int or NULL; hash the same thing."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def row_digest(prev_hash, fields):
    """sha256(prev_hash || canonical json of the fields). Key order is fixed by sort_keys, so a
    row rehashes identically on any machine and in any Python version."""
    payload = json.dumps(fields, sort_keys=True, default=str).encode()
    return hashlib.sha256((bytes(prev_hash) if prev_hash else b"") + payload).digest()


def chain_fields(user_id, dept_id, action, object_type, object_id, reason):
    return {"user_id": user_id, "dept_id": dept_id, "action": action,
            "object_type": object_type, "object_id": str(object_id), "reason": reason}


def append_audit(cur, *, action, object_type, object_id, user_id=None, dept_id=None,
                 reason=None, ip=None, grant_id=None):
    """Append one link. Returns the new hash. Raises when a reason is required and missing.

    ponytail: the chain assumes appends are serialised. Two writers that read the same tail hash
    produce two rows claiming the same predecessor, and a transaction that rolls back after
    another has committed on top of it leaves a link pointing at a row that never landed - both
    look like tampering to verify(). One API process with per-request transactions is safe; the
    upgrade is a `pg_advisory_xact_lock` on a fixed key around the read-and-insert, which costs
    a round trip and is worth it the moment a second writer exists.
    """
    if action in REASON_REQUIRED and not (reason or "").strip():
        raise ValueError(f"{action} requires a reason")
    # Hash what the database will store, not what the caller happened to pass. A JWT's `sub` is
    # a string and users.id is an integer; hashing "12" and storing 12 makes verify() report
    # tampering on a row nobody touched.
    user_id, dept_id = _as_int(user_id), _as_int(dept_id)
    cur.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1")
    row = cur.fetchone()
    prev_hash = row[0] if row else None
    fields = chain_fields(user_id, dept_id, action, object_type, object_id, reason)
    digest = row_digest(prev_hash, fields)
    cur.execute(
        """INSERT INTO audit_log (user_id, dept_id, action, object_type, object_id, ip,
                                  reason, grant_id, prev_hash, hash)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (user_id, dept_id, action, object_type, str(object_id), ip, reason, grant_id,
         prev_hash, digest))
    return digest


def record(store, **fields):
    """append_audit in its own transaction, for callers that are not already in one."""
    with store.conn as conn, conn.cursor() as cur:
        return append_audit(cur, **fields)


READ = """
SELECT seq, at, user_id, dept_id, action, object_type, object_id, ip, reason, grant_id
FROM audit_log
WHERE (%(since)s::timestamptz IS NULL OR at >= %(since)s)
  AND (%(until)s::timestamptz IS NULL OR at <= %(until)s)
ORDER BY seq DESC
LIMIT %(limit)s
"""

VERIFY = """
SELECT seq, user_id, dept_id, action, object_type, object_id, reason, prev_hash, hash
FROM audit_log ORDER BY seq
"""


class AuditLog:
    def __init__(self, store):
        self.store = store

    def read(self, since=None, until=None, limit=200):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute(READ, {"since": since, "until": until, "limit": limit})
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def verify(self):
        """Walk the chain. Returns {ok, first_broken_seq, checked}.

        Two ways it breaks, and both are reported the same way: a row whose stored hash does not
        match its own fields (someone edited it), and a row whose prev_hash does not match the
        previous row's hash (someone deleted or inserted one).
        """
        checked = 0
        previous_hash = None
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute(VERIFY)
            for (seq, user_id, dept_id, action, object_type, object_id, reason,
                 prev_hash, stored_hash) in cur:
                checked += 1
                stored_prev = bytes(prev_hash) if prev_hash is not None else None
                if stored_prev != previous_hash:
                    return {"ok": False, "first_broken_seq": seq, "checked": checked,
                            "detail": "prev_hash does not match the previous row"}
                expected = row_digest(previous_hash,
                                      chain_fields(user_id, dept_id, action, object_type,
                                                   object_id, reason))
                if bytes(stored_hash) != expected:
                    return {"ok": False, "first_broken_seq": seq, "checked": checked,
                            "detail": "row hash does not match its own fields"}
                previous_hash = bytes(stored_hash)
        return {"ok": True, "first_broken_seq": None, "checked": checked, "detail": None}


def build_router(store):
    """[C4]: GET /api/admin/audit and /api/admin/audit/verify. System Admin only ([C10])."""
    from fastapi import APIRouter, Depends

    from auth import requires

    router = APIRouter(prefix="/api/admin")
    audit = AuditLog(store)

    @router.get("/audit")
    def read_audit(since: str = None, until: str = None, limit: int = 200,
                   scope=Depends(requires("admin:audit"))):
        return audit.read(since=since, until=until, limit=limit)

    @router.get("/audit/verify")
    def verify_audit(scope=Depends(requires("admin:audit"))):
        return audit.verify()

    return router
