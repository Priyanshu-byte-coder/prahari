# CONTEXT — Prahari

**Living state file. Update on every commit or material change.**
Anyone (human or agent) picking this project up cold should read this file first
and know exactly where things stand, what is proven, and what to do next.

---

| | |
|---|---|
| **Last updated** | 2026-08-28 11:38 IST |
| **HEAD** | pending this commit on `main` |
| **Repo** | https://github.com/Priyanshu-byte-coder/prahari (**private**) |
| **Submission deadline** | **2026-09-07** — 11 days remaining |
| **Event** | 2026-09-10 → 11, i-Hub Gujarat, Gandhinagar |
| **Category** | Category 1 (student team) |
| **Owner** | Priyanshu Doshi (Priyanshu-byte-coder) |

---

## 1. What this is

Submission for the **Gujarat Police Innovation Challenge 2026** (Sentinel CCTV
Integration Hackathon), Home Department, Government of Gujarat.
Prize pool ₹51,00,000. Full strategy in [PLAN.md](PLAN.md).

**Architecture chosen:** Hybrid — Model 1 (mandatory registry & GIS) + Model 3
(federation middleware) + selective Model 4 analytics, edge-first inference.

**Three hard gates from the organisers:**
1. Model 1 registry+GIS is mandatory, must be combined with another model.
2. Working software only — mock-ups and concept videos are explicitly rejected.
3. On evaluation day judges supply a vehicle registration number; the platform
   must produce its timestamped, location-wise route across the camera network,
   plus live watchlist matching with automated alerts.

---

## 2. Current state

### Working and verified
- **Camera registry** — 30 cameras merged from three sources (upstream catalogue,
  our own probe survey, geocoding). `GET /api/cameras`.
- **GIS map** — all 30 plotted, colour-coded by status, **drag a marker to correct
  its position**; persists via `PUT /api/cameras/{id}/geo`.
- **Stream gateway** — relays HLS for all reachable cameras on our own origin,
  terminating the upstream cookie-gate session server-side.
- **Video wall** — staggered connects, exponential backoff with jitter, non-fatal
  decoder warnings, per-tile **measured** frame rate.
- **Catalogue sync** — `POST /api/registry/sync` re-pulls `/api/ingest` and diffs
  added/removed camera ids.
- **Reconnaissance tooling** — `probe_grid.py`, `survey_grid.py`,
  `geocode_cameras.py`, `snapshot_all.py`.
- **End-to-end proof** — real frames pulled from live Gujarat Police cameras
  through our own gateway; see `data/snapshots/grid_contact_sheet.jpg`.
- **ANPR worker (vehicle stage)** — `services/worker/`: PTS-driven stream
  reader (TCP-forced, backoff reconnect, discontinuity detection) → YOLOv8s
  vehicle detection → ByteTrack tracking (custom `bytetrack_traffic.yaml`,
  90-frame occlusion buffer). Writes per-camera JSONL to `data/detections/`.
  Verified live against the real grid: sane per-class unique-vehicle counts,
  no runaway track-id churn.
- **Live operator console upgrades** — per-tile fullscreen (⛶) with a
  right-side data panel (metadata + live vehicle counts + recent tracks), and
  a live bounding-box overlay drawn on every playing tile, polling
  `/api/detections/{id}` every 800ms. Box math correctly matches `cover`
  (grid) vs `contain` (expanded) CSS, verified in a real browser.
