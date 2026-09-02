# fixtures/golden/ — the labelled set. Never trained on, never guessed at.

200 plate crops and 100 full frames, hand-labelled. Images are gitignored; `labels.jsonl` is
committed, because the labels are the work and they are small.

## Format — one JSON object per line

```json
{"path":"crops/GJ-AHD-0123-20260910-0841-3.jpg","plate":"GJ01AB1234",
 "camera_id":"GJ-AHD-0123","day":"2026-09-10","track":"GJ-AHD-0123-0007","frame":3,
 "source":"hand-labelled"}
```

- `plate` — exactly what a human reads off the plate, separators optional (`normalise` strips
  them). If a human cannot read it, that is data: set `"plate": null` and it counts toward the
  honest recall figure instead of silently disappearing.
- `track` — crops of one vehicle pass share it. The report votes over a track, because that is
  what the pipeline does; scoring single crops measures a different system from the one we ship.
- `camera_id` + `day` — the split keys. **Never split by frame.** Crops from one pass are near
  duplicates, and a split that puts some on each side reports memory as accuracy.
- `source` — `hand-labelled` or `synthetic`. The report prints them separately and the deck
  quotes the hand-labelled numbers.

## Running the report

```bash
python scripts/accuracy_report.py --golden fixtures/golden/
```

Writes `docs/accuracy-report.md` and `fixtures/golden/report.json`. Every accuracy number in
the deck and the model card comes from that output; none is typed by hand.

## Before the grid clips are labelled

```bash
python scripts/accuracy_report.py --make-synthetic 200
```

Generates rendered plates with exact ground truth so the pipeline is measurable today. These
are an **upper bound** - rendered glyphs, generator-controlled blur, no real perspective - and
every row is tagged `synthetic` so no number can quietly migrate into the deck.

## Labelling rules (so two people label the same way)

1. Label what is on the plate, not what the vehicle "should" have. A damaged plate reading
   `GJ01AB123` is `GJ01AB123`.
2. Unreadable is `null`, not a guess and not a skipped row. About 13% of real crops are.
3. One crop per frame, at most 8 frames per pass; take them across the pass, not consecutively.
4. Crop generously - include the plate's surround. The reader's own detector wants context.
