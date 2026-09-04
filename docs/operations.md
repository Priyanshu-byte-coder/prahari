# Operations

Run it, watch it, recover it. Written for the person holding the laptop at 09:00 on demo day.

## Ports

| Service | Port | Notes |
|---|---|---|
| API + WebSocket | 8000 | `uvicorn --factory services.api.main:factory` |
| Console | 5173 | `scripts/console_serve.py`, also proxies the API and the video wall |
| PostgreSQL + TimescaleDB | 5432 | override with `POSTGRES_PORT` |
| Redis | 6379 | override with `REDIS_PORT` |
| MinIO | 9000 | crops; presigned URLs |
| OSRM | 5000 | road snapping; optional, the route degrades to straight lines |
| Worker metrics | 9108 | Prometheus text format |

**A local PostgreSQL on 5432 answers before Docker's port proxy**, and auth then fails with the
compose credentials — which looks exactly like a password bug and is not one. Set `POSTGRES_PORT`
to something free.

## Start

```bash
make up            # postgres+timescale, redis, minio, osrm
make seed          # db/migrate.sql (re-runnable) + the camera registry
make run           # API, console, persister, matcher — four processes, one command
```

Every `make` target is a one-line wrapper. Without `make` installed:

```bash
docker compose -f infra/docker-compose.yml up -d
psql "$POSTGRES_DSN" -v ON_ERROR_STOP=1 -f db/migrate.sql && python scripts/load_registry.py
python scripts/run_stack.py start          # ... status | stop | restart
```

`run_stack.py start` polls until the API and console answer and prints which one did not come up,
so "it started" and "it works" are the same statement. For a demo, prefer separate terminals — a
crash is then visible rather than buried in a log.

## First-run checks, in order

Each of these has failed at least once, which is why it is on the list.

```bash
curl -s localhost:8000/api/healthz                      # {"ok":true}
curl -s localhost:5173/api/cameras | head -c 120        # 30 cameras, lat/lon present
curl -s localhost:5173/api/grid                         # {"state":"signed in"} if GRID_KEY is set
python services/worker/selftest.py                      # SELFTEST OK, plate read back, under budget
pytest tests/ -q                                        # 348 passed
```

Then, with a token:

```bash
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/admin/audit/verify
# {"ok": true, "first_broken_seq": null, ...}
```

## Credentials

Nothing in the repo. `.env.example` names every variable; `run_demo_env.sh` (gitignored) is the
local copy.

| Variable | What it is |
|---|---|
| `POSTGRES_DSN`, `REDIS_URL`, `MINIO_*` | infrastructure |
| `JWT_SECRET` | **must be ≥32 bytes.** Unset, the API invents a random per-process key and every token dies at restart |
| `GRID_EMAIL`, `GRID_KEY` | the camera grid sign-in — it needs **both**; the key alone returns "incorrect", which reads exactly like an expired key |
| `PRAHARI_CONSOLE_USER` / `_PASSWORD` | the account the console proxies live data as |
| `PRAHARI_CONSOLE_ADMIN_USER` / `_PASSWORD` | a second, SYSTEM_ADMIN account for the audit tab — one account cannot serve both halves of `C10` |

## Watching it

```bash
# is the pipeline moving?
redis-cli -u "$REDIS_URL" XLEN sightings
redis-cli -u "$REDIS_URL" XINFO GROUPS sightings     # `pending` should sit near zero

# did anything get dead-lettered?
redis-cli -u "$REDIS_URL" XLEN sightings.dead

# is anything landing?
psql "$POSTGRES_DSN" -c "SELECT count(*), max(pts_first) FROM sightings"
```

The persister logs a line every ten seconds: `N persisted (rate), P pending, R reclaimed,
D dead-lettered`. **Pending climbing is the number that matters** — it means the database is
slower than the stream, and everything downstream is now behind.

Worker metrics on `:9108`: frames decoded, detections, OCR latency histogram, publish failures.

---

## Failure playbook

### Console shows cameras but the map is empty
Coordinates are missing at the top level of `/api/cameras`. `web/map.js` filters on
`c.lat != null`; a camera whose coordinates are only nested under `geo` is silently dropped. Check
`data/camera_geo.json` loaded — `make seed` again.

### "0 placed" in the console header
Not a bug. That counter is *hand-verified* coordinates (`geo.verified === true`). Everything is
geocoded rather than surveyed; issue #17.

### Video wall tiles stay grey
```bash
curl -s localhost:5173/api/grid      # "no key" | "no email" | "rejected" | "signed in"
```
- `no email` / `no key` — set `GRID_EMAIL` **and** `GRID_KEY`. The sign-in form needs both.
- `rejected` — the grid did not accept them. Try them in a browser; if they work there and not
  here, the IP is throttled.
- `signed in` but tiles grey — the grid is refusing RTSP (401). The wall gives up on RTSP after two
  auth failures and stays on HLS, which is a **downscaled rendition** on most cameras. Fine for the
  wall, halves the plate pixels for ANPR.

### Sightings stop arriving
1. Is the worker alive? `:9108/metrics` — if frames are climbing but sightings are not, it is the
   feasibility gate or the motion gate, not a crash.
2. Is the persister alive? Its ten-second log line stops when it dies.
3. `XINFO GROUPS sightings` — a dead consumer leaves entries pending. The persister reclaims them
   with `XAUTOCLAIM` on its next pass; if it is dead too, nothing reclaims anything.

### Alerts fire but never reach the console
The socket, not the matcher. Check `alerts` stream length is climbing (`XLEN alerts`); if it is,
the fanout or the scope is the problem. **A frame the scope disallows is never sent** — an operator
in another department correctly sees nothing.

### `audit/verify` returns `ok: false`
The chain is broken from `first_broken_seq` onward. Someone edited or deleted a row directly in the
database. The rows before that sequence number are still trustworthy; the ones after cannot be
proven. Do not "fix" it by rewriting hashes — that is the thing the chain exists to prevent.

### Route returns nothing for a plate that is definitely there
- Wrong window: default is 24 h, pass `from`/`to`.
- Wrong department: the SQL confines to your scope, so another department's hops are absent by
  design. A cross-department grant is the intended path.
- Genuinely fuzzy: check `fuzzy: true` in the response — an exact match failed and the fallback
  found something *similar*, which is labelled rather than presented as fact.

### CI is red but it passes locally
Two known causes, both fixed but worth recognising again: an OpenCV version reporting
`minAreaRect` angles in the other convention, and tests that assert on the generator's demo plate
against a database that has demo rows in it. Both were test bugs, not product bugs — but check the
failure names against `knowledge_base.md` §3 before assuming a regression.

---

## Backup and recovery

```bash
pg_dump "$POSTGRES_DSN" -Fc -f prahari-$(date +%F).dump      # schema + sightings + audit
docker exec sentinel-minio mc mirror /data /backup/crops     # crops
```

Restore is `pg_restore` into a database that has had `db/migrate.sql` applied. The audit chain
survives a dump and restore — it is content-addressed, not row-id dependent.

Retention is enforced by policy, not by hand: sightings compress after 7 days and drop after 90.
Crops expire with their bucket lifecycle. **This is a deletion guarantee, not a storage
optimisation** — see the privacy section of `hld.md`.
