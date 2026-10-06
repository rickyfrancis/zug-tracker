"""The train endpoints end to end: real app, real timetable, fixed clock.

Nothing is faked but the clock: positions are computed by the live snapshot
reader from what the importer loaded, so this is the path Swagger exercises.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_clock, get_db_session
from app.core.config import Settings
from app.core.db import Database
from app.main import create_app
from tests.conftest import _client_for
from tests.db.feed import FEED, FEED_ID, StubProvider, service

pytestmark = pytest.mark.db

#: Monday 08:00Z: day-trip is between Berlin (06:05Z) and München (10:00Z).
MONDAY_MORNING = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)


@pytest.fixture
async def client(database: Database) -> AsyncIterator[AsyncClient]:
    await service(database, StubProvider(FEED)).run()

    async def session() -> AsyncIterator[AsyncSession]:
        async with database.session() as db_session:
            yield db_session

    app = create_app(Settings(environment="test", log_level="WARNING", gtfs_feed_id=FEED_ID))
    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_clock] = lambda: lambda: MONDAY_MORNING
    async with _client_for(app) as http_client:
        yield http_client


async def trip_ids(client: AsyncClient, **params: str) -> list[str]:
    response = await client.get("/api/v1/trains", params=params)
    assert response.status_code == 200, response.text
    return [train["trip_id"] for train in response.json()["trains"]]


async def test_running_trains(client: AsyncClient) -> None:
    payload = (await client.get("/api/v1/trains")).json()

    assert payload["timestamp"] == "2026-08-24T08:00:00Z"
    assert payload["snapshot_age_seconds"] == 0
    (train,) = payload["trains"]
    assert (train["trip_id"], train["label"], train["destination"]) == (
        "day-trip",
        "ICE 10",
        "München Hbf",
    )
    segment = train["segment"]
    assert (segment["from_station"]["name"], segment["to_station"]["name"]) == (
        "Berlin Hbf",
        "München Hbf",
    )
    assert (segment["departure_utc"], segment["arrival_utc"]) == (
        "2026-08-24T06:05:00Z",
        "2026-08-24T10:00:00Z",
    )


async def test_filters(client: AsyncClient) -> None:
    assert await trip_ids(client, bbox="12.0,52.0,14.5,53.0") == ["day-trip"]
    assert await trip_ids(client, bbox="9.5,53.3,10.5,53.8") == []
    assert await trip_ids(client, category="EC") == []
    assert await trip_ids(client, category="ice", zoom="6") == ["day-trip"]


async def test_a_running_trains_detail(client: AsyncClient) -> None:
    payload = (await client.get("/api/v1/trains/day-trip")).json()

    assert payload["service_date"] == "2026-08-24"
    assert [stop["station"]["name"] for stop in payload["stops"]] == ["Berlin Hbf", "München Hbf"]
    assert payload["route"]["coordinates"] == [[13.369548, 52.525589], [11.558335, 48.140232]]
    assert payload["position"]["status"] == "moving"


async def test_a_trip_not_running_resolves_to_its_next_instance(client: AsyncClient) -> None:
    """night-trip runs only on the 29th, crossing midnight into the 30th."""
    payload = (await client.get("/api/v1/trains/night-trip")).json()

    assert payload["service_date"] == "2026-08-29"
    assert payload["position"] is None
    assert payload["arrival_utc"] == "2026-08-30T01:54:00Z"


async def test_an_unknown_trip_is_a_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/trains/no-such-trip")).status_code == 404


async def test_stats(client: AsyncClient) -> None:
    payload = (await client.get("/api/v1/stats")).json()

    assert payload["total"] == 1
    assert payload["by_category"] == {"ICE": 1}
    assert payload["by_status"] == {"moving": 1, "stopped": 0}
