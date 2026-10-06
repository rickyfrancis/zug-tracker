"""What to call a station.

A parent station's own name is often the local transit authority's, not the
railway's: ``S+U Berlin Hauptbahnhof``, ``Hamburg, Hamburg Hbf``. Its platforms
mostly carry the name a departure board uses - ``Berlin Hbf`` - so that is
where the display name comes from. Mostly: in fv_free, nine stations have
platforms under more than one name, and some of those are no better than the
parent's (``Bahnhof, Wittenberge``, ``München Hbf Gl.5-10``,
``Gesundbrunnen Bahnhof Badstr., Berlin``). The rule below picks a clean name
for all 553 stations in the 2026-10-06 release.

Resolved once at import, like the feed's other quirks (ADR-0003): the raw names
stay in ``stop.name`` and the choice goes into ``stop.display_name``.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from app.services.gtfs.rows import StopRow, StopTimeRow

#: A track range some platforms (and headsigns) carry: ``München Hbf Gl.5-10``.
_TRACK_SUFFIX = re.compile(r"\s+Gl\.\s*\d[\w\s/-]*$")


def strip_track_suffix(name: str) -> str:
    """``"München Hbf Gl.5-10"`` -> ``"München Hbf"``."""
    return _TRACK_SUFFIX.sub("", name)


def station_display_names(
    stops: Sequence[StopRow], stop_times: Iterable[StopTimeRow]
) -> dict[str, str]:
    """A display name for every stop that acts as a station.

    That is every station, plus any stop without a parent, which the timetable
    read treats as its own station.
    """
    calls = Counter(stop_time.stop_id for stop_time in stop_times)
    platform_names: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for stop in stops:
        if stop.parent_station_id is not None:
            platform_names[stop.parent_station_id][strip_track_suffix(stop.name)] += calls[
                stop.stop_id
            ]

    return {
        stop.stop_id: _choose(stop.name, platform_names.get(stop.stop_id, Counter()))
        for stop in stops
        if stop.is_station or stop.parent_station_id is None
    }


def _choose(own_name: str, platform_names: Counter[str]) -> str:
    """The most-called platform name, avoiding ``Place, Stop`` forms.

    A comma marks the local-transit naming style, which reads badly on a map, so
    a comma-free name wins even when it is called less often. Where every
    platform name has one, the station's own name is the better fallback if it
    does not.
    """
    own_name = strip_track_suffix(own_name)
    if not platform_names:
        return own_name

    clean = {name: count for name, count in platform_names.items() if "," not in name}
    if clean:
        return _most_called(clean)
    if "," not in own_name:
        return own_name
    return _most_called(platform_names)


def _most_called(names: dict[str, int]) -> str:
    # Ties go to the alphabetically first name, so the result is stable.
    return min(names, key=lambda name: (-names[name], name))
