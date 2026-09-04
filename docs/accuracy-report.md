# Accuracy report — lane I (generated, do not edit)

- generated: 2026-09-04 12:38:08+0530
- crops: 120 in 40 tracks · sources: synthetic
- readers: easyocr, paddleocr, tesseract, fastplate
- runtime: 50.8s

## Per reader (single crop, no vote)

| reader | n | exact | exact of read | CER | refused |
|---|---|---|---|---|---|
| easyocr | 120 | 70.0% | 73.7% | 0.221 | 5.0% |
| fastplate | 120 | 55.0% | 55.9% | 0.241 | 1.7% |
| paddleocr | 120 | 79.2% | 83.3% | 0.121 | 5.0% |
| tesseract | 120 | 42.5% | 46.0% | 0.257 | 7.5% |

## Fused vote (multi-frame, multi-reader) — what the pipeline emits

- tracks: 40
- exact match: **95.0%** of all tracks, 100.0% of the tracks it named
- CER: 0.050
- refused to name a plate: **5.0%** (these publish a crop and a null `plate_text`)

| band | n | share | precision | wrong |
|---|---|---|---|---|
| CONFIRMED | 38 | 95.0% | 100.0% | 0 |
| PROBABLE | 0 | 0.0% | - | 0 |
| POSSIBLE | 2 | 5.0% | - | 0 |
| NONE | 0 | 0.0% | - | 0 |

## By split (camera | day) — never by frame

| split | tracks | exact | refused |
|---|---|---|---|
| SYNTH-000|2026-09-10 | 4 | 100.0% | 0.0% |
| SYNTH-000|2026-09-11 | 3 | 100.0% | 0.0% |
| SYNTH-000|2026-09-12 | 3 | 100.0% | 0.0% |
| SYNTH-001|2026-09-10 | 3 | 100.0% | 0.0% |
| SYNTH-001|2026-09-11 | 4 | 100.0% | 0.0% |
| SYNTH-001|2026-09-12 | 3 | 100.0% | 0.0% |
| SYNTH-002|2026-09-10 | 3 | 100.0% | 0.0% |
| SYNTH-002|2026-09-11 | 3 | 66.7% | 33.3% |
| SYNTH-002|2026-09-12 | 4 | 100.0% | 0.0% |
| SYNTH-003|2026-09-10 | 4 | 100.0% | 0.0% |
| SYNTH-003|2026-09-11 | 3 | 66.7% | 33.3% |
| SYNTH-003|2026-09-12 | 3 | 100.0% | 0.0% |

## Verdict

- CONFIRMED wrong reads: **0** (meets I4's zero-confident-wrong bar)
- exact match on named tracks: 100.0% (meets the 70% bar)

> Synthetic crops are an upper bound: rendered glyphs, no perspective, no motion blur beyond what the generator adds. The deck quotes the hand-labelled grid split, and this report prints which is which.
