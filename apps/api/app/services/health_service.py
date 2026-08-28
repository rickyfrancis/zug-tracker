"""Health checks for the API's backing services.

Route handlers stay thin: they call :class:`HealthService` and translate the
report into a response.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.dataset_repository import DatasetRepository

logger = get_logger(__name__)


class DependencyStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    UNKNOWN = "unknown"


class OverallStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    status: DependencyStatus
    latency_ms: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class DatasetInfo:
    """The timetable currently being served.

    Informational: an expired or missing dataset does not make the API
    unhealthy, so it never flips the overall status. It is reported because
    until Phase 6 schedules re-imports, the feed's 31-day validity window is
    the thing most likely to quietly empty the map, and a deployment should be
    able to see that coming rather than discover it.
    """

    feed_id: str
    version: str
    imported_at: datetime
    valid_from: date
    valid_to: date

    @property
    def days_until_expiry(self) -> int:
        return (self.valid_to - datetime.now(UTC).date()).days

    @property
    def is_expired(self) -> bool:
        return self.days_until_expiry < 0


@dataclass(frozen=True)
class HealthReport:
    status: OverallStatus
    checked_at: datetime
    dependencies: tuple[DependencyCheck, ...]
    dataset: DatasetInfo | None = None


class HealthService:
    """Probes PostgreSQL, Redis and the worker heartbeat."""

    #: A degraded worker does not make the API unusable, so it is reported but
    #: does not flip the overall status.
    CRITICAL_DEPENDENCIES = frozenset({"postgres", "redis"})

    #: Upper bound per probe. Without it a dependency that accepts connections
    #: but never answers would hang the endpoint instead of failing it.
    PROBE_TIMEOUT_SECONDS = 3.0

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        *,
        heartbeat_key: str,
        heartbeat_ttl_seconds: int,
        feed_id: str,
    ) -> None:
        self._session = session
        self._redis = redis
        self._heartbeat_key = heartbeat_key
        self._heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self._feed_id = feed_id

    async def check(self) -> HealthReport:
        # Probes are independent, so run them concurrently: the endpoint's worst
        # case stays one PROBE_TIMEOUT_SECONDS rather than the sum of them.
        dependencies = tuple(
            await asyncio.gather(
                self._check_postgres(),
                self._check_redis(),
                self._check_worker(),
            )
        )
        failed = [
            check
            for check in dependencies
            if check.name in self.CRITICAL_DEPENDENCIES and check.status is not DependencyStatus.OK
        ]
        status = OverallStatus.DEGRADED if failed else OverallStatus.OK
        return HealthReport(
            status=status,
            checked_at=datetime.now(UTC),
            dependencies=dependencies,
            dataset=await self._active_dataset(),
        )

    async def _active_dataset(self) -> DatasetInfo | None:
        """Read the active dataset, tolerating its absence.

        Nothing here may raise: the table does not exist before the Phase 2
        migration runs, and no data has been imported before the first import.
        Both are ordinary states for a freshly deployed stack.
        """
        try:
            async with asyncio.timeout(self.PROBE_TIMEOUT_SECONDS):
                dataset = await DatasetRepository(self._session).active(self._feed_id)
        except Exception as exc:  # noqa: BLE001 - informational, never fatal
            logger.warning("healthcheck.dataset.unavailable", error=str(exc))
            return None

        if dataset is None:
            return None
        return DatasetInfo(
            feed_id=dataset.feed_id,
            version=dataset.version,
            imported_at=dataset.imported_at,
            valid_from=dataset.valid_from,
            valid_to=dataset.valid_to,
        )

    async def _check_postgres(self) -> DependencyCheck:
        async def probe() -> None:
            await self._session.execute(text("SELECT 1"))

        return await self._probe("postgres", probe)

    async def _check_redis(self) -> DependencyCheck:
        async def probe() -> None:
            await self._redis.ping()

        return await self._probe("redis", probe)

    async def _probe(self, name: str, probe: Callable[[], Awaitable[None]]) -> DependencyCheck:
        """Run one dependency probe under a timeout and turn failures into a status."""
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.PROBE_TIMEOUT_SECONDS):
                await probe()
        except TimeoutError:
            detail = f"timed out after {self.PROBE_TIMEOUT_SECONDS}s"
            logger.warning(f"healthcheck.{name}.timeout")
            return DependencyCheck(name, DependencyStatus.ERROR, _elapsed_ms(started), detail)
        except Exception as exc:  # noqa: BLE001 - any failure means "not healthy"
            logger.warning(f"healthcheck.{name}.failed", error=str(exc))
            return DependencyCheck(name, DependencyStatus.ERROR, _elapsed_ms(started), str(exc))
        return DependencyCheck(name, DependencyStatus.OK, _elapsed_ms(started))

    async def _check_worker(self) -> DependencyCheck:
        """Read the heartbeat the worker refreshes on every tick.

        The key carries a TTL, so a missing key means the worker has been quiet
        for longer than the allowed window.
        """
        try:
            async with asyncio.timeout(self.PROBE_TIMEOUT_SECONDS):
                raw = await self._redis.get(self._heartbeat_key)
        except TimeoutError:
            return DependencyCheck(
                "worker", DependencyStatus.UNKNOWN, detail="heartbeat read timed out"
            )
        except Exception as exc:  # noqa: BLE001
            return DependencyCheck("worker", DependencyStatus.UNKNOWN, detail=str(exc))

        # The client decodes responses, but the stub allows bytes too.
        heartbeat = raw.decode() if isinstance(raw, bytes) else raw
        if heartbeat is None:
            return DependencyCheck(
                "worker",
                DependencyStatus.UNKNOWN,
                detail=f"no heartbeat within {self._heartbeat_ttl_seconds}s",
            )
        return DependencyCheck("worker", DependencyStatus.OK, detail=f"last tick {heartbeat}")


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
