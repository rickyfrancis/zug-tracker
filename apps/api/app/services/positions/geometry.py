"""Where along a segment a train is, given how far through it it is.

Progress is interpolated by *time* in the estimator and placed here by *arc
length*, so a train holds a constant speed along its geometry, curves included.

Within one leg of a polyline, points are interpolated linearly in latitude and
longitude rather than along a great circle. The browser has to reproduce this
exactly when it extrapolates positions itself in Phase 8 - any other rule makes
a train jump when the first animated frame replaces the server's first paint -
and linear interpolation is the rule it can reproduce in one line. The cost is
a few kilometres of drift off the true great circle on the longest
straight-line legs, which curated corridors exist to shorten anyway.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate, pairwise

#: Mean Earth radius, as used by the haversine formula.
EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True, slots=True)
class Point:
    lat: float
    lon: float


def distance_m(a: Point, b: Point) -> float:
    """Great-circle distance in metres (haversine)."""
    phi_a, phi_b = math.radians(a.lat), math.radians(b.lat)
    d_phi = phi_b - phi_a
    d_lambda = math.radians(b.lon - a.lon)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def bearing_deg(a: Point, b: Point) -> float | None:
    """Direction of travel from ``a`` to ``b``, clockwise from north in ``[0, 360)``.

    Measured on a local flat approximation at the leg's mid-latitude, which is
    the direction a lat/lon-linear path actually runs in and, because Web
    Mercator is conformal, the direction a map icon must point to sit along the
    line drawn on screen. ``None`` when the two points coincide and there is no
    direction to report.
    """
    if a == b:
        return None
    mid_lat = math.radians((a.lat + b.lat) / 2)
    east = (b.lon - a.lon) * math.cos(mid_lat)
    north = b.lat - a.lat
    return math.degrees(math.atan2(east, north)) % 360


class Polyline:
    """A path between two stations, measured by arc length."""

    def __init__(self, points: Sequence[Point]) -> None:
        if not points:
            raise ValueError("a polyline needs at least one point")
        # Repeated points would make zero-length legs, which have no direction.
        deduplicated = [points[0]]
        deduplicated.extend(b for a, b in pairwise(points) if a != b)
        self._points = tuple(deduplicated)
        legs = (distance_m(a, b) for a, b in pairwise(self._points))
        self._cumulative_m = tuple(accumulate(legs, initial=0.0))

    @property
    def points(self) -> tuple[Point, ...]:
        return self._points

    @property
    def length_m(self) -> float:
        return self._cumulative_m[-1]

    def point_at(self, fraction: float) -> Point:
        """The point ``fraction`` of the way along, by distance. Clamped to the ends."""
        leg, t = self._locate(fraction)
        if leg is None:
            return self._points[0]
        a, b = self._points[leg], self._points[leg + 1]
        return Point(lat=a.lat + (b.lat - a.lat) * t, lon=a.lon + (b.lon - a.lon) * t)

    def bearing_at(self, fraction: float) -> float | None:
        """Direction of travel at ``fraction``: that of the leg it falls on."""
        leg, _ = self._locate(fraction)
        if leg is None:
            return None
        return bearing_deg(self._points[leg], self._points[leg + 1])

    def _locate(self, fraction: float) -> tuple[int | None, float]:
        """Which leg ``fraction`` falls on, and how far through that leg.

        ``None`` for a polyline of a single point, which has no legs.
        """
        legs = len(self._points) - 1
        if legs == 0:
            return None, 0.0
        target = min(max(fraction, 0.0), 1.0) * self.length_m
        # A target exactly on a vertex belongs to the leg leaving it, except at
        # the very end, which belongs to the last leg.
        leg = min(bisect_right(self._cumulative_m, target) - 1, legs - 1)
        start, end = self._cumulative_m[leg], self._cumulative_m[leg + 1]
        # Distinct points can still round to a zero-length leg.
        return leg, (target - start) / (end - start) if end > start else 0.0


@dataclass(frozen=True, slots=True)
class Corridor:
    """The geometry a train follows between two consecutive stations."""

    polyline: Polyline

    #: Names a curated geometry the browser can fetch and extrapolate along.
    #: ``None`` for the straight-line fallback, which the browser can rebuild
    #: from the two stations it is already sent.
    ref: str | None = None


def straight_line(origin: Point, destination: Point) -> Corridor:
    """The fallback for every station pair without a curated corridor."""
    return Corridor(Polyline((origin, destination)))
