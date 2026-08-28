# WORKPLAN — PLAN.md distributed across the team

[PLAN.md](PLAN.md) says *what* to build and *why it wins*. This file says **who
builds each piece and on which day**, for the real two-person team and the real
remaining clock.

**Written 2026-08-28 · 10 days to submission (7 Sep 14:00) · 8 days to feature
freeze (5 Sep 18:00)**

Owners are confirmed, not proposed. Ownership rules and file boundaries are in
[ROLES.md](ROLES.md); live task state is in [STATUS.md](STATUS.md).

---

## 1. Reality adjustment against PLAN.md

PLAN.md §7 was written assuming a team of 4–6 with a dedicated Lead, two CV
engineers, a backend, a frontend and a DevOps/Docs person. **The actual team is
two people**, both students, both also writing their own code with AI sessions.

That gap is the single biggest risk in the project, and it is not technical.
The distribution below collapses six planned roles onto two people:

| PLAN.md §7 role | Actually performed by |
|---|---|
| Lead / Architect | Priyanshu |
| CV Engineer 1 — plate detection, OCR, fusion | Neev |
| CV Engineer 2 — stream manager, tracking, Re-ID | Priyanshu |
| Backend — registry, correlation, alerts, DB | Priyanshu |
| Frontend — map, wall, alert console, route replay | Priyanshu, with Neev on plate-facing views |
| DevOps / Docs — deploy, videos, PDF report | **Nobody — see §5** |

Priyanshu carries four of the six roles. PLAN.md §7 states the Lead must stay
~40% unallocated to absorb surprises; that is not achievable here, so the scope
triage in §4 below is mandatory rather than optional.

---

## 2. Section-by-section distribution of PLAN.md

| PLAN.md section | Work | Owner | State |
|---|---|---|---|
| §1 Decoding the ask, three gates | Strategy | Priyanshu | ✅ Done |
| §2 Architecture choice (Model 1+3+4, edge-first) | Decision + defence | Priyanshu | ✅ Decided (CONTEXT.md D1) |
| §2 `GovDbAdapter` contract + mock provider | Backend | Priyanshu | 🔴 D-6 |
| §3 Grid rules baked into code | Stream manager | Priyanshu | ✅ Done |
| §3 `scripts/preflight.py` 8-point checklist | Tooling | Priyanshu | 🔴 D-4 |
| §4.1.1 Vehicle detection (YOLO) | CV | Priyanshu | ✅ Done |
| §4.1.2 Within-camera tracking (ByteTrack, PTS-driven) | CV | Priyanshu | ✅ Done (D9 tuning) |
| §4.1.3 Plate detection (localised crop) | CV | **Neev** | 🟡 Model sourced, not wired |
| §4.1.4 Plate recognition (OCR) | CV | **Neev** | 🔴 **0 reads — critical path** |
| §4.1.5 Vehicle Re-ID embedding | CV | Priyanshu | 🔴 D-7 fallback trigger |
| §4.2 Track-level fusion, format prior, confusion classes | CV | **Neev** | 🟡 Scaffolded |
| §4.3 Fuzzy watchlist matching + confidence bands | Backend | **Neev** | 🔴 D-6 |
| §4.4 Cross-camera route reconstruction | Backend | Priyanshu | 🔴 **D-9/D-8, gate G3** |
| §4.4 Spatio-temporal plausibility filter | Backend | Priyanshu | 🔴 D-8 |
| §4.4 PDF + CSV route report export | Backend | Priyanshu | 🔴 D-7 |
| §4.5 Camera health / NOC dashboard | Frontend | Priyanshu | 🔴 D-5 if time |
| §4.5 Counting / congestion per camera | Frontend | Priyanshu | 🟡 Counts already exist |
| §4.5 Intrusion zone, crowd density, abandoned object | CV | — | ⛔ Cut (see §4) |
| §5 RBAC + department scoping | Backend | Priyanshu | 🔴 D-5 |
| §5 Hash-chained audit log | Backend | Priyanshu | 🔴 D-5 |
| §5 DPDP posture, FR governance | Doc only | Doc owner | 🔴 Slide + HLD §11 |
| §6 Scale numbers (storage, GPU, bandwidth) | Doc only | Doc owner | ✅ Numbers computed, need writing up |
| §6 Load test — cameras per node | Measurement | Priyanshu | 🔴 D-8, produces a number judges ask for |
| §8 Public deployment + test credentials | DevOps | Priyanshu | 🔴 D-4 |
| §9.2 14-slide PPT | Docs | **Unassigned** | 🔴 **D-3/D-2** |
| §9.3 Q&A bank | Docs | Priyanshu | 🔴 D-2 |
| §10 HLD document (18 sections) | Docs | **Unassigned** | 🔴 **D-3/D-2** |
| §11 Questions to organisers | Admin | Priyanshu | 🔴 **Overdue — send today** |
| §12 Finale playbook, demo script | Priyanshu | Priyanshu | 🔴 D-2 |
| §14 Definition of done checklist | Both | Both | 🔴 D-1 |
| Demo Video A (own footage) | Docs | **Unassigned** | 🔴 D-2 |
| Demo Video B (govt feed + report) | Docs | **Unassigned** | 🔴 D-2 |

---

## 3. Day-by-day, two columns

PLAN.md §8 assumed twelve days from 26 Aug. Two of those are gone and the team
is a third of the assumed size, so the schedule below is compressed and
re-sequenced around the real critical path: **nothing downstream of plate OCR
can be demonstrated until plate OCR produces reads.**

