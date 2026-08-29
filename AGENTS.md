# AGENTS.md — Project Memory (auto-maintained)
Last updated: 2026-08-28 | Sessions logged: 1

## Identity
Entry for the Gujarat Police "Sentinel" CCTV Integration Hackathon 2026 (SCRB, Gandhinagar).
Build a vendor-neutral platform that unifies heterogeneous Government CCTV, runs ANPR/AI analytics,
correlates against watchlists, and traces vehicles across cameras on a GIS map.

## Stack & Commands
Nothing scaffolded yet. Target stack (open-source mandated): Python (ingest/AI), FastAPI or Node,
React + Leaflet/OpenLayers (UI), PostgreSQL + PostGIS, FFmpeg/GStreamer/OpenCV, RTSP/WHEP/HLS.

## Current State & Focus
- Requirements scraped from sentinel.gujarat.gov.in → SENTINEL_HACKATHON.md (full spec, verbatim facts).
- No code written yet. Next: decide architecture model (M1–M4/hybrid), then RTSP ingest spike.
- Hard deadline: submission 2026-09-07; event 2026-09-10/11 at i-Hub Gujarat.

## Architecture
TBD. Likely: RTSP feeds -> ingest workers (TCP-forced, PTS-based) -> ANPR inference -> events on a
queue -> PostGIS event store -> watchlist match -> alert + React/Leaflet map + track replay.

## File Map
`SENTINEL_HACKATHON.md` — full scraped challenge spec: problem, expected solution, deliverables,
evaluation, prizes, stream endpoints and gotchas. Read this before asking about requirements.

## Conventions
Open-source only (contest rule). No vendor lock-in. Working software only — mock-ups are disqualified.

## Dependencies & Gotchas
- RTSP must be forced over TCP (UDP dies on NAT/firewall); use PTS not wall-clock; reconnect with
  exponential backoff; feeds loop, so expect scene discontinuities; mixed H.264/H.265.
- Camera catalogue at `GET /api/ingest` on the grid host — read per-camera props before decoding.

## Decisions Log
2026-08-28 — scrape site into SENTINEL_HACKATHON.md instead of re-fetching pages — deadline is tight, site is slow.

## Changelog
2026-08-28 | scrape sentinel.gujarat.gov.in, extract requirements | SENTINEL_HACKATHON.md, AGENTS.md | single spec file as source of truth

## Archived Summary
(none)
