# knowledge_base.md — living memory

Updated: 2026-09-02 · KB v2 · cap 300 lines (temporarily exceeded by the QA_testing three-way merge —
next person to touch this file should fold old changelog lines into `## 7. Archived`) · patched after
**every** completed task (`CLAUDE.md §3`)

## 0. Now

- 2026-09-02. **`QA_testing`** branch created locally: `main` + `lane/priyanshu` (D1–D10) +
  `lane/neevmodh` (G1–G11) + `lane/neal006` (I1–I12, J1 leg 1) merged for integration testing ahead
  of the wave-3 freeze. `priyanshu/platform` was left out — it is 4 commits behind main, never had a
  PR, and is superseded by `lane/priyanshu`.
- 2026-08-31. **7 days to submission (7 Sep)**. Lane D is complete: D1-D10 all DONE, in PR #37.
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
- Open PRs, none merged: **#37** lane D wave 1+2 (D1-D5, mergeable, one Sonar rating failing) ·
  **#40** lane G wave 0+1 (G1, G5, G2, G3; CHANGES_REQUESTED, two Sonar ratings failing) ·
  **#41** lane I end-to-end (I1-I12, J1; merge-conflicting against `main`, two Sonar ratings failing).
  The merge queue is the bottleneck, not the code.
- First green light is in: `python -m services.worker.selftest --assert-xadd` replays a clip with a
  known plate and lands a CONFIRMED [C1] row on `sightings` 0.43 s after the pass. Against a live
  grid camera it is the same command with `--source rtsp://...`; lane I is no longer waiting on anyone.

## 1. Ticket board

State: `TODO` → `WIP` → `DONE` | `BLOCKED`. Flip your own cell only. Full ticket text: `grep -A 22 '^### I3' TASK.md`.

### Lane I — INFERENCE — Neal006 (17 pt)

| id | pt | wave | state | commit | note |
|---|---|---|---|---|---|
| I5 common/plate.py + vectors | 1 | 0 | DONE | bac680d | grammar slots fixed in a2f6b13 - see Decisions |
| I1 decode 5fps + motion gate | 2 | 1 | DONE | 2992e16 | 10 cams @5.02fps, 0 drops, 10 min |
| I2 backend + detector + batching | 2 | 1 | DONE | b2ccc28 | 193 fps batched on a 3050, bar was 150 |
| I3 ByteTrack + sighting builder | 2 | 1 | DONE | ed8df18 | one tracker per camera, 17 tests |
| I4 plate detect + OCR + grammar + vote | 3 | 2 | DONE | c4dd0fe | easyocr + paddleocr, 0 confident-wrong |
| I6 publish Redis + MinIO + metrics | 2 | 2 | DONE | 242d99a | row validated against [C1] on every publish |
| I8 worker selftest + replay harness | 1 | 2 | DONE | d8c90d2 | one command, 0.43 s to the stream |
| I7 golden set + accuracy report | 2 | 3 | WIP | 934c6b3 | report green on synthetic; hand labels pending clips |
| I9 deck, 10 slides | 2 | 3 | WIP | 3b4e4b5 | outline done; numbers land after the final runs |
| I10 Re-ID | 2 | P1 | DONE | ce9c3cb | ResNet-18 trunk; OSNet is a weights path |
| I11 fine-tune + TensorRT | 3 | P1 | WIP | 4fb493a | export + parity green; fine-tune needs a dataset |
| I12 bonus analytics | 2 | P1 | DONE | 12dacf2 | crowd, stopped, wrong-way, loitering |

### Lane G — EDGE + CONSOLE — neevmodh (18 pt)

