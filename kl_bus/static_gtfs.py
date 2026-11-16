"""Load the static GTFS feed (routes, stops, trips) into reference tables."""

from __future__ import annotations

import io
import logging
import zipfile

import pandas as pd
from psycopg2.extras import execute_values

from kl_bus.config import Config
from kl_bus.extract import fetch_bytes
from kl_bus.load import to_py

log = logging.getLogger(__name__)

# table -> (GTFS file inside the zip, columns, primary key column)
TABLES = {
    "routes": ("routes.txt", ["route_id", "route_short_name", "route_long_name"], "route_id"),
    "stops": ("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon"], "stop_id"),
    "trips": (
        "trips.txt",
        ["trip_id", "route_id", "service_id", "trip_headsign", "direction_id"],
        "trip_id",
    ),
}


def read_gtfs_table(zf: zipfile.ZipFile, filename: str, columns: list[str], key: str) -> pd.DataFrame:
    """Read one GTFS CSV from the zip, keeping only the wanted columns."""
    with zf.open(filename) as fh:
        df = pd.read_csv(
            fh, dtype=str, usecols=lambda c: c.strip() in columns, encoding="utf-8-sig"
        )
    df.columns = [c.strip() for c in df.columns]
    for col in columns:
        if col not in df.columns:
            df[col] = None
    df = df[columns].dropna(subset=[key]).drop_duplicates(subset=[key])
    for col in ("stop_lat", "stop_lon"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_static(conn, cfg: Config) -> dict[str, int]:
    """Download the static GTFS zip and replace the reference tables. Returns row counts."""
    content = fetch_bytes(cfg.static_url, timeout=max(cfg.request_timeout_s, 60), max_retries=cfg.max_retries)
    counts: dict[str, int] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        frames = {
            table: read_gtfs_table(zf, fname, cols, key)
            for table, (fname, cols, key) in TABLES.items()
        }
    with conn.cursor() as cur:
        cur.execute("TRUNCATE routes, stops, trips")
        for table, df in frames.items():
            cols = TABLES[table][1]
            rows = [tuple(to_py(v) for v in r) for r in df.itertuples(index=False, name=None)]
            if rows:
                execute_values(
                    cur,
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s",
                    rows,
                    page_size=5000,
                )
            counts[table] = len(rows)
    conn.commit()
    log.info("static GTFS loaded: %s", counts)
    return counts
