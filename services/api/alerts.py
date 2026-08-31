"""Alerts: creation with dedup, the state machine, and the audit row every transition leaves.

An alert is a claim that a watched vehicle was just seen. Two things about it are load-bearing:

  * it is deduplicated per (watchlist entry, camera) for 60 s. A car waiting at a signal is
    seen on twenty frames; twenty alerts for one event is how an operator learns to ignore the
    panel. The repeat increments `count` instead.
  * its state only moves one way: NEW -> ACKNOWLEDGED -> ACTIONED | DISMISSED. An illegal jump
    is a 409, not a silent write, because "who dismissed this and when" is the question asked
    after an incident, and a state that can be set arbitrarily cannot answer it. DISMISSED
    additionally requires a reason - dismissing without one is the failure mode that makes an
    audit log worthless.

Every transition writes an alert_events row and an audit_log row. The audit hash chain is
started here (each row hashes the previous row's hash); D10 walks it to find a broken link and
D7 puts the real user identity behind it.
"""

import hashlib
import json
import logging

log = logging.getLogger(__name__)

NEW, ACKNOWLEDGED, ACTIONED, DISMISSED = "NEW", "ACKNOWLEDGED", "ACTIONED", "DISMISSED"

# The whole machine. Anything not in here is a 409.
TRANSITIONS = {
    NEW: {ACKNOWLEDGED},
    ACKNOWLEDGED: {ACTIONED, DISMISSED},
    ACTIONED: set(),
    DISMISSED: set(),
}

DEDUP_TTL = 60                      # seconds, per [D2]/[D4]
ALERT_STREAM = "alerts"             # [C2]: D produces, D's ws-fanout consumes


class IllegalTransition(Exception):
    """409. Carries the two states so the API can say what it refused and why."""

    def __init__(self, from_state, to_state, detail=None):
        self.from_state = from_state
        self.to_state = to_state
        self.status_code = 409
        super().__init__(detail or f"{from_state} -> {to_state} is not a legal transition")


def next_states(state):
    return sorted(TRANSITIONS.get(state, set()))


