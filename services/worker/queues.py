"""[I1] Bounded per-camera frame queues. Drop frames, never sightings.

Depth 2 per camera: one frame in the consumer's hands, one waiting. When the detector falls
behind, the newest frame wins and the oldest is discarded - a stale frame is worth less than a
fresh one to a detector, and the alternative (an unbounded queue) converts a slow GPU into an
OOM an hour later, on stage, with no warning.

Drops are counted per camera because a silent drop rate is indistinguishable from a camera that
went dark. I6 puts these counters on /metrics.
"""

import threading
from queue import Empty, Full, Queue

DEPTH = 2


class FrameQueue:
    """A drop-oldest bounded queue. put() never blocks and never raises."""

    def __init__(self, camera_id, depth=DEPTH):
        self.camera_id = camera_id
        self._q = Queue(maxsize=depth)
        self._lock = threading.Lock()
        self.accepted = 0
        self.dropped = 0

    def put(self, frame):
        """Queue a frame, displacing the oldest if full. True when something was displaced."""
        displaced = False
        with self._lock:
            while True:
                try:
                    self._q.put_nowait(frame)
                    self.accepted += 1
                    return displaced
                except Full:
                    try:
                        self._q.get_nowait()
                        self.dropped += 1
                        displaced = True
                    except Empty:
                        # The consumer drained it between the Full and the get. Retry, don't
                        # count a drop that never happened.
                        pass

    def get(self, timeout=0.5):
        """Next frame, or None on timeout. None is 'nothing yet', never 'stream ended'."""
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None

    @property
    def depth(self):
        return self._q.qsize()

    def stats(self):
        # accepted counts every frame offered, so it is the denominator. Adding dropped to it
        # would count each displaced frame twice and report 50% where 99.8% were discarded.
        rate = self.dropped / self.accepted if self.accepted else 0.0
        return {"camera_id": self.camera_id, "accepted": self.accepted,
                "dropped": self.dropped, "drop_rate": rate, "depth": self.depth}
