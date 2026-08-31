# knowledge_base.md — living memory

Updated: 2026-08-29 · KB v2 · cap 300 lines · patched after **every** completed task (`CLAUDE.md §3`)

## 0. Now

- 2026-08-29. **9 days to submission (7 Sep)**, 12 to the live event (10–11 Sep, i-Hub Gandhinagar).
- `main` holds docs only — commit `416ef26 "Restart"` wiped the tree. Working code from before is at
  `4d0c945` and on `origin/priyanshu/platform`; salvage with `git show`, do not rewrite (`TASK.md §4`).
- Wave 0 is today: G1 camera seed + G5 compose · D2's fake-sightings generator (**done**) · I5 `common/plate.py`.
  Lane D's wave 1 (D1, D2, D3) is done and in PR #37; it was built against throwaway
  timescaledb-ha and redis containers because G5's compose has not landed.
- Tickets are mirrored as GitHub issues `#1–#35` on `Priyanshu-byte-coder/prahari` (private repo, all
  three are collaborators). Title prefix is the ticket id — `[I3] …`, `[G7] …`, `[D5] …`. Bodies are
  generated from `TASK.md`, so **edit the ticket in `TASK.md`, not in the issue**.
  Filter your own work: `gh issue list --repo Priyanshu-byte-coder/prahari --assignee @me --label wave:1`
- Open PRs, none merged: **#37** lane D wave 1+2 (D1-D5) · **#38** I5 `common/plate.py` ·
  **#40** lane G wave 0+1 (G1, G5, G2, G3). The merge queue is the bottleneck, not the code.
- Nothing is running yet. First green light we want: a sighting row on Redis from a live grid camera.

## 1. Ticket board

State: `TODO` → `WIP` → `DONE` | `BLOCKED`. Flip your own cell only. Full ticket text: `grep -A 22 '^### I3' TASK.md`.

### Lane I — INFERENCE — Neal006 (17 pt)

| id | pt | wave | state | commit | note |
|---|---|---|---|---|---|
| I5 common/plate.py + vectors | 1 | 0 | DONE | bac680d | D's plate_compat auto-upgraded |
| I1 decode 5fps + motion gate | 2 | 1 | TODO | | URL or local clip — no gateway needed |
| I2 backend + detector + batching | 2 | 1 | TODO | | pretrained yolov8s |
| I3 ByteTrack + sighting builder | 2 | 1 | TODO | | |
| I4 plate detect + OCR + grammar + vote | 3 | 2 | TODO | | the hard one |
| I6 publish Redis + MinIO + metrics | 2 | 2 | TODO | | lane's only real output |
| I8 worker selftest + replay harness | 1 | 2 | TODO | | feeds J1 |
| I7 golden set + accuracy report | 2 | 3 | TODO | | deck numbers come from here |
| I9 deck, 10 slides | 2 | 3 | TODO | | |
| I10 Re-ID | 2 | P1 | TODO | | corroboration only |
| I11 fine-tune + TensorRT | 3 | P1 | TODO | | 8–9 Sep only |
| I12 bonus analytics | 2 | P1 | TODO | | crowd, wrong-way, loitering |

### Lane G — EDGE + CONSOLE — neevmodh (18 pt)

| id | pt | wave | state | commit | note |
|---|---|---|---|---|---|
| G1 grid recon + cameras.seed.json | 1 | 0 | TODO | | salvage `probe_grid.py` |
| G5 infra compose + env + Makefile | 1 | 0 | TODO | | other lanes need this today |
| G2 CameraSource + transport resolution | 2 | 1 | TODO | | publishes `camera:transport:<id>` |
| G3 health monitor | 2 | 1 | TODO | | sole producer of `camera.health` |
| G6 coordinate ground truth | 1 | 1 | TODO | | before any route UI |
| G7 map layers 1–2 + API fixtures | 2 | 1 | TODO | | fixtures first, they unblock the lane |
| G8 wedges + bearing editor | 2 | 2 | TODO | | |
| G9 events layer + slider + WS client | 2 | 2 | TODO | | |
| G10 route view | 2 | 2 | TODO | | the graded test case |
| G11 video wall + admin drivers page | 2 | 2 | TODO | | |
| G4 ONVIF + VMS stub | 1 | 3 | TODO | | hybrid bonus; drop to P1 if late |
| G12 Grafana dashboard | 2 | P1 | TODO | | |

