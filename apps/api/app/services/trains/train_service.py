"""Trains for the API, read from a position snapshot.

The service answers in plain values; ``schemas/`` turns them into responses.
Positions come only from the snapshot, never recomputed here, so a train looks
the same in every endpoint and Phase 6 changes none of this.
"""

from dataclasses import dataclass
from datetime import datetime

from app.repositories.timetable_repository import TimetableRepository
from app.services.positions.estimator import CorridorResolver, SegmentState, straight_line_between
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

    def _info(self, snapshot: PositionSnapshot) -> SnapshotInfo:
        return SnapshotInfo(
            generated_at=snapshot.generated_at,
            age_seconds=snapshot.age_seconds(self._clock()),
        )
