-- KL bus pipeline: core schema (idempotent, safe to re-run)

-- ---------------------------------------------------------------
-- Static GTFS reference tables (reloaded wholesale by `load-static`)
-- No foreign keys on purpose: the realtime feed can reference route/trip
-- ids that are missing from the static feed, and we want to measure that
-- (see v_unmatched_routes) rather than have inserts fail.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routes (
    route_id         TEXT PRIMARY KEY,
    route_short_name TEXT,
    route_long_name  TEXT
);

CREATE TABLE IF NOT EXISTS stops (
    stop_id   TEXT PRIMARY KEY,
    stop_name TEXT,
    stop_lat  DOUBLE PRECISION,
    stop_lon  DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS trips (
    trip_id       TEXT PRIMARY KEY,
    route_id      TEXT,
    service_id    TEXT,
    trip_headsign TEXT,
    direction_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_trips_route ON trips (route_id);

-- ---------------------------------------------------------------
-- Realtime vehicle positions (one row per vehicle per feed timestamp)
-- The feed repeats a vehicle's last known position until it reports again,
-- so the primary key makes re-ingesting the same observation a no-op.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vehicle_positions (
    vehicle_id       TEXT             NOT NULL,
    feed_timestamp   TIMESTAMPTZ      NOT NULL,
    route_id         TEXT,
    trip_id          TEXT,
    latitude         DOUBLE PRECISION NOT NULL CHECK (latitude  BETWEEN -90  AND 90),
    longitude        DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    speed_kmh        REAL,
    bearing          REAL,
    current_status   TEXT,
    stop_id          TEXT,
    congestion_level TEXT,
    ingested_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (vehicle_id, feed_timestamp)
);

CREATE INDEX IF NOT EXISTS idx_vp_route_time ON vehicle_positions (route_id, feed_timestamp);
CREATE INDEX IF NOT EXISTS idx_vp_time       ON vehicle_positions (feed_timestamp);

-- ---------------------------------------------------------------
-- One row per poll attempt: lets you see gaps, failures and row counts
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_runs (
    id            BIGSERIAL   PRIMARY KEY,
    run_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    status        TEXT        NOT NULL CHECK (status IN ('ok', 'error')),
    rows_fetched  INT         NOT NULL DEFAULT 0,
    rows_kept     INT         NOT NULL DEFAULT 0,
    rows_inserted INT         NOT NULL DEFAULT 0,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_time ON ingest_runs (run_at);
