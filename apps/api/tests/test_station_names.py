"""Choosing a station's display name from its platforms.

Every name here is fv_free's own: the cases are the stations the rule was
written for, not invented edge cases.
"""

from app.services.gtfs.rows import StopRow, StopTimeRow
from app.services.gtfs.station_names import station_display_names, strip_track_suffix


def station(stop_id: str, name: str) -> StopRow:
    return StopRow(stop_id, name, None, 52.5, 13.4, location_type=1, platform_code=None)


def platform(stop_id: str, name: str, parent: str) -> StopRow:
    return StopRow(stop_id, name, parent, 52.5, 13.4, location_type=0, platform_code=None)


def calls(stop_id: str, count: int) -> list[StopTimeRow]:
    return [StopTimeRow(f"t{n}", 0, stop_id, 0, 0, None, None, None) for n in range(count)]


def name_of(stops: list[StopRow], *stop_times: list[StopTimeRow]) -> str:
    return station_display_names(stops, [call for group in stop_times for call in group])["P"]


def test_the_platform_name_replaces_the_parents_own() -> None:
    stops = [station("P", "S+U Berlin Hauptbahnhof"), platform("a", "Berlin Hbf", "P")]

    assert name_of(stops, calls("a", 3)) == "Berlin Hbf"


def test_a_place_prefix_on_the_parent_is_dropped() -> None:
    stops = [station("P", "Hamburg, Hamburg Hbf"), platform("a", "Hamburg Hbf", "P")]

    assert name_of(stops, calls("a", 1)) == "Hamburg Hbf"


def test_track_ranges_are_stripped_and_merged() -> None:
    stops = [
        station("P", "München Hbf"),
        platform("a", "München Hbf Gl.5-10", "P"),
        platform("b", "München Hbf Gl.27-36", "P"),
    ]

    assert name_of(stops, calls("a", 1), calls("b", 1)) == "München Hbf"


def test_the_most_called_platform_name_wins() -> None:
    stops = [
        station("P", "Köln Messe/Deutz Bf"),
        platform("a", "Köln Messe/Deutz Gl.11-12", "P"),
        platform("b", "Köln Messe/Deutz Hilfsname", "P"),
    ]

    assert name_of(stops, calls("a", 5), calls("b", 2)) == "Köln Messe/Deutz"


def test_a_comma_free_name_beats_a_more_called_place_stop_form() -> None:
    """Gesundbrunnen: 207 calls under the local name, 185 under the railway's."""
    stops = [
        station("P", "S+U Gesundbrunnen Bhf (Berlin)"),
        platform("a", "Gesundbrunnen Bahnhof Badstr., Berlin", "P"),
        platform("b", "Berlin Gesundbrunnen", "P"),
    ]

    assert name_of(stops, calls("a", 207), calls("b", 185)) == "Berlin Gesundbrunnen"


def test_the_parent_name_is_the_fallback_when_every_platform_has_a_comma() -> None:
    stops = [station("P", "Bremen Hauptbahnhof"), platform("a", "Bremen, Hauptbahnhof", "P")]

    assert name_of(stops, calls("a", 4)) == "Bremen Hauptbahnhof"


def test_with_commas_everywhere_the_most_called_platform_name_is_kept() -> None:
    stops = [
        station("P", "Elsterwerda, Bahnhof"),
        platform("a", "Bahnhof, Elsterwerda", "P"),
        platform("b", "Elsterwerda, Bf", "P"),
    ]

    assert name_of(stops, calls("a", 1), calls("b", 3)) == "Elsterwerda, Bf"


def test_ties_are_broken_alphabetically() -> None:
    stops = [
        station("P", "S Spandau Bhf (Berlin)"),
        platform("a", "Berlin-Spandau", "P"),
        platform("b", "Berlin Spandau", "P"),
    ]

    assert name_of(stops) == "Berlin Spandau"


def test_a_station_without_platforms_keeps_its_own_name() -> None:
    assert name_of([station("P", "Basel SBB")]) == "Basel SBB"


def test_a_parentless_platform_is_named_but_child_platforms_are_not() -> None:
    stops = [
        station("P", "S+U Berlin Hauptbahnhof"),
        platform("a", "Berlin Hbf", "P"),
        StopRow("lone", "Padborg St.", None, 54.8, 9.4, location_type=0, platform_code=None),
    ]

    assert station_display_names(stops, []) == {"P": "Berlin Hbf", "lone": "Padborg St."}


def test_strip_track_suffix_leaves_other_names_alone() -> None:
    assert strip_track_suffix("München Hbf Gl.27-36") == "München Hbf"
    assert strip_track_suffix("Frankfurt(Main)Hbf") == "Frankfurt(Main)Hbf"
    assert strip_track_suffix("Glückstadt") == "Glückstadt"
