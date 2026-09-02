#!/usr/bin/env python3
"""Load the camera registry into Postgres from lane G's two exchange files.

    python scripts/load_registry.py --dry-run     # read the files, touch nothing
    python scripts/load_registry.py               # upsert into cameras

Inputs are [C8]: data/cameras.seed.json (G1, a list) and data/camera_geo.json (G6, a dict
keyed by camera_id). Both belong to lane G and both routinely lag behind each other, so this
script never treats a disagreement between them as a failure — it reports it. Three cases
that are expected, not errors:

  * camera_geo.json missing entirely   -> every camera loads with null coordinates, warned once
  * a seed camera absent from the geo  -> one missing-coordinate warning per camera
  * a geo id absent from the seed      -> counted and named; the geo file is ahead or stale

The upsert coalesces incoming nulls against what is already stored, so re-running with a
truncated geo file cannot wipe coordinates that were already good. Coordinates are the one
thing here that is expensive to recover: G6 surveys them by hand.

transport_in_use is deliberately left alone. G's health monitor owns it at runtime; a loader
that guessed it would fight the gateway every time this runs.
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SEED = REPO / "data" / "cameras.seed.json"
DEFAULT_GEO = REPO / "data" / "camera_geo.json"
# Credentials come from POSTGRES_DSN in .env ([C9]), never from this file.
DEFAULT_DSN = "postgresql://localhost:5432/sentinel"

UPSERT = """
INSERT INTO cameras (camera_id, name, owner_dept_id, district_code, install_type,
                     lat, lon, coord_source, coord_conf,
                     bearing_deg, fov_deg, range_m, lane_bearing_deg,
                     transports, driver, updated_at)
VALUES (%(camera_id)s, %(name)s,
        (SELECT id FROM departments WHERE code = %(district_code)s),
        %(district_code)s, %(install_type)s,
        %(lat)s, %(lon)s, %(coord_source)s, %(coord_conf)s,
        %(bearing_deg)s, %(fov_deg)s, %(range_m)s, %(lane_bearing_deg)s,
        %(transports)s, %(driver)s, now())
ON CONFLICT (camera_id) DO UPDATE SET
  name             = EXCLUDED.name,
  owner_dept_id    = COALESCE(EXCLUDED.owner_dept_id, cameras.owner_dept_id),
  district_code    = COALESCE(EXCLUDED.district_code, cameras.district_code),
  install_type     = COALESCE(EXCLUDED.install_type, cameras.install_type),
  lat              = COALESCE(EXCLUDED.lat, cameras.lat),
  lon              = COALESCE(EXCLUDED.lon, cameras.lon),
  coord_source     = COALESCE(EXCLUDED.coord_source, cameras.coord_source),
  coord_conf       = COALESCE(EXCLUDED.coord_conf, cameras.coord_conf),
  bearing_deg      = COALESCE(EXCLUDED.bearing_deg, cameras.bearing_deg),
  fov_deg          = COALESCE(EXCLUDED.fov_deg, cameras.fov_deg),
  range_m          = COALESCE(EXCLUDED.range_m, cameras.range_m),
  lane_bearing_deg = COALESCE(EXCLUDED.lane_bearing_deg, cameras.lane_bearing_deg),
  transports       = COALESCE(EXCLUDED.transports, cameras.transports),
  driver           = COALESCE(EXCLUDED.driver, cameras.driver),
  updated_at       = now()
