# Video runbook — screen by screen

Read this top to bottom while recording. Left column is what you do, right column is what you
say. Target **2:45**; the portal's cap is 3:00 and an overrun is a disqualification risk.

**Record each screen as its own take.** Cut them together afterwards. Do not attempt one pass.

---

## Before you press record

```bash
cd C:/Users/Priyanshu/OneDrive/Desktop/All_projects/hackathon/cctv
source run_demo_env.sh

python scripts/run_stack.py restart        # API, console, persister, matcher
python scripts/fake_sightings.py --rate 5 --duration 3600 &    # demo traffic
curl -s -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:5173/api/wall/start
```

Then wait **three minutes** before recording. The wall rotates through cameras and you want
several tiles carrying pictures before the camera rolls.

Sanity check, all four must pass:

```bash
python scripts/verify_stack.py             # 35/35
python services/worker/selftest.py         # SELFTEST OK, under 1s
```

**Screen hygiene** — each of these has ruined a take:

- 1920×1080, browser at 100 % zoom, bookmarks bar hidden
- notifications off (Windows Focus Assist on), second monitor disconnected
- log in **before** recording starts, so no password is ever on screen
- move the cursor slowly; the judge is reading an unfamiliar UI at 1× speed

---

## What is on screen is real

Say this to yourself before each take, because it is the thing that makes this submission
different: **every box, every timestamp, every plate in this video is output the system produced
on the frame you are looking at.** The synthetic sighting generator populates the map with
traffic, and where that is on screen you say so. Nothing is drawn to look like a detection that
was not one.

---

# The takes

## Take 1 — Map · 0:00–0:15 *(15 s)*

| Do | Say |
|---|---|
| Console open on **Map**. Slowly pan across Gujarat. Click one pin so the camera panel opens. | "Prahari. Twenty-six government departments, twenty-six separate CCTV systems, no shared search. We don't replace any of them. We add one thing — a sighting: two hundred bytes describing one vehicle at one camera. The video stays where it is. The sighting is what crosses the boundary." |

Do not read the architecture aloud. The map is the argument.

---

## Take 2 — Wall with detection boxes · 0:15–0:50 *(35 s)* — **do not cut**

| Do | Say |
|---|---|
| Click **Wall**. Let it fill. Boxes are drawn on the live grid frames — amber boxes, vehicle class, confidence, and a count along the bottom. | "This is live footage from the Gujarat grid, and these boxes are our detector running on it right now. YOLO finds each vehicle, ByteTrack keeps its identity across frames, and every timestamp comes from the video frame's own presentation time — never the server clock. That is what lets two different cameras be compared later." |
| Click one tile to open it larger. Point at the caption under a box. | "And here is the part I want you to see. Under each vehicle it says what the plate would be worth in pixels. On this camera: not resolvable. The vehicles are fifty-five pixels wide, which makes the plate characters about two pixels tall. Nothing reads that — so we say so, instead of printing four confident characters of noise." |

**This is the strongest 35 seconds in the video.** It shows the system working *and* shows
judgement. Do not cut it for time.

---

## Take 3 — Reading a plate, our own feed · 0:50–1:20 *(30 s)*

| Do | Say |
|---|---|
| Terminal, full screen, large font. Run `python services/worker/selftest.py`. Let the output scroll to `SELFTEST OK`. | "When the pixels are there, the same pipeline reads the plate. This is our own camera feed: decode, detect, track, four OCR engines voting, published — end to end in under a second, inside a three-second budget. Plate read back exactly." |
| Point at the `plate_band` field in the printed row. | "And it publishes a confidence band. Four readers vote; if they disagree, it refuses to name the plate rather than guessing. On our controlled set that is ninety-five per cent read exactly, with zero confidently-wrong answers." |

---

## Take 4 — Watchlist and the alert · 1:20–1:50 *(30 s)* — **do not cut**

| Do | Say |
|---|---|
| **Watch** → add a plate you can see in the sightings list. Category *stolen vehicle*, severity *HIGH*. Save. | "An officer adds a plate to the watchlist. Stolen vehicle, high severity." |
| Go to **Alerts** or **Map**. **Do not refresh.** Wait for the badge to increment and the alert to appear. | "And the alert arrives on its own. No polling — one socket, and the server decides what this operator is allowed to see before the frame is ever on the wire. The matcher also collapses the characters cameras confuse — zero against O, eight against B — so one misread character doesn't lose the vehicle." |
| Open the alert, click **Acknowledge**. | "Acknowledged, by a named officer, and that transition is recorded." |

---

## Take 5 — Route history · 1:50–2:25 *(35 s)* — **the judged test case**

| Do | Say |
|---|---|
| **Trace** → type `GJ01AB1234` → the route draws. | "The test case the brief asks for: give it a registration number, get the route. Ordered hops, each with the camera, the coordinates and the timestamp, snapped to roads." |
| Point at the hop flagged **IMPLAUSIBLE**. | "This hop is flagged implausible — two hundred kilometres in a minute is a misread, not a journey. We show it flagged rather than hiding it, because the officer decides what to do with it, not the software." |
| Click **Export → PDF**. Then **Admin → Audit**. Your export is the top row. Click **Verify** → `ok: true`. | "Export it — and the export is already in the audit log. Every row is hash-chained to the one before, so if somebody edits a row directly in the database, this button says so." |

---

## Take 6 — The security test · 2:25–2:40 *(15 s)*

| Do | Say |
|---|---|
| Log out. Log in as **console-audit**. Click **Map** — refused. Click **Admin → Audit** — works. | "One last thing. This is the System Administrator — the most privileged account in the system. It can configure everything and it cannot watch anybody. Administering a surveillance system and using one are different jobs, and the account that can do both is the one an insider abuses." |

---

## Take 7 — Close · 2:40–2:45 *(5 s)*

| Do | Say |
|---|---|
| Back to the map, alert visible. Hold two seconds. | "Open source end to end. Running on one machine today, designed for eighty thousand cameras. Prahari." |

Do not fade to a logo — there isn't one, and an invented one looks like a mock-up.

---

## Before upload

- [ ] Runtime **2:30–3:00**. Measure it.
- [ ] No credential, token, IP or real personal plate visible — scrub at 0.5× speed
- [ ] 1080p, H.264, under 500 MB
- [ ] Uploaded **unlisted to YouTube** *and* mirrored to Drive with viewer access
- [ ] Open the link in a private window before submitting it

## If a take goes wrong

Stop and fix it. A take with a stack trace, a grey tile or a spinner is worth less than a shorter
take without one. `docs/operations.md` has the failure playbook.
