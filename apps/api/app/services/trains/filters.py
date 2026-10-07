"""Which trains a client asked for.

Parsing lives here rather than in the request schema so that the rules - and
their error messages - are plain functions, testable without HTTP and reusable
by the SSE stream in Phase 7.
"""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.services.positions.estimator import SegmentState
from app.services.positions.geometry import Point

#: Categories come from the feed (``route_short_name``'s first word), so they
#: are validated by shape, not against a list: ``Route.category`` is String(8).
_CATEGORY = re.compile(r"^[A-Za-z0-9]{1,8}$")
MAX_CATEGORIES = 20


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A viewport in degrees. Never crosses the antimeridian."""

    west: float
    south: float
    east: float
    north: float

    @classmethod
    def parse(cls, text: str) -> "BoundingBox":
        """Parse ``west,south,east,north``, as MapLibre's ``getBounds().toArray()`` flattens."""
        parts = text.split(",")
        if len(parts) != 4:
            raise ValueError(f"bbox needs 4 comma-separated numbers, got {len(parts)}")
        try:
            west, south, east, north = (float(part) for part in parts)
        except ValueError:
            raise ValueError("bbox values must be numbers") from None
        if not all(math.isfinite(value) for value in (west, south, east, north)):
            raise ValueError("bbox values must be finite")
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            raise ValueError("bbox longitudes must lie within [-180, 180]")
        if not (-90 <= south <= 90 and -90 <= north <= 90):
            raise ValueError("bbox latitudes must lie within [-90, 90]")
        if south > north:
            raise ValueError("bbox south must not exceed north")
        if west > east:
            raise ValueError(
                "bbox west must not exceed east; crossing the antimeridian is unsupported"
            )
        return cls(west=west, south=south, east=east, north=north)

    def overlaps(self, points: Iterable[Point]) -> bool:
        """Whether the bounding box of ``points`` overlaps this one, edges included."""
        points = list(points)
        lats = [point.lat for point in points]
        lons = [point.lon for point in points]
        return (
            min(lons) <= self.east
            and max(lons) >= self.west
            and min(lats) <= self.north
            and max(lats) >= self.south
        )


def parse_categories(text: str) -> frozenset[str]:
    """``"ice,IC"`` -> ``{"ICE", "IC"}``. Case-insensitive; duplicates collapse."""
    parts = text.split(",")
    if len(parts) > MAX_CATEGORIES:
        raise ValueError(f"at most {MAX_CATEGORIES} categories, got {len(parts)}")
    for part in parts:
        if not _CATEGORY.fullmatch(part):
            raise ValueError(f"not a category: {part!r} (expected 1-8 letters or digits)")
    return frozenset(part.upper() for part in parts)


@dataclass(frozen=True, slots=True)
class TrainFilter:
    """A request's filters. Every field is optional and they combine with AND."""

    bbox: BoundingBox | None = None
    categories: frozenset[str] | None = None

    #: Level of detail. Accepted and validated, but deliberately unused while
    #: the feed holds only long-distance trains: once regional trains arrive,
    #: their categories are left out below a threshold zoom. Taking it now
    #: keeps that from being a contract change.
    zoom: float | None = None

    def matches(self, state: SegmentState) -> bool:
        if self.categories is not None and state.category.upper() not in self.categories:
            return False
        # The segment, not the current point: a train about to drive into view
        # must already be in the payload the browser extrapolates from.
        return self.bbox is None or self.bbox.overlaps(
            (state.from_station.point, state.to_station.point)
        )
