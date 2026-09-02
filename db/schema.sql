-- db/schema.sql — canonical schema, lane D owns it.
--
-- This file is a verbatim copy of contract [C3] in TASK.md. Keep it that way: it is the
-- reference a reviewer diffs the contract against, so drift shows up as a diff instead of
-- as a runtime surprise in somebody else's lane. Anything that has to be re-runnable lives
-- in db/migrate.sql, which carries the same objects with IF NOT EXISTS guards.
--
-- Apply once, into an empty database:
--     psql "$POSTGRES_DSN" -f db/migrate.sql
--
-- Extensions come first — sightings.reid_vec needs pgvector, the trigram index needs
-- pg_trgm, and create_hypertable() does not exist until timescaledb is loaded.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE departments (id serial PRIMARY KEY, code text UNIQUE, name text);
CREATE TABLE users (id serial PRIMARY KEY, username text UNIQUE, pw_hash text,
  dept_id int REFERENCES departments(id), district_code text, role text NOT NULL, active bool DEFAULT true);

CREATE TABLE cameras (
  camera_id text PRIMARY KEY, name text NOT NULL, owner_dept_id int REFERENCES departments(id),
  district_code text, install_type text,            -- FIX | PTZ | RLVD
  lat double precision, lon double precision,
  coord_source text, coord_conf text,               -- gps|manual|district_centroid ; HIGH|MEDIUM|LOW
  bearing_deg real, fov_deg real DEFAULT 70, range_m real DEFAULT 60, lane_bearing_deg real,
  transports jsonb, transport_in_use text, driver text,   -- mediamtx|rtsp|onvif|vms
  health text DEFAULT 'UNKNOWN', health_at timestamptz, updated_at timestamptz DEFAULT now());

CREATE TABLE sightings (
  sighting_id text, camera_id text REFERENCES cameras(camera_id), track_id bigint,
  pts_first timestamptz NOT NULL, pts_last timestamptz, ts_source text,
  plate_text text, plate_norm text, plate_canon text, plate_conf real, plate_band text,
  vehicle_class text, colour text, bbox int[], reid_vec vector(512), crop_uri text,
  PRIMARY KEY (pts_first, sighting_id));
SELECT create_hypertable('sightings','pts_first', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON sightings (plate_norm, pts_first DESC);
CREATE INDEX ON sightings (plate_canon, pts_first DESC);
CREATE INDEX ON sightings (camera_id, pts_first DESC);
CREATE INDEX ON sightings USING gin (plate_norm gin_trgm_ops);
CREATE INDEX ON sightings USING hnsw (reid_vec vector_cosine_ops);

CREATE TABLE watchlist (id serial PRIMARY KEY, kind text, plate_norm text, plate_canon text,
  face_vec vector(512), description text, category text, reason text, severity text,
  owner_dept_id int, classification text, added_by int REFERENCES users(id),
  valid_from timestamptz, valid_until timestamptz, source text DEFAULT 'manual');

CREATE TABLE alerts (id serial PRIMARY KEY, watchlist_id int, sighting_id text, camera_id text,
  pts timestamptz, band text, state text DEFAULT 'NEW', count int DEFAULT 1,
  created_at timestamptz DEFAULT now());
CREATE TABLE alert_events (id serial PRIMARY KEY, alert_id int, from_state text, to_state text,
  by_user int, reason text, at timestamptz DEFAULT now());

CREATE TABLE access_grants (id serial PRIMARY KEY, requester int, target_dept_id int,
  case_no text NOT NULL, reason text NOT NULL, approved_by int,
  starts timestamptz, expires timestamptz NOT NULL, state text);

CREATE TABLE audit_log (seq bigserial PRIMARY KEY, at timestamptz DEFAULT now(), user_id int,
  dept_id int, action text, object_type text, object_id text, ip inet, reason text,
  grant_id int, prev_hash bytea, hash bytea NOT NULL);
