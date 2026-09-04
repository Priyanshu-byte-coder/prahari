# TASK.md — Prahari / SENTINEL: tickets, owners, contracts

Frozen 2026-08-29. Source of truth for **who builds what**.
Design detail lives in `docs/internal/implementation-plan.md` (grep by anchor, never read whole).
Live state lives in `knowledge_base.md`. Working rules live in `CLAUDE.md`.
Tickets are mirrored as GitHub issues on `Priyanshu-byte-coder/prahari`; ticket id is the issue title prefix.

## AGENTS: how to read this file

Never read this file whole. It is ~570 lines; your ticket is 15.

```bash
grep -n -A 22 '^### I3'  TASK.md      # your ticket block
grep -n -A 30 '^## C3 '  TASK.md      # a contract block your ticket names (keep the trailing space)
grep -n -A 30 '^### B3'  docs/internal/implementation-plan.md   # deep design, only if stuck
```

---

## 1. The clock (real dates, from docs/brief-sentinel-hackathon.md — the plan's §16 sprint dates are obsolete)

| Date | What |
|---|---|
| Sat 29 Aug | Wave 0. Every lane self-unblocked by tonight. |
| 30 Aug – 1 Sep | Wave 1 |
| 2 Sep – 4 Sep | Wave 2 |
| Fri 5 Sep | Wave 3 + **merge & freeze** |
| Sat 6 Sep | Demo video recorded, deck + HLD final, rehearsal 1 |
| **Sun 7 Sep** | **SUBMIT before registration closes.** Shortlist same evening. |
| 8–9 Sep | Hardening, rehearsals, P1 extras only if P0 is green |
| 10–11 Sep | Event at i-Hub, Gandhinagar |

9 days to submission. Anything not on a P0 ticket does not get built.

## 2. Lanes, owners, and why they never block each other

| Lane | Owner | Owns (directories) | Reads | Writes | Never touches |
|---|---|---|---|---|---|
| **I — INFERENCE** | **Neal006** | `services/worker/`, `models/`, `common/plate.py`, `fixtures/golden/`, `fixtures/clips/`, `docs/deck-outline.md` | a stream URL (Redis `camera:transport:<id>`, or a local clip) | Redis `sightings`, MinIO crops, `camera:fps:<id>` | gateway, api, db, web |
| **G — EDGE + CONSOLE** | **neevmodh** | `services/gateway/`, `web/`, `infra/`, `fixtures/api/`, `data/*.json` | grid `/api/ingest`, `camera:fps:<id>`, REST+WS contract | `cameras.seed.json`, `camera_geo.json`, `camera:transport:<id>`, Redis `camera.health`, the console | worker, models, api, db |
| **D — CORE** | **Priyanshu-byte-coder** | `services/api/`, `db/`, `common/` (except `plate.py`), `scripts/` | Redis `sightings` + `camera.health`, both seed files | Postgres, REST, WebSocket | worker, gateway, web |

Four seams, all frozen in §C below, none of them a person:

1. **Stream URL** (G → I). The gateway *resolves and monitors*; the worker *decodes and infers*. The worker never imports gateway code — it reads a URL string from `camera:transport:<id>` [C2], and falls back to a local clip in dev. Two processes, one string.
2. **Redis `sightings`** (I → D). D develops against `scripts/fake_sightings.py`, which D owns (part of D2). D never waits for the worker.
3. **REST + WS contract** (D → G). The console develops against `fixtures/api/*.json`, which G owns (part of G7). The console never waits for the API.
4. **Exchange files, one producer each**: `data/cameras.seed.json` + `data/camera_geo.json` (G), `db/schema.sql` (D), `fixtures/golden/` (I). No file has two writers.

Rules that keep it true:
- Edit only your own directories. Need a change elsewhere? Add a line under `## Cross-lane requests` at the bottom of this file. Do not edit another lane's code.
- Contracts in §C are frozen. Changing one needs a `CONTRACT CHANGE` line in `knowledge_base.md` **and** a message to the other two before you push.
- **J1 is the only ticket that depends on other people's merged work.** It is scheduled after the freeze, on purpose.
- One honest exception at hour zero: G5 ships `infra/docker-compose.yml`, which I and D need running locally. It is 1 hour, today, and after it lands nobody waits for anybody again. If it slips past tonight, any lane can start it — the container list is in [C9].

## 3. Effort balance (1 pt ≈ half a day)

| Lane | Wave 0 | Wave 1 | Wave 2 | Wave 3 | **P0 total** | P1 stretch |
|---|---|---|---|---|---|---|
| I — Neal006 | I5 (1) | I1,I2,I3 (6) | I4,I6,I8 (6) | I7,I9 (4) | **17** | I10,I11,I12 (7) |
| G — neevmodh | G1,G5 (2) | G2,G3,G6,G7 (7) | G8,G9,G10,G11 (8) | G4 (1) | **18** | G12 (2) |
| D — Priyanshu-byte-coder | (D2 generator) | D1,D2,D3 (6) | D4,D5,D6 (6) | D7,D8 (5) | **17** | D9,D10 (3) |

Plus **J1** (integration + rehearsals, 2 pt) which all three share after the freeze.
G carries one extra point — G4 (ONVIF + VMS stub) is the hybrid-architecture bonus screen. Drop it to P1 if that lane runs late.

## 4. Salvage before you write (saves ~2 days across the team)

`main` was reset by commit `416ef26 "Restart"`. The old working code is still in git:

```bash
git show 4d0c945:services/worker/stream_reader.py > /tmp/ref_stream_reader.py     # I, decode reference
git show 4d0c945:services/worker/plate_reader.py  > /tmp/ref_plate_reader.py      # I, OCR reference
git show 4d0c945:scripts/probe_grid.py           > scripts/probe_grid.py          # G
git show 4d0c945:data/catalogue/ingest.json      > data/catalogue/ingest.json     # G
git show 4d0c945:data/camera_geo.json            > data/camera_geo.json           # G, then fix coords
git show 4d0c945:web/vendor/leaflet.js           > web/vendor/leaflet.js          # G
git show 4d0c945:infra/sentinel-grid.yml         > infra/sentinel-grid.yml        # G
git show origin/priyanshu/platform:services/api/route_routes.py > /tmp/ref_route.py  # D
```

