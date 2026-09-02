"""[G6] Turn the salvaged geocoded coordinates into a [C8] starting point.

This does **not** complete G6. The ticket asks for a human to open each live
frame, find a landmark, and place the pin -- that is what earns `coord_source
= manual` and a HIGH confidence. What this does is give that human somewhere
to start, in the right shape, with honest confidence values.

Confidence is assigned from how the old file got each coordinate:

  landmark    -> MEDIUM   a geocoder matched a named place
  curated     -> MEDIUM   hand-written against a known junction
  approximate -> LOW      a town/area name, not a junction
  city centroid -> LOW    several cameras share one point; these are the
                          "demo car teleports" cases the ticket warns about

Nothing here is HIGH. A coordinate nobody has visually confirmed against the
camera's own view is not ground truth, and calling it HIGH would put a wrong
pin in front of a judge with a confident label on it.

    python scripts/geo_bootstrap.py            # write data/camera_geo.json
    python scripts/geo_bootstrap.py --report   # what still needs a human
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "cameras.seed.json"
GEO_OUT = ROOT / "data" / "camera_geo.json"
SALVAGE = ROOT / "data" / "catalogue" / "camera_geo.salvage.json"

# Coordinates that stand for a whole city rather than a junction. Any camera
# sitting exactly on one of these has not really been placed.
CITY_CENTROIDS = {
    (23.0225, 72.5714): "Ahmedabad city centroid",
}

PRECISION_TO_CONF = {
    "curated": "MEDIUM",
    "landmark": "MEDIUM",
    "approximate": "LOW",
}

DEFAULTS = {"fov_deg": 70, "range_m": 60}


def load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> dict:
    salvage = load(SALVAGE)
    seed = {str(c["camera_id"]): c for c in load(SEED)}

    geo: dict[str, dict] = {}
    for cam_id, old in salvage.items():
        lat, lon = old.get("lat"), old.get("lon")
        precision = old.get("precision")
        conf = PRECISION_TO_CONF.get(precision, "LOW")

        note = old.get("matched") or old.get("label") or ""
        centroid = CITY_CENTROIDS.get((lat, lon))
        if centroid:
            conf = "LOW"
            note = f"{centroid} -- NOT placed, needs a human"

        geo[cam_id] = {
            "lat": lat,
            "lon": lon,
            # bearing is the one thing a geocoder can never supply: it depends
            # on which way the camera actually looks. Null until someone sees
            # the frame; the console renders a pin with no wedge.
            "bearing_deg": None,
            "fov_deg": DEFAULTS["fov_deg"],
            "range_m": DEFAULTS["range_m"],
            "coord_source": "geocoded",
            "coord_conf": conf,
            "landmark": note,
            "location_raw": seed.get(cam_id, {}).get("location_raw"),
            "verified": False,
        }
    return geo


def duplicates(geo: dict) -> dict[tuple, list[str]]:
    seen: dict[tuple, list[str]] = {}
    for cam_id, v in geo.items():
        seen.setdefault((v["lat"], v["lon"]), []).append(cam_id)
    return {k: v for k, v in seen.items() if len(v) > 1}


def report(geo: dict) -> int:
    confs = Counter(v["coord_conf"] for v in geo.values())
    high_med = confs["HIGH"] + confs["MEDIUM"]
    print(f"cameras          : {len(geo)}")
    print(f"coord_conf       : {dict(confs)}")
    print(f"HIGH or MEDIUM   : {high_med}/{len(geo)}  (ticket needs >= 25)")
    print(f"bearing set      : {sum(1 for v in geo.values() if v['bearing_deg'] is not None)}/{len(geo)}")
    print(f"verified by human: {sum(1 for v in geo.values() if v['verified'])}/{len(geo)}")

    dupes = duplicates(geo)
    if dupes:
        print("\nshared coordinates -- at most one of each group is really placed:")
        for (lat, lon), ids in sorted(dupes.items(), key=lambda kv: -len(kv[1])):
            print(f"  {lat},{lon}  cameras {', '.join(ids)}")

    low = [c for c, v in geo.items() if v["coord_conf"] == "LOW"]
    if low:
        print(f"\nLOW confidence, need a human first: {', '.join(sorted(low, key=int))}")

    print("\nNo camera is HIGH: nothing here has been checked against its own")
    print("live frame yet. Run scripts/geo_helper.html to do that.")
    return 0 if high_med >= 25 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    geo = build()
    if not args.report:
        GEO_OUT.write_text(json.dumps(geo, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[+] wrote {len(geo)} cameras -> {GEO_OUT.relative_to(ROOT)}")
    return report(geo)


if __name__ == "__main__":
    sys.exit(main())
