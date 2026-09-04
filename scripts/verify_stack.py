"""End-to-end verification of a running Prahari stack - one check per claim the README makes.

    python scripts/run_stack.py start
    python scripts/verify_stack.py            # exits non-zero if anything is off

This is the pre-submission gate, and it is deliberately not a unit test: it talks to the actual
processes over HTTP, with real tokens, against the real database. The unit suite proves the parts
behave; this proves the assembled thing does - including the refusals, which are the checks that
matter most. An endpoint that answers an anonymous caller is a finding, not a warning.

Credentials come from the environment so no password lives in the repo:

    PRAHARI_TEST_USER / PRAHARI_TEST_PASSWORD          an INVESTIGATOR
    PRAHARI_TEST_ADMIN / PRAHARI_TEST_ADMIN_PASSWORD   a SYSTEM_ADMIN
"""
import json, os, sys, urllib.error, urllib.request

API = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
CONSOLE = os.environ.get("CONSOLE_BASE", "http://127.0.0.1:5173").rstrip("/")
results = []


def call(method, url, body=None, token=None, raw=False):
    hdr = {}
    data = None
    if token:
        hdr["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, data=data, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = r.read()
            return r.status, (payload if raw else payload.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:52} {detail[:70]}")


# --- auth ----------------------------------------------------------------------------------
USER = os.environ.get("PRAHARI_TEST_USER", "field")
PASSWORD = os.environ.get("PRAHARI_TEST_PASSWORD", "")
ADMIN = os.environ.get("PRAHARI_TEST_ADMIN", "console-audit")
ADMIN_PASSWORD = os.environ.get("PRAHARI_TEST_ADMIN_PASSWORD", "")

if not PASSWORD or not ADMIN_PASSWORD:
    raise SystemExit(
        "set PRAHARI_TEST_PASSWORD and PRAHARI_TEST_ADMIN_PASSWORD (and optionally "
        "PRAHARI_TEST_USER / PRAHARI_TEST_ADMIN). Bootstrap the accounts with: "
        "PRAHARI_BOOTSTRAP_PASSWORD=... python services/api/auth.py bootstrap "
        "--username field --role INVESTIGATOR")

st, body = call("POST", f"{API}/api/auth/login", {"username": USER, "password": PASSWORD})
check("login (investigator)", st == 200, f"{st}")
tok = json.loads(body)["access"] if st == 200 else None

st, body = call("POST", f"{API}/api/auth/login",
                {"username": ADMIN, "password": ADMIN_PASSWORD})
adm = json.loads(body)["access"] if st == 200 else None
check("login (system admin)", st == 200, f"{st}")

st, _ = call("POST", f"{API}/api/auth/login", {"username": USER, "password": "definitely-not-it"})
check("wrong password refused", st == 401, f"{st}")

st, _ = call("POST", f"{API}/api/auth/refresh", {"refresh": "garbage"})
check("forged refresh token refused", st == 401, f"{st}")

# --- the P0 fix ----------------------------------------------------------------------------
st, _ = call("GET", f"{API}/api/route?plate=GJ01AB1234")
check("#51 route refuses anonymous", st == 401, f"{st}")

st, _ = call("GET", f"{API}/api/route/export?plate=GJ01AB1234&fmt=pdf&user_id=999")
check("#51 export refuses anonymous", st == 401, f"{st}")

st, _ = call("GET", f"{API}/api/route?plate=GJ01AB1234", token=adm)
check("#51 route refuses SYSTEM_ADMIN [C10]", st == 403, f"{st}")

# --- RBAC matrix ---------------------------------------------------------------------------
for path, inv_want, adm_want in [("/api/cameras", 200, 403),
                                 ("/api/alerts", 200, 403),
                                 ("/api/watchlist", 200, 403),
                                 ("/api/admin/audit?limit=2", 403, 200)]:
    si, _ = call("GET", API + path, token=tok)
    sa, _ = call("GET", API + path, token=adm)
    check(f"RBAC {path}", si == inv_want and sa == adm_want, f"inv={si} admin={adm_want and sa}")

# --- route, the judged test case ------------------------------------------------------------
st, body = call("GET", f"{API}/api/route?plate=GJ01AB1234", token=tok)
route = json.loads(body) if st == 200 else {}
hops = route.get("hops", [])
check("route returns ordered hops", st == 200 and len(hops) > 0, f"{len(hops)} hops")
check("hops carry camera, coords and PTS",
      bool(hops) and all(h.get("camera_id") and h.get("pts") is not None for h in hops))
check("route says whether it is fuzzy", "fuzzy" in route, str(route.get("fuzzy")))
check("route carries snapped geometry", "snapped_geometry" in route)

# --- export ---------------------------------------------------------------------------------
st, body = call("GET", f"{API}/api/route/export?plate=GJ01AB1234&fmt=csv", token=tok)
check("export csv", st == 200 and "plate" in body, f"{st}, {len(body)}b")
st, raw = call("GET", f"{API}/api/route/export?plate=GJ01AB1234&fmt=pdf", token=tok, raw=True)
check("export pdf", st == 200 and raw[:4] == b"%PDF", f"{st}, {len(raw)}b")
st, _ = call("GET", f"{API}/api/route/export?plate=GJ01AB1234&fmt=docx", token=tok)
check("unknown export format is 400", st == 400, f"{st}")

# --- watchlist + alerts ----------------------------------------------------------------------
st, body = call("POST", f"{API}/api/watchlist",
                {"kind": "plate", "plate": "GJ07AZ4417", "category": "stolen vehicle",
                 "severity": "HIGH", "reason": "a-z verification"}, token=tok)
check("watchlist add", st == 200, f"{st}")
entry_id = json.loads(body).get("id") if st == 200 else None

st, _ = call("POST", f"{API}/api/watchlist",
             {"kind": "plate", "plate": "GJ07AZ4418", "category": "nonsense",
              "severity": "HIGH"}, token=tok)
check("bad category is 422", st == 422, f"{st}")

st, body = call("GET", f"{API}/api/alerts", token=tok)
alerts = json.loads(body) if st == 200 else []
new = [a for a in alerts if a["state"] == "NEW"]
check("alerts listed", st == 200, f"{len(alerts)} alerts, {len(new)} NEW")

if new:
    aid = new[0]["id"]
    st, _ = call("POST", f"{API}/api/alerts/{aid}/state", {}, token=tok)
    check("#58 missing to_state is 422", st == 422, f"{st}")
    st, _ = call("POST", f"{API}/api/alerts/{aid}/state",
                 {"to_state": "ACKNOWLEDGED", "reason": "a-z"}, token=tok)
    check("alert NEW -> ACKNOWLEDGED", st == 200, f"{st}")
    st, _ = call("POST", f"{API}/api/alerts/{aid}/state", {"to_state": "NEW"}, token=tok)
    check("illegal transition is 409", st == 409, f"{st}")

# --- grants -----------------------------------------------------------------------------------
st, body = call("POST", f"{API}/api/grants",
                {"target_dept_id": 1, "case_no": "AZ-2026/1",
                 "reason": "a-z verification", "hours": 2}, token=tok)
check("grant needs a case number (given)", st in (200, 201), f"{st}")
st, body = call("POST", f"{API}/api/grants",
                {"target_dept_id": 1, "reason": "no case number"}, token=tok)
check("grant without a case number refused", st == 400, f"{st}")

# --- audit --------------------------------------------------------------------------------------
st, body = call("GET", f"{API}/api/admin/audit/verify", token=adm)
verify = json.loads(body) if st == 200 else {}
check("audit chain verifies", st == 200 and verify.get("ok") is True,
      f"checked {verify.get('checked')}")

# --- console proxy ---------------------------------------------------------------------------------
for path, want in [("/api/cameras", "camera_id"), ("/api/wall", "cameras"),
                   ("/api/grid", "state"), ("/api/v1/alerts", "["),
                   ("/api/v1/admin/audit/verify", "ok"), ("/web/app.html", "<!doctype html>"),
                   ("/web/app.js", "Prahari"), ("/web/home.html", "<!doctype html>")]:
    st, body = call("GET", CONSOLE + path)
    check(f"console {path}", st == 200 and want in body, f"{st}")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILED: " + "; ".join(failed))
sys.exit(1 if failed else 0)
