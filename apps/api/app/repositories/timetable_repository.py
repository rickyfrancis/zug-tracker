"""Read the timetable back for the position engine.

The other half of ``gtfs_repository.py``: that module writes a dataset, this
one reads the active dataset as the plain values in
``services/positions/timetable.py``, with platforms already resolved to their
parent stations.
"""

from collections.abc import Sequence
from datetime import datetime
from itertools import groupby
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.gtfs import (
    Agency,
    Dataset,
    Route,
    Stop,
    StopTime,
    StopTimeInstance,
    TripInstance,
)
from app.services.gtfs.station_names import strip_track_suffix
from app.services.positions.timetable import Call, ScheduledTrip, Station

_platform = aliased(Stop, name="platform")
_station = aliased(Stop, name="station")


class TimetableRepository:
    """Reads dated trips out of the active dataset."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def trips_running_at(self, feed_id: str, at: datetime) -> list[ScheduledTrip]:
        """Every trip between its first departure and last arrival at ``at``.

        The window is an indexed range over ``TripInstance``'s absolute UTC
        bounds, so trips crossing midnight need no special case (ADR-0003).
        """
        statement = _calls_statement(feed_id).where(
            TripInstance.starts_at_utc <= at,
            TripInstance.ends_at_utc >= at,
        )
        return await self._trips(statement)

    async def _trips(self, statement: Select[Any]) -> list[ScheduledTrip]:
        rows = (await self._session.execute(statement)).all()
        return [
            _trip(calls)
            for _, calls in groupby(rows, key=lambda row: (row.service_date, row.trip_id))
        ]


def _calls_statement(feed_id: str) -> Select[Any]:
    """Every call of every dated trip in the feed's active dataset, in trip order.

    Scoped by joining the active dataset rather than by an id looked up
    beforehand: an import can flip the active dataset between two statements,
    and this way a read never mixes two timetables. Callers narrow it to the
    trips they want.
    """
    return (
        select(
            TripInstance.trip_id,
            TripInstance.service_date,
            Route.short_name,
            Route.category,
            Agency.name.label("operator"),
            StopTimeInstance.stop_sequence,
            StopTimeInstance.arrival_utc,
            StopTimeInstance.departure_utc,
            StopTime.stop_headsign,
            # A stop without a parent is already a station. The display name
            # is NULL on datasets imported before it existed.
            func.coalesce(_station.stop_id, _platform.stop_id).label("station_id"),
            func.coalesce(
                _station.display_name,
                _station.name,
                _platform.display_name,
                _platform.name,
            ).label("station_name"),
            func.coalesce(_station.lat, _platform.lat).label("station_lat"),
            func.coalesce(_station.lon, _platform.lon).label("station_lon"),
        )
        .join(Dataset, Dataset.id == TripInstance.dataset_id)
        .join(
            Route,
            and_(
                Route.dataset_id == TripInstance.dataset_id,
                Route.route_id == TripInstance.route_id,
            ),
        )
        .join(
            Agency,
            and_(Agency.dataset_id == Route.dataset_id, Agency.agency_id == Route.agency_id),
        )
        .join(
            StopTimeInstance,
            and_(
                StopTimeInstance.dataset_id == TripInstance.dataset_id,
                StopTimeInstance.service_date == TripInstance.service_date,
                StopTimeInstance.trip_id == TripInstance.trip_id,
            ),
        )
        .join(
            StopTime,
            and_(
                StopTime.dataset_id == StopTimeInstance.dataset_id,
                StopTime.trip_id == StopTimeInstance.trip_id,
                StopTime.stop_sequence == StopTimeInstance.stop_sequence,
            ),
        )
        .join(
            _platform,
            and_(
                _platform.dataset_id == StopTimeInstance.dataset_id,
                _platform.stop_id == StopTimeInstance.stop_id,
            ),
        )
        .outerjoin(
            _station,
            and_(
                _station.dataset_id == _platform.dataset_id,
                _station.stop_id == _platform.parent_station_id,
            ),
        )
        .where(Dataset.feed_id == feed_id, Dataset.is_active.is_(True))
        .order_by(
            TripInstance.service_date,
            TripInstance.trip_id,
            StopTimeInstance.stop_sequence,
        )
    )


def _trip(rows: Any) -> ScheduledTrip:
    calls: Sequence[Any] = list(rows)
    first = calls[0]
    return ScheduledTrip(
        trip_id=first.trip_id,
        service_date=first.service_date,
        route_name=first.short_name,
        category=first.category,
        operator=first.operator,
        calls=tuple(
            Call(
                stop_sequence=row.stop_sequence,
                station=Station(
                    station_id=row.station_id,
                    name=row.station_name,
                    lat=row.station_lat,
                    lon=row.station_lon,
                ),
                arrival_utc=row.arrival_utc,
                departure_utc=row.departure_utc,
                headsign=_headsign(row.stop_headsign),
            )
            for row in calls
        ),
    )


def _headsign(raw: str | None) -> str | None:
    """Headsigns carry track ranges too: ``München Hbf Gl.5-10``."""
    return strip_track_suffix(raw) if raw else raw
