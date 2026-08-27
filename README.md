# Prahari — Unified CCTV Integration & Video Intelligence Platform

> प्रहरी · *sentinel, watchman*

Submission for the **Gujarat Police Innovation Challenge 2026** (Sentinel CCTV Integration Hackathon),
Home Department, Government of Gujarat — Category 1.

Prahari unifies heterogeneous departmental CCTV systems into a single registry, viewing
surface and analytics plane: it onboards cameras from any protocol, runs AI video analytics
at the edge, correlates detections against watchlist databases, and reconstructs the
cross-camera movement of a vehicle of interest — while the video itself stays where it is.

---

## Architecture

**Hybrid: Model 1 (mandatory registry & GIS) + Model 3 (federation middleware) + a selective
Model 4 analytics plane, with edge-first inference.**

The defence in one line: *video is heavy, metadata is light — we move compute to the edge and
metadata to the centre.* A fully centralised VMS for 80,000 cameras implies ~160 Gbps of
sustained backhaul and ~26 PB of hot storage at 15-day retention. Prahari delivers the same
unified operational picture without either.

```
L0  SOURCES   dept cameras / NVR / VMS · analog (encoder) · IP · private (permitted)
              RTSP · ONVIF · vendor SDK · HLS
L1  EDGE      stream manager (PTS-driven, auto-reconnect) · NVDEC · vehicle+plate detection
              · OCR · Re-ID embedding   -> emits events only (~2 KB), not video
L2  BUS       Redis Streams / Kafka: detections · health · alerts
L3  CORE      registry+GIS · correlation engine · track assembler · alert engine
              · federation adapters · PostgreSQL+PostGIS · TimescaleDB · object store
L4  APPS      GIS map · video wall · vehicle search & route replay · alert console
              · watchlist admin · camera health NOC · audit log
```

---

## Grid reality check

Measured against the live Sentinel sandbox (`live.corp8.cloud`, 30 cameras), not assumed:

| Finding | Measured |
|---|---|
| Cameras reachable | 22 / 30 |
| Transport | RTSP 8554 filtered on our network → **HLS over 443** |
| Codecs | h264 × 20, hevc × 2 |
| Resolutions | 1920x1080, 1280x960, 1280x720, 960x576 |
| Frame rates | 9.92 – 29.67 fps, non-uniform |
| Catalogue metadata missing | 19 / 30 cameras report `0x0` / empty codec |
| Catalogue fps disagrees with delivery | 4 cameras (cam 13 claims 12.5, delivers 10.0) |
| Auth-gated | cam 15, 26 → HTTP 401 |
| Server-side failures | cam 17, 18, 21, 22 → HTTP 5XX |

Regenerate any time:

```bash
python scripts/survey_grid.py --transport hls --workers 8
```

The catalogue is the contract, the URL pattern is not — camera ids change, so the platform
polls `/api/ingest`, diffs it, and auto-onboards.

---

## Repository layout

```
infra/       MediaMTX + local clone of the Sentinel grid (same ports, same behaviour)
simgrid/     synthetic camera generator with known ground truth for scoring ANPR
scripts/     grid probe + survey tooling
services/    api (FastAPI) · worker (stream + inference)
web/         operator console: map, video wall, search, alerts
docs/        HLD, presentation, evaluation artifacts
data/        catalogue snapshots, survey results, ground truth
```

## Getting started

```bash
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
copy .env.example .env
python scripts/survey_grid.py --transport hls
```

## Licence & credentials

No credentials are committed. `.env` is gitignored. Sandbox access is issued per registered
team by the organisers.
