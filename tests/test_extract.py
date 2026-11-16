import pytest
import requests

from kl_bus import extract


class FakeResponse:
    content = b"payload"

    def raise_for_status(self):
        pass


class FlakySession:
    """Fails the first `failures` calls, then succeeds."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("boom")
        return FakeResponse()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda _s: None)


def test_fetch_retries_then_succeeds():
    session = FlakySession(failures=2)
    assert extract.fetch_bytes("http://x", max_retries=3, session=session) == b"payload"
    assert session.calls == 3


def test_fetch_raises_after_exhausting_retries():
    session = FlakySession(failures=10)
    with pytest.raises(extract.FetchError):
        extract.fetch_bytes("http://x", max_retries=3, session=session)
    assert session.calls == 3


def test_parse_vehicle_positions_decodes_protobuf():
    pb = pytest.importorskip("google.transit.gtfs_realtime_pb2")

    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_700_000_000

    bus = feed.entity.add()
    bus.id = "1"
    v = bus.vehicle
    v.vehicle.id = "BUS1"
    v.trip.trip_id = "T1"
    v.trip.route_id = "R1"
    v.position.latitude = 3.14
    v.position.longitude = 101.69
    v.position.speed = 10.0
    v.position.bearing = 90.0
    v.timestamp = 1_700_000_001
    v.current_status = pb.VehiclePosition.IN_TRANSIT_TO

    # An entity without a vehicle (e.g. a trip update) must be skipped
    other = feed.entity.add()
    other.id = "2"
    other.trip_update.trip.trip_id = "T2"

    rows = extract.parse_vehicle_positions(feed.SerializeToString())

    assert len(rows) == 1
    r = rows[0]
    assert r["vehicle_id"] == "BUS1"
    assert r["route_id"] == "R1"
    assert r["latitude"] == pytest.approx(3.14, abs=1e-4)
    assert r["longitude"] == pytest.approx(101.69, abs=1e-4)
    assert r["speed"] == pytest.approx(10.0)
    assert r["feed_timestamp"] == 1_700_000_001
    assert r["current_status"] == "IN_TRANSIT_TO"
