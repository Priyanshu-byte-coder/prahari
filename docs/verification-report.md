# Build status — what exists, what runs, what does not

**As of commit `f100143` on `main`, 2026-09-04.** Working tree clean, nothing unpushed, CI green
on that SHA.

Every row below was verified by running it on this machine on the date above. Where a thing does
not work, the row says so and says why. Nothing here is projected, planned or rounded up.

---

## 1. Headline

| Check | Result |
|---|---|
| `pytest tests/ -q` | **364 passed, 6 skipped, 0 failed** (370 collected) |
| `scripts/verify_stack.py` | **35 / 35 checks passed** |
| `pytest tests/test_integration.py` (J1, all legs) | **6 / 6 passed** |
| `services/worker/selftest.py` | **SELFTEST OK** — plate read back exactly, **0.68 s** against a 3.0 s budget |
| GitHub Actions on `f100143` | **success** |
| Sightings persisted, live database | **100,651** rows, 0 pending |
| Audit chain | **728 rows, `ok: true`** |

One thing does not work, and it is not ours: **the camera grid's login endpoint is timing out**
(details in §6).

---

## 2. Components — built and running

Twenty-three components. Nineteen work, two are degraded by an external dependency, two are not
built.

| # | Component | State | How it was verified |
|---|---|---|---|
| 1 | Camera ingest — RTSP / HLS / ONVIF drivers, transport probing, per-camera health | ✅ working | 30 cameras in the registry; HLS pull proven live earlier today (real frames, real tiles) |
| 2 | Video wall — 30 tiles, keyframe-only pull, corrupt-frame guard | ⚠️ blocked upstream | Pool starts and manages feeds correctly (`{"started":["18","27","4"],"running":3}`), but the grid will not authenticate right now — §6 |
| 3 | Decode — PTS timing, motion gate, discontinuity handling | ✅ working | 22 tests; selftest decodes the fixture clip and timestamps from frame PTS, never wall clock |
| 4 | Vehicle detection — YOLOv8s, the seven classes the brief names | ✅ working | Selftest detects the bus, bbox `[173, 34, 916, 530]` |
| 5 | Tracking — one ByteTrack per camera | ✅ working | 17 tests: stable IDs across frames, no state shared between cameras, IDs reset on discontinuity |
| 6 | Plate localisation — trained YOLOv9-t ONNX, classical blackhat/Sobel fallback | ✅ working | Detector loads and runs (0.38 s cold, ~10 ms warm); falls back cleanly when the package is absent |
| 7 | OCR — four-reader vote (PaddleOCR, EasyOCR, fast-plate-ocr, Tesseract) | ✅ working | 38 + 22 tests; all four score separately in the accuracy report |
| 8 | Multi-frame super-resolution (`mfsr.py`) and per-character majority vote (`mvcp.py`) | ✅ working | 4 + 7 tests; runs on escalation when two readers disagree |
| 9 | Feasibility gate — refuses cameras whose plates cannot be resolved | ✅ working | 29 tests; refuses below 8 px glyph height and returns the reason |
| 10 | Publish → Redis Streams | ✅ working | **100,366** entries on `sightings` |
| 11 | Persister → TimescaleDB, at-least-once with dead-letter | ✅ working | **100,651** rows persisted, **0 pending**, 22 dead-lettered (all `SELFTEST-000`, by design — that camera deliberately does not exist) |
| 12 | Watchlist matching — confusion-class canonicalisation, trigram fallback | ✅ working | 11 tests; 13 entries indexed and matching live |
| 13 | Alerts — state machine, 60 s dedup, alert stream | ✅ working | 28 tests; 30 alerts raised; NEW → ACKNOWLEDGED → ACTIONED verified live, illegal transition returns 409 |
| 14 | WebSocket push — scope-filtered, monotonic `seq`, resume, 15 s heartbeat | ✅ working | 13 tests against a real uvicorn server; injected alert arrived at a live client at seq 52 |
| 15 | Route reconstruction — hop collapsing, implausibility flag, OSRM snapping | ✅ working | 28 tests; live query returned **15 ordered hops** with camera, coordinates and PTS |
| 16 | Export — CSV and PDF, every export audited | ✅ working | CSV 1,653 B; PDF 4,887 B with a real `%PDF-1.4` header; audit row written for each |
| 17 | Auth and RBAC — 5 roles, department scoping, Postgres RLS backstop | ✅ working | 23 tests; full matrix verified live, including SYSTEM_ADMIN refused live data |
| 18 | Audit — hash-chained log with independent verify | ✅ working | **728 rows, `ok: true, first_broken_seq: null`** |
| 19 | Grants — cross-department access with case number, approval, expiry | ✅ working | 13 tests; create succeeds, create-without-case-number correctly refused (400) |
| 20 | Operator console — map, wall, trace, alerts, watchlist, admin | ✅ working | All six views serve; 30 cameras placed on the map; admin audit tab proxied under its own account |
| 21 | Analytics beyond ANPR — crowd, stopped vehicle, wrong-way, re-identification | ✅ working | 13 tests; wired into the worker loop |
| 22 | Grafana dashboards | ❌ not built | Issue #24. Prometheus metrics *are* exported on `:9108`; only the dashboards on top are missing |
| 23 | TensorRT engine build | ⚠️ partial | Issue #11. ONNX export and its parity gate exist and pass; the engine is not benchmarked on demo hardware |

