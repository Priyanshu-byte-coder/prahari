# Sentinel 2026 — Gujarat Police CCTV Integration Hackathon: Plan to Win

**Source of truth:** https://sentinel.gujarat.gov.in (Home, About, Phases, Problems, Schedule, Resources, FAQs, Contact, Register — all read 26 Aug 2026)

**Prize pool:** ₹51,00,000 · **Submission deadline:** 07 Sep 2026 · **Shortlist:** 07 Sep evening · **Event:** 10–11 Sep 2026, i-Hub Gujarat, Gandhinagar · **Results:** 11 Sep 2026

**Assumptions (correct me if wrong):**
- We enter **Category 1** (student team / researchers / professionals). Category 2 is large startups & companies, with a separate, richer prize table.
- Team of 4–6, at least one machine with an NVIDIA GPU (RTX 3060 or better) available for training/inference.
- ~12 calendar days from today to submission. This plan is built for that clock.

---

## 1. What the organisers actually want (decoded)

The public framing is "AI CCTV hackathon". The real ask, stripped down:

> Gujarat has 26 departments running fragmented CCTV islands (analog + IP, multiple VMS vendors, different retention, sites up to 1,000 km apart). Build the **unification layer** — inventory + feed integration + AI analytics + watchlist correlation + real-time alerts — that could plausibly scale to **~80,000 cameras**, without replacing what departments already own.

Three hard gates, all stated on the site:

| Gate | Requirement | Where stated |
|---|---|---|
| G1 | **Model 1 (Centralised CCTV Registry & GIS) is mandatory** and must be combined with at least one other model | FAQ #12, Problems Step 2 |
| G2 | **Working software only.** "Mock-ups, animations, simulated interfaces, or concept videos without an operational backend will not be considered." | Problems Step 5, FAQ #32 |
| G3 | On evaluation day they hand you a **vehicle registration number**; your platform must find it across ~50 heterogeneous cameras and output a **timestamped, location-wise route** | Problems Step 4, FAQ #27 |

Plus a continuous **watchlist cross-reference with automated real-time alerts** (you supply your own representative watchlist DB).

**Strategic read:** G3 is where most teams will die on stage. Indian plate OCR on real low-res CCTV at night, on a stream you cannot rewind, is genuinely hard. Everything in §4 is designed so that we *still produce a defensible route* even when OCR is imperfect. That single design decision is probably worth more than any other engineering choice in this plan.

---

## 2. Architecture decision — and how to defend it in one sentence

**Choose: Hybrid = Model 1 (mandatory registry/GIS) + Model 3 (federation middleware) + a selective Model 4 analytics plane, with edge-first inference.**

Do **not** pitch pure Model 4 (fully central VMS). Here is the number that kills it, and you should put it on a slide:

- 80,000 cameras × 2 Mbps (H.265, 1080p) = **160 Gbps** sustained backhaul to one datacentre.
- 15-day retention at 2 Mbps = 324 GB/camera → **~26 PB** of hot+warm storage.

Then the one-liner that wins the architecture question:

> "Video is heavy, metadata is light. We move **metadata to the centre and compute to the edge** — the state gets one unified operational picture without a 160 Gbps backbone or 26 PB of central storage. Full-resolution video only crosses the WAN on demand, when an operator or an alert asks for it."

### Layers

```
[ L0 SOURCES ]  Dept cameras / NVR / VMS · analog (encoder) · IP · private (permitted, view-only)
                RTSP / ONVIF / vendor SDK / HLS
                        |
[ L1 EDGE    ]  District Edge Node (containerised, 1 per district / cluster)
                |- Stream Manager: TCP-forced RTSP, PTS-driven, auto-reconnect w/ backoff
                |- Decode: NVDEC (H.264 + H.265), adaptive frame sampling
                |- Inference: vehicle det -> plate det -> plate OCR -> vehicle Re-ID embedding
                |             person det -> (optional) face embedding
                |- Emits ONLY events + thumbnails (~2 KB/event) upstream
                        |  (mTLS, store-and-forward buffer if WAN drops)
[ L2 BUS     ]  Kafka / Redis Streams   topics: detections, health, alerts
                        |
[ L3 CORE    ]  |- Registry Service (MODEL 1) — camera master data + GIS
                |- Correlation Engine — watchlist match, fuzzy plate match, dedupe
                |- Track Assembler — cross-camera route reconstruction
                |- Alert Engine — rules, priority, escalation, ack/audit
                |- Federation Adapters (MODEL 3) — per-vendor plugins:
                |     Milestone-like, Genetec-like, Hikvision/Dahua SDK, generic ONVIF, generic RTSP
                |- Stores: PostgreSQL + PostGIS (registry/geo) · TimescaleDB (events)
                |          OpenSearch (search) · MinIO/S3 (snapshots, clips)
                        |
[ L4 APPS    ]  React SPA: GIS map (Leaflet) · video wall (WebRTC WHEP, HLS fallback)
                · vehicle search + route replay · alert console · watchlist admin
                · camera health / NOC dashboard · audit log viewer
                REST + WebSocket + OpenAPI; integration-ready connectors for
                VAHAN / SARTHI / eGujCop (CCTNS) / AFIS / NAFIS (adapter stubs + contract)
```

