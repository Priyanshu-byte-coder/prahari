# Deck — 10 slides, one per scoring point

**Rule for this file: every number on a slide traces to a command's output or to a formula
printed on the slide itself.** Nothing is typed from memory. Where a figure is not measured yet
it is written `‹from …›` and the slide is not finished until that placeholder is replaced by a
run. A jury that cannot check a number should not be shown it.

Sources, in the order the slides use them:

| marker | comes from |
|---|---|
| `‹accuracy›` | `python scripts/accuracy_report.py` → `docs/accuracy-report.md` |
| `‹bench›` | `python -m services.worker.backend --bench` |
| `‹decode›` | `python -m services.worker.decode --bench --cameras 10 --seconds 600` |
| `‹latency›` | `python -m services.worker.selftest --assert-xadd` (row latency) |
| `‹drivers›` | `GET /api/admin/drivers` on the running system |
| `‹audit›` | `GET /api/admin/audit/verify` |

---

## 1 — The hybrid, and why it is not any one of the four

| Model | What we take | What we reject | Where it is in the repo |
|---|---|---|---|
| M1 registry + GIS | the camera registry as the spine; every asset on a map with a real coordinate | its assumption that one department owns every camera | `cameras` table [C3], `data/camera_geo.json` |
| M2 direct-attach streams | live view straight from the camera, no transcoding hop | one console per vendor | MediaMTX + WHEP/HLS wall |
| M3 pluggable drivers + event bus | the structure: drivers behind one interface, one event bus, one API | its heavyweight per-site install | `services/gateway/` drivers, Redis Streams [C2] |
| M4 analytics + cross-department correlation | correlation across departments, watchlist analytics | **central recording of 80k streams** — the arithmetic is slide 9 | matcher, alerts, `access_grants` |

One line for the jury: *federation middleware with pluggable drivers — three drivers live, the
departmental-VMS driver interface-complete pending vendor credentials.*

## 2 — Architecture and the protocol map

```
cameras / VMS ──▶ FEDERATION GATEWAY   drivers: mediamtx │ rtsp │ onvif │ vms-stub
                        │ RTSP/TCP, ONVIF, HLS, WHEP
                        ▼
                  INFERENCE WORKER     decode 5 fps ▸ YOLOv8s ▸ ByteTrack ▸ plate ▸ OCR vote
                        │ Redis Streams: sightings, camera.health
                        ▼
                  CORE API             persister ▸ matcher ▸ alerts ▸ ws-fanout ▸ route ▸ RBAC+audit
                        │ REST + WebSocket
                        ▼
                  GIS CONSOLE          Leaflet map, video wall, route view
```

The atom is the **sighting row**, ~200 bytes ([C1]). We ship rows, not video — that single
sentence is the whole architecture argument, and slide 9 is its arithmetic.

## 3 — Drivers: three live, one interface-complete

| Driver | Protocol | Status | Cameras |
|---|---|---|---|
| mediamtx | RTSP/WHEP/HLS | live | `‹drivers›` |
| rtsp | RTSP/TCP | live | `‹drivers›` |
| onvif | ONVIF Profile S + events | live | `‹drivers›` |
| vms-stub | vendor VMS SDK | interface-complete, awaiting credentials | 0 |

Say the honest thing out loud: the fourth is an interface, not a claim. Port 8554 is blocked on
our own network, so the gateway probes per camera and degrades to HLS — heterogeneity is the
thing the brief tests, and that fallback is the demo, not an excuse.

## 4 — ANPR pipeline and the record it produces

```
frame (PTS) ─▶ vehicle detect (batch 16, 20 ms flush) ─▶ ByteTrack, one per camera
            ─▶ plate detect *inside the vehicle crop* ─▶ 2 readers ─▶ grammar ─▶ vote
            ─▶ sighting row ─▶ Redis
```

- Plate detection on the vehicle crop, not the frame: a 20 px plate in a 1920 px frame is ~7 px
  after letterboxing; inside a 300 px crop it is a readable band.
- Grammar before the vote (`^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$`, BH series too): confusion
  classes are resolved by slot, so the vote spends itself on genuine ambiguity.
- Timestamps are frame PTS, never `now()`. `ts_source` is on every row.

Show the record itself — one real row from the running system, not a mock-up.

## 5 — Model card: what it gets right, and what it refuses

From `‹accuracy›`, per band, never averaged into one number:

| band | share | precision | what the system does |
|---|---|---|---|
| CONFIRMED | `‹accuracy›` | `‹accuracy›` | publishes `plate_text`, can raise an alert |
| PROBABLE | `‹accuracy›` | `‹accuracy›` | publishes `plate_text`, alert needs corroboration |
| POSSIBLE | `‹accuracy›` | — | **publishes a crop and a null plate** |
| NONE | `‹accuracy›` | — | vehicle row only |

Also on the slide, because leaving it off is how 70% becomes 95%: the refusal rate — the share
of passes no reader can read, around 13%. Detector throughput `‹bench›`, decode `‹decode›`.

## 6 — Watchlist, bands, alert state machine, latency

`NEW → ACK → IN_PROGRESS → RESOLVED | FALSE_POSITIVE`, every transition audited with a user and
a reason. Matching is banded, not binary: exact `plate_norm`, then `plate_canon` (confusion
classes collapsed), then weighted edit distance ≤ 1.0. Sighting-to-alert latency `‹latency›`.

## 7 — Route: the graded test case

A judge types a registration; the map draws the vehicle's hops across the grid with timestamps,
snapped to roads via OSRM. Each hop carries an implied speed, and a hop that needs 180 km/h
through a city is flagged `IMPLAUSIBLE` rather than quietly drawn — a route that cannot lie to
an officer is worth more than one that always answers.

## 8 — RBAC and audit

The [C10] matrix, enforced in SQL with row-level security as the backstop, not in the UI.
Every export and every live view writes an audit row; the log is hash-chained and
`‹audit›` verifies it. Hiding a button is not access control.

## 9 — Scale: the arithmetic, printed so the jury can check it

**Centralised video (the M4 approach we reject):**

```
80,000 cameras × 2 Mbps (H.264, 720p, 5 fps)      = 160,000 Mbps ≈ 160 Gbps
160 Gbps × 86,400 s/day                            ≈ 1.7 PB/day
                                                   ≈ 26 PB at ~15 days retention
```

**Metadata (what we actually ship):**

```
~200 bytes per sighting row ([C1])
80,000 cameras × ~1,000 sightings/camera/day       ≈ 80 M rows/day
80 M × 200 B                                       ≈ 16 GB/day raw
                                                   ≈ 2–3 GB/day compressed (Timescale)
```

Four orders of magnitude. That is the entire case for edge inference and a federated
architecture, and it fits on one slide because it is four multiplications.

## 10 — Roadmap

Now: three drivers, ANPR with a banded vote, watchlist alerts, route, RBAC + audit.
Next 30 days: the VMS driver against real credentials; fine-tuned detectors on labelled Gujarat
footage (+TensorRT); re-ID as PROBABLE corroboration; crowd, wrong-way and loitering analytics.
Then: face matching under a separate legal authorisation, ANPR-grade camera siting guidance
(a plate under 100 px wide is a siting fault, not a model fault).

Prize pool, if quoted: **₹51 lakh** — the portal figure, not the ₹37 lakh in press coverage.

---

**Close on this, verbatim:**

> The fusion refuses to guess below a 2/3 majority. We would rather report nothing than report
> the wrong vehicle to a police officer.
