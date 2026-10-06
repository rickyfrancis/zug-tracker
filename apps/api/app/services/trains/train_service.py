"""Trains for the API, read from a position snapshot.

The service answers in plain values; ``schemas/`` turns them into responses.
Positions come only from the snapshot, never recomputed here, so a train looks
the same in every endpoint and Phase 6 changes none of this.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.repositories.timetable_repository import TimetableRepository
from app.services.positions.estimator import (
    CorridorResolver,
    SegmentState,
    merge_station_calls,
    straight_line_between,
)
from app.services.positions.geometry import Polyline
from app.services.positions.route import trip_route
from app.services.positions.timetable import ScheduledTrip, Station, TripWindow
from app.services.trains.filters import TrainFilter
from app.services.trains.snapshot import Clock, PositionSnapshot, SnapshotReader, utc_now


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    """When the positions in a response were estimated, and how long ago."""

    generated_at: datetime
    age_seconds: int


@dataclass(frozen=True, slots=True)
class TrainList:
    snapshot: SnapshotInfo
    trains: tuple[SegmentState, ...]


@dataclass(frozen=True, slots=True)
class StopCall:
    """One station on a trip. No arrival at the origin, no departure at the terminus."""

    sequence: int
    station: Station
    arrival_utc: datetime | None
    departure_utc: datetime | None


@dataclass(frozen=True, slots=True)
class TrainDetail:
    snapshot: SnapshotInfo
    trip: ScheduledTrip
    destination: str
    #: ``None`` when the trip is not running at the snapshot's instant.
    position: SegmentState | None
    stops: tuple[StopCall, ...]
    route: Polyline

    @property
    def origin(self) -> Station:
        return self.stops[0].station

    @property
    def terminus(self) -> Station:
        return self.stops[-1].station

    @property
    def departure_utc(self) -> datetime | None:
        return self.stops[0].departure_utc

    @property
    def arrival_utc(self) -> datetime | None:
        return self.stops[-1].arrival_utc


class TrainService:
    def __init__(
        self,
        snapshots: SnapshotReader,
        timetable: TimetableRepository,
        *,
        feed_id: str,
        clock: Clock = utc_now,
        corridors: CorridorResolver = straight_line_between,
    ) -> None:
        self._snapshots = snapshots
        self._timetable = timetable
        self._feed_id = feed_id
        self._clock = clock
        self._corridors = corridors

    async def trains(self, train_filter: TrainFilter) -> TrainList:
        """Running trains matching ``train_filter``, ordered by trip and date."""
        snapshot = await self._snapshots.read()
        matching = sorted(
            (state for state in snapshot.trains if train_filter.matches(state)),
            key=lambda state: (state.trip_id, state.service_date),
        )
        return TrainList(snapshot=self._info(snapshot), trains=tuple(matching))

    async def detail(self, trip_id: str, service_date: date | None = None) -> TrainDetail | None:
        """One trip with its stops and route, and its position if it is running.

        A trip_id runs on many days, so without ``service_date`` the instance is
        the one in the snapshot - the train the map shows - or failing that the
        one :func:`choose_instance` picks. ``None`` if there is no such trip.
        """
        snapshot = await self._snapshots.read()
        running = snapshot.find(trip_id)
        if service_date is None:
            if running is not None:
                service_date = running.service_date
            else:
                windows = await self._timetable.trip_windows(self._feed_id, trip_id)
                chosen = choose_instance(windows, snapshot.generated_at)
                if chosen is None:
                    return None
                service_date = chosen.service_date

        trip = await self._timetable.trip(self._feed_id, trip_id, service_date)
        if trip is None:
            return None

        position = running if running is not None and running.service_date == service_date else None
        stops = _stops(trip)
        return TrainDetail(
            snapshot=self._info(snapshot),
            trip=trip,
            destination=(
                position.destination
                if position is not None
                else trip.calls[0].headsign or stops[-1].station.name
            ),
            position=position,
            stops=stops,
            route=trip_route(trip.calls, self._corridors),
        )

    def _info(self, snapshot: PositionSnapshot) -> SnapshotInfo:
        return SnapshotInfo(
            generated_at=snapshot.generated_at,
            age_seconds=snapshot.age_seconds(self._clock()),
        )


def choose_instance(windows: Sequence[TripWindow], now: datetime) -> TripWindow | None:
    """The instance of a trip someone asking about it "now" most likely means.

    The one running, else the most recent to have started - a train that has
    just arrived is still the one on screen - else the next to start.
    """
    started = [window for window in windows if window.starts_at_utc <= now]
    running = [window for window in started if window.contains(now)]
    if running:
        return running[0]
    if started:
        return max(started, key=lambda window: window.starts_at_utc)
    upcoming = [window for window in windows if window.starts_at_utc > now]
    return min(upcoming, key=lambda window: window.starts_at_utc, default=None)


def _stops(trip: ScheduledTrip) -> tuple[StopCall, ...]:
    """One row per station, folded as the estimator folds platform changes."""
    calls = merge_station_calls(trip.calls)
    last = len(calls) - 1
    return tuple(
        StopCall(
            sequence=index,
            station=call.station,
            arrival_utc=call.arrival_utc if index > 0 else None,
            departure_utc=call.departure_utc if index < last else None,
        )
        for index, call in enumerate(calls)
    )
