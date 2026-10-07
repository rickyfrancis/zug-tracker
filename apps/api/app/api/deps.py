"""Shared FastAPI dependencies.

Everything the request handlers need is assembled here, so handlers themselves
stay free of wiring code.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import Database
from app.repositories.timetable_repository import TimetableRepository
from app.services.health_service import HealthService
from app.services.positions.position_service import PositionService
from app.services.trains.snapshot import Clock, LiveSnapshotReader, SnapshotReader, utc_now
from app.services.trains.train_service import TrainService


def get_app_settings(request: Request) -> Settings:
    """Return the settings the app was created with.

    Reading them off the app rather than the module-level cache keeps a test
    app (or a second app in the same process) from picking up the wrong config.
    """
    settings: Settings = request.app.state.settings
    return settings


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.session() as session:
        yield session


async def get_redis_client(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis_client)]


def get_health_service(
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> HealthService:
    return HealthService(
        session,
        redis,
        heartbeat_key=settings.worker_heartbeat_key,
        heartbeat_ttl_seconds=settings.heartbeat_ttl_seconds,
        feed_id=settings.gtfs_feed_id,
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]


def get_clock() -> Clock:
    return utc_now


ClockDep = Annotated[Clock, Depends(get_clock)]


def get_snapshot_reader(
    session: SessionDep, settings: SettingsDep, clock: ClockDep
) -> SnapshotReader:
    """Where positions come from: computed per request until Phase 6.

    The worker then writes a snapshot to Redis each tick and this returns a
    reader for it - the one line that changes, since every endpoint reads
    through :class:`SnapshotReader`.
    """
    return LiveSnapshotReader(PositionService(session, feed_id=settings.gtfs_feed_id), clock)


SnapshotReaderDep = Annotated[SnapshotReader, Depends(get_snapshot_reader)]


def get_train_service(
    session: SessionDep,
    settings: SettingsDep,
    snapshots: SnapshotReaderDep,
    clock: ClockDep,
) -> TrainService:
    return TrainService(
        snapshots,
        TimetableRepository(session),
        feed_id=settings.gtfs_feed_id,
        clock=clock,
    )


TrainServiceDep = Annotated[TrainService, Depends(get_train_service)]
