"""Placing a train along a segment by distance."""

import pytest

from app.services.positions.geometry import (
    Point,
    Polyline,
    bearing_deg,
    distance_m,
    straight_line,
)

BERLIN = Point(lat=52.525589, lon=13.369548)
MUENCHEN = Point(lat=48.140232, lon=11.558335)

# Along the equator a degree of longitude is the same length everywhere, so
# fractions of distance are fractions of degrees.
ORIGIN = Point(lat=0.0, lon=0.0)
ONE_EAST = Point(lat=0.0, lon=1.0)
THREE_EAST = Point(lat=0.0, lon=3.0)
ONE_NORTH = Point(lat=1.0, lon=0.0)
ONE_NORTH_ONE_EAST = Point(lat=1.0, lon=1.0)


def test_distance_matches_the_known_berlin_to_munich_crow_flight() -> None:
    assert distance_m(BERLIN, MUENCHEN) == pytest.approx(504_000, rel=0.01)


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        (Point(lat=1.0, lon=0.0), 0.0),
        (Point(lat=0.0, lon=1.0), 90.0),
        (Point(lat=-1.0, lon=0.0), 180.0),
        (Point(lat=0.0, lon=-1.0), 270.0),
    ],
)
def test_bearing_is_clockwise_from_north(destination: Point, expected: float) -> None:
    assert bearing_deg(ORIGIN, destination) == pytest.approx(expected)


def test_bearing_shortens_longitude_at_high_latitude() -> None:
    """At 60°N a degree of longitude is about half as long as a degree of latitude.

    One degree north and one east is therefore ~26° off north, not the 45° that
    treating degrees as square would give - an icon visibly pointing wrong.
    """
    bearing = bearing_deg(Point(lat=60.0, lon=0.0), Point(lat=61.0, lon=1.0))
    assert bearing == pytest.approx(26.2, abs=0.2)


def test_coincident_points_have_no_bearing() -> None:
    assert bearing_deg(BERLIN, BERLIN) is None


class TestPolyline:
    def test_position_is_by_distance_not_by_vertex(self) -> None:
        """Legs of 1° and 2°: a third of the way is the middle vertex, not halfway."""
        line = Polyline((ORIGIN, ONE_EAST, THREE_EAST))

        assert line.point_at(1 / 3).lon == pytest.approx(1.0)
        assert line.point_at(0.5).lon == pytest.approx(1.5)

    def test_fractions_outside_the_segment_clamp_to_its_ends(self) -> None:
        line = Polyline((ORIGIN, THREE_EAST))

        assert line.point_at(-0.5) == ORIGIN
        assert line.point_at(1.5) == THREE_EAST

    def test_bearing_follows_the_leg_the_point_is_on(self) -> None:
        line = Polyline((ORIGIN, ONE_NORTH, ONE_NORTH_ONE_EAST))

        assert line.bearing_at(0.25) == pytest.approx(0.0)
        assert line.bearing_at(0.75) == pytest.approx(90.0, abs=0.1)

    def test_a_vertex_takes_the_bearing_of_the_leg_leaving_it(self) -> None:
        """East one degree then north one degree: two legs of exactly equal length."""
        line = Polyline((ORIGIN, ONE_EAST, ONE_NORTH_ONE_EAST))

        assert line.bearing_at(0.5) == pytest.approx(0.0)
        # ...except the final vertex, which has no leg leaving it.
        assert line.bearing_at(1.0) == pytest.approx(0.0)

    def test_repeated_points_do_not_make_a_directionless_leg(self) -> None:
        line = Polyline((ORIGIN, ORIGIN, ONE_EAST))

        assert line.points == (ORIGIN, ONE_EAST)
        assert line.bearing_at(0.0) == pytest.approx(90.0)

    def test_a_single_point_has_no_length_and_no_direction(self) -> None:
        line = Polyline((BERLIN, BERLIN))

        assert line.length_m == 0.0
        assert line.point_at(0.5) == BERLIN
        assert line.bearing_at(0.5) is None

    def test_an_empty_polyline_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one point"):
            Polyline(())


def test_the_straight_line_fallback_has_no_geometry_ref() -> None:
    """The browser rebuilds a straight line from the stations; there is nothing to fetch."""
    corridor = straight_line(BERLIN, MUENCHEN)

    assert corridor.ref is None
    assert corridor.polyline.points == (BERLIN, MUENCHEN)
