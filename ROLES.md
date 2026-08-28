# ROLES — who owns what

Two people, one repo, minimal collision. The split is drawn along file
boundaries, not just verbal agreement, so both of you can work for days
without touching the same file. Read [CONTEXT.md](CONTEXT.md) first for
current state; this file only says who does the next piece.

---

## The split

**Priyanshu — grid, buffering, tracking.** Everything between "a camera
exists" and "here is a labelled vehicle box with a stable track id."

**You — number plates, OCR, search.** Everything between "here is a vehicle
box" and "here is a validated plate string, searchable and fused across
frames."

The boundary is one function call. `run_worker.py` calls
`plates.observe(track_id, frame.image, bbox)` and gets back `str | None`.
Neither side needs to read the other's internals to work.

---

## File ownership

| Owns | Priyanshu | You |
|---|---|---|
| `services/worker/stream_reader.py` | ✅ PTS, reconnect, backoff, discontinuity | |
| `services/worker/vehicle_tracker.py` | ✅ YOLO detection, ByteTrack | |
| `services/worker/bytetrack_traffic.yaml` | ✅ tracker tuning | |
| `services/worker/run_worker.py` | ✅ orchestration (calls `plates.observe()` as a black box) | |
| `services/api/gateway.py` | ✅ stream relay, cookie session | |
| `services/api/main.py` — registry/GIS/camera endpoints |  | |
| `services/worker/plate_reader.py` | | ✅ detector, OCR, `PlateReader` vote fusion |
| `services/api/main.py` — `/api/search/plate` | | ✅ (extract to its own router — see below) |
| Plate format validation (RTO state codes) | | ✅ |
| Watchlist fuzzy matching | | ✅ (once built) |

**Shared, touch by agreement only:** `web/` (console UI), `CONTEXT.md`
(both update the section that's actually yours), `requirements.txt` (append,
don't reorder).

---

## The interface contract (this is what makes independence possible)

```python
from services.worker.plate_reader import PlateReader

plates = PlateReader()                          # once, at worker startup
plate = plates.observe(track_id, image, bbox)    # once per track per frame -> str | None
plates.reset()                                   # on stream discontinuity
```

That's the entire surface. If you change what's *inside* `PlateReader`
(swap the detector, change OCR engine, tune the vote count), Priyanshu's
code doesn't change. If he changes tracker buffer size, detection model, or
reconnect logic, your code doesn't change. If either of you needs to change
the *signature* of `observe()`, that's the one conversation you must have
before merging.

Next refactor worth doing (either of you): extract `/api/search/plate` and
`/api/detections/{id}` plate-adjacent fields into their own
`services/api/plate_routes.py` `APIRouter`, mounted in `main.py` the same
way `gateway_router` already is. Right now the plate search endpoint lives
inside `main.py`, which both of you would otherwise need to edit.

---

## Current state (2026-08-28)

**Working, Priyanshu's side:** stream reader, vehicle detection + tracking,
gateway. Verified live: sane per-class unique-vehicle counts, no runaway
track-id churn after the ByteTrack buffer fix (CONTEXT.md D9).

**Not working yet, your side:** plate OCR. Measured across 22 cameras,
~1,500 vehicle-level attempts, effectively zero genuine reads with the
current whole-vehicle-crop approach. Root cause found: EasyOCR splits a
plate into multiple text fragments; the current code only accepts a single
fragment matching the full plate regex, so real partial reads (a state code,
a digit group) get thrown away instead of merged.

**Your starting point:** a real, verified, MIT-licensed plate detector —
`Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8`
(6.24MB weights, single class `license_plate`, loads cleanly, live-tested
against this grid at up to 0.75 confidence). A different widely-cited
"94.5% accuracy" repo was checked and is fake (2-byte weights file) — don't
waste time on it. Full detail in CONTEXT.md §6 (D13).

---

## Your task list (plate/OCR side)

1. Wire the real plate detector into `plate_reader.py`, replacing the
   whole-vehicle-crop heuristic with a tight plate-region crop.
2. Fix fragment merging: EasyOCR returns multiple text pieces per plate:
   sort by bbox x-position, concatenate, then validate the merged string
   against `PLATE_RE`.
3. Add RTO state-code validation (`GJ`, `MH`, `RJ`, ... — PLAN.md §4.2)
   so a shape-valid but nonsense read (e.g. `LQ07209`, not a real state
   code) gets rejected instead of surfacing as a false positive.
4. Re-run the same 22-camera measurement CONTEXT.md documents and record
   the new numbers — replace the "zero reads" finding with real data,
   whatever it turns out to be. Don't claim success without measuring it.
5. Once reads are real: confusion-class character repair (`0↔O`, `1↔I`,
   `8↔B` — PLAN.md §4.2), then hand off to watchlist fuzzy matching.

## Priyanshu's task list (grid/buffer side)

1. RTSP-on-hotspot test (still open, CONTEXT.md §8 — blocks the ingestion
   decision).
2. Extend `run_worker.py` to run more than one camera concurrently (process
   pool or asyncio) — right now it's one camera per process, started by
   hand.
3. Postgres/PostGIS/Timescale migration, replacing JSON-on-disk.
4. Camera health / NOC dashboard.
5. Watch for whether ByteTrack's 90-frame buffer (D9) needs further tuning
   as more cameras come online — motorcycles were still the highest-churn
   class in testing.

---

## Merge discipline

- `git pull` before starting a session — `services/worker/` and the API
  routes are being built by both of you now.
- Commit inside your own files freely. A PR that touches both `plate_reader.py`
  and `vehicle_tracker.py` in the same commit is a signal the boundary broke
  somewhere — worth a quick sync before merging.
- If you need something from the other side's output (e.g. you need a new
  field on `VehicleTrack`), ask for it as an interface change, not a direct
  edit to their file.
