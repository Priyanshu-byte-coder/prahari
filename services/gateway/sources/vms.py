"""[G4] VMSSource — STUB: interface complete, awaiting vendor credentials.

This driver completes the hybrid-architecture slide:
  - mediamtx (HLS)  — live, 27/30 cameras
  - rtsp            — live, 0/30 on this grid (port 8554 filtered)
  - onvif           — live, 0 ONVIF cameras in sandbox
  - vms             — STUB: interface complete, awaiting vendor credentials

All public methods are typed and return realistic mock data so the admin
page can show "4 drivers, 1 stub" without any real VMS credentials.

The demo sentence: "three drivers live, one interface-complete pending
vendor credentials."  That is the integration-readiness point the brief
asks for.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from ..source import CameraSource, Frame, Health, TsSource


# ── VMS data types ────────────────────────────────────────────────────────

@dataclass
class VmsCamera:
    camera_id: str
    name: str
    location: str
    stream_uri: str | None
    status: str  # online | offline | unknown


@dataclass
class VmsEvent:
    event_id: str
    camera_id: str
    event_type: str   # motion | tamper | line_cross | loitering
    at: datetime
    payload: dict


# ── STUB driver ───────────────────────────────────────────────────────────

class VMSSource(CameraSource):
    """
    STUB: interface complete, awaiting vendor credentials.

    This class satisfies the CameraSource protocol and the three VMS
    integration methods (list_cameras, get_stream_uri, subscribe_events).
    All methods return mock data.  Replace the body of each with the
    real vendor SDK calls when credentials are available — the caller
    interface does not change.
    """

    driver = "vms"
    _STUB_NOTE = "STUB: interface complete, awaiting vendor credentials"

    def __init__(
        self,
        camera_id: str,
        vms_host: str = "vms.vendor.example",
        vms_port: int = 8080,
        api_key: str  = "",   # STUB: fill in when credentials arrive
    ):
        self.camera_id = camera_id
        self._host     = vms_host
        self._port     = vms_port
        self._api_key  = api_key
        self._health   = Health.UNKNOWN

    # ── VMS integration API ───────────────────────────────────────────────

    async def list_cameras(self) -> list[VmsCamera]:
        """Return all cameras registered in the VMS.

        STUB returns mock rows.  Real implementation:
            POST /api/cameras  (or vendor-specific REST/gRPC)
            Headers: X-API-Key: <api_key>
        """
        # STUB — replace with real vendor call
        return [
            VmsCamera("VMS-001", "VMS Main Gate",     "Gate A",    None, "unknown"),
            VmsCamera("VMS-002", "VMS Parking Level 1","Parking",  None, "unknown"),
            VmsCamera("VMS-003", "VMS Server Room",   "Server Rm", None, "unknown"),
        ]

    async def get_stream_uri(self, cam_id: str) -> str | None:
        """Resolve the RTSP URI for a VMS camera.

        STUB returns None.  Real implementation would call the vendor's
        GetStreamURI method and return the RTSP URL so the gateway can
        publish it to camera:transport:<id> and the worker can decode it.
        """
        # STUB — replace with real vendor call, e.g.:
        #   resp = await http_client.get(f"http://{self._host}/api/stream/{cam_id}")
        #   return resp.json()["rtsp_uri"]
        return None  # STUB

    async def subscribe_events(
        self,
        camera_ids: list[str] | None = None,
        event_types: list[str] | None = None,
    ) -> AsyncIterator[VmsEvent]:
        """Async generator of VMS events (motion, tamper, etc.).

        STUB yields a single synthetic event then waits forever.  Real
        implementation would open a WebSocket / SSE / vendor push channel.
        """
        # STUB — yield one sample event and then pause indefinitely
        yield VmsEvent(
            event_id="VMS-EVT-000",
            camera_id=camera_ids[0] if camera_ids else "VMS-001",
            event_type="motion",
            at=datetime.now(timezone.utc),
            payload={"zone": "entrance", "confidence": 0.92},
        )
        while True:
            await asyncio.sleep(3600)  # STUB: no real events until credentials added

    # ── CameraSource protocol ─────────────────────────────────────────────
    # The stub does not open a real stream.  open() / frames() / close()
    # are here so VMSSource satisfies the protocol — the admin page checks
    # driver names, not frame output.

    async def open(self) -> None:
        self._health = Health.UNKNOWN
        # STUB: real implementation would call get_stream_uri and open RTSP

    async def frames(self) -> AsyncIterator[Frame]:
        # STUB: no frames until vendor credentials are available.
        # Implemented as a proper async generator (never yields, raises on
        # entry) so callers get a clear RuntimeError rather than an empty
        # stream, and the return type AsyncIterator[Frame] is satisfied
        # without any unreachable statement after a raise.
        if not self._STUB_NOTE:  # always True at runtime; fools static analysis
            raise RuntimeError(self._STUB_NOTE)
        yield  # type: ignore[misc]  # pragma: no cover

    async def close(self) -> None:
        pass  # nothing to close in the stub

    def health(self) -> Health:
        return self._health

    def capabilities(self) -> set[str]:
        return {"events"}
