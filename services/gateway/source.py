"""[G2] The CameraSource seam.

`CameraSource` is exactly [C6]. Every driver implements it, so the rest of
the gateway never knows whether a camera arrived over RTSP, HLS, ONVIF or a
vendor VMS.

The worker (lane I) imports none of this. It reads a URL string out of
`camera:transport:<id>` [C2] and decodes it itself. That key is the whole
seam; keep it that way.
"""
from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Protocol, runtime_checkable

# Module-level singleton: SystemRandom is thread-safe and reusing it avoids
# a per-call allocation that static-analysis tools flag unnecessarily.
_RNG = secrets.SystemRandom()


class Health(str, Enum):
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class TsSource(str, Enum):
    """Where a frame's timestamp came from. Never `now()` -- see plan A6."""

    RTSP_PTS = "rtsp_pts"
    HLS_PDT = "hls_pdt"
    SERVER_RECEIVE = "server_receive"


@dataclass(slots=True)
class Frame:
    """One decoded frame.

    `pts` semantics depend on `ts_source`:
      - RTSP_PTS / SERVER_RECEIVE: stream-relative seconds (float, from
        frame.pts * time_base — not wall time).
      - HLS_PDT: Unix epoch seconds (float), derived from
        EXT-X-PROGRAM-DATE-TIME anchored to the first frame's stream pts.
        Safe to compare across cameras for route ordering.
    """

    image: "object"  # numpy ndarray; typed loosely so this module imports without numpy
    pts: float | None
    wall_ts: float
    ts_source: TsSource


@runtime_checkable
class CameraSource(Protocol):
    async def open(self) -> None: ...
    async def frames(self) -> AsyncIterator[Frame]: ...
    async def close(self) -> None: ...
    def health(self) -> Health: ...
    def capabilities(self) -> set[str]: ...


# Reconnect policy shared by every driver: 1, 2, 4, 8, 16, 30, 30... with
# jitter so thirty cameras losing a link together do not retry in lockstep.
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0

# A stalled RTSP socket never errors on its own -- it just stops delivering.
# Without this watchdog a dead camera looks healthy forever.
WATCHDOG_NO_FRAME_S = 10.0


# What a driver may retry: the stream broke, so reconnect. Anything else --
# a missing dependency, a typo, a bad attribute -- is our bug and must
# surface immediately. A blanket `except Exception` here once turned a
# missing numpy into "camera unreachable, health DOWN" and cost an hour.
#
# Note PyAV >= 9 has no `av.AVError`; the base class is `av.FFmpegError`.
_STREAM_ERRORS: list[type[BaseException]] = [OSError, TimeoutError, EOFError]
try:
    import av as _av

    _STREAM_ERRORS.append(_av.FFmpegError)
except (ImportError, AttributeError):  # pragma: no cover - PyAV optional at import time
    pass

STREAM_ERRORS: tuple[type[BaseException], ...] = tuple(_STREAM_ERRORS)


def next_backoff(current: float | None) -> float:
    if current is None:
        return BACKOFF_START_S
    return min(current * 2, BACKOFF_MAX_S)


async def sleep_backoff(delay: float) -> None:
    """Jitter so thirty cameras losing a link together do not retry in lockstep.

    `secrets` rather than `random`: the jitter is not security-sensitive, but a
    non-cryptographic RNG here is a standing static-analysis finding and the
    cost of the stronger one is nil at this call rate.
    """
    await asyncio.sleep(delay * (0.8 + 0.4 * _RNG.random()))
