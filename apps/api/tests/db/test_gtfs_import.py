"""The import as a whole, against a real database.

These cover the failures that only a database can demonstrate: that a re-import
does not orphan rows, that the swap is atomic, and that "one active dataset" is
a schema guarantee rather than a convention.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

from app.core.db import Database
from app.models.gtfs import Dataset, Stop, StopTimeInstance, Trip, TripInstance
from app.services.gtfs.import_service import GTFSImportError, _lock_key
from tests.db.feed import FEED, FEED_ID, StubProvider, service

pytestmark = pytest.mark.db


async def count(database: Database, model: type) -> int:
    async with database.session() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


async def active_dataset(database: Database) -> Dataset | None:
    async with database.session() as session:
        result = await session.execute(select(Dataset).where(Dataset.is_active.is_(True)))
        return result.scalar_one_or_none()


class TestFirstImport:
    async def test_loads_every_table_and_activates(self, database: Database) -> None:
        result = await service(database, StubProvider(FEED)).run()

        assert result.imported
        assert result.counts["agencies"] == 1
        assert result.counts["routes"] == 2
        assert result.counts["stops"] == 4
        assert result.counts["trips"] == 2
        assert result.counts["stop_times"] == 4

        dataset = await active_dataset(database)
        assert dataset is not None
        assert dataset.feed_id == FEED_ID
        assert dataset.timezone == "Europe/Berlin"

    async def test_validity_comes_from_the_calendar_not_feed_info(self, database: Database) -> None:
        await service(database, StubProvider(FEED)).run()

        dataset = await active_dataset(database)
        assert dataset is not None
        assert str(dataset.valid_from) == "2026-08-24"
        assert str(dataset.valid_to) == "2026-08-29"

    async def test_calendar_dates_only_service_produces_instances(self, database: Database) -> None:
        """A service with no calendar.txt row still runs. 60 of these in the real feed."""
        await service(database, StubProvider(FEED)).run()

        async with database.session() as session:
            result = await session.execute(
                select(TripInstance.service_date).where(TripInstance.trip_id == "night-trip")
            )
            assert [str(day) for day in result.scalars()] == ["2026-08-29"]

    async def test_calendar_exception_removes_a_date(self, database: Database) -> None:
        """Mon-Fri minus the Wednesday exception leaves four days."""
        await service(database, StubProvider(FEED)).run()

        async with database.session() as session:
            result = await session.execute(
                select(TripInstance.service_date)
                .where(TripInstance.trip_id == "day-trip")
                .order_by(TripInstance.service_date)
            )
            days = [str(day) for day in result.scalars()]

        assert days == ["2026-08-24", "2026-08-25", "2026-08-27", "2026-08-28"]

    async def test_a_midnight_crossing_call_lands_on_the_next_day(self, database: Database) -> None:
        await service(database, StubProvider(FEED)).run()

        async with database.session() as session:
            result = await session.execute(
                select(StopTimeInstance.arrival_utc).where(
                    StopTimeInstance.trip_id == "night-trip",
                    StopTimeInstance.stop_sequence == 1,
                )
            )
            arrival = result.scalar_one()

        # 27:54 on the 29th is 03:54 local on the 30th, i.e. 01:54Z.
        assert arrival == datetime(2026, 8, 30, 1, 54, tzinfo=UTC)

    async def test_stops_get_a_geography_point(self, database: Database) -> None:
        await service(database, StubProvider(FEED)).run()

        async with database.session() as session:
            result = await session.execute(
                text("SELECT round(ST_Y(point::geometry)::numeric, 4) FROM stop WHERE stop_id=:id"),
                {"id": "900003201"},
            )
            assert float(result.scalar_one()) == pytest.approx(52.5256)

    async def test_stations_get_a_display_name_and_platforms_do_not(
        self, database: Database
    ) -> None:
        await service(database, StubProvider(FEED)).run()

        async with database.session() as session:
            result = await session.execute(select(Stop.stop_id, Stop.display_name))
            names = dict(result.tuples().all())

        assert names == {
            "900003201": "Berlin Hbf",
            "8098160": None,
            "800000261": "München Hbf",
            "8000261": None,
        }


class TestReimport:
    async def test_unchanged_feed_is_a_no_op(self, database: Database) -> None:
        provider = StubProvider(FEED)
        await service(database, provider).run()

        result = await service(database, provider).run()

        assert not result.imported
        assert await count(database, Dataset) == 1

    async def test_force_reimports_identical_content(self, database: Database) -> None:
        provider = StubProvider(FEED)
        first = await service(database, provider).run()

        second = await service(database, provider).run(force=True)

        assert second.imported
        assert second.dataset_id != first.dataset_id

    async def test_changed_trip_ids_do_not_orphan_the_old_ones(self, database: Database) -> None:
        """GTFS ids are not stable across releases; upserting by id would accumulate."""
        await service(database, StubProvider(FEED)).run()

        renamed = dict(FEED)
        renamed["trips.txt"] = "route_id,service_id,trip_id\n77,weekday,RENAMED\n"
        renamed["stop_times.txt"] = (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence,"
            "stop_headsign,pickup_type,drop_off_type\n"
            "RENAMED,08:00:00,08:05:00,8098160,0,München Hbf,,\n"
            "RENAMED,12:00:00,12:00:00,8000261,1,München Hbf,,\n"
        )
        await service(database, StubProvider(renamed, etag='"v2"')).run()

        dataset = await active_dataset(database)
        assert dataset is not None
        async with database.session() as session:
            result = await session.execute(
                select(Trip.trip_id).where(Trip.dataset_id == dataset.id)
            )
            assert list(result.scalars()) == ["RENAMED"]

    async def test_pruning_retains_exactly_one_superseded_dataset(self, database: Database) -> None:
        provider = StubProvider(FEED)
        for _ in range(3):
            await service(database, provider).run(force=True)

        assert await count(database, Dataset) == 2

    async def test_pruning_cascades_to_every_child_row(self, database: Database) -> None:
        provider = StubProvider(FEED)
        await service(database, provider).run()
        instances_per_import = await count(database, TripInstance)

        await service(database, provider).run(force=True)
        await service(database, provider).run(force=True)

        # Two datasets retained, so exactly two imports' worth of rows survive.
        assert await count(database, TripInstance) == instances_per_import * 2

    async def test_retention_of_zero_leaves_only_the_active_dataset(
        self, database: Database
    ) -> None:
        provider = StubProvider(FEED)
        await service(database, provider, retention=0).run()
        await service(database, provider, retention=0).run(force=True)

        assert await count(database, Dataset) == 1


class TestAtomicity:
    async def test_only_one_dataset_can_be_active(self, database: Database) -> None:
        """Enforced by a partial unique index, not by the application."""
        provider = StubProvider(FEED)
        await service(database, provider).run()
        await service(database, provider).run(force=True)

        async with database.session() as session:
            result = await session.execute(
                select(func.count()).select_from(Dataset).where(Dataset.is_active.is_(True))
            )
            assert result.scalar_one() == 1

    async def test_the_database_rejects_a_second_active_dataset(self, database: Database) -> None:
        provider = StubProvider(FEED)
        await service(database, provider).run()
        await service(database, provider).run(force=True)

        with pytest.raises(Exception, match="uq_dataset_single_active"):
            async with database.session() as session:
                await session.execute(text("UPDATE dataset SET is_active = true"))
                await session.commit()

    async def test_a_failed_import_leaves_the_previous_dataset_serving(
        self, database: Database
    ) -> None:
        """Load and activation share one transaction: a failure leaves no trace."""
        provider = StubProvider(FEED)
        await service(database, provider).run()
        good = await active_dataset(database)
        assert good is not None

        broken = dict(FEED)
        broken["agency.txt"] = (
            "agency_id,agency_name,agency_url,agency_timezone,agency_lang\n"
            "8,DB Fernverkehr AG,https://www.bahn.de,Europe/Berlin,de\n"
            "9,SBB,https://www.sbb.ch,Europe/Zurich,de\n"
        )

        with pytest.raises(GTFSImportError, match="timezone"):
            await service(database, StubProvider(broken, etag='"v2"')).run()

        still_active = await active_dataset(database)
        assert still_active is not None
        assert still_active.id == good.id
        assert await count(database, Dataset) == 1


class TestConcurrentImports:
    """The worker refreshes on a schedule; an operator can still run the CLI.

    Both would otherwise load the whole feed and the loser would die on the
    single-active-dataset index, having done all of the work first.
    """

    async def test_an_import_is_skipped_while_another_holds_the_lock(
        self, database: Database
    ) -> None:
        async with database.session() as holder:
            await holder.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(FEED_ID)}
            )

            result = await service(database, StubProvider(FEED)).run()

            assert result.status == "skipped"
            assert await count(database, Dataset) == 0

    async def test_the_lock_is_released_with_the_transaction(self, database: Database) -> None:
        async with database.session() as holder:
            await holder.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(FEED_ID)}
            )
            await holder.rollback()

        result = await service(database, StubProvider(FEED)).run()

        assert result.imported
        assert await count(database, Dataset) == 1

    async def test_a_different_feed_is_not_blocked(self, database: Database) -> None:
        """Locks are per feed, so importing rv_free later cannot queue behind fv_free."""
        async with database.session() as holder:
            await holder.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key("other_feed")}
            )

            result = await service(database, StubProvider(FEED)).run()

            assert result.imported
