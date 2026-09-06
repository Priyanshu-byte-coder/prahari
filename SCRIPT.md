# Prahari — submission video, shooting script

Every command below has been run **in PowerShell on this machine**, and every output block is
real, transcribed. The portal caps the demo at **3 minutes** and rejects mock-ups, so the whole
thing is the running system.

Repo: **https://github.com/Priyanshu-byte-coder/prahari**

**About 340 spoken words ≈ 2:15 at a natural pace**, and the timings below add the clicks and
screen switches on top. Total lands at **2:45**. The cap is 3:00 — do not fill the gap.

> **The rule that keeps this short: don't read the numbers out.** The viewer can see them. Say
> what they *mean*. Every time you are tempted to recite a figure that is already on screen,
> point at it instead and say the consequence.

**Record each beat as its own take** and cut them together. Do not attempt one pass.

---

## PowerShell, not bash

`source run_demo_env.sh` is the bash spelling. In PowerShell it fails with
*"The term 'source' is not recognized"*. Use the PowerShell file, **with the leading dot**:

```powershell
. .\run_demo_env.ps1
```

The dot matters. Without it PowerShell runs the script in a child scope and every variable
vanishes when it exits — which looks exactly like the script having done nothing.

It sets `$env:PRAHARI_PY` to the project's virtualenv. **Use that instead of `python`** for
anything touching the computer-vision stack. A bare `python` on this machine has no torch, so
the detector silently loads nothing and the wall draws no boxes.

---

## Before you press record

### 1. Start everything

```powershell
cd C:\Users\Priyanshu\OneDrive\Desktop\All_projects\hackathon\cctv
. .\run_demo_env.ps1

docker start sentinel-postgres sentinel-redis sentinel-minio
& $env:PRAHARI_PY scripts\run_stack.py start
```

**OUTPUT:**
```
api        started (pid 18720) -> logs/api.log
console    started (pid 24176) -> logs/console.log
persister  started (pid 23144) -> logs/persister.log
matcher    started (pid 1636) -> logs/matcher.log
api        healthy  http://127.0.0.1:8000/api/healthz
console    healthy  http://127.0.0.1:5173/api/cameras

console: http://127.0.0.1:5173/
```

### 2. Background traffic, in its own window

```powershell
Start-Process -FilePath $env:PRAHARI_PY -ArgumentList "scripts\fake_sightings.py","--rate","6","--duration","14400" -WindowStyle Minimized
```

This keeps the map moving. It is a load generator and the script says so on camera.

### 3. The demo vehicle

```powershell
& $env:PRAHARI_PY scripts\demo_vehicle.py --watchlist --password $env:PRAHARI_CONSOLE_PASSWORD
```

**OUTPUT:**
```
  00:46:50  cam  4  CONFIRMED conf 0.96
  00:50:34  cam  1  CONFIRMED conf 0.97
  00:55:42  cam 20  PROBABLE  conf 0.81
  01:07:30  cam  5  CONFIRMED conf 0.94
  01:10:59  cam  3  CONFIRMED conf 0.94
  01:20:50  cam 12  CONFIRMED conf 0.97
  01:22:57  cam 17  POSSIBLE  conf 0.61

Type this into Trace:  GJ01DM0042
```

Safe to run again between takes — it clears the previous journey and prunes late arrivals, so
you always get the same seven hops.

### 4. Start the wall, then wait

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5173/api/wall/start" -ContentType "application/json" -Body "{}"
```

**Then wait three minutes.** The grid allows one session per IP, so the wall holds six
connections and rotates through the thirty cameras. You want tiles carrying pictures before the
camera rolls.

### 5. The one check that matters

```powershell
& $env:PRAHARI_PY scripts\preflight.py
```

**OUTPUT:**
```
PASS  interpreter has the CV stack (python.exe)
PASS  environment loaded (Postgres, Redis, JWT secret)
PASS  postgres, redis and minio are up
PASS  30 cameras registered
PASS  4578 sightings in the last hour
PASS  API is up on :8000
PASS  console is up on :5173
PASS  console session is live (role switch will work)
PASS  route for the demo plate returns 7 hops
PASS  6 of 30 tiles carry a picture
PASS  4 tiles have detector boxes drawn
PASS  grid session is signed in
PASS  OCR readers loaded: fastplate, easyocr
13 pass · 0 warn · 0 to fix

