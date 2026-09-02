# Prahari — High-Level Design

Cross-camera vehicle tracking for the Gujarat Police camera grid. This document is the
integration story: what talks to what, what is stored, who may read it, and what happens when a
piece of it fails. An engineer who has never seen the repository should be able to rebuild the
integration from this file alone.

Status markers are used throughout and mean exactly what they say: **built** is running and
tested in this repository; **planned** is designed and not yet written.

---

## 1. What the system is

A vehicle passes a camera. Within a couple of seconds the plate is read, checked against a
watchlist, and — if it matches — pushed to every console allowed to see that camera. Later, an
investigator can ask where that plate went and get an ordered, timestamped path across the
network, exportable and audited.

The atom is the **sighting**: roughly 200 bytes describing one vehicle at one camera over a short
interval (contract `C1`). Everything downstream reads sightings. Video is not the product;
sightings are.

```
 cameras ──► gateway ──► worker ──► sightings stream ──┬──► persister ──► Timescale
 (RTSP/HLS)  (transport  (decode,   (Redis)            │                  hypertable
              probe,      detect,                      ├──► matcher ────► alerts stream
              health)     OCR)                         │                       │
                                                       └──► ws fanout ◄─────────┘
                                                                  │
                                                              consoles
```

### Lane ownership

| Component | Owner | Status |
|---|---|---|
| Gateway, transport probing, health, console | lane G | built |
| Decode, detection, tracking, plate OCR | lane I | in progress |
| Schema, persistence, matching, alerts, API, RBAC | lane D | built |

---

## 2. Integration approach

### 2.1 Cameras into the system

Cameras are not integrated one protocol at a time; they are integrated behind one interface.
`CameraSource` (contract `C6`) exposes `open / frames / close / health / capabilities`, and each
transport is an implementation: MediaMTX-fronted RTSP, direct RTSP, HLS, and ONVIF for the
cameras that support events and PTZ.

Two field realities shaped this:

- **RTSP over TCP, never UDP.** UDP dies across NAT and firewalls, and the failure looks like a
  frozen frame rather than an error.
- **Port 8554 is blocked on parts of the network.** The gateway probes each camera and degrades
  to HLS per camera, recording which transport actually worked in
  `camera:transport:<id>` in Redis. That key is the whole contract between the gateway and the
  inference worker: a URL string. The worker imports no gateway code.

A stalled RTSP connection does not raise; it simply stops delivering. Health is therefore a
watchdog on frame arrival, not a try/except, and it publishes `camera.health` for the console.

### 2.2 Inference into the system

The worker consumes the transport URL, decodes at 5 fps behind a motion gate, detects vehicles,
tracks them, reads plates, and publishes one `C1` record per track — not one per frame. A vehicle
in frame for 200 frames is one sighting with a first and last timestamp, the best plate read on
that track, and one crop as evidence.

**Timestamps come from frame PTS, never `now()`.** Arrival order across cameras is meaningless:
one camera's frames may sit in a buffer while another's do not. A route assembled from arrival
times reorders itself under load. Every host runs chrony.

### 2.3 The seam between lanes

Four frozen contracts, and nothing else crosses a lane boundary:

| Seam | Shape | Direction |
|---|---|---|
| `camera:transport:<id>` | JSON: url, transport, driver, probed_at | G → I |
| stream `sightings` | `C1` record as one JSON field | I → D |
| REST + WebSocket | contracts `C4`, `C5` | D → G |
| exchange files | `cameras.seed.json`, `camera_geo.json`, fixtures | one producer each |

This is why three people can work in parallel: no ticket waits on another person's ticket, only
on a written contract.

---

## 3. Storage

**Built.** Postgres 16 + TimescaleDB + pgvector + pg_trgm (`db/schema.sql`, contract `C3`).

- `sightings` is a hypertable on `pts_first` with one-day chunks. The hypertable is created
  before the first insert — converting a populated table means a lock and an outage.
- Five indexes carry every read path: `plate_norm`, `plate_canon`, `camera_id`, a trigram index
  for fuzzy search, and an HNSW index on the 512-dimension re-ID vector.
- Compression after 7 days, retention 90 days for sightings, 30 days for crops. Alerts and audit
  rows are kept: an alert nobody can look up a year later is worth little, and an audit chain
  with holes is not evidence.
- Crops live in MinIO (S3 API), not in the database, and are reached only through presigned URLs
  with a five-minute expiry.

Measured: 14,991 synthetic sightings at 50 rows/s for five minutes persisted with zero consumer
lag growth on a laptop.

---

## 4. Watchlist correlation

**Built** (`services/api/watchlist.py`, `feeds.py`, `matcher.py`).

### 4.1 Getting entries in

