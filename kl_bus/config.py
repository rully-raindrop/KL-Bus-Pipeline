"""Configuration, read from environment variables with sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

# Official Malaysian open data (data.gov.my). Check the developer docs if these
# ever stop working: https://developer.data.gov.my/realtime-api/gtfs-realtime
DEFAULT_REALTIME_URL = (
    "https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana"
    "?category=rapid-bus-kl"
)
DEFAULT_STATIC_URL = (
    "https://openapi-malaysia-transport.s3.ap-southeast-1.amazonaws.com/"
    "prasarana/gtfs_rapid_bus_kl.zip"
)

# (min_lat, min_lon, max_lat, max_lon): a rough box around Kuala Lumpur
# (roughly Sentul/Kepong to Bukit Jalil, Bangsar to Setapak/Cheras).
DEFAULT_BBOX = (3.03, 101.58, 3.25, 101.78)

BBox = tuple[float, float, float, float]


def parse_bbox(raw: str) -> BBox:
    parts = [float(p) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("KL_BBOX must be 'min_lat,min_lon,max_lat,max_lon'")
    min_lat, min_lon, max_lat, max_lon = parts
    if min_lat >= max_lat or min_lon >= max_lon:
        raise ValueError("KL_BBOX minimums must be smaller than maximums")
    return (min_lat, min_lon, max_lat, max_lon)


@dataclass(frozen=True)
class Config:
    database_url: str
    realtime_url: str
    static_url: str
    poll_interval_s: int
    request_timeout_s: int
    max_retries: int
    bbox: BBox
    route_allowlist: frozenset[str]  # empty = keep every route in the bbox
    max_speed_kmh: float
    raw_dir: Path
    raw_every_n: int  # save every Nth raw snapshot; 0 disables


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    env = os.environ if env is None else env
    routes = frozenset(r.strip() for r in env.get("ROUTES", "").split(",") if r.strip())
    return Config(
        database_url=env.get(
            "DATABASE_URL", "postgresql://klbus:klbus@localhost:5432/klbus"
        ),
        realtime_url=env.get("REALTIME_URL", DEFAULT_REALTIME_URL),
        static_url=env.get("STATIC_URL", DEFAULT_STATIC_URL),
        poll_interval_s=int(env.get("POLL_INTERVAL_S", "30")),
        request_timeout_s=int(env.get("REQUEST_TIMEOUT_S", "20")),
        max_retries=int(env.get("MAX_RETRIES", "3")),
        bbox=parse_bbox(env["KL_BBOX"]) if env.get("KL_BBOX") else DEFAULT_BBOX,
        route_allowlist=routes,
        max_speed_kmh=float(env.get("MAX_SPEED_KMH", "100")),
        raw_dir=Path(env.get("RAW_DIR", "data/raw")),
        raw_every_n=int(env.get("RAW_EVERY_N", "20")),
    )
