"""One-off: sign in to the live grid, capture every camera's HLS feed to a local
clip, run the worker pipeline over each clip, and print every plate tracked per
camera.

    GRID_EMAIL=... GRID_KEY=... python scripts/grid_harvest.py --seconds 90

Why it captures to a local file first: the gateway (probe.py / MediaMTXSource)
only knows the old Cloudflare cookieCheck gate, and handing ffmpeg's HLS demuxer
a cookie-gated, flaky playlist churns through AVERROR_EXIT / "invalid data"
reconnects. Pulling the segments over `requests` (cookie attached, retried,
AES-128 handled) into one MPEG-TS clip removes ffmpeg's networking and auth from
the path entirely; the worker then decodes a plain local file.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests

import scripts.console_serve as console

GRID_BASE = "https://cctv.corp8.cloud"


# --- sign-in ------------------------------------------------------------------------------

def sign_in() -> tuple[str, str]:
    for attempt in range(1, 8):
        try:
            if console.grid_login():
                return console.GRID["cookie"], console.GRID_UA
        except Exception as exc:  # pragma: no cover
            console.GRID["detail"] = f"{type(exc).__name__}: {exc}"
        print(f"    sign-in attempt {attempt}: {console.GRID['state']} "
              f"- {console.GRID['detail']}; retrying", flush=True)
        time.sleep(min(4 * attempt, 20))
    raise SystemExit(f"grid sign-in failed: {console.GRID['state']} - {console.GRID['detail']}")


def _get(sess, url, ua, cookie, tries=5, **kw):
    last = None
    for i in range(1, tries + 1):
        try:
            r = sess.get(url, headers={"User-Agent": ua, "Cookie": cookie},
                         timeout=kw.pop("timeout", 25), **kw)
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            time.sleep(min(3 * i, 15))
    raise RuntimeError(f"GET {url} failed after {tries}: {last}")


def catalogue(sess, cookie, ua) -> list[dict]:
    return json.loads(_get(sess, f"{GRID_BASE}/cameras.json", ua, cookie).text)


# --- HLS capture -------------------------------------------------------------------------

def _parse_playlist(text: str, base_url: str):
    """Return (is_master, entries). entries for master: [(bandwidth, url)];
    for media: dict(target, seq, key, segments=[(url, seq)])."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if any(ln.startswith("#EXT-X-STREAM-INF") for ln in lines):
        variants = []
        for i, ln in enumerate(lines):
            if ln.startswith("#EXT-X-STREAM-INF"):
                bw = 0
                for part in ln.split(":", 1)[1].split(","):
                    if part.strip().startswith("BANDWIDTH="):
                        bw = int(part.split("=", 1)[1])
                if i + 1 < len(lines):
                    variants.append((bw, urllib.parse.urljoin(base_url, lines[i + 1])))
        return True, variants
    seq = 0
    target = 6.0
    key = None
    segs = []
    cur = seq
    for ln in lines:
        if ln.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            seq = int(ln.split(":", 1)[1]); cur = seq
        elif ln.startswith("#EXT-X-TARGETDURATION:"):
            target = float(ln.split(":", 1)[1])
        elif ln.startswith("#EXT-X-KEY:"):
            attrs = {}
            for part in ln.split(":", 1)[1].split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    attrs[k.strip()] = v.strip().strip('"')
            key = attrs
        elif not ln.startswith("#"):
            segs.append((urllib.parse.urljoin(base_url, ln), cur))
            cur += 1
    return False, {"target": target, "seq": seq, "key": key, "segments": segs}


def _decrypt(data: bytes, key_bytes: bytes, seq: int, iv_hex: str | None) -> bytes:
    from Crypto.Cipher import AES
    if iv_hex:
        iv = bytes.fromhex(iv_hex[2:] if iv_hex.lower().startswith("0x") else iv_hex)
    else:
        iv = seq.to_bytes(16, "big")
    return AES.new(key_bytes, AES.MODE_CBC, iv).decrypt(data)


FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def capture_hls(cid, cookie, ua, seconds, outdir) -> Path | None:
    """Capture `seconds` of the camera's HLS to a local MPEG-TS with the ffmpeg CLI.

    ffmpeg handles the cookie-gated playlist, AES-128, and mid-stream reconnects, and
    `-t` + a subprocess timeout give a hard wall-clock bound so one stalled feed can
    never wedge the run (which the PyAV interrupt-callback path did).
    """
    out = Path(outdir) / f"{cid}.ts"
    out.unlink(missing_ok=True)
    url = f"{GRID_BASE}/{cid}/index.m3u8"
    cmd = [
        FFMPEG, "-nostdin", "-loglevel", "error", "-y",
        "-headers", f"Cookie: {cookie}\r\nUser-Agent: {ua}\r\n",
        "-user_agent", ua,
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "8",
        "-rw_timeout", "15000000",
        "-i", url,
        "-t", str(int(seconds)), "-c", "copy", "-f", "mpegts", str(out),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 45)
    except subprocess.TimeoutExpired:
        print(f"  [{cid}] ffmpeg timed out (kept partial)", flush=True)
    else:
        if p.returncode != 0 and not out.exists():
            print(f"  [{cid}] ffmpeg failed: {(p.stderr or '').strip()[:200]}", flush=True)
            return None
    if not out.exists() or out.stat().st_size < 8192:
        out.unlink(missing_ok=True)
        print(f"  [{cid}] no usable feed", flush=True)
        return None
    print(f"  [{cid}] captured {out.stat().st_size // 1024} KiB", flush=True)
    return out