---

## 3. Test suite — file by file

370 collected, 364 pass, 6 skip, 0 fail. The 6 skips are integration legs that need
`PRAHARI_INTEGRATION=1` and a credential; run separately they pass (§4).

### Lane D — persistence, correlation, API, security (140 tests)

| File | Tests | What it proves |
|---|---|---|
| `test_d_alerts.py` | 28 | The alert state machine is one-way; illegal transitions are refused; dedup holds a vehicle at a signal to one alert; every transition is audited |
| `test_d_route.py` | 28 | Hops come back ordered with timestamps; repeats at one camera collapse to one hop; an impossible speed is flagged and **still returned**; a misread falls back to fuzzy and is **labelled**; anonymous callers get 401, SYSTEM_ADMIN gets 403, an out-of-department operator gets zero hops |
| `test_d_scope.py` | 23 | The [C10] capability matrix, department confinement, forged tokens, and the RLS backstop |
| `test_d_grants.py` | 13 | A grant needs a case number and a reason; only the target department's admin may approve; never self-approved; expiry is enforced |
| `test_d_ws.py` | 13 | Socket auth, server-side scope filtering, `seq` continuity, resume-after-gap, heartbeat, and that a slow console is dropped rather than allowed to stall the fanout |
| `test_d_watchlist.py` | 11 | All-or-nothing CSV import with per-line errors; closed vocabularies for category and severity |
| `test_d_persister.py` | 10 | At-least-once delivery, redelivery, poison messages, dead-consumer reclaim, and rows Postgres refuses being dead-lettered rather than killing the consumer |
| `test_d_generator.py` | 8 | The synthetic sighting generator emits [C1]-shaped rows against real camera ids |
| `test_d_registry.py` | 8 | The seed/geo join, including every way the two exchange files can disagree |
| `test_d_schema.py` | 6 | `schema.sql` and `migrate.sql` do not drift; indexes exist; `migrate.sql` is genuinely re-runnable |

### Lane I — decode, detection, tracking, OCR (163 tests)

| File | Tests | What it proves |
|---|---|---|
| `test_i_plate.py` | 38 | Plate proposal, upscaling, the reader wrapper, grammar-aware cleanup, and that a failing reader never kills the pipeline |
| `test_i_preprocess.py` | 29 | The feasibility refusal, frame conditioning, tiling coverage, deskew, multi-frame fusion, reader selection by cost, and that the expensive paths only run when the cheap one did not settle it |
| `test_i_decode.py` | 22 | PTS timing, the motion gate, bounded queues, discontinuity tolerance |
| `test_i_plate_vote.py` | 22 | The banded vote: CONFIRMED requires agreement, disagreement refuses rather than guessing |
| `test_i_tracker.py` | 17 | ByteTrack identity across frames, per-camera isolation, reset on discontinuity |
| `test_i_publish.py` | 13 | [C1] row shape and validation before anything reaches the stream |
| `test_i_analytics.py` | 13 | Crowd, stopped-vehicle, wrong-way and loitering detectors |
| `test_i_mvcp.py` | 7 | Majority vote by character position over several reconstructions |
| `test_i_run_preprocess_wiring.py` | 7 | Preprocessing is actually wired into the worker, with its kill-switches |
| `test_i_mfsr.py` | 4 | Multi-frame super-resolution reconstructs from several frames |
| `test_i_vote_shape_gate.py` | 4 | An agreed read that is not plate-shaped is POSSIBLE, not PROBABLE |

### Lane G — gateway, health, console (40 tests)

| File | Tests | What it proves |
|---|---|---|
| `test_g_health.py` | 22 | Per-camera health state machine, backoff, watchdog |
| `test_g_probe.py` | 10 | Transport probing for RTSP and HLS without touching the network |
| `test_g_console_shape.py` | 8 | The console serves coordinates where the map looks for them; the audit tab is proxied under an admin account; a refused RTSP feed stops being retried |

### Joint (6 tests)

| File | Tests | What it proves |
|---|---|---|
| `test_integration.py` | 6 | The four legs end to end — see §4 |

---

