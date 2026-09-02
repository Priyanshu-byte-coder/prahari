"""The persister has to survive redelivery, a dead consumer and a poisoned message.

These run against a real Redis and a real Postgres, because every one of the three failures
above is a property of the broker and the database, not of our Python. Point them at whatever
is running:

    TEST_REDIS_URL=redis://localhost:56379/0 \
    TEST_POSTGRES_DSN=postgresql://sentinel:sentinel@localhost:55432/sentinel \
    python -m pytest tests/test_d_persister.py

They skip, loudly, when nothing is listening.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from persister import Persister                      # noqa: E402
from store import Store                              # noqa: E402
import fake_sightings as fs                          # noqa: E402

REDIS_URL = os.environ.get("TEST_REDIS_URL", os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
DSN = os.environ.get("TEST_POSTGRES_DSN",
                     os.environ.get("POSTGRES_DSN",
                                    "postgresql://localhost:5432/sentinel"))


@pytest.fixture(scope="module")
def store():
    s = Store(dsn=DSN, redis_url=REDIS_URL)
    try:
        s.redis.ping()
        with s.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM cameras LIMIT 1")
    except Exception as exc:
        pytest.skip(f"needs a live Redis and a migrated Postgres: {exc}")
    yield s
    s.close()


@pytest.fixture
def rig(store):
    """A private stream and camera per test, so tests cannot see each other's rows."""
    tag = uuid.uuid4().hex[:8]
    camera = f"GJ-TEST-{tag}"
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO cameras (camera_id, name) VALUES (%s, %s)", (camera, "test rig"))
    persister = Persister(store=store, stream=f"sightings-test-{tag}",
                          group="persister", consumer=f"a-{tag}", block_ms=50, claim_idle_ms=0)
    persister.ensure_group()
    yield persister, camera
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sightings WHERE camera_id = %s", (camera,))
        cur.execute("DELETE FROM cameras WHERE camera_id = %s", (camera,))
    store.redis.delete(persister.stream)


def make_rows(camera, n, plate="GJ01AB1234"):
    import random
    rng = random.Random(11)
    base = datetime.now(fs.IST)
    return [fs.finish_bbox(fs.sighting(rng, camera, base + timedelta(seconds=i), plate), rng)
            for i in range(n)]


def publish(store, stream, rows):
    for row in rows:
        store.redis.xadd(stream, {"data": json.dumps(row)})


def count(store, camera):
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sightings WHERE camera_id = %s", (camera,))
        return cur.fetchone()[0]


def test_batch_is_persisted_and_acked(store, rig):
    persister, camera = rig
    publish(store, persister.stream, make_rows(camera, 25))
    assert persister.run_once() == 25
    assert count(store, camera) == 25
    assert persister.lag() == 0                        # acked, so nothing left pending


def test_redelivery_does_not_duplicate(store, rig):
    # A consumer that dies between the insert and the XACK sees the same batch again. Redis
    # streams are at-least-once; the primary key plus ON CONFLICT is what makes that harmless.
    persister, camera = rig
    rows = make_rows(camera, 10)
    publish(store, persister.stream, rows)
    persister.run_once()
    store.insert_sightings(rows)                       # the replay
    assert count(store, camera) == 10


def test_a_poisoned_message_does_not_stall_the_group(store, rig):
    persister, camera = rig
    store.redis.xadd(persister.stream, {"data": "{ not json"})
    publish(store, persister.stream, make_rows(camera, 3))
    persister.run_once()
    assert persister.dead_lettered == 1
    assert count(store, camera) == 3                   # the good rows still went in
    assert persister.lag() == 0
    assert store.redis.xlen("sightings.dead") >= 1


def test_pending_messages_of_a_dead_consumer_are_reclaimed(store, rig):
    persister, camera = rig
    publish(store, persister.stream, make_rows(camera, 6))
    # A consumer reads, then dies: the messages are delivered, unacked, and invisible to ">".
    store.redis.xreadgroup(persister.group, "dead-consumer", {persister.stream: ">"}, count=6)
    assert persister.run_once() == 0                   # nothing new to read
    assert count(store, camera) == 6                   # ... but the reclaim path caught them
    assert persister.lag() == 0


def test_recent_plate_cache_is_newest_first_and_capped(store, rig):
    persister, camera = rig
    plate = f"GJ99XX{uuid.uuid4().int % 10000:04d}"
    rows = make_rows(camera, 60, plate=plate)
    store.cache_recent(rows)
    ids = store.recent_sighting_ids(plate)
    assert len(ids) == 50                              # [D2]: last 50
    assert ids[0] == rows[-1]["sighting_id"]           # newest first
    assert 0 < store.redis.ttl(f"plate:{plate}") <= 24 * 3600
    store.redis.delete(f"plate:{plate}")


CROP = "s3://crops/GJ-AHD-0001/2026/09/14/01J6.jpg"


@pytest.fixture
def object_store_keys(monkeypatch):
    """Keys come from the environment ([C9]); the test supplies its own throwaway pair."""
    monkeypatch.setenv("MINIO_ACCESS_KEY", "test-access-key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "test-secret-key")


def test_crop_url_is_not_signed_when_the_scope_check_says_no(object_store_keys):
    denied = Store(dsn=DSN, redis_url=REDIS_URL, scope_check=lambda ctx: False)
    assert denied.crop_url(CROP) is None


def test_crop_url_expires_in_five_minutes(object_store_keys):
    allowed = Store(dsn=DSN, redis_url=REDIS_URL, scope_check=lambda ctx: True)
    url = allowed.crop_url(CROP)
    assert "X-Amz-Expires=300" in url and "01J6.jpg" in url


def test_signing_without_object_store_keys_refuses_rather_than_defaulting(monkeypatch):
    # A default key pair in source gets deployed unchanged, and the crop bucket holds
    # vehicles and faces. Refusing is the safe failure.
    monkeypatch.delenv("MINIO_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)
    store = Store(dsn=DSN, redis_url=REDIS_URL, scope_check=lambda ctx: True)
    with pytest.raises(RuntimeError, match="MINIO_ACCESS_KEY"):
        store.crop_url(CROP)
