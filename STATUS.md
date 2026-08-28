# STATUS — task completion at a glance

One table. Owner cells name a person — never "you" — because both team members
work with their own AI sessions and second person does not resolve the same way
for both readers. Full detail behind each row lives in [CONTEXT.md](CONTEXT.md);
ownership rules live in [ROLES.md](ROLES.md).

**Updated 2026-08-28 · HEAD `411d068` · 10 days to submission (7 Sep)**

Legend: ✅ done and verified · 🟡 partial or scaffolded · 🔴 not started ·
⛔ blocked on another row

| # | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 1 | Camera registry (Model 1) | ✅ Done | Priyanshu | 30 cameras merged from catalogue + survey + geo, `/api/cameras` |
| 2 | GIS map, drag-to-correct pins | ✅ Done | Priyanshu | `PUT /api/cameras/{id}/geo` |
| 3 | Catalogue auto-sync / diff | ✅ Done | Priyanshu | `POST /api/registry/sync` |
| 4 | Stream gateway (cookie session, LL-HLS strip) | ✅ Done | Priyanshu | Verified live against the real grid |
| 5 | Video wall (mixed codec, reconnect, measured fps) | ✅ Done | Priyanshu | |
| 6 | Live box overlay + fullscreen data panel | ✅ Done | Neev | Verified in browser; `cover` vs `contain` box math correct |
| 7 | Vehicle detection + tracking (ByteTrack) | ✅ Done | Priyanshu | Occlusion buffer 30 → 90 frames (D9) |
| 8 | Unique-vehicle counting (not per-frame) | ✅ Done | Priyanshu | Real bug, user-reported, fixed (D10) |
| 9 | **RTSP-on-hotspot test** | 🔴 Not done | **Priyanshu (manual)** | Blocks ingestion-path decision. Cannot be delegated to a coding session. |
| 10 | Multi-camera concurrent workers | 🟡 Built, untested | Priyanshu | `supervisor.py`: process-per-camera, staggered start, restart-with-backoff, health file, `--load-test` |
| 11 | Postgres/PostGIS/Timescale migration | ⛔ **Cut** | — | JSON-on-disk demos identically; stays in the HLD as the production data layer (WORKPLAN.md §4) |
| 12 | Camera health / NOC dashboard | 🔴 Not done | Priyanshu | |
| 13 | Plate detector (real, localised crop) | 🟡 Sourced, not wired | Neev | MIT model verified (D13); not yet in `plate_reader.py` |
| 14 | **Plate OCR producing real reads** | 🔴 Not working | Neev | 0 confirmed reads / ~1,500 attempts across 22 cameras. **Highest-value open task in the project.** |
| 15 | OCR fragment merging | 🔴 Not done | Neev | Root cause of #14; identified, not fixed |
| 16 | RTO state-code validation | 🔴 Not done | Neev | Rejects false positives such as `LQ07209` |
| 17 | Track-level plate vote fusion | 🟡 Scaffolded | Neev | `PlateReader` works; nothing real to vote on until #14 |
| 18 | Fuzzy plate search (`/api/search/plate`) | ✅ Done | Neev | Levenshtein matcher, verified correct |
| 19 | Confusion-class character repair | ⛔ Blocked | Neev | Blocked on #14 |
| 20 | Extract `services/api/plate_routes.py` | 🔴 Not done | Neev | Removes the last shared-file conflict in `main.py` |
| 21 | Watchlist DB + admin UI + CSV import | 🔴 Not started | Neev | Plate-domain data model |
| 22 | Fuzzy watchlist matching + confidence bands | 🔴 Not started | Neev | Extends #18 |
| 23 | Alert engine (WebSocket push, ack/dismiss) | 🔴 Not started | Priyanshu | |
| 24 | **Cross-camera route reconstruction** | 🔴 Not started | Priyanshu | **Mandatory gate G3 — the thing judges test on stage** |
| 25 | Spatio-temporal plausibility filter | 🔴 Not started | Priyanshu | |
| 26 | PDF/CSV route report export | 🔴 Not started | Priyanshu | Required submission artifact |
| 27 | Vehicle Re-ID fallback | 🔴 Not started | Priyanshu | **Promoted to primary route mechanism if #14 has no reads by 1 Sep** |
| 28 | RBAC + department scoping | 🔴 Not started | Priyanshu | Ship if time (WORKPLAN.md §4) |
| 29 | Hash-chained audit log | 🔴 Not started | Priyanshu | Ship if time |
| 30 | `scripts/preflight.py` (8-point checklist) | 🔴 Not built | Priyanshu | Cheap; good demo-video material |
| 37 | Consume-only compliance enforcement + static check | ✅ Done | Priyanshu | `gateway.py` guards + `scripts/compliance_check.py`, passes clean |
| 38 | Shared cross-camera timeline (PTS→wall anchor) | ✅ Done | Priyanshu | Prerequisite for #24; see CONTEXT.md D14 |
| 31 | Public deployment + test credentials | 🔴 Not started | Priyanshu | Currently localhost only |
| 32 | Docker Compose one-command bring-up | 🔴 Not started | Priyanshu | Ship if time |
| 33 | **HLD document** | 🔴 Not started | **Unassigned** | Scored evaluation area |
| 34 | **14-slide PPT** | 🔴 Not started | **Unassigned** | Scored evaluation area |
| 35 | **Demo Video A** (own footage) | 🔴 Not started | **Unassigned** | Needs footage Priyanshu must record |
| 36 | **Demo Video B** (govt feed + output report) | 🔴 Not started | **Unassigned** | Depends on #14 working |

---

## Rollup

- **10 done · 3 partial · 1 blocked · 22 not started**
- **10 days to submission** (7 Sep), **8 days to feature freeze** (5 Sep 18:00)
- **4 mandatory submission artifacts have no owner** (#33–36)

## Critical path

The chain that must complete for the submission to score at all:

```
#14 plate OCR real reads
      └─> #17 vote fusion  ──> #22 watchlist matching ──> #23 alerts
      └─> #24 cross-camera route ──> #26 route report ──> #36 Demo Video B
```

Everything downstream of #14 is currently blocked on it. If OCR is still not
producing reads by **1 September**, the fallback in PLAN.md §4.4 — vehicle
Re-ID (#27) to carry a route when the plate is unreadable — stops being a
bonus feature and becomes the primary plan, and must be started that day.

## Decisions needed from Priyanshu

1. Confirm or reassign the owners above.
2. Decide who writes the HLD, the deck, and the two videos — or recruit a third
   member for them.
3. Accept or reject the scope triage in ROLES.md §7, in particular whether the
   Postgres migration (#11) is cut.
