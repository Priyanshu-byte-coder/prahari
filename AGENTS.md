# AGENTS.md — project spine (stable; changes ~twice a week)

**Read `knowledge_base.md` first, not this file.** This file holds what does not change: identity,
stack, commands, repo layout, conventions. Everything that moves — current state, file map, decisions,
changelog — lives in `knowledge_base.md` and is patched after every task. One fact, one home, no drift.

| Need | File |
|---|---|
| What is true right now, what is done, what broke | `knowledge_base.md` |
| Your ticket, your owner boundaries, the frozen contracts | `TASK.md` (grep, never read whole) |
| How to work, what to read, the update contract | `CLAUDE.md` |
| Deep design detail | `docs/internal/implementation-plan.md` (grep an anchor) |
| What the judges require and score | `docs/brief-sentinel-hackathon.md` |

## Identity

Prahari — entry for the Gujarat Police **Sentinel** CCTV Integration Hackathon 2026 (SCRB, Gandhinagar).
A vendor-neutral platform that unifies heterogeneous government CCTV, runs ANPR, correlates every
sighting against watchlists in real time, traces a vehicle across cameras on a GIS map, and proves who
looked at what. Submission **7 Sep 2026**; live demo at i-Hub Gandhinagar **10–11 Sep 2026**.

Graded test case: a judge types a registration number and gets that vehicle's route across ~30–50
cameras, with timestamps. Everything else is built around making that answer trustworthy.

## Stack & Commands

Open source only (contest rule). Python 3.11 + FastAPI · PyAV/FFmpeg/OpenCV · YOLOv8s + ByteTrack ·
PaddleOCR · Postgres 16 + TimescaleDB + pgvector + pg_trgm · Redis Streams · MinIO · Leaflet ·
MediaMTX (RTSP/WHEP/HLS) · OSRM.

```bash
make up                    # docker compose: postgres+timescale, redis, minio, osrm
make seed                  # schema + load cameras.seed.json + camera_geo.json
make check                 # pytest + the RBAC scope test
python -m services.worker.run          # edge: cameras -> sightings on Redis
uvicorn services.api.main:app --reload # core: REST + /ws
python -m http.server 5173 -d web      # console
python scripts/fake_sightings.py       # lane P's independence tool, no cameras needed
python scripts/accuracy_report.py      # the only source of accuracy numbers
```

## Architecture — hybrid of the challenge's four models

```
cameras/VMS -> FEDERATION GATEWAY (drivers: mediamtx | rtsp | onvif | vms-stub)
            -> INFERENCE WORKER (decode 5fps -> YOLOv8s -> ByteTrack -> plate -> OCR vote)
            -> Redis Streams (sightings, camera.health)
            -> CORE API (persister -> Postgres/Timescale; matcher -> alerts; ws-fanout; route; RBAC+audit)
            -> GIS CONSOLE (Leaflet: basemap, assets, events, route) + video wall (HLS + WHEP)
```

Take from each reference model: **M1** the registry and GIS, **M2** the direct-attach stream path and
wall, **M3** the structure — pluggable drivers, event bus, one API, **M4** analytics and cross-department
correlation. Reject M4's central recording of 80k streams; the arithmetic is on the scale slide.
The claim we make and can demonstrate: *"federation middleware with pluggable drivers; three drivers
live, the departmental-VMS driver interface-complete pending vendor credentials."*

The atom is the **sighting row** (~200 bytes, `TASK.md §C1`). Everything downstream reads it. We ship
rows, not video.

## Repo layout and ownership

Each directory has exactly one owner. Do not edit another lane's directory — file a line under
`TASK.md → ## Cross-lane requests` instead.

```
services/worker/  models/  common/plate.py  fixtures/{golden,clips}/    -> lane I  (Neal006)
services/gateway/  web/  infra/  fixtures/api/  data/*.json             -> lane G  (neevmodh)
services/api/  db/  common/ (rest)  scripts/                            -> lane D  (Priyanshu-byte-coder)
tests/test_i_*.py | test_g_*.py | test_d_*.py                           -> by prefix
```

Lane seams are frozen contracts, never people: `camera:transport:<id>` — a URL string in Redis (G→I),
the `sightings` stream (I→D), REST+WS (D→G), and exchange files with one producer each. The worker
imports no gateway code and develops against a local clip. Full boundary table: `TASK.md §2`.

## Conventions

- Working software only — the portal rejects mock-ups and concept videos.
- Timestamps come from frame PTS, never `now()`. `ts_source` is recorded on every row.
- Plate identity is the only identity. Re-ID corroborates, never confirms; the two never share a field.
- Emit nothing rather than a guess: no `plate_text` below a 2/3 vote, no unbanded alert, no untraceable number in the deck.
- Scope is enforced in SQL with RLS as the backstop. Hiding a button is not access control.
- Every export and every live view writes an audit row.
- Commits: `[N3] short imperative message`. Branch `lane/<yourname>`. PR to `main`.
- Never commit `.env`, weights, video, crops, or anything over 10 MB.

## Dependencies & Gotchas (stable ones only — new discoveries go in `knowledge_base.md §3`)

- **RTSP must be forced over TCP.** UDP dies across NAT/firewall.
  `OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"` · ffmpeg `-rtsp_transport tcp` ·
  gstreamer `rtspsrc protocols=tcp latency=200`.
- Port 8554 is blocked on our network, so the gateway probes per camera and degrades to HLS. That
  fallback is a feature, not a workaround — it is the heterogeneity the brief tests.
- Grid feeds loop: expect scene discontinuities and inter-frame gaps. Mixed H.264/H.265, variable resolution.
- Read per-camera properties from `GET http://$GRID_HOST/api/ingest` before decoding anything.
- Reconnect with exponential backoff; a stalled RTSP connection needs a watchdog, it will not error out on its own.
- One ByteTrack instance per camera kept alive across frames — a fresh instance per frame resets track IDs.
- `main` was reset by commit `416ef26 "Restart"`. The previous working tree is at `4d0c945` and on
  `origin/priyanshu/platform`; recover files with `git show <ref>:<path>` instead of rewriting them.

## Protocol (for agents that read only this file)

1. Read `knowledge_base.md` whole, first. Read nothing else for orientation.
2. Grep your ticket out of `TASK.md`; do not read it whole. Never read another lane's source.
3. After **every** completed task, patch `knowledge_base.md`: ticket board cell, new file-map lines,
   a gotcha if you lost time, a decision if you chose, and one changelog line in your lane's block.
   One `Edit` per section, `git pull --rebase` first, never rewrite the file, keep it under 300 lines.
4. Update *this* file only when the spine moves: a new service, a changed command, a new convention.
   Full rules: `CLAUDE.md`.
