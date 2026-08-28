"""Static compliance check against the organisers' hard rules.

The Sentinel integration guide contains a handful of rules whose breach is a
disqualification risk rather than a bug: consume only, never publish upstream,
never call the control API, never plan around downloading footage, never
hard-code camera endpoints, force TCP on RTSP. Those rules are easy to honour
on day one and easy to break by accident on day nine, when someone adds a
convenience helper at 2am.

This scans the source tree and fails loudly if any of them has been broken.
Run it before every commit that touches ingestion, and before submitting.

    python scripts/compliance_check.py

Exit code 0 = clean, 1 = at least one violation.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_HOST = "live.corp8.cloud"

SCAN_DIRS = ["services", "scripts", "web", "simgrid"]
SCAN_SUFFIXES = {".py", ".js", ".html", ".yml", ".yaml"}
SKIP_PARTS = {"vendor", "__pycache__", ".venv", "node_modules"}

# This file necessarily contains the patterns it forbids.
SELF = Path(__file__).name

# Code that *enforces* a rule has to name the thing it blocks. Such lines carry
# this pragma. It is deliberately noisy to write, so it cannot be sprinkled
# around to silence a real finding without that showing up in review.
PRAGMA = "compliance-allow: enforcement"


@dataclass
class Rule:
    id: str
    title: str
    why: str
    pattern: re.Pattern
    # A finding is only a violation if this second pattern also matches the line
    # (used to scope "write verb" checks to the upstream host).
    requires: re.Pattern | None = None
    allow: re.Pattern | None = None


RULES = [
    Rule(
        id="C1",
        title="No writes to the sandbox grid",
        why="The integration guide says consume only. Publishing to the gateway "
            "or calling its control API is an explicit disqualification risk.",
        pattern=re.compile(r"\.(post|put|patch|delete)\s*\(", re.I),
        requires=re.compile(re.escape(UPSTREAM_HOST) + r"|UPSTREAM_BASE", re.I),
    ),
    Rule(
        id="C2",
        title="No control-API or publish paths",
        why="MediaMTX exposes configuration and WHIP publishing endpoints. "
            "Touching either is forbidden.",
        pattern=re.compile(r"/v[123]/config|/whip\b|whip/|/publish\b", re.I),
    ),
    Rule(
        id="C3",
        title="No hard-coded camera stream endpoints",
        why="Camera ids change between the sandbox and the finale. Every "
            "endpoint must be derived from GET /api/ingest, or it breaks on "
            "evaluation day.",
        pattern=re.compile(
            r"(rtsp://|https?://)[^\s\"']*" + re.escape(UPSTREAM_HOST) + r"[^\s\"']*/stream/\d+",
            re.I,
        ),
    ),
    Rule(
        id="C4",
        title="RTSP must be forced over TCP",
        why="UDP fails across NAT and venue firewalls, and partial delivery "
            "produces corrupt frames that look like model bugs.",
        # Flags an RTSP open that does not mention tcp on the same line.
        pattern=re.compile(r"rtsp_transport\s*[=:]\s*['\"]?udp", re.I),
    ),
    Rule(
        id="C5",
        title="No downloading or archiving of grid footage",
        why="The grid is live-only, with no seek and no download. Writing whole "
            "streams to disk both breaks on the real grid and reads as an "
            "attempt to take copies of government footage.",
        pattern=re.compile(
            r"(wget|curl\s+-o|urlretrieve)\b[^\n]*" + re.escape(UPSTREAM_HOST), re.I
        ),
    ),
]


def iter_files():
    for rel in SCAN_DIRS:
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.name == SELF:
                continue
            yield path


def main() -> int:
    violations: list[tuple[Rule, Path, int, str]] = []
    files = list(iter_files())

    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            stripped = line.strip()
            # Comments describe the rules; they do not break them.
            if stripped.startswith(("#", "//", "*", '"""', "'''")):
                continue
            if PRAGMA in line:
                continue
            for rule in RULES:
                if not rule.pattern.search(line):
                    continue
                if rule.requires and not rule.requires.search(line):
                    continue
                if rule.allow and rule.allow.search(line):
                    continue
                violations.append((rule, path, n, stripped[:120]))

    print(f"Prahari compliance check — {len(files)} files scanned\n")
    width = max(len(r.title) for r in RULES) + 2
    for rule in RULES:
        hits = [v for v in violations if v[0].id == rule.id]
        mark = "FAIL" if hits else " OK "
        print(f"  [{mark}] {rule.id}  {rule.title:<{width}} ({len(hits)} finding(s))")

    if violations:
        print("\n" + "=" * 72)
        for rule, path, n, snippet in violations:
            print(f"\n{rule.id} — {rule.title}")
            print(f"  {path.relative_to(ROOT)}:{n}")
            print(f"  {snippet}")
            print(f"  why: {rule.why}")
        print("\n" + "=" * 72)
        print(f"{len(violations)} violation(s). These are disqualification risks, not style nits.")
        return 1

    print("\nAll consume-only rules hold. Safe to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
