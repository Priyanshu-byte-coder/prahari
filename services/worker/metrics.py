"""[I6] /metrics. The numbers that say whether the lane is alive, in Prometheus text format.

Every counter here answers a question we will actually be asked on stage or at 2am:

  frames decoded / dropped   is the camera dark, or is the GPU behind?
  inference seconds by model which stage is the bottleneck - detector, plate, or OCR?
  queue depth                are we about to start dropping?
  sightings                  is the lane producing output at all?
  ocr votes by outcome       the honest recall figure, live: how often the vote refuses.
  analytics events by kind   [I12]'s crowd / stopped / wrong-way / loitering counts.

Histograms, not gauges, for latency: p50 and p95 have to be computable over a window after the
fact, and a gauge of "last latency" cannot answer that. Buckets are in seconds and stop at 2 s,
past which the answer is "it is broken", not "it is slow".
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger("prahari.worker.metrics")

REGISTRY = CollectorRegistry(auto_describe=True)
PORT = 9108

FRAMES_DECODED = Counter("prahari_frames_decoded_total", "Frames handed to the pipeline",
                         ["camera_id"], registry=REGISTRY)
FRAMES_DROPPED = Counter("prahari_frames_dropped_total", "Frames dropped by a bounded queue",
                         ["camera_id"], registry=REGISTRY)
QUEUE_DEPTH = Gauge("prahari_queue_depth", "Frames waiting per camera",
                    ["camera_id"], registry=REGISTRY)
INFERENCE = Histogram("prahari_inference_seconds", "Model call latency", ["model"],
                      buckets=(.005, .01, .02, .04, .08, .15, .3, .6, 1.2, 2.0),
                      registry=REGISTRY)
SIGHTINGS = Counter("prahari_sightings_total", "Sighting rows published",
                    ["camera_id"], registry=REGISTRY)
PUBLISH_FAILED = Counter("prahari_publish_failures_total", "Publish attempts that failed",
                         ["kind"], registry=REGISTRY)
BUFFERED = Gauge("prahari_buffered_sightings", "Sightings held in memory awaiting Redis",
                 registry=REGISTRY)
OCR_VOTES = Counter("prahari_ocr_votes_total", "Plate votes by outcome band",
                    ["band"], registry=REGISTRY)
ANALYTICS = Counter("prahari_analytics_events_total", "Analytics events by kind ([I12])",
                    ["kind"], registry=REGISTRY)


@contextmanager
def timed(model):
    """`with timed("detect"):` - the only way inference latency gets recorded."""
    start = time.perf_counter()
    try:
        yield
    finally:
        INFERENCE.labels(model=model).observe(time.perf_counter() - start)


def record_queues(queues):
    """Mirror `FrameQueue.stats()` into the registry. Counters are set from absolute totals,
    so this is safe to call on every loop and it cannot double-count."""
    for q in queues:
        stats = q.stats()
        QUEUE_DEPTH.labels(camera_id=stats["camera_id"]).set(stats["depth"])
        _set_counter(FRAMES_DECODED.labels(camera_id=stats["camera_id"]), stats["accepted"])
        _set_counter(FRAMES_DROPPED.labels(camera_id=stats["camera_id"]), stats["dropped"])


def _set_counter(counter, total):
    """Counters only go up, and the queue owns the absolute number - so move ours to match."""
    current = counter._value.get()
    if total > current:
        counter.inc(total - current)


def serve(port=PORT):
    """Start the scrape endpoint. Returns the port, or None when it could not bind - a
    metrics port already in use must never stop a worker from processing video."""
    try:
        start_http_server(port, registry=REGISTRY)
        logger.info("metrics on :%d/metrics", port)
        return port
    except OSError as exc:
        logger.warning("metrics port %d unavailable (%s) - continuing without /metrics",
                       port, exc)
        return None
