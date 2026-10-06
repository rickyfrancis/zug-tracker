"""The train service: snapshot age, instance choice, detail and stats."""

from datetime import date

import pytest

from app.services.positions.estimator import PositionSource, TrainStatus
from app.services.positions.timetable import TripWindow
from app.services.trains.snapshot import PositionSnapshot
from app.services.trains.train_service import choose_instance
from tests.trains import (
    BERLIN,
    LEIPZIG,
    MUENCHEN,
    NOW,
    FakeSnapshotReader,
    FakeTimetable,
    at,
    berlin_leipzig_muenchen,
    segment_state,
    train_service,
)


class TestSnapshotAge:
    def test_whole_seconds_rounded_down(self) -> None:
        snapshot = PositionSnapshot(generated_at=at(7, 59), trains=())

        assert snapshot.age_seconds(at(8, 0).replace(microsecond=999_000)) == 60

    def test_a_snapshot_from_the_future_is_fresh(self) -> None:
        """The worker's clock may run a little ahead of the API's."""
        assert PositionSnapshot(generated_at=at(8, 1), trains=()).age_seconds(NOW) == 0


def window(day: int, start: tuple[int, int], end: tuple[int, int, int]) -> TripWindow:
    return TripWindow(date(2026, 8, day), at(*start, day=day), at(end[0], end[1], day=end[2]))


#: An overnight trip, 21:00 to 03:00, on three consecutive days.
NIGHTS = [
    window(23, (21, 0), (3, 0, 24)),
    window(24, (21, 0), (3, 0, 25)),
    window(25, (21, 0), (3, 0, 26)),
]


class TestChooseInstance:
    def test_the_running_instance(self) -> None:
        assert choose_instance(NIGHTS, at(1, 0, day=25)) == NIGHTS[1]

    def test_otherwise_the_most_recent_to_have_started(self) -> None:
        """At noon on the 24th, last night's train has arrived and tonight's not left."""
        assert choose_instance(NIGHTS, at(12, 0, day=24)) == NIGHTS[0]

    def test_otherwise_the_next_to_start(self) -> None:
        assert choose_instance(NIGHTS, at(12, 0, day=20)) == NIGHTS[0]

    def test_nothing_when_there_are_no_instances(self) -> None:
        assert choose_instance([], NOW) is None


class TestDetail:
    async def test_a_running_trip_carries_its_position(self) -> None:
        running = segment_state(trip_id="t1", from_station=BERLIN, to_station=LEIPZIG)
        service = train_service(
            FakeSnapshotReader(running), FakeTimetable(berlin_leipzig_muenchen())
        )

        detail = await service.detail("t1")

        assert detail is not None
        assert detail.position == running
        assert detail.trip.service_date == date(2026, 8, 24)

    async def test_stops_fold_platform_changes_and_drop_the_ends_missing_times(self) -> None:
        service = train_service(timetable=FakeTimetable(berlin_leipzig_muenchen()))

        detail = await service.detail("t1", date(2026, 8, 24))

        assert detail is not None
        assert [
            (stop.sequence, stop.station, stop.arrival_utc, stop.departure_utc)
            for stop in detail.stops
        ] == [
            (0, BERLIN, None, at(7, 30)),
            (1, LEIPZIG, at(8, 30), at(8, 35)),
            (2, MUENCHEN, at(11, 0), None),
        ]
        assert (detail.origin, detail.terminus) == (BERLIN, MUENCHEN)
        assert (detail.departure_utc, detail.arrival_utc) == (at(7, 30), at(11, 0))
        assert detail.route.points == (BERLIN.point, LEIPZIG.point, MUENCHEN.point)

    async def test_a_trip_not_running_has_no_position(self) -> None:
        """Running today, but asked about tomorrow's instance."""
        running = segment_state(trip_id="t1")
        timetable = FakeTimetable(berlin_leipzig_muenchen(24), berlin_leipzig_muenchen(25))
        service = train_service(FakeSnapshotReader(running), timetable)

        detail = await service.detail("t1", date(2026, 8, 25))

        assert detail is not None
        assert detail.position is None
        assert detail.destination == "München Hbf"

    async def test_without_a_date_and_not_running_the_instance_is_chosen(self) -> None:
        timetable = FakeTimetable(berlin_leipzig_muenchen(24), berlin_leipzig_muenchen(25))
        """At noon today's train has arrived and tomorrow's has not left."""
        snapshot = FakeSnapshotReader(generated_at=at(12, 0, day=24))
        service = train_service(snapshot, timetable)

        detail = await service.detail("t1")

        assert detail is not None
        assert detail.trip.service_date == date(2026, 8, 24)
        assert detail.position is None

    @pytest.mark.parametrize(
        ("trip_id", "service_date"),
        [("unknown", None), ("unknown", date(2026, 8, 24)), ("t1", date(2026, 8, 26))],
    )
    async def test_an_unknown_trip_or_date_is_none(
        self, trip_id: str, service_date: date | None
    ) -> None:
        service = train_service(timetable=FakeTimetable(berlin_leipzig_muenchen()))

        assert await service.detail(trip_id, service_date) is None


class TestStats:
    async def test_counts_with_every_key_present(self) -> None:
        snapshot = FakeSnapshotReader(
            segment_state(trip_id="a", category="ICE"),
            segment_state(trip_id="b", category="ICE", status=TrainStatus.STOPPED),
            segment_state(trip_id="c", category="IC"),
        )
        timetable = FakeTimetable(categories=["EC", "EN", "IC", "ICE"])

        stats = await train_service(snapshot, timetable).stats()

        assert stats.total == 3
        assert stats.by_category == {"EC": 0, "EN": 0, "IC": 1, "ICE": 2}
        assert stats.by_status == {TrainStatus.MOVING: 2, TrainStatus.STOPPED: 1}
        assert stats.by_position_source == {PositionSource.REALTIME: 0, PositionSource.SCHEDULED: 3}

    async def test_a_running_category_missing_from_the_timetable_is_still_counted(self) -> None:
        """The snapshot and the category list are two reads; an import can land between them."""
        snapshot = FakeSnapshotReader(segment_state(category="RJ"))

        stats = await train_service(snapshot, FakeTimetable(categories=["ICE"])).stats()

        assert stats.by_category == {"ICE": 0, "RJ": 1}

    async def test_an_empty_fleet(self) -> None:
        stats = await train_service(timetable=FakeTimetable(categories=[])).stats()

        assert (stats.total, stats.by_category) == (0, {})
        assert stats.by_status == {TrainStatus.MOVING: 0, TrainStatus.STOPPED: 0}
