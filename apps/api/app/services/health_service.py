"""Health checks for the API's backing services.

Route handlers stay thin: they call :class:`HealthService` and translate the
report into a response.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

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
class HealthReport:
    status: OverallStatus
    checked_at: datetime
    dependencies: tuple[DependencyCheck, ...]


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
    ) -> None:
        self._session = session
        self._redis = redis
        self._heartbeat_key = heartbeat_key
        self._heartbeat_ttl_seconds = heartbeat_ttl_seconds

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
