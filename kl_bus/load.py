"""Load: write cleaned data into PostgreSQL."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from kl_bus.transform import COLUMNS

log = logging.getLogger(__name__)

_INSERT_SQL = f"""
INSERT INTO vehicle_positions ({", ".join(COLUMNS)})
VALUES %s
ON CONFLICT (vehicle_id, feed_timestamp) DO NOTHING
RETURNING 1
"""


def connect(database_url: str):
    return psycopg2.connect(database_url)


def to_py(value: Any) -> Any:
    """Convert pandas/numpy scalars (NaN, NA, NaT, Timestamp, np types) to plain Python."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        return value.item()
    return value


def insert_positions(conn, df: pd.DataFrame) -> int:
    """Insert rows, skipping ones that already exist. Returns rows actually inserted."""
    if df.empty:
        return 0
    rows = [tuple(to_py(v) for v in r) for r in df[COLUMNS].itertuples(index=False, name=None)]
    with conn.cursor() as cur:
        # fetch=True collects RETURNING rows across all pages, giving an exact count
        inserted = execute_values(cur, _INSERT_SQL, rows, page_size=1000, fetch=True)
    conn.commit()
    return len(inserted)


def log_run(
    conn,
    status: str,
    rows_fetched: int,
    rows_kept: int,
    rows_inserted: int,
    error: Optional[str] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_runs (status, rows_fetched, rows_kept, rows_inserted, error)"
            " VALUES (%s, %s, %s, %s, %s)",
            (status, rows_fetched, rows_kept, rows_inserted, error),
        )
    conn.commit()


def apply_sql_files(conn, sql_dir: Path) -> list[str]:
    """Run every *.sql file in sql_dir in filename order. Files are idempotent."""
    applied = []
    for path in sorted(sql_dir.glob("*.sql")):
        with conn.cursor() as cur:
            cur.execute(path.read_text(encoding="utf-8"))
        conn.commit()
        applied.append(path.name)
        log.info("applied %s", path.name)
    return applied
