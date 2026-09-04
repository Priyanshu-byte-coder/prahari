"""Start, check and stop the four processes the console needs. Works without `make`.

    python scripts/run_stack.py start      # API, console, persister, matcher + health checks
    python scripts/run_stack.py status     # what is up, on which port, with what answer
    python scripts/run_stack.py stop
    python scripts/run_stack.py restart

The Makefile calls this rather than duplicating it, because `make` is not present on every
machine this has to run on - including the Windows laptop the demo is recorded from - and a
documented command that only works on the author's box is worse than no command.

Each process gets its own log under `logs/`. They are started detached: killing this script does
not kill them, which is deliberate - the demo must survive the terminal that launched it.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
PIDS = LOGS / "stack.pids"

PY = sys.executable

# name -> (argv, health url, what "healthy" looks like)
SERVICES = {
    "api": ([PY, "-m", "uvicorn", "--factory", "services.api.main:factory",
             "--host", "127.0.0.1", "--port", "8000"],
            "http://127.0.0.1:8000/api/healthz", '{"ok":true}'),
    "console": ([PY, str(ROOT / "scripts" / "console_serve.py"), "--port", "5173"],
                "http://127.0.0.1:5173/api/cameras", "camera_id"),
    "persister": ([PY, str(ROOT / "services" / "api" / "persister.py"),
                   "--duration", "86400"], None, None),
    "matcher": ([PY, str(ROOT / "services" / "api" / "matcher.py"),
                 "--duration", "86400"], None, None),
}


def _get(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:                       # connection refused, DNS, timeout
        return None, type(exc).__name__


def start(only=None):
    LOGS.mkdir(exist_ok=True)
    running = _read_pids()
    started = {}
    for name, (argv, _url, _want) in SERVICES.items():
        if only and name not in only:
            continue
        if name in running and _alive(running[name]):
            print(f"{name:10} already running (pid {running[name]})")
            started[name] = running[name]
            continue
        log = (LOGS / f"{name}.log").open("ab")
        # Detached, so the stack outlives the shell that started it. On Windows that needs an
        # explicit creation flag; on POSIX a new session does the same job.
        kwargs = {"stdout": log, "stderr": subprocess.STDOUT, "cwd": str(ROOT)}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(argv, **kwargs)
        started[name] = proc.pid
        print(f"{name:10} started (pid {proc.pid}) -> logs/{name}.log")
    _write_pids({**running, **started})
    return started


def wait_healthy(deadline_s=45):
    """Poll the HTTP services until they answer, so `start` tells the truth about readiness."""
    checks = {n: (u, w) for n, (_a, u, w) in SERVICES.items() if u}
    deadline = time.time() + deadline_s
    ok = {}
    while time.time() < deadline and len(ok) < len(checks):
        for name, (url, want) in checks.items():
            if name in ok:
                continue
            status, body = _get(url)
            if status == 200 and (not want or want in body):
                ok[name] = True
                print(f"{name:10} healthy  {url}")
        if len(ok) < len(checks):
            time.sleep(2)
    for name in checks:
        if name not in ok:
            print(f"{name:10} DID NOT COME UP - see logs/{name}.log")
    return len(ok) == len(checks)


def status():
    running = _read_pids()
    for name, (_argv, url, want) in SERVICES.items():
        pid = running.get(name)
        alive = pid is not None and _alive(pid)
        line = f"{name:10} {'up  pid ' + str(pid) if alive else 'down':22}"
        if url:
            code, body = _get(url)
            healthy = code == 200 and (not want or want in body)
            line += f"{url:44} {'ok' if healthy else code or body}"
        print(line)


def stop():
    running = _read_pids()
    if not running:
        print("nothing recorded as running; if a process survived, kill it by port")
    for name, pid in running.items():
        if not _alive(pid):
            print(f"{name:10} already gone")
            continue
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"{name:10} stopped (pid {pid})")
        except OSError as exc:
            print(f"{name:10} could not stop pid {pid}: {exc}")
    PIDS.unlink(missing_ok=True)


def _alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, check=False)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pids():
    if not PIDS.exists():
        return {}
    out = {}
    for line in PIDS.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            name, pid = line.split("=", 1)
            if pid.strip().isdigit():
                out[name.strip()] = int(pid.strip())
    return out


def _write_pids(pids):
    LOGS.mkdir(exist_ok=True)
    PIDS.write_text("\n".join(f"{n}={p}" for n, p in pids.items()), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["start", "stop", "restart", "status"])
    ap.add_argument("--only", nargs="*", choices=list(SERVICES),
                    help="act on these services only")
    ap.add_argument("--no-wait", action="store_true", help="do not poll for health after start")
    args = ap.parse_args()

    if args.action in ("stop", "restart"):
        stop()
    if args.action in ("start", "restart"):
        start(args.only)
        if not args.no_wait:
            healthy = wait_healthy()
            print("\nconsole: http://127.0.0.1:5173/" if healthy
                  else "\nsomething did not start - check logs/ before demoing")
            return 0 if healthy else 1
    if args.action == "status":
        status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