Full old tree: `git ls-tree -r --name-only 4d0c945`. Read a salvaged file once, record what it gives you in `knowledge_base.md`, then adapt. Do not re-derive from scratch and do not re-read it next session.

## 5. Definition of done — every ticket, no exceptions

1. Code in your directories only.
2. **One runnable check** — the `Verify:` line in the ticket must pass on your machine.
3. **`knowledge_base.md` patched** per the update contract in `CLAUDE.md` (status line + file-map lines + changelog line). A ticket without a KB patch is not done.
4. Commit `[I3] short imperative message`, push to `lane/<yourname>`, PR to `main`, close the issue.

---

# LANE I — INFERENCE (Neal006)

Goal: pixels in, 200-byte sighting rows out on Redis. You own the worker process and every model in it.
You never open the gateway, the API or the console. Your input is a URL string; in dev it is a local clip,
so nothing about this lane waits for anybody.

### I5 — `common/plate.py` · 1 pt · Wave 0
- `normalise`, `canon`, `grammar_fix`, `weighted_levenshtein` exactly as [C7], with its test vectors. Pure functions, no I/O, no dependencies.
- Both your voting code and D's matcher import this. It is the one file you own inside `common/`.
- Files: `common/plate.py`, `tests/test_i_plate.py`
- Done when: every vector in [C7] passes.
- Verify: `pytest tests/test_i_plate.py`

### I1 — Decode pipeline · 2 pt · Wave 1
- One ffmpeg subprocess per camera: `-hwaccel cuda -c:v h264_cuvid -rtsp_transport tcp -i <url> -vf fps=5,scale=960:-2 -f rawvideo -pix_fmt bgr24 pipe:1`. CPU-decode fallback flag for laptops without NVDEC.
- Input is a **URL string or a local file path** — read `camera:transport:<id>` [C2] when Redis has it, else take `--file fixtures/clips/x.mp4`. That fallback is what keeps this lane independent of the gateway.
- Frame PTS travels with the frame from here to the sighting row. `pts_first`/`pts_last` never come from `now()`.
- Motion gate: 96 px grey thumbnail diff, skip the frame if <0.5% of pixels changed. Empty roads at night cost nothing.
- Bounded queues, depth 2 per camera. Under load drop **frames**, never sightings; count drops per camera.
- Publish `camera:fps:<id>` (float, TTL 30 s) so the gateway can compute health — that key is your only side output.
- Files: `services/worker/decode.py`, `services/worker/queues.py`
- Done when: 10 streams decode concurrently at 5 fps with flat memory for 10 min.
- Verify: `python -m services.worker.decode --bench --cameras 10 --seconds 60`
- Detail: plan §C3, §C8. Reference: `/tmp/ref_stream_reader.py` from §4.

### I2 — Backend + detector + batching · 2 pt · Wave 1
- `InferenceBackend` protocol exactly as [C6]. Ship `LocalBackend` on pretrained `yolov8s.pt`; fine-tuned weights are a **config path**, never a code change (that is I11, and it must never block this ticket).
- Batch up to 16 frames across cameras, flush every 20 ms. One big batch beats thirty small ones.
- Classes: two_wheeler, three_wheeler, car, lcv, bus, truck, tractor. COCO already covers most of them.
- Files: `services/worker/backend.py`, `models/README.md`
- Done when: batched inference sustains 150 frames/s on our GPU, measured not guessed.
- Verify: `python -m services.worker.backend --bench` prints p50/p95 per model.
- Detail: plan §B1, §C4, §C5.

### I3 — Tracker + sighting builder · 2 pt · Wave 1
- One ByteTrack instance **per camera, kept alive across frames** — a fresh instance per frame resets IDs. `track_thresh 0.25`, `track_buffer 30`, `match_thresh 0.8`.
- One sighting per track: open at first frame, close 6 s after the last, carrying the best crop and the best plate read.
- Emit the row exactly as [C1]. `sighting_id` is a ULID.
- Files: `services/worker/tracker.py`, `services/worker/sighting.py`
- Done when: a 60 s clip gives one sighting per vehicle pass and track ids do not churn.
- Verify: `pytest tests/test_i_tracker.py`
- Detail: plan §B4.

### I4 — Plate: detect, read, grammar, vote · 3 pt · Wave 2
- Plate detector runs on **vehicle crops, not full frames** — a 20 px plate in a 1920 px frame becomes ~60 px inside a 640 px vehicle crop, and small-object recall goes up for free.
- Two readers minimum (salvaged Awiros path + PaddleOCR); a third is stretch. OCR only tracks with no CONFIRMED read yet whose latest crop is sharper than the best so far (variance of the Laplacian).
- Grammar before voting: `^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$` or BH `^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$`. Letter slots convert 0→O, 1→I, 8→B, 5→S; digit slots convert the other way. This removes most confusion-class errors before any vote.
- Multi-frame vote: up to 8 sharpest crops per track, align by position, vote per character weighted by reader confidence. Emit `plate_text` only on a 2/3 majority; **otherwise emit null and keep the crop**. Reporting nothing beats reporting the wrong vehicle to a police officer.
- Set `plate_band` (CONFIRMED | PROBABLE | POSSIBLE | NONE) and fill `plate_norm`/`plate_canon` via I5.
- Files: `services/worker/plate.py`, `services/worker/vote.py`
- Done when: 200 hand-checked crops give exact-match ≥70% and **zero** confident-wrong reads at CONFIRMED.
- Verify: `pytest tests/test_i_plate_vote.py`
- Detail: plan §B2, §B3. Reference: `/tmp/ref_plate_reader.py`.

