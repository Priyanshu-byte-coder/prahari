# Prahari

**Cross-camera vehicle tracking for the Gujarat Police CCTV grid.**
A vehicle passes a camera. Within a couple of seconds its plate is read, checked against a
watchlist, and pushed to every console allowed to see that camera. Later, an investigator types
the plate and gets an ordered, timestamped route across the network — exportable, audited, and
labelled when the system is guessing.

Built for [SENTINEL 2026](docs/brief-sentinel-hackathon.md), the Gujarat Home Department / SCRB
CCTV integration hackathon. Open source end to end, no vendor lock-in, no component that needs a
licence to run.

<!-- SCREENSHOT: the console's live map with the 30-camera grid and an open alert -->

---

## The idea in one paragraph

Twenty-six government departments run their own CCTV, their own VMS, their own storage. Nobody
proposes replacing that — it would take years and a budget nobody has. Prahari leaves every
existing system in place and adds one thing on top: **a sighting**. Roughly 200 bytes describing
one vehicle at one camera over a short interval. Video never leaves the department that owns it;
sightings are what cross the boundary, and sightings are what get correlated, searched and
audited. That is the whole architecture, and it is why the scale path from 30 cameras to 80,000
is a capacity problem rather than a redesign.

**Architecture model: hybrid M1 + M2 + M3.** A central registry and GIS layer (M1) over a
metadata analytics plane (M2), federated to existing VMS through a thin driver layer (M3). No
central VMS (M4) — that is the model that requires ripping out what departments already paid for.

```
 cameras ──► gateway ──► worker ──► sightings stream ──┬──► persister ──► TimescaleDB
 (RTSP/HLS)  (transport  (decode,   (Redis Streams)    │                  hypertable
              probe,      detect,                      ├──► matcher ────► alerts stream
              health)     track, OCR)                  │                        │
                                                       └──► WS fanout ◄─────────┘
                                                                  │
                                                            consoles (map, wall,
                                                            trace, alerts, admin)
```

---

## What is actually built

| Capability | State | Where |
|---|---|---|
| Ingest from RTSP / HLS / ONVIF, transport probing, per-camera health | working | `services/gateway/` |
| Decode on PTS, motion gate, YOLOv8s detection, ByteTrack per camera | working | `services/worker/` |
| Plate read: 4-reader vote (PaddleOCR · EasyOCR · fast-plate-ocr · Tesseract) + Indian-plate grammar | working | `services/worker/plate.py`, `common/plate.py` |
| Trained plate detector (YOLOv9-t ONNX), multi-frame super-resolution, per-character majority vote | working | `services/worker/{mfsr,mvcp}.py` |
| Frame + crop conditioning, per-camera OCR feasibility gate, multi-frame fusion | working | `services/worker/preprocess.py` |
| Sightings → Redis Streams → TimescaleDB hypertable, at-least-once with dead-letter | working | `services/api/persister.py` |
| Watchlist match with confusion-class canonicalisation and banded confidence | working | `services/api/matcher.py` |
| Alerts with a state machine, dedup, and a WebSocket push to consoles | working | `services/api/alerts.py`, `ws.py` |
| Cross-camera route reconstruction, implausibility flagging, OSRM snapping | working | `services/api/route.py` |
| CSV / PDF export, every export audited | working | `services/api/export.py` |
| RBAC across 5 roles, department scoping, Postgres RLS backstop | working | `services/api/scope.py`, `auth.py` |
| Hash-chained audit log with an independent verify endpoint | working | `services/api/audit.py` |
| Cross-department access grants (case number + approval + expiry) | working | `services/api/grants.py` |
| Operator console: map, video wall, trace, alerts, watchlist, admin | working | `web/` |
| Re-identification embeddings, crowd/stopped/wrong-way analytics | working | `services/worker/reid.py`, `analytics.py` |
| ONNX export + parity gate; TensorRT path | partial | `services/worker/export_onnx.py` |
| Grafana dashboards | not built | see [what is not built](#what-is-not-built) |

---

## Quickstart

**Requires:** Docker, Python 3.12, ffmpeg on PATH.

```bash
git clone https://github.com/Priyanshu-byte-coder/prahari && cd prahari
cp .env.example .env                 # then edit: grid credentials, JWT secret
pip install -r requirements.txt

make up                              # postgres+timescale, redis, minio, osrm
make seed                            # schema + the 30-camera registry
python services/api/auth.py bootstrap --username admin --role SYSTEM_ADMIN
python services/api/auth.py bootstrap --username field --role INVESTIGATOR
```

Then, in separate shells:

```bash
python scripts/run_stack.py start     # API, console, persister, matcher - with health checks
```

That starts four processes and waits until they answer; `status` and `stop` do what they say.
To run them yourself, one per terminal — which is what to do for a demo, so a crash is visible
rather than buried in a log:

```bash
python -m uvicorn --factory services.api.main:factory --host 127.0.0.1 --port 8000   # API + WS
python scripts/console_serve.py --port 5173                                          # console
python services/api/persister.py                                                     # stream → DB
python services/api/matcher.py                                                       # DB → alerts
```

Open **http://127.0.0.1:5173/**.

To drive it without live cameras — the same path a real sighting takes, only the source is
synthetic:

```bash
python scripts/fake_sightings.py --rate 5 --duration 600
```

To prove the computer-vision path end to end on a real clip:

```bash
python services/worker/selftest.py      # decode → detect → track → OCR → publish, with a budget
```

---

## The judged test case

*"Given a vehicle registration number, produce the full route history across the grid."*

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"field","password":"..."}' | python -c 'import sys,json;print(json.load(sys.stdin)["access"])')

curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8000/api/route?plate=GJ01AB1234" | python -m json.tool
```

Returns ordered hops — camera, name, coordinates, PTS timestamp, confidence band, crop URL — plus
a road-snapped polyline. Or in the console: **Trace → type the plate**.

Three things this endpoint does that a demo usually does not:

- **It says when it is guessing.** No exact match falls back to a fuzzy search over
  confusion-collapsed plate keys, and the response is labelled `fuzzy: "fuzzy match; verify plate"`.
- **It flags the impossible.** Two sightings 200 km apart a minute later imply 12,000 km/h. That
  hop is returned marked `IMPLAUSIBLE` rather than quietly dropped — a dropped hop is a lie of
  omission, and the operator is the one who should decide.
- **It refuses what it may not show.** The department predicate is in the SQL, so hops another
  department owns are never in the process, let alone in the response.

---

## Honest numbers

Everything below is a measurement with a command beside it. Nothing here is estimated.

**The grid, surveyed** (`python scripts/grid_survey.py --probe`, 30 cameras, 2026-09-03 →
[`data/grid_survey.json`](data/grid_survey.json)):

| | |
|---|---|
| Resolution | 18 × 1920×1080, 5 × 1280×720, 4 × 1280×960, 1 × 960×576, 1 × 2560×1440 |
| Codec | 23 H.264, 6 HEVC |
| Frame rate | 25 fps mostly; 50, 20, 13 and 12 fps outliers |

**What that means for ANPR.** An Indian plate is 500 × 120 mm on a ~1800 mm vehicle, so the glyph
row is about **0.043 × the vehicle box width**. Measured on real frames:

| camera | median vehicle box | glyph height | verdict |
|---|---|---|---|
| cam17 Rajkot | 378 px | 16.5 px | readable |
| cam14 Delight RLVD | 227 px | 9.9 px | marginal |
| cam04 Paldi Circle | 55 px | **2.4 px** | not resolvable |

A vehicle box under ~325 px wide cannot yield a 14 px glyph, and no upscaling recovers a stroke
that was never sampled. So `preprocess.feasibility()` **refuses per camera and says why**, and the
console shows "plate not resolvable at this camera" instead of four confident characters of noise.
A wrong plate on a police report is worse than no plate. That single decision is the most
important line of engineering in this repo.

**Pipeline latency** (`python services/worker/selftest.py`): decode → detect → track → OCR →
publish in **0.61 s** against a 3.0 s budget, plate read back exactly.

**Accuracy** — `python scripts/accuracy_report.py` → [`docs/accuracy-report.md`](docs/accuracy-report.md).
120 crops over 40 tracks, all four readers:

| reader | exact match | CER | refused |
|---|---|---|---|
| paddleocr | 79.2% | 0.121 | 5.0% |
| easyocr | 70.0% | 0.221 | 5.0% |
| fast-plate-ocr | 55.0% | 0.241 | 1.7% |
| tesseract | 42.5% | 0.257 | 7.5% |
| **fused vote (what the pipeline emits)** | **95.0%** | **0.050** | 5.0% |

CONFIRMED covers 95% of tracks at **100% precision — zero confidently-wrong reads**. The vote
beats its best single reader by 16 points, which is the whole argument for four architectures
instead of one. *This corpus is synthetic and therefore an upper bound*; the report prints which
corpus it scored on every run and refuses to print a number when it has none.

**Low-resolution behaviour** — [`docs/lr-benchmark.md`](docs/lr-benchmark.md), measured against
the published UFPR-SR-Plates benchmark (Nascimento et al., JBCS 31:1, 2025), whose low-resolution
plates are 18–21 px tall, like the grid's:

| condition | recognition |
|---|---|
| low-res crop straight to OCR | 1.7 – 2.2% |
| + best single-image super-resolution | 29.9 – 31.1% |
| + majority vote by character position over several reconstructions | **42.3 – 44.7%** |

That last row is the design: `mfsr.py` builds several reconstructions and `mvcp.py` decides per
character position. Worth knowing that the paper *excluded night footage* because infrared made
plates unreadable even at high resolution — and the Sentinel grid is night footage.

**On the live grid, we read zero plates** ([`docs/plate-ocr-grid-report.md`](docs/plate-ocr-grid-report.md)).
All 30 feeds, hundreds of vehicle detections and tracks per camera, no plate resolvable — cam30
276 detections / 0 plates, cam04 123 / 0, cam05 107 / 0. That is the same conclusion the pixel
arithmetic above reaches from the other end, and it is stated here rather than buried: **these
cameras are placed for scene overview, not plate capture.** What would change it is an
enforcement-framed camera or the operators' own RLVD plate snapshots, neither of which is in the
public feed. Everything else in this system — tracking, correlation, routes, alerts, audit —
works on the grid today; ANPR needs a camera pointed at a plate.

**Latency** — `python services/worker/selftest.py`: decode → detect → track → OCR → publish in
**0.68 s** against a 3.0 s budget, plate read back exactly, band CONFIRMED. The expensive paths
(multi-frame super-resolution, multi-reconstruction voting) escalate only when two readers have
not already agreed, so a hard plate gets all of it and an easy one is not made to wait for it.

**Tests**: `pytest tests/ -q` → **348 passed, 6 skipped**. CI runs the same suite against real
Postgres and Redis service containers on every push.

---

## Security

- **Five roles**, and the interesting one is System Admin: it administers the platform and **cannot
  view live video or routes**. Enforced in one capability table (`services/api/scope.py`) that the
  API, the WebSocket and the SQL all read from.
- **Department scoping** on every query, with **Postgres row-level security** as a backstop — a
  query somebody forgets to scope still cannot return another department's rows.
- **Server-side filtering, never client-side.** A console that receives frames it must not show has
  already leaked them; the fanout filters before the frame reaches the wire.
- **Hash-chained audit log.** `hash = sha256(prev_hash || canonical_json(fields))`, verifiable by
  anyone through `GET /api/admin/audit/verify` — including edits made directly in the database.
- **Cross-department access is a grant**, not a role: case number and reason required, approved by
  the owning department's admin, never self-approved, expires in ≤72 h.
- Argon2id passwords, 15-minute access tokens, 8-hour refresh, presigned crop URLs that expire.

Read [`docs/hld.md` §8–9](docs/hld.md) for the full model, including the privacy answer.

---

## Documentation

| Document | What it is |
|---|---|
| [`docs/hld.md`](docs/hld.md) | High-level design — integration, correlation, alerts, security, scale tiers, failure modes |
| [`docs/project-overview.md`](docs/project-overview.md) | The whole project in plain language, for a non-specialist reader |
| [`docs/api.md`](docs/api.md) | Every endpoint, with roles, request and response |
| [`docs/operations.md`](docs/operations.md) | Run it, watch it, recover it — ports, health, failure playbook |
| [`docs/video-script.md`](docs/video-script.md) | The 3-minute submission video, shot by shot |
| [`docs/demo-script.md`](docs/demo-script.md) | The live 8-minute demo, with the drills |
| [`docs/model-card.md`](docs/model-card.md) | Models used, training provenance, known failure modes |
| [`docs/lr-benchmark.md`](docs/lr-benchmark.md) | What a 20 px plate can and cannot yield, against the published benchmark |
| [`docs/plate-ocr-grid-report.md`](docs/plate-ocr-grid-report.md) | The full 30-camera run: what was detected, what was readable, and why |
| [`docs/submission.md`](docs/submission.md) | Deliverables checklist and what remains |
| [`docs/deck.html`](docs/deck.html) | The 10-slide presentation |

---

## Repository map

```
common/          plate grammar and canonicalisation shared by worker and API
db/              schema.sql (contract copy) and migrate.sql (the one that runs)
services/
  gateway/       camera drivers, transport probing, health, video wall
  worker/        decode, detect, track, OCR, preprocessing, analytics, publish
  api/           persistence, matching, alerts, route, export, RBAC, audit, grants, WS
