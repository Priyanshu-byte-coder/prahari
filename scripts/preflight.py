"""Everything that can embarrass you on camera, checked before you press record.

    python scripts/preflight.py            # check, and say exactly how to fix what is wrong
    python scripts/preflight.py --fix      # start what can be started, then check again

Each line is PASS, FIX or WARN. FIX means the demo will visibly break; WARN means something will
look worse than it is. The point is that every FIX comes with the command that repairs it - a
check that only says "no" costs more time than it saves.

This exists because the failures that actually happened during rehearsal were all environmental
rather than logical: the wrong interpreter (no torch, so no bounding boxes), no environment file
(no Redis, so the selftest publishes into the void), Docker asleep, the grid session taken by
another login, or the workers not running so the map fills but nothing is ever traceable.
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FIX, WARN = "PASS", "FIX ", "WARN"
results = []


def report(level, what, detail=""):
    results.append((level, what, detail))
    colour = {"PASS": "", "FIX ": "", "WARN": ""}[level]
    print(f"{colour}{level}  {what}")
    if detail and level != PASS:
        for line in detail.strip().splitlines():
            print(f"        {line}")


def _get(url, timeout=5, limit=600):
    """`limit` keeps the health probes cheap; callers that parse JSON must read the whole body,
    because a truncated response is not JSON and the traceback blames the wrong thing."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            raw = r.read() if limit is None else r.read(limit)
            return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return None, ""


# --- 1. the interpreter --------------------------------------------------------------------

def check_interpreter():
    venv = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    running_venv = Path(sys.executable).resolve() == venv.resolve() if venv.exists() else False
    try:
        import torch                                        # noqa: F401
        import ultralytics                                  # noqa: F401
        has_cv = True
    except Exception:
        has_cv = False

    if has_cv:
        report(PASS, f"interpreter has the CV stack ({Path(sys.executable).name})")
    elif venv.exists():
        report(FIX, "this interpreter has no torch/ultralytics",
               f"The CV stack lives in .venv. Anything you run by hand must use it:\n"
               f"  {venv}  services/worker/selftest.py\n"
               f"scripts/run_stack.py already picks it up automatically.")
    else:
        report(FIX, "no virtualenv and no CV stack",
               "pip install -r requirements.txt")
    return has_cv or running_venv


# --- 2. environment ------------------------------------------------------------------------

def check_env():
    needed = ["POSTGRES_DSN", "REDIS_URL", "JWT_SECRET"]
    missing = [k for k in needed if not os.environ.get(k)]
    if missing:
        report(FIX, f"environment not loaded ({', '.join(missing)} unset)",
               "source run_demo_env.sh          # bash / git-bash\n"
               "Without it the worker cannot reach Redis and publishes into memory, and the\n"
               "selftest fails with 'no Redis ... sightings will buffer in memory'.")
        return False
    report(PASS, "environment loaded (Postgres, Redis, JWT secret)")

    if len(os.environ.get("JWT_SECRET", "")) < 32:
        report(WARN, "JWT_SECRET is under 32 bytes",
               "Tokens still work; the library warns on every mint, which clutters the log you\n"
               "may end up showing on camera.")
    return True


# --- 3. infrastructure ---------------------------------------------------------------------

def check_docker():
    if not shutil.which("docker"):
        report(WARN, "docker not on PATH", "Only matters if the containers are not already up.")
        return False
    up = subprocess.run(["docker", "ps", "--filter", "name=sentinel", "--format", "{{.Names}}"],
                        capture_output=True, text=True)
    if up.returncode != 0:
        report(FIX, "Docker is not running",
               "Start Docker Desktop, then:\n"
               "  docker start sentinel-postgres sentinel-redis sentinel-minio")
        return False
    names = [n for n in up.stdout.split() if n]
    wanted = {"sentinel-postgres", "sentinel-redis", "sentinel-minio"}
    missing = wanted - set(names)
    if missing:
        report(FIX, f"containers not running: {', '.join(sorted(missing))}",
               f"docker start {' '.join(sorted(missing))}")
        return False
    report(PASS, "postgres, redis and minio are up")
    return True


def check_database():
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        return False
    try:
        import psycopg2

        with psycopg2.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM cameras")
            cameras = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM sightings WHERE pts_first > now() - interval '1 hour'")
            recent = cur.fetchone()[0]
    except Exception as exc:
        report(FIX, "cannot reach Postgres", f"{type(exc).__name__}: {str(exc).strip()[:120]}")
        return False

    if cameras == 0:
        report(FIX, "no cameras in the registry", "make seed   # or python scripts/load_registry.py")
        return False
    report(PASS, f"{cameras} cameras registered")

    if recent == 0:
        report(FIX, "no sightings in the last hour - Trace and Alerts will look empty",
               "python scripts/fake_sightings.py --rate 6 --duration 7200 &\n"
               "The route endpoint searches the last 24 hours by default, so stale data means\n"
               "typing a plate into Trace returns nothing at all.")
        return False
    report(PASS, f"{recent} sightings in the last hour")
    return True


# --- 4. the services -----------------------------------------------------------------------

