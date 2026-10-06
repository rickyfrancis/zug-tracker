"""The whole route of a trip, as one line.

Built leg by leg from the same :data:`CorridorResolver` the estimator places
trains with, so the line drawn for a selected train is exactly the one its icon
travels along - straight between stations today, curated corridors where they
exist later.
"""

from collections.abc import Iterable
from itertools import pairwise

from app.services.positions.estimator import (
    CorridorResolver,
    merge_station_calls,
    straight_line_between,
)
from app.services.positions.geometry import Polyline
from app.services.positions.timetable import Call


def trip_route(
    calls: Iterable[Call], corridors: CorridorResolver = straight_line_between
) -> Polyline:
    """The polyline through every station of a trip, in stop order.

    Calls are folded per station first, as the estimator folds them, so a
    platform change does not add a zero-length leg. Each corridor starts where
    the previous one ended; :class:`Polyline` drops the repeated vertex.
    """
    stations = [call.station for call in merge_station_calls(calls)]
    if not stations:
        raise ValueError("a trip with no calls has no route")
    points = [stations[0].point]
    for origin, destination in pairwise(stations):
        points.extend(corridors(origin, destination).polyline.points)
    return Polyline(points)
