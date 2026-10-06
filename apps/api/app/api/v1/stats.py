"""Fleet statistics endpoint."""

from fastapi import APIRouter

from app.api.deps import TrainServiceDep
from app.schemas.stats import StatsResponse

router = APIRouter(tags=["trains"])


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Fleet counts",
    description=(
        "Running trains counted by category, status and position source, across the whole "
        "fleet. Categories with nothing running are listed as 0, so this also says which "
        "categories `GET /trains?category=` can filter on."
    ),
)
async def get_stats(service: TrainServiceDep) -> StatsResponse:
    return StatsResponse.from_stats(await service.stats())
