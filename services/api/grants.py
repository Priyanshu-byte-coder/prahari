"""Cross-department access, bounded four ways (ticket D9).

An investigator sometimes has to see another department's cameras. The unbounded version of that
is a role that sees everything forever, which is the design a citizen is right to object to. This
is the bounded version:

  * **purpose-bound** - a case number and a reason, both required, both recorded;
  * **time-boxed** - at most 72 hours, and it expires by itself rather than waiting for somebody
    to remember to revoke it;
  * **approved by the department that owns the data** - not by the requester's own chain;
  * **provable** - every row read under a grant is logged with the grant id and the case number,
    so "who looked at our cameras, and why" is answerable months later.

A grant widens a Scope's department list and nothing else. It does not grant a capability: an
operator with a grant is still an operator, and a System Admin still cannot watch video.
"""

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit import append_audit                                   # noqa: E402
from scope import DEPT_ADMIN, INVESTIGATOR                       # noqa: E402

log = logging.getLogger("grants")

MAX_DURATION = timedelta(hours=72)
REQUESTED, APPROVED, DENIED, EXPIRED = "REQUESTED", "APPROVED", "DENIED", "EXPIRED"


class GrantError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


ACTIVE_SQL = """
SELECT id, requester, target_dept_id, case_no, reason, starts, expires
FROM access_grants
WHERE requester = %(requester)s
  AND state = 'APPROVED'
  AND (starts IS NULL OR starts <= now())
  AND expires > now()
"""


class GrantRepo:
    def __init__(self, store):
        self.store = store

    def request(self, *, requester, target_dept_id, case_no, reason, hours=24):
        """An investigator asks. Nothing is readable yet - this is a request, not a key."""
        if not (case_no or "").strip():
            raise GrantError("a case number is required: access has to belong to a case")
        if not (reason or "").strip():
            raise GrantError("a reason is required")
        if hours <= 0 or timedelta(hours=hours) > MAX_DURATION:
            raise GrantError("a grant lasts at most 72 hours")

        starts = datetime.now(timezone.utc)
        expires = starts + timedelta(hours=hours)
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO access_grants (requester, target_dept_id, case_no, reason,
                                                      starts, expires, state)
                           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (requester, target_dept_id, case_no.strip(), reason.strip(),
                         starts, expires, REQUESTED))
            grant_id = cur.fetchone()[0]
            append_audit(cur, user_id=requester, dept_id=None, action="grant.request",
                         object_type="access_grant", object_id=grant_id,
                         reason=f"case {case_no}: {reason}")
        return grant_id

    def get(self, grant_id):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, requester, target_dept_id, case_no, reason, approved_by,
                                  starts, expires, state
                           FROM access_grants WHERE id = %s""", (grant_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return dict(zip([c.name for c in cur.description], row))

    def decide(self, grant_id, *, approver_scope, approve=True):
        """The target department's admin decides. Nobody approves their own request.

        The check is on the *target* department: an investigator who could approve a request for
        somebody else's cameras would make the whole mechanism decorative.
        """
        grant = self.get(grant_id)
        if grant is None:
            raise GrantError("no such grant", status_code=404)
        if grant["state"] != REQUESTED:
            raise GrantError(f"grant is already {grant['state']}", status_code=409)
        if approver_scope.normalised_role != DEPT_ADMIN:
            raise GrantError("only a department admin approves a grant", status_code=403)
        if approver_scope.dept_id != grant["target_dept_id"]:
            raise GrantError("a grant is approved by the department that owns the data",
                             status_code=403)
        if str(approver_scope.user_id) == str(grant["requester"]):
            raise GrantError("a grant cannot be approved by its requester", status_code=403)

        state = APPROVED if approve else DENIED
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("UPDATE access_grants SET state = %s, approved_by = %s WHERE id = %s",
                        (state, _as_int(approver_scope.user_id), grant_id))
            append_audit(cur, user_id=_as_int(approver_scope.user_id),
                         dept_id=approver_scope.dept_id,
                         action="grant.approve" if approve else "grant.deny",
                         object_type="access_grant", object_id=grant_id,
                         reason=f"case {grant['case_no']}: {state.lower()}")
        return self.get(grant_id)

    def active_for(self, user_id):
        """Grants this user can read under right now. Expiry is a query, not a cron job."""
        if user_id is None:
            return []
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute(ACTIVE_SQL, {"requester": _as_int(user_id)})
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def list_for_department(self, dept_id):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, requester, target_dept_id, case_no, reason, approved_by,
                                  starts, expires, state
                           FROM access_grants WHERE target_dept_id = %s ORDER BY id DESC""",
                        (dept_id,))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def widen(scope, repo):
    """Return (scope, grants): the same scope with granted departments added to its filter.

    The grants come back too, because the read that follows has to be logged against them - a
    grant that widens access without leaving a trail is the thing this ticket exists to avoid.
    """
    grants = repo.active_for(scope.user_id)
    if not grants:
        return scope, []
    granted = [g["target_dept_id"] for g in grants]
    widened = _WidenedScope(scope, granted)
    return widened, grants


class _WidenedScope:
    """A Scope plus granted departments. Wraps rather than mutates: Scope is frozen on purpose,
    so a request handler cannot widen its own access halfway through."""

    def __init__(self, scope, granted_departments):
        self._scope = scope
        self._granted = list(granted_departments)

    def __getattr__(self, name):
        return getattr(self._scope, name)

    def department_filter(self):
        base = self._scope.department_filter()
        if base["all_departments"]:
            return base
        return {"all_departments": False,
                "departments": sorted(set(base["departments"]) | set(self._granted))}

    def allows_department(self, owner_dept_id):
        return (self._scope.allows_department(owner_dept_id)
                or owner_dept_id in self._granted)


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_router(store):
    """POST /api/grants, POST /api/grants/{id}/approve, GET /api/grants."""
    from fastapi import APIRouter, Depends, HTTPException

    from auth import current_scope

    router = APIRouter(prefix="/api/grants")
    repo = GrantRepo(store)

    @router.post("")
    def request_grant(body: dict, scope=Depends(current_scope())):
        if scope.normalised_role not in (INVESTIGATOR, DEPT_ADMIN):
            # [C10] already gives an investigator statewide *reads*, so for them a grant adds the
            # case number and the trail rather than new access. For a department admin it is the
            # only way to see another department's cameras at all. Both may ask; nobody else can.
            raise HTTPException(status_code=403,
                                detail="only an investigator or a department admin may request "
                                       "cross-department access")
        try:
            grant_id = repo.request(requester=_as_int(scope.user_id),
                                    target_dept_id=body.get("target_dept_id"),
                                    case_no=body.get("case_no"),
                                    reason=body.get("reason"),
                                    hours=int(body.get("hours", 24)))
        except GrantError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return repo.get(grant_id)

    @router.post("/{grant_id}/approve")
    def approve_grant(grant_id: int, scope=Depends(current_scope())):
        try:
            return repo.decide(grant_id, approver_scope=scope, approve=True)
        except GrantError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post("/{grant_id}/deny")
    def deny_grant(grant_id: int, scope=Depends(current_scope())):
        try:
            return repo.decide(grant_id, approver_scope=scope, approve=False)
        except GrantError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.get("")
    def list_grants(scope=Depends(current_scope())):
        if scope.normalised_role == DEPT_ADMIN:
            return repo.list_for_department(scope.dept_id)
        return repo.active_for(scope.user_id)

    return router
