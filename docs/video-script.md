# Submission video — 2:45, shot by shot

The portal's rule, in its own words: a **screen-recorded demo, maximum 2–3 minutes, on your own
CCTV feed**, showing *onboarding → AI detection → watchlist match → alert*. Mock-ups and concept
videos are **explicitly rejected**. Every frame below is the running system.

**Target runtime 2:45.** Not 2:59 — an overrun is a disqualification risk and a rushed final
section is the one the judge remembers. If a take runs long, cut from §5, never from §3 or §4.

> **"Own CCTV feed" means ours, not the grid's.** This video is recorded against
> `fixtures/clips/selftest.mp4` replayed as a camera plus our own generator traffic. The
> Government-grid run is the *live* demo (deliverable 4) and a separate recording — do not mix
> them, and do not claim grid footage here.

---

## Before you hit record

```bash
# 1. clean slate, so the demo is not competing with old rows
make up && make seed
python services/api/auth.py bootstrap --username admin --role SYSTEM_ADMIN
python services/api/auth.py bootstrap --username field  --role INVESTIGATOR

# 2. the gate — if either is red, the fix is the work, not the recording
pytest tests/ -q                                    # expect: 348 passed
python services/worker/selftest.py                  # expect: SELFTEST OK, under budget

# 3. the four processes, one per shell
python -m uvicorn --factory services.api.main:factory --host 127.0.0.1 --port 8000
python scripts/console_serve.py --port 5173
python services/api/persister.py --duration 3600
python services/api/matcher.py   --duration 3600
```

Recording hygiene, each of which has ruined a take before:

- **1920×1080, 30 fps, browser at 100% zoom.** Console text is small at 90%.
- **Hide bookmarks, notifications, and any second monitor.** A Slack toast on a police
  submission video is not recoverable in the edit.
- **No credentials on screen.** Log in before recording starts, or blur the field.
- **Cursor visible, movements slow.** The judge is reading an unfamiliar UI at 1× speed.
- Record **one take per section** and cut them together. Do not attempt a single pass.

---

## The script

Timings are cumulative. Narration is what you say; **Action** is what the screen shows.

### §1 — What this is · 0:00–0:15 *(15 s)*

**Action.** The console's live map, 30 cameras across Gujarat, alert badge visible in the rail.

> "Prahari. Twenty-six departments, twenty-six CCTV systems, no shared search. We don't replace
> any of them — we add one thing: a sighting. Two hundred bytes describing one vehicle at one
> camera. Video stays where it is; sightings are what cross the boundary."

*Do not read the architecture aloud.* The map is the argument.

### §2 — Onboarding a camera · 0:15–0:40 *(25 s)*

**Action.** Admin → the camera list with driver and transport per camera. Add one camera; it
appears on the map with health, then the video wall tile for it comes up live.

> "Onboarding is a registry entry, not an integration project. Endpoint, department, coordinates.
> The gateway probes the transport itself — RTSP over TCP, HLS as fallback — and reports health per
> camera. Nothing was installed at the camera end."

**Cut point.** If the wall tile is slow, cut straight from "add" to the tile already live.

### §3 — Detection, on our own feed · 0:40–1:20 *(40 s)* — **do not cut this**

**Action.** Split view, or cut between: the wall tile playing our clip, and the map's sighting
list filling. Open one sighting: crop, vehicle class, plate, confidence band, **PTS timestamp**.

> "Detection runs on our own camera feed. YOLOv8 finds the vehicle, ByteTrack keeps its identity
> across frames, and the plate is read by three different OCR engines that vote — two scene-text
> models and one trained on plates. Every timestamp comes from the frame's presentation time, never
> the wall clock, because that is what makes two cameras comparable later."

Then, on screen, the honest bit — **this is the moment that separates this entry**:

**Action.** Open a wide-area camera whose plate is not resolvable. The console says so.

> "And here it refuses. This camera's vehicles are fifty-five pixels wide — the plate glyphs are
> two pixels. Nothing reads that, so we say 'not resolvable at this camera' instead of guessing.
> A wrong plate on a police report is worse than no plate."

### §4 — Watchlist match and alert · 1:20–2:00 *(40 s)* — **do not cut this**

**Action.** Watchlist → add the plate from §3 with a category and severity. Then, **without
touching the page**, the alert arrives: badge increments, the alert appears in the list, the
camera pulses on the map.

> "Add that plate to the watchlist. The matcher is already comparing every sighting against it —
> collapsing the characters that cameras confuse, zero against O, eight against B — so a single
> misread doesn't lose the vehicle. And the alert pushes itself. No polling: one WebSocket, and the
> server decides what this operator is allowed to see before the frame is on the wire."

**Action.** Open the alert, acknowledge it. State moves NEW → ACKNOWLEDGED with the operator's name.

> "Acknowledged, by a named officer, with the transition recorded."

### §5 — Route history, the judged test case · 2:00–2:35 *(35 s)*

**Action.** Trace → type the plate → the route draws across cameras in order, hops numbered,
timestamps on each, one hop flagged.

> "The test case: given a registration number, produce the route. Ordered hops, every one with the
> camera, the coordinates and the timestamp — snapped to roads. This hop is flagged implausible:
> two hundred kilometres in a minute is a misread, not a journey. We show it flagged rather than
> hiding it, because the officer decides, not us."

**Action.** Export → PDF. Then Admin → Audit → the export is already the top row → click Verify →
`ok: true`.

> "Export it, and the export itself is in the audit log — hash-chained, so a row edited in the
> database breaks the chain and this button says so."

### §6 — Close · 2:35–2:45 *(10 s)*

**Action.** Back to the map, alert visible.

> "Open source end to end, running on one machine today, designed to scale to eighty thousand
> cameras. Prahari."

Hold the last frame two seconds before cutting. Do not fade to a logo — there isn't one, and an
invented one looks like a mock-up.

---

## Checks before upload

- [ ] Runtime between **2:30 and 3:00**. Measure it, do not estimate.
- [ ] No credential, token, IP or personal plate visible in any frame — scrub at 0.5× speed.
- [ ] Audio is a clean voiceover, or none at all with on-screen captions. Never room noise.
- [ ] Exported at 1080p, H.264, under 500 MB.
- [ ] Uploaded **unlisted to YouTube** *and* mirrored to Drive with viewer access — one link
      failing on submission day is the failure mode we can actually prevent.
- [ ] The link opens in a private browsing window. Test it there, not in your logged-in browser.

## If something breaks mid-record

Stop and fix it. A take with a stack trace, a grey wall tile or a spinner is worth less than a
shorter take without one — the brief asks for a working system and the judges have seen every
variety of demo that quietly wasn't. `docs/operations.md` has the failure playbook.
