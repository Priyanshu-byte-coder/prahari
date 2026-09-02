"""[I6] The lane's only real output: a [C1] row on the `sightings` stream, a crop in MinIO.

Everything upstream of this file is ours to change. This file is not: the field names on the
row are frozen ([C1]) and lane D reads them with two consumer groups. So the row is built in
one place (`sighting.row()`), validated here against the contract's own field list, and any
drift fails loudly on our side instead of quietly on D's.

Two failure modes are designed for, because both will happen during the demo:

- **Redis is down.** Sightings buffer in memory and flush on the next success, oldest first.
  The buffer is bounded - an unbounded one converts a 20-minute Redis outage into an OOM - and
  it is the chaos drill J1 runs ("restart Postgres, workers buffer, no lost sightings").
- **MinIO is down or slow.** The crop is dropped, the row is published anyway with a null
  `crop_uri`. A sighting without a picture is still a route hop; a picture without a sighting
  is nothing. Never let object storage hold up the stream.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from datetime import datetime

import cv2

from services.worker import metrics
from services.worker.sighting import IST

logger = logging.getLogger("prahari.worker.publish")

STREAM = "sightings"
BUCKET = os.getenv("PRAHARI_CROP_BUCKET", "crops")
BUFFER_MAX = 20_000          # ~4 MB of rows; about 40 min of one busy camera
MAXLEN = 1_000_000           # stream cap, so a stalled consumer cannot fill the Redis box
JPEG_QUALITY = 85
S3_COOLDOWN_S = 60           # after a failed PUT, stop trying for this long

# [C1], in order. The row is checked against this on every publish - a typo in a field name is
# invisible in a JSON blob and expensive in D's persister.
FIELDS = ("sighting_id", "camera_id", "track_id", "pts_first", "pts_last", "ts_source",
          "plate_text", "plate_norm", "plate_canon", "plate_conf", "plate_band",
          "vehicle_class", "colour", "bbox", "reid_vec", "crop_uri")


def crop_key(camera_id, sighting_id, pts_first_epoch):
    """`<camera_id>/<yyyy>/<mm>/<dd>/<sighting_id>.jpg`, dated by PTS and not by upload time.

    A row replayed from a buffered outage would otherwise land in the wrong day's prefix, and
    the prefix is how an operator finds crops for a given day without a database.
    """
    day = datetime.fromtimestamp(pts_first_epoch, IST)
    return f"{camera_id}/{day:%Y/%m/%d}/{sighting_id}.jpg"


def validate(row):
    """Exactly the [C1] fields, no more, no fewer. Raises - this is a contract, not a warning."""
    missing = [f for f in FIELDS if f not in row]
    extra = [f for f in row if f not in FIELDS]
    if missing or extra:
        raise ValueError(f"[C1] drift: missing={missing} extra={extra}")
    if not row["sighting_id"] or not row["camera_id"]:
        raise ValueError("[C1] row without an id or a camera")
    if row["plate_band"] not in ("CONFIRMED", "PROBABLE", "POSSIBLE", "NONE"):
        raise ValueError(f"[C1] unknown plate_band {row['plate_band']!r}")
    if row["plate_band"] in ("POSSIBLE", "NONE") and row["plate_text"]:
        raise ValueError("[C1] plate_text set below a 2/3 vote - the whole point of I4")
    return row


class Publisher:
    """Redis XADD + MinIO PUT. Both optional, both failure-tolerant, neither ever raising
    into the frame loop."""

    def __init__(self, redis_client=None, redis_url=None, s3=None, bucket=BUCKET,
                 stream=STREAM, buffer_max=BUFFER_MAX):
        self.stream = stream
        self.bucket = bucket
        self.buffer = deque(maxlen=buffer_max)
        self.redis = redis_client if redis_client is not None else _redis(redis_url)
        self.s3 = s3 if s3 is not None else _s3()
        self._bucket_ready = False
        self._s3_down_until = 0.0

    def warm(self):
        """Touch object storage once, before the pipeline starts.

        If MinIO is not there, the circuit opens here instead of costing the first sighting a
        connect timeout - which is one-off deployment cost being charged to a latency budget.
        """
        if self.s3 is None:
            return
        try:
            self._ensure_bucket()
        except Exception as exc:
            self._s3_down_until = time.time() + S3_COOLDOWN_S
            logger.warning("object storage unreachable at startup (%s) - rows will publish "
                           "without crops for %ds", exc, S3_COOLDOWN_S)

    # --- crops --------------------------------------------------------------------------

    def put_crop(self, camera_id, sighting_id, pts_first_epoch, image):
        """PUT one JPEG, return its `s3://` URI, or None if object storage is not there.

        A failed PUT opens a 60 s circuit. Measured, not assumed: with MinIO down, one row
        spent 27 s in here - a TCP connect that is dropped rather than refused costs the full
        timeout, three calls deep (head, create, put), and the frame loop waits for all of it.
        A sighting without a picture is still a route hop; a stream that stalls is not.
        """
        if self.s3 is None or image is None or not getattr(image, "size", 0):
            return None
        if time.time() < self._s3_down_until:
            return None
        ok, buf = cv2.imencode(".jpg", image,
                               [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            return None
        key = crop_key(camera_id, sighting_id, pts_first_epoch)
        try:
            self._ensure_bucket()
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=buf.tobytes(),
                               ContentType="image/jpeg")
            return f"s3://{self.bucket}/{key}"
        except Exception as exc:
            metrics.PUBLISH_FAILED.labels(kind="crop").inc()
            self._s3_down_until = time.time() + S3_COOLDOWN_S
            self._bucket_ready = False
            logger.warning("crop PUT failed (%s) - rows publish without crops for %ds",
                           exc, S3_COOLDOWN_S)
            return None

    def _ensure_bucket(self):
        """One head, and a create only if the head says the bucket is missing rather than
        unreachable. An unreachable endpoint must fail once, here, not three times."""
        if self._bucket_ready:
            return
        try:
            self.s3.head_bucket(Bucket=self.bucket)
            self._bucket_ready = True
            return
        except Exception as exc:
            if not _is_missing_bucket(exc):
                raise                       # unreachable: let put_crop open the circuit
        # Worker credentials are PUT-only by design ([I6]); if creation is refused the bucket
        # is somebody else's job and the next put_object will say so.
        try:
            self.s3.create_bucket(Bucket=self.bucket)
        except Exception as exc:
            logger.info("bucket %s not created (%s)", self.bucket, exc)
        self._bucket_ready = True

    # --- rows ---------------------------------------------------------------------------

    def publish(self, sighting):
        """Publish one Sighting (or a ready [C1] dict). Returns the stream id, or None.

        None means buffered, not lost: the row is retried on the next publish.
        """
        if hasattr(sighting, "row"):
            if sighting.crop is not None:
                sighting.crop_uri = self.put_crop(sighting.camera_id, sighting.sighting_id,
                                                  sighting.pts_first, sighting.crop)
            row = sighting.row()
        else:
            row = sighting
        validate(row)
        metrics.OCR_VOTES.labels(band=row["plate_band"]).inc()
        return self._xadd(row)

    def _xadd(self, row):
        if self.redis is None:
            self._buffer(row)
            return None
        try:
            self._drain()
            stream_id = self.redis.xadd(self.stream, {"data": json.dumps(row)},
                                        maxlen=MAXLEN, approximate=True)
            metrics.SIGHTINGS.labels(camera_id=row["camera_id"]).inc()
            return stream_id.decode() if isinstance(stream_id, bytes) else stream_id
        except Exception as exc:
            metrics.PUBLISH_FAILED.labels(kind="xadd").inc()
            logger.warning("XADD failed (%s) - buffering %d rows", exc, len(self.buffer) + 1)
            self._buffer(row)
            return None

    def _buffer(self, row):
        if len(self.buffer) == self.buffer.maxlen:
            # ponytail: bounded buffer, oldest first out. A longer outage than this needs a
            # disk spool, not a bigger deque - say so in the drill report rather than pretend.
            logger.error("sighting buffer full (%d) - dropping the oldest row",
                         self.buffer.maxlen)
        self.buffer.append(row)
        metrics.BUFFERED.set(len(self.buffer))

    def _drain(self):
        """Flush buffered rows oldest-first. Order is the point: D's persister writes a route."""
        while self.buffer:
            row = self.buffer[0]
            self.redis.xadd(self.stream, {"data": json.dumps(row)},
                            maxlen=MAXLEN, approximate=True)
            self.buffer.popleft()
            metrics.SIGHTINGS.labels(camera_id=row["camera_id"]).inc()
        metrics.BUFFERED.set(0)

    def close(self):
        try:
            if self.redis is not None:
                self._drain()
        except Exception as exc:
            logger.error("%d sightings still buffered at shutdown: %s", len(self.buffer), exc)