### I6 — Publish: Redis + MinIO + metrics · 2 pt · Wave 2
- XADD the row to stream `sightings` exactly as [C1]/[C2]. This is your lane's only real output; the field names are frozen.
- PUT the best crop to MinIO at `crops/<camera_id>/<yyyy>/<mm>/<dd>/<sighting_id>.jpg` and put the URI on the row. Worker credentials do XADD and PUT, nothing else.
- `/metrics` (Prometheus): frames decoded, frames dropped, inference p50/p95 per model, queue depth, sightings/s, OCR vote success rate.
- Files: `services/worker/publish.py`, `services/worker/metrics.py`
- Done when: a live camera produces rows continuously for 10 min with no field-shape drift.
- Verify: `python -m services.worker.selftest --assert-xadd` replays a clip and asserts a valid row on the stream.

### I8 — Worker selftest + replay harness · 1 pt · Wave 2
- `ffmpeg -re -stream_loop -1 -i clip.mp4 -c copy -f rtsp rtsp://<grid>:8554/test` publishes a clip with a **known plate** on demand. This is how the judge scenario gets replayed at will, and it is what J1's integration test drives.
- Files: `scripts/replay_clip.sh`, `fixtures/clips/README.md`, `services/worker/selftest.py`
- Done when: one command injects a known plate and it lands on the `sightings` stream within 3 s.

### I7 — Golden set + accuracy report · 2 pt · Wave 3
- 200 plate crops + 100 full frames, hand-labelled, **never trained on**. Split by camera and by day, never by frame — frames from one clip on both sides of the split inflate every number you report.
- One command regenerates: exact-match rate, CER, precision per band, and the honest recall figure (share of plates no reader can read — expect ~13%).
- Files: `scripts/accuracy_report.py`, `fixtures/golden/`, `docs/model-card.md`
- Done when: every accuracy number in the deck comes from this report's output, never typed by hand.
- Verify: `python scripts/accuracy_report.py --golden fixtures/golden/`

### I9 — Deck: 10 slides · 2 pt · Wave 3
- One slide per scoring point: hybrid model table (M1–M4) · architecture + protocol map · drivers 3 live 1 interface-complete · ANPR pipeline + the sighting record · model card with per-band precision from I7 · watchlist bands + alert FSM + latency · route with plausibility · RBAC matrix + audit · scale arithmetic · roadmap.
- Scale slide, formula printed so the jury can check it: centralised video at 80k cameras ≈160 Gbps and ≈26 PB; metadata at ~200 B/sighting ≈80 M rows/day ≈16 GB/day raw, 2–3 GB compressed.
- Prize pool, if quoted: **₹51 lakh** (portal), not the ₹37 lakh press figure.
- Close on precision over recall: *"the fusion refuses to guess below a 2/3 majority; we would rather report nothing than report the wrong vehicle to a police officer."*
- Files: `docs/deck-outline.md`
- Done when: every number on a slide traces to a report or a printed formula, not to memory.

### I10 — (P1) Vehicle Re-ID · 2 pt
OSNet/fast-reid on VeRi-776 → 512-d vector on the sighting row. Self-supervised fine-tune: same track = positive, different tracks on one camera at one time = negative. **Corroboration only, never identity** — it may add a PROBABLE hop, never a confirmed one.

### I11 — (P1, 8–9 Sep only) Fine-tune + TensorRT · 3 pt
Fine-tune vehicle + plate detectors, export ONNX opset 17 → `trtexec --fp16`, assert PyTorch/ONNX agreement at rtol 1e-3 and an mAP drop under 0.5 point. Swap by config path. **Do not start before I1–I9 are green.**

### I12 — (P1) Bonus analytics · 2 pt
Crowd count per zone with a 30 s threshold; anomaly rules on tracks with no training — stopped >60 s in a no-stop zone, wrong-way against `lane_bearing_deg`, loitering >5 min.

---

# LANE G — EDGE + CONSOLE (neevmodh)

Goal: get heterogeneous cameras resolved and monitored, and give the judge the screen. You own both
ends of the video path — the gateway that finds a stream and the console that shows it — and you own
the API fixtures that keep the console independent of the server.

### G1 — Grid recon + camera seed · 1 pt · Wave 0
- Salvage `scripts/probe_grid.py` + `survey_grid.py` from `4d0c945` (§4).
- Hit `GET http://$GRID_HOST/api/ingest` and record every camera: id, name, codec, resolution, fps, and the three endpoint URLs. Read per-camera properties before anything else touches a stream.
- Emit `data/cameras.seed.json` in the shape of [C8]. No lat/lon here — that is G6.
- Files: `scripts/probe_grid.py`, `data/cameras.seed.json`
- Done when: the seed lists every grid camera with at least one reachable transport.
- Verify: `python scripts/probe_grid.py --check` prints camera count and per-transport reachability.

### G5 — Infra: compose, env, Makefile · 1 pt · Wave 0
- `infra/docker-compose.yml`: postgres 16 + TimescaleDB + pgvector, redis, minio, osrm. One `docker compose up` for the whole team — the other two lanes need this today.
- `.env.example` per [C9], `.gitignore` (`.env`, weights, video, crops), `requirements.txt`, `Makefile` with `up | seed | check`.
- Repo skeleton: `services/{gateway,worker,api} common db web infra scripts tests fixtures data docs models`.
- Files: `infra/`, `Makefile`, `.env.example`, `.gitignore`, `requirements.txt`
- Done when: `make up` gives green containers on all three laptops.

### G2 — CameraSource + transport resolution · 2 pt · Wave 1
- `CameraSource` protocol exactly as [C6], with two live drivers: `MediaMTXSource` (HLS) and `RTSPSource` (PyAV, `rtsp_transport=tcp` — UDP dies across NAT, non-negotiable).
- Probe order RTSP/TCP → HLS: open the RTSP port with a 2 s timeout, send DESCRIBE, fall back to the HLS playlist. Re-probe every 10 minutes so a fixed network upgrades itself back to RTSP.
- Publish the winner to `camera:transport:<id>` [C2] — `{url, transport, driver, probed_at}`. **That key is the whole seam with the worker**; the worker imports none of your code.
- Reconnect with exponential backoff 1/2/4…30 s; a watchdog kills a connection after 10 s with no frames, because a stalled RTSP socket never errors on its own.
- Files: `services/gateway/source.py`, `sources/mediamtx.py`, `sources/rtsp.py`, `services/gateway/probe.py`
- Done when: blocking port 8554 makes a camera fall back to HLS automatically and rewrite its key.
- Verify: `python -m services.gateway.selftest --probe-all` prints a transport table with the reason per camera.
- Detail: plan §A1–A3, §A6.

