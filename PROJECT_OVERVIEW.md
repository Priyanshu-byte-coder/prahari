# Prahari — Full Project Overview

*One document to understand the whole project: what we are building, why, the rules we were
given, what is done, and what is left. Written in plain language. No code — concepts only.*

Last updated: **3 September 2026**

---

## Table of contents

1. [The one-paragraph summary](#1-the-one-paragraph-summary)
2. [The competition: Sentinel 2026](#2-the-competition-sentinel-2026)
3. [The problem we are solving](#3-the-problem-we-are-solving)
4. [The five reference models (and the one we chose)](#4-the-five-reference-models-and-the-one-we-chose)
5. [Our solution, in plain words](#5-our-solution-in-plain-words)
6. [The core idea: we ship rows, not video](#6-the-core-idea-we-ship-rows-not-video)
7. [What each part of the system does](#7-what-each-part-of-the-system-does)
8. [How we keep the system honest](#8-how-we-keep-the-system-honest)
9. [Security and privacy](#9-security-and-privacy)
10. [The guidelines we were given](#10-the-guidelines-we-were-given)
11. [How the team works: three lanes and frozen contracts](#11-how-the-team-works-three-lanes-and-frozen-contracts)
12. [What is built](#12-what-is-built)
13. [What is in progress](#13-what-is-in-progress)
14. [What is left](#14-what-is-left)
15. [Timeline to submission](#15-timeline-to-submission)
16. [Deliverables checklist (competition view)](#16-deliverables-checklist-competition-view)
17. [Key decisions and trade-offs](#17-key-decisions-and-trade-offs)
18. [Risks](#18-risks)
19. [Glossary](#19-glossary)
20. [Where to find things](#20-where-to-find-things)

---

## 1. The one-paragraph summary

**Prahari** (Hindi for "sentinel/guard") is our entry for the Gujarat Police **Sentinel CCTV
Integration Hackathon 2026**. It is a software platform that takes the thousands of CCTV cameras
that different government departments run separately, brings their live feeds into **one screen**,
automatically **reads number plates** off the video, checks every plate against a **watchlist**
(stolen vehicles, wanted people, etc.), raises a **real-time alert** when there is a match, and
can **trace a vehicle's route** across many cameras on a **map** with timestamps. Crucially, it
does all of this **without storing the video centrally** — it processes each camera's feed where
the camera is and only sends out a tiny text record of what it saw. It also proves **who looked
at what**, so the system can be trusted.

The single thing the judges will test: *a judge types a vehicle registration number, and the
system shows that vehicle's journey across the camera grid with times and locations.* Everything
else exists to make that answer trustworthy.

---

## 2. The competition: Sentinel 2026

| | |
|---|---|
| **Full name** | Gujarat Police Innovation Challenge 2026 ("Sentinel") |
| **Run by** | Gujarat Home Department / State Crime Records Bureau (SCRB), Gandhinagar |
| **Website** | https://sentinel.gujarat.gov.in |
| **Tagline** | "Protect What Matters." |
| **Submission deadline** | 7 September 2026 (we target 6 Sep, 14:00 IST — the 7th is a buffer) |
| **Shortlisting** | 7 September 2026, evening |
| **Live event** | 10–11 September 2026, i-Hub, Gandhinagar |
| **Prize pool** | ₹51,00,000 (₹51 lakh) — this is the portal figure; press coverage said ₹37 lakh, we quote the portal |

### How the prize money is split

- **Phase 1 — Sandbox (₹18 lakh):** teams work on test feeds. Two categories (students/small
  startups, and larger companies). Top 3 from each category advance — 6 finalists total.
- **Phase 2 — Grand Finale (₹31 lakh):** the 6 finalists work with real feeds at scale, judged
  by Gujarat Police leadership plus a technical jury. 1st ₹16 L, 2nd ₹8 L, 3rd ₹7 L.

### What "not a simulation" means

The organisers are explicit: **mock-ups, animations, simulated interfaces, and concept videos
without a working backend will not be considered.** Every screenshot in our deck and every second
of our demo video must be the real running system.

### The seven things we are scored on

1. **Successful test case** — does it actually work on the government-provided feed?
2. **Solution presentation** — is the PPT/PDF clear and complete?
3. **Solution architecture** — is the High-Level Design technically sound, secure, interoperable?
4. **Working platform and demonstration** — how mature is the actual system?
5. **Video analytics output** — quality of ANPR, detection, timestamps, reports
6. **Scalability and PoC readiness** — can it scale toward ~80,000 cameras?
7. **Submission completeness** — are all documents, videos, links, and credentials present?

### Bonus points

Hybrid/custom architecture with clear value · cross-camera vehicle tracking · analytics beyond
ANPR · edge processing / bandwidth optimisation · cybersecurity, privacy, auditability, RBAC ·
operational dashboards, health monitoring, integration-ready APIs. **We hit all six of these.**

### Mandatory architecture principles

The solution must be **open, modular, scalable, secure, standards-based, and vendor-neutral** —
no lock-in on cameras, VMS, analytics engines, storage, or AI modules. **Open-source only.** It
must be technology-agnostic and support heterogeneous multi-vendor environments, and be ready to
integrate with state systems: **VAHAN** (national vehicle registry), **SARTHI** (driving
licences), **eGujCop** (Gujarat Police's CCTNS case system), **AFIS/NAFIS** (fingerprints).

---

## 3. The problem we are solving

Across Gujarat, **26 government departments** — Municipal Corporations, Transport (RTO), Police,
Civil Supplies, Health, GSRTC (state buses), Panchayats, and more — have each installed their own
CCTV cameras over the years. The result today:

- **Different vendors, different everything.** Analog cameras and IP cameras mixed together. Each
  department has its own Video Management System (VMS), its own storage, its own retention rules
  (some keep 7 days, some keep 15+).
- **No shared inventory.** Nobody has a single list of "where are all the government cameras and
  what condition are they in."
- **No interoperability.** A control room that wants to watch feeds from three departments needs
  three separate viewer applications.
- **No cross-department search.** You cannot ask "where has this vehicle been seen" across
  departments, because there is no system that sees across them.

So if a stolen car drives across a city, the footage that could trace it is sitting in five
different departments' systems, in five different formats, and nobody can join it up.

**The brief asks us to fix this** — build a secure, scalable, interoperable platform that:

1. Integrates ~50 heterogeneous cameras live (with a path to scale to ~80,000).
2. Runs AI analytics — **ANPR (number plate reading) is mandatory**; face recognition, crowd
   counting, anomaly detection are optional bonuses.
3. Correlates every sighting against watchlist databases and raises real-time alerts on a match.
4. Traces a vehicle across cameras with a timestamped movement history.
5. Shows routes and events on a GIS (map) interface.
6. Has role-based access per department, and APIs ready for VAHAN / SARTHI / eGujCop / AFIS / NAFIS.
7. Has encryption, network segmentation, disaster recovery, redundancy, and an audit trail.
8. Comes with a real plan (and cost estimate) to scale to 80,000 cameras.

---

## 4. The five reference models (and the one we chose)

The brief describes four "reference models" — approaches of increasing centralisation — plus a
fifth option to combine or invent. Here they are in plain language:

### Model 1 — Central CCTV Registry + GIS (the foundation)

Just a **database and a map** of every government camera: location, department, camera type,
owner, connectivity status, storage details. **No video at all.** Like a phone book for cameras.
Used for planning, spotting coverage gaps, assessing ageing equipment.
**The brief is explicit: Model 1 is the *foundation*. You always build it, then add Model 2, 3,
or 4 on top for actual video and analytics.**

### Model 2 — Unified Viewing, plugged in directly

One viewing website that connects **straight to each department's cameras** (via RTSP, ONVIF,
vendor SDKs, or APIs) and shows them in a single interface. Each department's VMS keeps running
untouched. **No middleware layer.** Can do light ANPR on the feeds it can reach. **No central
recording.**

### Model 3 — Federation Middleware (a translator in the middle)

Instead of talking to every camera directly, you build **one "translator" layer** that has a
**plug-in (adapter) for each vendor's VMS**, a shared bus for exchanging events and metadata, and
a **cross-system event-correlation engine**. Departments keep everything they have; the middleware
gives the command centre one unified interface and lets systems talk to each other. **No central
recording** — it federates, it does not absorb.

### Model 4 — Central VMS (one giant system)

Rip-and-replace at the top: **one statewide platform that ingests, records, and stores all
~80,000 camera feeds centrally**, with tiered hot/warm/cold storage, GPU analytics, face
recognition, statewide vehicle tracking. The most powerful — and it needs enormous bandwidth
(~160 Gbps), storage (~26 petabytes), and money.

### Model 5 — Hybrid / Custom

Pick the useful parts of several models, or invent your own, as long as you cover
interoperability, security, scale, and analytics. **Bonus points for a good hybrid.**

### What Prahari is

**A hybrid: Model 1 as the foundation + Model 3 as the architecture + Model 2's streaming
technique + Model 4's analytics — but NOT Model 4's central video store.**

| From | What we take | What we reject |
|---|---|---|
| **M1** | The camera registry as the system of record; every asset on a real map coordinate | Its assumption that one department owns every camera |
| **M2** | The direct RTSP/WHEP/HLS live view — no transcoding hop, no per-vendor console | M2 *as an architecture* — it forbids the middleware layer we depend on |
| **M3** | The whole structure — vendor adapters behind one interface, one event bus, one API, cross-system correlation | Its heavyweight "install a box at every site" model |
| **M4** | Cross-department correlation and watchlist analytics | **Central recording of 80,000 streams** — see the scale maths in section 6 |

**Our one-line pitch to the jury:** *"Federation middleware with pluggable drivers — three
drivers live, the departmental-VMS driver interface-complete pending vendor credentials. We ship
200-byte rows, not video."*

---

## 5. Our solution, in plain words

The system is a **pipeline of five stages**. Video enters at stage one and **never leaves it** —
only tiny text records flow onward.

```
1. Cameras / VMS   →   2. Federation Gateway   →   3. Inference Worker   →   4. Core API   →   5. GIS Console
   (many vendors)       (adapters, one          (reads plates,             (stores rows,       (map, video wall,
                         interface)               tracks vehicles)           matches watchlist,  route view)
                                                                             raises alerts,
                                                                             enforces access)
```

1. **Cameras / VMS** — the existing government cameras, speaking whatever protocol they speak
   (RTSP, ONVIF, HLS, WHEP, or a vendor's own SDK).

2. **Federation Gateway** — has one small **"driver" (adapter) per protocol**. Whatever a camera
   speaks, the driver normalises it. Everything downstream is protocol-blind. This is the Model 3
   translator layer. **Three drivers are live** (`mediamtx`, `rtsp`, `onvif`); a fourth
   (`vms-stub`) is fully built as an interface and waiting only on real vendor credentials.

3. **Inference Worker** — this is where the AI runs, **at the edge, near the camera**. It decodes
   the video at 5 frames per second, detects vehicles, tracks each vehicle across frames, finds
   the number plate inside each vehicle, reads it with **two independent OCR engines**, and takes
   a **per-character vote** between them. It produces one **sighting record** per vehicle pass.

4. **Core API** — receives the sighting records over a message stream, **stores** them in the
   database, **matches** each one against the watchlist, **raises alerts** on a match, **pushes**
   those alerts to connected consoles instantly, answers **route** queries ("where has plate X
   been?"), and enforces **who is allowed to see what** with a full **audit log**.

5. **GIS Console** — the operator's screen. A Leaflet map with every camera pinned, layers for
   department/type/status, a live video wall, the events timeline, and the route view where you
   type a plate and watch the vehicle's path draw across the map.

---

## 6. The core idea: we ship rows, not video

This is the whole argument for our architecture, and it is just four multiplications.

### If you centralise the video (Model 4):

```
80,000 cameras × 2 Mbps (H.264, 720p, 5 fps)   ≈ 160,000 Mbps  =  ~160 Gbps of network
160 Gbps × 86,400 seconds/day                                    ≈ ~1.7 petabytes per day
                                                                 ≈ ~26 petabytes at 15-day retention
```

That is a national-backbone amount of bandwidth and a data-centre of storage, just to move and
keep the video.

### If you ship only the metadata (Prahari):

```
~200 bytes per sighting record
80,000 cameras × ~1,000 sightings/camera/day    ≈ 80 million rows/day
80 million × 200 bytes                            ≈ 16 GB/day raw
                                                 ≈ 2–3 GB/day compressed (TimescaleDB)
```

**26 petabytes/day versus 16 GB/day — four orders of magnitude.** That is why the AI runs at the
edge and why the architecture is federated. It also happens to be the **privacy answer**: there
is no central video archive to subpoena, leak, or trawl, because we never built one.

### The "sighting record" (the atom of the system)

Every vehicle that passes a camera produces one ~200-byte JSON record. In plain terms it
contains: a time-sortable ID, which camera, which tracked vehicle, the **first and last
timestamp** of the pass (taken from the video's own clock, never the server's), the **plate text**
(or `null` if we could not read it confidently), a **confidence band**, the vehicle class and
colour, the bounding box, an optional re-identification vector, and a link to a small cropped
image of the vehicle. Everything downstream — storage, matching, alerts, routes, the map — reads
this one record shape.

---

## 7. What each part of the system does

### The Federation Gateway (Lane G)

- **Drivers** — one per protocol. `mediamtx` (RTSP/WHEP/HLS), `rtsp` (RTSP/TCP), `onvif` (ONVIF
  Profile S + events) are **live**. `vms-stub` (vendor VMS SDK) is **interface-complete** —
  the code is done, it just needs a real vendor's credentials to connect.
- **Transport probe** — for each camera, it tries RTSP first (best latency, real timestamps) and
  **falls back to HLS** if RTSP is blocked. On our test network, port 8554 is filtered, so
  27 of 30 cameras run over HLS. **This fallback is a feature, not a workaround** — heterogeneity
  is exactly what the brief is testing.
- **Health monitor** — the single source of truth for "is this camera up?" It publishes a
  `camera.health` signal; a camera that goes quiet for 15 seconds turns its map pin red.
- **Video wall** — pulls frames server-side and shows them as images, because the grid's
  low-latency stream cannot be played directly in a browser tab.

### The Inference Worker (Lane I) — the ANPR pipeline

The mandatory analytic, stage by stage:

1. **Decode** the video at 5 fps, with a motion gate so still scenes cost nothing.
2. **Detect vehicles** with YOLOv8s (a pretrained open-source model), processed in batches for speed.
3. **Track** each vehicle across frames with ByteTrack — **one tracker per camera, kept alive**,
   so each vehicle keeps a stable ID through its whole pass.
4. **Find the plate** *inside the vehicle crop*, not the whole frame. (A 20-pixel plate in a
   1920-pixel frame is ~7 pixels after resizing; inside a 300-pixel vehicle crop it is readable.)
5. **Read the plate** with **two independent OCR engines** (EasyOCR and PaddleOCR).
6. **Apply Indian plate grammar** (`AA 00 A(A)(A) 0000`, plus the newer BH series) *before*
   voting, so the vote only spends effort on genuinely ambiguous characters.
7. **Vote** per character. If the two readers do not reach a **2/3 majority**, we publish **no
   plate text** — a crop and a `null`, not a guess.

The worker also does **bonus analytics** (crowd density, stopped vehicle, wrong-way, loitering)
and produces a **re-identification vector** (an appearance fingerprint) that can *corroborate* a
route hop but can never *confirm* one.

It ships with a **one-command self-test**: replay a clip with a known plate, and confirm a valid
record lands on the stream within the latency budget (~0.4 s in testing).

### The Core API (Lane D)

- **Persister** — reads the sighting stream and writes rows into Postgres/TimescaleDB. If
  Postgres restarts mid-batch, the messages are simply redelivered and re-inserted (duplicates
  are ignored), so **no sightings are lost**.
- **Watchlist + feeds** — operators type entries or upload a CSV. There are also **stubs** for
  VAHAN and eGujCop, clearly labelled as stubs (every stub row says so), to show integration
  readiness honestly.
- **Matcher** — for each sighting, checks the plate against the watchlist in **bands**: exact
  match, then "confusion-class" match (e.g. `O`↔`0`, `B`↔`8`), then a weighted edit-distance ≤ 1.
  An exact match on a sighting that was itself only *possible* is raised as **PROBABLE, never
  CONFIRMED** — a shaky read that happens to spell a watched plate must not put "CONFIRMED" in
  front of an officer.
- **Alerts + state machine** — an alert moves `NEW → ACK → IN_PROGRESS → RESOLVED / FALSE_POSITIVE`,
  and **every transition is logged with a user and a reason**. Repeated sightings of the same
  vehicle bump a counter on the open alert instead of creating twenty alerts for one event.
- **WebSocket fan-out** — pushes alerts to every connected console instantly, filtered by that
  user's department scope, and **backfills the gap** if a console briefly disconnects.
- **Route API** — given a registration number, returns the vehicle's **ordered hops** (camera,
  coordinate, timestamp), snapped to roads via OSRM. Each hop carries an implied speed, and a hop
  that would need, say, 180 km/h through a city is flagged **IMPLAUSIBLE** rather than quietly
  drawn. Exports are PDF/CSV and **every export is audited**.
- **RBAC + audit** — access is enforced **in SQL** (with row-level security as a backstop), not
  in the UI. The audit log is **hash-chained**: if someone edits a past row, the chain breaks and
  a verify endpoint catches it.

### The GIS Console (Lane G)

A single web app: the camera map with layers, the live video wall, the events timeline with a
time slider, the alerts panel, the watchlist editor, the route/trace view, and an admin page
showing driver status. It talks to the Core API and holds its own scoped account so the operator
never sees a login form, **but the API still enforces scope on every call**.

---

## 8. How we keep the system honest

A recurring principle across the whole project: **emit nothing rather than a guess.** A wrong
plate shown to a police officer is worse than no plate.

- **No plate text below a 2/3 character vote.** The system publishes a crop and a `null` instead.
- **Four confidence bands, never averaged into one number:**
  - `CONFIRMED` — publishes the plate, can raise an alert
  - `PROBABLE` — publishes the plate, but an alert needs corroboration
  - `POSSIBLE` — publishes a crop and a `null` plate
  - `NONE` — vehicle row only, no plate
- **The refusal rate is stated openly** — on real footage, about **13% of passes cannot be read
  by any engine**. Leaving that number off a slide is how "70% accuracy" becomes "95% accuracy".
- **Plausibility on routes** — the system flags a hop it cannot physically defend instead of
  drawing a confident line.
- **Timestamps come from the video's own clock (PTS), never the server clock**, and every record
  says which clock it used (`ts_source`).
- **Plate identity is the only identity.** The re-ID appearance vector corroborates a route hop;
  it can never confirm one, and the two never share a database field.
- **Every number in the deck traces to a command.** If a figure cannot be reproduced by running
  a named script, it comes off the slide.
- **Accuracy numbers come from one place only** — `scripts/accuracy_report.py` against a
  hand-labelled golden set. Nothing is typed from memory.

---

## 9. Security and privacy

### Access control (the C10 role matrix)

| Role | Live view | Detections | Watchlist read | Watchlist write | Route | Export | Admin |
|---|---|---|---|---|---|---|---|
| **Viewer** (dept) | own dept | own dept | – | – | – | – | – |
| **Operator** | own dept | own dept | own dept | – | own dept | – | – |
| **Investigator** (Police) | all | all | all | own dept | statewide | yes, logged | – |
| **Dept Admin** | own dept | own dept | own dept | own dept | own dept | yes | users in dept |
| **System Admin** | – | – | – | – | – | – | config + audit only |

Note the deliberate split: the **System Admin can see the audit log but not live data**, and the
**Investigator can see live data but not the audit config**. No single account can both act and
erase the record of acting.

### Privacy — the answer is architectural, not a policy promise

- **No central video recording.** Video is decoded at the edge and discarded. What leaves a
  camera site is a ~200-byte row and at most a small vehicle crop. There is no archive to leak.
- **Retention is bounded and enforced by the database** — sightings 90 days, crops 30 days, as
  automatic policies, not a cleanup script someone has to remember.
- **Cross-department access needs a case number and a stated reason**, both recorded.
- **Such access is time-boxed** — it expires automatically within 72 hours.
- **Access is provable** — the hash-chained audit log means "nobody looked at this" can be
  *checked*, not just asserted.
- **Crops are reached only through 5-minute expiring links**, issued after the scope check.
- **What the system deliberately does not do:** face recognition against the general population,
  retention beyond the windows above, or any lookup that cannot name its case.

---

## 10. The guidelines we were given

There are two sets of rules: the **competition's**, and our **internal working rules**.

### 10a. From the competition

**Mandatory deliverables:**

1. **Solution Presentation (PPT + PDF)** — chosen model + justification, solution overview,
   architecture + workflow, AI analytics approach, how feeds are correlated with watchlists and
   alerts generated, technologies used, scalability/interoperability/security, operational impact.
2. **High-Level Design document (PDF)** — architecture diagrams and component interactions, how
   heterogeneous cameras/NVRs/VMS are integrated, how live streams from dispersed locations are
   ingested and processed, watchlist integration, AI approach (ANPR mandatory, plus FRS, object
   detection, tracking), alert workflow, scale to 80,000 cameras, and **what is needed from the
   departments**.
3. **Demo video on our own feed (2–3 minutes)** — a screen recording of the *working* system:
   onboarding → AI detection → watchlist match → automatic alert + visualisation. Mock-ups are
   explicitly rejected.
4. **Live demo on the government-provided feed** — onboarding, analytics output, and a
   **screen recording plus an output report** showing detected vehicles/plates with timestamps.
5. **The graded test case** — onboard the ~50 heterogeneous cameras, receive one vehicle
   registration number, and produce the **complete timestamped, location-wise route** of that
   vehicle across the grid, with the watchlist cross-referencing and auto-alerts running alongside.
6. **Scalability plan** — central/regional/edge compute, GPU sizing, bandwidth and low-bandwidth
   strategy, hot/warm/cold storage by retention, load balancing, HA, backup, DR, cybersecurity,
   and an **implementation + operational cost estimate**.

**Submission method:** unlisted YouTube link *or* Google Drive/OneDrive ("anyone with link —
viewer"). Optionally a hosted URL with test credentials, and a GitHub/GitLab repo link.

**Hard constraints:** open-source only; vendor-neutral, no lock-in; standards-based (documented
APIs, open protocols, SDKs, modular adapters); integrate without disturbing existing
infrastructure; support heterogeneous multi-vendor environments; real-time alerts correlating
live streams with a searchable watchlist; integration-ready for VAHAN/SARTHI/eGujCop/AFIS/NAFIS.

### 10b. Our internal working rules (from `CLAUDE.md` / `AGENTS.md`)

These exist because three developers work in one repo with a very tight deadline.

- **Three lanes, one repo.** Each person owns a set of directories and never edits another
  person's code. If you need something in someone else's area, you file a one-line request, you
  do not touch their files.
- **Lanes are split at *contract seams*, not pipeline stages** — so no one's task ever waits on
  someone else's task. The seams are frozen data formats (see section 11).
- **A living knowledge file.** `knowledge_base.md` is the single source of "what is true right
  now." It is patched after **every** completed task — ticket status, new files, any gotcha that
  cost time, any real decision, one changelog line. It is capped at 300 lines to stay readable.
- **`AGENTS.md`** is the stable "spine" — identity, stack, commands, conventions — and changes
  rarely. One fact, one home.
- **Token discipline** — grep for what you need, read line ranges not whole files, never read a
  huge planning doc end-to-end.
- **Ship the smallest thing that passes the ticket.** Every non-trivial ticket leaves **one
  runnable check** behind (a `Verify:` line). P1 (nice-to-have) work never happens before P0 is green.
- **Never fake a number.** Accuracy comes from the report script; latency comes from a real
  measurement.
- **Deliberate shortcuts get a `# ponytail:` comment** naming the ceiling and the upgrade path.
- **Never commit** `.env`, model weights, video, image crops, or anything over 10 MB.
- **Commits:** `[TicketID] short message`. Work on a branch, PR to `main`. QA reviewers (not the
  author) move a ticket to Done — no one grades their own work.

---

## 11. How the team works: three lanes and frozen contracts

| Lane | Owner | Owns | Builds |
|---|---|---|---|
| **Lane I — Inference** | Neal006 | `services/worker/`, `models/`, `common/plate.py`, `fixtures/` | The ANPR pipeline: decode, detect, track, read plates, vote, publish, analytics, re-ID |
| **Lane G — Edge + Console** | neevmodh | `services/gateway/`, `web/`, `infra/`, `data/*.json` | The gateway drivers, health monitor, video wall, and the whole GIS console + map |
| **Lane D — Core** | Priyanshu-byte-coder | `services/api/`, `db/`, `common/`, `scripts/` | Database, persister, watchlist, matcher, alerts, WebSocket, route API, RBAC, audit |
| **Joint — J1** | all three | `tests/test_integration.py` | End-to-end test, chaos drills, rehearsals, final submission packaging |

### The frozen contracts (the seams between lanes)

These never change without telling the other two owners. They are what let the three lanes work
independently.

| ID | What | Between |
|---|---|---|
| **C1** | The sighting record (~200-byte JSON shape) | I writes → D reads |
| **C2** | Redis Streams — `sightings`, `camera.health`, `alerts` | I & D & G |
| **C3** | The SQL schema (D owns; I and G never write to Postgres) | D |
| **C4** | The REST API (login, cameras, watchlist, alerts, route, admin) | D serves → G consumes |
| **C5** | The WebSocket protocol (token first, then resume-after-reconnect) | D → G |
| **C6** | Python interfaces — `CameraSource` (a driver), `WatchlistFeed` | G, D |
| **C7** | Plate helper functions + test vectors (`normalise`, `canon`, edit distance) | I owns → D imports |
| **C8** | Exchange files — `cameras.seed.json`, `camera_geo.json` (one producer each) | G |
| **C9** | Environment variable names (`.env.example`) | G owns file, all use names |
| **C10** | The role matrix (see section 9) | D enforces in SQL, G reflects in UI |

The single most important seam: **`camera:transport:<id>`** — the gateway writes a URL string to
this Redis key, and the worker reads it. That is the *entire* connection between Lane G and Lane
I. The worker imports no gateway code at all.

---

## 12. What is built

**The platform runs end to end.** On the docker-compose stack: 30 cameras seeded, 897 sightings
published and persisted with 0 pending, 5 alerts raised and pushed over the WebSocket, the route
API returning ordered hops, the System Admin correctly refused live views, and the audit chain
verifying. **304 tests pass, 6 skipped** against live Postgres and Redis.

### Lane I — Inference (all P0 tickets done)

| Ticket | What it delivers | Note |
|---|---|---|
| I1 | Decode at 5 fps + motion gate | 10 cameras at 5.02 fps, 0 drops over 10 min |
| I2 | Detector backend + batching | 193 fps batched on a consumer GPU (bar was 150) |
| I3 | ByteTrack + sighting builder | One tracker per camera, 17 tests |
| I4 | Plate detect + OCR + grammar + vote | EasyOCR + PaddleOCR, **0 confident-wrong** |
| I5 | `common/plate.py` + test vectors | Grammar slot logic, None-safe everywhere |
| I6 | Publish to Redis + MinIO + metrics | Row validated against C1 on every publish; survives a Redis outage |
| I8 | Worker self-test + replay harness | One command, plate on the stream in 0.43 s |
| I10 | Vehicle Re-ID | 512-d ResNet-18 vectors; only ever corroborates |
| I12 | Bonus analytics | Crowd, stopped, wrong-way, loitering |

### Lane G — Edge + Console (all P0 tickets done)

| Ticket | What it delivers |
|---|---|
| G1 | Grid recon + `cameras.seed.json` |
| G2 | `CameraSource` interface + 4 drivers + transport probe (27/30 resolve) |
| G3 | Health monitor (sole producer of `camera.health`) |
| G5 | Infra compose + env + Makefile (`make up` verified, 3 containers healthy, 16 h+ uptime) |
| G6 | Coordinate ground-truth tool + bootstrap |
| G7–G11 | Map layers, camera wedges + bearing editor, events layer + time slider + WS client, route view, video wall + admin drivers page |
| G4 | ONVIF + VMS stub — interface-complete, awaiting vendor credentials |

### Lane D — Core (all P0 tickets done)

| Ticket | What it delivers |
|---|---|
| D1 | Schema + registry loader (applies cleanly on Timescale) |
| D2 | Fake-sighting generator + persister (soak: 14,991 rows @ 49.5/s, 0 pending) |
| D3 | Watchlist + CSV import + VAHAN/eGujCop feed stubs |
| D4 | Matcher bands + alert state machine |
| D5 | WebSocket fan-out with scope filtering + resume backfill |
| D6 | Route API + plausibility flags + audited PDF/CSV export |
| D7 | RBAC + audit (SQL row-level security, runs in CI) |
| D8 | **The HLD document** — `docs/hld.md`, 13 sections, gaps named honestly |
| D9 | Cross-department grants — case number, 72-hour cap, target-dept approval, logged |
| D10 | Audit hash-chain verify endpoint (tamper test green) |

### Documents written

- `docs/hld.md` — the High-Level Design (13 sections)
- `docs/model-card.md` — what the ANPR pipeline gets right and what it refuses, with licences
- `docs/demo-script.md` — the 8-minute run sheet, 4 chaos drills, rehearsal tables
- `docs/submission.md` — deliverables, the "gate" that must pass before submitting, timeline
- `docs/deck-outline.md` — the 10-slide deck specification
- `docs/deck.html` — **the deck itself**, 10 slides, prints one-per-page to PDF *(numbers pending)*
- `docs/status.html` — a visual snapshot of this overview

### Bugs fixed and closed this week

- **#44** — the console was serving its own unauthenticated camera list, bypassing department
  scope. Now it draws the API's scoped list; refusals pass straight through.
- **#45** — the `ultralytics` library was unpinned; a version bump had silently changed the
  tracker's behaviour. Pinned to the 8.3 series (what the accuracy numbers were measured on).
- **#48** — the worker self-test published test rows onto the *real* sightings stream. Moved to
  a separate `sightings-selftest` stream.
- Closed 7 tracker issues that were done but left open.

---

## 13. What is in progress

Three items, all **submission-critical**, and **none of them is a coding problem** — they all
need the deployed stack running and, in one case, a human.

### #9 — I9: The solution deck

**Status:** all 10 slides built as `docs/deck.html`. Structure, copy, and diagrams are done.
**What's left:** six numbers must come from live runs and be pasted into the marked placeholders:
accuracy per band + refusal rate, detector throughput, decode throughput, sighting-to-alert
latency, driver camera counts, audit verify. Then export PPT + PDF from the browser.

### #8 — I7: Golden set + accuracy report

**Status:** the report runs green on **198 synthetic rows** (rendered plates — an upper bound).
**What's left:** pull ~30 real vehicle passes off the grid, crop the plates, **hand-label them**
(a person reads each plate; unreadable ones are marked `null`, ~13% expected), then run
`scripts/accuracy_report.py`. This produces the real numbers the deck needs. It cannot be
automated — it needs someone reading plates.

### #35 — J1: Integration test + chaos drills + rehearsals

**Status:** the test code is hardened — legs 2–3 now authenticate properly and correlate the
alert by the watchlist entry they created (previously they could only skip). Leg 1 is green.
**What's left:** run all four legs green against the live stack; then run the **4 chaos drills**
(kill a driver, block RTSP, restart Postgres, disconnect the console) and **2 timed rehearsals**
of the 8-minute demo. The steps and expected behaviour are already written in
`docs/demo-script.md` — they just need to be executed and the result tables filled in.

### Parked — P1, not needed for the submission

- **#11 — I11: Fine-tune + TensorRT.** ONNX export and parity are green. Fine-tuning the
  detectors on labelled Gujarat footage needs a dataset and is scheduled for the 8–9 Sep event
  window, not the submission.
- **#24 — G12: Grafana dashboard.** Not started. The metrics endpoint exists; a dashboard on top
  is operational polish for the finale.

---

## 14. What is left

### Not started — must be done before submitting

| Item | Owner | Notes |
|---|---|---|
| **Demo video (2–3 min, our own feed)** | J1 | The highest-weight missing deliverable and the one that can't be faked. Screen capture of the running system following the sequence in `docs/submission.md`. Keep a `/metrics` terminal visible in one shot as proof it is live. Record at 1920×1080, 30 fps; check it plays on a phone. |
| **Hosted URL + 3 role logins** | G + D | Deploy somewhere reachable from outside the dev network. Accounts: `demo.investigator`, `demo.operator`, `demo.admin` — so the jury can verify scope is really enforced. Test all three from mobile data. Credentials go in the submission form, never the repo. |
| **Government-feed demo** | all | Happens with the real feeds. Rehearse the flow now against the sandbox grid so nothing is new on the day. Produce the timestamped detection report. |
| **Deck → PDF** | I + all | Export at print resolution; open the PDF on another machine to check the architecture diagram did not rasterise to mush. |
| **Repo hygiene** | all | The checklist in `docs/submission.md`: no `.env` ever in git history, nothing over 10 MB, clean-clone run instructions in the README, every model's licence listed (the YOLOv8 AGPL question stated openly). |

### Known soft spots (not blockers, but say them out loud)

- **Route coordinates are geocoded from location text, not surveyed** — marked LOW/MEDIUM
  confidence. Fine for the demo; better to tell a judge than let them find it.
- **The `vms-stub` driver has 0 cameras** — it is an interface, not a claim, and the deck says so.
- **Accuracy numbers are synthetic until #8 is done** — the deck must quote the hand-labelled
  split, never the synthetic upper bound.

---

## 15. Timeline to submission

| When | What |
|---|---|
| **3 Sep — now** | Platform done. Deck and test scaffolding done. Start the demo-video dry run and the plate labelling. |
| **5 Sep** | **Feature freeze.** After this, only fixes that make the "gate" green. Run the 4 chaos drills, timed. |
| **5–6 Sep** | Two timed rehearsals of the 8-minute demo script. |
| **6 Sep, morning** | Final accuracy report → deck numbers replaced → deck to PDF. Hosted URL + logins live and phone-tested. |
| **6 Sep, afternoon** | Record the demo video, cut it, check playback on a phone. |
| **6 Sep, 14:00 IST** | **Submit everything.** |
| **7 Sep** | Buffer day. Portal closes. |
| **7 Sep evening** | Shortlist announced. |
| **10–11 Sep** | Live event at i-Hub, Gandhinagar. |

### The "gate" — nothing is submitted until these three pass, on the day

```
PRAHARI_INTEGRATION=1 pytest tests/test_integration.py -v     # every leg green or explicitly skipped
python scripts/accuracy_report.py --golden fixtures/golden/   # regenerates the real numbers
make check                                                    # unit suites + the RBAC scope test
```

Only then are the deck's placeholder numbers replaced with that run's output.

---

## 16. Deliverables checklist (competition view)

| # | Deliverable | Format | Status |
|---|---|---|---|
| 1 | Solution presentation | PPT **and** PDF | Built (`docs/deck.html`); **needs 6 numbers + PDF export** |
| 2 | High-Level Design document | PDF | **Done** (`docs/hld.md`) — needs PDF export |
| 3 | Demo video, 2–3 min, own feed | MP4 / link | **Not started** |
| 4 | Live demo on government feed + output report | screen recording + report | **Rehearse; happens on the feeds** |
| 5 | The graded test case (plate → route) | shown live | **Feature works; needs rehearsal** |
| 6 | Scalability plan | in deck + HLD §11 | **Done** in HLD; deck slide 9 has the maths; add cost estimate |
| 7 | Hosted URL + test credentials | URL + 3 logins | **Not started** |
| 8 | Source repository link | link | **Done** — this repo (after the hygiene checklist) |

---

## 17. Key decisions and trade-offs

The honest engineering choices, so anyone reading the code understands *why*:

- **Pretrained models for the submission.** Fine-tuning (I11) is only in the 8–9 Sep event window
  — a dataset + labelling + training loop does not fit in 9 days alongside building the pipeline.
- **Plate localisation is a classical image-processing method** (blackhat/Sobel) until a detector
  is trained — no labelled data exists yet. A weights path is wired so it swaps in without code
  changes.
- **The vote requires two independent reads *and* a 2/3 per-character majority.** CONFIRMED
  additionally needs a grammar-valid string and three reads. One engine's opinion is a read, not
  a vote.
- **OCR runs on its own thread with a bounded queue**, not in the frame loop — inline OCR was
  measured to cost 28 of 30 frames of a vehicle pass. "The queue being full *is* the OCR budget."
- **Re-ID uses a plain ResNet-18 trunk**, not a purpose-built vehicle re-ID network — no
  permissively licensed checkpoint could be verified in the time available. Swappable later.
- **Analytics events do not go on Redis** — the contract (C2) has no analytics stream, and adding
  one needs both other owners' sign-off. They go to metrics and logs instead.
- **The WebSocket fan-out reads the whole stream** (not a consumer group) — a group would split
  alerts between API replicas, so half the consoles would miss half the alerts. Fan-out must be
  broadcast.
- **An exact watchlist match on a non-CONFIRMED sighting is raised as PROBABLE, never CONFIRMED.**
- **The route PDF's picture is a schematic, not a basemap** — there is no offline tile source we
  can legally ship, and calling an unreferenced line a "map" on a document an officer signs would
  be a lie.
- **Row-level security treats a connection with no user as maintenance** (migration, persister,
  matcher all connect without a user). The application scope check stays the primary control; RLS
  is the backstop for a query someone forgets to scope.
- **The golden set ships synthetic** until real clips are labelled — every row tagged, printed
  separately, and called an upper bound.
- **`make up` was verified on real Docker** (not just assumed) — postgres, redis, minio healthy.

---

## 18. Risks

In rough order of how likely they are to sink the submission:

1. **Uploading on the last evening.** The portal is slow when everyone does it. Hence the 6 Sep
   14:00 target — the 7th is a buffer, not the plan.
2. **A video that looks like a mock-up.** Explicitly rejected by the portal. Record the real
   thing, even if it is uglier, with `/metrics` visible.
3. **A deck number nobody can reproduce.** Every figure must trace to a command, or it comes off
   the slide.
4. **Credentials that don't work from outside our network.** Test the hosted URL and all three
   logins from a phone on mobile data, not the dev laptop.
5. **A PDF export that turns the architecture diagram into mush.** Export at print resolution,
   open it on someone else's machine.
6. **The grid moving behind a sign-in** (it already did once — RTSP-direct still works without a
   key; HLS needs `GRID_KEY` + `GRID_EMAIL`).

---

## 19. Glossary

| Term | Plain meaning |
|---|---|
| **ANPR** | Automatic Number Plate Recognition — reading a vehicle's registration plate from video. The one mandatory analytic. |
| **VMS** | Video Management System — the software a department already uses to view and record its cameras. |
| **NVR** | Network Video Recorder — the box that records IP cameras. |
| **RTSP** | The standard "live video stream" protocol for IP cameras. We force it over TCP because UDP dies across firewalls. |
| **ONVIF** | An open standard so cameras and software from different vendors can talk. "Profile S" is the streaming profile. |
| **HLS** | HTTP Live Streaming — video chopped into small files served over normal web requests. Higher latency, but works through restrictive networks. Our fallback when RTSP is blocked. |
| **WHEP / WebRTC** | Low-latency browser streaming. Used for the video wall where the network allows it. |
| **MediaMTX** | The open-source media server we use to relay/normalise streams. |
| **YOLOv8s** | A pretrained open-source object-detection model. The "s" is the small/fast size. We use it to detect vehicles. |
| **ByteTrack** | An algorithm that follows each detected object across frames and gives it a stable ID. |
| **OCR** | Optical Character Recognition — turning an image of text into text. We use two engines (EasyOCR, PaddleOCR) and vote. |
| **Re-ID** | Re-identification — an appearance "fingerprint" vector for a vehicle. Corroborates a route hop; never confirms one. |
| **PTS** | Presentation Time Stamp — the video's own clock. We timestamp sightings from this, never the server clock. |
| **Sighting record / row** | The ~200-byte JSON produced for each vehicle pass. The atom of the whole system. |
| **Watchlist** | The list of plates/entities of interest — stolen vehicles, wanted/missing persons, blacklists. |
| **Alert bands** | CONFIRMED / PROBABLE / POSSIBLE / NONE — how sure the system is, never averaged into one number. |
| **RBAC** | Role-Based Access Control — what each role is allowed to see and do (the C10 matrix). |
| **RLS** | Row-Level Security — the database itself filters rows by department, as a backstop to the application check. |
| **Audit hash-chain** | Each audit record includes a hash of the previous one, so tampering with history breaks the chain and is detectable. |
| **OSRM** | Open Source Routing Machine — snaps the vehicle's hops to actual roads. |
| **TimescaleDB** | A PostgreSQL extension for time-series data (our sightings). |
| **Redis Streams** | The message pipe between the worker and the core API. |
| **MinIO** | S3-compatible object storage — holds the small vehicle crops. |
| **ULID** | A time-sortable unique ID (like a UUID, but ordered by creation time). |
| **The grid / sandbox** | The organisers' set of ~30 test cameras served as looping "live" streams. |
| **VAHAN / SARTHI / eGujCop / AFIS / NAFIS** | State/national systems we must be integration-ready for: vehicle registry, licences, police case system, fingerprint systems. |
| **`# ponytail:`** | Our comment tag marking a deliberate shortcut, naming its ceiling and the upgrade path. |
| **P0 / P1** | Priority 0 = must ship for the submission. Priority 1 = nice-to-have, only for the live event. |
| **Lane** | One developer's area of ownership (Inference / Edge+Console / Core). |
| **Contract (C1–C10)** | A frozen data format or interface between lanes that must not change without telling everyone. |

---

## 20. Where to find things

| You want... | Look at |
|---|---|
| What is true right now, what's done, what broke | `knowledge_base.md` (read this first) |
| The stable identity, stack, commands, conventions | `AGENTS.md` |
| How the team is supposed to work | `CLAUDE.md` |
| Exactly what the judges require and score | `SENTINEL_HACKATHON.md` |
| A specific developer's task and boundaries | `TASK.md` (grep the ticket, never read whole) |
| Deep design detail | `sentinel-e2e-implementation-plan.md` (grep an anchor, never read whole) |
| The High-Level Design | `docs/hld.md` |
| What the ANPR model does and refuses | `docs/model-card.md` |
| The demo run sheet, chaos drills, rehearsals | `docs/demo-script.md` |
| The submission plan and the pre-submit gate | `docs/submission.md` |
| The 10-slide deck (spec / rendered) | `docs/deck-outline.md` / `docs/deck.html` |
| A visual status snapshot | `docs/status.html` |
| **This overview** | `PROJECT_OVERVIEW.md` |
| The camera list and coordinates | `data/cameras.seed.json`, `data/camera_geo.json` |
| How to run the whole thing | `make up`, `make seed`, `make check`, then the service commands in `AGENTS.md` |

---

*This document is a snapshot for reading and onboarding. The authoritative live state is always
`knowledge_base.md`.*
