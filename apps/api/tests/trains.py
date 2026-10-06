"""Builders shared by the train service and API tests."""

from datetime import UTC, date, datetime

from app.services.positions.estimator import PositionSource, SegmentState, TrainStatus
from app.services.positions.timetable import Station

BERLIN = Station("900003201", "Berlin Hbf", 52.525589, 13.369548)
HAMBURG = Station("294573", "Hamburg Hbf", 53.553533, 10.006692)
LEIPZIG = Station("900008012", "Leipzig Hbf", 51.345, 12.382)
MUENCHEN = Station("800000261", "München Hbf", 48.140232, 11.558335)

#: Monday 24 August 2026, 08:00 UTC.
NOW = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)


def at(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def segment_state(
    *,
    trip_id: str = "t1",
    service_date: date = date(2026, 8, 24),
    category: str = "ICE",
    status: TrainStatus = TrainStatus.MOVING,
    from_station: Station = BERLIN,
    to_station: Station = LEIPZIG,
    progress: float = 0.5,
) -> SegmentState:
    return SegmentState(
        trip_id=trip_id,
        service_date=service_date,
        label=f"{category} 10",
        destination="München Hbf",
        category=category,
        operator="DB Fernverkehr AG",
        status=status,
        from_station=from_station,
        to_station=to_station,
        departure_utc=at(7, 30),
        arrival_utc=at(8, 30),
        progress=progress,
        lat=(from_station.lat + to_station.lat) / 2,
        lon=(from_station.lon + to_station.lon) / 2,
        bearing=200.0,
        geometry_ref=None,
        delay_seconds=None,
        position_source=PositionSource.SCHEDULED,
    )