- **Detections + fuzzy search API** — `GET /api/detections/{id}` (unique-track
  vehicle counts, recent track list), `GET /api/search/plate?q=...` (Python
  Levenshtein ±N matcher over all cameras' logged plates).

### Not built yet
- **Plate detection + OCR that actually works** — see "Known broken" below;
  this is the single biggest gap versus PLAN.md §4.1.
- Watchlist database, fuzzy matching, alert engine
- Cross-camera route reconstruction
- Persistence (PostgreSQL/PostGIS/TimescaleDB — currently JSON files on disk)
- RBAC, audit log
- HLD document, presentation, demo videos

### Known broken / degraded
- **RTSP 8554 filtered** on the current network → HLS is the only working transport.
- Only **15 of 30** cameras yield a frame reliably; the rest return 401, 5XX, 404
  or time out, and the set changes between runs.
- Geocoding is weak: 9 landmarks resolved via Nominatim, 15 hand-curated,
  the rest are district centroids. **All coordinates need ground-truth correction.**
- **Plate OCR does not work yet.** Measured, not assumed: a 22-camera sweep
  (best-resolution cameras first, ~12s live traffic each, ~1,500 vehicle-level
  OCR attempts) using EasyOCR on the *whole vehicle crop* produced **one** raw
  regex-valid string (`LQ07209` on cam 11) — and `LQ` is not a real Indian RTO
  state code, so even that hit is almost certainly noise. **Zero confirmed
  genuine reads.** Root cause identified by testing a real plate-region
  detector (see D13): once plate localization is tight instead of "whole
  vehicle," EasyOCR *does* pull real signal (a `GJ` state-code fragment, a
  digit group, a stable repeated read across 4 consecutive frames on one
  vehicle) — but our fragment-vs-full-regex matching throws all of it away
  because EasyOCR returns each plate as multiple text fragments, not one
  string. This is a fixable integration gap, not a dead end. Not yet wired in.

---

## 3. Grid facts (measured, not assumed)

Upstream: `https://live.corp8.cloud` — the grid is **MediaMTX** (ports 8554 /
8888 / 8889 and the `/whep` path are its defaults).

| Fact | Detail |
|---|---|
| Cameras in catalogue | 30, all flagged `live: true` |
| Reachable on survey | 22 / 30 over HLS; 0 over RTSP from this network |
| Actually yielding a frame | 15 / 22 (segment-level 5XX/404 on the rest) |
| Codecs | h264 × 20, hevc × 2 |
| Resolutions | 1920x1080, 1280x960, 1280x720, 960x576 |
| Frame rates | 9.92 – 29.67 fps, non-uniform |
| Catalogue metadata missing | 19 / 30 cameras report `0x0` and empty codec |
| Catalogue fps wrong | 4 cameras (cam 13 claims 12.5, delivers 10.0) |
| Auth-gated | cam 15, 26 → HTTP 401 |
| Server-side errors | cam 17, 18, 21, 22 → HTTP 5XX |

**The cookie gate.** First request to any HLS path returns `302` to
`?cookieCheck=1` with `Set-Cookie: cookieCheck=1; Secure; SameSite=None;
Partitioned`, and the redirect target downgrades to `http://`. Media players
follow this inside a session; a cross-origin browser request cannot. Our gateway
holds that session server-side. This is likely to stop most competing teams from
rendering feeds in a browser at all.

**LL-HLS is a trap.** Playlists advertise `CAN-BLOCK-RELOAD=YES` with
`#EXT-X-PART`. Players negotiate low-latency mode, issue blocking part-requests
several times per second per camera, and — in our case — never advanced to a
media segment. The gateway strips the low-latency tags and serves plain HLS.

**Camera identities are burned into the video overlay**, and are more informative
than the catalogue:
- `CSITMS-*` → Ahmedabad City Surveillance & Traffic Management System
- `PTZ` vs `FIX` → PTZ cameras move, so no static region-of-interest is valid
- `RLVD` → Red Light Violation Detection, aimed at stop lines.
  **These are the best ANPR targets: plates are largest and near-frontal.**

**Burned-in timestamps are NOT a shared clock.** Sampled overlays span 12:02 AM
to 23:18, and cam 13 read 23:16 then later 20:59 — time ran backwards, i.e. the
recording looped. Each camera plays its own 12-hour recording; the overlay is
source time, not grid time. **Cross-camera correlation must use stream PTS, never
the overlay and never frame arrival time.**

**Content skew.** Most footage is night. Cams 27/28/29 are indoor bus-station
cameras with no vehicles. The genuinely ANPR-useful subset is roughly 10–12
cameras, not 30.

---

## 4. Repository layout

