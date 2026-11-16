"""Command line entry point: python -m kl_bus <command>"""

from __future__ import annotations

import argparse
import logging
from contextlib import closing
from pathlib import Path

from kl_bus.config import load_config

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kl_bus", description=__doc__)
    parser.add_argument(
        "command",
        choices=["init-db", "load-static", "poll", "poll-once"],
        help=(
            "init-db: create tables and views | load-static: load routes/stops/trips | "
            "poll: run continuously | poll-once: run a single cycle"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()

    if args.command == "init-db":
        from kl_bus.load import apply_sql_files, connect

        with closing(connect(cfg.database_url)) as conn:
            apply_sql_files(conn, SQL_DIR)
    elif args.command == "load-static":
        from kl_bus.load import connect
        from kl_bus.static_gtfs import load_static

        with closing(connect(cfg.database_url)) as conn:
            load_static(conn, cfg)
    elif args.command == "poll-once":
        from kl_bus.poller import run_once

        result = run_once(cfg)
        return 0 if result["status"] == "ok" else 1
    else:
        from kl_bus.poller import run_forever

        run_forever(cfg)
    return 0
