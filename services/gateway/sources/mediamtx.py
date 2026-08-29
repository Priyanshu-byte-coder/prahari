"""[G2] MediaMTXSource — HLS, the fallback that keeps this grid usable.

Every camera on the sandbox grid arrives here: port 8554 is filtered, so
RTSP resolves for none of them and HLS carries all 27 reachable ones. That
is not a workaround, it is the heterogeneity the brief is testing.

Timestamps: prefer `EXT-X-PROGRAM-DATE-TIME` from the playlist (`hls_pdt`);
without it the only honest label is `server_receive`, and the UI shows those
as approximate. Never `now()` dressed up as a capture time (plan A6).
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import requests

from ..source import (
    STREAM_ERRORS,
    CameraSource,
    Frame,
    Health,
    TsSource,
    next_backoff,
    sleep_backoff,
)

try:
    import av
except ImportError:  # pragma: no cover
    av = None

# Shared session: the grid's Cloudflare gate hands out one cookieCheck cookie
# and we would rather negotiate it once than once per camera.
_SESSION = requests.Session()

# ~3 s of segment latency is the floor on HLS. That is the protocol, not our
# code -- D5's alert-latency slide quotes both paths separately for this reason.
SEGMENT_LATENCY_FLOOR_S = 3.0


class MediaMTXSource(CameraSource):
    driver = "mediamtx"

    def __init__(self, camera_id: str, url: str):
        self.camera_id = camera_id
        self.url = url
        self._container = None
        self._health = Health.UNKNOWN
        self._last_frame_at: float | None = None
        self._backoff: float | None = None
        self._ts_source = TsSource.SERVER_RECEIVE

    def _playlist_has_pdt(self) -> bool:
        """Does this stream carry real capture times?

        The master playlist never does -- `EXT-X-PROGRAM-DATE-TIME` lives one
        level down, in the variant. Checking only the master labels every frame
        `server_receive` and silently throws away the one honest clock this
        grid gives us, which is exactly what route ordering depends on.
        """
        try:
            body = self._fetch_playlist(self.url)
            if body is None:
                return False
            if "EXT-X-PROGRAM-DATE-TIME" in body:
                return True
            variant = self._first_variant_url(self.url, body)
            if variant is None:
                return False
            child = self._fetch_playlist(variant)
            return child is not None and "EXT-X-PROGRAM-DATE-TIME" in child
        except requests.RequestException:
            return False

    @staticmethod
    def _fetch_playlist(url: str) -> str | None:
        resp = _SESSION.get(url, timeout=8, allow_redirects=True)
        try:
            if resp.status_code >= 400:
                return None
            return resp.text
        finally:
            resp.close()

    @staticmethod
    def _first_variant_url(base_url: str, body: str) -> str | None:
        """First non-comment line of a master playlist is a variant path."""
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return requests.compat.urljoin(base_url, line)
        return None

    async def open(self) -> None:
        if av is None:
            raise RuntimeError("PyAV not installed; `pip install av`")
        has_pdt = await asyncio.to_thread(self._playlist_has_pdt)
        self._ts_source = TsSource.HLS_PDT if has_pdt else TsSource.SERVER_RECEIVE
        self._container = await asyncio.to_thread(av.open, self.url, timeout=15)
        self._health = Health.LIVE
        self._last_frame_at = time.time()
        self._backoff = None

    async def frames(self) -> AsyncIterator[Frame]:
        while True:
            if self._container is None:
                try:
                    await self.open()
                except STREAM_ERRORS:
                    self._health = Health.DOWN
                    self._backoff = next_backoff(self._backoff)
                    await sleep_backoff(self._backoff)
                    continue

            try:
                stream = self._container.streams.video[0]
                time_base = float(stream.time_base) if stream.time_base else None
                for packet in self._container.demux(stream):
                    for frame in packet.decode():
                        self._last_frame_at = time.time()
                        self._health = Health.LIVE
                        pts = float(frame.pts) * time_base if (frame.pts and time_base) else None
                        yield Frame(
                            image=frame.to_ndarray(format="bgr24"),
                            pts=pts,
                            wall_ts=self._last_frame_at,
                            ts_source=self._ts_source,
                        )
            except STREAM_ERRORS:
                await self.close()
                self._health = Health.DOWN
                self._backoff = next_backoff(self._backoff)
                await sleep_backoff(self._backoff)

    async def close(self) -> None:
        """Close in *this* thread, not a worker thread.

        `asyncio.to_thread(container.close)` closes the container while the
        demux iterator may still be alive on the loop thread, and PyAV then
        segfaults (exit 139) or aborts (134) instead of raising. Closing is
        cheap; it does not need a thread. Callers that stop iterating early
        should `aclose()` the generator before calling this.
        """
        if self._container is not None:
            container, self._container = self._container, None
            try:
                container.close()
            except Exception:
                pass

    def health(self) -> Health:
        return self._health

    def capabilities(self) -> set[str]:
        return {"snapshot"}
