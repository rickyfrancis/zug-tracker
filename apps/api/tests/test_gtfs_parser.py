"""Parsing the GTFS text files.

The feed ships ``routes.txt`` with columns in the order
``route_long_name, route_short_name, agency_id, route_type, route_id``. GTFS
fixes no column order, so these tests exist mainly to prove that positional
parsing is impossible here.
"""

import io

import pytest

from app.services.gtfs.parser import (
    GTFSParseError,
    parse_calendar_dates,
    parse_calendars,
    parse_routes,
    parse_stop_times,
    parse_stops,
    split_short_name,
)

# Deliberately the feed's own non-standard order, with route_id last.
ROUTES_TXT = """route_long_name,route_short_name,agency_id,route_type,route_id
,ICE 10,8,2,77
,ICE,4,2,18
,EC 95,11,2,21
"""


class TestParseRoutes:
    def test_reads_by_header_name_not_position(self) -> None:
        routes = parse_routes(io.StringIO(ROUTES_TXT))

        first = routes[0]
        assert first.route_id == "77"
        assert first.short_name == "ICE 10"
        assert first.agency_id == "8"
        assert first.route_type == 2

    def test_keeps_short_name_verbatim_and_splits_it(self) -> None:
        routes = parse_routes(io.StringIO(ROUTES_TXT))

        assert [(r.short_name, r.category, r.line) for r in routes] == [
            ("ICE 10", "ICE", "10"),
            ("ICE", "ICE", None),
            ("EC 95", "EC", "95"),
        ]

    def test_empty_long_name_becomes_none(self) -> None:
        """Every route in this feed has an empty long_name."""
        assert all(route.long_name is None for route in parse_routes(io.StringIO(ROUTES_TXT)))

    def test_missing_column_fails_loudly(self) -> None:
        without_route_id = "route_long_name,route_short_name,agency_id,route_type\n,ICE 10,8,2\n"

        with pytest.raises(GTFSParseError, match="route_id"):
            parse_routes(io.StringIO(without_route_id))


class TestSplitShortName:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("ICE 10", ("ICE", "10")),
            ("ICE", ("ICE", None)),
            ("EN", ("EN", None)),
            ("ECE 88", ("ECE", "88")),
            ("  IC  55  ", ("IC", "55")),
            ("ice 10", ("ICE", "10")),
        ],
    )
    def test_splits_category_from_line(self, value: str, expected: tuple[str, str | None]) -> None:
        assert split_short_name(value) == expected

    def test_rejects_an_empty_short_name(self) -> None:
        """It is the only line label the feed carries; silence is not an option."""
        with pytest.raises(GTFSParseError):
            split_short_name("   ")


class TestParseStops:
    STOPS_TXT = """stop_name,parent_station,stop_id,stop_lat,stop_lon,location_type,platform_code
Aachen Süd(Gr),,117544,50.731915,6.04541,1,
Aachen Süd(Gr),117544,266325,50.731915,6.04541,,
"""

    def test_blank_location_type_defaults_to_platform(self) -> None:
        station, platform = parse_stops(io.StringIO(self.STOPS_TXT))

        assert station.location_type == 1
        assert station.is_station
        assert platform.location_type == 0
        assert platform.parent_station_id == "117544"

    def test_blank_parent_station_becomes_none(self) -> None:
        station, _ = parse_stops(io.StringIO(self.STOPS_TXT))

        assert station.parent_station_id is None


class TestParseCalendars:
    def test_weekday_flags_are_indexed_monday_first(self) -> None:
        text = (
            "monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date,service_id\n"
            "0,0,0,0,0,0,1,20260822,20260823,30\n"
        )

        calendar = parse_calendars(io.StringIO(text))[0]

        assert calendar.weekdays == (False,) * 6 + (True,)
        assert calendar.service_id == "30"

    def test_exception_types_are_kept_as_given(self) -> None:
        text = "service_id,exception_type,date\n10,1,20260911\n10,2,20260912\n"

        added, removed = parse_calendar_dates(io.StringIO(text))

        assert (added.exception_type, removed.exception_type) == (1, 2)


class TestParseStopTimes:
    def test_times_past_midnight_become_offsets(self) -> None:
        text = (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence,"
            "stop_headsign,pickup_type,drop_off_type\n"
            "100279,27:54:00,27:56:00,685271,0,Warszawa Wschodnia,1,\n"
        )

        call = parse_stop_times(io.StringIO(text))[0]

        assert call.arrival_seconds == 100_440
        assert call.departure_seconds == 100_560
        assert call.stop_sequence == 0
        assert call.stop_headsign == "Warszawa Wschodnia"
        assert call.pickup_type == 1
        assert call.drop_off_type is None
