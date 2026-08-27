"""Prahari API — camera registry, GIS layer and operator console backend.

Model 1 of the challenge framework: a central registry that onboards camera
metadata from any source (bulk import, manual entry, or the upstream catalogue
API) and exposes it as a GIS-ready layer.

The registry merges three sources per camera:
  1. the upstream Sentinel catalogue (/api/ingest)  -- authoritative for URLs
  2. our own survey (grid_survey.json)              -- authoritative for codec,
     resolution and real frame rate, because the catalogue omits or misreports them
  3. the geo table (camera_geo.json)                -- position, operator-correctable

Run:
    uvicorn services.api.main:app --reload --port 8080
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.api.gateway import router as gateway_router

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
WEB = ROOT / "web"

UPSTREAM_BASE = "https://live.corp8.cloud"
CATALOGUE_FILE = DATA / "catalogue" / "ingest.json"
SURVEY_FILE = DATA / "catalogue" / "grid_survey.json"
GEO_FILE = DATA / "camera_geo.json"

app = FastAPI(
    title="Prahari",
    description="Unified CCTV Integration & Video Intelligence Platform",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(gateway_router)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


class RegistryEntry(BaseModel):
    id: str
    name: str
    location: str
    department: str | None = None
    lat: float | None = None
    lon: float | None = None
    geo_precision: str | None = None
    live: bool = False
    reachable: bool = False
    transport: str | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    catalogue_fps: float | None = None
    fps_disagreement: float | None = None
    bitrate_kbps: int | None = None
    hls_url: str | None = None
    upstream_hls_url: str | None = None
    rtsp_url: str | None = None
    webrtc_url: str | None = None
    status: str = "unknown"
    status_detail: str | None = None


# The five departments named on the hackathon site. The catalogue does not carry
# a department field, so it is inferred from the location text until the
# organisers expose one. Inference is transparent, not silently authoritative.
DEPARTMENT_RULES = [
    ("gram panchayat", "Panchayat"),
    ("panchayat", "Panchayat"),
    ("bus port", "GSRTC"),
    ("gsrtc", "GSRTC"),
    ("vidhyalaya", "Municipal"),
    ("tollnaka", "Municipal"),
    ("toll", "Municipal"),
    ("gate", "Police"),
    ("circle", "Police"),
    ("char rasta", "Police"),
    ("tran rasta", "Police"),
    ("teen rasta", "Police"),
    ("bridge", "Municipal"),
    ("bypass", "Police"),
    ("showroom", "Police"),
    ("office", "Municipal"),
    ("park", "Municipal"),
]


def infer_department(location: str) -> str:
    low = (location or "").lower()
    for needle, dept in DEPARTMENT_RULES:
        if needle in low:
            return dept
    return "Unclassified"


def build_registry() -> list[RegistryEntry]:
    catalogue = _read_json(CATALOGUE_FILE, {"cameras": []})
    cameras = catalogue["cameras"] if isinstance(catalogue, dict) else catalogue
    survey_doc = _read_json(SURVEY_FILE, {"cameras": []})
    survey = {str(c["id"]): c for c in survey_doc.get("cameras", [])}
    geo = _read_json(GEO_FILE, {})

    entries: list[RegistryEntry] = []
    for cam in cameras:
        cam_id = str(cam.get("id"))
        surveyed = survey.get(cam_id, {})
        position = geo.get(cam_id, {})

        transport = surveyed.get("use")
        probed = surveyed.get(transport) if transport else None

        hls = cam.get("hls_live_url") or ""
        if hls and not hls.startswith("http"):
            hls = UPSTREAM_BASE + hls

        if transport:
            status, detail = "online", None
        elif surveyed:
            errors = []
            for key in ("hls", "rtsp"):
                err = (surveyed.get(key) or {}).get("error")
                if err:
                    errors.append(f"{key}: {err}")
            detail = " | ".join(errors) or "unreachable"
            if "401" in detail:
                status = "auth_required"
            elif "5XX" in detail or "5xx" in detail:
                status = "upstream_error"
            elif "timeout" in detail:
                status = "timeout"
            else:
                status = "offline"
        else:
            status, detail = "unsurveyed", "not yet probed"

        entries.append(
            RegistryEntry(
                id=cam_id,
                name=cam.get("name") or f"Camera {cam_id}",
                location=cam.get("location") or "",
                department=infer_department(cam.get("location") or ""),
                lat=position.get("lat"),
                lon=position.get("lon"),
                geo_precision=position.get("precision"),
                live=bool(cam.get("live")),
                reachable=bool(transport),
                transport=transport,
                codec=(probed or {}).get("codec") or (cam.get("codec") or None),
                width=(probed or {}).get("width") or (cam.get("width") or None),
                height=(probed or {}).get("height") or (cam.get("height") or None),
                fps=(probed or {}).get("declared_fps") or (cam.get("fps") or None),
                catalogue_fps=cam.get("fps") or None,
                fps_disagreement=surveyed.get("fps_disagreement"),
                bitrate_kbps=cam.get("bitrate_kbps") or None,
                hls_url=f"/stream/{cam_id}/index.m3u8" if hls else None,
                upstream_hls_url=hls or None,
                rtsp_url=cam.get("rtsp_url"),
                webrtc_url=cam.get("webrtc_url"),
                status=status,
                status_detail=detail,
            )
        )
    entries.sort(key=lambda e: int(e.id) if e.id.isdigit() else 0)
    return entries


@app.get("/api/cameras")
def list_cameras() -> dict:
    entries = build_registry()
    by_status: dict[str, int] = {}
    by_department: dict[str, int] = {}
    by_codec: dict[str, int] = {}
    for e in entries:
        by_status[e.status] = by_status.get(e.status, 0) + 1
        by_department[e.department or "?"] = by_department.get(e.department or "?", 0) + 1
        if e.codec:
            by_codec[e.codec] = by_codec.get(e.codec, 0) + 1
    return {
        "summary": {
            "total": len(entries),
            "online": sum(1 for e in entries if e.reachable),
            "geo_exact": sum(1 for e in entries if e.geo_precision == "landmark"),
            "geo_approximate": sum(
                1 for e in entries if e.geo_precision in ("approximate", "curated")
            ),
            "fps_mismatch": sum(1 for e in entries if e.fps_disagreement),
            "by_status": by_status,
            "by_department": by_department,
            "by_codec": by_codec,
        },
        "cameras": [e.model_dump() for e in entries],
    }


@app.get("/api/cameras/{camera_id}")
def get_camera(camera_id: str) -> dict:
    for entry in build_registry():
        if entry.id == camera_id:
            return entry.model_dump()
    raise HTTPException(status_code=404, detail=f"camera {camera_id} not in registry")


class GeoUpdate(BaseModel):
    lat: float
    lon: float


@app.put("/api/cameras/{camera_id}/geo")
def update_geo(camera_id: str, update: GeoUpdate) -> dict:
    """Operator-corrected position. Model 1 requires manual metadata entry, and
    most of our coordinates start as district-centroid approximations."""
    geo = _read_json(GEO_FILE, {})
    entry = geo.get(camera_id, {})
    entry.update(
        {
            "lat": update.lat,
            "lon": update.lon,
            "source": "operator",
            "precision": "operator_verified",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    geo[camera_id] = entry
    GEO_FILE.write_text(json.dumps(geo, indent=2), encoding="utf-8")
    return {"ok": True, "camera_id": camera_id, **entry}


@app.post("/api/registry/sync")
def sync_catalogue() -> dict:
    """Re-pull the upstream catalogue and diff it.

    Camera ids and the set of available cameras change; the catalogue is the
    contract, so the registry polls it rather than trusting a cached copy.
    """
    try:
        resp = requests.get(f"{UPSTREAM_BASE}/api/ingest", timeout=25)
        resp.raise_for_status()
        upstream = resp.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"upstream unreachable: {exc}")

    new_cams = upstream["cameras"] if isinstance(upstream, dict) else upstream
    old = _read_json(CATALOGUE_FILE, {"cameras": []})
    old_cams = old["cameras"] if isinstance(old, dict) else old
    old_ids = {str(c.get("id")) for c in old_cams}
    new_ids = {str(c.get("id")) for c in new_cams}

    CATALOGUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATALOGUE_FILE.write_text(json.dumps(upstream, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "total": len(new_cams),
        "added": sorted(new_ids - old_ids),
        "removed": sorted(old_ids - new_ids),
        "unchanged": len(new_ids & old_ids),
    }


@app.get("/api/health")
def health() -> dict:
    survey = _read_json(SURVEY_FILE, {})
    return {
        "status": "ok",
        "upstream": UPSTREAM_BASE,
        "catalogue_present": CATALOGUE_FILE.exists(),
        "survey_present": SURVEY_FILE.exists(),
        "surveyed_at": survey.get("summary", {}).get("surveyed_at"),
        "server_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


if WEB.exists():
    app.mount("/vendor", StaticFiles(directory=WEB / "vendor"), name="vendor")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    @app.get("/app.js")
    def appjs() -> FileResponse:
        return FileResponse(WEB / "app.js")

    @app.get("/styles.css")
    def styles() -> FileResponse:
        return FileResponse(WEB / "styles.css")
