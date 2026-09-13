"""Render the submission pack: two documents, two diagrams, PDF and PNG.

    python scripts/build_submission.py
    python scripts/build_submission.py --only deck

Headless Chrome does the printing, because it is the only renderer on this machine that agrees
with what the author sees in a browser - WeasyPrint and wkhtmltopdf both disagree with Chrome
about flexbox inside a fixed-height print page, which is exactly what a 16:9 slide is.

Page sizes are declared in the CSS (`@page`), not here: the deck is 338.67 x 190.5 mm (16:9 at
96 dpi) and the HLD is A4. This script only points Chrome at the right file and checks that what
came out has the page count and page size it should.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "submission"
DIAGRAMS = ROOT / "docs" / "diagrams"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

# name, source html, expected page shape (portrait A4 or 16:9 landscape)
JOBS = [
    ("deck", "01-prahari-solution-presentation", ROOT / "docs" / "deck.html", "wide"),
    ("hld", "02-prahari-high-level-design", ROOT / "docs" / "hld.html", "a4"),
    ("architecture", "03-prahari-architecture-diagram", DIAGRAMS / "architecture.page.html", "wide"),
    ("workflow", "04-prahari-workflow-integration-diagram", DIAGRAMS / "workflow.page.html", "wide"),
]

SHAPES = {"wide": (960, 540), "a4": (595, 842)}


def find_chrome():
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("msedge")
    if found:
        return found
    raise SystemExit("No Chrome or Edge found. Install one, or edit CHROME_CANDIDATES.")


def print_pdf(chrome, src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The virtual time budget matters: without it Chrome prints before the webfonts arrive and
    # every heading falls back to the system sans, which is visible and looks like a broken file.
    cmd = [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
           "--virtual-time-budget=20000",
           "--print-to-pdf=%s" % dest, src.resolve().as_uri()]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if not dest.exists():
        raise SystemExit("Chrome produced nothing for %s\n%s" % (src.name, proc.stderr[-800:]))


def check(dest: Path, shape: str):
    """Page count and page size, so a silent layout regression cannot ship."""
    try:
        import fitz
    except ImportError:
        print("      (PyMuPDF not installed - skipping the page check)")
        return
    doc = fitz.open(dest)
    want = SHAPES[shape]
    got = tuple(round(v) for v in doc[0].rect[2:])
    ok = abs(got[0] - want[0]) <= 2 and abs(got[1] - want[1]) <= 2
    print("      %d pages, %dx%d pt %s" % (doc.page_count, got[0], got[1],
                                           "OK" if ok else "!! expected %dx%d" % want))
    if shape == "wide" and "diagram" in dest.name and doc.page_count != 1:
        print("      !! a one-page diagram came out as %d pages" % doc.page_count)


def png(dest: Path, dpi=220):
    try:
        import fitz
    except ImportError:
        return
    doc = fitz.open(dest)
    target = dest.with_suffix(".png")
    doc[0].get_pixmap(dpi=dpi).save(target)
    print("      + %s" % target.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=[j[0] for j in JOBS], help="build one job")
    args = ap.parse_args()

    chrome = find_chrome()
    print("chrome: %s\n" % chrome)

    for key, name, src, shape in JOBS:
        if args.only and key != args.only:
            continue
        if not src.exists():
            print("%-14s SKIP - %s is missing" % (key, src.name))
            continue
        dest = OUT / ("%s.pdf" % name)
        print("%-14s %s -> %s" % (key, src.name, dest.name))
        print_pdf(chrome, src, dest)
        check(dest, shape)
        if key in ("architecture", "workflow"):
            png(dest)
            shutil.copy(DIAGRAMS / ("%s.svg" % key), OUT / ("%s.svg" % name))
            print("      + %s.svg" % name)

    print("\nsubmission pack in %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
