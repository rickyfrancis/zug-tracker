"""Parse the GTFS text files into typed rows.

**Every file is read by header name.** ``routes.txt`` in this feed ships as
``route_long_name, route_short_name, agency_id, route_type, route_id`` - the
GTFS spec fixes no column order, and positional parsing against that header
silently loads route ids into name columns. A missing column raises here rather
than corrupting a load.
"""

import csv
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager
from datetime import date
from typing import IO

from app.services.gtfs.rows import (
    AgencyRow,
    CalendarDateRow,
    CalendarRow,
    FeedContents,
    RouteRow,
    StopRow,
    StopTimeRow,
    TripRow,
)
from app.services.gtfs.time_conversion import parse_gtfs_time

Row = Mapping[str, str | None]

#: Opens one feed file by name. Supplied by the provider, so the parser never
#: knows whether it is reading a zip member, a temp file or a StringIO.
OpenText = Callable[[str], AbstractContextManager[IO[str]]]

#: Monday-first so the tuple index matches ``date.weekday()``.
WEEKDAY_COLUMNS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class GTFSParseError(ValueError):
    """The feed is not shaped the way the importer requires."""


def read_rows(stream: IO[str], *, filename: str, required: Iterable[str]) -> Iterator[Row]:
    """Yield rows keyed by header name, failing loudly on a missing column."""
    reader = csv.DictReader(stream)
    headers = set(reader.fieldnames or ())
    missing = sorted(set(required) - headers)
    if missing:
        raise GTFSParseError(f"{filename} is missing required column(s): {', '.join(missing)}")
    yield from reader


def _text(row: Row, column: str) -> str | None:
    """Return a trimmed value, treating an empty cell as absent."""
    value = row.get(column)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _required_text(row: Row, column: str, *, filename: str) -> str:
    value = _text(row, column)
    if value is None:
        raise GTFSParseError(f"{filename}: empty value in required column {column!r}")
    return value


def _int(row: Row, column: str) -> int | None:
    value = _text(row, column)
    return None if value is None else int(value)


def _bool(row: Row, column: str) -> bool:
    return _text(row, column) == "1"