### Lane D — CORE — Priyanshu-byte-coder (17 pt)

| id | pt | wave | state | commit | note |
|---|---|---|---|---|---|
| D1 schema + registry loader | 2 | 1 | DONE | | applies and re-applies clean on timescaledb-ha:pg16 |
| D2 fake_sightings + persister | 2 | 1 | DONE | | soak: 14991 rows at 49.5/s, pending stayed 0 |
| D3 watchlist + CSV + feed stubs | 2 | 1 | DONE | | repo + feeds; HTTP routes land with the app |
| D4 matcher bands + alert FSM | 2 | 2 | DONE | | band table + FSM green against I5 from PR #38 |
| D5 WebSocket fanout | 2 | 2 | DONE | | push, scope filtering and resume backfill tested |
| D6 route API + plausibility + export | 2 | 2 | TODO | | the graded test case |
| D7 RBAC + audit | 3 | 3 | TODO | | scope test must run in CI |
| D8 HLD document | 2 | 3 | TODO | | mandatory deliverable |
| D9 cross-department grants | 2 | P1 | TODO | | |
| D10 audit hash-chain verify | 1 | P1 | TODO | | |

### Joint

| id | pt | when | state | note |
|---|---|---|---|---|
| J1 integration + chaos + rehearsals + submission | 2 | after 5 Sep freeze | TODO | the only cross-lane ticket |

## 2. File map

`path` — purpose — key symbols. Add a line the moment you create a file; check here before opening anything.

### shared
- `TASK.md` — tickets, lane boundaries, frozen contracts C1–C10. Grep, never read whole.
- `CLAUDE.md` — read order, token rules, the KB update contract, ticket loop.
- `AGENTS.md` — stable spine: identity, stack, commands, ownership, conventions.
- `SENTINEL_HACKATHON.md` — scraped portal spec: deliverables, evaluation, grid endpoints, dates.
- `sentinel-e2e-implementation-plan.md` — 745-line design reference. Grep an anchor (`^### B3`), never read whole.

### lane I
- `common/plate.py` — [C7] plate strings, pure and None-safe — `normalise` `canon` `grammar_fix`
  `weighted_levenshtein`; one table `CLASSES` drives `TO_DIGIT`, `TO_ALPHA` and the sub cost.
- `tests/test_i_plate.py` — I5's verify — the C7 vectors verbatim, plus null passthrough,
  canon idempotency, 1–3 letter series lengths, BH series, malformed-length passthrough.

### lane G
_(nothing yet)_

