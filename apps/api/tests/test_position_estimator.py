"""Estimating a train's position from its timetable.

Every instant is passed in, never read from the clock, so each case pins an
exact moment in the trip. Times are UTC throughout: by the time a trip reaches
the estimator, service-day offsets and DST have been resolved (ADR-0003).
"""

from datetime import UTC, date, datetime

import pytest

from app.services.positions.estimator import (
    PositionSource,
    SegmentState,
    TrainPositionEstimator,
    TrainStatus,
    merge_station_calls,
)
from app.services.positions.geometry import Corridor, Point, Polyline
from app.services.positions.timetable import Call, ScheduledTrip, Station

BERLIN = Station("900003201", "Berlin Hbf", 52.525589, 13.369548)
LEIPZIG = Station("900008012", "Leipzig Hbf", 51.345, 12.382)
MUENCHEN = Station("800000261", "München Hbf", 48.140232, 11.558335)


def at(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def call(
    sequence: int,
    station: Station,
    arrival: datetime,
    departure: datetime | None = None,
    headsign: str | None = "München Hbf",
) -> Call:
    return Call(
        stop_sequence=sequence,
        station=station,
        arrival_utc=arrival,
        departure_utc=departure or arrival,
        headsign=headsign,
    )


def trip(*calls: Call, route_name: str = "ICE 10") -> ScheduledTrip:
    return ScheduledTrip(
        trip_id="t1",
        service_date=date(2026, 8, 24),
        route_name=route_name,
        category="ICE",
        operator="DB Fernverkehr AG",
        calls=calls,
    )


#: Berlin 06:00 -> Leipzig 07:00, dwells 5 min -> München 10:05.
BERLIN_LEIPZIG_MUENCHEN = trip(
    call(0, BERLIN, at(5, 55), at(6, 0)),
    call(1, LEIPZIG, at(7, 0), at(7, 5)),
    call(2, MUENCHEN, at(10, 5)),
)


def estimate(scheduled: ScheduledTrip, now: datetime) -> SegmentState | None:
    return TrainPositionEstimator().estimate(scheduled, now)


def running(scheduled: ScheduledTrip, now: datetime) -> SegmentState:
    state = estimate(scheduled, now)
    assert state is not None, f"expected the train to be running at {now}"
    return state


class TestRunningWindow:
    def test_not_running_before_the_first_departure(self) -> None:
        """Boarding at the origin is not running: the map shows trains in motion."""
        assert estimate(BERLIN_LEIPZIG_MUENCHEN, at(5, 59)) is None

    def test_running_from_the_instant_of_first_departure(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(6, 0))

        assert state.status is TrainStatus.MOVING
        assert state.progress == 0.0
        assert (state.lat, state.lon) == (BERLIN.lat, BERLIN.lon)

    def test_arrived_at_the_instant_of_final_arrival(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(10, 5))

        assert state.status is TrainStatus.STOPPED
        assert state.progress == 1.0
        assert (state.from_station, state.to_station) == (LEIPZIG, MUENCHEN)
        assert (state.lat, state.lon) == pytest.approx((MUENCHEN.lat, MUENCHEN.lon))

    def test_not_running_after_the_final_arrival(self) -> None:
        assert estimate(BERLIN_LEIPZIG_MUENCHEN, at(10, 6)) is None


class TestBetweenStations:
    def test_progress_is_the_fraction_of_the_segment_elapsed(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(6, 15))

        assert state.status is TrainStatus.MOVING
        assert state.progress == pytest.approx(0.25)
        assert (state.from_station, state.to_station) == (BERLIN, LEIPZIG)

    def test_segment_times_are_departure_and_next_arrival(self) -> None:
        """What the browser needs to extrapolate to any later instant itself."""
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(6, 15))

        assert (state.departure_utc, state.arrival_utc) == (at(6, 0), at(7, 0))

    def test_position_and_bearing_come_from_the_segment_geometry(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(6, 30))

        assert state.lat == pytest.approx((BERLIN.lat + LEIPZIG.lat) / 2)
        assert state.lon == pytest.approx((BERLIN.lon + LEIPZIG.lon) / 2)
        # Berlin to Leipzig runs south-south-west.
        assert state.bearing == pytest.approx(208, abs=1)
        assert state.geometry_ref is None

    def test_a_trip_crossing_midnight_needs_no_special_case(self) -> None:
        """16% of the feed. Once times are absolute UTC, midnight is just an instant."""
        night = trip(call(0, BERLIN, at(23, 0), at(23, 0)), call(1, MUENCHEN, at(1, 0, day=25)))

        state = running(night, at(0, 0, day=25))

        assert state.progress == pytest.approx(0.5)


