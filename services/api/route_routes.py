"""Cross-camera route reconstruction — the platform's answer to gate G3.

On evaluation day a judge supplies a vehicle registration number, and the
platform must produce where that vehicle went: an ordered, timestamped,
location-wise route across the camera network, exportable as a report.

How a route is assembled:

1. **Sightings, not detections.** A vehicle sitting in frame for 200 frames is
   one sighting of one vehicle, not 200. Detection rows are collapsed by
   (camera, track id) into a single sighting with a first/last time, the best
   plate read on that track, and the best-confidence frame as evidence.
2. **One clock.** Sighting times come from the worker's `observed_at`, which is
   stream PTS anchored to the wall clock after the connect burst has passed
   (CONTEXT.md D14). Raw PTS cannot order sightings across cameras because its
   origin is per-stream, and the burned-in overlay runs backwards on loop.
3. **Plate matching is delegated.** Fuzzy plate matching belongs to the plate
   lane (ROLES.md). This module asks for a matcher and falls back to a plain
   normalised comparison if the richer one is not present yet.
4. **Physical plausibility.** Consecutive sightings imply a speed: road
   distance over elapsed time. A pair implying a speed no vehicle achieves is
   evidence the plate read was wrong, not that the car teleported, so the hop
   is flagged and can be dropped. This is what stops one bad OCR read from
   drawing a line across the state.

Endpoints:
    GET /api/route?plate=GJ01AB1234           reconstructed route + hops
    GET /api/route/export.csv?plate=...       the report artifact judges asked for
    GET /api/route/coverage                   which cameras have usable data
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]

# Overridable so a synthetic fixture set can be exercised without ever mixing
# fabricated rows into real captured detections.
DETECTIONS_DIR = Path(
    os.environ.get("PRAHARI_DETECTIONS_DIR", str(ROOT / "data" / "detections"))
)
GEO_FILE = ROOT / "data" / "camera_geo.json"

# A vehicle cannot plausibly average more than this between two cameras on
# Gujarat roads. Above it, the pairing is far more likely to be a bad plate read.
DEFAULT_MAX_SPEED_KMH = 120.0

# Two sightings of the same plate on the same camera closer than this are the
# same pass, not two visits.
SAME_PASS_SECONDS = 30.0


def _normalise_plate(text: str) -> str:
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _plate_matches(query: str, candidate: str, max_distance: int) -> tuple[bool, float]:
    """Return (matched, distance).

    Fuzzy plate matching with confusion-class weighting is the plate lane's
    responsibility (ROLES.md §3). If that matcher exists, use it; otherwise fall
    back to plain edit distance so route reconstruction is testable today and
    improves for free when the better matcher lands.
    """
    q, c = _normalise_plate(query), _normalise_plate(candidate)
    if not q or not c:
        return False, 99.0
    try:
        from services.api.plate_routes import weighted_plate_distance  # type: ignore
        dist = float(weighted_plate_distance(q, c))
    except Exception:
        dist = float(_levenshtein(q, c))
    return dist <= max_distance, dist


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Sighting:
    camera_id: str
    track_id: int
    plate: str
    plate_distance: float
    vehicle_class: str
    first_seen: float
    last_seen: float
    best_conf: float
    n_rows: int
    time_source: str          # "anchored" (usable across cameras) or "pts_only"
    lat: float | None = None
    lon: float | None = None
    location: str | None = None
    geo_precision: str | None = None


@dataclass
class TrackAccumulator:
    camera_id: str
    track_id: int
    plates: dict[str, int] = field(default_factory=dict)
    first_seen: float = math.inf
    last_seen: float = -math.inf
    best_conf: float = 0.0
    vehicle_class: str = "vehicle"
    n_rows: int = 0
    anchored: bool = False


def _load_geo() -> dict:
    if not GEO_FILE.exists():
        return {}
    try:
        return json.loads(GEO_FILE.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _iter_detection_rows(camera_ids: Iterable[str] | None = None):
    if not DETECTIONS_DIR.exists():
        return
    for path in sorted(DETECTIONS_DIR.glob("cam_*.jsonl")):
        cam_id = path.stem.replace("cam_", "")
        if camera_ids is not None and cam_id not in camera_ids:
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield cam_id, json.loads(line)
                    except ValueError:
                        continue  # a partially flushed final line
        except OSError:
            continue


def collapse_to_sightings(since: float | None = None) -> dict[tuple[str, int], TrackAccumulator]:
    """Collapse detection rows into one accumulator per (camera, track)."""
    tracks: dict[tuple[str, int], TrackAccumulator] = {}

    for cam_id, row in _iter_detection_rows():
        track_id = row.get("track_id")
        if track_id is None:
            continue

        observed = row.get("observed_at")
        anchored = observed is not None
        if not anchored:
            # Rows written before the shared timeline existed. Keep them for
            # per-camera evidence but never let them drive cross-camera timing.
            observed = row.get("pts_seconds") or 0.0
        if since is not None and anchored and observed < since:
            continue

        key = (cam_id, int(track_id))
        acc = tracks.get(key)
        if acc is None:
            acc = TrackAccumulator(camera_id=cam_id, track_id=int(track_id))
            tracks[key] = acc

        acc.n_rows += 1
        acc.anchored = acc.anchored or anchored
        acc.first_seen = min(acc.first_seen, float(observed))
        acc.last_seen = max(acc.last_seen, float(observed))
        conf = float(row.get("conf") or 0.0)
        if conf > acc.best_conf:
            acc.best_conf = conf
            acc.vehicle_class = row.get("class") or acc.vehicle_class

        plate = row.get("plate")
        if plate:
            acc.plates[plate] = acc.plates.get(plate, 0) + 1

    return tracks


def find_sightings(plate_query: str, max_distance: int, since: float | None) -> list[Sighting]:
    geo = _load_geo()
    out: list[Sighting] = []

    for (cam_id, track_id), acc in collapse_to_sightings(since).items():
        if not acc.plates:
            continue
        # The plate for a track is the most-voted read on that track.
        best_plate = max(acc.plates.items(), key=lambda kv: kv[1])[0]
        matched, dist = _plate_matches(plate_query, best_plate, max_distance)
        if not matched:
            continue

        pos = geo.get(cam_id, {})
        out.append(
            Sighting(
                camera_id=cam_id,
                track_id=track_id,
                plate=best_plate,
                plate_distance=dist,
                vehicle_class=acc.vehicle_class,
                first_seen=acc.first_seen,
                last_seen=acc.last_seen,
                best_conf=acc.best_conf,
                n_rows=acc.n_rows,
                time_source="anchored" if acc.anchored else "pts_only",
                lat=pos.get("lat"),
                lon=pos.get("lon"),
                location=pos.get("label"),
                geo_precision=pos.get("precision"),
            )
        )

    out.sort(key=lambda s: s.first_seen)
    return out


def dedupe_same_pass(sightings: list[Sighting]) -> list[Sighting]:
    """Collapse repeat sightings of one vehicle on one camera within a pass.

    A vehicle waiting at a signal can pick up more than one track id when it is
    briefly occluded; those are one visit to that camera, not several.
    """
    kept: list[Sighting] = []
    for s in sightings:
        merged = False
        for k in kept:
            if k.camera_id == s.camera_id and abs(s.first_seen - k.last_seen) <= SAME_PASS_SECONDS:
                k.last_seen = max(k.last_seen, s.last_seen)
                k.n_rows += s.n_rows
                k.best_conf = max(k.best_conf, s.best_conf)
                merged = True
                break
        if not merged:
            kept.append(s)
    return kept


def build_hops(sightings: list[Sighting], max_speed_kmh: float) -> list[dict]:
    """Link consecutive sightings and judge whether each hop is physically possible."""
    hops: list[dict] = []
    for prev, nxt in zip(sightings, sightings[1:]):
        hop = {
            "from_camera": prev.camera_id,
            "to_camera": nxt.camera_id,
            "from_location": prev.location,
            "to_location": nxt.location,
            "departed_at": prev.last_seen,
            "arrived_at": nxt.first_seen,
            "gap_seconds": round(nxt.first_seen - prev.last_seen, 1),
            "distance_km": None,
            "implied_speed_kmh": None,
            "plausible": True,
            "note": None,
        }

        if prev.time_source != "anchored" or nxt.time_source != "anchored":
            hop["plausible"] = True
            hop["note"] = "timing not anchored; speed not evaluated"
            hops.append(hop)
            continue

        if None in (prev.lat, prev.lon, nxt.lat, nxt.lon):
            hop["note"] = "camera position unknown; speed not evaluated"
            hops.append(hop)
            continue

        dist = haversine_km(prev.lat, prev.lon, nxt.lat, nxt.lon)
        hop["distance_km"] = round(dist, 2)
        dt_hours = max(hop["gap_seconds"], 1.0) / 3600.0
        speed = dist / dt_hours
        hop["implied_speed_kmh"] = round(speed, 1)

        if speed > max_speed_kmh:
            hop["plausible"] = False
            hop["note"] = (
                f"implies {speed:.0f} km/h over {dist:.1f} km — "
                "more likely a mismatched plate read than this vehicle"
            )
        elif prev.geo_precision in ("approximate", "curated") or \
                nxt.geo_precision in ("approximate", "curated"):
            hop["note"] = "distance approximate: camera position not ground-verified"

        hops.append(hop)
    return hops


def _reachable(a: Sighting, b: Sighting, max_speed_kmh: float) -> bool:
    """Could one vehicle be at a and later at b?"""
    if a.time_source != "anchored" or b.time_source != "anchored":
        return True  # cannot judge without a shared clock; do not discard
    if None in (a.lat, a.lon, b.lat, b.lon):
        return True  # cannot judge without positions
    gap = b.first_seen - a.last_seen
    if gap < 0:
        return False
    km = haversine_km(a.lat, a.lon, b.lat, b.lon)
    return km / (max(gap, 1.0) / 3600.0) <= max_speed_kmh


def largest_consistent_subset(sightings: list[Sighting], max_speed_kmh: float) -> list[Sighting]:
    """Keep the biggest set of sightings that one vehicle could actually produce.

    Deleting "the sighting that caused the bad hop" is ambiguous — a bad hop
    implicates two sightings and there is no local way to tell which is the
    impostor. Framed globally the question has one answer: find the longest
    chain, in time order, where every consecutive pair is physically reachable.
    A single spurious match cannot join that chain, while a genuine route of
    five cameras will.

    Ties break toward exact plate matches, so a fuzzy read never displaces an
    exact one of equal chain length.
    """
    n = len(sightings)
    if n < 3:
        return sightings

    best_len = [1] * n
    best_score = [-s.plate_distance for s in sightings]
    prev = [-1] * n

    for j in range(n):
        for i in range(j):
            if not _reachable(sightings[i], sightings[j], max_speed_kmh):
                continue
            cand_len = best_len[i] + 1
            cand_score = best_score[i] - sightings[j].plate_distance
            if (cand_len, cand_score) > (best_len[j], best_score[j]):
                best_len[j] = cand_len
                best_score[j] = cand_score
                prev[j] = i

    end = max(range(n), key=lambda i: (best_len[i], best_score[i]))
    chain: list[Sighting] = []
    while end != -1:
        chain.append(sightings[end])
        end = prev[end]
    chain.reverse()
    return chain


def _serialise(s: Sighting) -> dict:
    return {
        "camera_id": s.camera_id,
        "location": s.location,
        "lat": s.lat,
        "lon": s.lon,
        "geo_precision": s.geo_precision,
        "plate_read": s.plate,
        "plate_distance": s.plate_distance,
        "vehicle_class": s.vehicle_class,
        "first_seen": s.first_seen,
        "last_seen": s.last_seen,
        "first_seen_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s.first_seen))
        if s.time_source == "anchored" else None,
        "dwell_seconds": round(s.last_seen - s.first_seen, 1),
        "detection_rows": s.n_rows,
        "best_confidence": round(s.best_conf, 3),
        "time_source": s.time_source,
    }


def reconstruct(plate: str, max_distance: int, max_speed_kmh: float,
                window_hours: float | None, drop_implausible: bool) -> dict:
    since = time.time() - window_hours * 3600 if window_hours else None
    raw = find_sightings(plate, max_distance, since)
    sightings = dedupe_same_pass(raw)
    hops = build_hops(sightings, max_speed_kmh)

    if drop_implausible and any(not h["plausible"] for h in hops):
        sightings = largest_consistent_subset(sightings, max_speed_kmh)
        hops = build_hops(sightings, max_speed_kmh)

    anchored = [s for s in sightings if s.time_source == "anchored"]
    total_km = sum(h["distance_km"] or 0.0 for h in hops if h["plausible"])
    span = (anchored[-1].last_seen - anchored[0].first_seen) if len(anchored) > 1 else 0.0

    return {
        "query": {
            "plate": plate,
            "normalised": _normalise_plate(plate),
            "max_plate_distance": max_distance,
            "max_speed_kmh": max_speed_kmh,
            "window_hours": window_hours,
        },
        "summary": {
            "sightings": len(sightings),
            "cameras": len({s.camera_id for s in sightings}),
            "exact_matches": sum(1 for s in sightings if s.plate_distance == 0),
            "fuzzy_matches": sum(1 for s in sightings if s.plate_distance > 0),
            "implausible_hops": sum(1 for h in hops if not h["plausible"]),
            "route_distance_km": round(total_km, 2),
            "time_span_seconds": round(span, 1),
            "unanchored_sightings": sum(1 for s in sightings if s.time_source != "anchored"),
        },
        "sightings": [_serialise(s) for s in sightings],
        "hops": hops,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[s.lon, s.lat] for s in sightings
                                        if s.lat is not None and s.lon is not None],
                    },
                    "properties": {"plate": plate, "kind": "route"},
                }
            ] + [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [s.lon, s.lat]},
                    "properties": {
                        "camera_id": s.camera_id,
                        "location": s.location,
                        "seen_at": s.first_seen,
                        "plate_read": s.plate,
                    },
                }
                for s in sightings if s.lat is not None and s.lon is not None
            ],
        },
    }


@router.get("/api/route")
def get_route(
    plate: str = Query(..., min_length=3, description="registration number, spacing ignored"),
    max_distance: int = Query(1, ge=0, le=3, description="plate edit-distance tolerance"),
    max_speed_kmh: float = Query(DEFAULT_MAX_SPEED_KMH, gt=0),
    window_hours: float | None = Query(None, gt=0),
    drop_implausible: bool = Query(False, description="remove hops no vehicle could make"),
) -> dict:
    return reconstruct(plate, max_distance, max_speed_kmh, window_hours, drop_implausible)


@router.get("/api/route/export.csv")
def export_route_csv(
    plate: str = Query(..., min_length=3),
    max_distance: int = Query(1, ge=0, le=3),
    max_speed_kmh: float = Query(DEFAULT_MAX_SPEED_KMH, gt=0),
    window_hours: float | None = Query(None, gt=0),
) -> StreamingResponse:
    """The 'detected vehicles with corresponding timestamps' report, as CSV."""
    result = reconstruct(plate, max_distance, max_speed_kmh, window_hours, False)
    if not result["sightings"]:
        raise HTTPException(status_code=404, detail=f"no sightings for {plate}")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Prahari — vehicle movement report"])
    w.writerow(["Query plate", plate])
    w.writerow(["Generated", time.strftime("%Y-%m-%d %H:%M:%S")])
    w.writerow(["Sightings", result["summary"]["sightings"],
                "Cameras", result["summary"]["cameras"],
                "Route km", result["summary"]["route_distance_km"]])
    w.writerow([])
    w.writerow(["#", "Camera", "Location", "Latitude", "Longitude", "First seen",
                "Last seen", "Dwell (s)", "Plate read", "Edit distance",
                "Vehicle class", "Confidence", "Time source"])
    for i, s in enumerate(result["sightings"], 1):
        w.writerow([
            i, s["camera_id"], s["location"] or "", s["lat"] or "", s["lon"] or "",
            s["first_seen_iso"] or f"pts {s['first_seen']:.1f}",
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s["last_seen"]))
            if s["time_source"] == "anchored" else "",
            s["dwell_seconds"], s["plate_read"], s["plate_distance"],
            s["vehicle_class"], s["best_confidence"], s["time_source"],
        ])
    w.writerow([])
    w.writerow(["Hop", "From", "To", "Gap (s)", "Distance (km)",
                "Implied speed (km/h)", "Plausible", "Note"])
    for i, h in enumerate(result["hops"], 1):
        w.writerow([
            i, h["from_camera"], h["to_camera"], h["gap_seconds"],
            h["distance_km"] if h["distance_km"] is not None else "",
            h["implied_speed_kmh"] if h["implied_speed_kmh"] is not None else "",
            "yes" if h["plausible"] else "NO", h["note"] or "",
        ])

    filename = f"prahari_route_{_normalise_plate(plate)}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/route/export.pdf")
def export_route_pdf(
    plate: str = Query(..., min_length=3),
    max_distance: int = Query(1, ge=0, le=3),
    max_speed_kmh: float = Query(DEFAULT_MAX_SPEED_KMH, gt=0),
    window_hours: float | None = Query(None, gt=0),
) -> StreamingResponse:
    """The same movement report as a printable document."""
    result = reconstruct(plate, max_distance, max_speed_kmh, window_hours, False)
    if not result["sightings"]:
        raise HTTPException(status_code=404, detail=f"no sightings for {plate}")
    try:
        from services.api.route_report import build_route_pdf
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="PDF export needs reportlab: pip install reportlab",
        )
    pdf = build_route_pdf(result, plate)
    filename = f"prahari_route_{_normalise_plate(plate)}.pdf"
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/route/coverage")
def coverage() -> dict:
    """What the route engine actually has to work with.

    Answers 'why is this route short?' before anybody has to guess: how many
    cameras have written detections, how many tracks carry a plate read at all,
    and how many are usable for cross-camera timing.
    """
    tracks = collapse_to_sightings(None)
    per_camera: dict[str, dict] = defaultdict(
        lambda: {"tracks": 0, "with_plate": 0, "anchored": 0, "rows": 0}
    )
    for (cam_id, _), acc in tracks.items():
        c = per_camera[cam_id]
        c["tracks"] += 1
        c["rows"] += acc.n_rows
        if acc.plates:
            c["with_plate"] += 1
        if acc.anchored:
            c["anchored"] += 1

    total_tracks = sum(c["tracks"] for c in per_camera.values())
    with_plate = sum(c["with_plate"] for c in per_camera.values())
    return {
        "cameras_with_detections": len(per_camera),
        "total_tracks": total_tracks,
        "tracks_with_plate": with_plate,
        "plate_read_rate": round(with_plate / total_tracks, 4) if total_tracks else 0.0,
        "anchored_tracks": sum(c["anchored"] for c in per_camera.values()),
        "per_camera": dict(sorted(per_camera.items(),
                                  key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)),
    }