Four sources behind one protocol (`WatchlistFeed.pull(since)`):

| Feed | Status | Notes |
|---|---|---|
| Manual | built | what an operator types into the console |
| CSV import | built | all-or-nothing, per-line error report |
| VAHAN | **stub** | national vehicle registry: theft flag, blacklist status |
| e-GujCop | **stub** | FIR entities: wanted vehicles and persons |

The two state-system feeds carry written-down request and response shapes and return sample rows
labelled `STUB:<feed>`, so integration readiness is demonstrable without pretending the
connection exists. Field names in those shapes are placeholders until the department issues API
documentation and credentials — they are not a contract.

CSV import validates every row before writing any of them. A partial import is worse than a
rejected one: the operator believes 200 vehicles are watched when 188 are, and nothing says which
12 are missing. A rejected row names its spreadsheet line number and a reason in words.

### 4.2 Matching a sighting to an entry

Every sighting is checked by a second consumer group on the same stream, so a slow match never
delays a write.

1. **Canon lookup, O(1).** `canon()` collapses every confusion class — `{0,O,D,Q}`, `{1,I,L}`,
   `{8,B}`, `{5,S}`, `{2,Z}`, `{6,G}` — so any single confusion-pair misread lands on the same
   key as the true plate. One dictionary hit, no scan.
2. **Trigram fallback.** A plain misread changes the canon key, so a Postgres `similarity()`
   query at a 0.4 retrieval floor catches it. Measured: one edit in a ten-character plate scores
   0.57, two edits 0.47, an unrelated plate 0.0.
3. **Weighted Levenshtein decides the band.** A confusion-pair substitution costs 0.5, anything
   else 1.0.

| Cost | Meaning | Band |
|---|---|---|
| 0 | exact string match, and the read itself was CONFIRMED | **CONFIRMED** |
| 0 | exact match on a less confident read | PROBABLE |
| 0.5 | one confusion-pair edit | **PROBABLE** |
| 1.0 – 2.0 | one plain edit, or two edits | **POSSIBLE** |
| > 2.0 | a different vehicle | no alert |

An alert is never more confident than the read behind it. A POSSIBLE read that happens to spell a
watched plate does not put CONFIRMED in front of an officer.

Only entries valid *now* are indexed. An expired entry that still fires produces an alert the
operator has to dismiss, and a watchlist that cries wolf stops being read.

---

## 5. Alert workflow

**Built** (`services/api/alerts.py`).

```
 match ─► dedup check ─► NEW ─► ACKNOWLEDGED ─┬─► ACTIONED
                                              └─► DISMISSED (reason required)
```

- **Dedup** per (watchlist entry, camera) for 60 seconds. A car at a red light is seen on twenty
  frames; twenty alerts is how an operator learns to ignore the panel. The repeat increments a
  count. The window is per camera, so the same vehicle on the next camera is news.
- **The state machine is enforced server-side.** An illegal transition is HTTP 409 and writes
  nothing. `DISMISSED` requires a reason — dismissing without one is the failure mode that makes
  an audit log worthless.
- Every transition writes an `alert_events` row and an audit row.
- The alert is published to a Redis stream, and the WebSocket fanout turns it into an
  `alert.new` frame for every console whose scope covers that camera.

**Latency budget** (to be measured on the sandbox, ticket J1): sighting to console under 2 s on
the RTSP path, under 6 s on HLS. The HLS floor is the segment duration, not our code.

---

## 6. Delivery to the console

**Built** (`services/api/ws.py`, contract `C5`).

One WebSocket per console replaces all polling. The client sends its JWT as the first frame; the
server computes scope once and filters every frame server-side. A console that receives frames it
must not display and hides them in JavaScript has already leaked them.

Frames carry a monotonic `seq`, and the last few thousand stay in a ring buffer. A console that
drops off station wifi reconnects with `{"type":"resume","since":N}` and receives exactly what it
missed, filtered through its scope again — without that, a reconnect is a blank panel and the
operator cannot tell "nothing happened" from "I missed it". Heartbeat every 15 seconds, because a
dead TCP connection is indistinguishable from a quiet grid at 3 a.m.

Fanout reads the Redis streams with `XREAD` rather than a consumer group: a group splits messages
between its members, so two API replicas would each show half the alerts to half the consoles.

---

## 7. Route reconstruction

**Built** (`services/api/route.py`). This is the graded scenario: a judge names a plate and gets
its path.

1. Sightings for the plate over a window, ordered by `pts_first` off the hypertable.
2. Consecutive rows on one camera collapse into one hop. A route that lists the same junction
   five times is not a route.