def _is_missing_bucket(exc):
    """404/NoSuchBucket means "create it"; anything else means the endpoint is not there."""
    response = getattr(exc, "response", None) or {}
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    code = response.get("Error", {}).get("Code")
    return status == 404 or code in ("404", "NoSuchBucket")


def _redis(url=None):
    try:
        import redis
        client = redis.Redis.from_url(url or os.getenv("REDIS_URL",
                                                       "redis://localhost:6379/0"))
        client.ping()
        return client
    except Exception as exc:
        logger.warning("no Redis (%s) - sightings will buffer in memory", exc)
        return None


def _s3():
    """A MinIO client via botocore - already in the tree as a dependency of the AWS SDK, so
    this costs no new package. Path addressing: MinIO has no virtual-host DNS."""
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    try:
        import botocore.session
        from botocore.config import Config
        return botocore.session.get_session().create_client(
            "s3", endpoint_url=endpoint,
            aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            region_name=os.getenv("MINIO_REGION", "us-east-1"),
            config=Config(signature_version="s3v4",
                          s3={"addressing_style": "path"},
                          connect_timeout=1, read_timeout=3,
                          retries={"max_attempts": 1}))
    except Exception as exc:
        logger.warning("no MinIO client (%s) - crops will not be stored", exc)
        return None