### lane D
- `db/schema.sql` — [C3] verbatim, the copy a reviewer diffs against the contract — 9 tables, hypertable, 5 sighting indexes.
- `db/migrate.sql` — the file that actually runs: same objects, IF NOT EXISTS, named indexes, `if_not_exists => TRUE`.
- `scripts/load_registry.py` — joins `cameras.seed.json` + `camera_geo.json` into `cameras` — `read_json`, `build_rows`, `UPSERT`.
- `scripts/fake_sightings.py` — synthetic [C1] rows on the `sightings` stream — `ulid`, `sighting`, `route_schedule`, `ROUTE`.
- `tests/test_d_schema.py` — schema.sql vs migrate.sql drift, index and re-runnability checks.
- `tests/test_d_registry.py` — the seed/geo join, including every way lane G's two files disagree.
- `tests/test_d_generator.py` — [C1] field set, ULID ordering, route hop order and gaps.
- `common/plate_compat.py` — the single stand-in for I5 — `canon`, `normalise`, `is_valid_plate`, `USING_I5`. Delete when `common/plate.py` lands.
- `services/api/store.py` — Postgres + Redis access — `Store.insert_sightings`, `cache_recent`, `recent_sighting_ids`, `crop_url`.
- `services/api/persister.py` — consumer group `persister` — `Persister.run_once`, `reclaim`, `lag`, dead-letters to `sightings.dead`.
- `services/api/watchlist.py` — CRUD + all-or-nothing CSV import — `WatchlistRepo`, `validate_row`, `ImportRejected`.
- `services/api/feeds.py` — [C6] feeds — `ManualFeed`, `CSVFeed` live; `VahanFeed`, `EGujCopFeed` labelled STUB; `pull_all`.
- `tests/test_d_persister.py` — redelivery, poisoned message, dead-consumer reclaim. Needs a live Redis and Postgres.
- `tests/test_d_watchlist.py` — the D3 verify (2 bad rows, nothing written) plus the feed protocol checks.
- `services/api/alerts.py` — dedup, the NEW->ACK->ACTIONED|DISMISSED machine, audit chain — `AlertRepo`, `IllegalTransition`, `TRANSITIONS`.
- `services/api/matcher.py` — consumer group `matcher`, canon index + trigram fallback — `band_for`, `best_match`, `WatchlistIndex`, `Matcher`.
- `services/api/ws.py` — `/ws` fanout, scope at connect, resume backfill — `Hub`, `Scope`, `Subscriber`, `create_app`, `issue_token`.
- `tests/test_d_alerts.py` — the D4 band table and every illegal transition.
- `tests/test_d_ws.py` — push, scope filtering, resume, heartbeat, slow-console drop.
- `services/api/route.py` — [C4] `/api/route` + export — `RouteBuilder`, `collapse`, `flag_implausible`, `snap`, `haversine_km`.
- `services/api/export.py` — CSV and reportlab PDF, every export audited — `to_csv`, `to_pdf`, `render`, `record_export`.
- `tests/test_d_route.py` — five ordered hops with one flagged, fuzzy fallback, exports, HTTP surface.
- `requirements.txt` — one dependency per line, alphabetical, three lanes append to it.

## 3. Gotchas

- `[ALL]` RTSP must be forced over TCP — UDP dies across NAT/firewall. Port 8554 is blocked on our
  network, so the gateway probes and degrades to HLS per camera.
- `[ALL]` Timestamps come from frame PTS, never `now()`. Clock drift across hosts reorders a route —
  chrony on every machine.
- `[I]` Grid feeds loop: scene discontinuities and inter-frame gaps are normal, not bugs. Mixed H.264/H.265.
- `[I]` One ByteTrack instance per camera, kept alive across frames. A fresh instance per frame resets IDs.
- `[I]` H.264 decodes every frame even at `fps=5` output — 30 cameras × 25 fps ≈ 750 fps of decode, near
  the limit of one consumer-GPU NVDEC. Watch `nvidia-smi dmon` dec%; above 90% move cameras to CPU decode.
- `[G]` Read per-camera properties from `GET http://$GRID_HOST/api/ingest` before decoding.
- `[G]` A stalled RTSP connection does not error out — it just stops. You need a watchdog, not a try/except.
- `[G]` District-centroid coordinates make the demo car teleport. G6 before G10, no exceptions.
- `[G]` Judges' networks block WebRTC — the 3 s HLS fallback badge must be rehearsed on a phone hotspot.
- `[D]` Timescale hypertable must be created before any row is inserted into `sightings`.
- `[D]` MinIO only accepts SigV4. boto3 falls back to SigV2 when it cannot infer a region and
  signs a URL MinIO rejects — pass `Config(signature_version="s3v4")` and a `region_name`.
- `[D]` Ack after the commit, never before: Redis streams are at-least-once, so the replay is
  the normal path. `ON CONFLICT (pts_first, sighting_id) DO NOTHING` is what absorbs it.
- `[D]` A consumer that dies leaves its messages pending and invisible to `>` forever. XAUTOCLAIM
  on the idle path is the only thing that gets them back — J1's chaos drill tests exactly this.
