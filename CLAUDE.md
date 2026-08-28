# Prahari — working agreement

Submission for the Gujarat Police Innovation Challenge 2026. Deadline **7 Sep 2026**.

## Read first

1. **[CONTEXT.md](CONTEXT.md)** — current state, measured grid facts, decisions, action items.
2. [ROLES.md](ROLES.md) — who owns which files, so two people can work without collisions.
3. [STATUS.md](STATUS.md) — one table, every task, every owner.
4. [PLAN.md](PLAN.md) — competition strategy and day-by-day schedule.

## The team, and how to address it

Two people share this repository, each working with their own AI coding session:

- **Priyanshu Doshi** — grid, ingestion, tracking, platform.
- **Neev Modh** — number plates, OCR, plate search.

**Write every document and comment in the third person, naming people
explicitly.** Never write "you" or "we" in a repo file. Both sessions read
these files as instructions, so "you" resolves to a different person depending
on which session is reading — this has already caused confusion once. Before
starting work, identify which lane the current session is in and stay inside
the file ownership table in ROLES.md §3.

Always `git pull` before starting. Both lanes now edit `services/worker/` and
the API routes.

## Keep CONTEXT.md current

**CONTEXT.md must be updated in the same change as the work it describes** — before
or alongside every commit, never as an afterthought. Update:

- the header block (`Last updated`, `HEAD`, days remaining)
- **§2 Current state** — move items between working / not built / broken
- **§3 Grid facts** — whenever a measurement changes or a new one is taken
- **§6 Decisions log** — any non-obvious technical choice, *with its reason*
- **§8 Action items** — tick what is done, add what is newly discovered
- **§9 Changelog** — one row per commit

If a commit changes nothing a newcomer would need to know, say so rather than
padding the changelog.

## Ground rules

- **Measure, do not assume.** The upstream catalogue omits metadata for 19 of 30
  cameras and misreports frame rate on 4. Everything about the grid in CONTEXT.md
  came from probing it. Keep it that way, and record the measurement.
- **Correct the record.** If a stated finding turns out to be wrong, fix it in
  CONTEXT.md and tell the user plainly. An earlier claim that the burned-in
  timestamps were synchronised was wrong; §3 now says why.
- **Never commit credentials.** `.env` is gitignored. Sandbox access is issued
  per registered team.
- **Pace load against the live grid.** Every client gets its own copy of each
  stream. Sequential requests with a pause; never a tight retry loop. Their
  integration guide asks for this explicitly, and we have already been throttled
  once for ignoring it.
- **Consume only.** Never publish to the gateway or call its control API.

## Non-negotiable engineering rules for this grid

These come from the organisers' integration guide and from failures we hit:

| Rule | Why |
|---|---|
| Force RTSP over TCP | UDP fails across NAT; partial delivery looks like model bugs |
| Never trust declared frame rate | Measured values disagree with the catalogue |
| Drive all timing from PTS | GOP replay on connect makes arrival-time velocities impossible |
| Tolerate inter-frame gaps | Frame intervals are not uniform; a gap is not a disconnect |
| Reconnect with exponential backoff | Feeds are supervised and restart; 2 s → 30 s cap, jittered |
| Decoder warnings are never fatal | Joining mid-stream emits RPS/POC errors until the first IDR |
| Read per-camera properties | Mixed codecs and resolutions; no fixed-shape inference batch |
| Survive scene discontinuity | Recordings loop; track ids and Re-ID galleries must reset cleanly |

## Style

- Match surrounding code. Comments explain *why*, not *what*.
- Prose in docs and commits: plain, direct, no marketing register.
- Commit messages state what changed and the reason it was needed.