"""


def safe_path(path, label):
    """Resolve a path from the command line, or return None with the reason printed.

    The two inputs are file paths taken from argv, and this script is run by scripts and by
    agents as well as by people. Resolving first collapses `..` and symlinks, so what is checked
    is what is opened; requiring a regular .json file keeps a mistyped argument from turning a
    loader into a reader of whatever it was pointed at.
    """
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() != ".json":
        print(f"warning: {label} must be a .json file, got {resolved.name}")
        return None
    if resolved.is_dir():
        print(f"warning: {label} is a directory, not a file: {resolved}")
        return None
    return resolved


def read_json(path, expected, label):
    """Return the parsed file, or None with a reason printed. Never raises on a bad file."""
    path = safe_path(path, label)
    if path is None:
        return None
    if not path.exists():
        print(f"warning: {label} not found at {path} - lane G has not produced it yet")
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"warning: {label} at {path} is not valid JSON ({exc}) - treating it as absent")
        return None
    if not isinstance(doc, expected):
        print(f"warning: {label} is a {type(doc).__name__}, expected {expected.__name__} per [C8]")
        return None
    return doc


def build_rows(seed, geo):
    """Join the two files into one row per camera, plus the warnings the join produced."""
    rows, warnings = [], []
    for entry in seed:
        cam_id = entry.get("camera_id")
        if not cam_id:
            warnings.append(f"seed entry without camera_id skipped: {entry!r:.80}")
            continue
        g = geo.get(cam_id, {})
        if not g:
            warnings.append(f"{cam_id}: no coordinates - it cannot be drawn on the map or routed")
        elif g.get("lat") is None or g.get("lon") is None:
            warnings.append(f"{cam_id}: geo entry present but lat/lon is null")
        elif g.get("coord_conf") == "LOW" or g.get("coord_source") == "district_centroid":
            # G6's gotcha: a district centroid makes the demo car teleport between hops.
            warnings.append(f"{cam_id}: coordinates are {g.get('coord_source')}/{g.get('coord_conf')}"
                            " - good enough to store, not good enough for a route demo")
        rows.append({
            "camera_id": cam_id,
            "name": entry.get("name") or cam_id,
            "district_code": entry.get("district_code"),
            "install_type": entry.get("install_type"),
            "lat": g.get("lat"),
            "lon": g.get("lon"),
            "coord_source": g.get("coord_source"),
            "coord_conf": g.get("coord_conf"),
            "bearing_deg": g.get("bearing_deg"),
            "fov_deg": g.get("fov_deg"),
            "range_m": g.get("range_m"),
            "lane_bearing_deg": g.get("lane_bearing_deg"),
            "transports": json.dumps(entry["transports"]) if entry.get("transports") else None,
            "driver": entry.get("driver"),
        })
    orphans = sorted(set(geo) - {r["camera_id"] for r in rows})
    if orphans:
        warnings.append(f"{len(orphans)} id(s) in camera_geo.json are not in the seed: "
                        + ", ".join(orphans[:5]) + (" ..." if len(orphans) > 5 else ""))
    return rows, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    ap.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    ap.add_argument("--geo", type=Path, default=DEFAULT_GEO)
    # No --dsn. A connection string on the command line lands in shell history and in `ps`,
    # and a loader that takes one from argv can be aimed at any database by whoever - or
    # whatever - assembles the command. It comes from the environment ([C9]) or not at all.
    args = ap.parse_args()

    dsn = os.environ.get("POSTGRES_DSN") or DEFAULT_DSN
    seed = read_json(args.seed, list, "cameras.seed.json")
    geo = read_json(args.geo, dict, "camera_geo.json")
    if seed is None:
        print("nothing to load: the seed file is the only source of camera ids")
        return 1

    rows, warnings = build_rows(seed, geo or {})
    with_coords = sum(1 for r in rows if r["lat"] is not None and r["lon"] is not None)
    print(f"seed: {len(rows)} camera(s) | geo: {len(geo or {})} entry(ies) | "
          f"{with_coords} with coordinates, {len(rows) - with_coords} without")
    for w in warnings:
        print(f"  warning: {w}")

    if args.dry_run:
        print("dry run: no rows written")
        return 0

    import psycopg2  # imported late so --dry-run works with no driver and no database
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM cameras")
        before = cur.fetchone()[0]
        cur.executemany(UPSERT, rows)
        cur.execute("SELECT count(*) FROM cameras")
        after = cur.fetchone()[0]
    print(f"cameras: {before} before, {after} after ({after - before} new, "
          f"{len(rows) - (after - before)} updated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