### G3 — Health monitor · 2 pt · Wave 1
- Signals: connected, fps in the last 10 s (read `camera:fps:<id>`, which the worker writes), age of last frame, decode errors.
- LIVE = fps ≥60% of expected and last frame <3 s. DEGRADED = below that, or 3–15 s. DOWN = no frame for 15 s or repeated connect failures. UNKNOWN before the first probe.
- Publish `camera.health` [C2] on every change — you are its only producer. The console pin recolours within a second.
- Files: `services/gateway/health.py`
- Done when: killing a stream turns its pin red within 15 s and emits exactly one event.
- Detail: plan §A4.

### G6 — Coordinate ground truth · 1 pt · Wave 1
- **Do this before any route UI.** District-centroid coordinates make the demo car teleport across the map, and that single artifact kills the graded test case.
- Per camera (~4 min × 30 ≈ 2 h): open the live frame, find a landmark, place the pin on the basemap, set the bearing to what the frame looks at, record `coord_source=manual` and `coord_conf`.
- Emit `data/camera_geo.json` per [C8]. Cameras you cannot place stay `coord_conf=LOW` and render dotted.
- Files: `data/camera_geo.json`, `scripts/geo_helper.html`
- Done when: ≥25 of 30 cameras are HIGH or MEDIUM confidence.

### G7 — Map layers 1–2 + API fixtures · 2 pt · Wave 1
- **Write `fixtures/api/*.json` first** — one hand-written response for every endpoint in [C4]. This is what makes the console independent of D's API; skip it and you will be blocked by Wave 2.
- Leaflet, vendored (salvage from `4d0c945`). Muted grey basemap by default, satellite as a **toggle, never default** — pins are unreadable on satellite.
- `Leaflet.markercluster`: numbered bubbles zoomed out, splitting on zoom. Prove it at 80,000 pins by cloning the fixture list ×2000.
- Pin colour = health (green LIVE / amber DEGRADED / red DOWN / grey UNKNOWN); icon shape = install type (FIX/PTZ/RLVD); dotted outline = LOW coord confidence.
- Click a pin → side panel: metadata, live thumbnail refreshed every 5 s, health history, "open in wall".
- Files: `fixtures/api/`, `web/index.html`, `web/map.js`, `web/styles.css`
- Verify: the map renders fully with the API down.

### G8 — Coverage wedges + bearing editor · 2 pt · Wave 2
- Translucent polygon per fixed camera: `bearing − fov/2` to `bearing + fov/2`, out to `range_m`.
- A drag handle at the wedge tip rotates the bearing and saves through `PATCH /api/cameras/{id}` [C4]. Keep drag-to-move for position.
- Files: `web/wedges.js`
- Done when: rotating a wedge persists and survives a reload.

### G9 — Events layer + time slider + WS client · 2 pt · Wave 2
- Detections as small dots that fade after 30 s; alerts pulse red until acknowledged.
- Time slider: drag a window, the layer shows only that window (`GET /api/events?from&to&bbox`). Preload the last 6 h so dragging is instant.
- WS client per [C5]: JWT as the first message, heartbeat, reconnect with backoff, resume from the last `seq`. Acknowledge / dismiss controls; dismissing without a reason is blocked in the UI too (the server 409s regardless).
- Files: `web/events.js`, `web/ws.js`
- Verify: replay `fixtures/api/ws-stream.jsonl` through a local echo server — alerts pulse, health pins recolour in under a second.

### G10 — Route view (the graded test case) · 2 pt · Wave 2
- Plate + time window in; numbered pins 1..N out, line drawn in sequence with a short animation, each pin labelled camera + time, plate crop on hover.
- PROBABLE (Re-ID) hops dashed in a different colour and labelled. IMPLAUSIBLE hops carry a warning icon showing the implied speed. Fuzzy result sets show a "verify plate" banner.
- Legend text is fixed: *"sighting order, road-snapped between sightings; not a GPS track."*
- Table below the map with the same rows, plus CSV and PDF export buttons hitting [C4].
- Files: `web/route.js`
- Done when: `fixtures/api/route.json` renders 5 ordered pins including one dashed and one flagged, with no server running.

### G11 — Video wall + admin page · 2 pt · Wave 2
- HLS grid with `hls.js`. Click a tile → it expands and switches to WebRTC via WHEP (`http://$GRID_HOST:8889/stream/<id>/whep`); if WebRTC does not connect within 3 s, fall back to HLS with a small badge. Judges' networks block WebRTC — rehearse this on a phone hotspot.
- Health badge per tile. Preset "alert view" opens the alerting camera plus its two nearest neighbours.
- Admin page: the driver list showing 3 live + VMS stub labelled `interface complete`, and per-camera `transport_in_use` with the reason. Say it out loud in the demo: *"this camera came in on HLS because RTSP was blocked."*
- Files: `web/wall.js`, `web/admin.js`
- Verify: the grid plays from the live sandbox; kill WebRTC and confirm the fallback badge.

### G4 — ONVIF driver + VMS stub · 1 pt · Wave 3
- `ONVIFSource` with python-onvif-zeep: WS-Discovery, GetProfiles, GetStreamUri, then publish the resolved RTSP URL to `camera:transport:<id>` like any other driver. Expose PTZ ContinuousMove/Stop.
- `VMSSource`: **stub only** — typed signatures `list_cameras()`, `get_stream_uri(cam_id)`, `subscribe_events()`, returning mock rows, labelled `STUB: interface complete, awaiting vendor credentials`.
- This is the hybrid-architecture bonus in one screen: three drivers live, one interface-complete.
- Files: `services/gateway/sources/onvif.py`, `sources/vms.py`
- Done when: the admin page (G11) lists 3 live + 1 stub from real driver state.
- Detail: plan §A2, §3.5.

