import pandas as pd

from kl_bus.transform import COLUMNS, clean_positions

BBOX = (3.03, 101.58, 3.25, 101.78)


def row(**overrides):
    base = dict(
        vehicle_id="BUS1",
        trip_id="T1",
        route_id="R1",
        latitude=3.14,
        longitude=101.69,
        speed=10.0,  # m/s
        bearing=90.0,
        feed_timestamp=1_700_000_000,
        current_status="IN_TRANSIT_TO",
        stop_id="S1",
        congestion_level="RUNNING_SMOOTHLY",
    )
    base.update(overrides)
    return base


def test_empty_input_returns_empty_frame_with_columns():
    df, stats = clean_positions([], BBOX)
    assert df.empty
    assert list(df.columns) == COLUMNS
    assert stats["kept"] == 0


def test_happy_path_converts_units_and_timestamp():
    df, stats = clean_positions([row()], BBOX)
    assert len(df) == 1
    assert df.loc[0, "speed_kmh"] == 36.0  # 10 m/s -> 36 km/h
    assert df.loc[0, "feed_timestamp"] == pd.Timestamp("2023-11-14 22:13:20", tz="UTC")
    assert list(df.columns) == COLUMNS
    assert stats["kept"] == 1


def test_drops_rows_missing_required_fields():
    rows = [
        row(vehicle_id=None),
        row(vehicle_id="  "),
        row(latitude=None),
        row(feed_timestamp=None),
        row(vehicle_id="OK"),
    ]
    df, stats = clean_positions(rows, BBOX)
    assert list(df["vehicle_id"]) == ["OK"]
    assert stats["dropped_missing"] == 4


def test_drops_positions_outside_bbox():
    rows = [
        row(vehicle_id="IN"),
        row(vehicle_id="JB", latitude=1.49, longitude=103.74),  # Johor Bahru
        row(vehicle_id="NULL_ISLAND", latitude=0.0, longitude=0.0),
    ]
    df, stats = clean_positions(rows, BBOX)
    assert list(df["vehicle_id"]) == ["IN"]
    assert stats["dropped_out_of_area"] == 2


def test_route_allowlist_filters_routes():
    rows = [row(vehicle_id="A", route_id="R1"), row(vehicle_id="B", route_id="R9")]
    df, stats = clean_positions(rows, BBOX, route_allowlist={"R1"})
    assert list(df["vehicle_id"]) == ["A"]
    assert stats["dropped_route"] == 1


def test_implausible_speed_is_nulled_not_dropped():
    rows = [
        row(vehicle_id="FAST", speed=50.0),  # 180 km/h
        row(vehicle_id="NEG", speed=-1.0),
        row(vehicle_id="OK", speed=5.0),
    ]
    df, stats = clean_positions(rows, BBOX, max_speed_kmh=100)
    by_id = df.set_index("vehicle_id")["speed_kmh"]
    assert pd.isna(by_id["FAST"])
    assert pd.isna(by_id["NEG"])
    assert by_id["OK"] == 18.0
    assert stats["speed_nulled"] == 2
    assert len(df) == 3


def test_invalid_bearing_is_nulled():
    df, _ = clean_positions([row(bearing=400.0)], BBOX)
    assert pd.isna(df.loc[0, "bearing"])


def test_duplicate_vehicle_timestamp_is_removed():
    rows = [row(), row(speed=2.0)]
    df, stats = clean_positions(rows, BBOX)
    assert len(df) == 1
    assert stats["duplicates"] == 1


def test_same_vehicle_different_timestamps_are_kept():
    rows = [row(feed_timestamp=1_700_000_000), row(feed_timestamp=1_700_000_030)]
    df, _ = clean_positions(rows, BBOX)
    assert len(df) == 2


def test_missing_optional_columns_do_not_crash():
    minimal = [
        {"vehicle_id": "X", "latitude": 3.14, "longitude": 101.69, "feed_timestamp": 1_700_000_000}
    ]
    df, _ = clean_positions(minimal, BBOX)
    assert len(df) == 1
    assert pd.isna(df.loc[0, "speed_kmh"])