```
CONTEXT.md              this file — current state, update every commit
PLAN.md                 full competition strategy, day-by-day to 11 Sep
README.md               public-facing project description

infra/
  sentinel-grid.yml     MediaMTX config: local clone of the Sentinel grid
  mediamtx.exe          v1.20.1 (gitignored)
scripts/
  probe_grid.py         first-contact probe: ports, catalogue, codecs, real fps
  survey_grid.py        probes every camera, writes the per-camera truth table
  geocode_cameras.py    location names -> coordinates (Nominatim + curated)
  snapshot_all.py       one frame per camera + contact sheet
services/api/
  main.py               registry, GIS, catalogue sync, static console
  gateway.py            unified stream gateway (cookie session, HLS rewrite)
simgrid/
  plate_render.py       Indian HSRP plate renderer for synthetic test data
web/
  index.html app.js styles.css     operator console
  vendor/               hls.js + leaflet, vendored for offline demo safety
data/
  catalogue/ingest.json         upstream catalogue snapshot
  catalogue/grid_survey.json    our measured per-camera truth table
  camera_geo.json               coordinates, with precision provenance
  snapshots/                    captured frames + contact sheet
```

---

## 5. How to run

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# operator console + gateway  ->  http://127.0.0.1:8080
.venv\Scripts\python.exe -m uvicorn services.api.main:app --port 8080

# refresh the measured truth table
.venv\Scripts\python.exe scripts\survey_grid.py --transport hls --workers 8

# one frame from every camera
.venv\Scripts\python.exe scripts\snapshot_all.py
```

**Keep the console tab in the foreground** — Chrome stalls MediaSource
`sourceopen` in hidden tabs, and the wall will show black tiles.

---

## 6. Decisions log

| # | Decision | Why |
|---|---|---|
| D1 | Hybrid Model 1+3+4, edge-first | 80k cameras centralised = ~160 Gbps backhaul and ~26 PB storage. Metadata to centre, compute to edge. |
| D2 | Docker for infra only; CV on host Python | RTX 3050 is reachable natively on Windows; GPU passthrough via WSL is avoidable pain. |
| D3 | HLS as primary transport | RTSP 8554 filtered on our network. Auto-detect per camera, prefer RTSP where it works. |
| D4 | Own stream gateway rather than direct browser playback | Upstream cookie gate blocks cross-origin browsers. Also where access control, pooling and audit belong. |
| D5 | Strip LL-HLS at the gateway | ~10x fewer upstream requests; players failed to reach a media segment otherwise. ~800 ms latency cost is irrelevant for a monitoring wall. |
| D6 | Repo private until submission | Competitors. Flip to public on 7 Sep — the submission may include a repo link. |
| D7 | Registry supports drag-to-correct geo | Most coordinates start as approximations, and route plausibility filtering depends on real inter-camera distance. Doubles as Model 1's "manual entry" requirement. |
| D8 | Correlate on stream PTS, not burned-in overlay | Overlays are per-camera source time and loop backwards. |
| D9 | ByteTrack occlusion buffer raised 30 → 90 frames (`bytetrack_traffic.yaml`) | Default caused ID churn on this grid's junction cameras (vehicles briefly blocked by others/poles); measured 452 "unique" tracks from 16k detection rows before the fix, ~15-20 after. |
| D10 | Vehicle counts computed from unique `track_id`, never per-detection-row | The `/api/detections` endpoint was summing one row per frame a track is visible — a car in frame for 100 frames counted as 100 vehicles. Real bug, user-reported, fixed. |
| D11 | EasyOCR chosen for plate OCR, not PaddleOCR/PARSeq | `paddlepaddle` ships no wheel for this machine's Python 3.14; PARSeq needs its own weights/preprocessing not set up in this pass. EasyOCR (CRAFT+CRNN) is real and installs cleanly, but see "Plate OCR does not work yet" above — it is not sufficient on its own. |
| D12 | Fuzzy plate search is a Python Levenshtein matcher, not OpenSearch | Standing up an OpenSearch cluster is out of scope for this pass; same ±N-char matching behaviour without the infra. |
| D13 | Found a real plate-region detector to integrate: `Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8` (MIT, 471★, verified 6.24MB working YOLOv8 weights, single class `license_plate`) | A widely-cited "94.5% accuracy" alternative (`lavanyashree2805/yolov8-license-plate-india`) was checked and is **fake** — its committed weights file is 2 bytes. Always verify a model repo's actual file sizes before trusting its README. |

---

## 7. Open questions

**For the organisers** (`sentinel.hackathon@gujarat.gov.in`):
1. Are cams 15 and 26 (HTTP 401) meant to need separate credentials?
2. Will the finale use these same 30 cameras or an expanded ~50?
3. Is the designated vehicle guaranteed plate-readable on multiple cameras?
4. Venue: internet allowed for a cloud-hosted deployment, or must it run offline?
5. Team-size cap for Category 1?
6. Any restriction on AGPL-licensed models (Ultralytics YOLO) for a solution
   intended for government deployment?

**Unresolved internally:**
- Is RTSP blocked by the ISP/college firewall or closed at the server? Untested
  on a second network.
- Team size and role split — unknown, changes what gets automated vs documented.

---

## 8. Action items

### Owner (Priyanshu)
- [ ] **Test RTSP on a mobile hotspot.** Run
      `.venv\Scripts\python.exe scripts\probe_grid.py --host https://live.corp8.cloud --cameras 2`
      and report whether port 8554 shows open. **Blocks the ingestion decision.**
