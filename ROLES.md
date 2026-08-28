# ROLES — who owns what

Two people, one repository, minimal collision. The split is drawn along **file
boundaries**, not verbal agreement, so both can work for days without touching
the same file.

Read [CONTEXT.md](CONTEXT.md) first for current state and measured facts.
[STATUS.md](STATUS.md) is the one-table task tracker. This file only says who
owns which code and who does the next piece.

> **Writing convention — third person, always.** Every document in this repo
> names people explicitly: *Priyanshu*, *Neev*. Second person is banned. Both
> team members work with their own AI coding sessions, and those sessions read
> these files as instructions; "you" resolves differently depending on which
> session is reading, which has already caused confusion once. A sentence in
> any repo document must mean the same thing to every reader.

---

## 1. The people

| | Priyanshu Doshi | Neev Modh |
|---|---|---|
| GitHub | `Priyanshu-byte-coder` | `neevmodh` |
| Environment | Windows, CUDA GPU available, Python 3.12 | macOS, no CUDA, Python 3.14 |
| Repo role | Owner of the GitHub repository | Collaborator |
| Lane | **Grid, ingestion, tracking, platform** | **Number plates, OCR, plate search** |

The environment difference is not cosmetic. Only one side has CUDA, so GPU
inference and any training happen there; and the other side's Python version
has no `paddlepaddle` wheel, which is why EasyOCR was chosen (CONTEXT.md D11).
Any dependency added to `requirements.txt` must install on both, or be
documented as environment-specific.

---

## 2. The split, in one line each

**Priyanshu owns everything between "a camera exists" and "here is a labelled
vehicle box with a stable track id."**

**Neev owns everything between "here is a vehicle box" and "here is a
validated plate string, searchable and fused across frames."**

The boundary is a single function call. `run_worker.py` calls
`plates.observe(track_id, frame.image, bbox)` and receives `str | None`.
Neither side needs to read the other's internals.

---

## 3. File ownership

| File / area | Owner | Scope |
|---|---|---|
| `services/worker/stream_reader.py` | **Priyanshu** | PTS timing, reconnect, backoff, discontinuity detection |
| `services/worker/vehicle_tracker.py` | **Priyanshu** | YOLO vehicle detection, ByteTrack integration |
| `services/worker/bytetrack_traffic.yaml` | **Priyanshu** | Tracker tuning (occlusion buffer, thresholds) |
| `services/worker/run_worker.py` | **Priyanshu** | Orchestration; treats `plates.observe()` as a black box |
| `services/api/gateway.py` | **Priyanshu** | Stream relay, upstream cookie session, HLS rewriting |
| `services/api/main.py` — registry, GIS, camera, detections endpoints | **Priyanshu** | Model 1 surface |
| `scripts/*.py` | **Priyanshu** | Probe, survey, geocode, snapshot tooling |
| `infra/` | **Priyanshu** | MediaMTX local grid clone |
| `services/worker/plate_reader.py` | **Neev** | Plate detector, OCR, `PlateReader` vote fusion |
| `services/api/plate_routes.py` *(to be extracted)* | **Neev** | `/api/search/plate` and plate-adjacent fields |
| Plate format validation, RTO state codes | **Neev** | |
| Watchlist fuzzy matching | **Neev** | Once the watchlist exists |

**Shared — touch by agreement only:**

| File | Rule |
|---|---|
| `web/` (console UI) | Both may edit. Announce before a large restructure; small additions are fine. |
| `CONTEXT.md` | Both update, but only the sections describing their own work. |
| `STATUS.md` | Both update their own rows. |
| `requirements.txt` | **Append only, never reorder** — reordering guarantees a conflict. |
| `PLAN.md`, `README.md`, `ROLES.md` | Priyanshu is editor of record; Neev proposes changes. |

### Pending refactor (either may do, Neev preferred)

`/api/search/plate` and the plate-adjacent fields of `/api/detections/{id}`
currently live inside `services/api/main.py`, which is Priyanshu's file. They
should be extracted into `services/api/plate_routes.py` as its own
`APIRouter`, mounted in `main.py` exactly as `gateway_router` already is.
Until that extraction happens, `main.py` is the one file both lanes must edit,
and it is the most likely source of a merge conflict.

