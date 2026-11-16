# KL Bus Pipeline

An automated data pipeline that collects **Rapid KL bus positions in Kuala Lumpur** every 30 seconds, cleans and validates them, and stores them in PostgreSQL for analysis of bus bunching, speed patterns and slow zones.

Data: Prasarana's GTFS-Realtime and static GTFS feeds, published through [data.gov.my](https://developer.data.gov.my/realtime-api/gtfs-realtime). Credit to Prasarana Malaysia Berhad and data.gov.my; please check their terms of use before publishing derived data.

## Architecture

```mermaid
flowchart LR
    A[data.gov.my<br/>GTFS-Realtime feed] -->|every 30 s| B[extract<br/>fetch + retry + decode protobuf]
    B --> R[(raw snapshots<br/>gzip, every Nth poll)]
    B --> C[transform<br/>validate, filter to KL, convert units, dedupe]
    C --> D[(PostgreSQL<br/>vehicle_positions)]
    S[Static GTFS zip<br/>routes, stops, trips] --> E[load-static] --> D
    P[poller<br/>logs every run to ingest_runs] -.-> B
    D --> V[SQL views<br/>speed, bunching, health, data quality]
```

## Quick start (Docker)

```bash
cp .env.example .env            # optional; defaults work
docker compose up -d --build    # starts Postgres (schema auto-created) and the poller

# load route/stop/trip reference data once (and refresh weekly)
docker compose run --rm poller python -m kl_bus load-static

# watch it work
docker compose logs -f poller
docker compose exec db psql -U klbus -d klbus -c "SELECT count(*) FROM vehicle_positions;"
```

## Running locally (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# start any PostgreSQL 14+ and create a database, then:
export DATABASE_URL=postgresql://user:pass@localhost:5432/klbus
python -m kl_bus init-db        # tables + views
python -m kl_bus load-static    # routes/stops/trips
python -m kl_bus poll-once      # a single cycle, good for a first test
python -m kl_bus poll           # run continuously
pytest -q                       # unit tests (no network or database needed)
```

## Configuration

All optional, set via environment variables or `.env` (see `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_S` | `30` | Seconds between polls |
| `KL_BBOX` | `3.03,101.58,3.25,101.78` | `min_lat,min_lon,max_lat,max_lon`; positions outside are dropped |
| `ROUTES` | empty (all) | Comma-separated route ids to keep, e.g. your commute routes |
| `RAW_EVERY_N` | `20` | Save every Nth raw snapshot to `data/raw` (`0` disables) |
| `MAX_SPEED_KMH` | `100` | Speeds above this are treated as sensor errors and nulled |
| `DATABASE_URL` | local Postgres | Connection string |

## Data model

| Table | Purpose |
|---|---|
| `vehicle_positions` | One row per vehicle per feed timestamp. Primary key `(vehicle_id, feed_timestamp)` makes ingestion idempotent |
| `routes`, `stops`, `trips` | Static GTFS reference data |
| `ingest_runs` | One row per poll: status, rows fetched/kept/inserted, error text |

Analytics views (`sql/02_analytics.sql`): `v_hourly_speed`, `v_bunching_events`, `v_ingest_health`, `v_unmatched_routes`.

## Design decisions

- **Idempotent loads.** The feed repeats a bus's last known position until it reports again. `ON CONFLICT DO NOTHING` on `(vehicle_id, feed_timestamp)` means stale or repeated observations never create duplicates.
- **Raw snapshots kept (sampled).** If a transform bug is found later, saved raw payloads can be reprocessed. Saving every poll would use a lot of disk, so only every Nth is kept.
- **Failures are data.** Every poll writes to `ingest_runs`, so gaps in the dataset are visible and explainable before any analysis.
- **No foreign keys from positions to static tables.** Realtime ids may not match the static feed; `v_unmatched_routes` measures that instead of failing inserts.
- **Pure transform module.** `clean_positions` takes plain dicts and returns a DataFrame, so it is unit-tested without the network, protobuf or a database.
- **Timestamps stored in UTC, reported in `Asia/Kuala_Lumpur`.**

## Known limitations and things to verify

These were written against the published docs and have not all been checked against live data yet. Check them first when you run it:

- **Speed units.** The GTFS-RT spec says metres per second, and the pipeline converts to km/h. Compare a few values against what you'd expect; if they look 3.6x too high, remove the conversion in `transform.py`.
- **Route id matching.** Confirm realtime `route_id` values match static `routes.route_id` (`SELECT * FROM v_unmatched_routes;`). If not, you may need to join through `trips`.
- **Bounding box.** It is a rough rectangle, not the real KL boundary. Tighten it or use a route allow-list.
- **Bunching metric** is a proxy (same route, similar bearing, under 150 m, same minute) and will also flag buses idling at terminals.
- **Static GTFS URL** may change. Override with `STATIC_URL` if it does.

## Roadmap

- [ ] Streamlit dashboard: live map, speed by hour, bunching by route
- [ ] Headway analysis at stops using `stop_times` from the static feed
- [ ] Data quality checks as a scheduled report (e.g. Great Expectations or plain SQL assertions)
- [ ] dbt models on top of `vehicle_positions`
- [ ] Add `rapid-bus-mrtfeeder` and `rapid-rail-kl` categories
- [ ] Daily partitioning or a retention policy for `vehicle_positions`
- [ ] Deploy on a small VPS so collection runs 24/7

## Project layout

```
kl_bus/          extract.py, transform.py, load.py, static_gtfs.py, poller.py, cli.py, config.py
sql/             01_schema.sql, 02_analytics.sql
tests/           unit tests for transform and extract
Dockerfile, docker-compose.yml, .github/workflows/ci.yml
```
