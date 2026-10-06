"""The timetable as the position engine sees it.

Plain values, not ORM rows: the estimator is pure and is tested without a
database, so it takes these and the repository builds them. By the time a trip
gets here, everything awkward about the feed has already been resolved -
service-day offsets are absolute UTC (ADR-0003) and platforms are their parent
station.
"""

from dataclasses import dataclass
from datetime import date, datetime

from app.services.positions.geometry import Point


@dataclass(frozen=True, slots=True)
class Station:
    """A station, never a platform.

    ``stop_times`` reference platforms, and two platforms of one station are
    metres apart. Segments are drawn between stations or they come out
    near-zero length.
    """

    station_id: str
    name: str
    lat: float
    lon: float

    @property
    def point(self) -> Point:
        return Point(lat=self.lat, lon=self.lon)


@dataclass(frozen=True, slots=True)
class Call:
    """One scheduled stop of a dated trip."""

    stop_sequence: int
    station: Station
    arrival_utc: datetime
    departure_utc: datetime

    #: The destination shown on the train from this stop onwards. Populated on
    #: every stop time in fv_free, and the only destination the feed carries.
    headsign: str | None


@dataclass(frozen=True, slots=True)
class ScheduledTrip:
    """One trip on one service date, with its calls in stop order."""

    trip_id: str
    service_date: date

    #: ``route_short_name`` verbatim: ``"ICE 10"``, or a bare ``"ICE"`` on the
    #: 17% of trips whose route has no line number. There is no train number.
    route_name: str
    category: str
    operator: str
    calls: tuple[Call, ...]
