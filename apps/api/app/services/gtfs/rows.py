"""Typed rows parsed out of the GTFS text files.

These are the boundary between "what the feed said" and everything downstream.
Parsing produces them; expansion and the repositories consume them. Nothing
below this module handles a raw CSV string.
"""

from dataclasses import dataclass
from datetime import date

#: calendar_dates.txt exception_type values.
SERVICE_ADDED = 1
SERVICE_REMOVED = 2


@dataclass(frozen=True, slots=True)
class AgencyRow:
    agency_id: str
    name: str
    url: str | None
    timezone: str
    lang: str | None


@dataclass(frozen=True, slots=True)
class RouteRow:
    route_id: str
    agency_id: str
    short_name: str
    long_name: str | None
    category: str
    line: str | None
    route_type: int


@dataclass(frozen=True, slots=True)
class StopRow:
    stop_id: str
    name: str
    parent_station_id: str | None
    lat: float
    lon: float
    location_type: int
    platform_code: str | None

    @property
    def is_station(self) -> bool:
        return self.location_type == 1


@dataclass(frozen=True, slots=True)
class CalendarRow:
    service_id: str
    #: Monday-first, matching ``date.weekday()``.
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    start_date: date
    end_date: date

    def runs_on(self, day: date) -> bool:
        return self.weekdays[day.weekday()] and self.start_date <= day <= self.end_date


@dataclass(frozen=True, slots=True)
class CalendarDateRow:
    service_id: str
    date: date
    exception_type: int


@dataclass(frozen=True, slots=True)
class TripRow:
    trip_id: str
    route_id: str
    service_id: str


@dataclass(frozen=True, slots=True)
class StopTimeRow:
    trip_id: str
    stop_sequence: int
    stop_id: str
    #: Seconds from the service day start; may exceed 86400.
    arrival_seconds: int
    departure_seconds: int
    stop_headsign: str | None
    pickup_type: int | None
    drop_off_type: int | None


@dataclass(frozen=True, slots=True)
class FeedContents:
    """Everything parsed out of one feed archive."""

    agencies: tuple[AgencyRow, ...]
    routes: tuple[RouteRow, ...]
    stops: tuple[StopRow, ...]
    calendars: tuple[CalendarRow, ...]
    calendar_dates: tuple[CalendarDateRow, ...]
    trips: tuple[TripRow, ...]
    stop_times: tuple[StopTimeRow, ...]