---

## 4. The interface contract

This is what makes independent work possible. It is the only surface either
side may depend on.

```python
from services.worker.plate_reader import PlateReader

plates = PlateReader()                            # once, at worker startup
plate = plates.observe(track_id, image, bbox)     # per track per frame -> str | None
plates.reset()                                    # on stream discontinuity
```

- If Neev changes what is *inside* `PlateReader` — swaps the detector, changes
  OCR engine, tunes the vote count — Priyanshu's code does not change.
- If Priyanshu changes tracker buffer size, detection model, or reconnect
  logic, Neev's code does not change.
- **Changing the signature of `observe()` is the one change that requires a
  conversation before merging.**

If either side needs new data from the other — for example Neev needing a new
field on a vehicle track — it is requested as an interface change, never made
as a direct edit to the other's file.

---

## 5. Current state per lane (2026-08-28)

### Priyanshu's lane — working
Stream reader (PTS-driven, TCP-forced, backoff reconnect, discontinuity
detection), YOLOv8s vehicle detection, ByteTrack tracking, stream gateway,
camera registry, GIS map, operator console with live box overlay. Verified
live against the real grid: per-class unique-vehicle counts are sane and
track-id churn stopped after the ByteTrack occlusion buffer was raised from 30
to 90 frames (CONTEXT.md D9).

### Priyanshu's lane — not done
Multi-camera concurrency (one process per camera, started by hand), the
RTSP-on-hotspot test, database migration, health dashboard.

### Neev's lane — not working yet
Plate OCR produces effectively **zero genuine reads** across roughly 1,500
vehicle-level attempts on 22 cameras. Root cause is identified but not fixed:
EasyOCR returns a plate as several separate text fragments, and the current
code only accepts a single fragment matching the full plate regex, so real
partial reads — a state code, a digit group — are discarded instead of merged.

### Neev's starting point
A verified, MIT-licensed plate detector:
`Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8`
(6.24 MB weights, single class `license_plate`, loads cleanly, live-tested
against this grid at up to 0.75 confidence). A widely-cited "94.5% accuracy"
alternative was checked and is **fake** — its committed weights file is 2
bytes. Detail in CONTEXT.md D13.

---

## 6. Task lists

### Neev — plate and OCR lane
1. Wire the real plate detector into `plate_reader.py`, replacing the
   whole-vehicle-crop heuristic with a tight plate-region crop.
2. Fix fragment merging: sort EasyOCR fragments by bounding-box x-position,
   concatenate, then validate the merged string against `PLATE_RE`.
3. Add RTO state-code validation (`GJ`, `MH`, `RJ`, … — PLAN.md §4.2) so a
   shape-valid but nonsense read such as `LQ07209` is rejected rather than
   surfaced as a false positive.
4. Re-run the same 22-camera measurement and record the new numbers in
   CONTEXT.md, replacing the "zero reads" finding with real data — whatever it
   turns out to be. Success is not claimed without a measurement.
5. Once reads are real: confusion-class character repair (`0↔O`, `1↔I`, `8↔B`
   — PLAN.md §4.2), then hand off to watchlist fuzzy matching.
6. Extract `plate_routes.py` (§3) to remove the last shared-file conflict.

### Priyanshu — grid and platform lane
1. **RTSP-on-hotspot test** — still open, blocks the ingestion-path decision.
   The only task on this list that cannot be delegated to a coding session.
2. Multi-camera concurrent workers — process pool or asyncio, replacing the
   current one-process-per-camera-by-hand arrangement.
3. Postgres + PostGIS + TimescaleDB migration, replacing JSON-on-disk.
4. Camera health / NOC dashboard.
5. Monitor whether ByteTrack's 90-frame buffer needs further tuning as more
   cameras come online; motorcycles remain the highest-churn class.

---

## 7. Unassigned work — the real risk

STATUS.md previously listed 16 tasks with no owner. Priyanshu **confirmed the
assignment below on 2026-08-28**; it is reproduced here for reference, and the
day-by-day sequencing lives in [WORKPLAN.md](WORKPLAN.md).

Four tasks still have no owner — the HLD, the deck and both demo videos — and
they are scored evaluation areas, not nice-to-haves. WORKPLAN.md §5 sets out
the options.

