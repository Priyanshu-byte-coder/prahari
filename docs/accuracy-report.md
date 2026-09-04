# Accuracy report — lane I (generated, do not edit)

- generated: 2026-09-04 10:51:30+0530
- crops: 60 in 20 tracks · sources: synthetic
- readers: easyocr, paddleocr, fastplate
- runtime: 89.7s

## Per reader (single crop, no vote)

| reader | n | exact | exact of read | CER | refused |
|---|---|---|---|---|---|
| easyocr | 60 | 65.0% | 67.2% | 0.240 | 3.3% |
| fastplate | 60 | 16.7% | 16.7% | 0.280 | 0.0% |
| paddleocr | 60 | 78.3% | 82.5% | 0.166 | 5.0% |

## Fused vote (multi-frame, multi-reader) — what the pipeline emits

- tracks: 20
- exact match: **95.0%** of all tracks, 100.0% of the tracks it named
- CER: 0.050
- refused to name a plate: **5.0%** (these publish a crop and a null `plate_text`)

| band | n | share | precision | wrong |
|---|---|---|---|---|
| CONFIRMED | 17 | 85.0% | 100.0% | 0 |
| PROBABLE | 2 | 10.0% | 100.0% | 0 |
| POSSIBLE | 1 | 5.0% | - | 0 |
| NONE | 0 | 0.0% | - | 0 |

## By split (camera | day) — never by frame

| split | tracks | exact | refused |
|---|---|---|---|
| SYNTH-000|2026-09-10 | 2 | 100.0% | 0.0% |
| SYNTH-000|2026-09-11 | 2 | 100.0% | 0.0% |
| SYNTH-000|2026-09-12 | 1 | 100.0% | 0.0% |
| SYNTH-001|2026-09-10 | 1 | 100.0% | 0.0% |
| SYNTH-001|2026-09-11 | 2 | 100.0% | 0.0% |
| SYNTH-001|2026-09-12 | 2 | 100.0% | 0.0% |
| SYNTH-002|2026-09-10 | 2 | 100.0% | 0.0% |
| SYNTH-002|2026-09-11 | 1 | 100.0% | 0.0% |
| SYNTH-002|2026-09-12 | 2 | 50.0% | 50.0% |
| SYNTH-003|2026-09-10 | 2 | 100.0% | 0.0% |
| SYNTH-003|2026-09-11 | 2 | 100.0% | 0.0% |
| SYNTH-003|2026-09-12 | 1 | 100.0% | 0.0% |

## Verdict

- CONFIRMED wrong reads: **0** (meets I4's zero-confident-wrong bar)
- exact match on named tracks: 100.0% (meets the 70% bar)

> Synthetic crops are an upper bound: rendered glyphs, no perspective, no motion blur beyond what the generator adds. The deck quotes the hand-labelled grid split, and this report prints which is which.
