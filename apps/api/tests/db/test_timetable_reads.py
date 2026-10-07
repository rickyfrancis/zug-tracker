"""Reads the train detail and stats endpoints need, against an imported timetable."""

from datetime import UTC, date, datetime

import pytest

from app.core.db import Database
from app.repositories.timetable_repository import TimetableRepository
from app.services.positions.timetable import TripWindow
from tests.db.feed import FEED, FEED_ID, StubProvider, service

pytestmark = pytest.mark.db


@pytest.fixture
async def imported(database: Database) -> Database:
    await service(database, StubProvider(FEED)).run()
    return database


async def test_one_dated_trip_is_read_with_all_its_calls(imported: Database) -> None:
    async with imported.session() as session:
        trip = await TimetableRepository(session).trip(FEED_ID, "day-trip", date(2026, 8, 25))

    assert trip is not None
    assert (trip.trip_id, trip.service_date, trip.route_name) == (
        "day-trip",
        date(2026, 8, 25),
        "ICE 10",
    )
    assert [call.station.name for call in trip.calls] == ["Berlin Hbf", "München Hbf"]
    assert trip.calls[0].departure_utc == datetime(2026, 8, 25, 6, 5, tzinfo=UTC)


async def test_a_trip_is_absent_on_a_day_it_does_not_run(imported: Database) -> None:
    async with imported.session() as session:
        repository = TimetableRepository(session)
        assert await repository.trip(FEED_ID, "day-trip", date(2026, 8, 26)) is None
        assert await repository.trip(FEED_ID, "no-such-trip", date(2026, 8, 25)) is None


async def test_trip_windows_cover_every_service_date(imported: Database) -> None:
    async with imported.session() as session:
        repository = TimetableRepository(session)
        day = await repository.trip_windows(FEED_ID, "day-trip")
        night = await repository.trip_windows(FEED_ID, "night-trip")

    assert [window.service_date for window in day] == [
        date(2026, 8, 24),
        date(2026, 8, 25),
        date(2026, 8, 27),
        date(2026, 8, 28),
    ]
    assert night == [
        TripWindow(
            service_date=date(2026, 8, 29),
            starts_at_utc=datetime(2026, 8, 29, 21, 5, tzinfo=UTC),
            ends_at_utc=datetime(2026, 8, 30, 1, 54, tzinfo=UTC),
        )
    ]


async def test_categories_are_read_from_the_active_dataset_only(imported: Database) -> None:
    renamed = dict(FEED)
    renamed["routes.txt"] = (
        "route_long_name,route_short_name,agency_id,route_type,route_id\n,EC 7,8,2,77\n,EN,8,2,18\n"
    )
    await service(imported, StubProvider(renamed, etag='"v2"')).run()

    async with imported.session() as session:
        assert await TimetableRepository(session).categories(FEED_ID) == ["EC", "EN"]


async def test_reads_are_empty_before_the_first_import(database: Database) -> None:
    async with database.session() as session:
        repository = TimetableRepository(session)
        assert await repository.categories(FEED_ID) == []
        assert await repository.trip_windows(FEED_ID, "day-trip") == []
