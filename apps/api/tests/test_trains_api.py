"""The train endpoints over HTTP, with the snapshot and timetable faked.

What a database adds is covered in ``tests/db/test_trains_api.py``; these pin
down the contract: shapes, filtering and how bad input is refused.
"""

from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import get_train_service
from app.services.trains.train_service import TrainService
from tests.conftest import _client_for
from tests.trains import (
    BERLIN,
    HAMBURG,
    LEIPZIG,
    MUENCHEN,
    FakeSnapshotReader,
    FakeTimetable,
    at,
    berlin_leipzig_muenchen,
    segment_state,
    train_service,
)

BERLIN_LEIPZIG = segment_state(trip_id="ice-1", category="ICE", progress=0.48936170212765956)
HAMBURG_BERLIN = segment_state(
    trip_id="ic-2", category="IC", from_station=HAMBURG, to_station=BERLIN
)
LEIPZIG_MUENCHEN = segment_state(
    trip_id="ec-3", category="EC", from_station=LEIPZIG, to_station=MUENCHEN
)

#: Roughly Berlin and Brandenburg.
BERLIN_BBOX = "12.0,52.0,14.5,53.0"


@pytest.fixture
def serve(app_factory: Callable[..., FastAPI]) -> Callable[[TrainService], AsyncClient]:
    def _serve(service: TrainService) -> AsyncClient:
        app = app_factory()
        app.dependency_overrides[get_train_service] = lambda: service
        return _client_for(app)

    return _serve


@pytest.fixture
async def fleet(serve: Callable[[TrainService], AsyncClient]) -> AsyncIterator[AsyncClient]:
    snapshot = FakeSnapshotReader(LEIPZIG_MUENCHEN, BERLIN_LEIPZIG, HAMBURG_BERLIN)
    async with serve(train_service(snapshot)) as client:
        yield client


async def trip_ids(client: AsyncClient, **params: str) -> list[str]:
    response = await client.get("/api/v1/trains", params=params)
    assert response.status_code == 200, response.text
    return [train["trip_id"] for train in response.json()["trains"]]


class TestList:
    async def test_the_envelope(self, fleet: AsyncClient) -> None:
        payload = (await fleet.get("/api/v1/trains")).json()

        assert payload["timestamp"] == "2026-08-24T08:00:00Z"
        assert payload["snapshot_age_seconds"] == 0
        assert len(payload["trains"]) == 3

    async def test_a_train(self, fleet: AsyncClient) -> None:
        payload = (await fleet.get("/api/v1/trains")).json()
        train = next(train for train in payload["trains"] if train["trip_id"] == "ice-1")

        assert train == {
            "trip_id": "ice-1",
            "service_date": "2026-08-24",
            "label": "ICE 10",
            "destination": "München Hbf",
            "category": "ICE",
            "operator": "DB Fernverkehr AG",
            "status": "moving",
            "position_source": "scheduled",
            "delay_seconds": None,
            "lat": 51.93529,
            "lon": 12.87577,
            "bearing": 200.0,
            "progress": 0.4894,
            "segment": {
                "from_station": {
                    "station_id": "900003201",
                    "name": "Berlin Hbf",
                    "lat": 52.525589,
                    "lon": 13.369548,
                },
                "to_station": {
                    "station_id": "900008012",
                    "name": "Leipzig Hbf",
                    "lat": 51.345,
                    "lon": 12.382,
                },
                "departure_utc": "2026-08-24T07:30:00Z",
                "arrival_utc": "2026-08-24T08:30:00Z",
                "geometry_ref": None,
            },
        }

    async def test_trains_are_ordered_by_trip(self, fleet: AsyncClient) -> None:
        assert await trip_ids(fleet) == ["ec-3", "ic-2", "ice-1"]

    async def test_the_age_of_an_older_snapshot(
        self, serve: Callable[[TrainService], AsyncClient]
    ) -> None:
        """What Phase 6 will report when the worker falls behind."""
        snapshot = FakeSnapshotReader(BERLIN_LEIPZIG, generated_at=at(7, 58))
        async with serve(train_service(snapshot)) as client:
            payload = (await client.get("/api/v1/trains")).json()

        assert payload["timestamp"] == "2026-08-24T07:58:00Z"
        assert payload["snapshot_age_seconds"] == 120

    async def test_an_empty_fleet(self, serve: Callable[[TrainService], AsyncClient]) -> None:
        async with serve(train_service()) as client:
            payload = (await client.get("/api/v1/trains")).json()

        assert payload["trains"] == []


class TestFilters:
    async def test_category(self, fleet: AsyncClient) -> None:
        assert await trip_ids(fleet, category="ice,EC") == ["ec-3", "ice-1"]

    async def test_an_unknown_category_matches_nothing(self, fleet: AsyncClient) -> None:
        assert await trip_ids(fleet, category="XYZ") == []

    async def test_bbox_keeps_trains_whose_segment_touches_it(self, fleet: AsyncClient) -> None:
        assert await trip_ids(fleet, bbox=BERLIN_BBOX) == ["ic-2", "ice-1"]

    async def test_filters_combine(self, fleet: AsyncClient) -> None:
        assert await trip_ids(fleet, bbox=BERLIN_BBOX, category="IC", zoom="9") == ["ic-2"]

    async def test_zoom_alone_changes_nothing(self, fleet: AsyncClient) -> None:
        assert await trip_ids(fleet, zoom="5.5") == ["ec-3", "ic-2", "ice-1"]