- `[D]` Starlette's `TestClient` cannot test a server-pushed WebSocket frame: a client thread
  parked in `receive()` starves the app's own background task, so only heartbeats arrive. Run
  uvicorn in a thread on port 0 and connect with `websockets.sync.client` — see `serving()` in
  `tests/test_d_ws.py`. Cost: an hour.
- `[D]` A `@dataclass` in a `set()` needs `eq=False`, or it is unhashable and every subscribe
  raises `TypeError: unhashable type`.
- `[D]` pg_trgm `similarity()` on ten-character plates: one edit scores 0.57, two 0.47. A 0.7
  floor returns nothing — fine for D6's user-facing fuzzy search, dead code as D4's retrieval
  step. D4 retrieves at 0.4 and lets weighted_levenshtein decide.
- `[D]` `timescale/timescaledb-ha:pg16` already carries timescaledb, pgvector and pg_trgm, so
  `db/migrate.sql` runs on it unchanged — plain `postgres:16` needs all three installed by hand.
  Useful for G5: that image is the one lane D verified against.
- `[ALL]` `gh` is authed as Neal006 with scopes `gist, read:org, repo, workflow` — **no `project` scope**.
  Projects v2 needs `gh auth refresh -s project` (interactive, browser).

## 4. Decisions

- 2026-08-29 — Timeline follows the portal (submit 7 Sep, event 10–11 Sep), not the plan's §16 sprints
  (28 Sep) — the plan was written before the official dates were read back; §16 is obsolete.
- 2026-08-29 — Lanes are split at contract seams (stream URL, Redis stream, REST/WS, exchange files),
  not at pipeline stages — so no ticket ever waits on another person's ticket.
- 2026-08-29 — Neal006 owns inference, neevmodh owns gateway + console, Priyanshu-byte-coder owns core.
  The gateway/worker seam is `camera:transport:<id>` (a URL string in Redis), so the worker imports no
  gateway code and develops against a local clip.
- 2026-08-29 — `knowledge_base.md` is the auto-maintained memory; `AGENTS.md` is the stable spine —
  one fact one home, so nobody pays tokens to read the same thing twice.
- 2026-08-29 — Pretrained detectors for the submission; fine-tuning is I11, only in the 8–9 Sep window —
  a dataset + labelling + training loop does not fit in 9 days alongside the pipeline.
- 2026-08-29 — `canon()` collapses **every** confusion class including G→6, so `canon("GJ01AB1234")`
  is `6J01A81234` — plan §3.4's example contradicted §G2's rule; §G2 wins.
- 2026-08-29 — Re-ID corroboration (plan §B5, §G3 step 3) is out of P0. Route ships plate-keyed;
  PROBABLE dashed hops render only if I10 lands.
- 2026-08-29 — Salvage from `4d0c945` / `origin/priyanshu/platform` instead of rewriting — the gateway,
  worker, plate reader, geo file and vendored Leaflet all still exist in history.
- 2026-08-29 — Deck quotes the portal's ₹51 lakh prize pool, not the ₹37 lakh figure in press coverage.
- 2026-08-29 — `common/plate.py` is None-safe on every function, and `weighted_levenshtein`
  returns `inf` for a null operand — [C7] never says so, but D's persister feeds `plate_text`,
  which is null on ~13% of reads (I7). Raising there would crash the hot path on the expected case.
- 2026-08-29 — `tests/test_i_plate.py` carries its own `sys.path.insert(ROOT)` (lane D's existing
  pattern) instead of a repo-root `conftest.py` — repo root is on nobody's `sys.path`, and a shared
  root file would collide with PR #37 for no gain.
