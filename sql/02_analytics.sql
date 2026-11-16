-- KL bus pipeline: analytics views (idempotent, safe to re-run)
-- All times are converted to Malaysia time (Asia/Kuala_Lumpur) for reporting.

-- 1. Average speed of moving buses by route, hour of day and weekday/weekend.
--    Observations with speed <= 1 km/h are excluded so stops and terminals
--    don't drag the average down.
CREATE OR REPLACE VIEW v_hourly_speed AS
SELECT
    route_id,
    EXTRACT(HOUR FROM feed_timestamp AT TIME ZONE 'Asia/Kuala_Lumpur')::int       AS hour_kl,
    (EXTRACT(ISODOW FROM feed_timestamp AT TIME ZONE 'Asia/Kuala_Lumpur') >= 6)   AS is_weekend,
    COUNT(*)                                                                      AS n_obs,
    ROUND(AVG(speed_kmh)::numeric, 1)                                             AS avg_moving_speed_kmh
FROM vehicle_positions
WHERE speed_kmh IS NOT NULL
  AND speed_kmh > 1
GROUP BY 1, 2, 3;

-- 2. Bus bunching (proxy): two buses on the same route, heading in roughly
--    the same direction, within 150 m of each other in the same minute.
--    Known limitation: buses idling together at a terminal also match, so
--    consider excluding observations near terminals when you analyse this.
--    Performance note: this scans the whole table. On large datasets filter
--    by date when querying, or materialise per day.
CREATE OR REPLACE VIEW v_bunching_events AS
WITH per_minute AS (
    SELECT DISTINCT ON (vehicle_id, date_trunc('minute', feed_timestamp))
        vehicle_id,
        route_id,
        date_trunc('minute', feed_timestamp) AS minute_ts,
        latitude,
        longitude,
        bearing
    FROM vehicle_positions
    WHERE route_id IS NOT NULL
      AND bearing  IS NOT NULL
    ORDER BY vehicle_id, date_trunc('minute', feed_timestamp), feed_timestamp DESC
),
pairs AS (
    SELECT
        a.route_id,
        a.minute_ts,
        a.vehicle_id AS vehicle_a,
        b.vehicle_id AS vehicle_b,
        sqrt(
            power((a.latitude  - b.latitude)  * 111000, 2) +
            power((a.longitude - b.longitude) * 111000 * cos(radians(a.latitude)), 2)
        ) AS distance_m
    FROM per_minute a
    JOIN per_minute b
      ON  a.route_id  = b.route_id
      AND a.minute_ts = b.minute_ts
      AND a.vehicle_id < b.vehicle_id
    WHERE LEAST(abs(a.bearing - b.bearing), 360 - abs(a.bearing - b.bearing)) < 45
)
SELECT *
FROM pairs
WHERE distance_m < 150;

-- 3. Pipeline health: polls per hour, how many succeeded, rows inserted.
--    Use this to spot gaps before drawing conclusions from the data.
CREATE OR REPLACE VIEW v_ingest_health AS
SELECT
    date_trunc('hour', run_at AT TIME ZONE 'Asia/Kuala_Lumpur') AS hour_kl,
    COUNT(*)                                                    AS runs,
    COUNT(*) FILTER (WHERE status = 'ok')                       AS ok_runs,
    COALESCE(SUM(rows_inserted), 0)                             AS rows_inserted
FROM ingest_runs
GROUP BY 1;

-- 4. Data quality: route ids seen in realtime data but absent from static GTFS.
CREATE OR REPLACE VIEW v_unmatched_routes AS
SELECT vp.route_id, COUNT(*) AS n_obs
FROM vehicle_positions vp
LEFT JOIN routes r ON r.route_id = vp.route_id
WHERE vp.route_id IS NOT NULL
  AND r.route_id IS NULL
GROUP BY vp.route_id;

-- Example queries
-- Worst bunching routes:
--   SELECT route_id, COUNT(*) AS bunched_pairs
--   FROM v_bunching_events GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
-- Slowest hours across the network:
--   SELECT hour_kl, ROUND(AVG(avg_moving_speed_kmh), 1) AS avg_kmh
--   FROM v_hourly_speed WHERE NOT is_weekend GROUP BY 1 ORDER BY 2 LIMIT 5;
