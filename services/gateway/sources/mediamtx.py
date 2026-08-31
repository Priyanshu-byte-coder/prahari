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
from datetime import datetime, timezone
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
        # PDT anchor: epoch of the first PDT-tagged segment, and the stream-
        # relative pts of the first frame we decoded after that anchor. Together
        # they let us map any subsequent pts to a wall-clock epoch float.
        self._pdt_epoch: float | None = None
        self._pdt_pts_offset: float | None = None

    def _playlist_pdt(self) -> datetime | None:
        """Return the first EXT-X-PROGRAM-DATE-TIME value found in this stream.

        The master playlist never carries PDT — it lives one level down in the
        variant. We check the master body first (fast path, unusual) then fetch
        the first variant and look there.  Returns None if the stream has no
        PDT or is unreachable.
        """
        try:
            body = self._fetch_playlist(self.url)
            if body is None:
                return None
            dt = self._parse_pdt_from_body(body)
            if dt is not None:
                return dt
            variant = self._first_variant_url(self.url, body)
            if variant is None:
                return None
            child = self._fetch_playlist(variant)
            if child is None:
                return None
            return self._parse_pdt_from_body(child)
        except requests.RequestException:
            return None

    @staticmethod
    def _parse_pdt_from_body(body: str) -> datetime | None:
        """Extract and parse the first #EXT-X-PROGRAM-DATE-TIME line."""
        for line in body.splitlines():
            if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
                raw = line.split(":", 1)[1].strip()
                try:
                    # datetime.fromisoformat handles most ISO-8601 variants
                    # but not the trailing 'Z' until Python 3.11; normalise it.
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    return None
        return None

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
        pdt = await asyncio.to_thread(self._playlist_pdt)
        self._ts_source = TsSource.HLS_PDT if pdt is not None else TsSource.SERVER_RECEIVE
        self._pdt_epoch = pdt.timestamp() if pdt is not None else None
        self._pdt_pts_offset = None  # reset: will be anchored on the first frame
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
                        stream_pts = float(frame.pts) * time_base if (frame.pts is not None and time_base) else None
                        if (
                            self._ts_source is TsSource.HLS_PDT
                            and self._pdt_epoch is not None
                            and stream_pts is not None
                        ):
                            # Anchor the PDT epoch to the first frame's stream
                            # pts, then offset every subsequent frame from there.
                            # This maps stream-relative pts to wall-clock epoch
                            # without calling now() on each frame.
                            if self._pdt_pts_offset is None:
                                self._pdt_pts_offset = stream_pts
                            pts = self._pdt_epoch + (stream_pts - self._pdt_pts_offset)
                        else:
                            pts = stream_pts
                        yield Frame(
                            image=frame.to_ndarray(format="bgr24"),
                            pts=pts,
                            wall_ts=self._last_frame_at,
                            ts_source=self._ts_source,
                        )
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
