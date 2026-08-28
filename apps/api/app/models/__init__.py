"""ORM models.

Importing the model modules here registers their tables on ``Base.metadata``,
which is what Alembic's autogenerate compares the database against.
"""

from app.models.base import Base
from app.models.gtfs import (
    Agency,
    Calendar,
    CalendarDate,
    Dataset,
    Route,
    Stop,
    StopTime,
    StopTimeInstance,
    Trip,
    TripInstance,
)

__all__ = [
    "Agency",
    "Base",
    "Calendar",
    "CalendarDate",
    "Dataset",
    "Route",
    "Stop",
    "StopTime",
    "StopTimeInstance",
    "Trip",
    "TripInstance",
]
