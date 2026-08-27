"""Resolve camera location names to coordinates for the GIS registry.

The catalogue gives a free-text location per camera ("04 Paldi Circle",
"KHAPARIA GRAM PANCHAYAT , TALUKA GANDEVI, DISTRICT NAVSARI") but no geometry,
and Model 1 requires a GIS layer. This geocodes each name against OpenStreetMap
Nominatim, biased to Gujarat, and writes data/camera_geo.json.

Anything Nominatim cannot resolve falls back to a curated district centroid so
every camera still lands on the map, flagged with its provenance so we never
present a guess as a survey.

Nominatim asks for <=1 request/second and a real User-Agent; both are honoured.

Usage:
    python scripts/geocode_cameras.py
    python scripts/geocode_cameras.py --force     # ignore cached results
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data" / "catalogue" / "ingest.json"
OUT = ROOT / "data" / "camera_geo.json"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "Prahari-GujaratPoliceHackathon2026/0.1 (camera registry geocoding)"

# Gujarat bounding box: west, north, east, south
GUJARAT_VIEWBOX = "68.1,24.7,74.5,20.1"

# District centroids for fallback when a landmark name will not resolve.
DISTRICT_CENTROIDS = {
    "ahmedabad": (23.0225, 72.5714),
    "junagadh": (21.5222, 70.4579),
    "gir somnath": (20.9130, 70.3670),
    "gandhinagar": (23.2156, 72.6369),
    "rajkot": (22.3039, 70.8022),
    "navsari": (20.9467, 72.9520),
    "patan": (23.8493, 72.1266),
    "banaskantha": (24.1722, 72.4381),
    "kheda": (22.7507, 72.6847),
    "dahod": (22.8351, 74.2551),
    "gandhidham": (23.0753, 70.1337),
    "bilimora": (20.7690, 72.9600),
    "adalaj": (23.1645, 72.5810),
    "dehgam": (23.1690, 72.8210),
    "valsad": (20.5992, 72.9342),
}

# Curated coordinates for landmarks Nominatim resolves badly or not at all.
# These are best-effort placements, NOT survey data -- they are emitted with
# precision="curated" and must be verified by the team on the ground, because
# inter-camera distance feeds the route plausibility filter. The operator
# console supports drag-to-correct, which writes back over these.
CURATED = {
    "chiman bhai bridge": (23.0200, 72.5580, "Chimanbhai Patel Bridge, Ahmedabad"),
    "paldi circle": (23.0125, 72.5650, "Paldi Circle, Ahmedabad"),
    "visat teen rasta": (23.1005, 72.5905, "Visat Circle, Ahmedabad"),
    "visat p2": (23.1005, 72.5905, "Visat Circle, Ahmedabad"),
    "o.n.g.c. office": (23.1060, 72.5940, "ONGC Office, Chandkheda, Ahmedabad"),
    "cn vidhyalaya": (23.0225, 72.5510, "C N Vidyalaya, Ambawadi, Ahmedabad"),
    "tri mandir adalaj tollnaka": (23.1650, 72.5830, "Trimandir Adalaj Toll Naka"),
    "timbavadi gate junagadh": (21.5100, 70.4600, "Timbawadi Gate, Junagadh"),
    "majewadi gate junagadh": (21.5230, 70.4520, "Majewadi Gate, Junagadh"),
    "char chowk road 2 junagadh": (21.5220, 70.4650, "Char Chowk Road, Junagadh"),
    "new bypass near by circle junagadh 2": (21.5350, 70.4380, "New Bypass Circle, Junagadh"),
    "rajkot bus port cctv": (22.2960, 70.7930, "Rajkot Bus Port"),
    "rajkot cctv": (22.3039, 70.8022, "Rajkot"),
    "patan dethali char rasta": (23.8500, 72.1300, "Dethali Char Rasta, Patan"),
    "gandhidham rambaugh p2": (23.0800, 70.1330, "Rambaug, Gandhidham"),
}

# Hints that steer ambiguous names to the right district.
DISTRICT_HINTS = [
    ("junagadh", "junagadh"),
    ("somnath", "gir somnath"),
    ("navsari", "navsari"),
    ("gandevi", "navsari"),
    ("khaparia", "navsari"),
    ("bilimora", "navsari"),
    ("rajkot", "rajkot"),
    ("patan", "patan"),
    ("dethali", "patan"),
    ("adalaj", "adalaj"),
    ("dehgam", "dehgam"),
    ("gandhidham", "gandhidham"),
    ("mervada", "banaskantha"),
    ("tankal", "navsari"),
    ("kheram", "kheda"),
    ("dhanori", "ahmedabad"),
    ("mohanpura", "ahmedabad"),
    ("chiman", "ahmedabad"),
    ("janpath", "ahmedabad"),
    ("o.n.g.c", "ahmedabad"),
    ("ongc", "ahmedabad"),
    ("paldi", "ahmedabad"),
    ("visat", "ahmedabad"),
    ("c n vidhyalaya", "ahmedabad"),
    ("cn vidhyalaya", "ahmedabad"),
    ("delight", "ahmedabad"),
    ("suvidha", "ahmedabad"),
    ("timbavadi", "junagadh"),
    ("majewadi", "junagadh"),
    ("dolatpara", "junagadh"),
    ("char chowk", "junagadh"),
    ("hero-showroom", "gir somnath"),
]


def clean_location(raw: str) -> str:
    """Strip the leading serial number and normalise separators."""
    text = re.sub(r"^\s*\d+\s+", "", raw or "").strip()
    text = text.replace("-", " ").replace("_", " ")
    text = re.sub(r"\s*,\s*", ", ", text)
    return re.sub(r"\s+", " ", text).strip()


def guess_district(text: str) -> str | None:
    low = text.lower()
    for needle, district in DISTRICT_HINTS:
        if needle in low:
            return district
    return None


def nominatim(query: str, session: requests.Session) -> dict | None:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "in",
        "viewbox": GUJARAT_VIEWBOX,
        "bounded": 1,
    }
    try:
        resp = session.get(NOMINATIM, params=params, timeout=25)
    except requests.RequestException as exc:
        print(f"      network error: {exc}")
        return None
    if resp.status_code != 200:
        print(f"      HTTP {resp.status_code}")
        return None
    try:
        results = resp.json()
    except ValueError:
        return None
    return results[0] if results else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cameras = json.loads(CATALOGUE.read_text(encoding="utf-8"))["cameras"]
    cached: dict = {}
    if OUT.exists() and not args.force:
        cached = json.loads(OUT.read_text(encoding="utf-8"))

    session = requests.Session()
    session.headers["User-Agent"] = UA

    out: dict = {}
    for cam in cameras:
        cam_id = str(cam["id"])
        raw = cam.get("location") or cam.get("name") or ""
        if cam_id in cached and cached[cam_id].get("lat"):
            out[cam_id] = cached[cam_id]
            print(f"  cam {cam_id:>2}  cached      {cached[cam_id]['label']}")
            continue

        name = clean_location(raw)
        district = guess_district(name)

        curated = CURATED.get(name.lower())
        if curated:
            lat, lon, label = curated
            out[cam_id] = {
                "lat": lat, "lon": lon, "label": name, "raw": raw,
                "district": district, "source": "curated",
                "matched": label, "precision": "curated",
            }
            print(f"  cam {cam_id:>2}  curated     {name}  ->  {lat:.4f},{lon:.4f}")
            continue

        queries = []
        if district:
            queries.append(f"{name}, {district}, Gujarat, India")
        queries.append(f"{name}, Gujarat, India")

        hit = None
        for query in queries:
            hit = nominatim(query, session)
            time.sleep(1.1)  # Nominatim rate limit
            if hit:
                break

        if hit:
            out[cam_id] = {
                "lat": float(hit["lat"]),
                "lon": float(hit["lon"]),
                "label": name,
                "raw": raw,
                "district": district,
                "source": "nominatim",
                "matched": hit.get("display_name", "")[:140],
                "precision": "landmark",
            }
            print(f"  cam {cam_id:>2}  geocoded    {name}  ->  "
                  f"{out[cam_id]['lat']:.4f},{out[cam_id]['lon']:.4f}")
        else:
            lat, lon = DISTRICT_CENTROIDS.get(district or "", DISTRICT_CENTROIDS["ahmedabad"])
            out[cam_id] = {
                "lat": lat,
                "lon": lon,
                "label": name,
                "raw": raw,
                "district": district,
                "source": "district_centroid",
                "matched": None,
                "precision": "approximate",
            }
            print(f"  cam {cam_id:>2}  FALLBACK    {name}  ->  district centroid "
                  f"{district or 'ahmedabad'}")

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    exact = sum(1 for v in out.values() if v["source"] == "nominatim")
    print(f"\n  {exact}/{len(out)} resolved to a landmark; "
          f"{len(out) - exact} fell back to a district centroid")
    print(f"  written: {OUT.relative_to(ROOT)}")
    print("\n  NOTE: fallback entries are flagged precision=approximate. Refine them")
    print("        by hand before the finale -- route plausibility filtering uses")
    print("        inter-camera distance, so bad coordinates degrade tracking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
