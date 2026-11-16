"""Poller: run extract -> transform -> load on a fixed interval."""

from __future__ import annotations

import gzip
import logging
import signal
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from kl_bus.config import Config
from kl_bus.extract import fetch_bytes, parse_vehicle_positions
from kl_bus.load import connect, insert_positions, log_run
from kl_bus.transform import clean_positions

log = logging.getLogger(__name__)


def save_raw(content: bytes, raw_dir: Path) -> Path:
    """Keep a gzipped copy of the raw protobuf so a transform bug can be reprocessed."""
    now = datetime.now(timezone.utc)
    path = raw_dir / f"{now:%Y/%m/%d}" / f"{now:%H%M%S}.pb.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(content))
    return path


def _record_run(cfg: Config, status: str, fetched: int, kept: int, inserted: int, error):
    try:
        with closing(connect(cfg.database_url)) as conn:
            log_run(conn, status, fetched, kept, inserted, error)
    except Exception as exc:  # never let monitoring crash the poller
        log.warning("could not record run in ingest_runs: %s", exc)


def run_once(cfg: Config, tick: int = 0) -> dict:
    """One full pipeline cycle. Never raises: failures are logged and recorded."""
    fetched = kept = inserted = 0
    error = None
    try:
        content = fetch_bytes(
            cfg.realtime_url, timeout=cfg.request_timeout_s, max_retries=cfg.max_retries
        )
        if cfg.raw_every_n > 0 and tick % cfg.raw_every_n == 0:
            save_raw(content, cfg.raw_dir)
        rows = parse_vehicle_positions(content)
        df, stats = clean_positions(rows, cfg.bbox, cfg.route_allowlist, cfg.max_speed_kmh)
        fetched, kept = stats["fetched"], stats["kept"]
        with closing(connect(cfg.database_url)) as conn:
            inserted = insert_positions(conn, df)
        log.info(
            "ok: fetched=%d kept=%d inserted=%d (out_of_area=%d, speed_nulled=%d)",
            fetched, kept, inserted, stats["dropped_out_of_area"], stats["speed_nulled"],
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.error("poll failed: %s", error)
    status = "ok" if error is None else "error"
    _record_run(cfg, status, fetched, kept, inserted, error)
    return {"status": status, "fetched": fetched, "kept": kept, "inserted": inserted}


def run_forever(cfg: Config) -> None:
    stop = threading.Event()

    def _handle(signum, _frame):
        log.info("received signal %s, shutting down after current cycle", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    log.info(
        "polling every %ds (bbox=%s, routes=%s)",
        cfg.poll_interval_s, cfg.bbox, sorted(cfg.route_allowlist) or "all",
    )
    tick = 0
    while not stop.is_set():
        started = time.monotonic()
        run_once(cfg, tick)
        tick += 1
        stop.wait(max(0.0, cfg.poll_interval_s - (time.monotonic() - started)))
    log.info("stopped")
