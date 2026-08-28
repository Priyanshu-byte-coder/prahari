"""Render a vehicle movement report as PDF.

The organisers ask for "a screen-recorded video along with an output report
showing detected vehicles or number plates with corresponding timestamps".
This is that report as a document an officer could print and put in a file,
rather than a screenshot of a dashboard.

Two decisions worth stating, because both are about credibility in front of a
technical jury rather than about layout:

- **Rejected legs are printed, not omitted.** A leg the engine discarded
  appears in the document with the reason. A report that silently drops
  inconvenient evidence is worth less than one that shows its reasoning.
- **Confidence and provenance travel with every row.** Each sighting carries
  whether the plate matched exactly or fuzzily, how far off it was, and whether
  the camera position is ground-verified or still an approximation. Nothing in
  the document invites more confidence than the underlying data supports.
"""
from __future__ import annotations

import io
import time

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

NAVY = colors.HexColor("#0a1628")
ACCENT = colors.HexColor("#ff6b00")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#cbd5e1")
BAD = colors.HexColor("#dc2626")
OK = colors.HexColor("#15803d")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=17, leading=21,
                                textColor=NAVY, alignment=TA_LEFT, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=8.5, leading=11,
                              textColor=MUTED),
        "h2": ParagraphStyle("h", parent=base["Heading2"], fontSize=10.5, leading=13,
                             textColor=NAVY, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=8.5, leading=11),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=7.5, leading=9.5),
        "bad": ParagraphStyle("bd", parent=base["Normal"], fontSize=7.5, leading=9.5,
                              textColor=BAD),
        "note": ParagraphStyle("n", parent=base["Normal"], fontSize=7.5, leading=9.5,
                               textColor=MUTED),
    }


def _fmt_time(sighting: dict) -> str:
    if sighting.get("first_seen_iso"):
        return sighting["first_seen_iso"]
    return f"pts {sighting['first_seen']:.1f} (timing not anchored)"


def build_route_pdf(result: dict, plate: str) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Prahari vehicle movement report — {plate}",
        author="Prahari",
    )
    flow = []
    s = result["summary"]

    flow.append(Paragraph("Vehicle Movement Report", st["title"]))
    flow.append(Paragraph(
        "Prahari &middot; Unified CCTV Integration &amp; Video Intelligence Platform "
        "&middot; Gujarat Police Innovation Challenge 2026", st["sub"]))
    flow.append(Spacer(1, 7))

    meta = [
        ["Registration number queried", plate,
         "Generated", time.strftime("%Y-%m-%d %H:%M:%S")],
        ["Sightings", str(s["sightings"]),
         "Cameras", str(s["cameras"])],
        ["Exact plate matches", str(s["exact_matches"]),
         "Fuzzy matches", str(s["fuzzy_matches"])],
        ["Route distance", f"{s['route_distance_km']} km",
         "Observed span", f"{round(s['time_span_seconds'])} s"],
        ["Legs rejected as implausible", str(s["implausible_hops"]),
         "Plate match tolerance", f"±{result['query']['max_plate_distance']} characters"],
    ]
    t = Table(meta, colWidths=[52 * mm, 45 * mm, 45 * mm, 45 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (2, 0), (2, -1), MUTED),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
    ]))
    flow.append(t)

    # ---- sightings -----------------------------------------------------
    flow.append(Paragraph("Movement history", st["h2"]))
    head = ["#", "Camera", "Location", "First seen", "Dwell",
            "Plate read", "Match", "Class", "Conf.", "Position"]
    rows = [head]
    for i, sight in enumerate(result["sightings"], 1):
        exact = sight["plate_distance"] == 0
        geo = sight.get("geo_precision") or "unknown"
        rows.append([
            str(i),
            sight["camera_id"],
            Paragraph(sight["location"] or "—", st["cell"]),
            _fmt_time(sight),
            f"{sight['dwell_seconds']}s",
            sight["plate_read"],
            "exact" if exact else f"±{sight['plate_distance']:g}",
            sight["vehicle_class"],
            f"{sight['best_confidence']:.2f}",
            "verified" if geo == "operator_verified" else "approximate",
        ])

    tbl = Table(rows, colWidths=[8 * mm, 15 * mm, 52 * mm, 34 * mm, 14 * mm,
                                 30 * mm, 15 * mm, 20 * mm, 13 * mm, 24 * mm],
                repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, sight in enumerate(result["sightings"], 1):
        if sight["plate_distance"] != 0:
            style.append(("TEXTCOLOR", (6, i), (6, i), ACCENT))
        else:
            style.append(("TEXTCOLOR", (6, i), (6, i), OK))
    tbl.setStyle(TableStyle(style))
    flow.append(tbl)

    # ---- legs ----------------------------------------------------------
    if result["hops"]:
        flow.append(Paragraph("Legs between sightings", st["h2"]))
        head = ["Leg", "From", "To", "Elapsed", "Distance",
                "Implied speed", "Assessment"]
        rows = [head]
        for i, h in enumerate(result["hops"], 1):
            note = h.get("note") or ""
            assessment = "plausible" if h["plausible"] else "REJECTED"
            rows.append([
                str(i), h["from_camera"], h["to_camera"],
                f"{round(h['gap_seconds'])}s",
                f"{h['distance_km']} km" if h["distance_km"] is not None else "—",
                f"{h['implied_speed_kmh']} km/h" if h["implied_speed_kmh"] is not None else "—",
                Paragraph(f"<b>{assessment}</b>. {note}" if note else f"<b>{assessment}</b>",
                          st["bad"] if not h["plausible"] else st["cell"]),
            ])
        legs = Table(rows, colWidths=[12 * mm, 18 * mm, 18 * mm, 18 * mm,
                                      22 * mm, 26 * mm, 111 * mm], repeatRows=1)
        legstyle = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i, h in enumerate(result["hops"], 1):
            if not h["plausible"]:
                legstyle.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fef2f2")))
        legs.setStyle(TableStyle(legstyle))
        flow.append(legs)

    # ---- provenance ----------------------------------------------------
    caveats = [
        "Sighting times are derived from stream presentation timestamps anchored "
        "to the wall clock once each feed has settled after connection; they are "
        "not read from the burned-in camera overlay, which is per-camera source "
        "time and is not synchronised across the network.",
        "A sighting is one vehicle track on one camera, not one video frame. "
        "Dwell is the interval between the first and last frame of that track.",
        "Legs marked REJECTED imply a speed no road vehicle achieves. They are "
        "far more likely to be a mismatched plate read than genuine movement, "
        "and are retained in this report so the assessment can be reviewed.",
    ]
    if s.get("unanchored_sightings"):
        caveats.append(
            f"{s['unanchored_sightings']} sighting(s) predate the shared timeline "
            "and carry stream-relative timing only; they are excluded from speed "
            "assessment.")
    approx = sum(1 for x in result["sightings"]
                 if (x.get("geo_precision") or "") != "operator_verified")
    if approx:
        caveats.append(
            f"{approx} camera position(s) are approximate and not ground-verified, "
            "so distances involving them are indicative rather than surveyed.")

    flow.append(Paragraph("Basis and limitations", st["h2"]))
    for c in caveats:
        flow.append(Paragraph("&bull; " + c, st["note"]))
        flow.append(Spacer(1, 2))

    doc.build(flow)
    return buf.getvalue()
