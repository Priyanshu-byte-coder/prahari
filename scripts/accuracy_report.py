"""[I7] The only source of accuracy numbers. Every figure in the deck comes out of this file.

    python scripts/accuracy_report.py --golden fixtures/golden/

What it measures, and why each one is here:

  exact-match rate      the number a judge will ask for, per reader and for the fused vote
  CER                   character error rate - tells you *how* wrong a wrong read was, which
                        separates "one confusable digit" from "read a different vehicle"
  precision per band    the number that matters. CONFIRMED must be near-perfect precision or
                        the band means nothing; POSSIBLE is allowed to be wrong, it publishes
                        no plate_text
  refusal / recall      the share of plates no reader can read at all. Around 13% of real
                        crops. Quoting exact-match without it is how a 70% system gets
                        presented as a 95% one

**Splits.** Never by frame. Frames from one vehicle pass are near-duplicates, and a split that
puts some on each side reports the model's memory as its accuracy. Groups are (camera, day)
here, and every crop of one track stays in one group by construction.

**Synthetic vs hand-labelled.** Rendered plates are an upper bound, and they are labelled
`synthetic` in the report and printed in their own block. The deck quotes the hand-labelled
grid split. `--make-synthetic` exists so the report runs, and the pipeline is measurable, before
the grid clips are labelled - not so the deck has a bigger number.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.plate import grammar_fix, normalise  # noqa: E402
from services.worker.plate import read_all, readers  # noqa: E402
from services.worker.vote import PlateVote  # noqa: E402

logger = logging.getLogger("prahari.accuracy")

GOLDEN = ROOT / "fixtures" / "golden"
BANDS = ("CONFIRMED", "PROBABLE", "POSSIBLE", "NONE")


# --- the golden set -------------------------------------------------------------------------

def load(golden=GOLDEN):
    """Read `labels.jsonl`. One row per crop: path, plate, camera_id, day, track, source."""
    path = Path(golden) / "labels.jsonl"
    if not path.exists():
        raise SystemExit(f"no golden set at {path}\n"
                         f"  hand-labelled crops go in {golden}/crops/ with a line each in "
                         f"labels.jsonl\n"
                         f"  or run with --make-synthetic 200 to generate a stand-in set")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        image = cv2.imread(str(Path(golden) / row["path"]))
        if image is None:
            logger.warning("unreadable crop, skipped: %s", row["path"])
            continue
        row["image"] = image
        row["plate"] = normalise(row["plate"])
        rows.append(row)
    return rows


def make_synthetic(golden=GOLDEN, count=200, seed=0):
    """Write a synthetic golden set. Labelled `synthetic` on every row, deliberately."""
    from services.worker.synth import crops

    golden = Path(golden)
    (golden / "crops").mkdir(parents=True, exist_ok=True)
    lines = []
    for i, row in enumerate(crops(count=count, seed=seed)):
        name = f"crops/{row['track']}-{row['frame']}.jpg"
        cv2.imwrite(str(golden / name), row.pop("image"))
        lines.append(json.dumps({"path": name, **row}))
    (golden / "labels.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# --- metrics --------------------------------------------------------------------------------

def cer(truth, guess):
    """Character error rate: unweighted Levenshtein over the true length. 1.0 when nothing read.

    Unweighted on purpose, unlike [C7]'s `weighted_levenshtein` - that one is for *matching*,
    where a confusable substitution should cost less. Here we are reporting how wrong we were,
    and a wrong character is a wrong character however sympathetic the reason.
    """
    if not truth:
        return 0.0
    if not guess:
        return 1.0
    prev = list(range(len(guess) + 1))
    for i, a in enumerate(truth, 1):
        cur = [i]
        for j, b in enumerate(guess, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / len(truth)


def summarise(cases):
    """cases: (truth, guess, band). Returns the block of numbers the deck quotes."""
    total = len(cases)
    if not total:
        return {}
    read = [c for c in cases if c[1]]
    exact = [c for c in cases if c[1] == c[0]]
    per_band = {}
    for band in BANDS:
        in_band = [c for c in cases if c[2] == band]
        named = [c for c in in_band if c[1]]
        per_band[band] = {
            "n": len(in_band),
            "share": round(len(in_band) / total, 4),
            "precision": (round(sum(c[1] == c[0] for c in named) / len(named), 4)
                          if named else None),
            "wrong": sum(c[1] != c[0] for c in named),
        }
    return {
        "n": total,
        "exact_match": round(len(exact) / total, 4),
        "exact_match_of_read": round(len(exact) / len(read), 4) if read else None,
        "cer": round(statistics.fmean(cer(t, g) for t, g, _ in cases), 4),
        "refused": round(1 - len(read) / total, 4),
        "bands": per_band,
    }


def score(rows, engines=None):
    """Run every reader over every crop, then the fused vote over each track."""
    # Every engine present, not just the ones inside the live latency budget. This report is
    # offline: wall time does not matter here, and the point is to measure each reader as well as
    # the vote. The live worker deliberately loads fewer - see plate.DEFAULT_READER_BUDGET_MS -
    # so the report states which engines it used and the deck must quote that, not "all of them".
    os.environ.setdefault("PRAHARI_OCR_READERS", "all")
    engines = readers() if engines is None else engines
    per_reader = defaultdict(list)
    per_track = defaultdict(lambda: {"truth": None, "votes": PlateVote(), "group": None})
    started = time.time()

    for i, row in enumerate(rows, 1):
        readings = read_all(row["image"], engines=engines)
        for reading in readings:
            guess = grammar_fix(normalise(reading.text)) or ""
            per_reader[reading.reader].append((row["plate"], guess, "-"))
        for engine in engines:                       # a reader that returned nothing still counts
            if not any(r.reader == engine.name for r in readings):
                per_reader[engine.name].append((row["plate"], "", "-"))
        track = per_track[row.get("track", row["path"])]
        track["truth"] = row["plate"]
        track["group"] = (row.get("camera_id", "?"), row.get("day", "?"))
        track["votes"].add(readings, sharpness=float(row.get("sharpness", i % 8)))
        if i % 25 == 0:
            logger.info("%d/%d crops (%.1f/s)", i, len(rows), i / (time.time() - started))

    fused, by_group = [], defaultdict(list)
    for track in per_track.values():
        text, _conf, band = track["votes"].result()
        case = (track["truth"], text or "", band)
        fused.append(case)
        by_group[track["group"]].append(case)

    return {
        "readers": {name: summarise(cases) for name, cases in per_reader.items()},
        "vote": summarise(fused),
        "groups": {f"{cam}|{day}": summarise(cases)
                   for (cam, day), cases in sorted(by_group.items())},
        "seconds": round(time.time() - started, 1),
    }


# --- report ---------------------------------------------------------------------------------

def render(report, rows, engines):
    sources = sorted({r.get("source", "hand-labelled") for r in rows})
    tracks = len({r.get("track", r["path"]) for r in rows})
    out = [
        "# Accuracy report — lane I (generated, do not edit)",
        "",
        f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S%z')}",
        f"- crops: {len(rows)} in {tracks} tracks · sources: {', '.join(sources)}",
        f"- readers: {', '.join(e.name for e in engines) or 'none'}",
        f"- runtime: {report['seconds']}s",
        "",
        "## Per reader (single crop, no vote)",
        "",
        "| reader | n | exact | exact of read | CER | refused |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in sorted(report["readers"].items()):
        out.append(f"| {name} | {s['n']} | {s['exact_match']:.1%} | "
                   f"{_pct(s['exact_match_of_read'])} | {s['cer']:.3f} | {s['refused']:.1%} |")

    vote = report["vote"]
    out += ["", "## Fused vote (multi-frame, multi-reader) — what the pipeline emits", "",
            f"- tracks: {vote['n']}",
            f"- exact match: **{vote['exact_match']:.1%}** of all tracks, "
            f"{_pct(vote['exact_match_of_read'])} of the tracks it named",
            f"- CER: {vote['cer']:.3f}",
            f"- refused to name a plate: **{vote['refused']:.1%}** "
            f"(these publish a crop and a null `plate_text`)",
            "", "| band | n | share | precision | wrong |", "|---|---|---|---|---|"]
    for band in BANDS:
        b = vote["bands"][band]
        out.append(f"| {band} | {b['n']} | {b['share']:.1%} | {_pct(b['precision'])} | "
                   f"{b['wrong']} |")

    out += ["", "## By split (camera | day) — never by frame", "",
            "| split | tracks | exact | refused |", "|---|---|---|---|"]
    for name, s in report["groups"].items():
        out.append(f"| {name} | {s['n']} | {s['exact_match']:.1%} | {s['refused']:.1%} |")

    confirmed_wrong = vote["bands"]["CONFIRMED"]["wrong"]
    out += ["", "## Verdict", "",
            f"- CONFIRMED wrong reads: **{confirmed_wrong}** "
            f"({'meets' if confirmed_wrong == 0 else 'FAILS'} I4's zero-confident-wrong bar)",
            f"- exact match on named tracks: {_pct(vote['exact_match_of_read'])} "
            f"({'meets' if (vote['exact_match_of_read'] or 0) >= 0.70 else 'below'} the 70% bar)"]
    if "synthetic" in sources:
        out += ["", "> Synthetic crops are an upper bound: rendered glyphs, no perspective, no "
                "motion blur beyond what the generator adds. The deck quotes the hand-labelled "
                "grid split, and this report prints which is which."]
    return "\n".join(out) + "\n"


def _pct(value):
    return "-" if value is None else f"{value:.1%}"


def _manifest_len(golden):
    manifest = Path(golden) / "labels.jsonl"
    if not manifest.exists():
        return 0
    return sum(1 for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description="[I7] golden set accuracy report")
    ap.add_argument("--golden", default=str(GOLDEN))
    ap.add_argument("--make-synthetic", type=int, metavar="N",
                    help="generate N synthetic labelled crops first (stand-in for grid clips)")
    ap.add_argument("--limit", type=int, help="score only the first N crops")
    ap.add_argument("--out", default=str(ROOT / "docs" / "accuracy-report.md"))
    ap.add_argument("--json", dest="json_out", default=str(GOLDEN / "report.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s %(message)s")

    if args.make_synthetic:
        n = make_synthetic(args.golden, args.make_synthetic)
        print(f"wrote {n} synthetic crops to {args.golden}")

    rows = load(args.golden)[: args.limit]
    if not rows:
        manifest = _manifest_len(args.golden)
        raise SystemExit(
            "no labelled crops found under " + str(args.golden) + ".\n"
            "labels.jsonl lists " + str(manifest) + " rows, but the images they name are not "
            "there - crops are not committed to this repo.\n"
            "Either drop the hand-labelled crops into that directory, or generate a synthetic "
            "stand-in:\n"
            "    python scripts/accuracy_report.py --make-synthetic 40\n"
            "A report scored over zero crops is not a low number, it is no number, and the deck "
            "must not quote one.")
    engines = readers()
    if not engines:
        raise SystemExit("no OCR reader available - install easyocr or paddleocr")
    if len(engines) < 2:
        logging.getLogger("prahari.accuracy").warning(
            "scoring with a single reader (%s): this measures one read, not the 2-of-3 vote the "
            "pipeline ships. The report says so, and so must the deck.",
            ", ".join(e.name for e in engines))
    report = score(rows, engines)
    markdown = render(report, rows, engines)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(markdown, encoding="utf-8")
    Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(markdown)
    print(f"written: {args.out} and {args.json_out}")
    return 0 if report["vote"]["bands"]["CONFIRMED"]["wrong"] == 0 else 1


if __name__ == "__main__":
    os.environ.setdefault("YOLO_VERBOSE", "0")
    raise SystemExit(main())
