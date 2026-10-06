"""Estimate where a train is from its timetable.

The engine returns **segment state**, not just a point: the two stations a
train is between, when it leaves one and reaches the other, and the geometry
joining them. A point goes stale the moment it is sent; segment state lets the
browser compute the position for any later instant itself, which is what makes
motion smooth between 60-second updates (Phase 8).

``now`` is always a parameter, never read from the clock. That is what makes
every case below - midnight crossings included - deterministic to test.
"""

from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.services.positions.geometry import Corridor, straight_line
from app.services.positions.timetable import Call, ScheduledTrip, Station

#: Supplies the geometry between two consecutive stations.
CorridorResolver = Callable[[Station, Station], Corridor]


class TrainStatus(StrEnum):
    MOVING = "moving"
    #: Standing at ``from_station``: dwelling mid-route, or arrived at the
    #: terminus.
    STOPPED = "stopped"


class PositionSource(StrEnum):
    SCHEDULED = "scheduled"
    #: Schedule adjusted by a GTFS-RT trip update. Arrives with Phase 6.
    REALTIME = "realtime"


@dataclass(frozen=True, slots=True)
class SegmentState:
    """Where a train is, and everything needed to say where it will be next."""

    trip_id: str
    service_date: date

    label: str
    destination: str
    category: str
    operator: str

    status: TrainStatus

    #: The segment the train is on. A train dwelling at a station is given the
    #: segment it is *about to start*, with a departure still in the future:
    #: progress then clamps to 0 until it leaves, and the browser sets it moving
    #: on time without waiting for the next update.
    from_station: Station
    to_station: Station
    departure_utc: datetime
    arrival_utc: datetime

    #: Fraction of the segment's duration elapsed, in ``[0, 1]``.
    progress: float

    #: For first paint only; the browser extrapolates from the fields above.
    lat: float
    lon: float
    #: Clockwise from north. ``None`` when the segment has no direction.
    bearing: float | None
    geometry_ref: str | None

    #: Seconds behind schedule. ``None`` until realtime data arrives (Phase 6).
    delay_seconds: int | None
    position_source: PositionSource

    @property
    def display_name(self) -> str:
        """``"ICE 10 → München Hbf"``: line and destination, since there is no train number."""
        return f"{self.label} → {self.destination}"


class TrainPositionEstimator:
    """Turns a dated trip and an instant into segment state."""

    def __init__(self, corridors: CorridorResolver | None = None) -> None:
        self._corridors = corridors or _straight_line_between

    def estimate(self, trip: ScheduledTrip, now: datetime) -> SegmentState | None:
        """Where ``trip`` is at ``now``, or ``None`` if it is not running.

        A trip runs from departure at its first station to arrival at its last,
        both inclusive - the window ``TripInstance`` indexes. The two differ
        only where calls are folded at one station: a trip that changes platform
        at its origin starts once it actually leaves.
        """
        calls = merge_station_calls(trip.calls)
        if len(calls) < 2:
            return None
        if now < calls[0].departure_utc or now > calls[-1].arrival_utc:
            return None

        # How many of the calls after the first the train has already reached.
        reached = bisect_right([call.arrival_utc for call in calls[1:]], now)

        terminus = calls[-1].station
        if reached == len(calls) - 1:
            # Exactly at the final arrival: arrived, at the end of the last leg.
            return self._state(trip, terminus, calls[-2], calls[-1], TrainStatus.STOPPED, 1.0)

        current, upcoming = calls[reached], calls[reached + 1]
        if now < current.departure_utc:
            return self._state(trip, terminus, current, upcoming, TrainStatus.STOPPED, 0.0)

        progress = _progress(now, current.departure_utc, upcoming.arrival_utc)
        return self._state(trip, terminus, current, upcoming, TrainStatus.MOVING, progress)

    def _state(
        self,
        trip: ScheduledTrip,
        terminus: Station,
        current: Call,
        upcoming: Call,
        status: TrainStatus,
        progress: float,
    ) -> SegmentState:
        corridor = self._corridors(current.station, upcoming.station)
        point = corridor.polyline.point_at(progress)
        return SegmentState(
            trip_id=trip.trip_id,
            service_date=trip.service_date,
            label=trip.route_name,
            # The headsign can change along a trip, so read it where the train is.
            destination=current.headsign or terminus.name,
            category=trip.category,
            operator=trip.operator,
            status=status,
            from_station=current.station,
            to_station=upcoming.station,
            departure_utc=current.departure_utc,
            arrival_utc=upcoming.arrival_utc,
            progress=progress,
            lat=point.lat,
            lon=point.lon,
            bearing=corridor.polyline.bearing_at(progress),
            geometry_ref=corridor.ref,
            delay_seconds=None,
            position_source=PositionSource.SCHEDULED,
        )


def merge_station_calls(calls: Iterable[Call]) -> list[Call]:
    """Order calls by stop sequence and fold consecutive calls at one station.

    Two consecutive stop times on different platforms of the same station
    resolve to the same station, and a segment from a station to itself has no
    length and no direction. Folding keeps the first arrival and the last
    departure, so the dwell spans both, and the later headsign, which is the
    one the train leaves with.
    """
    merged: list[Call] = []
    for call in sorted(calls, key=lambda call: call.stop_sequence):
        if merged and merged[-1].station.station_id == call.station.station_id:
            previous = merged[-1]
            merged[-1] = Call(
                stop_sequence=previous.stop_sequence,
                station=previous.station,
                arrival_utc=previous.arrival_utc,
                departure_utc=call.departure_utc,
                headsign=call.headsign or previous.headsign,
            )
        else:
            merged.append(call)
    return merged


def _progress(now: datetime, departure: datetime, arrival: datetime) -> float:
    """Fraction of the segment elapsed.

    The caller has established ``departure <= now < arrival`` - bisection finds
    an arrival strictly after ``now`` even in a timetable that runs backwards -
    so the segment has a duration and the result lies in ``[0, 1)``. A
    zero-minute hop, which a timetable rounded to the minute can contain, never
    gets here: its arrival is not after ``now``, so the train counts as having
    reached it.
    """
    return (now - departure) / (arrival - departure)


def _straight_line_between(origin: Station, destination: Station) -> Corridor:
    return straight_line(origin.point, destination.point)