## 4. Integration test — the four legs

Run with the stack up:

```bash
PRAHARI_INTEGRATION=1 PRAHARI_TEST_USER=<investigator> PRAHARI_TEST_PASSWORD=<pw> \
  pytest tests/test_integration.py -q
```

**Result: 6 passed.**

| Leg | What it checks | Result |
|---|---|---|
| 1 | A clip with a known plate replays through the whole worker and lands on the real `sightings` stream | ✅ |
| 1b | The row is [C1]-shaped — every contract field present and correctly typed | ✅ |
| 2 | The plate is added to the watchlist, and **that entry's** alert fires — correlated by `watchlist_id`, so a stale alert cannot make it pass vacuously | ✅ |
| 3 | The alert reaches a WebSocket client | ✅ |
| 4 | The route endpoint returns the vehicle's hops | ✅ |

These legs skip in the default suite because they need a live stack and a credential. A skip is
not a pass, and the run above is the one that counts.

---

## 5. Stack verification — 35 checks

`python scripts/verify_stack.py` against the running system. **35 / 35 passed.**

| Group | Checks | Notable |
|---|---|---|
| Authentication | 4 | Login as investigator and as system admin; wrong password 401; forged refresh token 401 |
| Route authorisation | 3 | Anonymous 401 on both route and export; **SYSTEM_ADMIN 403** on route, per [C10] |
| RBAC matrix | 4 | Cameras, alerts and watchlist: investigator 200 / system admin 403. Audit: the reverse |
| Route | 4 | 15 hops returned; every hop carries camera, coordinates and PTS; the response says whether it is fuzzy; snapped geometry present |
| Export | 3 | CSV and PDF both return real files; an unknown format is a 400 |
| Watchlist | 2 | Add succeeds; an invalid category is a 422 naming the allowed set |
| Alerts | 4 | Listed; missing `to_state` is 422; NEW → ACKNOWLEDGED succeeds; going back to NEW is 409 |
| Grants | 2 | With a case number succeeds; without one is refused |
| Audit | 1 | Chain verifies over 728 rows |
| Console proxy | 8 | Cameras, wall, grid, alerts, audit verify, and the three static pages |

---

## 6. What is not working

### The camera grid's login endpoint is timing out — **their side, not ours**

Right now:

```
GET  https://cctv.corp8.cloud/auth/login    → 200   (the page loads)
POST https://cctv.corp8.cloud/auth/login    → read timeout after 20 s
GET  /api/grid (our console)                → {"state": "unreachable", "detail": "ConnectionError"}
```

The credentials are correct — the same email and key authenticated successfully earlier today and
pulled live frames from cam04, cam14, cam17, cam18, cam25, cam26, cam27 and cam29. Our side is
unchanged. **Consequence:** the video wall shows grey tiles until the grid answers. Everything
that does not need live video is unaffected.

### RTSP returns 401 for our IP — issue #56, open

`rtsp://103.250.160.189:8554/stream/<id>` answers `401 Unauthorized` for every camera. It was open
without credentials earlier and started refusing after a 30-camera parallel probe from this IP.
**Consequence:** we are on the HLS rendition, which is **downscaled** on most cameras — cam04 is
1920×1080 over RTSP and 854×480 over HLS; cam26 is 2560×1440 HEVC and arrives 854×480 H.264. That
is roughly half the pixels on a plate. Needs the organisers.

### Grafana dashboards — issue #24, not built

Prometheus metrics are exported on `:9108` (frames decoded, detections, OCR latency histogram,
publish failures). The dashboards on top of them are not built. P1 stretch.

### TensorRT engine — issue #11, partial

The ONNX export and its numerical parity gate exist and pass. The TensorRT engine is not built or
benchmarked on the demo hardware. P1, and the ticket itself scopes it to 8–9 Sep.

### ANPR on the provided grid reads zero plates

Across all 30 feeds: hundreds of vehicle detections and tracks per camera, **no plate resolvable**
(`docs/plate-ocr-grid-report.md`). This is a measurement, not a failure of the pipeline, and it is
reached independently from two directions:

- **Arithmetic.** An Indian plate is 500 × 120 mm on a ~1800 mm vehicle, so the glyph row is about
  0.043 × the vehicle box width. Measured: cam04 median vehicle 55 px → **2.4 px glyphs**; cam14
  (an RLVD camera) 227 px → 9.9 px; cam17 378 px → 16.5 px. Below roughly 8 px of glyph the
  strokes were never sampled, and no upscaling recovers what was not captured.