class TestAtAStation:
    def test_a_dwelling_train_is_stopped_at_the_station(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(7, 2))

        assert state.status is TrainStatus.STOPPED
        assert (state.lat, state.lon) == (LEIPZIG.lat, LEIPZIG.lon)
        assert state.progress == 0.0

    def test_a_dwelling_train_is_given_the_segment_it_is_about_to_start(self) -> None:
        """Its departure is in the future, so the browser starts it moving on time."""
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(7, 2))

        assert (state.from_station, state.to_station) == (LEIPZIG, MUENCHEN)
        assert state.departure_utc == at(7, 5)
        assert state.bearing is not None

    def test_arriving_counts_as_reaching_the_station(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(7, 0))

        assert state.status is TrainStatus.STOPPED
        assert state.from_station == LEIPZIG

    def test_departing_starts_the_next_segment(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(7, 5))

        assert state.status is TrainStatus.MOVING
        assert state.from_station == LEIPZIG
        assert state.progress == 0.0

    def test_a_zero_minute_hop_does_not_divide_by_zero(self) -> None:
        """Timetables round to the minute, so a short hop can depart and arrive together."""
        hop = trip(
            call(0, BERLIN, at(6, 0), at(6, 0)),
            call(1, LEIPZIG, at(6, 0), at(6, 0)),
            call(2, MUENCHEN, at(7, 0)),
        )

        state = running(hop, at(6, 0))

        assert state.from_station == LEIPZIG
        assert state.progress == 0.0


class TestIdentity:
    def test_label_is_the_line_and_destination_the_headsign(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(6, 30))

        assert state.label == "ICE 10"
        assert state.destination == "München Hbf"
        assert state.display_name == "ICE 10 → München Hbf"
        assert state.operator == "DB Fernverkehr AG"
        assert state.category == "ICE"

    def test_a_route_without_a_line_number_is_labelled_by_category(self) -> None:
        """953 trips (17%) sit on routes named just "ICE"."""
        bare = trip(*BERLIN_LEIPZIG_MUENCHEN.calls, route_name="ICE")

        assert running(bare, at(6, 30)).display_name == "ICE → München Hbf"

    def test_the_destination_is_read_where_the_train_is(self) -> None:
        """A headsign can change along a trip, e.g. where a train splits."""
        changing = trip(
            call(0, BERLIN, at(6, 0), at(6, 0), headsign="Leipzig Hbf"),
            call(1, LEIPZIG, at(7, 0), at(7, 5), headsign="München Hbf"),
            call(2, MUENCHEN, at(10, 5)),
        )

        assert running(changing, at(6, 30)).destination == "Leipzig Hbf"
        assert running(changing, at(8, 0)).destination == "München Hbf"

    def test_a_missing_headsign_falls_back_to_the_terminus(self) -> None:
        unsigned = trip(
            call(0, BERLIN, at(6, 0), at(6, 0), headsign=None),
            call(1, MUENCHEN, at(10, 0), headsign=None),
        )

        assert running(unsigned, at(8, 0)).destination == "München Hbf"

    def test_every_position_is_schedule_estimated_until_realtime_arrives(self) -> None:
        state = running(BERLIN_LEIPZIG_MUENCHEN, at(6, 30))

        assert state.position_source is PositionSource.SCHEDULED
        assert state.delay_seconds is None


class TestCalls:
    def test_calls_are_taken_in_stop_sequence_order(self) -> None:
        shuffled = trip(*reversed(BERLIN_LEIPZIG_MUENCHEN.calls))

        assert running(shuffled, at(6, 15)) == running(BERLIN_LEIPZIG_MUENCHEN, at(6, 15))

    def test_consecutive_calls_at_one_station_fold_into_one_dwell(self) -> None:
        """Two platforms of one station resolve to the same station: no zero-length segment."""
        merged = merge_station_calls(
            [
                call(0, BERLIN, at(6, 0), at(6, 0)),
                call(1, LEIPZIG, at(7, 0), at(7, 2), headsign="Leipzig Hbf"),
                call(2, LEIPZIG, at(7, 3), at(7, 5), headsign="München Hbf"),
                call(3, MUENCHEN, at(10, 5)),
            ]
        )

        assert [c.station for c in merged] == [BERLIN, LEIPZIG, MUENCHEN]
        leipzig = merged[1]
        assert (leipzig.arrival_utc, leipzig.departure_utc) == (at(7, 0), at(7, 5))
        assert leipzig.headsign == "München Hbf"

    def test_a_trip_that_never_leaves_its_station_is_not_running(self) -> None:
        stationary = trip(call(0, BERLIN, at(6, 0), at(6, 0)), call(1, BERLIN, at(6, 10)))

        assert estimate(stationary, at(6, 5)) is None


class TestCorridors:
    def test_a_curated_corridor_replaces_the_straight_line(self) -> None:
        detour = Point(lat=BERLIN.lat, lon=LEIPZIG.lon)

        def corridors(origin: Station, destination: Station) -> Corridor:
            return Corridor(
                Polyline((origin.point, detour, destination.point)),
                ref="berlin-leipzig",
            )

        estimator = TrainPositionEstimator(corridors)
        state = estimator.estimate(BERLIN_LEIPZIG_MUENCHEN, at(6, 0))

        assert state is not None
        assert state.geometry_ref == "berlin-leipzig"
        # First leg of the detour runs due west.
        assert state.bearing == pytest.approx(270.0)
