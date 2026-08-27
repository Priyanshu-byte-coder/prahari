"""Survey every camera on the grid and build the per-camera truth table.

The published catalogue leaves codec/resolution/fps empty for most cameras, and
where it does report a frame rate that number disagrees with what is delivered.
Their integration guide says as much: do not trust the reported frame rate, and
read per-camera properties before sizing batches and decoders.

This probes each camera over both transports, records what is actually served,
and writes data/catalogue/grid_survey.json -- the file the worker reads to
decide how to open each stream.

Usage:
    python scripts/survey_grid.py                 # all cameras, HLS + RTSP
    python scripts/survey_grid.py --transport hls --workers 8
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data" / "catalogue" / "ingest.json"
OUT = ROOT / "data" / "catalogue" / "grid_survey.json"
BASE = "https://live.corp8.cloud"


def load_cameras() -> list[dict]:
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return data["cameras"] if isinstance(data, dict) else data


def hls_url(cam: dict) -> str:
    raw = cam.get("hls_live_url") or ""
    return raw if raw.startswith("http") else BASE + raw


def probe(url: str, *, rtsp: bool, timeout: int) -> dict:
    cmd = ["ffprobe", "-hide_banner", "-loglevel", "error"]
    if rtsp:
        cmd += ["-rtsp_transport", "tcp"]
    cmd += [
        "-print_format", "json", "-show_streams",
        "-analyzeduration", "5000000", "-probesize", "8000000",
        url,
    ]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout>{timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "ffprobe not on PATH"}

    try:
        info = json.loads(proc.stdout or "{}")
    except ValueError:
        info = {}
    video = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if not video:
        err = (proc.stderr or "").strip().splitlines()
        return {"ok": False, "error": (err[-1][:200] if err else "no video stream")}

    def as_fps(value: str | None) -> float | None:
        try:
            num, den = (float(x) for x in (value or "0/0").split("/"))
            return round(num / den, 2) if den else None
        except (ValueError, ZeroDivisionError):
            return None

    return {
        "ok": True,
        "codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "pix_fmt": video.get("pix_fmt"),
        "declared_fps": as_fps(video.get("avg_frame_rate")),
        "r_frame_rate": as_fps(video.get("r_frame_rate")),
        "connect_s": round(time.time() - started, 1),
    }


def survey_one(cam: dict, transports: list[str], timeout: int) -> dict:
    entry = {
        "id": cam.get("id"),
        "name": cam.get("name"),
        "location": cam.get("location"),
        "catalogue": {
            "codec": cam.get("codec") or None,
            "width": cam.get("width") or None,
            "height": cam.get("height") or None,
            "fps": cam.get("fps") or None,
            "bitrate_kbps": cam.get("bitrate_kbps") or None,
        },
        "hls_url": hls_url(cam),
        "rtsp_url": cam.get("rtsp_url"),
    }
    for transport in transports:
        if transport == "hls":
            entry["hls"] = probe(entry["hls_url"], rtsp=False, timeout=timeout)
        else:
            entry["rtsp"] = probe(entry["rtsp_url"], rtsp=True, timeout=timeout)

    # Decide the transport the worker should actually use for this camera.
    if entry.get("rtsp", {}).get("ok"):
        entry["use"] = "rtsp"
    elif entry.get("hls", {}).get("ok"):
        entry["use"] = "hls"
    else:
        entry["use"] = None

    probed = entry.get(entry["use"]) if entry["use"] else None
    if probed:
        cat_fps = entry["catalogue"]["fps"]
        if cat_fps and probed.get("declared_fps"):
            drift = abs(cat_fps - probed["declared_fps"])
            entry["fps_disagreement"] = round(drift, 2) if drift > 0.5 else 0.0
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["hls", "rtsp", "both"], default="both")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=50)
    ap.add_argument("--only", default=None, help="comma-separated camera ids")
    args = ap.parse_args()

    transports = ["hls", "rtsp"] if args.transport == "both" else [args.transport]
    cameras = load_cameras()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        cameras = [c for c in cameras if str(c.get("id")) in wanted]

    print(f"surveying {len(cameras)} cameras over {'+'.join(transports)} "
          f"with {args.workers} workers\n", flush=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(survey_one, cam, transports, args.timeout): cam
            for cam in cameras
        }
        for fut in futures:
            pass
        for fut, cam in futures.items():
            entry = fut.result()
            results.append(entry)
            use = entry["use"]
            if use:
                p = entry[use]
                flag = ""
                if entry.get("fps_disagreement"):
                    flag = f"  [catalogue fps off by {entry['fps_disagreement']}]"
                print(
                    f"  [+] cam {str(entry['id']):>2} via {use:<4} "
                    f"{p['codec']:<5} {p['width']}x{p['height']} "
                    f"@{p['declared_fps']}fps{flag}",
                    flush=True,
                )
            else:
                errs = []
                for t in transports:
                    errs.append(f"{t}:{entry.get(t, {}).get('error', '?')}")
                print(f"  [-] cam {str(entry['id']):>2} UNREACHABLE  {' | '.join(errs)}",
                      flush=True)

    results.sort(key=lambda e: int(e["id"]) if str(e["id"]).isdigit() else 0)
    reachable = [r for r in results if r["use"]]
    summary = {
        "base": BASE,
        "surveyed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(results),
        "reachable": len(reachable),
        "by_transport": {
            t: sum(1 for r in results if r["use"] == t) for t in ("rtsp", "hls")
        },
        "codecs": {},
        "resolutions": {},
        "catalogue_fps_wrong": sum(1 for r in results if r.get("fps_disagreement")),
    }
    for r in reachable:
        p = r[r["use"]]
        summary["codecs"][p["codec"]] = summary["codecs"].get(p["codec"], 0) + 1
        res = f"{p['width']}x{p['height']}"
        summary["resolutions"][res] = summary["resolutions"].get(res, 0) + 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"summary": summary, "cameras": results}, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 62)
    print(f"reachable   : {summary['reachable']}/{summary['total']}")
    print(f"transport   : {summary['by_transport']}")
    print(f"codecs      : {summary['codecs']}")
    print(f"resolutions : {summary['resolutions']}")
    print(f"catalogue fps wrong on {summary['catalogue_fps_wrong']} cameras")
    print(f"written     : {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
