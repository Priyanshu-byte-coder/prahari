# knowledge_base.md — living memory

Updated: 2026-09-01 · KB v2 · cap 300 lines · patched after **every** completed task (`CLAUDE.md §3`)

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
  `weighted_levenshtein`; one table `CLASSES` drives `TO_DIGIT`, `TO_ALPHA` and the sub cost.
- `tests/test_i_plate.py` — I5's verify — the C7 vectors verbatim, plus null passthrough,
  canon idempotency, 1–3 letter series lengths, BH series, malformed-length passthrough.
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
_(nothing yet)_

### lane D
_(nothing yet)_

## 3. Gotchas

- `[ALL]` RTSP must be forced over TCP — UDP dies across NAT/firewall. Port 8554 is blocked on our
  network, so the gateway probes and degrades to HLS per camera.
- `[ALL]` Timestamps come from frame PTS, never `now()`. Clock drift across hosts reorders a route —
  chrony on every machine.
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
_(none)_

### lane D
_(none)_

### setup
- 08-29 | lanes reassigned: inference→Neal006, edge+console→neevmodh, core→Priyanshu | TASK.md, knowledge_base.md, AGENTS.md | G→I seam became a Redis URL key, so the worker imports no gateway code
- 08-29 | tickets frozen, contracts C1–C10 published | TASK.md, CLAUDE.md, AGENTS.md, knowledge_base.md | 3 lanes × ~17 pt, no cross-lane ticket dependency except J1

## 7. Archived

_(compress oldest changelog lines here, one line per day, when the KB passes 300 lines)_

- 08-29 | lane I | I5 `common/plate.py` + 23 tests; D's `plate_compat.py` flipped to the real one
- 09-01 | lane I | I1 decode: 10 cams x 5.02 fps for 10 min, 0 drops, memory band 1.5%
