"""Health endpoint."""

from fastapi import APIRouter, Response, status

from app.api.deps import HealthServiceDep, SettingsDep
from app.schemas.health import HealthResponse
from app.services.health_service import OverallStatus

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description=(
        "Reports the API's own status plus its backing services. Returns 503 when a "
        "critical dependency (PostgreSQL or Redis) is unreachable."
    ),
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def get_health(
    response: Response,
    service: HealthServiceDep,
    settings: SettingsDep,
) -> HealthResponse:
    report = await service.check()
    if report.status is not OverallStatus.OK:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse.from_report(report, settings.environment)
