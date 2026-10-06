"""Positions for every running train.

Glue only: the repository says which trains are running, the estimator says
where each one is. From Phase 6 the worker calls this once per tick and writes
the result to Redis, so the cost is per train rather than per train per client.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.timetable_repository import TimetableRepository
from app.services.positions.estimator import SegmentState, TrainPositionEstimator


class PositionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        feed_id: str,
        estimator: TrainPositionEstimator | None = None,
    ) -> None:
        self._session = session
        self._feed_id = feed_id
        self._estimator = estimator or TrainPositionEstimator()

    async def positions_at(self, now: datetime) -> list[SegmentState]:
        """Segment state for every train running at ``now``.

        Empty, not an error, before the first import: a freshly deployed stack
        has no timetable yet and that is an ordinary state.
        """
        trips = await TimetableRepository(self._session).trips_running_at(self._feed_id, now)
        states = (self._estimator.estimate(trip, now) for trip in trips)
        return [state for state in states if state is not None]