**Government DB integration:** we will not have real VAHAN/SARTHI/eGujCop access. Do **not** fake it. Build a `GovDbAdapter` interface with a documented request/response contract, ship a **mock provider** loaded with a representative watchlist (stolen vehicles, wanted persons, missing persons, blacklisted vehicles), and state on the slide: *"swap one config line to point at the real endpoint; the contract is already written."* That reads as integration-ready engineering, not hand-waving. Judges from SCRB will recognise the difference.

---

## 3. The Sandbox Integration Guide is the exam paper — treat it that way

The Resources page ("Consuming the Sentinel Camera Grid") is effectively a list of the ways client pipelines fail. Every item is a scoring opportunity. Bake each into code **and** show it on a slide called "Built for the real grid".

| Grid behaviour | What breaks | Our implementation |
|---|---|---|
| Live RTP/RTSP, no seek, no download | Teams who plan to download footage | Live capture from day 1; never build against a local copy |
| UDP fails on NAT/firewall | Corrupt frames that look like model bugs | `rtsp_transport=tcp` forced everywhere; HLS fallback if 8554 blocked |
| `CAP_PROP_FPS` lies | Wrong speed / dwell / velocity | Never read declared FPS; measure it or ignore it |
| GOP replay on connect → burst of frames | Trackers compute impossible velocities right after every connect | **All timing from PTS** (`CAP_PROP_POS_MSEC` / GStreamer buffer PTS); Kalman fed PTS deltas |
| Non-uniform frame intervals | Gap treated as a disconnect | Gap tolerance; motion model uses actual elapsed PTS |
| Feeds are supervised and restart | Tight reconnect loops | Exponential backoff 2 s → 30 s cap, jittered |
| Mixed H.264 + H.265, join mid-stream | `Error constructing the frame RPS` aborts pipeline | Decoder warnings logged, never fatal; wait for first IDR |
| Non-uniform resolution/codec/bitrate | Fixed-shape inference batch fails | Per-camera props read from `/api/ingest`; dynamic batching |
| Recording **loops** → hard scene cut | Background models, Re-ID galleries, track IDs corrupt | Discontinuity detector (PTS regression + scene change) → soft-reset track state, keep event history |
| Each client gets its own stream copy | Grid overload, throttling | Connection pool; open only cameras actively processed; explicit release |
| Do not publish / do not call control API | Disqualification risk | Consume-only, enforced in code review |

`GET /api/ingest` is **the contract** — camera ids change. Never hard-code endpoints; poll the catalogue, diff it, auto-onboard new cameras into the registry. Auto-onboarding from `/api/ingest` is itself a Model-1 demo moment.

Ship a `scripts/preflight.py` that runs the 8-point pre-submission checklist from that page and prints a green table. Put that table in the demo video. It signals "we read your docs" louder than any slide.

---

## 4. The vehicle-tracking pipeline (this is where the hackathon is won)

### 4.1 Detection & recognition stack

