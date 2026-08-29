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
| G5 infra compose + env + Makefile | 1 | 0 | WIP | | compose+env+Makefile+skeleton written; no Docker in this sandbox to confirm `make up` green -- needs a real run |
| G2 CameraSource + transport resolution | 2 | 1 | DONE | | frame path proven live: hls_pdt, 6 fps, 26-27/30 resolve |
| G3 health monitor | 2 | 1 | DONE | | live: LIVE 4.86fps -> DEGRADED +4s -> DOWN +16s |
| G6 coordinate ground truth | 1 | 1 | WIP | | tool + honest bootstrap done; **0/30 placed by a human** — that part is manual |
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
- `infra/docker-compose.yml` — postgres16+timescaledb+pgvector (`timescale/timescaledb-ha:pg16`), redis, minio, osrm (profile `full`, no Gujarat extract yet -- D6).
- `.env.example` — [C9] keys verbatim. `.gitignore` — `.env`, weights, video, crops per build rules. `requirements.txt` — full stack, shared root file.
- `Makefile` — `up` (compose up+ps), `down`, `seed` (db/schema.sql + load_registry.py, both lane D, not built yet), `check` (pytest).
- `services/gateway/source.py` — [C6] `CameraSource` protocol, `Frame`, `Health`, `TsSource`, backoff/watchdog constants.
- `services/gateway/probe.py` — `probe_rtsp` (socket+DESCRIBE), `probe_hls` (cookie-gated GET), `resolve_transport` → `TransportResult`, `publish` (the G→I seam), `reprobe_forever` (10 min).
- `services/gateway/sources/rtsp.py` — `RTSPSource`, PyAV `rtsp_transport=tcp`, backoff + stall watchdog. `sources/mediamtx.py` — `MediaMTXSource` (HLS), picks `hls_pdt` vs `server_receive` from the playlist.
- `services/gateway/selftest.py` — `--probe-all` transport table with per-camera reason; `--publish` writes Redis. `tests/test_g_probe.py` — 10 tests, no network.
- `services/gateway/wall.py` — `Wall`/`CameraFeed`: one puller thread per camera holding the stream open, **keyframes only** (~0.5 fps decode, not 30), latest JPEG cached in memory. `start`/`stop`/`state`/`jpeg`.
- `scripts/console_serve.py` — `/api/cameras`, `/api/wall`, `/api/wall/start|stop`, `/tile/<id>.jpg` (instant, from cache), `/grid/*` proxy.
- `web/console.html` — operator console: Map/Wall/Split, all 30 pins on one map (streets/satellite/dark), live wall with start-stop, search + district + status filters, detail panel, stale badges.
- `scripts/geo_bootstrap.py` — salvaged geocodes → [C8] `data/camera_geo.json`, honest confidence (nothing HIGH), `--report` lists what needs a human.
- `scripts/geo_serve.py` — serves the repo, proxies `/grid/*` past the Cloudflare gate, and `/snapshot/<id>.jpg` decodes one frame via PyAV (browser HLS does not work here).
- `web/geo_helper.html` — placement tool: camera list, OSM map, draggable pin, bearing dial, live frame, export. `web/vendor/` — leaflet + hls.js, salvaged.
- `services/gateway/health.py` — `classify` (pure), `HealthMonitor.evaluate` (one event per change), `expected_fps` (capped at worker sampling rate), `tick`/`read_fps`/`publish` over `camera:fps:<id>` → `camera.health`. `tests/test_g_health.py` — 22 tests, time injected.

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
- `[G]` `live.corp8.cloud` is intermittent — it 502'd for hours on 08-29 then came back. `probe_grid.py` falls back to `ingest.json.bootstrap` when it does; always re-run once it is up.
- `[ALL]` The grid is behind a **Cloudflare cookie gate**: first request 302s to `?cookieCheck=1` with a Set-Cookie, then serves. **HEAD answers 404, not 405** — a HEAD probe reports every live camera as down. Use a streamed GET through a cookie-carrying `requests.Session` and confirm the body starts with `#EXTM3U`. This cost a full 0/30-vs-27/30 wrong answer.
- `[G]` Port 8554 is filtered at the grid: dial it **once at the host**, not once per camera, or 30 full timeouts buy you one fact. RTSP is 0/30; HLS is the real path (27/30 as of 08-29).
- `[ALL]` **The burnt-in overlay names the camera AND its install type** — cam 1 reads `Chiman bhai Bridge CSITMS-32_PTZ2`. `install_type` is readable from a frame, not from the catalogue. `cameras.seed.json` currently says `FIX` for all 30 and **that is wrong**; G6 fixes it per camera. Matters to lane I: a PTZ moves, so no static ROI is ever valid on it.
- `[ALL]` **The footage is looped recordings, not live.** Cam 1's overlay reads `13-06-2026 23:10` while the wall clock is 29-08-2026 midday, and the scene is night. So three clocks disagree: burnt-in scene time (June, fictional "now"), HLS PDT (real wall clock), and stream pts (relative, resets on loop). Sightings will be stamped with PDT while the video shows June at night — fine for a demo, but say it out loud rather than let a judge notice it.
- `[G]` A wall cannot open a stream per request (2-18 s each). Hold streams open in worker threads and **decode keyframes only** — HLS segments here are ~2 s with a keyframe at the head, so it is ~0.5 fps of decode per camera instead of 30, and 27 cameras run on a laptop.
- `[G]` **Frame age must be on screen.** Pullers routinely sit 60-270 s behind on some cameras while still reporting `live`; showing that as a live wall is a lie a judge will catch. The console badges anything over 90 s as `stale`, greys it and colours the age.
- `[G]` Leaflet's fade animation can leave tiles at `opacity:0` forever after a `fitBounds` during load — they report `leaflet-tile-loaded` and never paint, giving a black map with pins floating on it. Use `fadeAnimation:false`.
- `[G]` **Browser-side HLS does not work against this grid.** The Cloudflare cookie is `SameSite=None; Secure; Partitioned` with `ACAO:*`; a cross-origin page cannot use it (credentials need an echoed origin, not `*`), so `fetch`/hls.js fail with a bare "Failed to fetch". Proxy it same-origin (`scripts/geo_serve.py`). Even proxied, the vendored hls.js never paints a frame — these are low-latency fMP4 (`EXT-X-PART-INF`, `EXT-X-MAP`). **G11's video wall will hit this**; server-side snapshots (PyAV, which decodes them fine) are the reliable path.
- `[G]` Reachability is **26–27 of 30, and varies between consecutive runs** — 17/18/22 are reliably dead (hls 500 / ReadTimeout), others flap. Not a probe bug. Never quote a single run's number as if it were fixed; the deck should say "26–27 of 30" or re-measure at demo time.
- `[ALL]` **`EXT-X-PROGRAM-DATE-TIME` is on the VARIANT playlist, not the master.** Checking only the master (`index.m3u8`) returns False and labels every frame `server_receive`, throwing away the one real capture clock the grid gives us. Follow master → first non-comment line → variant. Confirmed present on cams 1/5/23; `ts_source=hls_pdt` after the fix.
- `[G]` PyAV ≥ 9 has **no `av.AVError`** — the base class is `av.FFmpegError`. Catching the old name raises `AttributeError` the first time a stream drops.
- `[G]` `frame.to_ndarray()` imports numpy **lazily**, so a missing numpy looks like a dead camera, not an ImportError: the stream opens, decodes, then throws per frame. Never wrap a driver's frame loop in `except Exception` — use `STREAM_ERRORS` (`services/gateway/source.py`) so a bug surfaces instead of masquerading as DOWN. Cost an hour of wrong hypotheses.
- `[G]` `frames()` reconnects **forever** by design, so any caller needs its own bound (`asyncio.wait_for`). A timeout placed inside the `async for` body never fires when zero frames arrive — which is exactly the case you are timing out for. Matters for G3.
- `[G]` **Never `asyncio.to_thread(container.close)`.** Closing a PyAV container on a worker thread while the demux iterator is alive on the loop thread **segfaults (139) or aborts (134)** — no traceback, no catchable exception, the process just dies. Close synchronously and null the reference first. Stopping early? `await gen.aclose()` *before* `source.close()`. Do not "fix" this with `try/finally: await self.close()` inside the generator — awaiting during `GeneratorExit` made it worse (that attempt turned a working exit 0 into SIGABRT).
- `[G]` **Measure fps from the first frame, not from connect.** HLS open latency on this grid ranged **1.6 s to 18 s for the same camera**, so a window started at connect time reports ~0 fps for a healthy stream. A naive measurement marks every camera DOWN.
- `[G]` Open latency up to ~18 s vs a 15 s DOWN threshold means a reconnecting camera can trip DOWN while it is merely connecting. G3 currently rides on `camera:fps:<id>` freshness so it does not hit this, but any future direct-decode path needs a CONNECTING state.
- `[G]` OSRM needs a preprocessed Gujarat extract (`osrm-extract` + `osrm-contract`) before `osrm-routed` can serve anything — put it behind compose profile `full` rather than crash-looping the default `make up`. D6 owns building the extract.
- `[G]` No Docker in this dev sandbox — `infra/docker-compose.yml` is YAML-validated but `make up` giving green containers is unverified. Whoever runs it first on a real laptop should update this line.
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
- 08-29 | G6 | scripts/geo_bootstrap.py, scripts/geo_serve.py, web/geo_helper.html, web/vendor/, data/camera_geo.json | tool works end to end (live frame + OSM map + pin + bearing). **Placement itself is manual and not started: 0/30 verified, 0 bearings.** Found: install_type is in the frame overlay (cam 1 is PTZ, seed says FIX for all 30 = wrong); footage is looped June recordings; browser HLS is impossible against this grid.
- 08-29 | G3 | services/gateway/health.py, tests/test_g_health.py, scripts/g3_health_check.py | live cam 1: **4.86 fps -> LIVE, +4s DEGRADED, +16s DOWN**, one event per change. Fixed a PyAV **segfault** on cross-thread container close, and an fps measurement that timed from connect (reported 0 fps for a healthy camera).
- 08-29 | G2 | services/gateway/*, scripts/g2_frame_check.py, requirements.txt | **frame path proven on live cam 1**: 1920x1080 bgr24, 6.0 fps decoded, monotonic pts, health LIVE, `ts_source=hls_pdt`. Found+fixed: PDT lives on the variant playlist; `av.AVError` gone in PyAV≥9; missing numpy masked as a dead camera by a blanket except.
- 08-29 | G2 | services/gateway/{source,probe,selftest}.py, sources/{rtsp,mediamtx}.py, tests/test_g_probe.py | probe order RTSP→HLS live-verified: **27/30 resolve, all HLS, rtsp 0/30**; 17/18/22 dead both ways (hls 500/ReadTimeout). 10 tests green, no network needed.
- 08-29 | G5 | infra/docker-compose.yml, .env.example, .gitignore, requirements.txt, Makefile, repo skeleton | compose+env+Makefile written, YAML-validated; `make up` unverified, no Docker in this sandbox
- 08-29 | G1 | scripts/probe_grid.py, data/cameras.seed.json | grid came back up; HEAD-probe bug found (Cloudflare gate 404s HEAD) — fixed to streamed GET, reachability went 0/30 → **27/30 via HLS**, rtsp 0/30 (8554 filtered). SonarCloud SSRF/path findings fixed too.
- 08-29 | G1 | scripts/probe_grid.py, data/cameras.seed.json, data/catalogue/ingest.json.bootstrap | seed built and verified (`--check`); grid host was 502, used salvaged catalogue as bootstrap

### lane D
_(none)_

### setup
- 08-29 | lanes reassigned: inference→Neal006, edge+console→neevmodh, core→Priyanshu | TASK.md, knowledge_base.md, AGENTS.md | G→I seam became a Redis URL key, so the worker imports no gateway code
- 08-29 | tickets frozen, contracts C1–C10 published | TASK.md, CLAUDE.md, AGENTS.md, knowledge_base.md | 3 lanes × ~17 pt, no cross-lane ticket dependency except J1

## 7. Archived

_(compress oldest changelog lines here, one line per day, when the KB passes 300 lines)_
