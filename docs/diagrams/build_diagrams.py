"""Generate the two submission diagrams as self-contained SVG.

    python docs/diagrams/build_diagrams.py

Written as a generator rather than hand-authored SVG because the layout is arithmetic:
chip widths follow their text, rows follow their chips, and one changed label used to mean
half an hour of nudging coordinates. Both outputs are 16:9 so they drop into the deck
full-bleed and print to a landscape page without letterboxing.

The rule these diagrams follow: a diagram is a picture, not a paragraph. Anything that needs a
sentence to explain it belongs in the HLD, not on the canvas.
"""

import io
from pathlib import Path

OUT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- palette
INK, INK2, INK3 = "#1b1f27", "#454b57", "#6b7280"
LINE, LINE2 = "#d3d7dd", "#b6bcc6"
GROUND, SURF, SURF2 = "#f4f5f7", "#ffffff", "#eceef1"
ACC, ACC_BG, ACC_LN = "#b5731a", "#f7ead6", "#d9a45e"
OK, OK_BG, OK_LN = "#1f7a3d", "#e3f2e6", "#7cb98d"
CRIT, CRIT_BG, CRIT_LN = "#b23020", "#f6e3df", "#d29184"

FONT = "'IBM Plex Sans','Segoe UI',Helvetica,Arial,sans-serif"
MONO = "'IBM Plex Mono',Consolas,monospace"

# ---------------------------------------------------------------- icons
# Each icon is drawn inside a 0 0 24 24 box so <use> can scale it to any tile size.
ICONS = {
    "camera": """<path d="M3 7.5 17 4.2a1 1 0 0 1 1.2.7l1 3.6a1 1 0 0 1-.7 1.2L4.6 13.4a1 1 0 0 1-1.2-.7l-1-3.6a1 1 0 0 1 .6-1.6z"/>
                 <circle cx="16.4" cy="8.2" r="1.5" fill="#fff"/>
                 <path d="M6 13.9 7 17M11 10.5v10M8.6 20.5h4.8"/>""",
    "hub": """<circle cx="12" cy="12" r="3.3"/>
              <circle cx="3.6" cy="5" r="2.1"/><circle cx="20.4" cy="5" r="2.1"/>
              <circle cx="3.6" cy="19" r="2.1"/><circle cx="20.4" cy="19" r="2.1"/>
              <path d="M5.2 6.4 9.6 10M18.8 6.4 14.4 10M5.2 17.6 9.6 14M18.8 17.6 14.4 14"/>""",
    "chip": """<rect x="6" y="6" width="12" height="12" rx="2.2"/>
               <rect x="9.4" y="9.4" width="5.2" height="5.2" rx="1"/>
               <path d="M9.5 6V3M14.5 6V3M9.5 21v-3M14.5 21v-3M6 9.5H3M6 14.5H3M21 9.5h-3M21 14.5h-3"/>""",
    "stream": """<path d="M2.5 7h12"/><path d="M12 4.2 15.3 7 12 9.8"/>
                 <path d="M21.5 12h-12"/><path d="M12 9.2 8.7 12 12 14.8"/>
                 <path d="M2.5 17h12"/><path d="M12 14.2 15.3 17 12 19.8"/>""",
    "db": """<ellipse cx="12" cy="5.6" rx="8" ry="3.1"/>
             <path d="M4 5.6v12.8c0 1.7 3.6 3.1 8 3.1s8-1.4 8-3.1V5.6"/>
             <path d="M4 12c0 1.7 3.6 3.1 8 3.1s8-1.4 8-3.1"/>""",
    "monitor": """<rect x="2.5" y="3.5" width="19" height="13" rx="1.8"/>
                  <path d="M9 20.5h6M12 16.5v4"/>
                  <path d="M6.5 12.5 9.5 9l2.5 2.6L15 7.5l2.5 3.4"/>""",
    "shield": """<path d="M12 2.6 20 5.6v6.1c0 4.6-3.3 8.6-8 9.7-4.7-1.1-8-5.1-8-9.7V5.6z"/>
                 <path d="M8.6 12.2 11 14.6l4.6-4.8"/>""",
    "chain": """<path d="M9.6 14.4a4.2 4.2 0 0 1 0-5.9l2.4-2.4a4.2 4.2 0 0 1 5.9 5.9l-1.3 1.3"/>
                <path d="M14.4 9.6a4.2 4.2 0 0 1 0 5.9l-2.4 2.4a4.2 4.2 0 1 1-5.9-5.9l1.3-1.3"/>""",
    "clock": """<circle cx="12" cy="12" r="8.6"/><path d="M12 6.8V12l3.4 2.1"/>""",
    "open": """<circle cx="12" cy="12" r="8.6"/><path d="M3.6 12h16.8"/>
               <path d="M12 3.4a13 13 0 0 1 0 17.2 13 13 0 0 1 0-17.2z"/>""",
    "pin": """<path d="M12 21.5c4.2-5.3 6.4-9 6.4-11.5a6.4 6.4 0 1 0-12.8 0c0 2.5 2.2 6.2 6.4 11.5z"/>
              <circle cx="12" cy="10" r="2.4"/>""",
    "bell": """<path d="M6.2 16.4V10.6a5.8 5.8 0 0 1 11.6 0v5.8l1.8 2.3H4.4z"/>
               <path d="M9.8 21.4h4.4"/>""",
    "route": """<circle cx="5.4" cy="18.6" r="2.6"/><circle cx="18.6" cy="5.4" r="2.6"/>
                <path d="M8 18.6h5.8a4.4 4.4 0 0 0 0-8.8H10a4.4 4.4 0 0 1 0-8.8"/>""",
    "user": """<circle cx="12" cy="8" r="3.9"/><path d="M4.6 20.8a7.4 7.4 0 0 1 14.8 0"/>""",
    "eye": """<path d="M1.8 12S5.6 5.4 12 5.4 22.2 12 22.2 12 18.4 18.6 12 18.6 1.8 12 1.8 12z"/>
              <circle cx="12" cy="12" r="3"/>""",
    "ban": """<circle cx="12" cy="12" r="8.6"/><path d="M6 18 18 6"/>""",
    "box": """<path d="M12 2.8 21 7.4v9.2L12 21.2 3 16.6V7.4z"/><path d="M3 7.4 12 12l9-4.6M12 12v9.2"/>""",
}


