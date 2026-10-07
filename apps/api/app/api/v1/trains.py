"""Train endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import TrainServiceDep
from app.schemas.trains import TrainDetailResponse, TrainListParams, TrainListResponse

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


# Phase 7's /trains/stream must be registered above this route, or "stream"
# would be taken for a trip_id.
@router.get(
    "/{trip_id}",
    response_model=TrainDetailResponse,
    summary="One train in detail",
    description=(
        "A trip's stops, route line and - while it runs - its position. A trip_id runs on "
        "many days: without `service_date` this is the instance running now, else the most "
        "recent to have started, else the next. Trip ids are not stable across timetable "
        "releases, so a stored id may stop resolving after a re-import."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"description": "No such trip in the timetable"}},
)
async def get_train(
    trip_id: str,
    service: TrainServiceDep,
    service_date: Annotated[date | None, Query(description="Which day's instance.")] = None,
) -> TrainDetailResponse:
    detail = await service.detail(trip_id, service_date)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no trip {trip_id!r} in the timetable")
    return TrainDetailResponse.from_detail(detail)
