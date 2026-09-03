# Demo script — 8 minutes, and the drills that make it survivable

**No demo without a green integration test and a fresh accuracy report.** Both, on the day,
before anyone opens a browser:

```bash
# legs 2-3 need an investigator credential - without it they skip, they never pass vacuously:
export PRAHARI_TEST_USER=<investigator> PRAHARI_TEST_PASSWORD=<pw>   # or PRAHARI_TEST_JWT=<token>
PRAHARI_INTEGRATION=1 pytest tests/test_integration.py -v     # every leg green or explicitly skipped
python scripts/accuracy_report.py --golden fixtures/golden/   # regenerates docs/accuracy-report.md
```

If either is red, the demo is the fix, not the presentation. A run where legs 2-3 **skip** is
not a green run for demo purposes — chase the skip reason (API down, wrong role, no credential)
until all four legs are green.

---

## Before the room (T-30 min)

```bash
make up                                        # postgres+timescale, redis, minio, mediamtx, osrm
make seed                                      # cameras.seed.json + camera_geo.json
python -m services.worker.run --camera GJ-AHD-0001 --camera GJ-AHD-0002 --metrics-port 9108
uvicorn services.api.main:app --host 0.0.0.0   # core
python -m http.server 5173 -d web              # console
scripts/replay_clip.sh                         # the known-plate camera, in its own shell
```

Checks, in this order, each one a thing that has failed before:

1. `curl -s localhost:9108/metrics | grep prahari_sightings_total` — rows are being produced.
2. `curl -s localhost:8000/healthz` and the console loads with pins on the map.
3. Open the video wall on **a phone hotspot**. Judges' networks block WebRTC; the 3 s HLS
   fallback badge has to be seen working, not described.
4. `python -m services.worker.selftest --assert-xadd` — one command, end to end, ~40 s.
5. Watchlist already contains the demo plate, added through the UI so the audit row exists.
6. Laptop on mains, screen sleep off, notifications off, browser zoom 110%, one window.

## The eight minutes

| min | What is on screen | What is said | The point being scored |
|---|---|---|---|
| 0:00–0:45 | title, then the map with every camera pinned | "80,000 cameras, four vendors, no common console. We built the middleware, not another VMS." | problem framing |
| 0:45–1:45 | admin → drivers page, four rows | "Three drivers live. The VMS driver is interface-complete and waiting on vendor credentials — we are not going to pretend otherwise." | M3 hybrid, honesty |
| 1:45–2:45 | video wall, one WHEP tile, one degraded to HLS with the badge | "Port 8554 is blocked here, so this camera fell back to HLS by itself. That is the heterogeneity the brief is about." | M2, resilience |
| 2:45–4:00 | live detections on the map; open one sighting: crop, class, band, timestamp | "Every row is 200 bytes, timestamped from the frame's own PTS, not from a server clock." | ANPR, [C1] |
| 4:00–5:00 | alert fires for the watchlist plate; ack it with a reason | "CONFIRMED band. Below a 2/3 character majority we publish the crop and no plate — we would rather report nothing than the wrong vehicle." | precision over recall |
| 5:00–6:15 | type the plate → route across cameras, snapped to roads, one hop flagged IMPLAUSIBLE | "This is the graded test case. The flagged hop is the system refusing to draw a line it cannot defend." | the graded scenario |
| 6:15–7:00 | log in as a district viewer: the same query returns less | "Scope is enforced in SQL with row-level security. Hiding a button is not access control." | RBAC, [C10] |
| 7:00–7:40 | audit log, then `/api/admin/audit/verify` returning ok | "Every export and every live view is logged, and the log is hash-chained." | accountability |
| 7:40–8:00 | the scale slide | "160 Gbps and 26 petabytes to centralise the video. 16 GB a day to ship the rows. That is the architecture." | scale arithmetic |

**Do not** narrate the pipeline internals. If asked, the answer is one sentence — "vehicle
detect, per-camera tracker, plate detect inside the vehicle crop, two readers, grammar, then a
per-character vote that refuses below two thirds" — and then back to the screen.

## Chaos drills

Run all four the day before, timed, and write the result in the table. A drill nobody has run
is a rehearsal for panic.

| # | Drill | Command | Expected | Last run |
|---|---|---|---|---|
| 1 | kill a driver | `docker kill prahari-gateway` (or the driver process) | camera pins go red within one health interval; the driver restarts and pins recover; no sightings lost from the other cameras | |
| 2 | block RTSP | `iptables -A OUTPUT -p tcp --dport 8554 -j REJECT` (Windows: firewall rule) | the gateway probes, marks the transport unavailable, and the wall falls back to HLS with the badge inside 3 s | |
| 3 | restart Postgres | `docker restart prahari-postgres` | the worker keeps publishing; D's persister buffers and replays; **row count before == row count after** | |
| 4 | disconnect the console | close the laptop lid / drop wifi for 60 s | the WebSocket reconnects and backfills with `{"type":"resume","since":<seq>}`; no gap in the events layer | |

Drill 3 has a worker-side half worth showing explicitly, because it is the one people doubt:

```bash
docker stop prahari-redis
python -m services.worker.selftest --assert-xadd   # rows buffer in memory, nothing raises
docker start prahari-redis                          # the buffer drains, oldest first, in order
curl -s localhost:9108/metrics | grep -E "buffered|publish_failures"
```

The buffer is bounded (20,000 rows, about 40 minutes of one busy camera). Past that it drops
the oldest and says so in the log — say that out loud if asked, rather than claiming
unlimited durability we have not built.

## Rehearsals

Two full run-throughs, timed, before submission. Record what actually went wrong.

| # | Date | Time taken | What broke | Fix |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

## If something dies mid-demo

- **A camera goes dark** — say so and move on; the health pin turning red *is* a feature you
  were going to demo anyway.
- **The route is empty** — fall back to the replayed clip's camera, which is the one you
  control. Never re-type the plate three times in silence.
- **The console will not load** — show `/metrics` and the raw sighting row. Rows are the
  product; the map is a view of them.
- **Nothing works** — the demo video (2–3 minutes, recorded on our own running system, see
  `docs/submission.md`) is on the laptop and on a USB stick. Play it, then debug afterwards.
