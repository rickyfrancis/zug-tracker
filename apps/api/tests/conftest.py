"""Test fixtures.

The suite runs without Docker: PostgreSQL and Redis are replaced by fakes
through FastAPI's dependency overrides.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session, get_redis_client
from app.core.config import Settings
from app.main import create_app


class FakeSession:
    """Stands in for an AsyncSession.

    ``failing`` simulates a refused connection, ``hangs`` a dependency that
    accepts the connection but never answers.
    """

    def __init__(self, *, failing: bool = False, hangs: bool = False) -> None:
        self.failing = failing
        self.hangs = hangs

    async def execute(self, *_args: object, **_kwargs: object) -> None:
        if self.hangs:
            await asyncio.sleep(3600)
        if self.failing:
            raise ConnectionError("connection refused")


class FakeRedis:
    """Minimal async Redis stub covering ping/get."""

    def __init__(self, *, failing: bool = False, heartbeat: str | None = None) -> None:
        self.failing = failing
        self.heartbeat = heartbeat

    async def ping(self) -> bool:
        if self.failing:
            raise ConnectionError("connection refused")
        return True

    async def get(self, _key: str) -> str | None:
        if self.failing:
            raise ConnectionError("connection refused")
        return self.heartbeat


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", log_level="WARNING")


@pytest.fixture
def app_factory(settings: Settings) -> Callable[..., FastAPI]:
    def _build(session: object | None = None, redis: object | None = None) -> FastAPI:
        app = create_app(settings)
        app.dependency_overrides[get_db_session] = lambda: session or FakeSession()
        app.dependency_overrides[get_redis_client] = lambda: redis or FakeRedis()
        return app

    return _build


@pytest.fixture
async def client(app_factory: Callable[..., FastAPI]) -> AsyncIterator[AsyncClient]:
    async with _client_for(app_factory()) as http_client:
        yield http_client


def _client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