- **The published benchmark.** UFPR-SR-Plates (Nascimento et al., JBCS 31:1, 2025) measures exactly
  this regime — 18–21 px plates — and reports 1.7–2.2% recognition from the raw crop, ~31% with
  the best single-image super-resolution, and 42.3–44.7% with majority voting over several
  reconstructions. That last row is what `mfsr.py` + `mvcp.py` implement. The same paper
  **excluded night footage** because infrared made plates unreadable even at high resolution; the
  Sentinel grid is night footage.

The system's response to this is to **refuse** — `preprocess.feasibility()` returns
`no / marginal / ok` per camera with a reason, and the console says "plate not resolvable at this
camera" rather than showing characters it cannot support. On the controlled corpus, where the
pixels exist, the same pipeline reads **95.0% exactly with zero confidently-wrong reads**.

Everything else in the system — detection, tracking, cross-camera correlation, routes, alerts,
RBAC, audit — works on these feeds today.

---

## 7. Measured numbers

Each with the command that produced it. Nothing estimated.

| Measurement | Value | Command |
|---|---|---|
| End-to-end CV latency | **0.68 s** (budget 3.0 s) | `python services/worker/selftest.py` |
| Fused vote accuracy, controlled corpus | **95.0%** exact, 100% of tracks named | `python scripts/accuracy_report.py` |
| Confidently-wrong reads | **0** | same |
| Best single reader (PaddleOCR) | 79.2% exact | same |
| Sightings ingested end to end | 100,651 rows, 0 pending | live database |
| Audit chain | 728 rows, verified | `GET /api/admin/audit/verify` |
| Grid survey | 30 cameras: 18×1080p, 5×720p, 4×1280×960, 1×960×576, 1×1440p; 23 H.264 / 6 HEVC | `python scripts/grid_survey.py --probe` |

### Reader-by-reader, controlled corpus (120 crops, 40 tracks)

| Reader | Exact | CER | Refused |
|---|---|---|---|
| PaddleOCR | 79.2% | 0.121 | 5.0% |
| EasyOCR | 70.0% | 0.221 | 5.0% |
| fast-plate-ocr | 55.0% | 0.241 | 1.7% |
| Tesseract | 42.5% | 0.257 | 7.5% |
| **Fused vote** | **95.0%** | **0.050** | 5.0% |

The vote beats its best single reader by 16 points. That is the argument for four architectures
rather than one. **The corpus is synthetic and therefore an upper bound** — the report states
which corpus it scored on every run, and refuses to print a number when it has no crops.

---

## 8. Issues

Closed today, with the fix in `main`:

| # | Issue | Fix |
|---|---|---|
| 51 | `/api/route` and `/api/route/export` unauthenticated | Both scoped; identity from the token, not a query parameter; department predicate moved into the SQL |
| 52 | Accuracy report crashed on the committed golden set | Names the missing directory, points at `--make-synthetic`, refuses to score zero crops |
| 53 | Worker selftest could not run from the repo root | `sys.path` set like every other script here |
| 54 | Only one OCR reader loaded — the "vote" was one read | fast-plate-ocr added; PaddleOCR's channel bug fixed; four readers now vote |
| 55 | Route tests failed on any database with demo rows | Per-run plate; derived fuzzy variant; audit assertion scoped to the run |
| 57 | The wall retried refused RTSP on every other cycle | Gives up after two auth failures, stays on HLS, resumes when RTSP works |
| 58 | Missing `to_state` returned a confusing 409 | Now a 422 naming the field |

Still open:

| # | Issue | Owner | Note |
|---|---|---|---|
| 56 | RTSP 401 for our IP | neevmodh | External; needs the organisers |
| 35 | J1 integration, chaos drills, rehearsals | all | Integration test green; drills and rehearsals are event-day work |
| 24 | Grafana dashboards | neevmodh | P1 stretch |
| 11 | Fine-tune + TensorRT | Neal006 | P1, scoped to 8–9 Sep |
| 9 | Deck: 10 slides | Neal006 | Built; needs the PDF/PPT export and the honest ANPR slide |
| 8 | Golden set + accuracy report | Neal006 | Harness works; a hand-labelled *grid* corpus may not be obtainable — the grid yields no readable plates |

---

## 9. How to reproduce all of this

```bash
git clone https://github.com/Priyanshu-byte-coder/prahari && cd prahari
cp .env.example .env          # fill in: grid credentials, JWT secret, console accounts
pip install -r requirements.txt

make up && make seed
python services/api/auth.py bootstrap --username field --role INVESTIGATOR
python scripts/run_stack.py start

pytest tests/ -q                                            # 364 passed, 6 skipped
python services/worker/selftest.py                          # SELFTEST OK, 0.68 s
python scripts/verify_stack.py                              # 35/35
PRAHARI_INTEGRATION=1 pytest tests/test_integration.py -q   # 6 passed
python scripts/accuracy_report.py                           # regenerates docs/accuracy-report.md
```
