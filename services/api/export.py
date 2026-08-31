"""Route exports: the artifact that leaves the system, and the audit row that records it.

CSV for anything that will be opened in a spreadsheet or attached to a case file, PDF for the
version a person signs. Both carry the same numbers, both carry the plausibility flags, and
neither is produced without writing an audit row first - an export is a copy of surveillance
data leaving the building, and "who exported what, when" is the question that gets asked
afterwards.

The PDF is drawn with reportlab rather than WeasyPrint, which D6 names. WeasyPrint needs GTK
libraries present on the machine; reportlab is a pure wheel, and on a hackathon laptop the
difference is whether the deliverable builds at all. The layout is the salvaged one from
`origin/priyanshu/platform:services/api/route_report.py` - a title block, a hop table, and a
schematic of the path.

The schematic is drawn from the hop coordinates, not from map tiles. Calling it a map would be
a lie: there is no basemap behind it. It shows shape and order, which is what the table cannot.
"""

import csv
import io
import logging
from datetime import datetime

log = logging.getLogger("export")

CSV_COLUMNS = ["n", "camera_id", "name", "lat", "lon", "pts", "kind", "band",
               "implied_speed_kmh", "flag", "sightings"]


def to_csv(route):
    """One row per hop, plus a header block that keeps the export self-describing."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["# plate", route["plate"]])
    writer.writerow(["# window", route["from"], route["to"]])
    writer.writerow(["# match", "fuzzy - verify plate" if route["fuzzy"] else "exact"])
    writer.writerow(["# geometry", "road-snapped" if route.get("snapped") else "straight-line"])
    writer.writerow([])
    writer.writerow(CSV_COLUMNS)
    for hop in route["hops"]:
        writer.writerow([hop.get(column) for column in CSV_COLUMNS])
    return buffer.getvalue().encode("utf-8")


def _schematic(hops, width, height):
    """A reportlab Drawing of the path: dots in order, joined, north up. No basemap."""
    from reportlab.graphics.shapes import Circle, Drawing, Line, String

    points = [(h["lon"], h["lat"]) for h in hops if h["lat"] is not None and h["lon"] is not None]
    drawing = Drawing(width, height)
    if len(points) < 2:
        drawing.add(String(4, height / 2, "no coordinates for these cameras", fontSize=8))
        return drawing

    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    span_lon = max(max(lons) - min(lons), 1e-6)
    span_lat = max(max(lats) - min(lats), 1e-6)
    pad = 12

    def place(lon, lat):
        x = pad + (lon - min(lons)) / span_lon * (width - 2 * pad)
        y = pad + (lat - min(lats)) / span_lat * (height - 2 * pad)
        return x, y

    placed = [place(lon, lat) for lon, lat in points]
    for (x1, y1), (x2, y2) in zip(placed, placed[1:]):
        drawing.add(Line(x1, y1, x2, y2, strokeWidth=1))
    for index, (x, y) in enumerate(placed, start=1):
        drawing.add(Circle(x, y, 3, fillColor=None))
        drawing.add(String(x + 5, y + 3, str(index), fontSize=7))
    return drawing


def to_pdf(route):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, title=f"Route {route['plate']}",
                                 leftMargin=18 * mm, rightMargin=18 * mm,
                                 topMargin=16 * mm, bottomMargin=16 * mm)

    story = [Paragraph(f"Route reconstruction — {route['plate']}", styles["Title"])]
    story.append(Paragraph(f"Window: {route['from']} to {route['to']}", styles["Normal"]))
    story.append(Paragraph(
        "Match: fuzzy — <b>verify plate before acting</b>" if route["fuzzy"] else "Match: exact",
        styles["Normal"]))
    story.append(Paragraph(
        "Geometry: road-snapped" if route.get("snapped")
        else "Geometry: straight lines between cameras (no routing service available)",
        styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    header = ["#", "Camera", "Seen at", "Band", "Implied km/h", "Flag"]
    body = [[hop["n"], f"{hop['name'] or hop['camera_id']}\n{hop['camera_id']}", hop["pts"],
             hop["band"] or "-",
             "-" if hop["implied_speed_kmh"] is None else hop["implied_speed_kmh"],
             hop["flag"] or ""] for hop in route["hops"]]
    table = Table([header] + body, repeatRows=1,
                  colWidths=[10 * mm, 55 * mm, 45 * mm, 22 * mm, 25 * mm, 25 * mm])
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#22303f")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 8),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b8c0"))]
    for index, hop in enumerate(route["hops"], start=1):
        if hop["flag"] == "IMPLAUSIBLE":
            # Shown, not hidden: a route with one doubtful hop is better evidence than four
            # suspiciously perfect ones.
            style.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#ffe4b5")))
    table.setStyle(TableStyle(style))
    story.append(table)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Path schematic (order and shape only — not a map)", styles["Heading4"]))
    story.append(_schematic(route["hops"], 160 * mm, 70 * mm))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"Generated {datetime.now().isoformat(timespec='seconds')} · "
        "every export is recorded in the audit log.", styles["Italic"]))

    document.build(story)
    return buffer.getvalue()


def render(route, fmt="csv"):
    """Returns (bytes, content type)."""
    if fmt == "csv":
        return to_csv(route), "text/csv"
    if fmt == "pdf":
        return to_pdf(route), "application/pdf"
    raise ValueError(f"unsupported export format: {fmt!r}")


def record_export(store, route, fmt, user_id=None, dept_id=None, ip=None):
    """Write the audit row for an export. Returns the row's hash.

    Deliberately not optional and not best-effort: if the audit write fails, the export fails.
    An export nobody can account for afterwards is the thing an inquiry looks for.
    """
    from alerts import append_audit

    with store.conn as conn, conn.cursor() as cur:
        return append_audit(
            cur, user_id=user_id, dept_id=dept_id, action="route.export",
            object_type="route", object_id=route["plate"], ip=ip,
            reason=f"{fmt} export, {len(route['hops'])} hop(s), "
                   f"{'fuzzy' if route['fuzzy'] else 'exact'} match, "
                   f"window {route['from']} to {route['to']}")
