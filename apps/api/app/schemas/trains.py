"""Request and response models for the train endpoints.

These shapes are the contract the map (Phase 5), the SSE stream (Phase 7) and
client-side animation (Phase 8) are built on. Fields that only realtime data can
fill are present and ``null`` until Phase 6, so filling them is not a change of
shape.
"""

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.positions.estimator import PositionSource, SegmentState, TrainStatus
from app.services.positions.timetable import Station
from app.services.trains.filters import BoundingBox, TrainFilter, parse_categories
from app.services.trains.train_service import SnapshotInfo, TrainList

#: ~1 m. Train coordinates are for first paint only, so more is noise.
POSITION_DECIMALS = 5

SNAPSHOT_AGE_DESCRIPTION = (
    "Seconds between estimating these positions and answering. 0 while positions are "
    "computed per request; once a worker writes them (Phase 6), a growing value means "
    "the worker has stopped and the data is stale."
)


def _utc(instant: datetime) -> datetime:
    """Serialised as ``...Z`` whatever the database session's time zone."""
    return instant.astimezone(UTC)


# -- request ------------------------------------------------------------------


class TrainListParams(BaseModel):
    """Query parameters for ``GET /trains``. Unknown parameters are rejected."""

    model_config = ConfigDict(extra="forbid")

    bbox: str | None = Field(
        default=None,
        description=(
            "Viewport as `west,south,east,north` in degrees. A train is included when the "
            "bounds of its current segment overlap the box, so trains about to enter the "
            "view are already present. Must not cross the antimeridian."
        ),
        examples=["5.87,47.27,15.04,55.06"],
    )
    zoom: float | None = Field(
        default=None,
        ge=0,
        le=24,
        allow_inf_nan=False,
        description=(
            "Map zoom level. Reserved for level of detail: once regional trains exist, "
            "their categories are omitted below a threshold zoom. No effect yet."
        ),
        examples=[6],
    )
    category: str | None = Field(
        default=None,
        description=(
            "Comma-separated categories, case-insensitive, e.g. `ICE,IC`. Unknown "
            "categories match nothing; `GET /stats` lists the ones the timetable has."
        ),
        examples=["ICE,IC,EC"],
    )

    @field_validator("bbox")
    @classmethod
    def _valid_bbox(cls, value: str | None) -> str | None:
        if value is not None:
            BoundingBox.parse(value)
        return value

    @field_validator("category")
    @classmethod
    def _valid_category(cls, value: str | None) -> str | None:
        if value is not None:
            parse_categories(value)
        return value

    def to_filter(self) -> TrainFilter:
        return TrainFilter(
            bbox=BoundingBox.parse(self.bbox) if self.bbox is not None else None,
            categories=parse_categories(self.category) if self.category is not None else None,
            zoom=self.zoom,
        )


# -- responses ----------------------------------------------------------------


class StationOut(BaseModel):
    station_id: str = Field(examples=["256012"])
    name: str = Field(examples=["Berlin Hbf"])
    lat: float
    lon: float

    @classmethod
    def from_station(cls, station: Station) -> "StationOut":
        return cls(
            station_id=station.station_id, name=station.name, lat=station.lat, lon=station.lon
        )


class SegmentOut(BaseModel):
    """Everything a client needs to place the train itself at any later instant."""

    from_station: StationOut
    to_station: StationOut
    departure_utc: datetime
    arrival_utc: datetime
    geometry_ref: str | None = Field(
        description=(
            "Names a curated corridor geometry. `null` means a straight line between "
            "`from_station` and `to_station`."
        ),
    )

    @classmethod
    def from_state(cls, state: SegmentState) -> "SegmentOut":
        return cls(
            from_station=StationOut.from_station(state.from_station),
            to_station=StationOut.from_station(state.to_station),
            departure_utc=_utc(state.departure_utc),
            arrival_utc=_utc(state.arrival_utc),
            geometry_ref=state.geometry_ref,
        )


class PositionOut(BaseModel):
    """Where a train is, as of the response's ``timestamp``."""

    status: TrainStatus
    position_source: PositionSource
    delay_seconds: int | None = Field(description="`null` until realtime data arrives.")
    lat: float
    lon: float
    bearing: float | None = Field(description="Degrees clockwise from north.")
    progress: float = Field(ge=0, le=1, description="Fraction of the segment elapsed.")
    segment: SegmentOut

    @classmethod
    def from_state(cls, state: SegmentState) -> "PositionOut":
        return cls.model_validate(_position_fields(state))


def _position_fields(state: SegmentState) -> dict[str, object]:
    return {
        "status": state.status,
        "position_source": state.position_source,
        "delay_seconds": state.delay_seconds,
        "lat": round(state.lat, POSITION_DECIMALS),
        "lon": round(state.lon, POSITION_DECIMALS),
        "bearing": round(state.bearing, 1) if state.bearing is not None else None,
        "progress": round(state.progress, 4),
        "segment": SegmentOut.from_state(state),
    }


class TrainOut(PositionOut):
    """A running train. ``(trip_id, service_date)`` identifies it."""

    trip_id: str = Field(examples=["1579104"])
    service_date: date
    label: str = Field(examples=["ICE 10"], description="Line, or bare category; no train number.")
    destination: str = Field(examples=["München Hbf"])
    category: str = Field(examples=["ICE"])
    operator: str = Field(examples=["DB Fernverkehr AG"])

    @classmethod
    def from_state(cls, state: SegmentState) -> "TrainOut":
        return cls.model_validate(
            {
                "trip_id": state.trip_id,
                "service_date": state.service_date,
                "label": state.label,
                "destination": state.destination,
                "category": state.category,
                "operator": state.operator,
                **_position_fields(state),
            }
        )


class SnapshotFields(BaseModel):
    timestamp: datetime = Field(description="The instant the positions were estimated for.")
    snapshot_age_seconds: int = Field(ge=0, description=SNAPSHOT_AGE_DESCRIPTION)

    @staticmethod
    def snapshot_fields(info: SnapshotInfo) -> dict[str, object]:
        return {"timestamp": _utc(info.generated_at), "snapshot_age_seconds": info.age_seconds}


class TrainListResponse(SnapshotFields):
    trains: list[TrainOut]

    @classmethod
    def from_list(cls, result: TrainList) -> "TrainListResponse":
        return cls.model_validate(
            {
                **cls.snapshot_fields(result.snapshot),
                "trains": [TrainOut.from_state(state) for state in result.trains],
            }
        )
