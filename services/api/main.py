"""The API: every [C4] endpoint on one app, every read behind a scope ([C10], ticket D7).

    uvicorn services.api.main:app --host 0.0.0.0 --port 8000

The rule that shapes this file: **hiding a button is not access control.** Each read below takes
the caller's Scope and puts it in the SQL, so a Transport viewer who types the URL of a Police
camera gets an empty list, not a rendering quirk. Postgres row-level security sits behind that
as a backstop for the query somebody forgets to scope.

Live views are audited as well as writes. In a surveillance system the abuse worth catching is
reading - an officer looking up an ex-partner's vehicle leaves no other trace.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, FastAPI, HTTPException, Query           # noqa: E402

import audit as audit_module                                          # noqa: E402
import auth as auth_module                                            # noqa: E402
import grants as grants_module                                        # noqa: E402
import ws as ws_module                                                # noqa: E402
from alerts import AlertRepo, IllegalTransition                       # noqa: E402
from scope import DEPARTMENT_PREDICATE                                # noqa: E402
from store import Store                                               # noqa: E402
from watchlist import ImportRejected, WatchlistRepo, validate_row     # noqa: E402

log = logging.getLogger("api")

CAMERAS_SQL = f"""
SELECT camera_id, name, district_code, owner_dept_id, install_type, lat, lon,
       coord_source, coord_conf, bearing_deg, fov_deg, range_m, transports,
       transport_in_use, driver, health, health_at
FROM cameras
WHERE {DEPARTMENT_PREDICATE}
ORDER BY camera_id
"""


class CameraRepo:
    """Cameras, scoped. The only place [C10]'s "own dept" is turned into rows."""

    def __init__(self, store):
        self.store = store

    def list(self, scope=None):
        params = (scope.department_filter() if scope is not None
                  else {"all_departments": True, "departments": []})
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute(CAMERAS_SQL, params)
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def build_router(store):
    from fastapi import APIRouter

    router = APIRouter(prefix="/api")
    cameras = CameraRepo(store)
    grant_repo = grants_module.GrantRepo(store)
    watchlist = WatchlistRepo(store)
    alerts = AlertRepo(store)
    requires = auth_module.requires

    @router.get("/cameras")
    def list_cameras(scope=Depends(requires("live"))):
        # A live grant widens which departments this read covers, and is named in the audit row:
        # access that widens without leaving a trail is what D9 exists to prevent.
        widened, active = grants_module.widen(scope, grant_repo)
        rows = cameras.list(scope=widened)
        for grant in active or [None]:
            audit_module.record(store, user_id=scope.user_id, dept_id=scope.dept_id,
                                action="camera.list", object_type="camera",
                                object_id=f"{len(rows)} row(s)",
                                grant_id=grant["id"] if grant else None,
                                reason=f"case {grant['case_no']}" if grant else None)
        return rows

    @router.get("/watchlist")
    def list_watchlist(scope=Depends(requires("watchlist:read"))):
        return watchlist.list(scope=scope)

    @router.post("/watchlist")
    def add_watchlist(entry: dict, scope=Depends(requires("watchlist:write"))):
        try:
            parsed = validate_row(entry)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        entry_id = watchlist.add(parsed, added_by=_as_int(scope.user_id),
                                 owner_dept_id=scope.dept_id)
        audit_module.record(store, user_id=scope.user_id, dept_id=scope.dept_id,
                            action="watchlist.add", object_type="watchlist",
                            object_id=entry_id, reason=parsed.reason)
        return {"id": entry_id}

    @router.post("/watchlist/import")
    def import_watchlist(payload: dict, scope=Depends(requires("watchlist:write"))):
        try:
            result = watchlist.import_csv(payload.get("csv", ""),
                                          added_by=_as_int(scope.user_id),
                                          owner_dept_id=scope.dept_id)
        except ImportRejected as exc:
            # [C4]: {added:n, errors:[{line,reason}]}. A rejected import is a 422 with the rows
            # named, never a 500 - the user has to know which lines to fix.
            raise HTTPException(status_code=422,
                                detail={"added": 0, "errors": exc.errors}) from exc
        return result

    @router.delete("/watchlist/{entry_id}")
    def delete_watchlist(entry_id: int, scope=Depends(requires("watchlist:write"))):
        removed = watchlist.delete(entry_id)
        if not removed:
            raise HTTPException(status_code=404, detail="no such entry")
        audit_module.record(store, user_id=scope.user_id, dept_id=scope.dept_id,
                            action="watchlist.delete", object_type="watchlist",
                            object_id=entry_id)
        return {"deleted": removed}

    @router.get("/alerts")
    def list_alerts(state: str = Query(None), limit: int = 100,
                    scope=Depends(requires("alerts:read"))):
        return alerts.list(state=state, limit=limit, scope=scope)

    @router.post("/alerts/{alert_id}/state")
    def set_alert_state(alert_id: int, body: dict,
                        scope=Depends(requires("alerts:write"))):
        try:
            return alerts.transition(alert_id, (body.get("to_state") or "").upper(),
                                     by_user=_as_int(scope.user_id), dept_id=scope.dept_id,
                                     reason=body.get("reason"))
        except IllegalTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/healthz")
    def healthz():
        return {"ok": True}

    return router


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def create_app(store=None):
    resolved = store or Store()
    app = ws_module.create_app(store=resolved)      # /ws, /api/route, /api/route/export
    app.include_router(auth_module.build_router(resolved))
    app.include_router(build_router(resolved))
    app.include_router(audit_module.build_router(resolved))
    app.include_router(grants_module.build_router(resolved))
    return app


app = None      # built lazily by uvicorn's factory or by the tests


def factory():
    global app
    app = create_app()
    return app