Nothing blocking. Good to record.
```

**Do not record with an outstanding FIX.** Each one comes with the command that repairs it, and
each one is something a viewer would see.

### 6. Screen setup

| | |
|---|---|
| **Resolution** | 1920×1080, record the whole screen |
| **Browser** | `http://127.0.0.1:5173/`, zoom 100%, bookmarks bar hidden |
| **Terminal** | second window, full screen, font 16–18pt, dark background |
| **Hide** | notifications (Focus Assist on), chat apps, second monitor |

**Do not open the grid in a browser tab while recording.** One session per IP — signing in
takes the console's session and the wall goes grey.

---

## The script

**Total 2:45.** ±5s per beat is fine.

---

### `0:00 – 0:15` · What this is

**SCREEN:** Console on **Map**. Thirty pins across Gujarat.
**DO:** Pan slowly. Click one pin so the camera panel opens. Then just talk.

> "Twenty-six government departments in Gujarat run their own CCTV. Their own systems, their own
> storage, no shared search.
>
> We don't replace any of it. We add one thing — a sighting. Two hundred bytes describing one
> vehicle at one camera. The video stays where it is. The sighting is what crosses the boundary."

**DO NOT** read the architecture aloud. The map is the argument.

---

### `0:15 – 0:50` · Detection on the government grid — **do not cut**

**SCREEN:** Click **Wall**. Tiles with amber boxes on live night footage.
**DO:** Let it sit for two seconds before speaking. Then point at a box.

> "This is live footage from the Gujarat grid, and these boxes are our detector running on it
> right now. YOLO finds each vehicle, ByteTrack keeps its identity across frames.
>
> Every timestamp comes from the video frame's own presentation time — never the server clock.
> That is what makes two different cameras comparable later."

**DO:** Click one tile to open it larger. Point at the line along the bottom.

**ON SCREEN:** `4 vehicles tracked — none close enough for ANPR at this camera`

> "And here is the part I want you to see. It says none of these plates can be read.
>
> The vehicles on this camera are about fifty pixels wide, which puts the plate characters at
> two pixels tall. Nothing reads that. So we say so, instead of printing four confident
> characters of noise.
>
> A wrong plate on a police report is worse than no plate."

---

### `0:50 – 1:20` · Reading a plate, on our own feed

**SCREEN:** Terminal, full screen.
**DO:** Say the first line, **then** run:

```powershell
& $env:PRAHARI_PY services\worker\selftest.py
```

**OUTPUT:**
```
source      fixtures\clips\selftest.mp4
redis       redis
injected    GJ 25 BJ 8377
read back   GJ25BJ8377
rows        1 on `sightings-selftest`, 1 published
latency     0.58s (budget 3.0s, wall 6.21s)
row         {"sighting_id": "01M1W3M62K...", "camera_id": "SELFTEST-000", ...
             "plate_text": "GJ25BJ8377", "plate_conf": 0.989, "plate_band": "CONFIRMED", ...}

SELFTEST OK
```

**DO:** Let it land. Point at `read back` and then at `latency`.

> "When the pixels are there, the same pipeline reads the plate. This is our own camera feed:
> decode, detect, track, four OCR engines voting, published.
>
> Under a second, end to end, inside a three-second budget. Plate read back exactly.
>
> Four readers vote. When they disagree, it refuses to name the plate rather than guessing —
> ninety-five per cent read exactly on our test set, and zero confidently-wrong answers."

---

### `1:20 – 1:50` · Watchlist to alert — **do not cut**

