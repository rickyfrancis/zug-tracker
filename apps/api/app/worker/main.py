"""Background worker.

Runs the same image as the API but a different command. Today it only proves
the stack is wired up by refreshing a heartbeat in Redis; Phase 2 adds the GTFS
import and Phase 6 replaces the tick body with GTFS-Realtime polling. The loop
and shutdown handling stay as they are.
"""

import asyncio
import signal
from contextlib import suppress
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis

logger = get_logger(__name__)


class Worker:
    """Periodic task loop with graceful shutdown."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._database = Database(settings.database_url)
        self._redis: Redis = create_redis(settings.redis_url)
        self._stop = asyncio.Event()
        self._tick_count = 0

    def request_stop(self) -> None:
        logger.info("worker.stop_requested")
        self._stop.set()

    async def run(self) -> None:
        logger.info(
            "worker.startup",
            environment=self._settings.environment,
            interval_seconds=self._settings.worker_interval_seconds,
        )
        try:
            while not self._stop.is_set():
                await self._tick()
                await self._sleep_until_next_tick()
        finally:
            await self._shutdown()

    async def _tick(self) -> None:
        self._tick_count += 1
        try:
            await self._heartbeat()
        except Exception as exc:  # noqa: BLE001 - a failing tick must not kill the loop
            logger.error("worker.tick_failed", tick=self._tick_count, error=str(exc))

    async def _heartbeat(self) -> None:
        """Touch both backing services and publish the result to Redis."""
        async with self._database.session() as session:
            await session.execute(text("SELECT 1"))

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        await self._redis.set(
            self._settings.worker_heartbeat_key,
            timestamp,
            ex=self._settings.heartbeat_ttl_seconds,
        )
        logger.info("worker.tick", tick=self._tick_count, at=timestamp)

    async def _sleep_until_next_tick(self) -> None:
        """Sleep, but wake up immediately when shutdown is requested."""
        with suppress(TimeoutError):
            await asyncio.wait_for(
                self._stop.wait(), timeout=self._settings.worker_interval_seconds
            )

    async def _shutdown(self) -> None:
        await self._redis.aclose()
        await self._database.dispose()
        logger.info("worker.shutdown", ticks=self._tick_count)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    worker = Worker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