| id | pt | wave | state | commit | note |
|---|---|---|---|---|---|
| G1 grid recon + cameras.seed.json | 1 | 0 | DONE | 697edc5 | grid returned 502, seed built from salvaged catalogue |
| G5 infra compose + env + Makefile | 1 | 0 | DONE | 8231618 | `make up` verified: all 3 containers healthy (neevmodh, 2026-09-01) |
| G2 CameraSource + transport resolution | 2 | 1 | DONE | 8231618 | probe+drivers done, 27/30 resolve to HLS; all SonarCloud issues fixed |
| G3 health monitor | 2 | 1 | DONE | 8231618 | sole producer of `camera.health`; selftest + health tests green |
| G6 coordinate ground truth | 1 | 1 | DONE | d501d49 | geo_helper.html placement tool + geo_bootstrap.py |
| G7 map layers 1–2 + API fixtures | 2 | 1 | DONE | d501d49 | fixtures/api/*.json + web/map.js + web/index.html |
| G8 wedges + bearing editor | 2 | 2 | DONE | d501d49 | web/wedges.js — L.marker+DivIcon drag (fixed Copilot review) |
| G9 events layer + slider + WS client | 2 | 2 | DONE | d501d49 | web/events.js + web/ws.js |
| G10 route view | 2 | 2 | DONE | d501d49 | web/route.js — numbered pins, PROBABLE, IMPLAUSIBLE, CSV |
| G11 video wall + admin drivers page | 2 | 2 | DONE | d501d49 | web/wall.js + web/admin.js |
| G4 ONVIF + VMS stub | 1 | 3 | DONE | d501d49 | interface complete; awaiting vendor credentials |
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
| D7 RBAC + audit | 3 | 3 | DONE | | scope test green, runs in GitHub Actions |
| D8 HLD document | 2 | 3 | DONE | | docs/hld.md, 13 sections, gaps named |
| D9 cross-department grants | 2 | P1 | DONE | | case number, 72 h cap, target-dept approval, logged |
| D10 audit hash-chain verify | 1 | P1 | DONE | | GET /api/admin/audit/verify, tamper test green |

### Joint

| id | pt | when | state | note |
|---|---|---|---|---|
| J1 integration + chaos + rehearsals + submission | 2 | after 5 Sep freeze | WIP | 5c73577 - leg 1 (worker to `sightings`) green; legs 2-3 skip until D's API is up |

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
  `weighted_levenshtein`; one table `CLASSES` drives `DIGIT_TO_ALPHA`, `ALPHA_TO_DIGIT` and the sub cost.
- `tests/test_i_plate.py` — I5's verify — the C7 vectors verbatim, plus null passthrough,
  canon idempotency, 1–3 letter series lengths, BH series, malformed-length passthrough, and the
  slot-fix regression set (only the wrong *kind* of character converts).
- `services/worker/decode.py` — [I1] camera → PTS-carrying frames — `Frame` `decode`
  `read_frames` `resolve_source` (the [C2] G→I seam) `publish_fps` `moved` `thumbnail` `scale`
  `bench` `synth_clip` `_floor_band`. PyAV, not an ffmpeg rawvideo pipe — see Decisions.
- `services/worker/queues.py` — [I1] bounded per-camera frame queues, depth 2, drop-oldest —
  `FrameQueue` (`put` never blocks, returns True when it displaced) `.stats()` for I6/metrics.
- `tests/test_i_decode.py` — I1's unit check, 22 tests — queue drop accounting, motion gate
  thresholds, `scale=960:-2` geometry, and the memory verdict's leak sensitivity. No ffmpeg.
- `services/worker/backend.py` — [I2] the [C6] seam — `InferenceBackend` `LocalBackend` (`detect`
  `plates` `ocr_all` `reid`) `Batcher` (16/20 ms) `Detection` `Reading` `CLASSES` `COCO_TO_CLASS`
  `bench`. Weights are env paths; nothing else imports ultralytics.
- `services/worker/tracker.py` — [I3] one ByteTrack per camera — `Trackers` (the only
  constructor) `CameraTracker` `Track` `_Dets`; `BUFFER_FRAME_RATE` explains the 30 vs 5 fps trap.
- `services/worker/sighting.py` — [I3] tracks -> [C1] rows — `SightingBuilder` (`observe` `tick`
  `flush` `epoch`) `Sighting` (`row` `wants_ocr` `claim_ocr`) `ulid` `sharpness` `colour_of`.
- `services/worker/plate.py` — [I4] localisation + readers — `propose` `candidates` `upscale`
  `read_all` `readers` `{EasyOCR,Paddle,Tesseract}Reader`. Vehicle crops only, never frames.
- `services/worker/vote.py` — [I4] the refusal — `PlateVote` (`add` `result` `band`) `VALID`;
  grammar before the vote, null `plate_text` below 2/3.
- `services/worker/publish.py` — [I6] the lane's only output — `Publisher` (`publish` `put_crop`
  `warm` `close`) `validate` `crop_key` `FIELDS`; buffers on Redis loss, circuit-breaks on MinIO.
- `services/worker/metrics.py` — [I6] `/metrics` — `serve` `timed` `record_queues`, counters
  `FRAMES_*` `INFERENCE` `SIGHTINGS` `OCR_VOTES` `ANALYTICS` `BUFFERED`.
- `services/worker/run.py` — the worker (`python -m services.worker.run`) — `Worker` (`run`
  `process` `warm` `stop`) `OcrPool` (OCR off the frame loop, bounded, per-sighting `drain`).
- `services/worker/selftest.py` — [I8] the one-command check — `run` (returns a report dict,
  used by J1) `main --assert-xadd --source --make-clip`.
- `services/worker/synth.py` — [I7]/[I8] known-plate fixtures — `render_plate` `stamp_plate`
  `frames` `make_clip` `crops` `vehicle_asset`. Salvaged from `4d0c945:simgrid/plate_render.py`.
- `services/worker/reid.py` — [I10] corroboration only — `Embedder` (512-d) `similarity`
  `corroborates` `descriptor` `pairs` `fit_projection`.
- `services/worker/analytics.py` — [I12] rules over track history — `Analytics` (`observe`)
  `Event` `expected_sign` `load_config`. Nothing here touches a sighting row.
- `scripts/accuracy_report.py` — [I7] the only source of accuracy numbers — `load` `score`
  `summarise` `cer` `make_synthetic`. Writes `docs/accuracy-report.md`.
- `scripts/export_trt.py` — [I11] `finetune` `export_onnx` `parity` `build_engine` `map_delta` ·
  `scripts/replay_clip.sh` — [I8] publish a clip to MediaMTX as an RTSP camera.
- `tests/test_i_{tracker,plate_vote,publish,analytics}.py` — 65 checks for I3/I4/I6/I12, no
  models, ~2 s total.
- `tests/test_integration.py` — [J1] cross-lane, gated on `PRAHARI_INTEGRATION=1`; skips a leg
  with its reason rather than passing vacuously.
- `models/README.md` · `fixtures/*/README.md` · `docs/*.md` — weights/config table, fixture
  formats, model card, deck outline, demo script, submission checklist.

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
- `services/api/scope.py` — [C10] in one table — `Scope`, `CAPABILITIES`, `DEPARTMENT_PREDICATE`, `apply_session_scope`.
- `services/api/auth.py` — argon2 + JWT (15 min / 8 h), login/refresh, bootstrap CLI — `UserRepo`, `issue_tokens`, `requires`.
- `services/api/audit.py` — the one hash chain — `append_audit`, `record`, `AuditLog.verify` (D10).
- `services/api/main.py` — every [C4] endpoint on one app — `create_app`, `CameraRepo`, scoped routers.
- `tests/test_d_scope.py` — D7's verify: Transport viewer sees only Transport, across cameras, watchlist and alerts.
- `.github/workflows/ci.yml` — pytest against timescaledb-ha + redis services on every push and PR.
- `services/api/grants.py` — bounded cross-department access — `GrantRepo`, `widen`, `MAX_DURATION`.
- `tests/test_d_grants.py` — request, approve, self-approval refused, expiry, the audited read.
- `docs/hld.md` — the mandatory HLD: integration, correlation, alerts, security, privacy, scale tiers, failure table.
- `requirements.txt` — one dependency per line, three lanes append to it (merged as a grouped union for `QA_testing`).

## 3. Gotchas

- `[ALL]` RTSP must be forced over TCP — UDP dies across NAT/firewall. Port 8554 is blocked on our
  network, so the gateway probes and degrades to HLS per camera.
- `[ALL]` Timestamps come from frame PTS, never `now()`. Clock drift across hosts reorders a route —
  chrony on every machine.
- `[ALL]` The grid is behind a **Cloudflare cookie gate**: first request 302s to `?cookieCheck=1` with a Set-Cookie, then serves. **HEAD answers 404, not 405** — a HEAD probe reports every live camera as down. Use a streamed GET through a cookie-carrying `requests.Session` and confirm the body starts with `#EXTM3U`. This cost a full 0/30-vs-27/30 wrong answer.
- `[ALL]` SonarCloud findings are readable without a SonarCloud login:
  `gh api repos/OWNER/REPO/commits/<sha>/check-runs` for the id, then
  `gh api repos/OWNER/REPO/check-runs/<id>/annotations`. The web UI 404s on a private project
  unless you are signed in, and the PR comment only prints the ratings. Cost: 40 minutes.
- `[ALL]` A Security Hotspot cannot be cleared from code - somebody marks it reviewed in the
  SonarCloud UI. Chasing one with code changes is wasted time.
- `[ALL]` `gh` is authed as Neal006 with scopes `gist, read:org, repo, workflow` — **no `project` scope**.
  Projects v2 needs `gh auth refresh -s project` (interactive, browser).
- `[I]` Grid feeds loop: scene discontinuities and inter-frame gaps are normal, not bugs. Mixed H.264/H.265.
- `[I]` One ByteTrack instance per camera, kept alive across frames. A fresh instance per frame resets IDs.
- `[I]` A single RSS sample is worthless as a leak signal: it lands at a random point in the
  decode cycle (±100 MB of transient frame buffers) and Windows trims the working set on top,
  so one sample landed *below* the process baseline. Least squares over raw samples called the
  same code +112 MB/min (60 s run) and +7.8 MB/min (600 s run). Use per-window floors, and drop
  the first 2–3 min — ten decoders take that long to allocate their pools.
- `[I]` To tell a leak from allocator noise, change the work rate, not the run length: at 1.85×
  the frame rate (`--flat-out`) memory did not grow, so nothing leaks per frame.
- `[I]` H.264 decodes every frame even at `fps=5` output — 30 cameras × 25 fps ≈ 750 fps of decode, near
  the limit of one consumer-GPU NVDEC. Watch `nvidia-smi dmon` dec%; above 90% move cameras to CPU decode.
- `[I]` ultralytics scales `track_buffer` by `frame_rate/30`, so passing our real 5 fps turns a
  30-frame buffer into 5 frames (1 s). Pass `frame_rate=30` to keep the ticket's 30 frames.
- `[I]` ultralytics restarts its global track-id counter for every `BYTETracker` it builds, so a
  tracker constructed per frame does not churn ids upward - it collapses every vehicle to id 1.
- `[I]` PaddleOCR 3.7 needs `enable_mkldnn=False`; with oneDNN on it raises
  `ConvertPirAttribute2RuntimeAttribute` per crop and reads nothing while looking installed.
- `[I]` Two readers over one crop cost ~0.8 s - four frames at 5 fps. OCR must not run in the
  frame loop; inline it emptied the depth-2 queues and processed 2 frames of a 30-frame pass.
- `[I]` A file replay must be paced to its own PTS. Unpaced, decode hands the queues hundreds of
  frames a second and the drop-oldest rule discards nine in ten - the plate among them.
- `[I]` Load models before any latency measurement. A 20 s OCR engine load during the pass
  produced a NONE band for a plate the readers could read perfectly.
- `[I]` botocore against an unreachable MinIO cost 27 s per row (connect timeout x head, create,
  put). `Publisher.warm()` probes once at startup and a failed PUT opens a 60 s circuit.
- `[I]` A synthetic fixture's plate must be stamped inside the *detector's* box, not just inside
  the image - at 0.86 of the photo's height it lands on the pavement and the crop has no plate.
- `[G]` `live.corp8.cloud` is intermittent — it 502'd for hours on 08-29 then came back. `probe_grid.py` falls back to `ingest.json.bootstrap` when it does; always re-run once it is up.
- `[G]` Port 8554 is filtered at the grid: dial it **once at the host**, not once per camera, or 30 full timeouts buy you one fact. RTSP is 0/30; HLS is the real path (27/30 as of 08-29).
- `[G]` Cameras **17, 18, 22** are dead on both transports (hls HTTP 500 / ReadTimeout), not a probe bug — same three across G1 and G2 runs. Expect 27, not 30, and say so rather than quietly showing 30 pins.
- `[G]` HLS carries no PTS worth trusting unless the playlist has `EXT-X-PROGRAM-DATE-TIME`; `MediaMTXSource` reads the playlist once at open and labels frames `hls_pdt` or `server_receive` accordingly. A `server_receive` row is **not** a capture time — the UI must show it as approximate.
- `[G]` OSRM needs a preprocessed Gujarat extract (`osrm-extract` + `osrm-contract`) before `osrm-routed` can serve anything — put it behind compose profile `full` rather than crash-looping the default `make up`. D6 owns building the extract.
- `[G]` `make up` is now verified on real Docker (neevmodh, 09-01): sentinel-postgres, sentinel-redis,
  sentinel-minio all healthy. MinIO healthcheck fixed from `mc ready` to `curl /minio/health/live`.
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
- 2026-08-31 — audit rows hash `int(user_id)`, not the JWT's `sub` string. Postgres stores an
  integer; hashing the string made verify() report tampering on rows nobody touched.
- 2026-08-31 — RLS policies treat an unset `prahari.dept_ids` as a maintenance connection and
  allow the row, because the migration, the persister and the matcher connect without a user.
  The application predicate stays the primary control; RLS is the backstop for a query somebody
  forgets to scope. Marked `# ponytail:` in db/migrate.sql.
- 2026-08-31 — `services/api/main.py` exists although D7's file list stops at auth/scope/audit.
  The scope test has to go through HTTP with a real token, and that needs an app with the [C4]
  endpoints on it; D3 and D4 deliberately stopped at the repository layer.
- 2026-09-01 — I1 decodes through PyAV instead of the ticket's `-f rawvideo -pix_fmt bgr24
  pipe:1` ffmpeg pipe — a rawvideo pipe carries no timestamps, so PTS would have to be
  reconstructed as index/fps, which drifts silently on the grid's looping recordings. That is
  the exact number `ts_source` records in [C1]. `--hwaccel` keeps the CUDA half of that line.
- 2026-09-01 — I1's flat-memory verdict is a plateau **band** (peak-to-trough of per-window RSS
  floors over the median), budget 5% per 10 min, not a slope — a slope fit runs through the
  warm-up ramp and flaps between FLAT and DRIFTING on identical code. Catches ≥6 MB/min against
  2.2% of measured platform noise; re-measure in the compose stack at J1 for a tighter bound.
- 2026-09-02 — `grammar_fix` converts only the wrong *kind* of character (digit in a letter slot,
  letter in a digit slot), not every member of a confusion class. The old table rewrote a
  correctly read D into an O and an L into an I, which I7 caught as 13 of 66 tracks CONFIRMED and
  wrong. [C7]'s wording is unchanged - the implementation was wrong, not the contract - but
  `common/plate.py` is imported by D, so the behaviour change is called out in the PR.
- 2026-09-02 — `plate_text` needs a 2/3 per-character majority **and** at least two independent
  reads; CONFIRMED additionally needs a grammar-valid string and three. One reader's single
  opinion is a read, not a vote, and PROBABLE already exists for "named but not corroborated".
- 2026-09-02 — OCR runs on its own thread with a bounded queue rather than in the frame loop, and
  a closing sighting waits up to 2 s for its outstanding reads. Measured: inline OCR cost 28 of
  30 frames of a pass. The queue being full *is* the OCR budget.
- 2026-09-02 — Plate localisation is a classical blackhat/Sobel proposal until I11 trains a
  detector. No labelled data exists yet, and `PRAHARI_PLATE_WEIGHTS` swaps it without a code
  change. The whole vehicle crop is always the last candidate, because both readers ship their
  own text detector.
- 2026-09-02 — Re-id uses a torchvision ResNet-18 trunk (512-d, exactly [C3]'s width), not
  OSNet/VeRi-776: no permissively licensed checkpoint could be verified in this window.
  `PRAHARI_REID_WEIGHTS` takes a TorchScript module when one is vetted.
- 2026-09-02 — I12's analytics events stay off Redis. [C2] has no analytics stream and adding one
  is a contract change needing both other owners; they go to /metrics and the log instead.
- 2026-09-02 — The golden set ships synthetic (rendered plates on a real vehicle photo) until the
  grid clips are labelled. Every row is tagged `synthetic`, the report prints it separately and
  calls it an upper bound, and the deck quotes the hand-labelled split.
- 2026-09-02 — `QA_testing` unions `.gitignore` and `requirements.txt` across all three lanes
  instead of picking one branch's version — each lane had appended its own copy independently and
  all three sets of entries are needed together on the merged tree.

## 5. Contract changes

`YYYY-MM-DD — [Cx] what changed — who was told`. Nothing yet. Contracts in `TASK.md §C` are frozen;
changing one without a line here breaks somebody else's lane silently.

## 6. Changelog

`MM-DD | ticket | files | outcome` — newest at the top of **your own** lane's block.

### lane I
- 09-02 | J1 | tests/test_integration.py, docs/{demo-script,submission}.md | 4 legs, leg 1 green,
  the rest skip with their reason; chaos drills and the 8-minute script written down
- 09-02 | I9 | docs/deck-outline.md | 10 slides; every number is a marker naming its command
- 09-02 | I11 | scripts/export_trt.py | ONNX opset 17, rtol 1e-3 parity, mAP-drop gate; the
  fine-tune waits on a labelled dataset
- 09-02 | I12 | services/worker/analytics.py, tests/test_i_analytics.py | crowd/stopped/wrong-way/
  loitering in seconds not frames, 13 tests
- 09-02 | I10 | services/worker/reid.py | 512-d vectors; `corroborates()` returns a bool, so no
  path from here can make a CONFIRMED hop
- 09-02 | I7 | scripts/accuracy_report.py, fixtures/golden/, docs/model-card.md | fused vote
  98.5% exact, 100% of named tracks, 1.5% refused, CONFIRMED precision 100% (0 wrong) on 198
  synthetic crops; readers alone are 66.7% and 77.8% - the report found the grammar bug
- 09-02 | I8 | services/worker/{run,selftest,synth}.py, scripts/replay_clip.sh | known plate on
  the stream 0.43 s after the pass; OCR moved off the frame loop to get there
- 09-02 | I6 | services/worker/{publish,metrics}.py, tests/test_i_publish.py | [C1] validated on
  every publish, buffers through a Redis outage, circuit-breaks a dead MinIO
- 09-02 | I4 | services/worker/{plate,vote}.py, tests/test_i_plate_vote.py | 2/3 vote, 22 tests,
  zero confident-wrong by construction
- 09-02 | I3 | services/worker/{tracker,sighting}.py, tests/test_i_tracker.py | one tracker per
  camera, one sighting per pass, PTS-anchored timestamps, 17 tests
- 09-02 | I2 | services/worker/backend.py, models/README.md | 193 fps batched (bar 150), 3.0x the
  one-frame rate on an RTX 3050 Laptop
- 09-02 | I5 | common/plate.py, tests/test_i_plate.py | grammar slots convert only the wrong kind
  of character; 13 confident-wrong reads became 0

### lane G
- 09-01 | G5 | infra/docker-compose.yml | `make up` verified on real Docker: sentinel-postgres, sentinel-redis, sentinel-minio all healthy. MinIO healthcheck fixed from `mc ready` → `curl /minio/health/live`.
- 09-01 | G2–G11 | PR #40 final fixes | All Neal006 blocking issues + 5 Copilot issues + SonarCloud Security E + Reliability C resolved. 32 tests green. `allow_redirects` SSRF guard, thread-local sessions, `while not _closed` generators, `autocomplete` on inputs, `esc()` everywhere, `datetime.now(utc)`.
- 08-29 | G2 | services/gateway/{source,probe,selftest}.py, sources/{rtsp,mediamtx}.py, tests/test_g_probe.py | probe order RTSP→HLS live-verified: **27/30 resolve, all HLS, rtsp 0/30**; 17/18/22 dead both ways (hls 500/ReadTimeout). 10 tests green, no network needed.
- 08-29 | G5 | infra/docker-compose.yml, .env.example, .gitignore, requirements.txt, Makefile, repo skeleton | compose+env+Makefile written, YAML-validated; `make up` unverified, no Docker in this sandbox
- 08-29 | G1 | scripts/probe_grid.py, data/cameras.seed.json | grid came back up; HEAD-probe bug found (Cloudflare gate 404s HEAD) — fixed to streamed GET, reachability went 0/30 → **27/30 via HLS**, rtsp 0/30 (8554 filtered). SonarCloud SSRF/path findings fixed too.
- 08-29 | G1 | scripts/probe_grid.py, data/cameras.seed.json, data/catalogue/ingest.json.bootstrap | seed built and verified (`--check`); grid host was 502, used salvaged catalogue as bootstrap

### lane D
- 08-29 | D1 | db/schema.sql, db/migrate.sql, scripts/load_registry.py, tests/test_d_{schema,registry}.py | schema applies twice with no errors on a throwaway timescaledb-ha:pg16; loader upserts 3 fixture cameras, and a missing camera_geo.json no longer wipes stored coordinates
- 08-29 | D3 | services/api/watchlist.py, services/api/feeds.py, tests/test_d_watchlist.py | all-or-nothing CSV import reports both bad rows by line number and writes nothing; VAHAN and e-GujCop stubs carry request/response shapes and label every row STUB
- 08-29 | D2 | scripts/fake_sightings.py, services/api/{store,persister}.py, tests/test_d_{generator,persister}.py | 14991 rows at 49.5/s for 5 min, pending stayed 0; redelivery, poisoned message and dead-consumer reclaim covered by tests

### setup
- 08-29 | lanes reassigned: inference→Neal006, edge+console→neevmodh, core→Priyanshu | TASK.md, knowledge_base.md, AGENTS.md | G→I seam became a Redis URL key, so the worker imports no gateway code
- 08-29 | tickets frozen, contracts C1–C10 published | TASK.md, CLAUDE.md, AGENTS.md, knowledge_base.md | 3 lanes × ~17 pt, no cross-lane ticket dependency except J1

## 7. Archived

_(compress oldest changelog lines here, one line per day, when the KB passes 300 lines)_

- 08-29 | lane I | I5 `common/plate.py` + 23 tests; D's `plate_compat.py` flipped to the real one
- 09-01 | lane I | I1 decode: 10 cams x 5.02 fps for 10 min, 0 drops, memory band 1.5%
