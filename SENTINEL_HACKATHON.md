# Sentinel — Gujarat Police CCTV Integration Hackathon 2026
Source: https://sentinel.gujarat.gov.in (about, problems, phases, resource, schedule, faqs) — scraped 2026-08-28

## Identity
"Protect What Matters." Gujarat Home Dept / State Crime Records Bureau (SCRB) challenge to build a
unified, vendor-neutral platform integrating fragmented Government CCTV + AI analytics + watchlist
correlation. "Not a simulation. Not a proof of concept." Mock-ups/concept videos rejected.

## Problem
- 26 Government Departments run independent CCTV systems statewide.
- Heterogeneous vendors, analog + IP cameras, separate VMS, separate storage, retention 7–15+ days.
- No unified asset inventory, no interoperability, no cross-department search or correlation.
- Departments: traffic, law & order, civil supplies, RTO, Health, GSRTC, Panchayat, Municipal.

## Expected solution
Secure, scalable, interoperable, cost-effective, uses existing infrastructure maximally.
1. Live integration of ~50 heterogeneous cameras (scale path to ~80,000).
2. AI analytics correlating streams with watchlists (stolen vehicles, wanted/missing persons).
   ANPR mandatory baseline. Optional: face recognition, crowd counting, anomaly detection, person tracking.
3. Real-time alerts on database match.
4. Cross-camera vehicle tracking with timestamped movement history.
5. GIS visualisation of routes/events.
6. RBAC per department; APIs ready for VAHAN, SARTHI, eGujCop, AFIS, NAFIS.
7. Encryption, network segmentation, DR, redundancy, audit.
8. Scale plan: GPU capacity, bandwidth, tiered hot/warm/cold storage, load balancing, monitoring, capex/opex estimate.

### Architecture models (pick one or hybrid)
- M1 Centralised CCTV Registry & GIS Mapping (metadata only)
- M2 Unified Viewing & Metadata Analytics (single UI, existing VMS untouched)
- M3 VMS Federation & Middleware (interop layer, no centralisation)
- M4 Central VMS (fully integrated statewide)
- Hybrid/Custom (bonus points)

## Deliverables (mandatory)
1. Solution presentation PPT/PDF — model chosen + justification, architecture, AI approach, scalability.
2. High-Level Design (HLD) — integration approach, watchlist correlation, alert workflow, security, interop assumptions.
3. Screen-recorded demo, max 2–3 min, on your OWN CCTV feed: onboarding → AI detection → watchlist match → alert.
4. Live demo on Government-provided feeds: timestamped video analytics output + detection reports.
5. Test case: given a vehicle registration number, produce full route history (locations + timestamps) across the ~50-camera grid.
Submission via unlisted YouTube link OR Google Drive/OneDrive (viewer access) OR hosted URL with test creds.
GitHub/GitLab repo optional.

## Evaluation (7 areas)
gov-feed test case success · presentation clarity · technical/architecture soundness · platform maturity ·
analytics output quality (timestamps, accuracy) · scalability & PoC readiness · submission completeness.
Bonus: hybrid architecture, multi-camera tracking, analytics beyond ANPR, edge processing/bandwidth
optimisation, cybersecurity/auditability, operational dashboards.

## Tech constraints
Open-source only. Suggested: React, Python, Node.js, PostgreSQL, PostGIS, WebRTC, RTSP, Kafka, RabbitMQ,
TensorFlow, PyTorch, FFmpeg, GStreamer, Leaflet, OpenLayers. Open/modular/standards-based/vendor-neutral, no lock-in.

## Provided grid (Sentinel Camera Grid)
- 30+ cameras, ~12h footage each, 5 departments, real infra footage, no synthetic data.
- Served as looping simulated live streams by a Python middleware.
- Catalogue: `GET http://<host>/api/ingest` → ids, locations, codecs, status, stream props, endpoint URLs.
- RTSP  `rtsp://<host>:8554/stream/<id>`      → AI inference (OpenCV/GStreamer/FFmpeg/DeepStream)
- WHEP  `http://<host>:8889/stream/<id>/whep` → low-latency browser preview
- HLS   `http://<host>/live/stream/<id>/index.m3u8` → dashboards/mobile/restricted networks

### Gotchas (from Resources page)
- Force RTSP over TCP — UDP fails across NAT/firewall. `OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"`,
  gstreamer `rtspsrc protocols=tcp latency=200`, ffmpeg `-rtsp_transport tcp`, DeepStream `select-rtp-protocol=4`.
- Use PTS, never wall-clock, for timing.
- Auto-reconnect with exponential backoff.
- Mixed H.264/H.265 and variable resolutions.
- Feeds loop → tolerate scene discontinuities and inter-frame gaps.
- Read per-camera properties from /api/ingest before processing.

## Phases & prizes — ₹51,00,000
Phase 1 Sandbox (₹18L): test feeds, two categories, top 3 each advance (6 finalists).
  Cat 1 (students/small-med startups): 4L / 2L / 1L   Cat 2 (large startups/companies): 5L / 3L / 2L
  Consolation ₹25,000 × 4 = ₹1L
Phase 2 Grand Finale (₹31L): real feeds at scale, judged by Gujarat Police leadership + technical jury.
  1st ₹16L · 2nd ₹8L · 3rd ₹7L · ₹1.5L consolation (other 3 finalists) · ₹50,000 Special Jury Award

## Timeline
Registration opens 2026-08-04 · closes 2026-09-07 · shortlist 2026-09-07 evening ·
event 2026-09-10 to 09-11 at i-Hub Gujarat, Gandhinagar · results 2026-09-11.

## Eligibility
Cat 1: students, graduates, PG, doctoral, academic/research teams, DPIIT-recognised startups.
Cat 2: companies, industry partners, system integrators, solution providers, LLPs, partnerships, enterprises.
Individual or team. Team size not stated on site. IP ownership not addressed on site.

## Contact
SCRB, next to Police Bhawan, Sector 18, Gandhinagar 382009 · +91 95370 89982 ·
sentinel.hackathon@gujarat.gov.in · https://gujhome.gujarat.gov.in
