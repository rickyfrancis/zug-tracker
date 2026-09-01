"""Worker job scheduling.

The properties under test are the ones that decide whether a deployed worker
keeps the timetable fresh: that a job runs at all without waiting out its first
interval, that a failure costs one cycle rather than the process, and that a
day-long interval does not hold up shutdown.

Intervals here are milliseconds. The loop waits on the stop event rather than
sleeping, so the tests drive it by setting that event instead of by waiting.
"""

import asyncio

import pytest

from app.core.config import Settings
from app.worker.jobs import Job, JobRunner, run_jobs
from app.worker.main import Worker


class Recorder:
    """A job body that counts its runs and can be made to fail."""

    def __init__(self, *, fail_times: int = 0, stop_after: int | None = None) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.stop_after = stop_after
        self.finished = asyncio.Event()

    async def __call__(self) -> None:
        self.calls += 1
        if self.stop_after is not None and self.calls >= self.stop_after:
            self.finished.set()
        if self.calls <= self.fail_times:
            raise RuntimeError("origin unreachable")


async def run_until(runner: JobRunner, recorder: Recorder, stop: asyncio.Event) -> None:
    """Run the loop until the job has been called enough times, then stop it."""
    task = asyncio.create_task(runner.run())
    try:
        async with asyncio.timeout(5):
            await recorder.finished.wait()
    finally:
        stop.set()
        await task


class TestScheduling:
    async def test_runs_immediately_at_startup(self) -> None:
        """A fresh deployment must not wait out an interval before importing."""
        recorder = Recorder(stop_after=1)
        stop = asyncio.Event()
        # An interval long enough that a second run cannot be what we observed.
        job = Job(name="refresh", run=recorder, interval_seconds=3600)

        await run_until(JobRunner(job, stop), recorder, stop)

        assert recorder.calls == 1

    async def test_repeats_on_its_interval(self) -> None:
        recorder = Recorder(stop_after=3)
        stop = asyncio.Event()
        job = Job(name="refresh", run=recorder, interval_seconds=0.001)

        await run_until(JobRunner(job, stop), recorder, stop)

        assert recorder.calls >= 3

    async def test_can_defer_the_first_run(self) -> None:
        recorder = Recorder()
        stop = asyncio.Event()
        job = Job(name="refresh", run=recorder, interval_seconds=3600, run_at_startup=False)

        task = asyncio.create_task(JobRunner(job, stop).run())
        await asyncio.sleep(0)
        stop.set()
        await task

        assert recorder.calls == 0

    async def test_does_not_run_when_already_stopped(self) -> None:
        recorder = Recorder()
        stop = asyncio.Event()
        stop.set()

        await JobRunner(Job(name="refresh", run=recorder, interval_seconds=1), stop).run()

        assert recorder.calls == 0


class TestFailureHandling:
    async def test_a_failing_run_does_not_end_the_loop(self) -> None:
        """An unreachable origin must cost one cycle, not the worker."""
        recorder = Recorder(fail_times=2, stop_after=3)
        stop = asyncio.Event()
        job = Job(name="refresh", run=recorder, interval_seconds=0.001, retry_seconds=0.001)
        runner = JobRunner(job, stop)

        await run_until(runner, recorder, stop)

        assert recorder.calls >= 3
        assert runner.failures == 2

    async def test_failure_waits_the_retry_interval_not_the_full_one(self) -> None:
        """A day is too long to wait when the feed is what expires."""
        job = Job(name="refresh", run=Recorder(), interval_seconds=86400, retry_seconds=900)

        assert job.delay_after_failure() == 900

    async def test_failure_falls_back_to_the_interval(self) -> None:
        job = Job(name="heartbeat", run=Recorder(), interval_seconds=10)

        assert job.delay_after_failure() == 10

    async def test_cancellation_is_not_swallowed(self) -> None:
        """Cancellation is shutdown, not a job failure to be retried."""

        async def hang() -> None:
            await asyncio.sleep(3600)

        stop = asyncio.Event()
        runner = JobRunner(Job(name="slow", run=hang, interval_seconds=1), stop)
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert runner.failures == 0


class TestRunJobs:
    async def test_runs_every_job_and_stops_them_together(self) -> None:
        first, second = Recorder(stop_after=1), Recorder(stop_after=1)
        stop = asyncio.Event()
        jobs = [
            Job(name="a", run=first, interval_seconds=3600),
            Job(name="b", run=second, interval_seconds=3600),
        ]

        task = asyncio.create_task(run_jobs(jobs, stop))
        async with asyncio.timeout(5):
            await first.finished.wait()
            await second.finished.wait()
        stop.set()
        runners = await task

        assert [runner.name for runner in runners] == ["a", "b"]
        assert first.calls == 1
        assert second.calls == 1

    async def test_a_long_interval_does_not_delay_shutdown(self) -> None:
        """A day-long job must not make the container wait a day to stop."""
        recorder = Recorder(stop_after=1)
        stop = asyncio.Event()
        jobs = [Job(name="daily", run=recorder, interval_seconds=86400)]

        task = asyncio.create_task(run_jobs(jobs, stop))
        async with asyncio.timeout(5):
            await recorder.finished.wait()
        stop.set()

        async with asyncio.timeout(1):
            await task


class TestWorkerJobs:
    """Which jobs the worker registers, given its settings."""

    def test_registers_the_feed_refresh_when_a_url_is_configured(self) -> None:
        worker = Worker(
            Settings(
                environment="test",
                gtfs_static_url="https://example.invalid/latest.zip",
                gtfs_refresh_interval_seconds=86400,
                gtfs_refresh_retry_seconds=900,
            )
        )

        jobs = {job.name: job for job in worker._build_jobs()}

        assert set(jobs) == {"heartbeat", "refresh-feed"}
        assert jobs["refresh-feed"].interval_seconds == 86400
        assert jobs["refresh-feed"].delay_after_failure() == 900

    def test_omits_the_feed_refresh_without_a_url(self) -> None:
        """Better to run without the job than to register one that only fails."""
        worker = Worker(Settings(environment="test", gtfs_static_url=""))

        assert [job.name for job in worker._build_jobs()] == ["heartbeat"]

    def test_the_heartbeat_keeps_the_worker_interval(self) -> None:
        worker = Worker(Settings(environment="test", worker_interval_seconds=30))

        heartbeat = next(job for job in worker._build_jobs() if job.name == "heartbeat")
        assert heartbeat.interval_seconds == 30
