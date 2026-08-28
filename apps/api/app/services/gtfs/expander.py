"""Expand undated trips into dated instances with absolute UTC timestamps.

This is where the two hardest facts about the feed are resolved once, so that
nothing downstream has to think about them again:

- **16% of trips cross midnight**, with ``stop_times`` hours reaching 35.
- **Service dates are not calendar dates**, and DST makes the difference real.

The output is what the worker's hot loop reads: a trip instance whose bounds are
absolute UTC, so "which trains are running now" becomes an indexed range query
rather than per-tick timezone arithmetic. See ADR-0003.

Expansion yields one trip at a time rather than building the whole 300k-row
result, so the importer can write it in bounded batches.
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.logging import get_logger
from app.services.gtfs.rows import FeedContents, StopTimeRow
from app.services.gtfs.service_calendar import ServiceCalendar
from app.services.gtfs.time_conversion import service_day_origin_utc

logger = get_logger(__name__)

#: A trip needs two calls to describe any movement at all.
MINIMUM_STOPS = 2


@dataclass(frozen=True, slots=True)
class TripInstanceRow:
    service_date: date
    trip_id: str
    route_id: str
    #: Departure from the first stop and arrival at the last: the window during
    #: which the train is actually between stations.
    starts_at_utc: datetime
    ends_at_utc: datetime


@dataclass(frozen=True, slots=True)
class StopTimeInstanceRow:
    service_date: date
    trip_id: str
    stop_sequence: int
    stop_id: str
    arrival_utc: datetime
    departure_utc: datetime


@dataclass(frozen=True, slots=True)
class ExpandedTrip:
    """One trip on one date, with its calls. Written parent-first."""

    instance: TripInstanceRow
    stop_times: tuple[StopTimeInstanceRow, ...]


class TripExpander:
    """Turns ``trips x service dates`` into dated rows."""

    def __init__(self, timezone: ZoneInfo) -> None:
        self._timezone = timezone

    def expand(self, feed: FeedContents, calendar: ServiceCalendar) -> Iterator[ExpandedTrip]:
        stop_times_by_trip = _group_stop_times(feed.stop_times)
        # The origin is per service date, not per trip: computing it once saves
        # ~300k redundant timezone resolutions.
        origins: dict[date, datetime] = {}
        skipped = 0

        for trip in feed.trips:
            calls = stop_times_by_trip.get(trip.trip_id, ())
            if len(calls) < MINIMUM_STOPS:
                skipped += 1
                continue

            for service_date in sorted(calendar.dates_for(trip.service_id)):
                if service_date not in origins:
                    origins[service_date] = service_day_origin_utc(service_date, self._timezone)
                origin = origins[service_date]

                stop_times = tuple(
                    StopTimeInstanceRow(
                        service_date=service_date,
                        trip_id=trip.trip_id,
                        stop_sequence=call.stop_sequence,
                        stop_id=call.stop_id,
                        arrival_utc=origin + _seconds(call.arrival_seconds),
                        departure_utc=origin + _seconds(call.departure_seconds),
                    )
                    for call in calls
                )

                yield ExpandedTrip(
                    instance=TripInstanceRow(
                        service_date=service_date,
                        trip_id=trip.trip_id,
                        route_id=trip.route_id,
                        starts_at_utc=stop_times[0].departure_utc,
                        ends_at_utc=stop_times[-1].arrival_utc,
                    ),
                    stop_times=stop_times,
                )

        if skipped:
            logger.warning("gtfs.expand.trips_without_enough_stops", count=skipped)


def _seconds(value: int) -> timedelta:
    return timedelta(seconds=value)


def _group_stop_times(
    stop_times: tuple[StopTimeRow, ...],
) -> dict[str, tuple[StopTimeRow, ...]]:
    """Group calls by trip, ordered by ``stop_sequence``.

    The feed happens to arrive in order, but nothing in GTFS promises that and
    the first and last entries decide the trip's bounds.
    """
    grouped: dict[str, list[StopTimeRow]] = defaultdict(list)
    for call in stop_times:
        grouped[call.trip_id].append(call)
    return {
        trip_id: tuple(sorted(calls, key=lambda call: call.stop_sequence))
        for trip_id, calls in grouped.items()
    }
