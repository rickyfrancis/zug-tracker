"""Filtering trains by viewport and category."""

from dataclasses import replace

import pytest

from app.services.positions.estimator import SegmentState
from app.services.positions.geometry import Point
from app.services.trains.filters import BoundingBox, TrainFilter, parse_categories
from tests.trains import BERLIN, HAMBURG, LEIPZIG, MUENCHEN, segment_state

#: Roughly Berlin and Brandenburg.
BERLIN_AREA = BoundingBox(west=12.0, south=52.0, east=14.5, north=53.0)


class TestBoundingBoxParse:
    def test_west_south_east_north(self) -> None:
        assert BoundingBox.parse("5.87,47.27,15.04,55.06") == BoundingBox(5.87, 47.27, 15.04, 55.06)

    def test_a_degenerate_box_is_allowed(self) -> None:
        assert BoundingBox.parse("13,52,13,52") == BoundingBox(13, 52, 13, 52)

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("5,47,15", "4 comma-separated"),
            ("5,47,15,55,1", "4 comma-separated"),
            ("5,47,east,55", "numbers"),
            ("5,47,,55", "numbers"),
            ("nan,47,15,55", "finite"),
            ("5,47,inf,55", "finite"),
            ("-181,47,15,55", "longitudes"),
            ("5,-91,15,55", "latitudes"),
            ("5,55,15,47", "south must not exceed north"),
            ("170,47,-170,55", "antimeridian"),
        ],
    )
    def test_invalid_boxes_are_rejected(self, text: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            BoundingBox.parse(text)


class TestBoundingBoxOverlap:
    def test_a_segment_inside(self) -> None:
        assert BERLIN_AREA.overlaps([Point(52.5, 13.4), Point(52.4, 13.1)])

    def test_a_segment_crossing_with_both_ends_outside(self) -> None:
        """Hamburg to Leipzig passes over the box without stopping in it."""
        box = BoundingBox(west=10.5, south=52.2, east=11.5, north=52.8)

        assert box.overlaps([HAMBURG.point, LEIPZIG.point])

    def test_a_segment_entirely_outside(self) -> None:
        assert not BERLIN_AREA.overlaps([LEIPZIG.point, MUENCHEN.point])

    def test_touching_an_edge_counts(self) -> None:
        assert BERLIN_AREA.overlaps([Point(53.0, 13.0), Point(54.0, 13.0)])


class TestCategories:
    def test_case_insensitive_and_deduplicated(self) -> None:
        assert parse_categories("ice,IC,Ice") == frozenset({"ICE", "IC"})

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("ICE,,IC", "not a category: ''"),
            ("", "not a category: ''"),
            ("IC E", "not a category"),
            ("ICE;IC", "not a category"),
            ("TOOLONGXX", "not a category"),
            (",".join(["ICE"] * 21), "at most 20"),
        ],
    )
    def test_invalid_lists_are_rejected(self, text: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_categories(text)


class TestTrainFilter:
    def test_an_empty_filter_matches_everything(self) -> None:
        assert TrainFilter().matches(segment_state())

    def test_category(self) -> None:
        state = segment_state(category="ICE")

        assert TrainFilter(categories=frozenset({"ICE", "EC"})).matches(state)
        assert not TrainFilter(categories=frozenset({"IC"})).matches(state)

    def test_an_unknown_category_matches_nothing(self) -> None:
        assert not TrainFilter(categories=frozenset({"XYZ"})).matches(segment_state())

    def test_bbox_uses_the_segment_not_the_current_point(self) -> None:
        """Just out of Leipzig towards Berlin: the point is outside, the destination inside."""
        state: SegmentState = replace(
            segment_state(from_station=LEIPZIG, to_station=BERLIN), lat=51.4, lon=12.4
        )

        assert TrainFilter(bbox=BERLIN_AREA).matches(state)
        assert not TrainFilter(bbox=BERLIN_AREA, categories=frozenset({"IC"})).matches(state), (
            "filters combine with AND"
        )

    def test_zoom_changes_nothing_yet(self) -> None:
        state = segment_state(from_station=LEIPZIG, to_station=MUENCHEN)

        assert TrainFilter(zoom=3).matches(state)
        assert not TrainFilter(bbox=BERLIN_AREA, zoom=12).matches(state)
