"""Periodic jobs and the loop that paces them.

The worker runs work on genuinely different cadences: a heartbeat every few
seconds, a feed refresh once a day, and from Phase 6 a realtime poll every
minute. Running them from one loop would mean either refreshing the feed far
too often or letting a slow import starve the heartbeat, so each job gets its
own loop and they run concurrently.

Two properties matter more than the scheduling itself:

- **A failing job must not stop the worker.** Every run is wrapped, so an
  unreachable origin costs one cycle rather than the process.
- **Shutdown must be prompt.** Jobs wait on the stop event rather than sleeping,
  so a container stopping does not have to wait out a day-long interval.

Scheduling is deliberately in-memory. There is no persisted "last run", because
a job that repeats on restart is cheap by design - the feed refresh sends a
conditional GET - while a fresh deployment that waits a full day before its
first import is not.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Job:
    """One unit of periodic work.

    ``retry_seconds`` applies after a failed run. Left as ``None`` a failure
    simply waits out the normal interval.
    """

    name: str
    run: Callable[[], Awaitable[None]]
    interval_seconds: float
    retry_seconds: float | None = None

    #: Run once immediately on startup rather than waiting out an interval
    #: first. What a fresh deployment needs, and harmless for a cheap job.
    run_at_startup: bool = True

    def delay_after_failure(self) -> float:
        return self.interval_seconds if self.retry_seconds is None else self.retry_seconds


class JobRunner:
    """Runs one :class:`Job` on its own schedule until asked to stop."""

    def __init__(self, job: Job, stop: asyncio.Event) -> None:
        self._job = job
        self._stop = stop
        self._runs = 0
        self._failures = 0

    @property
    def name(self) -> str:
        return self._job.name

    @property
    def runs(self) -> int:
        return self._runs

    @property
    def failures(self) -> int:
        return self._failures

    async def run(self) -> None:
        logger.info(
            "worker.job.started",
            job=self._job.name,
            interval_seconds=self._job.interval_seconds,
        )
        delay = 0.0 if self._job.run_at_startup else self._job.interval_seconds

        while not await self._wait(delay):
            delay = await self._run_once()

        logger.info(
            "worker.job.stopped",
            job=self._job.name,
            runs=self._runs,
            failures=self._failures,
        )

    async def _run_once(self) -> float:
        """Run the job once and report how long to wait before the next run."""
        self._runs += 1
        try:
            await self._job.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failing run must not end the loop
            self._failures += 1
            delay = self._job.delay_after_failure()
            logger.error(
                "worker.job.failed",
                job=self._job.name,
                run=self._runs,
                error=str(exc),
                retry_in_seconds=delay,
            )
            return delay
        return self._job.interval_seconds

    async def _wait(self, seconds: float) -> bool:
        """Wait, returning ``True`` if shutdown was requested instead.

        Waiting on the stop event rather than sleeping is what keeps a job with
        a day-long interval from delaying shutdown by a day.
        """
        if self._stop.is_set():
            return True
        if seconds <= 0:
            return False
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True


async def run_jobs(jobs: list[Job], stop: asyncio.Event) -> list[JobRunner]:
    """Run every job concurrently until shutdown is requested."""
    runners = [JobRunner(job, stop) for job in jobs]
    async with asyncio.TaskGroup() as group:
        for runner in runners:
            group.create_task(runner.run(), name=f"job:{runner.name}")
    return runners
