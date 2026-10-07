"""Bulk-load parsed GTFS rows under a dataset.

Written with Core inserts and ``COPY`` rather than ORM objects. The ORM models
exist for reading; a 300k-row load needs no identity map, no relationship
cascade and no flush ordering, and paying for them would make the daily
re-import slow enough to feel risky.

Load order matters: composite foreign keys are checked per row, so parents go
in before children, and stations go in before the platforms that reference them.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.gtfs import (
    Agency,
    Calendar,
    CalendarDate,
    Route,
    Stop,
)
from app.services.gtfs.expander import ExpandedTrip
from app.services.gtfs.rows import (
    AgencyRow,
    CalendarDateRow,
    CalendarRow,
    RouteRow,
    StopRow,
    StopTimeRow,
    TripRow,
)

logger = get_logger(__name__)

#: Rows per COPY flush. Bounded so expansion never materialises 300k rows.
BATCH_TRIPS = 2_000

#: Small tables go in through Core inserts; this bounds the parameter count.
INSERT_CHUNK = 1_000


class GTFSRepository:
    """Writes one dataset's worth of GTFS data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- small tables ---------------------------------------------------------

    async def load_agencies(self, dataset_id: int, rows: Sequence[AgencyRow]) -> int:
        return await self._insert(
            Agency,
            [
                {
                    "dataset_id": dataset_id,
                    "agency_id": row.agency_id,
                    "name": row.name,
                    "url": row.url,
                    "timezone": row.timezone,
                    "lang": row.lang,
                }
                for row in rows
            ],
        )

    async def load_routes(self, dataset_id: int, rows: Sequence[RouteRow]) -> int:
        return await self._insert(
            Route,
            [
                {
                    "dataset_id": dataset_id,
                    "route_id": row.route_id,
                    "agency_id": row.agency_id,
                    "short_name": row.short_name,
                    "long_name": row.long_name,
                    "category": row.category,
                    "line": row.line,
                    "route_type": row.route_type,
                }
                for row in rows
            ],
        )

    async def load_stops(
        self,
        dataset_id: int,
        rows: Sequence[StopRow],
        display_names: Mapping[str, str],
    ) -> int:
        """Stations first: platforms carry a foreign key to their parent."""
        ordered = sorted(rows, key=lambda row: not row.is_station)
        return await self._insert(
            Stop,
            [
                {
                    "dataset_id": dataset_id,
                    "stop_id": row.stop_id,
                    "name": row.name,
                    "display_name": display_names.get(row.stop_id),
                    "parent_station_id": row.parent_station_id,
                    "lat": row.lat,
                    "lon": row.lon,
                    "location_type": row.location_type,
                    "platform_code": row.platform_code,
                    # EWKT: the geography column carries the SRID with the value.
                    "point": f"SRID=4326;POINT({row.lon} {row.lat})",
                }
                for row in ordered
            ],
        )

    async def load_calendars(self, dataset_id: int, rows: Sequence[CalendarRow]) -> int:
        return await self._insert(
            Calendar,
            [
                {
                    "dataset_id": dataset_id,
                    "service_id": row.service_id,
                    "monday": row.weekdays[0],
                    "tuesday": row.weekdays[1],
                    "wednesday": row.weekdays[2],
                    "thursday": row.weekdays[3],
                    "friday": row.weekdays[4],
                    "saturday": row.weekdays[5],
                    "sunday": row.weekdays[6],
                    "start_date": row.start_date,
                    "end_date": row.end_date,
                }
                for row in rows
            ],
        )

    async def load_calendar_dates(self, dataset_id: int, rows: Sequence[CalendarDateRow]) -> int:
        return await self._insert(
            CalendarDate,
            [
                {
                    "dataset_id": dataset_id,
                    "service_id": row.service_id,
                    "date": row.date,
                    "exception_type": row.exception_type,
                }
                for row in rows
            ],
        )

    # -- bulk tables ----------------------------------------------------------

    async def load_trips(self, dataset_id: int, rows: Sequence[TripRow]) -> int:
        return await self._copy(
            "trip",
            ("dataset_id", "trip_id", "route_id", "service_id"),
            ((dataset_id, row.trip_id, row.route_id, row.service_id) for row in rows),
        )

    async def load_stop_times(self, dataset_id: int, rows: Sequence[StopTimeRow]) -> int:
        return await self._copy(
            "stop_time",
            (
                "dataset_id",
                "trip_id",
                "stop_sequence",
                "stop_id",
                "arrival_seconds",
                "departure_seconds",
                "stop_headsign",
                "pickup_type",
                "drop_off_type",
            ),
            (
                (
                    dataset_id,
                    row.trip_id,
                    row.stop_sequence,
                    row.stop_id,
                    row.arrival_seconds,
                    row.departure_seconds,
                    row.stop_headsign,
                    row.pickup_type,
                    row.drop_off_type,
                )
                for row in rows
            ),
        )

    async def load_instances(
        self, dataset_id: int, expanded: Iterable[ExpandedTrip]
    ) -> tuple[int, int]:
        """Write trip instances and their calls in bounded batches.

        Batching keeps memory flat across a 300k-row expansion, and writing each
        batch parent-first satisfies the composite foreign key from
        ``stop_time_instance`` back to ``trip_instance``.
        """
        trip_total = 0
        call_total = 0

        for batch in _batched(expanded, BATCH_TRIPS):
            trip_total += await self._copy(
                "trip_instance",
                (
                    "dataset_id",
                    "service_date",
                    "trip_id",
                    "route_id",
                    "starts_at_utc",
                    "ends_at_utc",
                ),
                (
                    (
                        dataset_id,
                        trip.instance.service_date,
                        trip.instance.trip_id,
                        trip.instance.route_id,
                        trip.instance.starts_at_utc,
                        trip.instance.ends_at_utc,
                    )
                    for trip in batch
                ),
            )
            call_total += await self._copy(
                "stop_time_instance",
                (
                    "dataset_id",
                    "service_date",
                    "trip_id",
                    "stop_sequence",
                    "stop_id",
                    "arrival_utc",
                    "departure_utc",
                ),
                (
                    (
                        dataset_id,
                        call.service_date,
                        call.trip_id,
                        call.stop_sequence,
                        call.stop_id,
                        call.arrival_utc,
                        call.departure_utc,
                    )
                    for trip in batch
                    for call in trip.stop_times
                ),
            )

        return trip_total, call_total

    # -- mechanics ------------------------------------------------------------

    async def _insert(self, model: type[Any], values: list[dict[str, Any]]) -> int:
        if not values:
            return 0
        for start in range(0, len(values), INSERT_CHUNK):
            await self._session.execute(insert(model), values[start : start + INSERT_CHUNK])
        return len(values)

    async def _copy(
        self,
        table: str,
        columns: Sequence[str],
        rows: Iterable[tuple[Any, ...]],
    ) -> int:
        """Stream rows into ``table`` with ``COPY ... FROM STDIN``.

        Reaches through SQLAlchemy to the psycopg connection because COPY has no
        Core equivalent. It stays inside the session's transaction, so a failure
        rolls the whole load back with everything else.
        """
        connection = await self._session.connection()
        raw = await connection.get_raw_connection()
        driver_connection = raw.driver_connection
        if driver_connection is None:  # pragma: no cover - psycopg always provides one
            raise RuntimeError("COPY needs a psycopg driver connection")
        column_list = ", ".join(columns)
        statement = f"COPY {table} ({column_list}) FROM STDIN"

        written = 0
        async with driver_connection.cursor() as cursor, cursor.copy(statement) as copy:
            for row in rows:
                await copy.write_row(row)
                written += 1
        return written


def _batched(items: Iterable[ExpandedTrip], size: int) -> Iterator[list[ExpandedTrip]]:
    batch: list[ExpandedTrip] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
