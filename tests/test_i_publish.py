"""I6's check: the [C1] row shape is enforced, and an outage loses nothing.

The ticket's Verify line is `selftest --assert-xadd`, which needs models and a clip. This file
covers what that command cannot fail cleanly on: the contract itself, and the two outages we
promised to survive. Both run against fakeredis and a fake S3 in milliseconds.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.worker.publish import (FIELDS, Publisher, crop_key,  # noqa: E402
                                     validate)
from services.worker.sighting import SightingBuilder  # noqa: E402
from services.worker.tracker import Track  # noqa: E402


def redis_client():
    import fakeredis
    return fakeredis.FakeRedis()


def row(**overrides):
    b = SightingBuilder("GJ-AHD-0123", vote_factory=lambda: None)
    b._anchor = 1_757_000_000.0
    b.observe(Track("GJ-AHD-0123", 4821, "car", 0.9, (412, 220, 688, 410), 10.0))
    return {**b.flush()[0].row(), **overrides}


class DeadS3:
    """Object storage that is not there. Every call raises, as botocore's would."""

    def __init__(self):
        self.calls = 0

    def _fail(self, **_kwargs):
        self.calls += 1
        raise OSError("Connect timeout on endpoint URL")

    head_bucket = create_bucket = put_object = _fail


# --- the contract ----------------------------------------------------------------------------

def test_a_clean_row_passes():
    assert validate(row()) is not None


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.pop("plate_canon"), "missing"),
    (lambda r: r.update(extra_field=1), "extra"),
    (lambda r: r.update(plate_band="MAYBE"), "unknown plate_band"),
    (lambda r: r.update(plate_band="POSSIBLE", plate_text="GJ01AB1234"), "2/3 vote"),
    (lambda r: r.update(camera_id=""), "without an id"),
])
def test_drift_is_rejected_loudly(mutate, message):
    r = row()
    mutate(r)
    with pytest.raises(ValueError, match=message):
        validate(r)


def test_the_row_goes_on_the_stream_as_one_json_field():
    client = redis_client()
    p = Publisher(redis_client=client, s3=None)
    assert p.publish(row()) is not None
    _id, fields = client.xrange("sightings")[0]
    payload = json.loads(fields[b"data"])
    assert list(payload) == list(FIELDS)


def test_crop_key_is_dated_by_pts_not_by_upload_time():
    """A row replayed after an outage must land in the day it was seen, not the day it was sent."""
    key = crop_key("GJ-AHD-0123", "01J6ABC", 1_757_000_000.0)      # 2025-09-04 IST
    assert key.startswith("GJ-AHD-0123/2025/09/04/") and key.endswith(".jpg")


# --- outages ----------------------------------------------------------------------------------

def test_redis_down_buffers_and_replays_in_order():
    """The chaos drill, in one test: no row is lost and the order survives - a route is an order."""
    p = Publisher(redis_client=None, s3=None)
    ids = []
    for i in range(5):
        r = row(sighting_id=f"01J6{i}")
        ids.append(r["sighting_id"])
        assert p.publish(r) is None                 # buffered, not lost
    assert len(p.buffer) == 5

    client = redis_client()
    p.redis = client
    p.publish(row(sighting_id="01J65"))
    stored = [json.loads(f[b"data"])["sighting_id"] for _, f in client.xrange("sightings")]
    assert stored == ids + ["01J65"]
    assert not p.buffer


def test_the_buffer_is_bounded():
    p = Publisher(redis_client=None, s3=None, buffer_max=3)
    for i in range(10):
        p.publish(row(sighting_id=f"01J6{i}"))
    assert len(p.buffer) == 3
    assert [r["sighting_id"] for r in p.buffer] == ["01J67", "01J68", "01J69"]


def test_object_storage_down_still_publishes_the_row():
    """A sighting without a picture is a route hop. A picture without a sighting is nothing."""
    client, s3 = redis_client(), DeadS3()
    p = Publisher(redis_client=client, s3=s3)
    b = SightingBuilder("CAM", vote_factory=lambda: None)
    b.observe(Track("CAM", 1, "car", 0.9, (0, 0, 80, 60), 1.0),
              crop=np.full((60, 80, 3), 200, np.uint8))
    sighting = b.flush()[0]
    assert p.publish(sighting) is not None
    assert sighting.crop_uri is None
    assert client.xlen("sightings") == 1


def test_a_dead_endpoint_is_not_retried_on_every_crop():
    """The circuit breaker. Without it one row spent 27 s inside a connect timeout."""
    p = Publisher(redis_client=redis_client(), s3=DeadS3())
    image = np.full((60, 80, 3), 200, np.uint8)
    for i in range(5):
        p.put_crop("CAM", f"01J6{i}", 1_757_000_000.0, image)
    assert p.s3.calls == 1, f"tried object storage {p.s3.calls} times while it was down"


def test_warm_opens_the_circuit_before_the_pipeline_starts():
    p = Publisher(redis_client=redis_client(), s3=DeadS3())
    p.warm()
    assert p.s3.calls == 1
    assert p.put_crop("CAM", "01J6", 1_757_000_000.0,
                      np.full((60, 80, 3), 200, np.uint8)) is None
    assert p.s3.calls == 1, "the first sighting paid the connect timeout again"
