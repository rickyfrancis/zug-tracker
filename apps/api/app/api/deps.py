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
from app.services.health_service import HealthService


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
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
