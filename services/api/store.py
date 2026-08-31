"""Postgres and Redis access for lane D. Everything that writes a sighting goes through here.

Three jobs, one class, because they share a connection and a transaction boundary:

  * batched inserts into the `sightings` hypertable;
  * the `plate:<plate_norm>` recent-ids cache the matcher and the search box read (O(1) instead
    of a hypertable scan for "where has this plate been in the last day");
  * presigned crop URLs, which are the only way a crop ever reaches a browser.

The crop URL is behind a scope check on purpose. D7 puts the real [C10] role matrix behind that
hook; until then the default says yes and logs that it did, so the hole is visible in the log
rather than forgotten in the code.
"""

import json
import logging
import os

log = logging.getLogger(__name__)

RECENT_CACHE_SIZE = 50           # [D2] last 50 sighting ids per plate
RECENT_CACHE_TTL = 24 * 3600
CROP_URL_TTL = 300               # 5 minutes: long enough to look at, short enough to leak safely

# No credentials in source. A DSN with a password in it belongs in .env ([C9]); a default
# that happens to work on a laptop is how one ends up in a container image.
DEFAULT_DSN = "postgresql://localhost:5432/sentinel"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_MINIO_ENDPOINT = "http://localhost:9000"

INSERT = """
INSERT INTO sightings (sighting_id, camera_id, track_id, pts_first, pts_last, ts_source,
                       plate_text, plate_norm, plate_canon, plate_conf, plate_band,
                       vehicle_class, colour, bbox, reid_vec, crop_uri)
VALUES %s
ON CONFLICT (pts_first, sighting_id) DO NOTHING
"""

COLUMNS = ("sighting_id", "camera_id", "track_id", "pts_first", "pts_last", "ts_source",
           "plate_text", "plate_norm", "plate_canon", "plate_conf", "plate_band",
           "vehicle_class", "colour", "bbox", "reid_vec", "crop_uri")


def allow_until_d7(_context):
    """Default scope check: yes, and say so. Replaced by the [C10] matrix in D7."""
    log.warning("crop URL signed without a scope check - D7 has not landed")
    return True


class Store:
    def __init__(self, dsn=None, redis_url=None, scope_check=allow_until_d7, s3=None):
        self.dsn = dsn or os.environ.get("POSTGRES_DSN") or DEFAULT_DSN
        self.redis_url = redis_url or os.environ.get("REDIS_URL") or DEFAULT_REDIS_URL
        self.scope_check = scope_check
        self._conn = None
        self._redis = None
        self._s3 = s3

    # -- connections -------------------------------------------------------------------

    @property
    def conn(self):
        import psycopg2
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
        return self._conn

    @property
    def redis(self):
        import redis
        if self._redis is None:
            self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def close(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    # -- sightings ---------------------------------------------------------------------

    @staticmethod
    def _tuple(row):
        """One [C1] dict as an INSERT tuple. reid_vec goes in as pgvector's text form."""
        vec = row.get("reid_vec")
        return tuple(
            json.dumps(vec) if field == "reid_vec" and vec is not None else row.get(field)
            for field in COLUMNS
        )

    def insert_sightings(self, rows):
        """Insert a batch in one round trip. Returns the number of rows the database accepted.

        ON CONFLICT DO NOTHING is what makes redelivery safe: a consumer that dies between the
        insert and the XACK will see the same messages again, and the second insert must not
        raise. Redis streams are at-least-once, so this is the normal path, not the edge case.
        """
        if not rows:
            return 0
        from psycopg2.extras import execute_values
        with self.conn as conn, conn.cursor() as cur:
            execute_values(cur, INSERT, [self._tuple(r) for r in rows], page_size=len(rows))
            return cur.rowcount

    def cache_recent(self, rows):
        """Push sighting ids onto plate:<plate_norm>, newest first, capped and expiring."""
        plated = [r for r in rows if r.get("plate_norm")]
        if not plated:
            return 0
        pipe = self.redis.pipeline(transaction=False)
        for row in plated:
            key = f"plate:{row['plate_norm']}"
            pipe.lpush(key, row["sighting_id"])
            pipe.ltrim(key, 0, RECENT_CACHE_SIZE - 1)
            pipe.expire(key, RECENT_CACHE_TTL)
        pipe.execute()
        return len(plated)

    def recent_sighting_ids(self, plate_norm, limit=RECENT_CACHE_SIZE):
        return self.redis.lrange(f"plate:{plate_norm}", 0, limit - 1)

    # -- crops -------------------------------------------------------------------------

    @property
    def s3(self):
        if self._s3 is None:
            import boto3
            from botocore.config import Config
            # MinIO only accepts SigV4. boto3 falls back to SigV2 when it cannot infer a
            # region, and a SigV2 URL carries Expires as an epoch - MinIO rejects it outright.
            access_key = os.environ.get("MINIO_ACCESS_KEY")
            secret_key = os.environ.get("MINIO_SECRET_KEY")
            if not (access_key and secret_key):
                # Refusing beats defaulting: object-storage keys that ship in source get
                # deployed unchanged, and the crop bucket holds vehicles and faces.
                raise RuntimeError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be set "
                                   "(see .env.example, [C9]) before a crop can be signed")
            self._s3 = boto3.client(
                "s3",
                endpoint_url=os.environ.get("MINIO_ENDPOINT") or DEFAULT_MINIO_ENDPOINT,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=os.environ.get("MINIO_REGION", "us-east-1"),
                config=Config(signature_version="s3v4"))
        return self._s3

    def crop_url(self, crop_uri, context=None):
        """Presign a crop for CROP_URL_TTL seconds, or return None if the scope check says no.

        A returned URL is a bearer token for that image for five minutes: anyone holding it can
        fetch the crop without logging in. That is why the check happens before signing and not
        in the route handler that calls this.
        """
        if not crop_uri:
            return None
        if not self.scope_check(context or {}):
            return None
        if not crop_uri.startswith("s3://"):
            raise ValueError(f"crop_uri is not an s3:// URI: {crop_uri!r}")
        # Signed only after the check above: the URL is a bearer token for that image for
        # five minutes, and anyone holding it can fetch the crop without logging in.
        bucket, _, key = crop_uri[len("s3://"):].partition("/")
        return self.s3.generate_presigned_url("get_object",
                                              Params={"Bucket": bucket, "Key": key},
                                              ExpiresIn=CROP_URL_TTL)
