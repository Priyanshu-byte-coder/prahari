# API reference

Base URL `http://<host>:8000`. Every endpoint except `/api/healthz` and `/api/auth/*` needs
`Authorization: Bearer <access token>`.

The live OpenAPI schema is served at `/openapi.json` and the interactive form at `/docs` — this
page is the narrative version, and the column that matters is **who can call it**.

## Roles and capabilities

Five roles, one capability table (`services/api/scope.py`), read by the REST layer, the WebSocket
fanout and the SQL alike.

| Capability | VIEWER | OPERATOR | INVESTIGATOR | DEPT_ADMIN | SYSTEM_ADMIN |
|---|:--:|:--:|:--:|:--:|:--:|
| `live` (video, cameras) | ✅ | ✅ | ✅ | ✅ | ❌ |
| `detections` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `watchlist:read` | ❌ | ✅ | ✅ | ✅ | ❌ |
| `watchlist:write` | ❌ | ❌ | ✅ | ✅ | ❌ |
| `alerts:read` / `alerts:write` | ❌ | ✅ | ✅ | ✅ | ❌ |
| `route` | ❌ | ✅ | ✅ | ✅ | ❌ |
| `export` | ❌ | ❌ | ✅ | ✅ | ❌ |
| `admin:users` | ❌ | ❌ | ❌ | ✅ | ❌ |
| `admin:config` / `admin:audit` | ❌ | ❌ | ❌ | ❌ | ✅ |

**System Admin cannot view live video, detections or routes.** That is deliberate, and it is the
control most surveillance platforms do not have: the account that can change the system is not the
account that can watch people with it. Contract `C10`.

On top of the role, every read is confined to the caller's **department**, in the SQL rather than
after the fetch, with Postgres row-level security as a backstop.

---

## Authentication

### `POST /api/auth/login`

```json
{"username": "field", "password": "..."}
```
→ `{"access": "<15 min JWT>", "refresh": "<8 h JWT>", "role": "INVESTIGATOR"}`

Passwords are argon2id. Tokens carry a `typ` claim; a refresh token presented as an access token
is refused rather than silently accepted.

### `POST /api/auth/refresh`
`{"refresh": "<token>"}` → a new access token. `401` on anything else.

### Bootstrap a user (CLI, never over HTTP)

```bash
PRAHARI_BOOTSTRAP_PASSWORD=... python services/api/auth.py bootstrap \
  --username field --role INVESTIGATOR --dept-id 3
```

The password comes from the environment, never from `argv` — command lines end up in shell
history and in `ps`.

---

## Cameras

### `GET /api/cameras` — capability `live`
The caller's cameras, with coordinates, department, district, driver, transport and health. A
System Admin gets `403`, not an empty list: the distinction matters when debugging.

---

## Watchlist

### `GET /api/watchlist` — `watchlist:read`
### `POST /api/watchlist` — `watchlist:write`

```json
{"kind": "plate", "plate": "GJ01AB1234", "category": "stolen vehicle",
 "severity": "HIGH", "reason": "FIR 214/2026", "description": "white hatchback"}
```

`category` and `severity` are closed vocabularies; an unknown value is a `422` naming the allowed
set. Entries are stored with both a normalised and a **canonicalised** plate — the canonical form
collapses the character classes cameras confuse (`0 O D Q`, `1 I L`, `8 B`, `5 S`, `2 Z`), which
is what lets a single misread still match.

### `POST /api/watchlist/import` — `watchlist:write`

```json
{"csv": "kind,plate,category,severity,description,reason\nplate,GJ01AB1234,stolen vehicle,HIGH,,FIR 214/2026\n"}
```

**All or nothing.** One bad row rejects the file and returns every problem by line number:

```json
{"added": 0, "errors": [{"line": 4, "reason": "severity must be one of [...], got 'urgent'"}]}
```

A partial import is worse than a failed one — nobody can tell which half landed.

### `DELETE /api/watchlist/{entry_id}` — `watchlist:write`

---

## Alerts

### `GET /api/alerts?state=NEW&limit=100` — `alerts:read`

### `POST /api/alerts/{alert_id}/state` — `alerts:write`

```json
{"to_state": "ACKNOWLEDGED", "reason": "unit dispatched"}
```

The state machine is one-way:

```
NEW ──► ACKNOWLEDGED ──┬──► ACTIONED
                       └──► DISMISSED
```

`409` for an illegal transition, `422` for a body without `to_state`. Every transition writes an
audit row naming the officer. Alerts are deduplicated per watchlist entry per camera for 60
seconds, so a vehicle waiting at a signal raises one alert, not forty.