3. **Plausibility.** Great-circle distance over elapsed time gives an implied speed. Above
   150 km/h the pairing is far more likely to be a misread plate than a car that teleported, so
   the lower-confidence hop of the pair is flagged `IMPLAUSIBLE` **and still shown**. Deleting it
   silently hands the operator a clean-looking route with a hole in it; a judge who sees the
   system catch its own bad read learns more than one who sees four suspiciously perfect hops.
4. **Fuzzy fallback**, only when the exact plate returns nothing: canon key, then trigram at 0.7
   — stricter than the matcher's retrieval floor, because this result goes in front of a person.
   The whole result set is labelled *fuzzy match; verify plate*, and the label survives into the
   CSV and the PDF.
5. **Road snapping** through OSRM when `OSRM_URL` answers. When it does not, the response carries
   the straight line between cameras and says `snapped: false` rather than dressing it up as a
   road path.

Exports are CSV and PDF, and neither is produced without an audit row.

---

## 8. Security model

**Built** (`services/api/scope.py`, `auth.py`, `audit.py`, `db/migrate.sql`).

### 8.1 Identity

argon2id password hashes. A 15-minute access token and an 8-hour refresh token — one shift. A
refresh token presented as an access token is refused. An unknown username costs a full hash
verification, because returning instantly is a timing oracle that enumerates accounts.

### 8.2 Authorisation — contract `C10`

| Role | Live | Detections | WL read | WL write | Route | Export | Admin |
|---|---|---|---|---|---|---|---|
| Viewer (dept) | own | own | – | – | – | – | – |
| Operator | own | own | own | – | own | – | – |
| Investigator (Police) | all | all | all | own | statewide | yes, logged | – |
| Dept Admin | own | own | own | own | own | yes | users in dept |
| System Admin | – | – | – | – | – | – | config + audit only |

The last row is deliberate: **the most privileged account cannot watch video.** Administering a
surveillance system and using one are different jobs, and the account that does both is the one
an insider abuses.

Enforcement is in three layers, in this order:

1. **The capability check** — the role either holds `watchlist:write` or gets a 403.
2. **The scope predicate in the SQL** — every read carries
   `(statewide OR owner_dept_id = ANY(:departments))`. Hiding a button is not access control.
3. **Postgres row-level security** — the backstop for a query somebody forgets to scope, keyed
   on session variables set per request.

A user with no department matches nothing rather than everything: a misconfigured account should
see an empty screen, not the state.

### 8.3 Audit

Append-only, and hash-chained: `hash = sha256(prev_hash || fields)`. The chain does not prevent
tampering — it makes tampering visible, which is the achievable property. Edit one row and every
hash after it stops matching; `GET /api/admin/audit/verify` walks the chain and names the first
break.

Reads are logged, not just writes. In a surveillance system the abuse worth catching is looking:
an officer checking an ex-partner's vehicle leaves no other trace. Exports, live views, watchlist
changes and every alert transition are on one chain.

---

## 9. The privacy answer, in full

This is the question a citizen asks, and the answer is architectural rather than a policy
promise:

- **No central video recording.** Video is decoded at the edge and discarded. What leaves a
  camera site is a ~200-byte row and, at most, a small crop of the vehicle. There is no archive
  to subpoena, leak or trawl, because there is no archive.
- **Retention is bounded and enforced by the database.** Sightings 90 days, crops 30 days, both
  as automatic policies rather than a cleanup script somebody remembers to run. Alerts and audit
  rows are kept, because those are the records of what the *system* did.
- **Access is purpose-bound.** A cross-department lookup requires a case number and a stated
  reason, both recorded (ticket D9).
- **Access is time-boxed.** Such a grant expires automatically, at most 72 hours, rather than
  living until somebody remembers to revoke it.
- **Access is scoped.** A department sees its own cameras. Statewide access is one role, held by
  investigators, and every use of it is logged.
- **Access is provable.** The hash-chained audit log means "nobody looked at this" is a claim
  that can be checked rather than asserted.
- **Crops are reached only through five-minute presigned URLs**, issued after the scope check.
  A leaked URL expires; a leaked bucket path is useless.

What the system deliberately does not do: face recognition against a general population, retention
beyond the windows above, and any lookup that cannot name the case it belongs to.

---

## 10. Interop assumptions

Stated so an integrator can check them before writing code:

1. **Cameras** speak RTSP (TCP) or HLS. ONVIF is used where available for events and PTZ, and is
   not required. Mixed H.264 and H.265 in one grid is normal.
2. **The grid catalogue** is available as `GET /api/ingest` on the sandbox host, and per-camera
   properties are read from it before decoding rather than probed blindly.
3. **Clocks** are synchronised (chrony). Sighting order across cameras depends on it.
4. **VAHAN and e-GujCop** are reachable only with agency credentials issued by the respective
   department. Until those exist, both feeds run as labelled stubs; swapping in the live client
   changes one class each and no calling code.
