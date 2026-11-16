"""Extract: download the GTFS-Realtime feed and decode it into plain dicts."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

USER_AGENT = "kl-bus-pipeline/0.1 (personal student project)"


class FetchError(RuntimeError):
    """Raised when a URL could not be fetched after all retries."""


def fetch_bytes(
    url: str,
    timeout: float = 20,
    max_retries: int = 3,
    backoff_s: float = 2.0,
    session: Optional[Any] = None,
) -> bytes:
    """GET a URL with retries and exponential backoff; return the body bytes."""
    client = session if session is not None else requests
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("fetch attempt %d/%d failed: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(backoff_s * 2 ** (attempt - 1))
    raise FetchError(f"giving up on {url} after {max_retries} attempts") from last_exc


def _enum_name(enum_wrapper: Any, value: int) -> Optional[str]:
    try:
        return enum_wrapper.Name(value)
    except ValueError:
        return None


def parse_vehicle_positions(content: bytes) -> list[dict]:
    """Decode a GTFS-Realtime protobuf payload into a list of flat dicts.

    Only entities that carry a vehicle position are returned. Values are left
    raw (speed in m/s as per the GTFS-RT spec, timestamps as epoch seconds);
    cleaning and unit conversion happen in transform.py.
    """
    # Imported here so modules that don't need protobuf (and their tests)
    # can be imported without it installed.
    from google.transit import gtfs_realtime_pb2 as pb

    feed = pb.FeedMessage()
    feed.ParseFromString(content)
    header_ts = feed.header.timestamp or None

    rows: list[dict] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        has_pos = v.HasField("position")
        pos = v.position
        rows.append(
            {
                "vehicle_id": v.vehicle.id or v.vehicle.license_plate or None,
                "trip_id": v.trip.trip_id or None,
                "route_id": v.trip.route_id or None,
                "latitude": pos.latitude if has_pos else None,
                "longitude": pos.longitude if has_pos else None,
                "speed": pos.speed if has_pos and pos.HasField("speed") else None,
                "bearing": pos.bearing if has_pos and pos.HasField("bearing") else None,
                "feed_timestamp": v.timestamp if v.HasField("timestamp") else header_ts,
                "current_status": (
                    _enum_name(pb.VehiclePosition.VehicleStopStatus, v.current_status)
                    if v.HasField("current_status")
                    else None
                ),
                "stop_id": v.stop_id or None,
                "congestion_level": (
                    _enum_name(pb.VehiclePosition.CongestionLevel, v.congestion_level)
                    if v.HasField("congestion_level")
                    else None
                ),
            }
        )
    return rows
