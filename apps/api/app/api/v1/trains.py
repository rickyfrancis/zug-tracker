"""Train endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import TrainServiceDep
from app.schemas.trains import TrainListParams, TrainListResponse

router = APIRouter(prefix="/trains", tags=["trains"])


@router.get(
    "",
    response_model=TrainListResponse,
    summary="Running trains",
    description=(
        "Every train running now, optionally narrowed to a viewport and to categories. "
        "Each train carries its current segment, so a client can keep placing it "
        "between updates."
    ),
)
async def list_trains(
    params: Annotated[TrainListParams, Query()],
    service: TrainServiceDep,
) -> TrainListResponse:
    return TrainListResponse.from_list(await service.trains(params.to_filter()))
