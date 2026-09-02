# Submission — SENTINEL 2026, due **7 Sep 2026**, not in the evening

The portal closes on the 7th. Registration closing and the upload working are two different
things, and only one of them is under our control. **Target: everything uploaded by 14:00 IST on
6 Sep**, so the 7th is a buffer day and not the plan.

## What the portal wants

| # | Deliverable | Format | Owner | State |
|---|---|---|---|---|
| 1 | Presentation | PPT **and** PDF | I (deck), all (review) | outline in `docs/deck-outline.md` |
| 2 | High-level design document | PDF | D (`D8`) | |
| 3 | Demo video, 2–3 min | MP4, link | J1 | |
| 4 | Hosted URL + test credentials | URL + 3 logins | G + D | |
| 5 | Source repository | link | all | this repo |

Mock-ups and concept videos are **explicitly rejected** by the portal. Every frame of the video
and every screenshot in the deck must be the running system on our own feed.

## The gate — nothing is submitted until these three pass, on the day

```bash
PRAHARI_INTEGRATION=1 pytest tests/test_integration.py -v     # J1, every leg
python scripts/accuracy_report.py --golden fixtures/golden/   # I7, regenerates the numbers
make check                                                    # unit suites + the RBAC scope test
```

Then, and only then, the deck's `‹markers›` get replaced with that run's output
(`docs/deck-outline.md` lists which marker comes from which command).

## Demo video — 2–3 minutes, recorded, not narrated live

Recorded on our own running system, screen capture, one take per section, cut together. The
sequence is the first half of `docs/demo-script.md`:

1. **0:00–0:20** onboarding: a camera added in the admin page, appearing on the map with health.
2. **0:20–0:55** detection: live sightings on the map, one opened — crop, class, band, PTS.
3. **0:55–1:30** watchlist match: the plate added to the watchlist, the alert firing, banded.
4. **1:30–2:15** route: the plate typed in, hops drawn across cameras, one flagged IMPLAUSIBLE.
5. **2:15–2:40** audit: the export that was just made, in the audit log, and `audit/verify` ok.

No slides in the video. No voice-over claims that the screen does not show. Keep the terminal
with `/metrics` visible in one shot — it is the cheapest proof that this is a running system
and not a click-through.

Record at 1920×1080, 30 fps, and check it plays in a browser on a phone before uploading.

## Hosted URL and test credentials

Three logins, one per role we claim in [C10], because a jury that can only log in as an admin
cannot check that scope is enforced:

| role | username | what they should see |
|---|---|---|
| Investigator (Police) | `demo.investigator` | everything, statewide route, export |
| Operator (dept) | `demo.operator` | own department only, no export |
| Dept Admin | `demo.admin` | own department, users in dept, audit |

Credentials go in the submission form, never in this repo. Rotate them after the event.

## Repository hygiene before the link is submitted

- [ ] `.env` is not in git and never was (`git log --all --full-history -- .env` is empty).
- [ ] No weights, no video, no crops (`.gitignore` covers `models/`, `fixtures/clips/`).
- [ ] `git ls-files | xargs ls -l | sort -k5 -n | tail` shows nothing over 10 MB.
- [ ] `README`/`AGENTS.md` say how to run it from a clean clone: `make up`, `make seed`,
      `make check`, then the three service commands.
- [ ] Licences of every model listed (`docs/model-card.md`) — the contest is open source only,
      and the YOLOv8 AGPL question is stated openly rather than hidden.

## Timeline

| when | what |
|---|---|
| **5 Sep** | feature freeze. After this, only fixes that make the gate green. |
| 5 Sep | chaos drills, all four, timed (`docs/demo-script.md`) |
| 5–6 Sep | two timed rehearsals of the 8-minute script |
| 6 Sep AM | final accuracy report; deck markers replaced with real numbers; deck → PDF |
| 6 Sep PM | record the demo video, cut, check playback on a phone |
| **6 Sep 14:00** | **submit everything** |
| 7 Sep | buffer. Portal closes. |
| 10–11 Sep | live event, i-Hub Gandhinagar |

## Things that have sunk submissions before, in order of likelihood

1. **Uploading on the last evening.** The portal is slow when everyone does this. Hence the 6th.
2. **A video that shows a mock-up.** Explicitly rejected. Record the real thing, even if uglier.
3. **A number in the deck that nobody can reproduce.** Every figure traces to a command
   (`docs/deck-outline.md`), or it comes off the slide.
4. **Credentials that do not work from outside our network.** Test the hosted URL and all three
   logins from a phone on mobile data, not from the dev laptop.
5. **A PDF export that rasterises the architecture diagram into mush.** Export at print
   resolution and open the PDF on someone else's machine.