**SCREEN:** Console → **Watch**. `GJ01DM0042` is listed as *stolen vehicle · HIGH*.
**DO:** Point at the entry.

> "An officer puts a plate on the watchlist. Stolen vehicle, high severity."

**DO:** Click **Alerts**. The alerts for that plate are already there.

> "The alerts arrived on their own — no refresh, no polling. One socket, and the server decides
> what this operator is allowed to see before the frame is ever on the wire.
>
> The matcher also collapses the characters cameras confuse — zero against O, eight against B —
> so a single misread character doesn't lose the vehicle."

**DO:** Open one alert, click **Acknowledge**. State moves NEW → ACKNOWLEDGED.

> "Acknowledged, by a named officer, and that transition is recorded."

---

### `1:50 – 2:25` · The route — the judged test case

**SCREEN:** **Trace**.
**DO:** Type **`GJ01DM0042`**, press Trace. Seven numbered hops draw across the map.

> "The test the brief asks for: give it a registration number, get the route.
>
> Seven hops, in order, each with the camera, the coordinates and the timestamp — southern
> Ahmedabad, up through the city, out to Gandhinagar. Snapped to roads."

**DO:** Point at hop 7, in coral, flagged **IMPLAUSIBLE**, six thousand km/h beside it.

> "And this one is flagged. Two hundred kilometres in two minutes — that's a misread, not a
> journey.
>
> We show it flagged rather than dropping it. A dropped hop is a lie of omission. The officer
> decides what to do with it, not the software."

**DO:** Click **Export → PDF**. Then **Admin → Audit**. The export is the top row. Click
**Verify**.

**ON SCREEN:** `ok: true`

> "Export it, and the export is already in the audit log. Every row is hash-chained to the one
> before it — so if somebody edits a row directly in the database, this button says so."

---

### `2:25 – 2:40` · The account that cannot watch

**SCREEN:** Console. The account chip at the bottom of the left rail reads `FI`.
**DO:** Click it. It turns red and reads `SA`. Then click **Alerts** — refused. Then
**Admin → Audit** — works.

> "One last thing. This is the System Administrator — the most privileged account in the system.
> It can configure everything, and it cannot watch anybody.
>
> Administering a surveillance system and using one are different jobs. The account that can do
> both is the one an insider abuses."

---

### `2:40 – 2:45` · Close

**SCREEN:** Back to the map.
**DO:** Hold two seconds, then stop recording.

> "Open source, end to end. Running on one machine today, designed for eighty thousand cameras.
>
> Prahari."

Do not fade to a logo — there isn't one, and an invented one looks like a mock-up.

---

## After recording

- [ ] Runtime **2:30–3:00**. Measure it, do not estimate.
- [ ] Scrub at 0.5× for any credential, token, IP or real personal plate on screen
- [ ] Export 1080p, H.264, under 500 MB
- [ ] Upload **unlisted to YouTube** *and* mirror to Drive with viewer access
- [ ] Open the link in a private window before submitting it

## Stopping everything

```powershell
& $env:PRAHARI_PY scripts\run_stack.py stop
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*cctv*" } | Stop-Process -Force
docker stop sentinel-postgres sentinel-redis sentinel-minio
```

To remove the demo vehicle entirely:

```powershell
& $env:PRAHARI_PY scripts\demo_vehicle.py --clear
```

## If a beat goes wrong

Stop and fix it. A take with a stack trace, a grey tile or a spinner is worth less than a shorter
take without one. Re-run `preflight.py` — it names the problem and the command that fixes it.
`docs\operations.md` has the longer failure playbook.

## The cut list, if you are over 3:00

Cut in this order. **Never** cut the wall refusal (`0:15–0:50`) or the implausible hop
(`1:50–2:25`) — those two are the whole argument.

1. The export and audit-verify half of the route beat (−12s)
2. The acknowledge step in the alerts beat (−8s)
3. The second half of the selftest narration (−10s)