class TestInvalidParameters:
    @pytest.mark.parametrize(
        ("params", "field", "message"),
        [
            ({"bbox": "5,47,15"}, "bbox", "4 comma-separated"),
            ({"bbox": "5,55,15,47"}, "bbox", "south must not exceed north"),
            ({"bbox": "5,47,x,55"}, "bbox", "numbers"),
            ({"zoom": "30"}, "zoom", "less than or equal to 24"),
            ({"zoom": "-1"}, "zoom", "greater than or equal to 0"),
            ({"zoom": "nan"}, "zoom", "finite"),
            ({"category": "ICE,,IC"}, "category", "not a category"),
            ({"catgory": "ICE"}, "catgory", "Extra inputs are not permitted"),
        ],
    )
    async def test_rejected_with_a_422_naming_the_parameter(
        self, fleet: AsyncClient, params: dict[str, str], field: str, message: str
    ) -> None:
        response = await fleet.get("/api/v1/trains", params=params)

        assert response.status_code == 422
        (error,) = response.json()["detail"]
        assert error["loc"] == ["query", field]
        assert message in error["msg"]


class TestDetail:
    @pytest.fixture
    async def client(
        self, serve: Callable[[TrainService], AsyncClient]
    ) -> AsyncIterator[AsyncClient]:
        running = segment_state(trip_id="t1", progress=0.5)
        timetable = FakeTimetable(berlin_leipzig_muenchen(24), berlin_leipzig_muenchen(25))
        async with serve(train_service(FakeSnapshotReader(running), timetable)) as client:
            yield client

    async def test_a_running_train(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/trains/t1")

        assert response.status_code == 200
        payload = response.json()
        assert payload["timestamp"] == "2026-08-24T08:00:00Z"
        assert payload["snapshot_age_seconds"] == 0
        assert {
            key: payload[key]
            for key in ("trip_id", "service_date", "label", "destination", "category", "operator")
        } == {
            "trip_id": "t1",
            "service_date": "2026-08-24",
            "label": "ICE 10",
            "destination": "München Hbf",
            "category": "ICE",
            "operator": "DB Fernverkehr AG",
        }
        assert payload["origin"]["name"] == "Berlin Hbf"
        assert payload["terminus"]["name"] == "München Hbf"
        assert (payload["departure_utc"], payload["arrival_utc"]) == (
            "2026-08-24T07:30:00Z",
            "2026-08-24T11:00:00Z",
        )
        assert payload["position"]["status"] == "moving"
        assert payload["position"]["segment"]["to_station"]["name"] == "Leipzig Hbf"
        assert "trip_id" not in payload["position"]

    async def test_stops_and_route(self, client: AsyncClient) -> None:
        payload = (await client.get("/api/v1/trains/t1")).json()

        assert payload["stops"] == [
            {
                "sequence": 0,
                "station": {
                    "station_id": "900003201",
                    "name": "Berlin Hbf",
                    "lat": 52.525589,
                    "lon": 13.369548,
                },
                "arrival_utc": None,
                "departure_utc": "2026-08-24T07:30:00Z",
            },
            {
                "sequence": 1,
                "station": {
                    "station_id": "900008012",
                    "name": "Leipzig Hbf",
                    "lat": 51.345,
                    "lon": 12.382,
                },
                "arrival_utc": "2026-08-24T08:30:00Z",
                "departure_utc": "2026-08-24T08:35:00Z",
            },
            {
                "sequence": 2,
                "station": {
                    "station_id": "800000261",
                    "name": "München Hbf",
                    "lat": 48.140232,
                    "lon": 11.558335,
                },
                "arrival_utc": "2026-08-24T11:00:00Z",
                "departure_utc": None,
            },
        ]
        assert payload["route"] == {
            "type": "LineString",
            "coordinates": [[13.369548, 52.525589], [12.382, 51.345], [11.558335, 48.140232]],
        }

    async def test_another_days_instance_has_no_position(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/trains/t1", params={"service_date": "2026-08-25"})

        assert response.status_code == 200
        assert response.json()["service_date"] == "2026-08-25"
        assert response.json()["position"] is None

    @pytest.mark.parametrize(
        ("path", "params"),
        [("/api/v1/trains/unknown", {}), ("/api/v1/trains/t1", {"service_date": "2026-08-26"})],
    )
    async def test_an_unknown_trip_is_a_404(
        self, client: AsyncClient, path: str, params: dict[str, str]
    ) -> None:
        response = await client.get(path, params=params)

        assert response.status_code == 404
        assert response.json()["detail"].startswith("no trip")

    async def test_a_malformed_date_is_a_422(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/trains/t1", params={"service_date": "24.08.2026"})

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", "service_date"]
