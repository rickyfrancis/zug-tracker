"""Resolving GTFS service definitions into concrete dates.

The case worth guarding is the one the feed actually contains and the obvious
implementation misses: 60 of its service_ids exist only in
``calendar_dates.txt``, with no weekly pattern at all.
"""

from datetime import date

from app.services.gtfs.rows import CalendarDateRow, CalendarRow
from app.services.gtfs.service_calendar import ServiceCalendar

MONDAY = date(2026, 8, 24)
TUESDAY = date(2026, 8, 25)
SATURDAY = date(2026, 8, 29)


def weekly(service_id: str, *, weekdays: tuple[bool, ...], start: date, end: date) -> CalendarRow:
    return CalendarRow(
        service_id=service_id,
        weekdays=weekdays,  # type: ignore[arg-type]
        start_date=start,
        end_date=end,
    )


WEEKDAYS_ONLY = (True, True, True, True, True, False, False)


def test_weekly_pattern_expands_within_its_own_bounds() -> None:
    calendar = ServiceCalendar.build(
        [weekly("s1", weekdays=WEEKDAYS_ONLY, start=MONDAY, end=SATURDAY)], []
    )

    assert calendar.dates_for("s1") == frozenset(
        {MONDAY, TUESDAY, date(2026, 8, 26), date(2026, 8, 27), date(2026, 8, 28)}
    )


def test_service_defined_only_by_calendar_dates_still_runs() -> None:
    """The 60-service bug: no calendar.txt row at all, but real trips attached."""
    calendar = ServiceCalendar.build([], [CalendarDateRow("s2", MONDAY, exception_type=1)])

    assert calendar.dates_for("s2") == frozenset({MONDAY})
    assert "s2" in calendar.service_ids


def test_exception_adds_a_date_outside_the_weekly_pattern() -> None:
    calendar = ServiceCalendar.build(
        [weekly("s1", weekdays=WEEKDAYS_ONLY, start=MONDAY, end=TUESDAY)],
        [CalendarDateRow("s1", SATURDAY, exception_type=1)],
    )

    assert SATURDAY in calendar.dates_for("s1")


def test_exception_removes_a_date_the_pattern_includes() -> None:
    calendar = ServiceCalendar.build(
        [weekly("s1", weekdays=WEEKDAYS_ONLY, start=MONDAY, end=TUESDAY)],
        [CalendarDateRow("s1", MONDAY, exception_type=2)],
    )

    assert calendar.dates_for("s1") == frozenset({TUESDAY})


def test_a_fully_cancelled_service_yields_no_dates() -> None:
    calendar = ServiceCalendar.build(
        [weekly("s1", weekdays=WEEKDAYS_ONLY, start=MONDAY, end=MONDAY)],
        [CalendarDateRow("s1", MONDAY, exception_type=2)],
    )

    assert calendar.dates_for("s1") == frozenset()


def test_unknown_service_is_empty_rather_than_an_error() -> None:
    assert ServiceCalendar.build([], []).dates_for("nope") == frozenset()


def test_bounds_span_both_files() -> None:
    """Feed validity comes from here: feed_info.txt carries no dates."""
    calendar = ServiceCalendar.build(
        [weekly("s1", weekdays=WEEKDAYS_ONLY, start=MONDAY, end=TUESDAY)],
        [CalendarDateRow("s2", SATURDAY, exception_type=1)],
    )

    assert calendar.bounds() == (MONDAY, SATURDAY)


def test_bounds_are_none_when_nothing_runs() -> None:
    assert ServiceCalendar.build([], []).bounds() is None