---

## Route — the judged test case

### `GET /api/route?plate=GJ01AB1234&from=<iso>&to=<iso>` — `route`

```json
{
  "plate": "GJ01AB1234",
  "from": "2026-09-03T07:00:00+05:30",
  "to":   "2026-09-04T07:00:00+05:30",
  "fuzzy": false,
  "note": null,
  "hops": [
    {"n": 1, "camera_id": "1", "name": "Chimanbhai Bridge",
     "lat": 23.02, "lon": 72.558,
     "pts": "2026-09-03T13:12:09+05:30",
     "band": "CONFIRMED", "kind": "CONFIRMED",
     "crop_url": "<presigned, expires>"}
  ],
  "snapped_geometry": {"type": "LineString", "coordinates": [], "snapped": true}
}
```

Behaviour worth knowing before you rely on it:

- Repeated sightings at one camera **collapse into one hop** — a vehicle parked in view is one
  event, not two hundred.
- A hop whose implied speed exceeds 150 km/h is returned with `kind: "IMPLAUSIBLE"`. **It is still
  returned.** Silently dropping it would hide the misread that produced it.
- No exact match retries against the canonical key and trigram similarity, and the response is
  marked `fuzzy: true` with `note: "fuzzy match; verify plate"`.
- `snapped: false` means OSRM was unreachable and the geometry is straight lines between cameras —
  a rendering fallback, and the flag says so rather than implying a road path.

### `GET /api/route/export?plate=...&fmt=csv|pdf` — `export`

Returns the file with a `Content-Disposition` attachment header. **Every export writes an audit
row** naming the caller, taken from the token — never from a parameter the caller controls. The
PDF carries a schematic of the hops, explicitly labelled *not a map*, so nobody mistakes the
diagram for surveyed geography.

---

## Grants — cross-department access

Access to another department's cameras is not a role, it is a **grant**.

### `POST /api/grants`
```json
{"target_dept_id": 4, "case_no": "FIR 214/2026", "reason": "vehicle crossed into Surat", "hours": 24}
```

Rules the code enforces, not conventions:

- A case number and a reason are **required** — access has to belong to a case.
- Approved only by an admin of the **target** department. Never self-approved.
- Maximum 72 hours; it expires on its own rather than needing revocation.
- Request, approval and expiry are all audited.

### `GET /api/grants` · `POST /api/grants/{id}/approve` · `POST /api/grants/{id}/deny`

---

## Audit

### `GET /api/admin/audit?since=&until=&limit=` — `admin:audit`
### `GET /api/admin/audit/verify` — `admin:audit`

```json
{"ok": true, "first_broken_seq": null, "checked": 221, "detail": null}
```

Each row carries `hash = sha256(prev_hash || canonical_json(fields))`. Editing or deleting a row
directly in the database breaks the chain, and `verify` reports the first sequence number where it
breaks. This is the answer to "how do we know the log wasn't edited" that does not require trusting
the operator.

---

## WebSocket — `GET /ws`

One socket per console. First frame from the client must be `{"token": "<access token>"}`; a
socket that sends anything else is **closed**, not left silently receiving nothing.

Server frames:

```json
{"type": "ready",         "seq": 41, "data": {"role": "INVESTIGATOR", "dept_id": 3}}
{"type": "alert.new",     "seq": 42, "data": {...}}
{"type": "camera.health", "seq": 43, "data": {...}}
{"type": "sighting",      "seq": 44, "data": {...}}
{"type": "ping"}
```

- **`seq` is monotonic and survives a reconnect.** Send `{"type": "resume", "since": 41}` and you
  get exactly what you missed, filtered through your scope again. Without that, a console that
  drops off station wifi comes back to a blank panel and cannot tell "nothing happened" from "I
  missed it".
- **The server filters, never the client.** A frame you may not see is never sent.
- **Heartbeat every 15 s**, because a dead TCP connection looks exactly like a quiet one, and quiet
  is the normal state of a camera grid at 3 a.m.
- A console too slow to drain its queue is **dropped, not waited for** — one bad link must not
  stall the fanout for everyone else.

---

## Errors

| Code | Meaning |
|---|---|
| `400` | malformed parameter (bad timestamp, unsupported export format) |
| `401` | missing, expired, forged or wrong-type token |
| `403` | authenticated, but the role lacks the capability |
| `409` | illegal state transition |
| `422` | valid syntax, invalid content — always names the field and the allowed values |
| `503` | a dependency is down; the body says which |

Error bodies are `{"detail": ...}`, and `detail` is written to be read by the person who has to fix
it.
