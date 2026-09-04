# CLAUDE.md — how to work in this repo

Repo rules beat the global `~/.claude/CLAUDE.md` where they differ. The one difference: **the
auto-maintained memory here is `knowledge_base.md`, not `AGENTS.md`.** `AGENTS.md` is the stable
spine and changes maybe twice a week; `knowledge_base.md` changes after every task.

Deadline: submission **7 Sep 2026**, event 10–11 Sep. Three developers, three lanes, one shared file.

## 1. Orientation budget — one file, one grep

```
1. knowledge_base.md          read whole, always, first. Capped at 300 lines. This is your context.
2. your ticket block          grep -n -A 22 '^### N3' TASK.md
3. a contract, if named       grep -n -A 30 '^## C1 ' TASK.md    (trailing space: '^## C1' also hits C10)
```

That is the entire allowance. Then write code.

- **Never** read `TASK.md` whole (~500 lines) — grep your ticket.
- **Never** read `docs/internal/implementation-plan.md` whole (745 lines). Grep an anchor:
  `grep -n -A 30 '^### B3' docs/internal/implementation-plan.md`. Your ticket already carries what you need;
  go here only when the ticket points you here or you are genuinely stuck.
- **Never** read `docs/brief-sentinel-hackathon.md` unless the question is "what do the judges require".
- **Never** read another lane's source. What you need from them is a frozen contract in `TASK.md §C`.
  If it is not in a contract, it is not a dependency — say so and move on.

## 2. Token rules

1. Grep for a symbol before reading a file. Read line ranges, not whole files. Never a file over 400 lines whole.
2. Never read the same file twice in a session. First read → record what it gives you in the file map.
3. Check the `knowledge_base.md` file map before opening anything — if purpose and symbols are listed, that is your answer.
4. Exploration touching more than 3 files → subagent, summary only comes back.
5. Never echo a file back. Diffs and snippets only. Never explain unchanged code.
6. Answers ≤10 lines unless detail was asked for. No preamble, no restating the request, no summary of what you just did.
7. Library question → check `## 3. Gotchas` first, then web search once, then **write the answer into Gotchas** so nobody pays for it twice.
8. Multi-file edit → list the files and the one-line change each, then do it. Pause only if something is destructive.

## 3. The update contract — mandatory, after every completed task

Not optional, not "if significant". A ticket without a KB patch is not done. Do it silently, do not
narrate it, and keep it to **one `Edit` per section touched** — never rewrite the file.

```
git pull --rebase          # before you touch the KB, always
```

| Section | When | Exact line |
|---|---|---|
| `## 1. Ticket board` | every ticket state change | flip the `state` cell to `WIP` / `DONE` / `BLOCKED`, paste the 7-char commit |
| `## 2. File map` | you created a file | `` `path` — purpose — key symbols `` (one line, under your lane) |
| `## 3. Gotchas` | you lost >15 min to something non-obvious | `[N] one line, the fix, not the story` |
| `## 4. Decisions` | you picked between real alternatives | `YYYY-MM-DD — decision — why` |
| `## 5. Contract changes` | you changed anything in `TASK.md §C` | `YYYY-MM-DD — [C4] what changed — who was told` **and tell the other two before you push** |
| `## 6. Changelog` | every completed ticket | `MM-DD | N3 | files touched | outcome` at the top of **your lane's** block |

Rules that keep three people out of each other's merges:

- Edit only lines inside **your own lane's** block. Lane N never edits lane P's rows.
- Append at the top of your changelog block, never in the middle. Rebase conflicts then become trivial.
- Enforce the 300-line cap yourself: when the KB grows past it, fold your oldest changelog lines into
  `## 7. Archived` as one line per day, and delete file-map lines for files that no longer exist.
- If a fact belongs in the KB, it does not also belong in a chat summary. Write it once, in the file.

## 4. Ticket loop

```
grep your ticket  →  code (your directories only)  →  run the ticket's Verify line
   →  patch knowledge_base.md  →  commit "[N3] message"  →  push lane/<yourname>  →  PR to main
```

- Blocked? Set the board cell to `BLOCKED` with one line of why, then start the next ticket in your lane.
  Never idle on another person, and never start their ticket to unblock yourself.
- Need something inside someone else's directory? One line in `TASK.md` → `## Cross-lane requests`. Do not edit their code.
- Before writing anything new, check §4 of `TASK.md`: the pre-`Restart` code at `4d0c945` and on
  `origin/priyanshu/platform` is still recoverable with `git show`, and salvaging beats rewriting.

## 5. Build rules

- Ship the smallest thing that passes the ticket's `Done when`. P1 items do not get built before P0 is green.
- Every non-trivial ticket leaves **one runnable check** behind — the `Verify:` line. No frameworks beyond pytest.
- Open source only, and no vendor lock-in — it is a contest rule, not a preference.
- Never fake a number. Accuracy figures come from `scripts/accuracy_report.py`; latency comes from a measurement.
  A wrong plate shown to a police officer is worse than no plate, and the same rule applies to the deck.
- Deliberate corners get a `# ponytail:` comment naming the ceiling and the upgrade path.
- Never commit: `.env`, weights, video, crops, anything over 10 MB.
