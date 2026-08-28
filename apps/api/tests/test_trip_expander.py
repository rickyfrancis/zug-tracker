"""Expanding trips into dated instances."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.services.gtfs.expander import TripExpander
from app.services.gtfs.rows import (
    CalendarDateRow,
    FeedContents,
    StopTimeRow,
    TripRow,
)
from app.services.gtfs.service_calendar import ServiceCalendar

BERLIN = ZoneInfo("Europe/Berlin")
SERVICE_DATE = date(2026, 8, 24)


def call(sequence: int, arrival: int, departure: int, stop_id: str = "s") -> StopTimeRow:
    return StopTimeRow(
        trip_id="t1",
        stop_sequence=sequence,
        stop_id=stop_id,
        arrival_seconds=arrival,
        departure_seconds=departure,
        stop_headsign="München Hbf",
        pickup_type=None,
        drop_off_type=None,
    )


def feed(*stop_times: StopTimeRow) -> FeedContents:
    return FeedContents(
        agencies=(),
        routes=(),
        stops=(),
        calendars=(),
        calendar_dates=(),
        trips=(TripRow(trip_id="t1", route_id="r1", service_id="svc"),),
        stop_times=stop_times,
    )


def one_service_date() -> ServiceCalendar:
    return ServiceCalendar.build([], [CalendarDateRow("svc", SERVICE_DATE, exception_type=1)])


def expand(*stop_times: StopTimeRow) -> list:
    return list(TripExpander(BERLIN).expand(feed(*stop_times), one_service_date()))


def test_bounds_run_from_first_departure_to_last_arrival() -> None:
    """Not first arrival: the window is when the train is actually moving."""
    expanded = expand(call(0, 28_800, 29_100), call(1, 32_400, 32_700))

    instance = expanded[0].instance
    assert instance.starts_at_utc == datetime(2026, 8, 24, 6, 5, tzinfo=UTC)  # 08:05 CEST
    assert instance.ends_at_utc == datetime(2026, 8, 24, 7, 0, tzinfo=UTC)  # 09:00 CEST
    assert instance.route_id == "r1"


def test_calls_after_midnight_land_on_the_next_calendar_day() -> None:
    """16% of this feed's trips do exactly this."""
    expanded = expand(call(0, 82_800, 82_800), call(1, 100_440, 100_440))

    last = expanded[0].stop_times[-1]
    assert last.arrival_utc.astimezone(BERLIN).date() == date(2026, 8, 25)
    assert last.service_date == SERVICE_DATE  # still one trip, one service date


def test_calls_are_ordered_by_stop_sequence_not_file_order() -> None:
    """The bounds depend on first and last; GTFS promises no row ordering."""
    expanded = expand(call(1, 32_400, 32_700), call(0, 28_800, 29_100))

    assert [c.stop_sequence for c in expanded[0].stop_times] == [0, 1]
    assert expanded[0].instance.starts_at_utc < expanded[0].instance.ends_at_utc


def test_a_trip_runs_once_per_service_date() -> None:
    calendar = ServiceCalendar.build(
        [],
        [
            CalendarDateRow("svc", SERVICE_DATE, exception_type=1),
            CalendarDateRow("svc", date(2026, 8, 25), exception_type=1),
        ],
    )

    expanded = list(
        TripExpander(BERLIN).expand(feed(call(0, 0, 0), call(1, 3_600, 3_600)), calendar)
    )

    assert sorted(e.instance.service_date for e in expanded) == [SERVICE_DATE, date(2026, 8, 25)]


def test_a_trip_with_one_call_is_skipped() -> None:
    """A single stop describes no movement, so there is nothing to interpolate."""
    assert expand(call(0, 0, 0)) == []


def test_a_service_that_never_runs_produces_nothing() -> None:
    expanded = list(
        TripExpander(BERLIN).expand(
            feed(call(0, 0, 0), call(1, 3_600, 3_600)), ServiceCalendar.build([], [])
        )
    )

    assert expanded == []
