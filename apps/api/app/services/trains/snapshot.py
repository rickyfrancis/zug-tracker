"""Where the API's positions come from.

Every train endpoint reads one :class:`PositionSnapshot` - every running train
at one instant - and never asks how it was made. In Phase 4 it is computed on
the request (:class:`LiveSnapshotReader`). From Phase 6 the worker computes it
once per tick and writes it to Redis, and a second reader returns that instead:
the only change is which reader ``api/deps.py`` hands out. See ADR-0005.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.services.positions.estimator import SegmentState
from app.services.positions.position_service import PositionService

#: Supplies "now". Injected so that every endpoint is deterministic under test.
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """Every running train, as estimated at ``generated_at``."""

    generated_at: datetime
    trains: tuple[SegmentState, ...]

    def age_seconds(self, now: datetime) -> int:
        """Whole seconds since the snapshot was made; never negative.

        Clamped because the worker's clock and the API's need not agree to the
        second, and a snapshot "from the future" is simply fresh.
        """
        return max(0, math.floor((now - self.generated_at).total_seconds()))

    def find(self, trip_id: str) -> SegmentState | None:
        """The running instance of ``trip_id``. Trips last at most 18 hours, so
        there is never more than one."""
        return next((state for state in self.trains if state.trip_id == trip_id), None)


class SnapshotReader(Protocol):
    async def read(self) -> PositionSnapshot: ...


class LiveSnapshotReader:
    """Computes the snapshot on the spot, so it is always zero seconds old."""

    def __init__(self, positions: PositionService, clock: Clock = utc_now) -> None:
        self._positions = positions
        self._clock = clock

    async def read(self) -> PositionSnapshot:
        now = self._clock()
        return PositionSnapshot(
            generated_at=now, trains=tuple(await self._positions.positions_at(now))
        )
