"""Generate synthetic detections with known ground truth, and verify the route
engine reproduces them.

Cross-camera route reconstruction is gate G3, and it cannot wait for plate OCR
to start working before it is proven correct. This builds a detection set whose
answer is known in advance — a target vehicle driving a plausible path through
real camera positions, decoy vehicles, a noisy OCR read of the target, and one
physically impossible sighting — then asks the route engine for the route and
checks what comes back.

The fixture is written to `data/detections_fixture/`, never to
`data/detections/`, and the engine is pointed at it with
PRAHARI_DETECTIONS_DIR. Fabricated rows must never mix with real captured
detections: everything the judges see has to come from the live grid.

    python scripts/route_fixture.py            generate, then verify
    python scripts/route_fixture.py --clean    delete the fixture
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "data" / "detections_fixture"
GEO_FILE = ROOT / "data" / "camera_geo.json"

TARGET_PLATE = "GJ01AB1234"
DECOY_PLATES = ["GJ05CD4321", "MH12XY8765", "GJ18JK2211", "RJ14PQ9090"]

# Average speed between cameras, km/h. Deliberately ordinary city driving.
CRUISE_KMH = 35.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def pick_route_cameras(geo: dict, n: int) -> list[str]:
    """Choose n cameras that form a geographically sensible path.

    Nearest-neighbour walk from an Ahmedabad camera, so the synthetic journey
    looks like a vehicle crossing a city rather than teleporting between
    districts.
    """
    usable = {cid: (v["lat"], v["lon"]) for cid, v in geo.items()
              if v.get("lat") is not None and v.get("lon") is not None}
    if len(usable) < n:
        raise SystemExit(f"need {n} geolocated cameras, have {len(usable)}")

    # Start from the camera closest to central Ahmedabad.
    centre = (23.0225, 72.5714)
    start = min(usable, key=lambda cid: haversine_km(usable[cid], centre))

    route = [start]
    remaining = dict(usable)
    remaining.pop(start)
    while len(route) < n and remaining:
        last = usable[route[-1]]
        nxt = min(remaining, key=lambda cid: haversine_km(usable[cid], last))
        route.append(nxt)
        remaining.pop(nxt)
    return route


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def vehicle_pass(camera_id: str, track_id: int, plate: str | None,
                 start_at: float, duration: float, rng: random.Random,
                 vehicle_class: str = "car", frames_per_second: float = 5.0) -> list[dict]:
    """One vehicle crossing one camera, as the worker would have written it."""
    rows = []
    n = max(2, int(duration * frames_per_second))
    for i in range(n):
        t = start_at + i / frames_per_second
        x = 300 + i * 6
        rows.append({
            "camera_id": camera_id,
            "track_id": track_id,
            "class": vehicle_class,
            "conf": round(rng.uniform(0.55, 0.93), 3),
            "bbox": [x, 400.0, x + 140, 520.0],
            "pts_seconds": round(120.0 + i / frames_per_second, 3),
            "observed_at": round(t, 3),
            # Plate is only read on some frames, exactly as the real pipeline
            # behaves: OCR is throttled and most frames yield nothing.
            "plate": plate if (plate and i % 4 == 0) else None,
        })
    return rows


def generate(seed: int = 7) -> dict:
    rng = random.Random(seed)
    geo = json.loads(GEO_FILE.read_text(encoding="utf-8"))

    if FIXTURE_DIR.exists():
        shutil.rmtree(FIXTURE_DIR)
    FIXTURE_DIR.mkdir(parents=True)

    route = pick_route_cameras(geo, 5)
    now = time.time()
    t = now - 3600  # journey started an hour ago
    truth = []

    print("synthetic journey for", TARGET_PLATE)
    for i, cam in enumerate(route):
        dwell = rng.uniform(6.0, 14.0)
        rows = vehicle_pass(cam, 1000 + i, TARGET_PLATE, t, dwell, rng)
        write_rows(FIXTURE_DIR / f"cam_{cam}.jsonl", rows)
        pos = geo[cam]
        truth.append({"camera": cam, "at": t, "location": pos.get("label")})
        print(f"  {i+1}. cam {cam:>3}  {pos.get('label','?'):<28} "
              f"{time.strftime('%H:%M:%S', time.localtime(t))}")

        if i + 1 < len(route):
            nxt = route[i + 1]
            km = haversine_km((geo[cam]["lat"], geo[cam]["lon"]),
                              (geo[nxt]["lat"], geo[nxt]["lon"]))
            t += dwell + (km / CRUISE_KMH) * 3600.0

    # Decoy traffic on the same cameras, so matching has to discriminate.
    for cam in route:
        for j, plate in enumerate(DECOY_PLATES):
            write_rows(FIXTURE_DIR / f"cam_{cam}.jsonl",
                       vehicle_pass(cam, 2000 + j, plate,
                                    now - rng.uniform(600, 3600),
                                    rng.uniform(5, 12), rng,
                                    rng.choice(["car", "truck", "motorcycle"])))

    # A noisy read of the target on a sixth camera: '0' misread as 'O'. A
    # fuzzy matcher should still place this on the route.
    noisy_cam = next(c for c in geo if c not in route
                     and geo[c].get("lat") is not None)
    write_rows(FIXTURE_DIR / f"cam_{noisy_cam}.jsonl",
               vehicle_pass(noisy_cam, 3000, "GJO1AB1234", t + 200, 8.0, rng))
    print(f"  noisy read 'GJO1AB1234' planted on cam {noisy_cam}")

    # A physically impossible sighting: the target appearing far away seconds
    # after the last real one. The plausibility filter must flag this.
    far_cam = max(
        (c for c in geo if geo[c].get("lat") is not None),
        key=lambda c: haversine_km((geo[c]["lat"], geo[c]["lon"]),
                                   (geo[route[-1]]["lat"], geo[route[-1]]["lon"])),
    )
    write_rows(FIXTURE_DIR / f"cam_{far_cam}.jsonl",
               vehicle_pass(far_cam, 4000, TARGET_PLATE, t + 20, 6.0, rng))
    far_km = haversine_km((geo[far_cam]["lat"], geo[far_cam]["lon"]),
                          (geo[route[-1]]["lat"], geo[route[-1]]["lon"]))
    print(f"  impossible sighting planted on cam {far_cam} ({far_km:.0f} km away, 20s later)")

    return {"route": route, "truth": truth, "noisy_cam": noisy_cam,
            "far_cam": far_cam, "far_km": far_km}


def verify(plan: dict) -> int:
    os.environ["PRAHARI_DETECTIONS_DIR"] = str(FIXTURE_DIR)
    sys.path.insert(0, str(ROOT))
    import importlib
    import services.api.route_routes as rr
    importlib.reload(rr)

    print("\n" + "=" * 68)
    print("VERIFY — exact match only (max_distance=0)")
    exact = rr.reconstruct(TARGET_PLATE, 0, 120.0, None, False)
    cams_exact = [s["camera_id"] for s in exact["sightings"]]
    print(f"  cameras on route: {cams_exact}")
    print(f"  summary: {exact['summary']}")

    print("\nVERIFY — fuzzy match (max_distance=1), should also catch the noisy read")
    fuzzy = rr.reconstruct(TARGET_PLATE, 1, 120.0, None, False)
    cams_fuzzy = [s["camera_id"] for s in fuzzy["sightings"]]
    print(f"  cameras on route: {cams_fuzzy}")
    print(f"  exact={fuzzy['summary']['exact_matches']} "
          f"fuzzy={fuzzy['summary']['fuzzy_matches']} "
          f"implausible_hops={fuzzy['summary']['implausible_hops']}")

    failures = []

    # 1. Every planted route camera must appear.
    missing = [c for c in plan["route"] if c not in cams_exact]
    if missing:
        failures.append(f"route cameras missing from exact match: {missing}")

    # 2. Order must match the journey.
    ordered = [c for c in cams_exact if c in plan["route"]]
    if ordered != plan["route"]:
        failures.append(f"route out of order: got {ordered}, expected {plan['route']}")

    # 3. Decoys must never appear.
    decoy_hits = [s for s in fuzzy["sightings"] if s["plate_read"] in DECOY_PLATES]
    if decoy_hits:
        failures.append(f"decoy vehicles matched: {[s['plate_read'] for s in decoy_hits]}")

    # 4. The noisy read must be recovered by fuzzy matching but not by exact.
    if plan["noisy_cam"] in cams_exact:
        failures.append("noisy read matched at distance 0, which is wrong")
    if plan["noisy_cam"] not in cams_fuzzy:
        failures.append("fuzzy matching failed to recover the noisy plate read")

    # 5. The impossible hop must be flagged.
    if fuzzy["summary"]["implausible_hops"] < 1:
        failures.append("the impossible sighting was not flagged by the speed filter")
    else:
        bad = [h for h in fuzzy["hops"] if not h["plausible"]]
        for h in bad:
            print(f"\n  flagged hop {h['from_camera']} -> {h['to_camera']}: {h['note']}")

    # 6. Dropping implausible sightings must remove it.
    cleaned = rr.reconstruct(TARGET_PLATE, 1, 120.0, None, True)
    if cleaned["summary"]["implausible_hops"] != 0:
        failures.append("drop_implausible did not remove the impossible hop")

    print("\n" + "=" * 68)
    if failures:
        print(f"FAILED — {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASSED — route engine reproduces the planted journey:")
    print(f"  - all {len(plan['route'])} route cameras found, in the right order")
    print("  - decoy vehicles correctly excluded")
    print("  - noisy plate read recovered by fuzzy matching only")
    print("  - physically impossible sighting flagged and removable")
    print(f"\n  CSV report: GET /api/route/export.csv?plate={TARGET_PLATE}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    if args.clean:
        if FIXTURE_DIR.exists():
            shutil.rmtree(FIXTURE_DIR)
            print(f"removed {FIXTURE_DIR.relative_to(ROOT)}")
        return 0

    plan = generate(args.seed)
    return verify(plan)


if __name__ == "__main__":
    sys.exit(main())
