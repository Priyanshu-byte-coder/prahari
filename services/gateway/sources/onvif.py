"""[G4] ONVIFSource — WS-Discovery + GetStreamUri, then publish to camera:transport:<id>.

Driver flow:
  1. WS-Discovery broadcast → collect responding devices on the subnet.
  2. GetProfiles  → pick the first token whose resolution is highest.
  3. GetStreamUri → resolve the RTSP URL for that profile.
  4. Publish `{url, transport:"rtsp", driver:"onvif", probed_at}` to Redis,
     exactly like probe.py does for the grid cameras — same key, same shape.
  5. Expose PTZ: ContinuousMove / Stop wrapped as async methods.

When python-onvif-zeep is absent the module still imports cleanly and
ONVIFSource raises a descriptive RuntimeError on open() rather than
an ImportError that would crash the whole gateway.

PTZ usage:
    src = ONVIFSource(camera_id="ONVIF-001", host="192.168.1.42", port=80,
                      username="admin", password="admin")
    await src.open()
    await src.ptz_move(pan=0.2, tilt=0.0, zoom=0.0)
    await asyncio.sleep(1)
    await src.ptz_stop()
    async for frame in src.frames():
        ...
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from ..source import (
    STREAM_ERRORS,
    CameraSource,
    Frame,
    Health,
    TsSource,
    next_backoff,
    sleep_backoff,
)

log = logging.getLogger(__name__)

try:
    from onvif import ONVIFCamera  # python-onvif-zeep
    _ONVIF_OK = True
except ImportError:
    _ONVIF_OK = False

try:
    import av
except ImportError:  # pragma: no cover
    av = None

OPEN_OPTIONS = {
    "rtsp_transport": "tcp",
    "stimeout":       "5000000",
    "max_delay":      "500000",
}


class ONVIFSource(CameraSource):
    """Live ONVIF driver: WS-Discovery → GetProfiles → GetStreamUri → RTSP."""

    driver = "onvif"

    def __init__(
        self,
        camera_id: str,
        host: str,
        port: int = 80,
        username: str = "admin",
        password: str = "admin",
    ):
        self.camera_id  = camera_id
        self._host      = host
        self._port      = port
        self._username  = username
        self._password  = password
        self._rtsp_url: str | None = None
        self._container = None
        self._ptz       = None
        self._profile_token: str | None = None
        self._health    = Health.UNKNOWN
        self._last_frame_at: float | None = None
        self._backoff: float | None = None
        self._closed    = False  # set by close(); stops the frames() generator

    # ── Discovery (class-level helper) ────────────────────────────────────

    @classmethod
    async def discover(cls, timeout: float = 3.0) -> list[dict]:
        """WS-Discovery broadcast → list of {address, host} dicts.

        Returns an empty list when python-onvif-zeep is not installed or
        when no ONVIF devices respond in time.
        """
        if not _ONVIF_OK:
            return []
        try:
            from wsdiscovery import WSDiscovery  # type: ignore
            wsd = WSDiscovery()
            wsd.start()
            await asyncio.sleep(timeout)
            services = wsd.searchServices()
            wsd.stop()
            return [
                {"address": str(svc.getXAddrs()[0]) if svc.getXAddrs() else "", "service": svc}
                for svc in services
            ]
        except Exception as exc:  # noqa: BLE001 — discovery failure is non-fatal
            log.debug("ONVIF discovery error: %s", exc)
            return []

    # ── CameraSource protocol ──────────────────────────────────────────────

    async def open(self) -> None:
        if not _ONVIF_OK:
            raise RuntimeError(
                "python-onvif-zeep not installed; `pip install onvif-zeep`"
            )
        if av is None:
            raise RuntimeError("PyAV not installed; `pip install av`")

        cam = await asyncio.to_thread(
            ONVIFCamera, self._host, self._port, self._username, self._password
        )

        # GetProfiles — pick the highest-resolution token
        media  = await asyncio.to_thread(cam.create_media_service)
        profiles = await asyncio.to_thread(media.GetProfiles)
        token = self._best_profile_token(profiles)
        self._profile_token = token

        # GetStreamUri
        req = media.create_type("GetStreamUri")
        req.ProfileToken = token
        req.StreamSetup  = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
        uri_resp = await asyncio.to_thread(media.GetStreamUri, req)
        self._rtsp_url = str(uri_resp.Uri)
        log.info("ONVIF cam %s → %s", self.camera_id, self._rtsp_url)

        # Open RTSP stream with PyAV
        self._container = await asyncio.to_thread(
            av.open, self._rtsp_url, options=OPEN_OPTIONS, timeout=10
        )
        self._health         = Health.LIVE
        self._last_frame_at  = time.time()
        self._backoff        = None

        # PTZ service (optional — not all ONVIF cameras have it)
        try:
            self._ptz = await asyncio.to_thread(cam.create_ptz_service)
        except Exception:  # noqa: BLE001
            self._ptz = None

    @staticmethod
    def _best_profile_token(profiles) -> str:
        """Pick the profile with the highest pixel count."""
        best, best_px = None, 0
        for p in profiles:
            try:
                vconf = p.VideoEncoderConfiguration
                w = vconf.Resolution.Width
                h = vconf.Resolution.Height
                if w * h > best_px:
                    best, best_px = p.token, w * h
            except AttributeError:
                pass
        if best is None and profiles:
            best = profiles[0].token
        return best or ""

    async def frames(self) -> AsyncIterator[Frame]:
        while not self._closed:
            if self._container is None:
                try:
                    await self.open()
                except STREAM_ERRORS:
                    self._health  = Health.DOWN
                    self._backoff = next_backoff(self._backoff)
                    await sleep_backoff(self._backoff)
                    continue

            try:
                stream    = self._container.streams.video[0]
                time_base = float(stream.time_base) if stream.time_base else None
                for packet in self._container.demux(stream):
                    for frame in packet.decode():
                        self._last_frame_at = time.time()
                        self._health        = Health.LIVE
                        pts = (
                            float(frame.pts) * time_base
                            if frame.pts is not None and time_base
                            else None
                        )
                        yield Frame(
                            image=frame.to_ndarray(format="bgr24"),
                            pts=pts,
                            wall_ts=self._last_frame_at,
                            ts_source=TsSource.RTSP_PTS,
                        )
                # Normal EOF — reconnect
                await self.close()
                self._health  = Health.DOWN
                self._backoff = next_backoff(self._backoff)
                await sleep_backoff(self._backoff)
            except STREAM_ERRORS:
                await self.close()
                self._health  = Health.DOWN
                self._backoff = next_backoff(self._backoff)
                await sleep_backoff(self._backoff)

    async def close(self) -> None:
        self._closed = True
        if self._container is not None:
            container, self._container = self._container, None
            try:
                container.close()
            except STREAM_ERRORS as exc:
                log.debug("onvif close(%s): %s", self.camera_id, exc)

    def health(self) -> Health:
        return self._health

    def capabilities(self) -> set[str]:
        caps = {"snapshot"}
        if self._ptz is not None:
            caps.add("ptz")
        return caps

    # ── PTZ helpers ───────────────────────────────────────────────────────

    async def ptz_move(self, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0) -> None:
        """ContinuousMove — values in [-1, 1]."""
        if self._ptz is None or self._profile_token is None:
            raise RuntimeError("PTZ not available on this camera")
        req = self._ptz.create_type("ContinuousMove")
        req.ProfileToken = self._profile_token
        req.Velocity = {
            "PanTilt": {"x": pan,  "y": tilt},
            "Zoom":    {"x": zoom},
        }
        await asyncio.to_thread(self._ptz.ContinuousMove, req)

    async def ptz_stop(self, pan_tilt: bool = True, zoom: bool = True) -> None:
        """Stop any ongoing PTZ movement."""
        if self._ptz is None or self._profile_token is None:
            return
        req = self._ptz.create_type("Stop")
        req.ProfileToken = self._profile_token
        req.PanTilt = pan_tilt
        req.Zoom    = zoom
        await asyncio.to_thread(self._ptz.Stop, req)

    def rtsp_url(self) -> str | None:
        """The resolved RTSP URL — published to camera:transport:<id> by the gateway."""
        return self._rtsp_url
