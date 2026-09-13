# Submission pack — Prahari · Sentinel 2026

Four files, matching the three mandatory deliverables in the brief. Everything here is generated
from the repository, so a number on a slide and a number in the code cannot drift apart.

| # | Portal field | File | Format |
|---|---|---|---|
| 1 | Solution Presentation | `01-prahari-solution-presentation.pdf` | PDF, 15 pages, 16:9 |
| 2 | High-Level Design / Architecture Document | `02-prahari-high-level-design.pdf` | PDF, 14 pages, A4 |
| 3 | Workflow / Integration Diagram | `04-prahari-workflow-integration-diagram.pdf` | PDF, 1 page, 16:9 |
| — | Architecture diagram, on its own page | `03-prahari-architecture-diagram.pdf` | PDF, 1 page, 16:9 |

Both diagrams are also supplied as `.png` (220 dpi) and `.svg`, because the portal accepts PDF,
PNG, JPG, JPEG or SVG and different upload widgets prefer different ones. Upload whichever the
field takes — they are the same picture.

## Which file answers which requirement

The brief asks the presentation to cover *model chosen + justification, architecture, AI approach,
scalability*, and the HLD to cover *integration approach, watchlist correlation, alert workflow,
security, interop assumptions*. Both are covered, and neither document repeats the other at length:

- **Model and justification** — presentation slide 01, HLD §1
- **Architecture** — presentation slide 02 (the full-page diagram), HLD §1 Figure 1
- **Integration approach** — presentation slide 03, HLD §2
- **AI approach** — presentation slides 04–06, HLD §2.2 and §13
- **Watchlist correlation** — presentation slide 08, HLD §4
- **Alert workflow** — presentation slide 08, HLD §5, diagram 04 path A
- **Route reconstruction (the graded test case)** — presentation slide 09, HLD §7, diagram 04 path B
- **Security and auditability** — presentation slide 10, HLD §8
- **Scalability** — presentation slide 11, HLD §11
- **Interop assumptions** — HLD §10
- **Platform maturity / evidence** — presentation slide 12, HLD §13

## Where the numbers come from

Every figure quoted in either document is produced by a command in the repository, and slide 12
prints the commands next to their results so a judge can re-run them:

```
pytest tests/ -q                                            # 372 passed, 6 skipped
python scripts/verify_stack.py                              # 35 / 35
python services/worker/selftest.py                          # SELFTEST OK, 0.68 s
PRAHARI_INTEGRATION=1 pytest tests/test_integration.py -q   # 6 / 6
python scripts/accuracy_report.py                           # 95.0% exact, 0 confidently-wrong
python scripts/preflight.py                                 # 13 / 13
```

The ANPR accuracy set is synthetic, and both documents say so rather than rounding it into a
headline. The low-resolution benchmark on slide 06 and in HLD §13 is the number that matters for
a real grid, and it is measured against the published UFPR-SR-Plates baseline.

## Rebuilding these files

```
python docs/diagrams/build_diagrams.py      # regenerates both SVGs from source
python scripts/build_submission.py          # re-renders all four PDFs + PNGs
```

Sources: `docs/deck.html`, `docs/hld.html`, `docs/diagrams/build_diagrams.py`.