def defs():
    out = ['<defs>']
    for name, body in ICONS.items():
        out.append('<g id="i-%s" fill="none" stroke="currentColor" stroke-width="1.6" '
                   'stroke-linecap="round" stroke-linejoin="round">%s</g>' % (name, body))
    for mid, col in (("a", INK3), ("b", ACC), ("c", OK), ("d", CRIT)):
        out.append('<marker id="m%s" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" '
                   'markerHeight="7" orient="auto-start-reverse">'
                   '<path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker>' % (mid, col))
    out.append('</defs>')
    return "\n".join(out)


def icon(name, x, y, size=24, colour=INK):
    """Place an icon with its top-left at (x, y), scaled to `size`."""
    k = size / 24.0
    return ('<g transform="translate(%g %g) scale(%g)" color="%s" stroke-width="%g">'
            '<use href="#i-%s"/></g>' % (x, y, k, colour, 1.7 / k, name))


def txt(x, y, s, size=14, fill=INK, weight=400, family=FONT, anchor="start",
        style="", spacing=""):
    extra = ""
    if style:
        extra += ' font-style="%s"' % style
    if spacing:
        extra += ' letter-spacing="%s"' % spacing
    return ('<text x="%g" y="%g" font-size="%g" fill="%s" font-weight="%s" font-family="%s" '
            'text-anchor="%s"%s>%s</text>' % (x, y, size, fill, weight, family, anchor, extra, s))


def rect(x, y, w, h, fill=SURF, stroke=LINE, rx=10, sw=1.4, dash=""):
    d = ' stroke-dasharray="%s"' % dash if dash else ""
    return ('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" stroke="%s" '
            'stroke-width="%g"%s/>' % (x, y, w, h, rx, fill, stroke, sw, d))


