-- db/migrate.sql — the file that actually runs. Same objects as db/schema.sql, guarded so it
-- can be applied to a database that is already partly built.
--
--     psql "$POSTGRES_DSN" -f db/migrate.sql
--
-- Two differences from db/schema.sql, both deliberate:
--   * every object carries IF NOT EXISTS, and create_hypertable() gets if_not_exists => TRUE,
--     so a re-run after a partial failure is not a wall of "already exists" errors;
--   * the sightings indexes are named. [C3] writes them unnamed, which makes Postgres invent
--     sightings_plate_norm_pts_first_idx and friends — those cannot be guarded, so a second
--     run would try to build all five again.
-- tests/test_d_schema.py fails if the two files stop describing the same tables.
--
-- The hypertable is created immediately after the table and before anything can insert:
-- create_hypertable() on a table that already holds rows needs migrate_data and a table lock,
-- and on a live grid that is an outage, not a migration.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS departments (id serial PRIMARY KEY, code text UNIQUE, name text);

CREATE TABLE IF NOT EXISTS users (id serial PRIMARY KEY, username text UNIQUE, pw_hash text,
  dept_id int REFERENCES departments(id), district_code text, role text NOT NULL, active bool DEFAULT true);

CREATE TABLE IF NOT EXISTS cameras (
  camera_id text PRIMARY KEY, name text NOT NULL, owner_dept_id int REFERENCES departments(id),
  district_code text, install_type text,
  lat double precision, lon double precision,
  coord_source text, coord_conf text,
  bearing_deg real, fov_deg real DEFAULT 70, range_m real DEFAULT 60, lane_bearing_deg real,
  transports jsonb, transport_in_use text, driver text,
  health text DEFAULT 'UNKNOWN', health_at timestamptz, updated_at timestamptz DEFAULT now());

CREATE TABLE IF NOT EXISTS sightings (
  sighting_id text, camera_id text REFERENCES cameras(camera_id), track_id bigint,
  pts_first timestamptz NOT NULL, pts_last timestamptz, ts_source text,
  plate_text text, plate_norm text, plate_canon text, plate_conf real, plate_band text,
  vehicle_class text, colour text, bbox int[], reid_vec vector(512), crop_uri text,
  PRIMARY KEY (pts_first, sighting_id));

SELECT create_hypertable('sightings','pts_first',
                         chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS sightings_plate_norm_pts_idx  ON sightings (plate_norm, pts_first DESC);
CREATE INDEX IF NOT EXISTS sightings_plate_canon_pts_idx ON sightings (plate_canon, pts_first DESC);
CREATE INDEX IF NOT EXISTS sightings_camera_pts_idx      ON sightings (camera_id, pts_first DESC);
CREATE INDEX IF NOT EXISTS sightings_plate_norm_trgm_idx ON sightings USING gin (plate_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS sightings_reid_vec_hnsw_idx   ON sightings USING hnsw (reid_vec vector_cosine_ops);

CREATE TABLE IF NOT EXISTS watchlist (id serial PRIMARY KEY, kind text, plate_norm text, plate_canon text,
  face_vec vector(512), description text, category text, reason text, severity text,
  owner_dept_id int, classification text, added_by int REFERENCES users(id),
  valid_from timestamptz, valid_until timestamptz, source text DEFAULT 'manual');

CREATE TABLE IF NOT EXISTS alerts (id serial PRIMARY KEY, watchlist_id int, sighting_id text, camera_id text,
  pts timestamptz, band text, state text DEFAULT 'NEW', count int DEFAULT 1,
  created_at timestamptz DEFAULT now());

CREATE TABLE IF NOT EXISTS alert_events (id serial PRIMARY KEY, alert_id int, from_state text, to_state text,
  by_user int, reason text, at timestamptz DEFAULT now());

CREATE TABLE IF NOT EXISTS access_grants (id serial PRIMARY KEY, requester int, target_dept_id int,
  case_no text NOT NULL, reason text NOT NULL, approved_by int,
  starts timestamptz, expires timestamptz NOT NULL, state text);

CREATE TABLE IF NOT EXISTS audit_log (seq bigserial PRIMARY KEY, at timestamptz DEFAULT now(), user_id int,
  dept_id int, action text, object_type text, object_id text, ip inet, reason text,
  grant_id int, prev_hash bytea, hash bytea NOT NULL);

-- [D2] Compression and retention. Not in [C3] - the contract describes the shape of the data,
-- these describe how long it is kept, and they are lane D's call. schema.sql stays a verbatim
-- copy of the contract, so it does not carry them.
--
-- Compressed chunks are read-only in the sense that matters here: the persister only ever
-- inserts into the newest chunk, and 7 days is far behind it.
ALTER TABLE sightings SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'camera_id',
  timescaledb.compress_orderby   = 'pts_first DESC');

SELECT add_compression_policy('sightings', INTERVAL '7 days',  if_not_exists => TRUE);
SELECT add_retention_policy  ('sightings', INTERVAL '90 days', if_not_exists => TRUE);

-- alerts, alert_events and audit_log get no retention policy on purpose: an alert nobody can
-- look up a year later is worth little, and the audit chain has to stay whole to be evidence.
-- Crops expire at 30 days in MinIO's bucket lifecycle, not here - object storage is lane G's
-- infra. Filed under TASK.md "Cross-lane requests" if it is not set by the freeze.