5. **Coordinates** come from a survey, not from district centroids. A centroid puts every camera
   in a district on one pixel and makes the demo car teleport.
6. **Everything is open source.** Postgres, TimescaleDB, Redis, MinIO, OSRM, FastAPI, MediaMTX,
   Ultralytics. No managed service is required to run this, which is a contest rule and also the
   difference between a pilot and a procurement.

---

## 11. Scale tiers

The deployment shape changes three times between a demo and a state rollout. The code does not.

### Tier 1 — one node (today, and the demo)

Everything on one machine: gateway, one or two workers, Redis, Postgres/Timescale, MinIO, API,
console. Handles roughly 30 cameras at 5 fps analysis. The limit is GPU decode: H.264 decodes
every frame even when analysis runs at 5 fps, so 30 cameras at 25 fps is ~750 fps of decode,
which is near the ceiling of one consumer-grade NVDEC. Watch `nvidia-smi dmon`; above 90% decode
utilisation, move cameras to CPU decode.

### Tier 2 — a district (tens to a few hundred cameras)

Workers move to their own boxes, one per GPU, each pinned to a set of cameras from the registry.
Redis stays central to the district. Postgres stays single-node; a Timescale hypertable on
commodity hardware absorbs a few hundred sightings per second without trouble. The API scales
horizontally behind a load balancer — the WebSocket fanout is broadcast-safe because every
process reads the whole stream.

### Tier 3 — statewide (thousands of cameras)

- **Edge workers** keep doing exactly what they do now, and buffer locally when the uplink drops.
- **Kafka replaces Redis Streams** as the trunk between districts and the centre. The migration
  is contained: the producer and the two consumer groups are the only code that knows which
  broker it is talking to, and the `C1` record does not change. Kafka is chosen for retention and
  replay across a WAN, which is where Redis Streams stops being the right tool.
- **Central Postgres/Timescale** with district-level partitioning, plus read replicas for the
  console.
- **Object storage** (MinIO or S3-compatible) for crops, with lifecycle rules enforcing the
  30-day window.
- Re-ID vectors move to a dedicated index if HNSW inside Postgres stops keeping up.

The seams that make this possible are the ones already in place: a stream between inference and
storage, a REST/WebSocket boundary between storage and the console, and no shared code across
either.

---

## 12. Failure modes, and what the operator sees

The system is judged on a live grid, so this section is about what a person sees at 3 a.m., not
about ideal behaviour.

| Failure | Detection | What the operator sees | Recovery |
|---|---|---|---|
| **A district uplink drops** | frame watchdog, no `camera.health` for 15 s | that district's pins turn red within 15 s, with a "buffering" badge | edge workers buffer sightings locally and replay when the link returns; no gap in the timeline |
| **A GPU or worker dies** | its cameras stop producing sightings; heartbeat lapses | affected pins go amber, then red | the registry reassigns those cameras to a surviving worker within 30 s |
| **Postgres restarts** | persister insert fails | nothing — the console keeps receiving live alerts | the consumer group has not acked, so the batch is redelivered and inserted; `ON CONFLICT DO NOTHING` absorbs the replay |
| **A consumer process dies mid-batch** | its messages stay pending | nothing | `XAUTOCLAIM` moves anything idle past the threshold to a live consumer; without this a killed worker is a permanent hole |
| **Port 8554 blocked for a camera** | transport probe fails at startup | that camera shows an "HLS" badge | the gateway degrades that camera to HLS; latency rises to the segment duration |
| **A console loses connectivity** | socket closes | reconnect banner | it reconnects with `resume: seq` and the server backfills exactly the gap |
| **OSRM is down** | request times out in 3 s | the route still draws, as straight lines, labelled unsnapped | none needed; the hops, times and flags are the evidence |
| **MinIO is unreachable** | presign raises | hops render without thumbnails | the route and the alert are unaffected |
| **A plate is misread into a watched plate** | plausibility check on the route | the hop is shown, flagged `IMPLAUSIBLE`, with the implied speed | the operator sees the doubt instead of a confident lie |

Each of these is a drill in ticket J1, run before the demo rather than discovered during it.

---

## 13. What is not built yet

Named plainly, because a design document that hides its gaps is not useful:

- Re-ID corroboration of route hops (ticket I10) — the route ships plate-keyed; a hop supported by
  appearance similarity is a P1 upgrade.
- Cross-department grants (ticket D9) — the schema and the audit fields exist; the request and
  approval flow is next.
- Live VAHAN and e-GujCop connections — blocked on credentials, stubbed behind the real protocol.
- Fine-tuned detection and TensorRT export (ticket I11) — pretrained models ship first.