CHIP_H = 24


def chip_w(label, size=12.0):
    return len(label) * size * 0.60 + 20


def chip(x, y, label, size=12.0, fill=SURF2, stroke=LINE, ink=INK2):
    w = chip_w(label, size)
    return (rect(x, y, w, CHIP_H, fill, stroke, rx=6, sw=1.1) +
            txt(x + w / 2.0, y + 16.5, label, size, ink, 500, MONO, "middle")), w


def chip_row(x, y, labels, maxw, size=12.0, fill=SURF2, stroke=LINE, ink=INK2, gap=7):
    """Lay chips out left to right, wrapping inside `maxw`. Returns (svg, height)."""
    out, cx, cy = [], x, y
    for label in labels:
        w = chip_w(label, size)
        if cx > x and cx + w > x + maxw:
            cx, cy = x, cy + CHIP_H + gap
        svg, w = chip(cx, cy, label, size, fill, stroke, ink)
        out.append(svg)
        cx += w + gap
    return "\n".join(out), cy + CHIP_H - y


def arrow(x1, y1, x2, y2, colour=INK3, mid="a", w=2.4, dash=""):
    d = ' stroke-dasharray="%s"' % dash if dash else ""
    return ('<path d="M%g %g L%g %g" stroke="%s" stroke-width="%g" fill="none" '
            'marker-end="url(#m%s)"%s/>' % (x1, y1, x2, y2, colour, w, mid, d))