class AlertRepo:
    def __init__(self, store):
        self.store = store

    # -- audit ---------------------------------------------------------------------------

    def _write_audit(self, cur, *, user_id, dept_id, action, object_type, object_id,
                     reason=None, ip=None, grant_id=None):
        """Append one link to the audit chain. Returns the new hash.

        The chain is what makes the log tamper-evident: changing a row means recomputing every
        hash after it, and D10's verify walks the chain to find the first link that does not.
        """
        cur.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
        prev_hash = row[0] if row else None
        payload = json.dumps({
            "user_id": user_id, "dept_id": dept_id, "action": action,
            "object_type": object_type, "object_id": str(object_id), "reason": reason,
        }, sort_keys=True).encode()
        digest = hashlib.sha256((bytes(prev_hash) if prev_hash else b"") + payload).digest()
        cur.execute(
            """INSERT INTO audit_log (user_id, dept_id, action, object_type, object_id, ip,
                                      reason, grant_id, prev_hash, hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (user_id, dept_id, action, object_type, str(object_id), ip, reason, grant_id,
             prev_hash, digest))
        return digest

    # -- creation ------------------------------------------------------------------------

    def raise_alert(self, *, watchlist_id, sighting, band, user_id=None, dept_id=None):
        """Create an alert, or bump the count of the live one for this entry and camera.

        Returns (alert_id, created). created is False when it was a duplicate inside the
        60 s window - the caller uses that to decide whether to push to the console.
        """
        camera_id = sighting["camera_id"]
        key = f"alert:dedup:{watchlist_id}:{camera_id}"
        fresh = self.store.redis.set(key, "1", nx=True, ex=DEDUP_TTL)

        with self.store.conn as conn, conn.cursor() as cur:
            if not fresh:
                cur.execute(
                    """UPDATE alerts SET count = count + 1
                       WHERE id = (SELECT id FROM alerts
                                   WHERE watchlist_id = %s AND camera_id = %s
                                   ORDER BY created_at DESC LIMIT 1)
                       RETURNING id, count""",
                    (watchlist_id, camera_id))
                bumped = cur.fetchone()
                if bumped:                       # the window is alive and so is the alert
                    return bumped[0], False
                # Key was set but the alert is gone (retention, or a manual delete). Fall
                # through and make a new one rather than dropping the sighting on the floor.

            cur.execute(
                """INSERT INTO alerts (watchlist_id, sighting_id, camera_id, pts, band, state)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (watchlist_id, sighting["sighting_id"], camera_id,
                 sighting["pts_first"], band, NEW))
            alert_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO alert_events (alert_id, from_state, to_state, by_user, reason)
                   VALUES (%s,%s,%s,%s,%s)""",
                (alert_id, None, NEW, user_id, "raised by matcher"))
            self._write_audit(cur, user_id=user_id, dept_id=dept_id, action="alert.raise",
                              object_type="alert", object_id=alert_id,
                              reason=f"{band} on {camera_id}")

        self._publish(alert_id, watchlist_id, sighting, band, NEW, 1)
        return alert_id, True

    def _publish(self, alert_id, watchlist_id, sighting, band, state, count):
        """[C2] `alerts` stream - what D5's fanout turns into an `alert.new` frame."""
        self.store.redis.xadd(ALERT_STREAM, {"data": json.dumps({
            "alert_id": alert_id, "watchlist_id": watchlist_id,
            "sighting_id": sighting["sighting_id"], "camera_id": sighting["camera_id"],
            "band": band, "state": state, "count": count, "pts": sighting["pts_first"],
        })})

    # -- state machine -------------------------------------------------------------------

    def get(self, alert_id):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, watchlist_id, sighting_id, camera_id, pts, band, state,
                                  count, created_at FROM alerts WHERE id = %s""", (alert_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return dict(zip([c.name for c in cur.description], row))

    def list(self, state=None, limit=100):
        clause, params = ("WHERE state = %s", [state]) if state else ("", [])
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute(f"""SELECT id, watchlist_id, sighting_id, camera_id, pts, band, state,
                                   count, created_at FROM alerts {clause}
                            ORDER BY created_at DESC LIMIT %s""", params + [limit])
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def transition(self, alert_id, to_state, *, by_user=None, dept_id=None, reason=None):
        """Move an alert, or raise IllegalTransition (409). Writes an event and an audit row."""
        if to_state == DISMISSED and not (reason or "").strip():
            raise IllegalTransition(None, to_state,
                                    "DISMISSED requires a reason - who dismissed it and why is "
                                    "the question asked after an incident")
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("SELECT state FROM alerts WHERE id = %s FOR UPDATE", (alert_id,))
            row = cur.fetchone()
            if row is None:
                raise IllegalTransition(None, to_state, f"alert {alert_id} does not exist")
            from_state = row[0]
            if to_state not in TRANSITIONS.get(from_state, set()):
                raise IllegalTransition(from_state, to_state)

            cur.execute("UPDATE alerts SET state = %s WHERE id = %s", (to_state, alert_id))
            cur.execute(
                """INSERT INTO alert_events (alert_id, from_state, to_state, by_user, reason)
                   VALUES (%s,%s,%s,%s,%s)""",
                (alert_id, from_state, to_state, by_user, reason))
            self._write_audit(cur, user_id=by_user, dept_id=dept_id,
                              action=f"alert.{to_state.lower()}", object_type="alert",
                              object_id=alert_id, reason=reason)
        return self.get(alert_id)

    def events(self, alert_id):
        with self.store.conn as conn, conn.cursor() as cur:
            cur.execute("""SELECT from_state, to_state, by_user, reason, at
                           FROM alert_events WHERE alert_id = %s ORDER BY id""", (alert_id,))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

