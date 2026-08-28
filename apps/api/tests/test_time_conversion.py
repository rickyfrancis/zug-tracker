"""GTFS service-day time semantics.

The feed's own validity window contains no DST transition, so these dates are
deliberately synthetic: they are the only way to pin the behaviour the plan
calls out as the hardest correctness problem in the project.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.gtfs.time_conversion import (
    SECONDS_PER_HOUR,
    InvalidGTFSTimeError,
    parse_gtfs_time,
    service_day_origin_utc,
    to_utc,
)

BERLIN = ZoneInfo("Europe/Berlin")

#: Europe/Berlin transitions at 02:00 local on the last Sunday of March/October.
SPRING_FORWARD = date(2027, 3, 28)  # 23-hour day
AUTUMN_BACK = date(2026, 10, 25)  # 25-hour day
ORDINARY_SUMMER = date(2026, 8, 28)  # CEST, +02:00


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[arg-type]


class TestParseGTFSTime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("00:00:00", 0),
            ("12:00:00", 43_200),
            ("23:59:59", 86_399),
            ("24:00:00", 86_400),
            ("27:54:00", 100_440),
            ("35:59:00", 129_540),  # the feed's observed maximum hour
            ("7:05:00", 25_500),  # single-digit hour
        ],
    )
    def test_parses_offsets_including_hours_past_midnight(self, value: str, expected: int) -> None:
        assert parse_gtfs_time(value) == expected

    @pytest.mark.parametrize(
        "value", ["", "12:00", "12:00:00:00", "aa:00:00", "12:60:00", "-1:00:00"]
    )
    def test_rejects_malformed_times(self, value: str) -> None:
        with pytest.raises(InvalidGTFSTimeError):
            parse_gtfs_time(value)


class TestServiceDayOrigin:
    def test_ordinary_day_starts_at_local_midnight(self) -> None:
        # CEST is +02:00, so local midnight is 22:00 UTC the previous day.
        assert service_day_origin_utc(ORDINARY_SUMMER, BERLIN) == utc(2026, 8, 27, 22, 0)

    def test_spring_forward_day_starts_before_local_midnight(self) -> None:
        """Local noon is CEST (+02:00), so noon-minus-12h lands at 23:00 CET."""
        origin = service_day_origin_utc(SPRING_FORWARD, BERLIN)
        assert origin == utc(2027, 3, 27, 22, 0)
        assert origin.astimezone(BERLIN).hour == 23

    def test_autumn_back_day_starts_after_local_midnight(self) -> None:
        """Local noon is CET (+01:00), so noon-minus-12h lands at 01:00 CEST."""
        origin = service_day_origin_utc(AUTUMN_BACK, BERLIN)
        assert origin == utc(2026, 10, 24, 23, 0)
        assert origin.astimezone(BERLIN).hour == 1


class TestToUTC:
    def test_midday_departure_is_local_noon(self) -> None:
        assert to_utc(ORDINARY_SUMMER, parse_gtfs_time("12:00:00"), BERLIN) == utc(2026, 8, 28, 10)

    def test_hour_past_24_lands_on_the_following_calendar_day(self) -> None:
        """27:54 on a service date is 03:54 local the next morning."""
        moment = to_utc(ORDINARY_SUMMER, parse_gtfs_time("27:54:00"), BERLIN)

        assert moment == utc(2026, 8, 29, 1, 54)
        assert moment.astimezone(BERLIN).date() == date(2026, 8, 29)

    def test_hour_35_stays_on_the_same_service_date(self) -> None:
        """The feed's worst case: still one trip, still one service date."""
        moment = to_utc(ORDINARY_SUMMER, parse_gtfs_time("35:00:00"), BERLIN)

        assert moment == utc(2026, 8, 29, 9, 0)

    def test_spring_forward_departure_skips_the_missing_hour(self) -> None:
        """02:30 is scheduled into an hour that does not exist locally.

        Real elapsed time from the anchor puts it at 01:30 CET - a real instant -
        rather than raising or silently landing an hour late.
        """
        moment = to_utc(SPRING_FORWARD, parse_gtfs_time("02:30:00"), BERLIN)

        assert moment == utc(2027, 3, 28, 0, 30)
        assert moment.astimezone(BERLIN).strftime("%H:%M") == "01:30"

    def test_autumn_back_departure_resolves_the_repeated_hour(self) -> None:
        """02:30 occurs twice locally; the anchor picks the second, unambiguously."""
        moment = to_utc(AUTUMN_BACK, parse_gtfs_time("02:30:00"), BERLIN)

        assert moment == utc(2026, 10, 25, 1, 30)
        assert moment.astimezone(BERLIN).utcoffset().total_seconds() == 3600  # type: ignore[union-attr]

    def test_offsets_are_monotonic_across_a_transition(self) -> None:
        """Whatever the local clock does, later offsets are later instants."""
        moments = [
            to_utc(SPRING_FORWARD, seconds, BERLIN)
            for seconds in range(0, 30 * SECONDS_PER_HOUR, SECONDS_PER_HOUR)
        ]

        assert moments == sorted(moments)
