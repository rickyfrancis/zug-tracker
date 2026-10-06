"""The position engine against an imported timetable.

The estimator is tested without a database; what needs one is the read path
that feeds it - that the running window, the active dataset and the
platform-to-station resolution all hold in SQL, on data the importer wrote.
"""

from datetime import UTC, date, datetime

import pytest

from app.core.db import Database
from app.services.positions.estimator import SegmentState, TrainStatus
from app.services.positions.position_service import PositionService
from tests.db.feed import FEED, FEED_ID, StubProvider, service

pytestmark = pytest.mark.db

# day-trip runs Berlin 08:05 -> München 12:00 local, Mon-Fri 24-28 Aug 2026 but
# not Wednesday the 26th. In CEST that is 06:05Z -> 10:00Z.
MONDAY_DEPARTURE = datetime(2026, 8, 24, 6, 5, tzinfo=UTC)
MONDAY_ARRIVAL = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


async def positions_at(
    database: Database, now: datetime, feed_id: str = FEED_ID
) -> list[SegmentState]:
    async with database.session() as session:
        return await PositionService(session, feed_id=feed_id).positions_at(now)


@pytest.fixture
async def imported(database: Database) -> Database:
    await service(database, StubProvider(FEED)).run()
    return database


async def test_a_running_train_is_positioned(imported: Database) -> None:
    states = await positions_at(imported, datetime(2026, 8, 24, 8, 0, tzinfo=UTC))

    assert len(states) == 1
    state = states[0]
    assert state.trip_id == "day-trip"
    assert state.status is TrainStatus.MOVING
    assert state.progress == pytest.approx(115 / 235)
    assert (state.departure_utc, state.arrival_utc) == (MONDAY_DEPARTURE, MONDAY_ARRIVAL)
    assert state.display_name == "ICE 10 → München Hbf"
    assert state.operator == "DB Fernverkehr AG"


async def test_platforms_resolve_to_their_parent_station(imported: Database) -> None:
    """stop_times name platform 8098160; the segment runs from station 900003201."""
    (state,) = await positions_at(imported, datetime(2026, 8, 24, 8, 0, tzinfo=UTC))

    assert state.from_station.station_id == "900003201"
    assert state.to_station.station_id == "800000261"
    assert state.from_station.name == "Berlin Hbf"


async def test_the_running_window_is_inclusive_at_both_ends(imported: Database) -> None:
    second = datetime(2026, 8, 24, 6, 4, 59, tzinfo=UTC)

    assert await positions_at(imported, second) == []
    assert len(await positions_at(imported, MONDAY_DEPARTURE)) == 1
    assert len(await positions_at(imported, MONDAY_ARRIVAL)) == 1


async def test_no_train_runs_on_a_date_the_calendar_removes(imported: Database) -> None:
    assert await positions_at(imported, datetime(2026, 8, 26, 8, 0, tzinfo=UTC)) == []


async def test_a_midnight_crossing_train_runs_into_the_next_day(imported: Database) -> None:
    """night-trip: 23:05 on the 29th to 27:54, i.e. 03:54 local on the 30th."""
    (state,) = await positions_at(imported, datetime(2026, 8, 30, 0, 30, tzinfo=UTC))

    assert state.trip_id == "night-trip"
    assert state.service_date == date(2026, 8, 29)
    assert state.display_name == "ICE → München Hbf"


async def test_only_the_active_dataset_is_read(imported: Database) -> None:
    """The superseded dataset is retained, so its trips are still in the tables."""
    renamed = dict(FEED)
    renamed["trips.txt"] = "route_id,service_id,trip_id\n77,weekday,RENAMED\n"
    renamed["stop_times.txt"] = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,"
        "stop_headsign,pickup_type,drop_off_type\n"
        "RENAMED,08:00:00,08:05:00,8098160,0,München Hbf,,\n"
        "RENAMED,12:00:00,12:00:00,8000261,1,München Hbf,,\n"
    )
    await service(imported, StubProvider(renamed, etag='"v2"')).run()

    states = await positions_at(imported, datetime(2026, 8, 24, 8, 0, tzinfo=UTC))

    assert [state.trip_id for state in states] == ["RENAMED"]


async def test_another_feed_is_not_read(imported: Database) -> None:
    assert await positions_at(imported, datetime(2026, 8, 24, 8, 0, tzinfo=UTC), "rv_free") == []


async def test_nothing_is_running_before_the_first_import(database: Database) -> None:
    """A freshly deployed stack: an empty map, not an error."""
    assert await positions_at(database, datetime(2026, 8, 24, 8, 0, tzinfo=UTC)) == []