def check_services():
    ok = True
    status, body = _get("http://127.0.0.1:8000/api/healthz")
    if status == 200:
        report(PASS, "API is up on :8000")
    else:
        report(FIX, "API is not answering on :8000", "python scripts/run_stack.py start")
        ok = False

    status, body = _get("http://127.0.0.1:5173/api/cameras")
    if status == 200 and "camera_id" in body:
        report(PASS, "console is up on :5173")
    else:
        report(FIX, "console is not answering on :5173", "python scripts/run_stack.py start")
        ok = False

    status, body = _get("http://127.0.0.1:5173/api/session")
    if status == 200 and "role" in body:
        report(PASS, "console session is live (role switch will work)")
    elif status:
        report(WARN, "console session endpoint is unhappy",
               "The role switch in the rail is how the video shows [C10]. Restart the console.")
    return ok


def check_route():
    """The judged test case, end to end, before a judge tries it."""
    status, body = _get("http://127.0.0.1:5173/api/v1/route?plate=GJ01AB1234", timeout=20,
                        limit=None)
    if status != 200:
        report(FIX, f"route endpoint returned {status}",
               "Is the API up and the console signed in? python scripts/run_stack.py status")
        return False
    import json

    hops = json.loads(body or "{}").get("hops", [])
    if not hops:
        report(FIX, "route for the demo plate returns zero hops",
               "python scripts/fake_sightings.py --rate 6 --duration 7200 &\n"
               "Then wait ~30 s. On camera this looks like the Trace button doing nothing.")
        return False
    report(PASS, f"route for the demo plate returns {len(hops)} hops")
    return True


# --- 5. the wall ---------------------------------------------------------------------------

def check_wall():
    import json

    status, body = _get("http://127.0.0.1:5173/api/wall", timeout=15, limit=None)
    if status != 200:
        report(WARN, "wall state unavailable", "The Wall view will be empty.")
        return False
    cams = json.loads(body or "{}").get("cameras", [])
    with_frames = [c for c in cams if c.get("frames")]
    with_boxes = [c for c in cams if c.get("detections")]

    if not with_frames:
        report(FIX, "no wall tile has a picture yet",
               'curl -X POST -H "Content-Type: application/json" -d "{}" \\\n'
               "     http://127.0.0.1:5173/api/wall/start\n"
               "Then wait two to three minutes - the wall rotates through the cameras a few at\n"
               "a time because the grid allows one session per IP.")
        return False
    report(PASS, f"{len(with_frames)} of {len(cams)} tiles carry a picture")

    if not with_boxes:
        report(WARN, "no tile has detections drawn on it",
               "Usually the console was started with the system python, so the detector could\n"
               "not load. Restart with: python scripts/run_stack.py restart")
    else:
        report(PASS, f"{len(with_boxes)} tiles have detector boxes drawn")

    status, _ = _get("http://127.0.0.1:5173/api/grid", timeout=10)
    grid_state = json.loads(_get("http://127.0.0.1:5173/api/grid", limit=None)[1]
                            or "{}").get("state")
    if grid_state != "signed in":
        report(WARN, f"grid session is '{grid_state}'",
               "Someone else signing in takes our session - the grid allows one per IP. Do not\n"
               "open the grid in a browser while recording.")
    else:
        report(PASS, "grid session is signed in")
    return True


# --- 6. the OCR readers --------------------------------------------------------------------

def check_readers():
    try:
        from services.worker.plate import readers

        names = [r.name for r in readers()]
    except Exception as exc:
        report(WARN, "could not load the OCR readers", f"{type(exc).__name__}: {exc}")
        return False
    if not names:
        report(FIX, "no OCR reader is available - the selftest will read nothing",
               "You are almost certainly on the system python. Use the venv:\n"
               f"  .venv/Scripts/python.exe services/worker/selftest.py")
        return False
    if len(names) < 2:
        report(WARN, f"only one OCR reader loaded ({names[0]})",
               "The vote needs two. Fine for a demo, but do not call it a vote on camera.")
    else:
        report(PASS, f"OCR readers loaded: {', '.join(names)}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true",
                    help="start the stack and the generator, then re-check")
    args = ap.parse_args()

    print("\nPrahari preflight\n" + "-" * 60)
    check_interpreter()
    env_ok = check_env()
    docker_ok = check_docker()
    if env_ok and docker_ok:
        db_ok = check_database()
    else:
        db_ok = False
    services_ok = check_services()

    if args.fix and (not services_ok or not db_ok):
        print("\n--fix: starting what is missing ...\n")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "run_stack.py"), "start"],
                       cwd=str(ROOT))
        if not db_ok:
            subprocess.Popen([sys.executable, str(ROOT / "scripts" / "fake_sightings.py"),
                              "--rate", "6", "--duration", "7200"], cwd=str(ROOT))
            print("started the sighting generator; give it thirty seconds")
        services_ok = check_services()

    if services_ok:
        check_route()
        check_wall()
    check_readers()

    print("-" * 60)
    fixes = [r for r in results if r[0] == FIX]
    warns = [r for r in results if r[0] == WARN]
    print(f"{len(results) - len(fixes) - len(warns)} pass · {len(warns)} warn · {len(fixes)} to fix")
    if fixes:
        print("\nFix these before recording:")
        for _lvl, what, _detail in fixes:
            print(f"  - {what}")
    else:
        print("\nNothing blocking. Good to record.")
    return 1 if fixes else 0


if __name__ == "__main__":
    raise SystemExit(main())