web/             the operator console (vanilla JS + Leaflet, no build step)
scripts/         registry loader, sighting generator, grid survey, accuracy report
tests/           348 tests; one per claim the system makes
infra/           docker-compose for postgres+timescale, redis, minio, osrm
docs/            design, operations, submission material
```

## What is not built

Stated plainly, because a system that overstates itself is worse than a smaller one that does not:

- **Face recognition** — deliberately out of scope. It is optional in the brief and carries a
  privacy cost this design does not want to argue for by accident.
- **Grafana dashboards** — Prometheus metrics are exported (`/metrics` on the worker); the
  dashboards on top are not built.
- **TensorRT engine build** — the ONNX export and its parity gate exist; the TensorRT path is
  written but not benchmarked on the demo hardware.
- **Live RTSP from the provided grid** — the grid answers 401 on RTSP for our IP; everything runs
  through the HLS path, which is a downscaled rendition on most cameras. Tracked as issue #56.
- **The golden accuracy corpus** — the harness is built and runs; the hand-labelled grid crops are
  not committed (crops are personal data). `--make-synthetic` generates a stand-in and the report
  says which corpus it scored.

## Licence

[Apache-2.0](LICENSE). Open-source dependencies only; every one is listed in
[`requirements.txt`](requirements.txt) with a note on why it is there.