- 2026-08-29 — Ticket state lives in GitHub Project `prahari`
  (https://github.com/users/Priyanshu-byte-coder/projects/1), Status column set is
  Todo / In Progress / In QA Review / QA Review Failed / Done. A lane owner moves a ticket to
  In QA Review, never straight to Done; BhavyaSoneji and omvaghelaa own QA and are the only ones who
  move it to Done or QA Review Failed — so no lane grades its own work.

- 2026-08-31 — D4's band comes from [C7]'s weighted cost alone: 0 exact, 0.5 one confusion edit
  (PROBABLE), 1.0-2.0 anything else within two edits (POSSIBLE), above 2.0 no alert. A plain
  edit and two confusion edits both cost 1.0 and D4 calls both POSSIBLE, so the collision is
  harmless and no second distance function is needed.
- 2026-08-31 — an exact string match on a sighting whose own band is not CONFIRMED is raised as
  PROBABLE, never CONFIRMED. A POSSIBLE read that happens to spell a watched plate is exactly
  the case that must not put CONFIRMED in front of an officer.
- 2026-08-31 — D5 reads the Redis streams with XREAD, not the `ws-fanout` consumer group named
  in [C2]. A group splits messages between members, so with two API replicas half the alerts
  would reach half the consoles. Fanout is broadcast; every process reads the whole stream.
  Not a contract change — [C2] names the consumer, and D still owns both ends of it.
- 2026-08-31 — with `JWT_SECRET` unset, `ws.py` signs with a random per-process key rather than
  accepting unsigned tokens. Until D7 issues real ones, a dev run still works and a forged
  token still fails; "no secret configured" must never mean "open socket".

- 2026-08-31 — D6 renders the PDF with reportlab, not WeasyPrint as the ticket says. WeasyPrint
  needs GTK libraries on the machine; reportlab is a pure wheel, and the layout was salvageable
  from `origin/priyanshu/platform:services/api/route_report.py`.
- 2026-08-31 — the route PDF's picture is a schematic of the hop coordinates, not a basemap. There
  is no tile source we can ship offline, and calling an unreferenced polyline a map would be a lie
  on a document an officer signs.
- 2026-08-31 — `RouteResponse` carries an extra `snapped` boolean alongside [C4]'s
  `snapped_geometry`. Additive, so no consumer breaks, and without it a straight line between
  cameras is indistinguishable from a road path.

## 5. Contract changes

`YYYY-MM-DD — [Cx] what changed — who was told`. Nothing yet. Contracts in `TASK.md §C` are frozen;
changing one without a line here breaks somebody else's lane silently.

## 6. Changelog

`MM-DD | ticket | files | outcome` — newest at the top of **your own** lane's block.

### lane I
- 08-29 | I5 | common/plate.py, tests/test_i_plate.py | 23 tests green; D's `plate_compat.py`
  flipped `USING_I5` True on import, so its fallback half can be deleted

### lane G
_(none)_

### lane D
- 08-29 | D1 | db/schema.sql, db/migrate.sql, scripts/load_registry.py, tests/test_d_{schema,registry}.py | schema applies twice with no errors on a throwaway timescaledb-ha:pg16; loader upserts 3 fixture cameras, and a missing camera_geo.json no longer wipes stored coordinates
- 08-29 | D3 | services/api/watchlist.py, services/api/feeds.py, tests/test_d_watchlist.py | all-or-nothing CSV import reports both bad rows by line number and writes nothing; VAHAN and e-GujCop stubs carry request/response shapes and label every row STUB
- 08-29 | D2 | scripts/fake_sightings.py, services/api/{store,persister}.py, tests/test_d_{generator,persister}.py | 14991 rows at 49.5/s for 5 min, pending stayed 0; redelivery, poisoned message and dead-consumer reclaim covered by tests

### setup
- 08-29 | lanes reassigned: inference→Neal006, edge+console→neevmodh, core→Priyanshu | TASK.md, knowledge_base.md, AGENTS.md | G→I seam became a Redis URL key, so the worker imports no gateway code
- 08-29 | tickets frozen, contracts C1–C10 published | TASK.md, CLAUDE.md, AGENTS.md, knowledge_base.md | 3 lanes × ~17 pt, no cross-lane ticket dependency except J1

## 7. Archived

_(compress oldest changelog lines here, one line per day, when the KB passes 300 lines)_