- [ ] Email the organisers the questions in §7.
- [ ] Drop post-login materials into `docs/` — official problem statement PDF,
      submission form fields, HLD template, team/participant ID.
- [ ] Record 2–3 minutes of **daytime Indian traffic footage** (phone at a
      junction is fine) into `data/videos/`. Highest-value input for OCR accuracy.
- [ ] Confirm team size and who can take frontend / docs / video editing.
- [ ] Verify camera coordinates with local knowledge — drag pins on the map.

### Build queue (next up, in order)
- [x] ANPR worker: PTS-driven reader → vehicle detect → track (ByteTrack)
- [ ] **Wire in the real plate detector (D13)** to replace whole-vehicle-crop
      OCR, and fix the fragment-merging bug: EasyOCR returns a plate as
      multiple text pieces, current code only accepts one fragment matching
      the full regex. Merge fragments left-to-right by bbox position before
      validating. This is the highest-value next task — see "Known broken."
- [ ] Track-level fusion: character voting, format prior, confusion-class repair
      (vote-across-frames scaffolding exists in `run_worker.py`; needs the
      fixed OCR above to have anything real to vote on)
- [ ] Postgres + PostGIS + TimescaleDB, replacing JSON-on-disk
- [ ] Watchlist schema, admin UI, CSV bulk import
- [ ] Fuzzy matcher with confidence bands + alert engine + WebSocket push
- [ ] Cross-camera route assembler + spatio-temporal plausibility filter
- [ ] PDF/CSV route report export (a required submission artifact)
- [ ] Vehicle Re-ID fallback for when OCR fails
- [ ] Camera health / NOC dashboard
- [ ] RBAC + hash-chained audit log
- [ ] HLD document, 14-slide deck, two demo videos

### Deadlines
- **05 Sep 18:00** — feature freeze. Docs, video, rehearsal only after this.
- **07 Sep 14:00** — submit. Not 23:00; the portal will be under load.

---

## 9. Changelog

| Commit | Date | Change |
|---|---|---|
| *(pending)* | 2026-08-28 11:38 | ANPR worker (stream reader, YOLOv8s+ByteTrack vehicle tracking, tuned occlusion buffer), live box overlay + fullscreen data panel in the console, `/api/detections` and `/api/search/plate` endpoints, unique-track counting bugfix. Plate OCR still not producing real reads -- measured across 22 cameras, root cause identified, real detector sourced but not yet integrated (see §6 D9-D13). |
| `5862c68` | 2026-08-27 18:34 | CONTEXT.md living state file + CLAUDE.md working agreement |
| `7b99f81` | 2026-08-27 18:22 | Stream gateway (cookie session, HLS rewrite, LL-tag stripping), operator console (GIS map + video wall), snapshot tooling, grid reconnaissance |
| `357c2e3` | 2026-08-27 17:52 | Grid survey tooling, MediaMTX clone of the Sentinel grid, Indian plate renderer, first measurements of the live grid |
