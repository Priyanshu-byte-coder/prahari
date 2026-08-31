"""[G2] RTSPSource — generic RTSP over TCP, via PyAV.

UDP dies across NAT and firewalls; `rtsp_transport=tcp` is non-negotiable.

Two failure modes this handles that a plain try/except does not:
  - a connection that never opens  -> exponential backoff, 1/2/4...30 s
  - a connection that opens and then silently stops delivering frames
    -> watchdog, because a stalled RTSP socket never raises
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from ..source import (
    STREAM_ERRORS,
    WATCHDOG_NO_FRAME_S,
    CameraSource,
    Frame,
    Health,
    TsSource,
    next_backoff,
    sleep_backoff,
)

# PyAV is only needed to actually pull frames. Importing this module (and so
# running the probe/selftest) must not require it.
try:
    import av
except ImportError:  # pragma: no cover
    av = None

OPEN_OPTIONS = {
    "rtsp_transport": "tcp",
    "stimeout": "5000000",  # 5 s socket timeout, microseconds
    "max_delay": "500000",
}


class RTSPSource(CameraSource):
    driver = "rtsp"

    def __init__(self, camera_id: str, url: str):
        self.camera_id = camera_id
        self.url = url
        self._container = None
        self._health = Health.UNKNOWN
        self._last_frame_at: float | None = None
        self._backoff: float | None = None

    async def open(self) -> None:
        if av is None:
            raise RuntimeError("PyAV not installed; `pip install av`")
        self._container = await asyncio.to_thread(
            av.open, self.url, options=OPEN_OPTIONS, timeout=10
        )
        self._health = Health.LIVE
        self._last_frame_at = time.time()
        self._backoff = None

    async def frames(self) -> AsyncIterator[Frame]:
        """Reconnects forever. The caller consumes frames and never sees a gap."""
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
                        pts = float(frame.pts) * time_base if (frame.pts is not None and time_base) else None
                        yield Frame(
                            image=frame.to_ndarray(format="bgr24"),
                            pts=pts,
                            wall_ts=self._last_frame_at,
                            ts_source=TsSource.RTSP_PTS,
                        )
                    if self._stalled():
                        raise TimeoutError("watchdog: no frame")
                # demux() exhausted normally (EOF / looping clip). Close and
                # reconnect so we don't spin on a dead iterator with health LIVE.
                await self.close()
                self._health = Health.DOWN
                self._backoff = next_backoff(self._backoff)
                await sleep_backoff(self._backoff)
            except STREAM_ERRORS:
                await self.close()
                self._health = Health.DOWN
                self._backoff = next_backoff(self._backoff)
                await sleep_backoff(self._backoff)

    def _stalled(self) -> bool:
        return (
            self._last_frame_at is not None
            and time.time() - self._last_frame_at > WATCHDOG_NO_FRAME_S
        )

    async def close(self) -> None:
        """Close in *this* thread, not a worker thread. See mediamtx.py."""
        if self._container is not None:
            container, self._container = self._container, None
            try:
                container.close()
            except Exception:
                pass

    def health(self) -> Health:
        if self._health is Health.LIVE and self._stalled():
            return Health.DOWN
        return self._health

    def capabilities(self) -> set[str]:
        return {"snapshot"}
