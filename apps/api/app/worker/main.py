"""Background worker.

Runs the same image as the API but a different command. It owns two jobs today:

    heartbeat        every WORKER_INTERVAL_SECONDS   - proves the stack is alive
    refresh-feed     every GTFS_REFRESH_INTERVAL_S   - re-imports the timetable

Phase 6 adds a third for GTFS-Realtime polling; because each job carries its own
interval (see ``jobs.py``), that is a registration rather than a restructuring.

The feed refresh is here rather than in cron because the feed's validity window
is 31 days and an expired feed serves an empty map. Nothing about a manual step
survives contact with a deployed demo. The refresh runs the same
``GTFSImportService`` as ``python -m app.cli import-data``, so the scheduled and
manual paths cannot drift apart.
"""

import asyncio
import signal
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis
from app.providers.gtfs_static import GTFSStaticProvider
from app.services.gtfs.import_service import GTFSImportService
from app.worker.jobs import Job, run_jobs

logger = get_logger(__name__)


class Worker:
    """Owns the worker's jobs and their shared resources."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._database = Database(settings.database_url)
        self._redis: Redis = create_redis(settings.redis_url)
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        logger.info("worker.stop_requested")
        self._stop.set()

    async def run(self) -> None:
        jobs = self._build_jobs()
        logger.info(
            "worker.startup",
            environment=self._settings.environment,
            jobs=[job.name for job in jobs],
        )
        try:
            runners = await run_jobs(jobs, self._stop)
        finally:
            await self._shutdown()
        logger.info("worker.stopped", runs={runner.name: runner.runs for runner in runners})

    def _build_jobs(self) -> list[Job]:
        jobs = [
            Job(
                name="heartbeat",
                run=self._heartbeat,
                interval_seconds=self._settings.worker_interval_seconds,
            )
        ]

        if self._settings.gtfs_static_url:
            jobs.append(
                Job(
                    name="refresh-feed",
                    run=self._refresh_feed,
                    interval_seconds=self._settings.gtfs_refresh_interval_seconds,
                    retry_seconds=self._settings.gtfs_refresh_retry_seconds,
                )
            )
        else:
            # Better to run without the job and say so than to register one that
            # can only ever fail.
            logger.warning("worker.refresh_feed.disabled", reason="GTFS_STATIC_URL is not set")

        return jobs

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
        logger.info("worker.heartbeat", at=timestamp)

    async def _refresh_feed(self) -> None:
        """Re-import the static feed if the origin says it changed.

        The conditional GET means an unchanged feed costs one 304, so this is
        cheap enough to run on every startup as well as daily.
        """
        service = GTFSImportService(
            self._database,
            GTFSStaticProvider(self._settings.gtfs_static_url),
            feed_id=self._settings.gtfs_feed_id,
            retention=self._settings.gtfs_dataset_retention,
        )
        result = await service.run()
        logger.info(
            "worker.refresh_feed",
            status=result.status,
            dataset_id=result.dataset_id,
            version=result.version,
        )

    async def _shutdown(self) -> None:
        await self._redis.aclose()
        await self._database.dispose()
        logger.info("worker.shutdown")


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