### G12 — (P1) Grafana dashboard · 2 pt
One dashboard: cameras up, GPU load, queue depth, drop rate, alert latency p95. Screenshot goes in the deck.

---

# LANE D — CORE (Priyanshu-byte-coder)

Goal: rows in, answers out — persistence, correlation, alerts, route, access control, and the HLD.
You never open a video stream; your input is a Redis stream you can generate yourself.

### D1 — Schema + registry loader · 2 pt · Wave 1
- `db/schema.sql` exactly as [C3]: Postgres 16 + TimescaleDB + pgvector + pg_trgm. Hypertable on `sightings.pts_first` with 1-day chunks, all five indexes. Create the hypertable **before** any row is inserted.
- `scripts/load_registry.py` joins `data/cameras.seed.json` + `data/camera_geo.json` (both G's) into `cameras`. Idempotent, prints before/after counts, tolerates either file being stale or missing.
- Files: `db/schema.sql`, `db/migrate.sql`, `scripts/load_registry.py`
- Done when: `make up` plus one command gives a queryable schema and a populated camera table.
- Verify: `python scripts/load_registry.py --dry-run` prints row counts and missing-coordinate warnings.
- Detail: plan §D2, §A5.

### D2 — Sighting generator + persister · 2 pt · Wave 1
- **Write `scripts/fake_sightings.py` first** (~40 lines): XADDs synthetic rows matching [C1] at a set rate, including a scripted plate that crosses 5 cameras in order — that is your route test data. It is what lets you finish this entire lane before the worker exists.
- Consumer group `persister` on `sightings` → batched inserts. Reclaim a dead consumer's pending messages with XAUTOCLAIM.
- Redis KV cache `plate:<plate_norm>` = last 50 sighting ids, TTL 24 h — O(1) recent lookup for the matcher and the search box.
- MinIO presigned crop URLs, 5 min expiry, signed **only after the scope check passes** (wire the hook now, enforce in D7).
- Timescale compression on chunks older than 7 days; retention: sightings 90 d, crops 30 d, alerts and audit kept.
- Files: `scripts/fake_sightings.py`, `services/api/persister.py`, `services/api/store.py`
- Done when: 50 rows/s persist for 5 minutes with no consumer lag growth.
- Verify: `pytest tests/test_d_persister.py`

### D3 — Watchlist + feeds · 2 pt · Wave 1
- CRUD per [C4]. Fields: kind, plate/description, category (stolen vehicle | wanted person | missing person | blacklisted vehicle | suspect), reason, severity, owner dept, classification, validity window, added_by, source.
- CSV import: header check, plate-grammar check, and a **row-level error report** — a rejected row names its line number and its reason. No partial writes.
- `WatchlistFeed` protocol [C6]: `ManualFeed` + `CSVFeed` live; `VahanFeed` + `EGujCopFeed` stubs with the real request/response shapes written down, returning sample rows, labelled STUB. That is the integration-readiness point the brief asks for.
- Files: `services/api/watchlist.py`, `services/api/feeds.py`
- Verify: `pytest tests/test_d_watchlist.py` — import a CSV with 2 bad rows, assert both reported and nothing written.

### D4 — Matcher + alerts + state machine · 2 pt · Wave 2
- Consumer group `matcher` on `sightings`; every sighting is checked within milliseconds of arrival.
- Bands: **CONFIRMED** = exact `plate_norm` match and the sighting's own band is CONFIRMED. **PROBABLE** = distance 1 where the edit is a confusion pair (0/O, 1/I, 8/B, 5/S, 2/Z, 6/G). **POSSIBLE** = distance 2, or distance 1 outside those pairs.
- Look up `plate_canon` first (O(1) in Redis and the watchlist index), then rank candidates by weighted Levenshtein (confusion substitutions cost 0.5); trigram similarity is the distance-2 fallback. Import `common/plate.py` (I5) — do not write a second copy.
- Dedup `alert:dedup:<watchlist_id>:<camera_id>` TTL 60 s → increment `count` instead of spawning a duplicate.
- State machine NEW → ACKNOWLEDGED → ACTIONED | DISMISSED. **DISMISSED requires a reason.** The API enforces it: an illegal transition is HTTP 409. Every transition writes an `alert_events` row and an audit row.
- Files: `services/api/matcher.py`, `services/api/alerts.py`
- Verify: `pytest tests/test_d_alerts.py` — the full band table plus every illegal transition returning 409.
- Detail: plan §E3, §E4.

### D5 — WebSocket fanout · 2 pt · Wave 2
- `/ws` per [C5]. The client sends its JWT as the first message; the server computes scope **once** and subscribes that socket to `alerts`, `camera.health` and `sightings` filtered by it. The server filters, never the client.
- Heartbeat every 15 s; the client resumes with `{"type":"resume","since":<seq>}` and gets the gap backfilled. Monotonic `seq` per socket.
- This replaces polling completely — no 800 ms loop survives this ticket.
- Files: `services/api/ws.py`
- Done when: an alert reaches a connected console ≤2 s after the sighting on the RTSP path (≤6 s on HLS — the segment delay is the floor, not our code). Measure both, both go on a slide.
- Verify: `pytest tests/test_d_ws.py` — connect, inject an alert, assert the push and the reconnect backfill.

### D6 — Route API + export · 2 pt · Wave 2
- `GET /api/route?plate=&from=&to=` → [C4] `RouteResponse`, ordered by `pts_first` off the hypertable.
- Plausibility: haversine ÷ time gap = implied speed. Above 150 km/h, flag the lower-confidence hop `IMPLAUSIBLE` and **still show it** — never delete silently. Two sightings 200 km apart 90 s apart means one is wrong, and the judge seeing us catch it beats four suspiciously perfect hops.
- Fuzzy fallback: if the exact query returns nothing, retry on `plate_canon` with trigram ≥0.7 and label the result set `fuzzy match; verify plate`.
- Road snapping: osrm-backend in Docker with a Gujarat OSM extract, hop coordinates as waypoints, snapped path returned as GeoJSON.
- Export CSV and PDF (WeasyPrint: table + static map image). **Every export writes an audit row.**
- Files: `services/api/route.py`, `services/api/export.py`
- Done when: `fake_sightings.py --route GJ01AB1234` returns 5 ordered hops with one flagged implausible.
- Verify: `pytest tests/test_d_route.py`
- Detail: plan §G3, §G4.

### D7 — RBAC + audit · 3 pt · Wave 3
- JWT carrying user_id, dept_id, district_code, role; access 15 min, refresh 8 h; argon2 hashes; one bootstrap System Admin from a CLI command.
- A FastAPI dependency turns the JWT into a `Scope`. **Every** repository function takes `scope` and appends `WHERE owner_dept_id = ANY(:depts)` — for cameras, watchlist and alerts alike. Hiding a button is not access control.
- Postgres RLS as the backstop, keyed on a session variable set per request.
- Role matrix [C10]. Note the deliberate last row: the System Admin **cannot view video**. Say that on the slide.
- Audit log: append-only; who, what, when, from where, and why when a reason is required. Log every export and every live view. Hash chain (`hash = sha256(prev_hash || fields)`) with `GET /admin/audit/verify` if time allows (else D10).
- Files: `services/api/auth.py`, `services/api/scope.py`, `services/api/audit.py`
- Done when: the scope test is green and runs in CI on every merge.
- Verify: `pytest tests/test_d_scope.py` — log in as a Transport viewer, `GET /api/cameras`, assert only Transport cameras come back; repeat for watchlist and alerts.
- Detail: plan §H1–H5.

### D8 — HLD document · 2 pt · Wave 3
- Mandatory deliverable. Cover: integration approach, watchlist correlation, alert workflow, security model, interop assumptions, and the scale tiers (edge workers → Kafka → central Postgres/Timescale + object store).
- Include the privacy answer in full: no central video recording, only rows and small crops with retention limits; access purpose-bound (case number), time-boxed (grant expiry), scoped (department) and provable (hash-chained audit).
- State what fails and what the operator sees: a district link drops → its pins go red in 15 s, the edge buffers and replays; a GPU dies → its cameras reassign from the registry in 30 s.
- Files: `docs/hld.md`
- Done when: an outside engineer could rebuild the integration story from this document alone.

### D9 — (P1) Cross-department grants · 2 pt
An Investigator requests target dept + case number + reason + ≤72 h; the target Dept Admin approves; the grant auto-expires; every row read under it is logged with the grant id and case number.

### D10 — (P1) Audit hash-chain verify · 1 pt
`GET /admin/audit/verify` walks the chain and reports the first broken link. Tamper evidence in one slide.

---

# J — JOINT

### J1 — Integration test, chaos drills, rehearsals · 2 pt · after the 5 Sep freeze
- **The only ticket that depends on other lanes' merged work** — which is why it sits after the freeze.
- Integration test: I8 replays a clip with a known plate → assert a sighting row, a CONFIRMED alert, and a WebSocket message within 3 s. One command, run nightly against the sandbox.
- Chaos drills: kill a driver (pin red, restarts) · block 8554 (falls back to HLS) · restart Postgres (workers buffer, no lost sightings) · disconnect the console (reconnect and backfill).
- Two rehearsals of the 8-minute demo script (plan §15), timed. **No demo without a green integration test and a fresh accuracy report.**
- Demo video (2–3 min, screen-recorded on our own feed: onboarding → detection → watchlist match → alert) and the submission package: PPT/PDF + HLD + video link + hosted URL with test credentials. Mock-ups are explicitly rejected, so every frame must be the running system.
- **Submit 7 Sep before registration closes.** Not in the evening.
- Files: `tests/test_integration.py`, `docs/demo-script.md`, `docs/submission.md`

---

# C. FROZEN CONTRACTS

Copy these verbatim. Changing one requires a `CONTRACT CHANGE` line in `knowledge_base.md` and telling the other two owners first.

## C1 — Sighting record (I writes, D reads) — ~200 bytes

```json
{
  "sighting_id": "01J6...",            // ULID, sorts by time
  "camera_id": "GJ-AHD-0123",
  "track_id": 4821,
  "pts_first": "2026-09-14T10:41:03.120+05:30",
  "pts_last":  "2026-09-14T10:41:05.960+05:30",
  "ts_source": "rtsp_pts",             // rtsp_pts | hls_pdt | server_receive
  "plate_text": "GJ01AB1234",          // null when the vote fails — that is correct behaviour
  "plate_norm": "GJ01AB1234",
  "plate_canon": "6J01A81234",
  "plate_conf": 0.91,
  "plate_band": "CONFIRMED",           // CONFIRMED | PROBABLE | POSSIBLE | NONE
  "vehicle_class": "car",              // two_wheeler|three_wheeler|car|lcv|bus|truck|tractor
  "colour": "white",
  "bbox": [412, 220, 688, 410],
  "reid_vec": null,                    // float[512] or null
  "crop_uri": "s3://crops/GJ-AHD-0123/2026/09/14/01J6....jpg"
}
```

## C2 — Redis

| Key / stream | Producer | Consumer | Payload |
|---|---|---|---|
| stream `sightings` | I (worker) | D: groups `persister`, `matcher` | [C1] as one field `data` (JSON string) |
| stream `camera.health` | G (gateway) | D: group `ws-fanout` | `{camera_id, health, fps, last_frame_age_s, transport_in_use, at}` |
| stream `alerts` | D (api) | D: ws-fanout | `{alert_id, watchlist_id, sighting_id, camera_id, band, state, count, pts}` |
| `camera:transport:<id>` | G | I | `{url, transport, driver, probed_at}` — **the G→I seam** |
| `camera:fps:<id>` | I | G | float, TTL 30 s |
| `plate:<plate_norm>` | D | D | last 50 sighting ids, TTL 24 h |
| `alert:dedup:<wl>:<cam>` | D | D | TTL 60 s |

## C3 — SQL (D owns; I and G never write to Postgres)

```sql
CREATE TABLE departments (id serial PRIMARY KEY, code text UNIQUE, name text);
CREATE TABLE users (id serial PRIMARY KEY, username text UNIQUE, pw_hash text,
  dept_id int REFERENCES departments(id), district_code text, role text NOT NULL, active bool DEFAULT true);

CREATE TABLE cameras (
  camera_id text PRIMARY KEY, name text NOT NULL, owner_dept_id int REFERENCES departments(id),
  district_code text, install_type text,            -- FIX | PTZ | RLVD
  lat double precision, lon double precision,
  coord_source text, coord_conf text,               -- gps|manual|district_centroid ; HIGH|MEDIUM|LOW
  bearing_deg real, fov_deg real DEFAULT 70, range_m real DEFAULT 60, lane_bearing_deg real,
  transports jsonb, transport_in_use text, driver text,   -- mediamtx|rtsp|onvif|vms
  health text DEFAULT 'UNKNOWN', health_at timestamptz, updated_at timestamptz DEFAULT now());

CREATE TABLE sightings (
  sighting_id text, camera_id text REFERENCES cameras(camera_id), track_id bigint,
  pts_first timestamptz NOT NULL, pts_last timestamptz, ts_source text,
  plate_text text, plate_norm text, plate_canon text, plate_conf real, plate_band text,
  vehicle_class text, colour text, bbox int[], reid_vec vector(512), crop_uri text,
  PRIMARY KEY (pts_first, sighting_id));
SELECT create_hypertable('sightings','pts_first', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON sightings (plate_norm, pts_first DESC);
CREATE INDEX ON sightings (plate_canon, pts_first DESC);
CREATE INDEX ON sightings (camera_id, pts_first DESC);
CREATE INDEX ON sightings USING gin (plate_norm gin_trgm_ops);
CREATE INDEX ON sightings USING hnsw (reid_vec vector_cosine_ops);

CREATE TABLE watchlist (id serial PRIMARY KEY, kind text, plate_norm text, plate_canon text,
  face_vec vector(512), description text, category text, reason text, severity text,
  owner_dept_id int, classification text, added_by int REFERENCES users(id),
  valid_from timestamptz, valid_until timestamptz, source text DEFAULT 'manual');

CREATE TABLE alerts (id serial PRIMARY KEY, watchlist_id int, sighting_id text, camera_id text,
  pts timestamptz, band text, state text DEFAULT 'NEW', count int DEFAULT 1,
  created_at timestamptz DEFAULT now());
CREATE TABLE alert_events (id serial PRIMARY KEY, alert_id int, from_state text, to_state text,
  by_user int, reason text, at timestamptz DEFAULT now());

CREATE TABLE access_grants (id serial PRIMARY KEY, requester int, target_dept_id int,
  case_no text NOT NULL, reason text NOT NULL, approved_by int,
  starts timestamptz, expires timestamptz NOT NULL, state text);

CREATE TABLE audit_log (seq bigserial PRIMARY KEY, at timestamptz DEFAULT now(), user_id int,
  dept_id int, action text, object_type text, object_id text, ip inet, reason text,
  grant_id int, prev_hash bytea, hash bytea NOT NULL);
```

## C4 — REST (D serves, G consumes)

```
POST   /api/auth/login              {username,password} -> {access, refresh, role, dept}
POST   /api/auth/refresh            {refresh} -> {access}
GET    /api/cameras                 -> [Camera]                      (scoped)
GET    /api/cameras/{id}            -> Camera + health_history[]
PATCH  /api/cameras/{id}            {lat?,lon?,bearing_deg?,fov_deg?,range_m?} -> Camera
GET    /api/cameras/{id}/snapshot   -> 302 to presigned jpg
GET    /api/events?from&to&bbox&camera_id&limit   -> [Sighting]
GET    /api/search?plate&from&to    -> {rows:[Sighting], fuzzy:bool}
GET    /api/route?plate&from&to     -> RouteResponse  (see below)
GET    /api/route/export?plate&from&to&fmt=csv|pdf   -> file  (writes an audit row)
GET    /api/watchlist               -> [WatchlistEntry]
POST   /api/watchlist               WatchlistEntry -> WatchlistEntry
DELETE /api/watchlist/{id}
POST   /api/watchlist/import        multipart csv -> {added:n, errors:[{line,reason}]}
GET    /api/alerts?state&limit      -> [Alert]
POST   /api/alerts/{id}/state       {to_state, reason?} -> Alert | 409
GET    /api/admin/drivers           -> [{driver, status, cameras, note}]
GET    /api/admin/audit?from&to     -> [AuditRow]
GET    /api/admin/audit/verify      -> {ok:bool, first_broken_seq:int|null}
GET    /healthz  |  GET /metrics
WS     /ws                          see [C5]

Camera = {camera_id,name,district_code,owner_dept_id,install_type,lat,lon,coord_source,
          coord_conf,bearing_deg,fov_deg,range_m,transports,transport_in_use,driver,health,health_at}

RouteResponse = {plate, from, to, fuzzy:bool, hops:[
  {n,camera_id,name,lat,lon,pts,kind:"CONFIRMED"|"PROBABLE",band,crop_url,
   implied_speed_kmh,flag:null|"IMPLAUSIBLE",reid_similarity}],
  snapped_geometry: <GeoJSON LineString>}
```

## C5 — WebSocket

```
client -> {"token":"<jwt>"}                       first message, always
client -> {"type":"resume","since":<seq>}         after reconnect
server -> {"type":"alert.new"|"alert.state"|"camera.health"|"sighting"|"route.progress",
           "seq":<int>, "data":{...}}
server -> {"type":"ping"} every 15 s
```
Scope is computed once at connect from the JWT; the server filters, the client never does.

## C6 — Python protocols

```python
class CameraSource(Protocol):                      # lane G
    async def open(self) -> None: ...
    async def frames(self) -> AsyncIterator[Frame]: ...   # Frame = ndarray, pts, wall_ts, ts_source
    async def close(self) -> None: ...
    def health(self) -> Health: ...                       # LIVE|DEGRADED|DOWN|UNKNOWN
    def capabilities(self) -> set[str]: ...               # {"ptz","events","snapshot"}

class InferenceBackend(Protocol):                  # lane I
    def detect(self, frames) -> list[Detections]: ...
    def plates(self, crops) -> list[Detections]: ...
    def ocr(self, crops) -> list[Reading]: ...
    def reid(self, crops) -> np.ndarray: ...

class WatchlistFeed(Protocol):                     # lane D
    def pull(self, since: datetime) -> list[WatchlistEntry]: ...
```

## C7 — Plate functions + test vectors (I owns `common/plate.py`; D imports it)

```python
normalise(s)  # upper, strip spaces/hyphens/dots and a leading "IND"
canon(s)      # collapse confusion classes: {0,O,D,Q}->0 {1,I,L}->1 {8,B}->8 {5,S}->5 {2,Z}->2 {6,G}->6
grammar_fix(s)# ^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$ | ^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$
              # letter slots: 0->O 1->I 8->B 5->S ; digit slots: the reverse
weighted_levenshtein(a,b)  # confusion-pair substitution costs 0.5, everything else 1.0
```

| Call | Expected |
|---|---|
| `normalise("GJ 01 AB-1234")` | `GJ01AB1234` |
| `normalise("ind gj01ab1234")` | `GJ01AB1234` |
| `canon("GJ01AB1234")` | `6J01A81234` |
| `canon("6J01A81234")` | `6J01A81234` (idempotent) |
| `grammar_fix("GJ0IAB1234")` | `GJ01AB1234` (digit slot: I→1) |
| `grammar_fix("6J01AB1234")` | `GJ01AB1234` (letter slot: 6→G) |
| `weighted_levenshtein("GJ01AB1234","GJ01A81234")` | `0.5` → band PROBABLE |
| `weighted_levenshtein("GJ01AB1234","GJ01AC1234")` | `1.0` → band POSSIBLE |

Note: the plan's §3.4 example prints `plate_canon` as `GJ01A81234` (it skipped G→6). §G2's rule is the correct one and wins — canon maps **every** class character. Logged as a decision in `knowledge_base.md`.

## C8 — Exchange files (one producer each, never two)

```jsonc
// data/cameras.seed.json     PRODUCER: G (ticket G1)
[{"camera_id":"...", "name":"...", "district_code":"...", "install_type":"FIX",
  "driver":"mediamtx", "codec":"h264", "resolution":"1920x1080", "fps":25,
  "transports":{"rtsp":"rtsp://host:8554/stream/id","hls":"http://host/live/stream/id/index.m3u8",
                "whep":"http://host:8889/stream/id/whep"},
  "transport_probe":{"rtsp":true,"hls":true}}]

// data/camera_geo.json       PRODUCER: G (ticket G6)
{"<camera_id>":{"lat":23.0225,"lon":72.5714,"bearing_deg":135,"fov_deg":70,"range_m":60,
                "coord_source":"manual","coord_conf":"HIGH","landmark":"CG Road junction"}}

// fixtures/api/*.json        PRODUCER: G (ticket G7) — mirrors every [C4] response
// fixtures/golden/           PRODUCER: I (ticket I7) — labelled crops, never trained on
// fixtures/clips/            PRODUCER: I (ticket I8) — clips with known plates
```

## C9 — Environment (`.env.example`, G owns the file, everyone uses the names)

```
GRID_HOST=<sandbox host>        # RTSP :8554  WHEP :8889  HLS :80  catalogue GET /api/ingest
POSTGRES_DSN=postgresql://sentinel:sentinel@localhost:5432/sentinel
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=localhost:9000   MINIO_ACCESS_KEY=...  MINIO_SECRET_KEY=...
API_BASE=http://localhost:8000  WEB_PORT=5173  OSRM_URL=http://localhost:5000
JWT_SECRET=...                  FRAME_FPS=5   FRAME_WIDTH=960
```
Secrets live in `.env`, never in the repo. `.env` is gitignored on day one.

## C10 — Role matrix (D enforces in SQL, G reflects in the UI)

| Role | Live view | Detections | WL read | WL write | Route | Export | Admin |
|---|---|---|---|---|---|---|---|
| Viewer (dept) | own dept | own dept | – | – | – | – | – |
| Operator | own dept | own dept | own dept | – | own dept | – | – |
| Investigator (Police) | all | all | all | own dept | statewide | yes, logged | – |
| Dept Admin | own dept | own dept | own dept | own dept | own dept | yes | users in dept |
| System Admin | – | – | – | – | – | – | config + audit only |

---

## Cross-lane requests

Append one line here instead of editing another lane's code. The owner deletes the line when it is done.

| Date | From | To | Request | State |
|---|---|---|---|---|
| 2026-09-03 | D | I | Wire `services/worker/preprocess.py` into the worker: `prepare_frame()` before the detector, `tiles()`/`tile_plan()` on the wide-area cameras (a 55px vehicle is 18px after a 640 letterbox), `feasibility()` as the gate before an OCR pass, and `prepare_for_ocr(track_crops)` in place of `plate.upscale` in the OCR worker. Module + tests are written and green; no lane I file was touched. | PARTIAL (2026-09-03, lane G owner-directed): `prepare_frame` + `feasibility` gate wired in `run.py` behind env kill-switches, tests in `test_i_run_preprocess_wiring.py`. **Still open:** tiling (decode scales to 960 before the worker — needs native-res frames) and `prepare_for_ocr`/fusion (needs a per-track crop buffer). Neal006 to verify thresholds on the grid. |
| 2026-09-03 | D | G | Touched `services/gateway/wall.py` (2 lines): `Wall(user_agent=...)` passed to PyAV as its own option. Inside `headers` ffmpeg appends its own UA too and Cloudflare 403s the pair, so every tile sat on 'connecting'. Wall now pulls live HLS. | DONE, FYI |
| | | | | |