| Day | Priyanshu | Neev |
|---|---|---|
| **28 Aug (today)** | Multi-camera supervisor; measure cameras-per-node. Email organisers §11 questions. RTSP hotspot test. | Wire real plate detector into `plate_reader.py`; fix EasyOCR fragment merging |
| **29 Aug** | Sighting store; cross-camera route assembler (plate-agnostic input) | RTO state-code validation; re-run the 22-camera measurement and record real numbers |
| **30 Aug** | Spatio-temporal plausibility filter; route polyline on the GIS map | Confusion-class character repair; extract `plate_routes.py` |
| **31 Aug** | Route report export (CSV + PDF) | Watchlist schema + CSV bulk import |
| **1 Sep** | **Re-ID fallback — trigger day.** If OCR still has no reads, this becomes the primary route mechanism | Fuzzy watchlist matching + confidence bands |
| **2 Sep** | Alert engine: priority, WebSocket push, ack/dismiss | Watchlist admin UI; alert evidence crops |
| **3 Sep** | RBAC + department scoping; hash-chained audit log; NOC dashboard | Accuracy measurement on a held-out set — the number for the Q&A bank |
| **4 Sep** | `preflight.py`; public deployment + test credentials, verified from an outside network | Support deployment; freeze plate models |
| **5 Sep** | **FEATURE FREEZE 18:00.** Videos A and B, output report | Video support, plate demo material |
| **6 Sep** | Rehearse demo ×3 timed; verify every submission link from a phone on mobile data | Same |
| **7 Sep** | **Submit by 14:00** | — |
| 8–9 Sep | Finale prep: offline build, backup laptop, printed report | Same |
| 10–11 Sep | i-Hub Gujarat — PLAN.md §12 | Same |

**Documents (HLD, PPT) must land 3–2 Sep.** They are unassigned, which means
right now they land on Priyanshu on top of everything in his column. That is
not survivable — see §5.

---

## 4. Scope triage — confirmed cuts

Ranked by what the organisers' evaluation framework actually rewards.

**Must ship — these are scored gates**
Working ANPR producing real reads · cross-camera route with timestamps ·
watchlist matching with live alerts · HLD · PPT · both demo videos · public URL
with test credentials.

**Ship if time allows**
RBAC · audit log · NOC dashboard · Docker Compose · preflight script.

**Cut — decided, not deferred**

| Cut | Reasoning |
|---|---|
| Postgres/PostGIS/Timescale migration | Costs a day, changes nothing a judge can see. JSON-on-disk demonstrates identically. The HLD names Postgres/PostGIS/Timescale as the production data layer — that is what is scored, not the sandbox implementation. |
| Kafka / Redis Streams bus | Same reasoning. Direct calls work at 15 cameras; the HLD describes the bus for 80k. |
| OpenSearch | The Python Levenshtein matcher already gives the same behaviour (CONTEXT.md D12). |
| Intrusion zones, crowd density, abandoned object | PLAN.md §4.5 explicitly says build only after core is green. Core is not green. |
| Face recognition | Heaviest, most privacy-fraught, and not required by any gate. Covered as governance policy in the HLD instead. |
| TensorRT INT8 conversion | An optimisation for 80k cameras, not for a 15-camera demo. Quote the numbers in the HLD. |

Every cut item stays in the HLD as designed-and-justified architecture. The
organisers score the *design* for scalability and the *demo* for working
software; conflating the two wastes the remaining days.

---

## 5. The unassigned-documents problem

**Three of the seven scored evaluation areas are documentation:** Solution
Presentation, Solution Architecture (the HLD), and Submission Completeness. A
working platform with no deck and no video scores badly, and PLAN.md §13 lists
"feature creep kills the docs" as a high-probability, high-impact risk.

Nobody owns the HLD, the PPT, or the two demo videos.

Three options, in order of preference:

1. **Recruit a third member for documents and video.** Category 1 permits
   student teams; the team-size cap is still an open question with the
   organisers (CONTEXT.md §7). This person needs no coding ability — they need
   the ability to write clearly and edit a 3-minute video. Highest leverage
   available right now.
2. **Priyanshu reserves 3–5 Sep entirely for documentation**, and everything in
   his column from 3 Sep onward (RBAC, audit log, NOC dashboard, preflight) is
   cut. The platform stops improving three days before submission.
3. **Neev takes the HLD** once plate OCR is working, since he will have the
   accuracy numbers and can write §9 of the HLD from direct knowledge, while
   Priyanshu takes the deck and videos.

**This needs a decision from Priyanshu today**, not on 3 September. It is the
one item on this page where a day of delay costs more than a day.

---

## 6. Definition of done ownership

PLAN.md §14 has 13 checkboxes. Mapped:

| Checkbox | Owner |
|---|---|
| Cameras auto-onboarded, on GIS map, live health | Priyanshu ✅ |
| Video wall mixed codec, survives feed restart | Priyanshu ✅ |
| ANPR plate + confidence + crop, measured accuracy | Neev |
| Plate → route + timestamps + polyline + PDF/CSV | Priyanshu |
| Watchlist + fuzzy match + alerts + ack + audit | Neev (match) · Priyanshu (alerts, audit) |
| RBAC with department scoping | Priyanshu |
| Preflight checklist green | Priyanshu |
| Public URL + test credentials from outside network | Priyanshu |
| Repo + README + one-command bring-up | Priyanshu |
| Video A | Doc owner |
| Video B + output report | Doc owner |
| PPT + HLD uploaded, permissions verified | Doc owner |
| Submitted by 14:00 on 7 Sep | Priyanshu |
