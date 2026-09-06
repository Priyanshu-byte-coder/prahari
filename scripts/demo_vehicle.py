"""Lay down one scripted vehicle for the demo, through the real pipeline.

    python scripts/demo_vehicle.py                 # the standard demo run
    python scripts/demo_vehicle.py --watchlist     # ... and put it on the watchlist first
    python scripts/demo_vehicle.py --clear         # remove every trace of it afterwards

The background generator produces plausible traffic, but a trace shown to a judge wants a
*legible* journey: hops in order, sensible gaps, a route that reads as one vehicle crossing a
city, and - the point of the whole exercise - one hop that is physically impossible so the
implausibility flag has something to catch.

**This vehicle is synthetic and the demo says so.** What is not synthetic is the path it takes:
the rows are published to the same Redis stream a camera publishes to, picked up by the same
persister, matched by the same matcher and reconstructed by the same route builder. Nothing is
written directly to the database, because a demo that bypasses the pipeline is a demo of nothing.

The route is a real corridor. Southern Ahmedabad up through the city to Gandhinagar, on cameras
that actually sit on that line, at speeds a car actually does. Then a single sighting in Rajkot
two minutes later, 200 km away - the misread that the route builder marks IMPLAUSIBLE and shows
anyway, because hiding it would be hiding the evidence that something went wrong.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import fake_sightings as fs                                          # noqa: E402

# A plate that is unmistakably ours. GJ-01 is the Ahmedabad series, where the journey starts;
# "DM" is not an issued letter pair, so this cannot collide with a real registration on a real
# vehicle - which matters, because this plate ends up in a video that goes to a police audience.
DEMO_PLATE = "GJ01DM0042"

# (camera_id, minutes after the start, band). The gaps are what a car does on that road: about
# two kilometres between the city cameras at four to five minutes apart, then the run north to
# Gandhinagar which is longer in both distance and time.
ROUTE = [
    ("4",  0,  "CONFIRMED"),     # 23.0125, 72.5650  southern Ahmedabad
    ("1",  4,  "CONFIRMED"),     # 23.0200, 72.5580  ~1 km north
    ("20", 9,  "PROBABLE"),      # 23.0225, 72.5714  eastwards - one weaker read, on purpose
    ("5",  21, "CONFIRMED"),     # 23.1005, 72.5905  north up the highway
    ("3",  24, "CONFIRMED"),     # 23.1060, 72.5940
    ("12", 34, "CONFIRMED"),     # 23.1650, 72.5830  Gandhinagar
]

# The impossible one. Rajkot is roughly 200 km from Gandhinagar; two minutes after the last hop
# implies about 6,000 km/h. This is what a misread looks like in real data, and the route builder
# returns it flagged rather than dropping it.
IMPLAUSIBLE = ("17", 36, "POSSIBLE")     # 22.2960, 70.7930  Rajkot


def rows(start, include_implausible=True, seed=42):
    """The scripted journey as [C1] rows, in order."""
    rng = random.Random(seed)
    out = []
    plan = ROUTE + ([IMPLAUSIBLE] if include_implausible else [])
    for camera_id, minute, band in plan:
        at = start + timedelta(minutes=minute, seconds=rng.uniform(0, 40))
        row = fs.sighting(rng, camera_id, at, DEMO_PLATE)
        row["plate_band"] = band
        # A band is a claim about confidence, so the confidence has to agree with it.
        row["plate_conf"] = {"CONFIRMED": round(rng.uniform(0.93, 0.99), 2),
                             "PROBABLE": round(rng.uniform(0.78, 0.88), 2),
                             "POSSIBLE": round(rng.uniform(0.55, 0.68), 2)}[band]
        row["vehicle_class"] = "car"
        row["colour"] = "white"
        out.append(fs.finish_bbox(row, rng))
    return out


def publish(rows_, redis_url=None, stream=fs.STREAM):
    import redis

    client = redis.from_url(redis_url or os.environ.get("REDIS_URL",
                                                        "redis://localhost:6379/0"),
                            decode_responses=True)
    client.ping()
    for row in rows_:
        client.xadd(stream, {"data": json.dumps(row)})
    return len(rows_)


def add_to_watchlist(api_base, username, password):
    """Put the demo plate on the watchlist through the API, so the alert fires for real."""
    import urllib.error
    import urllib.request

    def call(path, body=None, token=None):
        req = urllib.request.Request(
            api_base.rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={k: v for k, v in {
                "Content-Type": "application/json" if body is not None else None,
                "Authorization": f"Bearer {token}" if token else None}.items() if v},
            method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, {"detail": exc.read().decode("utf-8", "replace")[:200]}
        except Exception as exc:
            return None, {"detail": f"{type(exc).__name__}: {exc}"}

    status, body = call("/api/auth/login", {"username": username, "password": password})
    if status != 200:
        return False, f"could not log in as {username}: {status} {body.get('detail','')}"
    token = body["access"]

    # Clear any entry from a previous run first. The matcher keys its index by canonical plate
    # and raises one alert for the vehicle, not one per duplicate entry - so a stale entry would
    # absorb the match and the new one would look broken.
    status, existing = call("/api/watchlist", token=token)
    for entry in (existing if isinstance(existing, list) else []):
        if entry.get("plate_norm") == DEMO_PLATE:
            urllib.request.urlopen(urllib.request.Request(
                f"{api_base.rstrip('/')}/api/watchlist/{entry['id']}", method="DELETE",
                headers={"Authorization": f"Bearer {token}"}), timeout=15)

    status, body = call("/api/watchlist", {
        "kind": "plate", "plate": DEMO_PLATE, "category": "stolen vehicle",
        "severity": "HIGH", "reason": "demo vehicle - scripted route",
        "description": "white hatchback, demo"}, token=token)
    if status not in (200, 201):
        return False, f"watchlist add failed: {status} {body.get('detail','')}"
    return True, f"watchlist entry {body.get('id')}"


def clear(dsn=None):
    """Remove the demo vehicle from the database. Returns (sightings, alerts, watchlist)."""
    import psycopg2

    conn = psycopg2.connect(dsn or os.environ["POSTGRES_DSN"])
    with conn, conn.cursor() as cur:
        cur.execute("""DELETE FROM alerts WHERE watchlist_id IN
                       (SELECT id FROM watchlist WHERE plate_norm = %s)""", (DEMO_PLATE,))
        alerts = cur.rowcount
        cur.execute("DELETE FROM sightings WHERE plate_norm = %s", (DEMO_PLATE,))
        sightings = cur.rowcount
        cur.execute("DELETE FROM watchlist WHERE plate_norm = %s", (DEMO_PLATE,))
        entries = cur.rowcount
    conn.close()
    return sightings, alerts, entries


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plate", default=None, help="override the demo plate")
    ap.add_argument("--minutes-ago", type=int, default=50,
                    help="when the journey started, relative to now")
    ap.add_argument("--watchlist", action="store_true",
                    help="add the plate to the watchlist first, so the alert fires too")
    ap.add_argument("--no-implausible", action="store_true",
                    help="leave out the impossible Rajkot hop")
    ap.add_argument("--clear", action="store_true", help="delete this vehicle and exit")
    ap.add_argument("--api", default=os.environ.get("API_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--user", default=os.environ.get("PRAHARI_CONSOLE_USER", "field"))
    ap.add_argument("--password", default=os.environ.get("PRAHARI_CONSOLE_PASSWORD", ""))
    args = ap.parse_args()

    global DEMO_PLATE
    if args.plate:
        DEMO_PLATE = args.plate.upper()

    if args.clear:
        sightings, alerts, entries = clear()
        print(f"removed {sightings} sighting(s), {alerts} alert(s), {entries} watchlist entry/ies "
              f"for {DEMO_PLATE}")
        return 0

    if args.watchlist:
        if not args.password:
            print("--watchlist needs a password: set PRAHARI_CONSOLE_PASSWORD or pass --password")
            return 2
        ok, detail = add_to_watchlist(args.api, args.user, args.password)
        print(("watchlist: " if ok else "watchlist FAILED: ") + detail)
        if not ok:
            return 1
        # Give the matcher time to reload its index, or the sightings arrive before it knows.
        print("waiting 32 s for the matcher to pick the entry up ...")
        time.sleep(32)

    start = datetime.now(fs.IST) - timedelta(minutes=args.minutes_ago)
    journey = rows(start, include_implausible=not args.no_implausible)
    published = publish(journey)

    print(f"\npublished {published} sighting(s) for {DEMO_PLATE} to the `{fs.STREAM}` stream")
    print(f"journey starts {args.minutes_ago} min ago and covers {len(journey)} cameras\n")
    for row in journey:
        when = datetime.fromisoformat(row["pts_first"]).strftime("%H:%M:%S")
        print(f"  {when}  cam {row['camera_id']:>2}  {row['plate_band']:<9} "
              f"conf {row['plate_conf']}")
    print(f"\nType this into Trace:  {DEMO_PLATE}")
    print("The last hop is 200 km away two minutes later - it comes back flagged IMPLAUSIBLE,")
    print("which is the point of showing it.")
    print("\nUndo everything with:  python scripts/demo_vehicle.py --clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
