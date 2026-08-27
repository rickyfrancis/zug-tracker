"""Response models for the health endpoint."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.health_service import DependencyStatus, HealthReport, OverallStatus


class DependencyHealth(BaseModel):
    name: str = Field(examples=["postgres"])
    status: DependencyStatus
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: OverallStatus
    environment: str
    checked_at: datetime
    dependencies: list[DependencyHealth]

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
        )