# --- pipeline ---------------------------------------------------------------------------

def run_pipeline(clips: dict[str, Path], publisher, backend):
    from services.worker.run import Worker
    per_cam: dict[str, list[dict]] = defaultdict(list)
    for cid, clip in clips.items():
        worker = Worker({cid: str(clip)}, backend=backend, publisher=publisher,
                        once=True, motion_gate=True)
        try:
            worker.run(seconds=600)
        except Exception as exc:
            print(f"  [{cid}] pipeline error: {type(exc).__name__}: {exc}", flush=True)
    return per_cam


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90.0, help="capture window per camera")
    ap.add_argument("--workers", type=int, default=6, help="cameras captured in parallel")
    ap.add_argument("--only", help="comma-separated camera ids")
    ap.add_argument("--clipdir", default=str(ROOT / "runs" / "grid_clips"))
    ap.add_argument("--out", default=str(ROOT / "runs" / "grid_plates.json"))
    args = ap.parse_args()

    sess = requests.Session()
    cookie, ua = sign_in()
    print(f"[+] signed in; cookie {cookie[:32]}...", flush=True)
    cams = catalogue(sess, cookie, ua)
    if args.only:
        want = set(args.only.split(","))
        cams = [c for c in cams if c["id"] in want]
    names = {c["id"]: c["name"] for c in cams}
    print(f"[+] {len(cams)} cameras; capturing {args.seconds:.0f}s each, "
          f"{args.workers} in parallel", flush=True)

    Path(args.clipdir).mkdir(parents=True, exist_ok=True)
    clips: dict[str, Path] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(capture_hls, c["id"], cookie, ua, args.seconds, args.clipdir): c["id"]
                for c in cams}
        for fut in as_completed(futs):
            cid = futs[fut]
            try:
                p = fut.result()
                if p:
                    clips[cid] = p
            except Exception as exc:
                print(f"  [{cid}] capture crashed: {exc}", flush=True)

    print(f"\n[+] captured {len(clips)}/{len(cams)} cameras; running pipeline", flush=True)

    try:
        import fakeredis
        client = fakeredis.FakeRedis()
    except ImportError:
        raise SystemExit("pip install fakeredis")
    stream = "sightings-grid"
    from services.worker.publish import Publisher
    from services.worker.backend import LocalBackend
    publisher = Publisher(redis_client=client, stream=stream)
    backend = LocalBackend()

    from services.worker.run import Worker
    per_cam: dict[str, list[dict]] = defaultdict(list)
    seen_ids: set[str] = set()
    warmed = False
    for cid, clip in sorted(clips.items()):
        worker = Worker({cid: str(clip)}, backend=backend, publisher=publisher,
                        once=True, motion_gate=True)
        if not warmed:
            worker.warm(); warmed = True
        t0 = time.time()
        try:
            worker.run(seconds=900)
        except Exception as exc:
            print(f"  [{cid}] pipeline error: {type(exc).__name__}: {exc}", flush=True)
        for _id, fields in client.xrange(stream, min="-", max="+"):
            k = _id.decode() if isinstance(_id, bytes) else _id
            if k in seen_ids:
                continue
            seen_ids.add(k)
            raw = fields.get(b"data") or fields.get("data")
            row = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            per_cam[row["camera_id"]].append(row)
        print(f"  [{cid}] {time.time()-t0:.0f}s, "
              f"{len(per_cam.get(cid, []))} sightings", flush=True)

    # report
    print("\n" + "=" * 90)
    print(f"{'cam':<7} {'name':<46} plates (band, conf)")
    print("-" * 90)
    result = []
    for c in cams:
        cid = c["id"]
        rows = per_cam.get(cid, [])
        plates: dict[str, dict] = {}
        for r in rows:
            p = r.get("plate_text")
            if not p:
                continue
            cur = plates.get(p)
            if cur is None or r.get("plate_conf", 0) > cur["conf"]:
                plates[p] = {"conf": round(r.get("plate_conf", 0), 3),
                             "band": r.get("plate_band"),
                             "vehicle": r.get("vehicle_class")}
        listing = "  ".join(f"{k} ({v['band']},{v['conf']})"
                            for k, v in plates.items()) or "-"
        note = "" if cid in clips else "  [no feed captured]"
        print(f"{cid:<7} {c['name'][:46]:<46} {listing}{note}")
        result.append({"camera_id": cid, "name": c["name"],
                       "captured": cid in clips, "sightings": len(rows),
                       "plates": [{"plate": k, **v} for k, v in plates.items()]})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))
    tp = sum(len(r["plates"]) for r in result)
    print("-" * 90)
    print(f"{tp} distinct plates across {len(clips)}/{len(cams)} captured cameras -> {args.out}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("YOLO_VERBOSE", "0")
    raise SystemExit(main())
