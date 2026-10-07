"""Response model for the stats endpoint."""

from pydantic import Field

from app.schemas.trains import SnapshotFields
from app.services.trains.train_service import FleetStats


class StatsResponse(SnapshotFields):
    """Counts across every running train. Every key is present, zeros included."""

    total: int = Field(ge=0, examples=[253])
    by_category: dict[str, int] = Field(
        description="Every category in the timetable, running or not.",
        examples=[{"EC": 21, "ECE": 6, "EN": 0, "IC": 41, "ICE": 181, "RJ": 4}],
    )
    by_status: dict[str, int] = Field(examples=[{"moving": 201, "stopped": 52}])
    by_position_source: dict[str, int] = Field(examples=[{"realtime": 0, "scheduled": 253}])

    @classmethod
    def from_stats(cls, stats: FleetStats) -> "StatsResponse":
        return cls.model_validate(
            {
                **cls.snapshot_fields(stats.snapshot),
                "total": stats.total,
                "by_category": stats.by_category,
                "by_status": {str(status): count for status, count in stats.by_status.items()},
                "by_position_source": {
                    str(source): count for source, count in stats.by_position_source.items()
                },
            }
        )
