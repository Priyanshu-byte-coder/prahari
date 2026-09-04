# Submission — SENTINEL 2026

Portal closes **7 Sep 2026**. Registration closing and the upload working are two different
things, and only one of them is under our control. **Target: everything uploaded by 14:00 IST on
6 Sep**, so the 7th is a buffer day and not the plan.

Event: 10–11 Sep, i-Hub Gujarat, Gandhinagar.

---

## What the portal asks for, and where we are

| # | Deliverable | Format | State |
|---|---|---|---|
| 1 | Solution presentation — model chosen + justification, architecture, AI approach, scalability | PPT **and** PDF | **`docs/deck.html` built, needs export to PDF/PPT** |
| 2 | High-level design document | PDF | **`docs/hld.md` written, needs export to PDF** |
| 3 | Screen-recorded demo on **our own** feed, max 2–3 min | MP4 / link | **script ready (`docs/video-script.md`), not recorded** |
| 4 | Live demo on Government feeds | in person, 10–11 Sep | runs today; see the ANPR caveat below |
| 5 | Test case: registration number → full route history | shown in demo | **working** — `GET /api/route?plate=…`, or Trace in the console |
| — | Hosted URL + test credentials | URL + logins | **not deployed** — currently localhost only |
| — | Source repository | link | this repo, Apache-2.0, README complete |

Mock-ups and concept videos are **explicitly rejected**. Every frame of the video and every
screenshot in the deck must be the running system.

---

## What is left to do

Ordered by what would cost us most if it were missed.

### Blocking — the submission is incomplete without these

1. **Export the deck to PDF and PPT.** `docs/deck.html` is 10 slides and renders; the portal
   wants PPT *and* PDF. Print-to-PDF from the browser covers one; the PPT needs rebuilding in
   Slides/PowerPoint or the portal accepting PDF alone — **check the portal's exact wording**.
2. **Export the HLD to PDF.** `docs/hld.md` → PDF (pandoc, or print the rendered Markdown).
3. **Record the demo video.** `docs/video-script.md` is shot-by-shot with narration and timings,
   targeting 2:45. Needs one person, one screen, about an hour with retakes.
4. **Screenshots for the README and the deck.** Placeholders are marked
   `<!-- SCREENSHOT: … -->` in `README.md`. The console, the map with an alert, the route view.
5. **Decide the hosting story.** Either deploy somewhere reachable with three test logins
   (VIEWER, OPERATOR, INVESTIGATOR + a SYSTEM_ADMIN to show it *cannot* see video), or state in
   the submission that the system is demonstrated live and by video. If deploying: it is four
   processes and a compose file, but budget half a day for TLS, a domain, and locking the demo
   accounts down.

### Should be done

6. **Say the ANPR result plainly in the deck.** We read zero plates across all 30 grid feeds
   (`docs/plate-ocr-grid-report.md`), because the cameras are framed for scene overview and the
   footage is at night. Everything else — tracking, correlation, routes, alerts, RBAC, audit —
   works on those feeds today. Presented as a measurement with the pixel arithmetic behind it
   (`preprocess.feasibility`, `docs/lr-benchmark.md`), this is a strength: it is the difference
   between a team that measured and a team that assumed. Buried, it looks like a gap the judges
   found for us.
7. **Ask the organisers for a plate-capable feed** — an enforcement-framed camera or the
   operators' own RLVD plate snapshots. An afternoon with either produces a real accuracy number
   instead of a synthetic one.
8. **RTSP access** (#56). We are on the downscaled HLS rendition because RTSP answers 401 for our
   IP. Worth one email; it roughly doubles the pixels on a plate.
9. **Rehearse the live demo twice, end to end, on the event laptop** — `docs/demo-script.md`.
   Including the failure drills.

### Optional

10. Grafana dashboards (#24) — Prometheus metrics are already exported.
11. TensorRT engine build (#11) — ONNX export and its parity gate exist.

---

## The gate — run this before anything is uploaded

Nothing is submitted until all four are green, **on the machine that will be demonstrated**:

```bash
pytest tests/ -q                                   # 362 passed, 6 skipped
python services/worker/selftest.py                 # SELFTEST OK, 0.68 s, plate read back
python scripts/run_stack.py start
python scripts/verify_stack.py                     # 35/35 checks
PRAHARI_INTEGRATION=1 pytest tests/test_integration.py -q   # 6 passed
python scripts/accuracy_report.py                  # regenerates docs/accuracy-report.md
```

Last full run: **all green**, 2026-09-04.

Then, and only then, the deck's `‹markers›` get replaced with that run's output —
`docs/deck-outline.md` lists which marker comes from which command. Do not hand-write a number
into the deck; if a number has no command, it does not go in.

---

## Judged on seven things — where we stand

| Criterion | Where we are |
|---|---|
| Gov-feed test case success | Route history works end to end. ANPR on the grid returns no plate, honestly and by design (`feasibility` refuses rather than guesses) |
| Presentation clarity | Deck built; needs the PDF/PPT export and the honest ANPR slide |
| Technical / architecture soundness | Hybrid M1+M2+M3, sighting-as-atom, full HLD, contracts frozen |
| Platform maturity | 362 tests, CI on every push, 35-check stack verification, audit chain, failure playbook |
| Analytics output quality | PTS timestamps throughout, banded confidence, zero confidently-wrong reads, per-reader accuracy published |
| Scalability & PoC readiness | Three scale tiers costed in the HLD; runs on one node today |
| Submission completeness | The five items above |

Bonus criteria we can claim: hybrid architecture, multi-camera tracking, analytics beyond ANPR
(crowd, stopped vehicle, wrong-way, re-identification), edge/bandwidth thinking (sightings cross
the boundary, not video), cybersecurity and auditability (hash-chained log, RLS, grants), and
operational dashboards (the console's admin view).