# ================================================================ architecture
def architecture():
    W, H = 1760, 990
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
         'font-family="%s">' % (W, H, W, H, FONT),
         '<title>Prahari — system architecture</title>',
         '<desc>Five stages from the department camera estate to the operator console. Video is '
         'decoded at the edge and never crosses into the platform; a ~200-byte sighting does.</desc>',
         defs(),
         rect(0, 0, W, H, GROUND, GROUND, rx=0, sw=0)]

    p.append(txt(48, 54, "Prahari — system architecture", 28, INK, 800))
    p.append(txt(48, 82, "Hybrid M1 + M2 + M3 · open source · no vendor lock-in", 15, INK3))

    # ---- badge: the thesis
    p.append(rect(1256, 30, 456, 60, ACC_BG, ACC_LN, rx=10))
    p.append(icon("ban", 1274, 44, 30, CRIT))
    p.append(txt(1316, 56, "Video never leaves the department", 15, INK, 600))
    p.append(txt(1316, 77, "A ~200-byte sighting is the only thing that does.", 12.5, INK2))

    # ---- source strip
    SY = 112
    p.append(rect(48, SY, 1664, 118, SURF, LINE))
    p.append(txt(70, SY + 28, "26 GOVERNMENT DEPARTMENTS · EXISTING VMS UNTOUCHED",
                 13, ACC, 700, spacing="0.12em"))
    depts = [("Traffic", "RTSP·TCP"), ("Law &amp; Order", "ONVIF"), ("RTO / GSRTC", "HLS"),
             ("Municipal", "RTSP·H.265"), ("Panchayat", "RTSP"), ("Civil supplies", "vendor SDK"),
             ("Health", "vendor SDK")]
    tw, gap = 218, 15
    for n, (name, proto) in enumerate(depts):
        x = 70 + n * (tw + gap)
        p.append(rect(x, SY + 40, tw, 58, SURF2, LINE, rx=8, sw=1.1))
        p.append(icon("camera", x + 12, SY + 55, 28, ACC))
        p.append(txt(x + 50, SY + 66, name, 13.5, INK, 600))
        p.append(txt(x + 50, SY + 86, proto, 11.5, INK3, 400, MONO))

    p.append(arrow(198, SY + 118, 198, SY + 168, INK3))

    # ---- the five stages
    CY, CH = 286, 330
    cw, cgap = 300, 41
    x0 = 48
    stages = [
        ("hub", "Federation gateway", "one interface, four transports",
         ["rtsp · TCP", "hls", "onvif", "vms-stub"],
         "probes each camera · degrades per camera · frame watchdog", ACC),
        ("chip", "Edge inference", "runs where the cameras are",
         ["YOLOv8s", "ByteTrack", "YOLOv9-t", "OCR vote ×4"],
         "decode 5 fps · one record per track, not per frame", ACC),
        ("stream", "Sighting bus", "~200 bytes · contract C1",
         ["sightings", "alerts", "camera.health"],
         "two consumer groups · replay on failure", INK3),
        ("db", "Store &amp; correlate", "Postgres 16 · TimescaleDB",
         ["hypertable", "pgvector", "pg_trgm", "MinIO", "matcher"],
         "canon → trigram → Levenshtein · dedup 60 s", INK3),
        ("monitor", "API &amp; console", "FastAPI · Leaflet",
         ["REST", "WebSocket", "RBAC C10", "audit chain"],
         "map · video wall · trace · alerts · export", INK3),
    ]
    for n, (ic, title, sub, chips, foot, accent) in enumerate(stages):
        x = x0 + n * (cw + cgap)
        head = ACC_BG if n < 2 else SURF2
        p.append(rect(x, CY, cw, CH, SURF, LINE2 if n < 2 else LINE, rx=12, sw=1.6))
        p.append(rect(x, CY, cw, 108, head, "none", rx=12, sw=0))
        p.append(rect(x, CY + 96, cw, 12, head, "none", rx=0, sw=0))
        p.append(icon(ic, x + 22, CY + 22, 46, ACC if n < 2 else INK2))
        p.append(txt(x + 22, CY + 92, "0%d" % (n + 1), 34, ACC_LN if n < 2 else "#c3c9d2", 800, MONO, "start"))
        p.append(txt(x + cw - 22, CY + 52, title, 17, INK, 700, FONT, "end"))
        p.append(txt(x + cw - 22, CY + 74, sub, 12.5, INK2, 400, FONT, "end"))
        body, _h = chip_row(x + 22, CY + 130, chips, cw - 44,
                            fill=SURF if n < 2 else SURF2)
        p.append(body)
        p.append('<path d="M%g %g H%g" stroke="%s" stroke-width="1.2"/>'
                 % (x + 22, CY + CH - 74, x + cw - 22, LINE))
        # foot text, wrapped by hand at the middle dot nearest the centre
        words, line, lines = foot.split(" "), "", []
        for w_ in words:
            if len(line + " " + w_) > 36:
                lines.append(line)
                line = w_
            else:
                line = (line + " " + w_).strip()
        lines.append(line)
        for li, ln in enumerate(lines[:3]):
            p.append(txt(x + 22, CY + CH - 50 + li * 17, ln, 12, INK3))
        if n < len(stages) - 1:
            p.append(arrow(x + cw + 6, CY + CH / 2, x + cw + cgap - 6, CY + CH / 2,
                           ACC if n < 2 else INK3, "b" if n < 2 else "a"))

    # ---- the video boundary, between edge inference and the bus
    bx = x0 + 2 * (cw + cgap) - cgap / 2
    p.append('<path d="M%g %g V%g" stroke="%s" stroke-width="2.2" stroke-dasharray="7 6"/>'
             % (bx, CY - 12, CY + CH + 30, CRIT))
    p.append(rect(bx - 178, CY - 50, 356, 36, CRIT_BG, CRIT_LN, rx=8, sw=1.2))
    p.append(icon("ban", bx - 168, CY - 44, 22, CRIT))
    p.append(txt(bx - 138, CY - 26, "VIDEO STOPS HERE — frames are discarded",
                 13, CRIT, 700))

    # ---- cross-cutting band
    BY = 664
    p.append(rect(48, BY, 1090, 124, SURF, LINE))
    p.append(txt(70, BY + 28, "ACROSS EVERY STAGE", 13, ACC, 700, spacing="0.12em"))
    cross = [("shield", "RBAC enforced in SQL", "the admin cannot watch"),
             ("chain", "Hash-chained audit", "reads logged, not just writes"),
             ("clock", "Retention 90 / 30 days", "a database policy"),
             ("open", "Open source", "no vendor lock-in")]
    for n, (ic, a, b) in enumerate(cross):
        x = 70 + n * 262
        p.append(icon(ic, x, BY + 52, 30, ACC))
        p.append(txt(x + 42, BY + 66, a, 13.5, INK, 600))
        p.append(txt(x + 42, BY + 86, b, 11.5, INK3))

    # ---- externals
    p.append(rect(1160, BY, 552, 124, SURF, LINE))
    p.append(txt(1182, BY + 28, "EXTERNAL INTERFACES", 13, ACC, 700, spacing="0.12em"))
    ext = [("VAHAN · SARTHI", "stub"), ("e-GujCop · AFIS", "stub"),
           ("OSRM", "live"), ("chrony", "live")]
    for n, (name, state) in enumerate(ext):
        x = 1182 + (n % 2) * 268
        y = BY + 50 + (n // 2) * 38
        col = ACC_BG if state == "stub" else OK_BG
        ln = ACC_LN if state == "stub" else OK_LN
        p.append(rect(x, y, 250, 26, col, ln, rx=6, sw=1.1))
        p.append(txt(x + 12, y + 18, name, 12.5, INK, 600))
        p.append(txt(x + 238, y + 18, state, 11, ACC if state == "stub" else OK, 600, MONO, "end"))

    # ---- outcome strip
    OY = 818
    p.append(rect(48, OY, 1664, 124, SURF, LINE))
    p.append(txt(70, OY + 28, "WHAT AN OFFICER GETS", 13, ACC, 700, spacing="0.12em"))
    outs = [("pin", "GIS map of the estate", "live health per camera"),
            ("bell", "Watchlist alert, pushed", "no polling, no refresh"),
            ("route", "Route across departments", "ordered, timestamped, flagged"),
            ("box", "CSV / PDF export", "never without an audit row"),
            ("eye", "Every lookup on the record", "including who looked")]
    for n, (ic, a, b) in enumerate(outs):
        x = 70 + n * 330
        p.append(icon(ic, x, OY + 52, 30, OK))
        p.append(txt(x + 42, OY + 66, a, 13.5, INK, 600))
        p.append(txt(x + 42, OY + 86, b, 11.5, INK3))

    p.append('</svg>')
    return "\n".join(p)


# ================================================================ workflow
def workflow():
    W, H = 1760, 990
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
         'font-family="%s">' % (W, H, W, H, FONT),
         '<title>Prahari — workflow and integration</title>',
         '<desc>Two paths: a vehicle passing a camera through to an acknowledged alert, and a '
         'registration number through to an audited route export.</desc>',
         defs(),
         rect(0, 0, W, H, GROUND, GROUND, rx=0, sw=0)]

    p.append(txt(48, 54, "Prahari — workflow &amp; integration", 28, INK, 800))
    p.append(txt(48, 82, "Two paths. Both end on the same hash-chained audit log.", 15, INK3))

    def path_row(y, tag, tagsub, steps, tone):
        col = {"a": (ACC, ACC_BG, ACC_LN, "b"), "c": (OK, OK_BG, OK_LN, "c")}[tone]
        accent, bg, ln, mid = col
        out = [rect(48, y, 1664, 300, SURF, LINE)]
        out.append(rect(48, y, 1664, 44, INK, INK, rx=12, sw=0))
        out.append(rect(48, y + 32, 1664, 12, INK, INK, rx=0, sw=0))
        out.append(txt(70, y + 29, tag, 15, "#e0a24a", 700, FONT, "start", spacing="0.06em"))
        out.append(txt(1690, y + 29, tagsub, 13, "#9aa1ad", 400, FONT, "end"))

        n = len(steps)
        cw, gap = 178, 30
        total = n * cw + (n - 1) * gap
        x0 = 48 + (1664 - total) / 2.0
        for i, (ic, title, chips, hot) in enumerate(steps):
            x = x0 + i * (cw + gap)
            fill = bg if hot else SURF2
            edge = ln if hot else LINE
            out.append(rect(x, y + 76, cw, 202, fill, edge, rx=11, sw=1.5))
            out.append('<circle cx="%g" cy="%g" r="15" fill="%s"/>' % (x + 26, y + 102, accent))
            out.append(txt(x + 26, y + 107, str(i + 1), 14, "#ffffff", 800, FONT, "middle"))
            out.append(icon(ic, x + cw - 68, y + 86, 46, accent if hot else INK2))
            # title, wrapped to two lines at width ~20 chars
            words, line, lines = title.split(" "), "", []
            for w_ in words:
                if len(line + " " + w_) > 19:
                    lines.append(line)
                    line = w_
                else:
                    line = (line + " " + w_).strip()
            lines.append(line)
            for li, lnn in enumerate(lines[:3]):
                out.append(txt(x + 16, y + 156 + li * 21, lnn, 14.5, INK, 700))
            body, _h = chip_row(x + 16, y + 156 + len(lines[:3]) * 21 + 8, chips, cw - 32,
                                size=11.0, fill=SURF if hot else SURF)
            out.append(body)
            if i < n - 1:
                out.append(arrow(x + cw + 5, y + 177, x + cw + gap - 5, y + 177, accent, mid, 2.6))
        return "\n".join(out)

    p.append(path_row(
        112, "A · VEHICLE  →  ACKNOWLEDGED ALERT",
        "measured 0.68 s frame to sighting, against a 3.0 s budget",
        [("camera", "Vehicle passes a camera", ["frame PTS"], True),
         ("chip", "Detect, track, read the plate", ["YOLO", "OCR ×4"], True),
         ("shield", "Band it — or refuse it", ["CONFIRMED", "UNREADABLE"], True),
         ("stream", "Sighting on the bus", ["~200 B", "C1"], False),
         ("db", "Match against watchlist", ["canon", "dedup 60 s"], False),
         ("bell", "Alert pushed to console", ["WebSocket", "scoped"], False),
         ("user", "Officer acknowledges", ["by name", "409 on illegal"], False),
         ("chain", "Audit row appended", ["sha256 chain"], False)], "a"))

    p.append(path_row(
        442, "B · REGISTRATION NUMBER  →  AUDITED ROUTE",
        "the graded test case",
        [("user", "Investigator types a plate", ["GJ01DM0042"], True),
         ("shield", "Capability and scope", ["C10", "403 or rows"], True),
         ("db", "Hypertable query", ["by pts_first"], False),
         ("route", "Hops, in order", ["one per camera"], False),
         ("ban", "Impossible hop flagged", ["&gt;150 km/h"], True),
         ("pin", "Snapped to roads", ["OSRM"], False),
         ("box", "CSV / PDF export", ["presigned crops"], False),
         ("chain", "Audit row appended", ["no export without"], False)], "c"))

    # ---- the two rules
    RY = 776
    p.append(rect(48, RY, 820, 150, ACC_BG, ACC_LN))
    p.append(icon("ban", 74, RY + 34, 44, CRIT))
    p.append(txt(136, RY + 56, "Never print a plate it cannot read", 19, INK, 700))
    p.append(txt(136, RY + 86, "Below the pixel floor, or with the readers in disagreement, it says so.", 13.5, INK2))
    p.append(txt(136, RY + 108, "A wrong plate on a police report is worse than no plate.", 13.5, INK2))

    p.append(rect(892, RY, 820, 150, ACC_BG, ACC_LN))
    p.append(icon("eye", 918, RY + 34, 44, CRIT))
    p.append(txt(980, RY + 56, "The account that configures it cannot watch through it", 19, INK, 700))
    p.append(txt(980, RY + 86, "SYSTEM_ADMIN holds config and audit, and is refused live data, alerts and route.", 13.5, INK2))
    p.append(txt(980, RY + 108, "Administering a surveillance system and using one are different jobs.", 13.5, INK2))

    p.append('</svg>')
    return "\n".join(p)


if __name__ == "__main__":
    for name, svg in (("architecture", architecture()), ("workflow", workflow())):
        f = OUT / ("%s.svg" % name)
        io.open(f, "w", encoding="utf-8").write(svg)
        print("wrote %s (%d bytes)" % (f.name, len(svg)))
