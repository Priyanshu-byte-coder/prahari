# knowledge_base.md — living memory

Updated: 2026-08-29 · KB v2 · cap 300 lines · patched after **every** completed task (`CLAUDE.md §3`)

## 0. Now

- 2026-08-29. **9 days to submission (7 Sep)**, 12 to the live event (10–11 Sep, i-Hub Gandhinagar).
- `main` holds docs only — commit `416ef26 "Restart"` wiped the tree. Working code from before is at
  `4d0c945` and on `origin/priyanshu/platform`; salvage with `git show`, do not rewrite (`TASK.md §4`).
- Wave 0 is today: G1 camera seed + G5 compose · D2's fake-sightings generator · I5 `common/plate.py`.
  After those land, no lane can block another.
- Tickets are mirrored as GitHub issues `#1–#35` on `Priyanshu-byte-coder/prahari` (private repo, all
  three are collaborators). Title prefix is the ticket id — `[I3] …`, `[G7] …`, `[D5] …`. Bodies are
  generated from `TASK.md`, so **edit the ticket in `TASK.md`, not in the issue**.
  Filter your own work: `gh issue list --repo Priyanshu-byte-coder/prahari --assignee @me --label wave:1`
- Nothing is running yet. First green light we want: a sighting row on Redis from a live grid camera.

## 1. Ticket board

State: `TODO` → `WIP` → `DONE` | `BLOCKED`. Flip your own cell only. Full ticket text: `grep -A 22 '^### I3' TASK.md`.

### Lane I — INFERENCE — Neal006 (17 pt)

| id | pt | wave | state | commit | note |
|---|---|---|---|---|---|
| I5 common/plate.py + vectors | 1 | 0 | TODO | | pure functions, D imports it |
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
| G1 grid recon + cameras.seed.json | 1 | 0 | DONE | 697edc5 | grid returned 502, seed built from salvaged catalogue |
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
| D1 schema + registry loader | 2 | 1 | TODO | | hypertable before first insert |
| D2 fake_sightings + persister | 2 | 1 | TODO | | generator first, unblocks the lane |
| D3 watchlist + CSV + feed stubs | 2 | 1 | TODO | | |
| D4 matcher bands + alert FSM | 2 | 2 | TODO | | imports I5, no second copy |
| D5 WebSocket fanout | 2 | 2 | TODO | | kills all polling |
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
_(nothing yet)_

### lane G
- `scripts/probe_grid.py` — hits grid `/api/ingest`, probes RTSP/HLS reachability per camera, writes `data/cameras.seed.json` [C8]; falls back to salvaged catalogue if the sandbox is down. `--check` prints count + reachability.
- `data/cameras.seed.json` — [C8] camera seed, 30 cameras, `district_code` best-effort from location text, `UNKNOWN` where ambiguous.
- `data/catalogue/ingest.json.bootstrap` — real 30-camera catalogue salvaged from `4d0c945` (host `live.corp8.cloud`), offline fallback source for probe_grid.py.

### lane D
_(nothing yet)_

## 3. Gotchas

- `[ALL]` RTSP must be forced over TCP — UDP dies across NAT/firewall. Port 8554 is blocked on our
  network, so the gateway probes and degrades to HLS per camera.
- `[ALL]` Timestamps come from frame PTS, never `now()`. Clock drift across hosts reorders a route —
  chrony on every machine.
- `[I]` Grid feeds loop: scene discontinuities and inter-frame gaps are normal, not bugs. Mixed H.264/H.265.
- `[I]` One ByteTrack instance per camera, kept alive across frames. A fresh instance per frame resets IDs.
- `[I]` H.264 decodes every frame even at `fps=5` output — 30 cameras × 25 fps ≈ 750 fps of decode, near
  the limit of one consumer-GPU NVDEC. Watch `nvidia-smi dmon` dec%; above 90% move cameras to CPU decode.
- `[G]` `live.corp8.cloud` (the sandbox host from the salvaged catalogue) returns HTTP 502 as of 08-29 — grid is likely only live during the event window. `probe_grid.py` falls back to `ingest.json.bootstrap` when it does; re-run for real once the grid is up.
- `[G]` Read per-camera properties from `GET http://$GRID_HOST/api/ingest` before decoding.
- `[G]` A stalled RTSP connection does not error out — it just stops. You need a watchdog, not a try/except.
- `[G]` District-centroid coordinates make the demo car teleport. G6 before G10, no exceptions.
- `[G]` Judges' networks block WebRTC — the 3 s HLS fallback badge must be rehearsed on a phone hotspot.
- `[D]` Timescale hypertable must be created before any row is inserted into `sightings`.
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
- 2026-08-29 — Ticket state lives in GitHub Project `prahari`
  (https://github.com/users/Priyanshu-byte-coder/projects/1), Status column set is
  Todo / In Progress / In QA Review / QA Review Failed / Done. A lane owner moves a ticket to
  In QA Review, never straight to Done; BhavyaSoneji and omvaghelaa own QA and are the only ones who
  move it to Done or QA Review Failed — so no lane grades its own work.

## 5. Contract changes

`YYYY-MM-DD — [Cx] what changed — who was told`. Nothing yet. Contracts in `TASK.md §C` are frozen;
changing one without a line here breaks somebody else's lane silently.

## 6. Changelog

`MM-DD | ticket | files | outcome` — newest at the top of **your own** lane's block.

### lane I
_(none)_

### lane G
- 08-29 | G1 | scripts/probe_grid.py, data/cameras.seed.json, data/catalogue/ingest.json.bootstrap | seed built and verified (`--check`); grid host was 502, used salvaged catalogue as bootstrap

### lane D
_(none)_

### setup
- 08-29 | lanes reassigned: inference→Neal006, edge+console→neevmodh, core→Priyanshu | TASK.md, knowledge_base.md, AGENTS.md | G→I seam became a Redis URL key, so the worker imports no gateway code
- 08-29 | tickets frozen, contracts C1–C10 published | TASK.md, CLAUDE.md, AGENTS.md, knowledge_base.md | 3 lanes × ~17 pt, no cross-lane ticket dependency except J1

## 7. Archived

_(compress oldest changelog lines here, one line per day, when the KB passes 300 lines)_
