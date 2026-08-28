"""GTFS time semantics: service-day offsets to absolute UTC.

GTFS does not measure stop times from local midnight. It measures them from
**noon minus twelve hours** on the service date, and the spec is explicit that
this is "effectively midnight, except for days on which daylight savings time
changes occur". Local noon is never ambiguous - no DST transition lands there -
so anchoring at noon and stepping back twelve *real* hours yields a well-defined
instant on every date of the year, including the 23- and 25-hour ones.

The practical consequence, intended rather than accidental: on a transition date
the service day begins an hour either side of local midnight, so a timetable
entry of ``02:30`` on the spring-forward date resolves to local ``01:30``.
Adding a ``timedelta`` to local midnight instead would be wrong twice a year and
silently right the rest of the time - the worst possible failure shape.

Hours are not clamped to 24. This feed reaches **35** and 16% of its trips cross
midnight, so times stay integer seconds everywhere else and become timestamps
only here.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600

#: The anchor GTFS defines service-day offsets against, and the step back from
#: it to offset zero.
SERVICE_DAY_ANCHOR = time(12, 0)
SERVICE_DAY_ANCHOR_OFFSET = timedelta(hours=12)


class InvalidGTFSTimeError(ValueError):
    """A stop time that is not ``H:MM:SS``."""


def parse_gtfs_time(value: str) -> int:
    """Parse ``"27:54:00"`` into seconds since the service day start.

    Hours above 23 are ordinary input, not an error: they are how GTFS expresses
    a call happening after midnight on a trip that departed the evening before.
    """
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise InvalidGTFSTimeError(f"expected H:MM:SS, got {value!r}")

    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError as exc:
        raise InvalidGTFSTimeError(f"non-numeric component in {value!r}") from exc

    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise InvalidGTFSTimeError(f"component out of range in {value!r}")

    return hours * SECONDS_PER_HOUR + minutes * SECONDS_PER_MINUTE + seconds


def service_day_origin_utc(service_date: date, timezone: ZoneInfo) -> datetime:
    """Return the UTC instant that offset ``0`` on ``service_date`` refers to.

    Noon is resolved in the feed's timezone first and converted to UTC *before*
    the twelve-hour step, so the subtraction is real elapsed time rather than
    wall-clock arithmetic. That is the whole point of the anchor.
    """
    local_noon = datetime.combine(service_date, SERVICE_DAY_ANCHOR, tzinfo=timezone)
    return local_noon.astimezone(UTC) - SERVICE_DAY_ANCHOR_OFFSET


def to_utc(service_date: date, offset_seconds: int, timezone: ZoneInfo) -> datetime:
    """Resolve one stop time to an absolute UTC timestamp."""
    return service_day_origin_utc(service_date, timezone) + timedelta(seconds=offset_seconds)
