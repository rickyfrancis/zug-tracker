"""Health endpoint behaviour."""

import asyncio
from collections.abc import Callable

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import FakeRedis, FakeSession, _client_for


def _dependency(payload: dict, name: str) -> dict:
    return next(item for item in payload["dependencies"] if item["name"] == name)


async def test_health_reports_ok_when_dependencies_are_reachable(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["environment"] == "test"
    assert _dependency(payload, "postgres")["status"] == "ok"
    assert _dependency(payload, "redis")["status"] == "ok"


async def test_health_returns_503_when_postgres_is_down(
    app_factory: Callable[..., FastAPI],
) -> None:
    app = app_factory(session=FakeSession(failing=True))

    async with _client_for(app) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert _dependency(payload, "postgres")["status"] == "error"


async def test_health_returns_503_when_redis_is_down(app_factory: Callable[..., FastAPI]) -> None:
    app = app_factory(redis=FakeRedis(failing=True))

    async with _client_for(app) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 503
    assert _dependency(response.json(), "redis")["status"] == "error"


async def test_missing_worker_heartbeat_is_reported_but_not_fatal(
    app_factory: Callable[..., FastAPI],
) -> None:
    """A quiet worker degrades observability, not the API itself."""
    app = app_factory(redis=FakeRedis(heartbeat=None))

    async with _client_for(app) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert _dependency(response.json(), "worker")["status"] == "unknown"


async def test_worker_heartbeat_is_reported_when_present(
    app_factory: Callable[..., FastAPI],
) -> None:
    app = app_factory(redis=FakeRedis(heartbeat="2026-08-27T12:00:00+00:00"))

    async with _client_for(app) as client:
        response = await client.get("/api/v1/health")

    worker = _dependency(response.json(), "worker")
    assert worker["status"] == "ok"
    assert "2026-08-27T12:00:00+00:00" in worker["detail"]


async def test_hanging_dependency_times_out_instead_of_blocking(
    app_factory: Callable[..., FastAPI],
) -> None:
    """A dependency that never answers must fail the check, not the request."""
    app = app_factory(session=FakeSession(hangs=True))

    async with _client_for(app) as client:
        response = await asyncio.wait_for(client.get("/api/v1/health"), timeout=10)

    assert response.status_code == 503
    postgres = _dependency(response.json(), "postgres")
    assert postgres["status"] == "error"
    assert "timed out" in postgres["detail"]