1. **Vehicle detection** — YOLOv8/YOLO11-s, COCO classes car/truck/bus/motorcycle. TensorRT FP16.
2. **Tracking within camera** — ByteTrack / OC-SORT, **driven by PTS deltas**, not frame count.
3. **Plate detection** — YOLO-nano fine-tuned on Indian plates. Data: Roboflow "Indian Number Plate" sets, CCPD (structure transfer), plus self-labelled crops from the sandbox grid itself (label 300–500 crops on day 3 — highest-ROI hour of the whole build).
4. **Plate recognition** — PARSeq or a small CRNN/CTC, or PaddleOCR-v4 fine-tuned. Train on synthetic Indian plates (generate ~50k with correct font/spacing/state codes + augmentation: blur, motion, glare, night, rain, angle) then fine-tune on real crops.
5. **Vehicle Re-ID embedding** — lightweight OSNet/CLIP-ReID embedding + colour histogram + coarse type. This is the safety net for G3.

### 4.2 Track-level fusion (the accuracy multiplier)

Do **not** classify a plate from one frame. Per vehicle track, collect every plate read, then:

- **Per-character confidence voting** across N reads (weight by crop sharpness × plate area × detector confidence).
- **Format prior:** Indian plates match `^[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{0,3}[ -]?\d{4}$`. Reject or repair reads that violate it. Validate the state code against the real RTO list (`GJ`, `MH`, `RJ`, …) and district digits for GJ (01–38).
- **Positional confusion classes:** `0↔O·D·Q`, `1↔I·L`, `8↔B`, `5↔S`, `2↔Z`, `6↔G`. Resolve by *position*: positions 1–2 must be letters, last 4 must be digits. Roughly half of raw OCR errors vanish here.
- Output: `plate_string`, `confidence`, `n_reads`, `best_crop_url`.

### 4.3 Fuzzy watchlist matching

Never do exact string equality against the watchlist. Match with **weighted edit distance** where confusion-class substitutions cost 0.25 instead of 1.0. Bands:

- distance 0 → **CONFIRMED** alert
- ≤ 0.5 → **PROBABLE** alert (shown, flagged, operator-confirmable)
- ≤ 1.5 → **POSSIBLE** candidate (queued, not paged)

Show the confidence band in the UI. Every alert carries the evidence crop + camera + PTS timestamp + geo point. **Operator ack/dismiss is recorded** — that closes the audit loop and reads as real police software, not a demo.

### 4.4 Cross-camera route reconstruction

Given a query plate:

1. Pull all detections in the window, exact + fuzzy.
2. Add Re-ID candidates whose embedding matches a confirmed sighting above threshold, even when the plate was unreadable — **this is how we recover a route when OCR fails on 3 of 8 cameras.**
3. **Spatio-temporal plausibility filter:** between consecutive sightings, implied speed = road distance / Δt. Reject sightings requiring >120 km/h or physically impossible ordering. Cuts false positives hard and is a great judge-facing explanation.
4. Emit an ordered polyline on the GIS map with timestamps, dwell gaps, per-hop confidence, and thumbnail evidence per hop. Export as **PDF + CSV** — that is literally the "output report showing detected vehicles or number plates with corresponding timestamps" required in Step 5.

### 4.5 Beyond mandatory (bonus points — build only after core is green)

Ranked by (judge impact ÷ effort): **camera health / NOC dashboard** → **ANPR-based counting & congestion per camera** → **loitering / intrusion zone (draw polygon on feed)** → **crowd density estimate** → **abandoned-object detection** → face recognition (do last: heaviest and most privacy-fraught).

---

## 5. Privacy, security & compliance (cheap points almost everyone forgets)

The evaluation list includes cybersecurity, and the bonus list explicitly names "enhanced cybersecurity, privacy protection, auditability, RBAC". One slide plus real implementation:

