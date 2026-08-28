"""Resolve GTFS service definitions into the concrete dates they run on.

Two files describe when a service operates, and the naive reading - walk
``calendar.txt`` and patch it with ``calendar_dates.txt`` - drops services
silently. In this feed **60 of 1,057 service_ids appear only in
calendar_dates.txt**, with no weekly pattern at all; they are one-off dates,
and they carry real trips. So the set of services is the *union* of both files,
not the key set of either.

Everything here is pure. It is the fiddliest logic in the import and the part
most worth testing without a database attached.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from app.services.gtfs.rows import (
    SERVICE_ADDED,
    SERVICE_REMOVED,
    CalendarDateRow,
    CalendarRow,
)


class ServiceCalendar:
    """Which dates each ``service_id`` operates on."""

    def __init__(self, dates_by_service: dict[str, frozenset[date]]) -> None:
        self._dates_by_service = dates_by_service

    @classmethod
    def build(
        cls,
        calendars: Iterable[CalendarRow],
        calendar_dates: Iterable[CalendarDateRow],
    ) -> "ServiceCalendar":
        exceptions: dict[str, list[CalendarDateRow]] = defaultdict(list)
        for exception in calendar_dates:
            exceptions[exception.service_id].append(exception)

        patterns = {calendar.service_id: calendar for calendar in calendars}

        resolved: dict[str, frozenset[date]] = {}
        for service_id in patterns.keys() | exceptions.keys():
            pattern = patterns.get(service_id)
            days = set(_weekly_dates(pattern)) if pattern else set()

            for exception in exceptions.get(service_id, ()):
                if exception.exception_type == SERVICE_ADDED:
                    days.add(exception.date)
                elif exception.exception_type == SERVICE_REMOVED:
                    days.discard(exception.date)

            resolved[service_id] = frozenset(days)

        return cls(resolved)

    def dates_for(self, service_id: str) -> frozenset[date]:
        """Dates this service runs. Empty for an unknown or fully-cancelled service."""
        return self._dates_by_service.get(service_id, frozenset())

    @property
    def service_ids(self) -> frozenset[str]:
        return frozenset(self._dates_by_service)

    def bounds(self) -> tuple[date, date] | None:
        """The feed's real validity window.

        Derived here because ``feed_info.txt`` in this feed carries no dates at
        all and its ``feed_version`` is the constant string ``latest-fv-free``.
        """
        all_dates = {day for days in self._dates_by_service.values() for day in days}
        if not all_dates:
            return None
        return min(all_dates), max(all_dates)


def _weekly_dates(pattern: CalendarRow) -> Iterable[date]:
    day = pattern.start_date
    while day <= pattern.end_date:
        if pattern.weekdays[day.weekday()]:
            yield day
        day += timedelta(days=1)