| Task | Owner | Reasoning |
|---|---|---|
| Cross-camera route reconstruction | **Priyanshu** | Consumes camera geo and PTS, both in his lane. **This is mandatory gate G3.** |
| Spatio-temporal plausibility filter | **Priyanshu** | Same data, same lane |
| Alert engine, WebSocket push, ack/dismiss | **Priyanshu** | Backend/API lane |
| Watchlist DB, admin UI, CSV import | **Neev** | Plate-domain data model |
| Fuzzy watchlist matching + confidence bands | **Neev** | Direct extension of his existing Levenshtein matcher |
| PDF/CSV route report export | **Priyanshu** | Required submission artifact |
| Vehicle Re-ID fallback | **Priyanshu** | Operates on vehicle crops, before the plate boundary |
| RBAC + department scoping | **Priyanshu** | API surface |
| Hash-chained audit log | **Priyanshu** | API surface |
| `scripts/preflight.py` | **Priyanshu** | Owns `scripts/` |
| Public deployment + test credentials | **Priyanshu** | Owns infra |
| Docker Compose one-command bring-up | **Priyanshu** | Owns infra |
| HLD document | **Unassigned — WORKPLAN.md §5** | Large; neither lane has slack |
| 14-slide PPT | **Unassigned — WORKPLAN.md §5** | |
| Demo Video A (own footage) | **Unassigned — WORKPLAN.md §5** | Needs footage Priyanshu must record |
| Demo Video B (govt feed + output report) | **Unassigned — WORKPLAN.md §5** | Depends on working ANPR |

**The documents and videos are not optional.** The organisers' evaluation
framework scores "Solution Presentation", "Solution Architecture" and
"Submission Completeness" as three of seven areas, and explicitly rejects
submissions whose demonstrations are not of working software. A perfect
platform with no deck and no video scores badly.

**Recommended action:** recruit a third team member for documents, deck and
video editing, or Priyanshu formally reserves 4–5 September for documentation
and cuts scope elsewhere. Category 1 permits student teams; team size cap is
still an open question with the organisers (CONTEXT.md §7).

### Proposed scope triage if the team stays at two

Ranked by what the evaluation framework actually rewards:

**Must ship — these are scored gates**
Working ANPR producing real reads · cross-camera route with timestamps ·
watchlist matching with live alerts · HLD document · PPT · both demo videos ·
public URL with test credentials.

**Ship if time allows**
Postgres migration (JSON-on-disk demos identically) · RBAC · audit log ·
NOC dashboard · Docker Compose.

**Cut without regret**
Vehicle Re-ID fallback · Kafka · OpenSearch · anything in PLAN.md §4.5 beyond
the mandatory ANPR.

The Postgres migration in particular is worth questioning: it consumes a day
and changes nothing a judge can see. JSON-on-disk is defensible in a
prototype, and the HLD can state Postgres/PostGIS/Timescale as the production
data layer without it being implemented for the sandbox round.

---

## 8. Merge discipline

- **`git pull` before starting every session.** `services/worker/` and the API
  routes are now being edited by both lanes.
- Commit freely inside owned files.
- A commit that touches both `plate_reader.py` and `vehicle_tracker.py` is a
  signal that the boundary broke somewhere — worth a sync before merging.
- Neither side edits the other's files to "quickly fix" something. Requesting
  an interface change costs a message; an unexpected edit costs a merge
  conflict and a broken assumption.
- `CONTEXT.md` §9 changelog gets one row per commit, and the header block
  (`Last updated`, `HEAD`, days remaining) is updated in the same commit.

## 9. Coordination protocol

- **Blocking questions** go to the other person directly, not into a TODO
  comment in code that the other person may never read.
- **Findings that change the other lane's assumptions** — a grid behaviour
  change, a model that turns out to be fake, a measurement that contradicts an
  earlier claim — go into CONTEXT.md §3 or §6 immediately, because that file
  is what each side's AI session reads at the start of a session.
- **Never claim a capability works without a measurement recorded in
  CONTEXT.md.** The "zero reads across 1,500 attempts" entry is exactly the
  kind of honesty that keeps the other lane from building on sand.