def parse_date(value: str) -> date:
    """Parse a GTFS ``YYYYMMDD`` date."""
    if len(value) != 8 or not value.isdigit():
        raise GTFSParseError(f"expected YYYYMMDD, got {value!r}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def split_short_name(short_name: str) -> tuple[str, str | None]:
    """Split ``route_short_name`` into category and line.

    fv_free ships ``"ICE 10"`` for most routes but a bare ``"ICE"`` for 953
    trips (17% of the feed), so the line half is genuinely absent rather than
    merely unparsed - it is not invented from anywhere else.
    """
    parts = short_name.strip().split(maxsplit=1)
    if not parts:
        raise GTFSParseError("route_short_name is empty; it is the only line label the feed has")
    category = parts[0].upper()
    line = parts[1].strip() if len(parts) > 1 else None
    return category, line


def parse_agencies(stream: IO[str]) -> tuple[AgencyRow, ...]:
    required = ("agency_id", "agency_name", "agency_timezone")
    return tuple(
        AgencyRow(
            agency_id=_required_text(row, "agency_id", filename="agency.txt"),
            name=_required_text(row, "agency_name", filename="agency.txt"),
            url=_text(row, "agency_url"),
            timezone=_required_text(row, "agency_timezone", filename="agency.txt"),
            lang=_text(row, "agency_lang"),
        )
        for row in read_rows(stream, filename="agency.txt", required=required)
    )


def parse_routes(stream: IO[str]) -> tuple[RouteRow, ...]:
    required = ("route_id", "agency_id", "route_short_name", "route_type")
    routes = []
    for row in read_rows(stream, filename="routes.txt", required=required):
        short_name = _required_text(row, "route_short_name", filename="routes.txt")
        category, line = split_short_name(short_name)
        routes.append(
            RouteRow(
                route_id=_required_text(row, "route_id", filename="routes.txt"),
                agency_id=_required_text(row, "agency_id", filename="routes.txt"),
                short_name=short_name,
                long_name=_text(row, "route_long_name"),
                category=category,
                line=line,
                route_type=int(_required_text(row, "route_type", filename="routes.txt")),
            )
        )
    return tuple(routes)


def parse_stops(stream: IO[str]) -> tuple[StopRow, ...]:
    required = ("stop_id", "stop_name", "stop_lat", "stop_lon")
    return tuple(
        StopRow(
            stop_id=_required_text(row, "stop_id", filename="stops.txt"),
            name=_required_text(row, "stop_name", filename="stops.txt"),
            parent_station_id=_text(row, "parent_station"),
            lat=float(_required_text(row, "stop_lat", filename="stops.txt")),
            lon=float(_required_text(row, "stop_lon", filename="stops.txt")),
            # Blank means 0 (a stop/platform) per the GTFS default.
            location_type=_int(row, "location_type") or 0,
            platform_code=_text(row, "platform_code"),
        )
        for row in read_rows(stream, filename="stops.txt", required=required)
    )


def parse_calendars(stream: IO[str]) -> tuple[CalendarRow, ...]:
    required = ("service_id", "start_date", "end_date", *WEEKDAY_COLUMNS)
    calendars = []
    for row in read_rows(stream, filename="calendar.txt", required=required):
        weekdays = tuple(_bool(row, column) for column in WEEKDAY_COLUMNS)
        calendars.append(
            CalendarRow(
                service_id=_required_text(row, "service_id", filename="calendar.txt"),
                weekdays=weekdays,  # type: ignore[arg-type]
                start_date=parse_date(_required_text(row, "start_date", filename="calendar.txt")),
                end_date=parse_date(_required_text(row, "end_date", filename="calendar.txt")),
            )
        )
    return tuple(calendars)


def parse_calendar_dates(stream: IO[str]) -> tuple[CalendarDateRow, ...]:
    required = ("service_id", "date", "exception_type")
    return tuple(
        CalendarDateRow(
            service_id=_required_text(row, "service_id", filename="calendar_dates.txt"),
            date=parse_date(_required_text(row, "date", filename="calendar_dates.txt")),
            exception_type=int(
                _required_text(row, "exception_type", filename="calendar_dates.txt")
            ),
        )
        for row in read_rows(stream, filename="calendar_dates.txt", required=required)
    )


def parse_trips(stream: IO[str]) -> tuple[TripRow, ...]:
    required = ("trip_id", "route_id", "service_id")
    return tuple(
        TripRow(
            trip_id=_required_text(row, "trip_id", filename="trips.txt"),
            route_id=_required_text(row, "route_id", filename="trips.txt"),
            service_id=_required_text(row, "service_id", filename="trips.txt"),
        )
        for row in read_rows(stream, filename="trips.txt", required=required)
    )


def parse_stop_times(stream: IO[str]) -> tuple[StopTimeRow, ...]:
    required = ("trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time")
    return tuple(
        StopTimeRow(
            trip_id=_required_text(row, "trip_id", filename="stop_times.txt"),
            stop_sequence=int(_required_text(row, "stop_sequence", filename="stop_times.txt")),
            stop_id=_required_text(row, "stop_id", filename="stop_times.txt"),
            arrival_seconds=parse_gtfs_time(
                _required_text(row, "arrival_time", filename="stop_times.txt")
            ),
            departure_seconds=parse_gtfs_time(
                _required_text(row, "departure_time", filename="stop_times.txt")
            ),
            stop_headsign=_text(row, "stop_headsign"),
            pickup_type=_int(row, "pickup_type"),
            drop_off_type=_int(row, "drop_off_type"),
        )
        for row in read_rows(stream, filename="stop_times.txt", required=required)
    )


def parse_feed(open_text: OpenText) -> FeedContents:
    """Parse a whole feed, given a callable that opens one file by name."""
    with open_text("agency.txt") as stream:
        agencies = parse_agencies(stream)
    with open_text("routes.txt") as stream:
        routes = parse_routes(stream)
    with open_text("stops.txt") as stream:
        stops = parse_stops(stream)
    with open_text("calendar.txt") as stream:
        calendars = parse_calendars(stream)
    with open_text("calendar_dates.txt") as stream:
        calendar_dates = parse_calendar_dates(stream)
    with open_text("trips.txt") as stream:
        trips = parse_trips(stream)
    with open_text("stop_times.txt") as stream:
        stop_times = parse_stop_times(stream)

    return FeedContents(
        agencies=agencies,
        routes=routes,
        stops=stops,
        calendars=calendars,
        calendar_dates=calendar_dates,
        trips=trips,
        stop_times=stop_times,
    )
