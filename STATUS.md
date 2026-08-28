# STATUS — task completion at a glance

One table. Update the Status/Owner cells as work lands; don't let this drift
from [CONTEXT.md](CONTEXT.md), which has the full detail behind each row.

| # | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 1 | Camera registry (Model 1) | ✅ Done | — | 30 cameras merged from catalogue+survey+geo, `/api/cameras` |
| 2 | GIS map, drag-to-correct pins | ✅ Done | — | `PUT /api/cameras/{id}/geo` |
| 3 | Catalogue auto-sync/diff | ✅ Done | — | `POST /api/registry/sync` |
| 4 | Stream gateway (cookie session, LL-HLS strip) | ✅ Done | — | Verified live against real grid |
| 5 | Video wall (mixed codec, reconnect, measured fps) | ✅ Done | — | |
| 6 | Live box overlay + fullscreen data panel | ✅ Done | — | Verified in browser |
| 7 | Vehicle detection + tracking (ByteTrack) | ✅ Done | Priyanshu | Counting bug fixed, track-buffer tuned |
| 8 | Unique-vehicle counting (not per-frame) | ✅ Done | — | Bug found + fixed this session |
| 9 | RTSP-on-hotspot test | 🔴 Not done | Priyanshu | Blocks ingestion-path decision |
| 10 | Multi-camera concurrent workers | 🔴 Not done | Priyanshu | Currently one process per camera, started by hand |
| 11 | Postgres/PostGIS/Timescale migration | 🔴 Not done | Priyanshu | Still JSON-on-disk |
| 12 | Camera health / NOC dashboard | 🔴 Not done | Priyanshu | |
| 13 | Plate detector (real, localized crop) | 🟡 Sourced, not wired in | You | Real MIT model verified; not yet in `plate_reader.py` |
| 14 | Plate OCR producing real reads | 🔴 Not working | You | 0 confirmed reads / ~1,500 attempts across 22 cameras |
| 15 | OCR fragment merging | 🔴 Not done | You | Root cause of #14, identified not fixed |
| 16 | RTO state-code validation | 🔴 Not done | You | Needed to reject false positives like `LQ07209` |
| 17 | Track-level plate vote fusion | ✅ Scaffolding done | You | `PlateReader` class works; nothing real to vote on yet |
| 18 | Fuzzy plate search (`/api/search/plate`) | ✅ Done | You | Levenshtein matcher, verified correct |
| 19 | Confusion-class character repair | 🔴 Not done | You | Blocked on #14 |
| 20 | Watchlist DB + admin UI + CSV import | 🔴 Not started | — | |
| 21 | Fuzzy watchlist matching + confidence bands | 🔴 Not started | — | |
| 22 | Alert engine (WebSocket push, ack/dismiss) | 🔴 Not started | — | |
| 23 | Cross-camera route reconstruction | 🔴 Not started | — | The G3 mandatory-gate feature |
| 24 | Spatio-temporal plausibility filter | 🔴 Not started | — | |
| 25 | Vehicle Re-ID fallback | 🔴 Not started | — | |
| 26 | PDF/CSV route report export | 🔴 Not started | — | Required submission artifact |
| 27 | RBAC + department scoping | 🔴 Not started | — | |
| 28 | Hash-chained audit log | 🔴 Not started | — | |
| 29 | `scripts/preflight.py` (8-point checklist) | 🔴 Not built | — | |
| 30 | Public deployment + test credentials | 🔴 Not started | — | Currently localhost only |
| 31 | Docker Compose one-command bring-up | 🔴 Not started | — | |
| 32 | HLD document | 🔴 Not started | — | |
| 33 | 14-slide PPT | 🔴 Not started | — | |
| 34 | Demo Video A (own footage) | 🔴 Not started | — | |
| 35 | Demo Video B (govt feed + report) | 🔴 Not started | — | |

**Rollup:** 9 done, 2 partial/scaffolded, 24 not started — **9 days to submission (7 Sep)**.
