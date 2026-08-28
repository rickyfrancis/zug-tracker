"""Response models for the health endpoint."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.services.health_service import (
    DatasetInfo,
    DependencyStatus,
    HealthReport,
    OverallStatus,
)


class DependencyHealth(BaseModel):
    name: str = Field(examples=["postgres"])
    status: DependencyStatus
    latency_ms: float | None = None
    detail: str | None = None


class DatasetHealth(BaseModel):
    """The timetable currently being served. Never affects ``status``."""

    feed_id: str = Field(examples=["fv_free"])
    version: str = Field(examples=["20260822T084127Z-8153a8b8"])
    imported_at: datetime
    valid_from: date
    valid_to: date
    days_until_expiry: int = Field(
        description="Negative once the feed has expired and the map has emptied."
    )
    is_expired: bool

    @classmethod
    def from_info(cls, info: DatasetInfo) -> "DatasetHealth":
        return cls(
            feed_id=info.feed_id,
            version=info.version,
            imported_at=info.imported_at,
            valid_from=info.valid_from,
            valid_to=info.valid_to,
            days_until_expiry=info.days_until_expiry,
            is_expired=info.is_expired,
        )


class HealthResponse(BaseModel):
    status: OverallStatus
    environment: str
    checked_at: datetime
    dependencies: list[DependencyHealth]

    #: ``None`` before the first import has run.
    dataset: DatasetHealth | None = None

    @classmethod
    def from_report(cls, report: HealthReport, environment: str) -> "HealthResponse":
        return cls(
            status=report.status,
            environment=environment,
            checked_at=report.checked_at,
            dependencies=[
                DependencyHealth(
                    name=check.name,
                    status=check.status,
                    latency_ms=check.latency_ms,
                    detail=check.detail,
                )
                for check in report.dependencies
            ],
            dataset=DatasetHealth.from_info(report.dataset) if report.dataset else None,
        )