- **DPDP Act 2023 posture:** purpose limitation, data minimisation (store embeddings + crops, not full video, at the centre), stated retention per data class.
- **RBAC:** Viewer / Analyst / Investigator / Dept-Admin / State-Admin. Department scoping enforced at the query layer — a Panchayat operator cannot see Health cameras.
- **Immutable audit log** (hash-chained) of every feed view, plate search, watchlist edit, alert action. Demo it: run a search, then show the audit entry appear.
- **Face recognition governance:** off by default, per-case authorisation, four-eyes approval to enable, everything logged. Say plainly that FR is used for *investigative lead generation*, not automated action. A police + forensic-university panel respects this framing.
- Transport mTLS edge↔core, secrets in a vault, network segmentation, signed container images, no default credentials.
- **Private cameras** (societies/malls, FAQ #7): consent-registered, view-only, opt-in, separate legal basis, clearly marked in the registry with a different map layer.

---

## 6. Scale plan for ~80,000 cameras (put these exact numbers on a slide)

**Storage** — video stays at the edge/department; the centre stores metadata + evidence only:

- Per camera: 2 Mbps H.265 ≈ 21.6 GB/day → 15 days = **324 GB**
- 80k cameras, distributed: **~26 PB** total; **central** load = events + snapshots ≈ 50 KB/camera/day → **~4 GB/day statewide**, ~1.5 TB/year. This contrast is the whole argument.

**Compute** — analytics on the ~30% of cameras that are ANPR-relevant (24,000):

- Sampling 5 fps for detection (not 25) is a 5× saving with no meaningful ANPR loss.
- YOLO-s @ 640, TensorRT INT8 on **NVIDIA L4** ≈ 400–500 inferences/s → ~80–90 ANPR cameras per L4 including OCR crops.
- 24,000 ÷ 85 ≈ **~280 L4-class GPUs**, distributed across ~33 district edge nodes (≈8–9 GPUs each) + regional aggregation at 4 zonal DCs + state core.

**Network:** central-only would need 160 Gbps. Edge-first needs **~50 Mbps per district node** for events, bursting only for on-demand video pull. Low-bandwidth mode: event-only sync, snapshot instead of clip, store-and-forward queue on WAN loss.

**Rollout (phased, 24 months):** Phase A registry + GIS for all 26 departments (metadata only, zero disruption, 3 mo) → Phase B federation adapters for the top-4 VMS vendors + 5,000 cameras across 4 cities (6 mo) → Phase C ANPR at 20,000 high-value cameras (9 mo) → Phase D statewide 80k + DR site (24 mo).

**Cost-benefit (indicative — label it as such):** edge-first vs full-central avoids the 160 Gbps backbone and ~26 PB of central storage. Give a rough ₹ range for edge GPU nodes, core cluster, storage, and 5-year O&M, with the assumption base stated openly. Judges penalise fake precision more than honest ranges.

**HA/DR:** active-active core across two state DCs, RPO 15 min / RTO 1 hr for metadata; edge nodes autonomous for 72 hrs offline (alerts still fire locally); quarterly DR drill in the ops plan.

---

## 7. Team & roles (4–6 people)

| Role | Owns | Never blocked on |
|---|---|---|
| **Lead / Architect** | HLD doc, PPT, judge-facing narrative, demo script, integration decisions | anything — must stay ~40% unallocated |
| **CV Engineer 1** | Plate detection + OCR training, track-level fusion | frontend |
| **CV Engineer 2** | Stream manager (PTS / reconnect / discontinuity), tracking, Re-ID | model training |
| **Backend** | Registry + GIS API, correlation engine, alert engine, Postgres/PostGIS/Timescale, Kafka | UI |
| **Frontend** | React: map, video wall (WHEP), alert console, route replay, reports | models |
| **DevOps / Docs** (can be the Lead if 4-person) | Docker Compose + k8s manifests, public deploy + test creds, videos, PDF/CSV report | — |

**Non-negotiable rituals:** 15-minute standup at 10:00 and 21:00 IST. Trunk-based git, `main` always demoable. A **feature freeze at 18:00 on 5 Sep** — the last 48 hours are for docs, video, and rehearsal only. Teams lose this competition by coding until midnight on deadline day and submitting a broken link.

---

## 8. Day-by-day plan (26 Aug → 11 Sep)

### D0 — TODAY, 26 Aug (do this before you sleep)
- [ ] **Register on sentinel.gujarat.gov.in** (free, email OTP). Category 1 unless we register a DPIIT startup.
- [ ] Log in → Resources → capture the **sandbox host, `/api/ingest` output, and credentials**. Save the full catalogue JSON to `data/catalogue/`.
- [ ] Verify: can we reach RTSP port 8554 from our network? If blocked, WHEP/HLS is plan B — find out **now**, not on 6 Sep.
- [ ] Repo skeleton + Docker Compose (postgres+postgis, timescale, redis/kafka, minio, api, worker, web).
- [ ] Email `sentinel.hackathon@gujarat.gov.in` with our clarifying questions (see §11). Early questions get answered; 6 Sep questions do not.

### D1–D2 — 27–28 Aug · Ingest spine
- Stream Manager: TCP-forced, PTS-based, backoff reconnect, discontinuity detection, mixed H.264/H.265, per-camera props from `/api/ingest`. Prove it by killing and restoring a feed.
- Registry + PostGIS schema; auto-onboard every camera from the catalogue; Leaflet map showing all ~50 with live/down status.
- **Milestone M1: all sandbox cameras onboarded, visible on the map, and streaming in a browser video wall.**

### D3–D5 — 29–31 Aug · ANPR core
- Vehicle detection + ByteTrack (PTS-driven) running on N cameras in parallel.
- Plate detector fine-tune; **label 300–500 real crops from the sandbox grid** — the single highest-ROI task in the build.
- OCR: synthetic pretrain + real fine-tune. Track-level voting + format prior + confusion-class repair.
- **Milestone M2: plate string with confidence, written to Timescale, visible in UI, with measured accuracy on a held-out set of our own grid crops.**

### D6–D7 — 1–2 Sep · Correlation, alerts, route
- Watchlist DB + admin UI + bulk CSV import (build a representative watchlist: stolen vehicles, wanted, missing, blacklisted).
- Fuzzy matcher with confidence bands; alert engine with priority, WebSocket push, ack/dismiss + audit.
- Cross-camera route assembler + spatio-temporal filter + map polyline + PDF/CSV export.
- **Milestone M3: give the system any plate → correct route with timestamps, evidence crops, exportable report.**

### D8 — 3 Sep · Harden + bonus
- Re-ID fallback path. Camera health / NOC dashboard. RBAC + audit viewer. Preflight script green.
- Load test: how many concurrent cameras does one node hold? Record the number — judges ask.

### D9 — 4 Sep · Deploy + lock approach
- Public deployment (cloud GPU VM, or a tunnelled on-prem box). **Test credentials created and verified from an outside network.** Seed demo data.
- HLD document draft complete. Architecture diagrams: one system diagram, one dataflow, one deployment topology.

### D10 — 5 Sep · Documents + videos (FEATURE FREEZE 18:00)
- **Video A (own feed, 2–3 min):** our own footage/phone video → onboarding → ANPR → watchlist match → real-time alert. Tight, no dead air, subtitles.
- **Video B (government feed):** onboard sandbox cameras → live viewing → analytics output → plate detections with timestamps + the **output report**.
- PPT (§9). HLD final (§10). Upload to Drive/OneDrive with **"Anyone with the link — Viewer"**; YouTube set to **Unlisted**.

### D11 — 6 Sep · Rehearse + verify links
- Full submission dry run: open every link in a private browser window, on a phone, on mobile data. A dead link is an automatic loss.
- Rehearse the 8-minute demo three times, timed. Prepare the Q&A bank (§9.3).

### D12 — 7 Sep · SUBMIT EARLY
- Submit by **14:00**, not 23:00. Portals fall over on deadline day and there is no appeal.
- Shortlist announced that evening. If we are through → §12.

### 8–9 Sep · Finale prep
- Rehearse under venue-like conditions: laptop + hotspot only, no home LAN. Offline fallback build. Print the report. Charge everything.

### 10–11 Sep · i-Hub Gujarat
- See §12.

---

## 9. The pitch

### 9.1 One-liner
> "Sentinel Grid: one registry, every camera; one map, every alert. We put compute at the edge and intelligence at the centre — so Gujarat can go from 50 cameras to 80,000 without a new backbone."

### 9.2 PPT skeleton (14 slides, ~1 min each)
1. Title + team + category
2. The problem in one picture: 26 departments, 26 islands
3. Our model choice: **Model 1 (mandatory) + Model 3 + selective Model 4** — with the one-line justification
4. System architecture (the L0–L4 diagram)
5. Integration strategy: adapters for RTSP / ONVIF / SDK / HLS + analog encoders
6. AI analytics: detection → tracking → plate → **track-level fusion** (show the accuracy lift number)
7. Watchlist correlation + fuzzy matching + alert workflow
8. **Cross-camera route reconstruction** (the G3 money slide — real screenshot, real route)
9. "Built for the real grid" — the §3 table (PTS, TCP, reconnect, discontinuity, mixed codecs)
10. Security, privacy, DPDP, RBAC, audit
11. Scale to 80k: the storage / bandwidth / GPU numbers from §6
12. Cost-benefit + phased rollout
13. What we need from departments (the §11 list — shows deployment thinking)
14. Roadmap + ask

### 9.3 Q&A bank — prepare exact answers
- *What is your ANPR accuracy, and on what test set?* — give a real number with the test-set description. Never say "very high".
- *What happens at night / in rain / on a motorcycle plate?* — degradation numbers + the Re-ID fallback.
- *How do you handle a false alert on a wanted person?* — confidence bands, human in the loop, no automated action, audit trail.
- *Can this run on our existing hardware?* — edge node spec + minimum viable config.
- *What if a department refuses API access?* — ONVIF fallback → RTSP fallback → registry-only (Model 1 still delivers value). Graceful degradation is the answer.
- *How long to onboard a new department?* — adapter effort estimate in person-days.
- *Cost per camera per year?* — a range with stated assumptions.

---

## 10. HLD document outline (maps 1:1 to their Step-5 bullet list)

1. Executive summary
2. Scope & assumptions
3. Chosen model + justification
4. Overall architecture (diagrams)
5. Component specs (each of L0–L4)
6. Heterogeneous integration approach — IP, analog + encoder, multi-vendor VMS, per-protocol adapter matrix
7. Geographically dispersed ingestion; edge vs central decision matrix
8. Watchlist integration + correlation logic + real-time alert workflow (prioritisation, visualisation, operator interaction)
9. AI analytics: ANPR, FRS, object detection, person/vehicle tracking
10. Data model + retention + lifecycle
11. Security architecture + privacy + DPDP + RBAC + audit
12. Scalability to 80k (§6 numbers)
13. Infrastructure sizing + BOM
14. Cost-benefit
15. **Prerequisites & information required from departments** — they explicitly ask for this, and most teams skip it, so it is free differentiation
16. DR / HA
17. Rollout roadmap
18. Appendix: API spec, adapter interface, test results

---

## 11. Questions to email the organisers on Day 0

1. Are the ~50 evaluation cameras the same grid as the ~30+ published on Resources, or an expanded set on event day?
2. Is the designated vehicle guaranteed to be plate-readable on multiple cameras, or should we assume partial occlusion?
3. Is internet allowed at the venue for a cloud-hosted deployment, or must the solution run fully offline on our own hardware?
4. Is there a team-size cap for Category 1? Can a mixed student + working-professional team enter Category 1?
5. Will `/api/ingest` credentials for the finale differ from the sandbox ones?
6. Is a hosted-URL submission with test credentials evaluated in addition to the videos, or only as a backup?
7. Any restriction on pre-trained model licences (e.g. YOLO AGPL) for a solution intended for government deployment?

Question 7 matters more than it looks: **Ultralytics YOLO is AGPL-3.0.** For a "deployment-ready government solution" that could become a real procurement, we should either say so openly on a licence slide or use a permissive alternative (YOLOX / Apache-2.0, RT-DETR, or another licence-clean detector). Raising this ourselves signals commercial maturity that student teams almost never show.

---

## 12. Finale playbook (10–11 Sep, i-Hub Gujarat)

**Before leaving home:** two laptops (primary + identical backup), the GPU box if portable, two mobile hotspots on different carriers, HDMI + all adapters, an offline build that works with zero internet, local copies of every model weight, printed HLD + report + 6 copies of a one-page summary, all videos on a USB stick *and* on the laptop.

**On arrival:** claim a spot near power, test the projector immediately, test hotspot bandwidth, run preflight against the venue's grid, warm the model caches. Never let the first stream open happen in front of the judges.

**The 8-minute demo script (rehearse until the timing is automatic):**
- 0:00–0:45 — Problem + our one-liner. Map already on screen with all cameras live.
- 0:45–2:00 — Registry & GIS: onboard a *new* camera live from `/api/ingest` → it appears on the map in seconds. (Proves Model 1 works, not just exists.)
- 2:00–3:30 — Video wall: multi-camera grid, mixed codecs; kill one feed and let it auto-recover while you keep talking. **Deliberately show the reconnect.** It reads as production-grade.
- 3:30–5:30 — **The money moment:** judge gives the plate → type it in → route appears on the map with timestamps + evidence crops → export the PDF report and hand it to them physically.
- 5:30–6:45 — Watchlist alert firing live: alert pops on screen, operator acknowledges, audit entry appears.
- 6:45–8:00 — Scale slide (the numbers), security/privacy, and the ask.

**Failure drills — rehearse each:**
- Grid down → switch to recorded local feeds, keep narrating, do not apologise twice.
- Plate not detected → show the Re-ID candidate route and the confidence band, then explain *why* it degraded. Judges score honest failure analysis far above a frozen screen.
- Internet dead → offline build, same demo.
- Laptop dies → backup laptop, same repo commit.

**Read the room:** the panel is Gujarat Police leadership + a technical jury + NFSU / DA-IICT academics. Lead with **operational value to a control-room operator**, back it with architecture, and never say "it's just a prototype".

---

## 13. Risk register

| Risk | P | Impact | Mitigation |
|---|---|---|---|
| ANPR fails on grid quality | High | Critical | Track-level fusion + fuzzy match + **Re-ID fallback route**; label real grid crops on D3 |
| RTSP 8554 blocked on our network | Med | High | Test on D0; WHEP/HLS fallback path built in |
| No GPU / insufficient compute | Med | High | Rent a cloud GPU by D1; INT8 + 5 fps sampling; scope how many cameras run concurrently |
| Feature creep kills the docs | High | High | **Feature freeze 5 Sep 18:00**, non-negotiable |
| Submission link broken / wrong permissions | Med | Critical | D11 verification from an outside device on mobile data |
| Portal down on deadline day | Med | Critical | Submit 7 Sep by 14:00 |
| Loop discontinuity corrupts tracks mid-demo | Med | Med | Discontinuity detector + state reset, tested |
| Team member unavailable in the final week | Med | High | Every component has a documented second owner |
| Licence challenge on AGPL models | Low | Med | Raise it first; keep a permissive-detector branch ready |

---

## 14. Definition of done (tick before submitting)

- [ ] All ~50 sandbox cameras auto-onboarded from `/api/ingest` into the registry, on the GIS map, with live health status
- [ ] Video wall streams mixed H.264/H.265 at mixed resolutions and survives a feed restart on camera
- [ ] ANPR produces plate + confidence + evidence crop, measured on a held-out set with a stated number
- [ ] Any plate → cross-camera route with timestamps, map polyline, evidence, and PDF + CSV export
- [ ] Watchlist DB + fuzzy matching + real-time alerts + operator ack + audit entry
- [ ] RBAC with department scoping, enforced and demonstrable
- [ ] Preflight checklist (all 8 items from the Resources page) prints green
- [ ] Public URL live with working test credentials, verified from an outside network
- [ ] Git repo accessible with README + one-command Docker Compose bring-up
- [ ] Video A (own feed, 2–3 min) — unlisted YouTube, verified playable
- [ ] Video B (government feed) + output report with plates and timestamps
- [ ] PPT (14 slides) + HLD (18 sections) — PDF, uploaded, link permissions verified
- [ ] Submitted by 14:00 on 7 Sep

---

## 15. Where the marks actually are (their criteria → our artifact)

| Their evaluation area | Our proof |
|---|---|
| 01 Successful test case on govt feed | Auto-onboarding from `/api/ingest` + live video wall + ANPR output (Video B) |
| 02 Solution presentation | 14-slide PPT with model justification |
| 03 Solution architecture | HLD, L0–L4 diagrams, edge-first defence with real numbers |
| 04 Working platform maturity | Hosted URL + test creds + public repo + one-command bring-up |
| 05 Video analytics output | Plate + timestamp report (PDF/CSV), accuracy number, extra analytics |
| 06 Scalability & PoC readiness | §6 numbers, phased rollout, load-test result |
| 07 Submission completeness | §14 checklist, verified links |
| **Bonus** — hybrid architecture | Model 1 + 3 + 4 hybrid with stated rationale |
| **Bonus** — cross-camera correlation | Route reconstruction + spatio-temporal filter + Re-ID fallback |
| **Bonus** — analytics beyond ANPR | Health / NOC dashboard, counting, intrusion zones |
| **Bonus** — edge / low-bandwidth | Edge inference, store-and-forward, event-only sync mode |
| **Bonus** — security / privacy / audit | RBAC, hash-chained audit log, DPDP posture, FR governance |
| **Bonus** — dashboards & APIs | Alert console, OpenAPI spec, integration-ready gov-DB adapters |

Every bonus row is claimed. That is the plan.
