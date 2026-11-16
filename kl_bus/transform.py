"""Transform: clean raw vehicle-position dicts into a validated DataFrame."""

from __future__ import annotations

import logging
from typing import Iterable

import pandas as pd

from kl_bus.config import BBox

log = logging.getLogger(__name__)

# Columns of the cleaned frame, in the order the loader inserts them.
COLUMNS = [
    "vehicle_id",
    "feed_timestamp",
    "route_id",
    "trip_id",
    "latitude",
    "longitude",
    "speed_kmh",
    "bearing",
    "current_status",
    "stop_id",
    "congestion_level",
]

_RAW_COLUMNS = [
    "vehicle_id",
    "route_id",
    "trip_id",
    "latitude",
    "longitude",
    "speed",
    "bearing",
    "feed_timestamp",
    "current_status",
    "stop_id",
    "congestion_level",
]

MS_TO_KMH = 3.6  # GTFS-RT speed is metres per second


def clean_positions(
    rows: list[dict],
    bbox: BBox,
    route_allowlist: Iterable[str] = frozenset(),
    max_speed_kmh: float = 100.0,
) -> tuple[pd.DataFrame, dict]:
    """Validate and normalise raw rows.

    Steps: drop rows missing id/coordinates/timestamp, drop positions outside
    the bounding box, optionally keep only allow-listed routes, convert epoch
    seconds to UTC timestamps, convert speed to km/h and null implausible
    values, null invalid bearings, and drop duplicate (vehicle, timestamp).

    Returns the cleaned DataFrame and a dict of counts for logging/monitoring.
    """
    allowlist = frozenset(route_allowlist)
    stats = {
        "fetched": len(rows),
        "dropped_missing": 0,
        "dropped_out_of_area": 0,
        "dropped_route": 0,
        "speed_nulled": 0,
        "duplicates": 0,
        "kept": 0,
    }
    if not rows:
        return pd.DataFrame(columns=COLUMNS), stats

    df = pd.DataFrame(rows)
    for col in _RAW_COLUMNS:
        if col not in df.columns:
            df[col] = None

    for col in ("latitude", "longitude", "speed", "bearing", "feed_timestamp"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["vehicle_id"] = df["vehicle_id"].astype("string").str.strip().replace("", pd.NA)

    before = len(df)
    df = df.dropna(subset=["vehicle_id", "latitude", "longitude", "feed_timestamp"])
    stats["dropped_missing"] = before - len(df)

    min_lat, min_lon, max_lat, max_lon = bbox
    in_area = df["latitude"].between(min_lat, max_lat) & df["longitude"].between(
        min_lon, max_lon
    )
    stats["dropped_out_of_area"] = int((~in_area).sum())
    df = df[in_area]

    if allowlist:
        keep = df["route_id"].isin(allowlist)
        stats["dropped_route"] = int((~keep).sum())
        df = df[keep]

    df = df.copy()
    df["feed_timestamp"] = pd.to_datetime(df["feed_timestamp"], unit="s", utc=True)

    df["speed_kmh"] = df["speed"] * MS_TO_KMH
    bad_speed = df["speed_kmh"].notna() & (
        (df["speed_kmh"] < 0) | (df["speed_kmh"] > max_speed_kmh)
    )
    stats["speed_nulled"] = int(bad_speed.sum())
    df.loc[bad_speed, "speed_kmh"] = float("nan")

    bad_bearing = df["bearing"].notna() & ((df["bearing"] < 0) | (df["bearing"] > 360))
    df.loc[bad_bearing, "bearing"] = float("nan")

    before = len(df)
    df = df.drop_duplicates(subset=["vehicle_id", "feed_timestamp"], keep="last")
    stats["duplicates"] = before - len(df)

    df = df[COLUMNS].reset_index(drop=True)
    stats["kept"] = len(df)
    log.debug("transform stats: %s", stats)
    return df, stats
