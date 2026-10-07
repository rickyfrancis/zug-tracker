"""A trip's route polyline, built from its corridors."""

from datetime import UTC, datetime

import pytest

from app.services.positions.geometry import Corridor, Point, Polyline
from app.services.positions.route import trip_route
from app.services.positions.timetable import Call, Station

BERLIN = Station("900003201", "Berlin Hbf", 52.525589, 13.369548)
LEIPZIG = Station("900008012", "Leipzig Hbf", 51.345, 12.382)
MUENCHEN = Station("800000261", "München Hbf", 48.140232, 11.558335)

NOON = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def call(sequence: int, station: Station) -> Call:
    return Call(sequence, station, NOON, NOON, headsign="München Hbf")


def test_straight_legs_join_the_stations_in_stop_order() -> None:
    route = trip_route([call(2, MUENCHEN), call(0, BERLIN), call(1, LEIPZIG)])

    assert route.points == (BERLIN.point, LEIPZIG.point, MUENCHEN.point)


def test_a_platform_change_does_not_repeat_the_station() -> None:
    route = trip_route([call(0, BERLIN), call(1, LEIPZIG), call(2, LEIPZIG), call(3, MUENCHEN)])

    assert route.points == (BERLIN.point, LEIPZIG.point, MUENCHEN.point)


def test_corridor_vertices_are_kept_and_shared_ends_are_not_repeated() -> None:
    bend = Point(51.9, 12.6)

    def corridors(origin: Station, destination: Station) -> Corridor:
        if origin == BERLIN:
            return Corridor(Polyline((origin.point, bend, destination.point)), ref="berlin-leipzig")
        return Corridor(Polyline((origin.point, destination.point)))

    route = trip_route([call(0, BERLIN), call(1, LEIPZIG), call(2, MUENCHEN)], corridors)

    assert route.points == (BERLIN.point, bend, LEIPZIG.point, MUENCHEN.point)


def test_a_single_station_is_a_single_point() -> None:
    assert trip_route([call(0, BERLIN)]).points == (BERLIN.point,)


def test_no_calls_is_an_error() -> None:
    with pytest.raises(ValueError, match="no route"):
        trip_route([])
