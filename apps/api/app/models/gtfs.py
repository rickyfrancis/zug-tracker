"""ORM models for the static GTFS feed and its materialized daily expansion.

Every table below is scoped to a :class:`Dataset` and keyed by
``(dataset_id, <gtfs id>)``. GTFS ids are only unique *within* a feed release,
so making ``dataset_id`` part of every primary and foreign key is what stops a
trip from one import joining a stop time from another. See ADR-0002.

These models exist for *reading*. The importer writes through
``repositories/gtfs_repository.py``, which uses Core inserts and ``COPY``.
"""

from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

#: GTFS identifiers are opaque strings, not numbers, even when they look like
#: integers. Nothing may depend on their numeric value.
GTFS_ID = String(64)


class Dataset(Base):
    """One import of one feed.

    The only table with a surrogate key: everything else hangs off ``id``.
    Exactly one row may be active at a time, enforced by a partial unique index
    rather than by convention.
    """

    __tablename__ = "dataset"
    __table_args__ = (
        Index(
            "uq_dataset_single_active",
            "is_active",
            unique=True,
            postgresql_where="is_active",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    #: Which feed this came from. ``fv_free`` today; ``rv_free`` (regional) is
    #: an import under a second feed_id rather than a migration.
    feed_id: Mapped[str] = mapped_column(String(32))

    #: Derived, because ``feed_info.feed_version`` is the constant string
    #: "latest-fv-free" and identifies nothing.
    version: Mapped[str] = mapped_column(String(64))

    etag: Mapped[str | None] = mapped_column(String(128))
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str] = mapped_column(String(64))

    #: The feed's timezone. All 13 agencies in fv_free are Europe/Berlin; the
    #: importer refuses a feed that ships more than one.
    timezone: Mapped[str] = mapped_column(String(64))

    #: Derived from calendar/calendar_dates bounds. feed_info.txt has no dates.
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)

    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


def _dataset_fk() -> Mapped[int]:
    return mapped_column(
        BigInteger,
        ForeignKey("dataset.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Agency(Base):
    __tablename__ = "agency"

    dataset_id: Mapped[int] = _dataset_fk()
    agency_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)

    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64))
    lang: Mapped[str | None] = mapped_column(String(8))


class Route(Base):
    """A line, not a train.

    ``short_name`` and ``long_name`` are kept verbatim so the UI can render
    whatever the feed says. ``category`` and ``line`` are the parsed halves:
    fv_free ships ``"ICE 10"`` for most routes but a bare ``"ICE"`` for 953
    trips (17%), so ``line`` is nullable by necessity. ``long_name`` is empty
    on every route in the current feed and is stored against a feed that may
    one day populate it.
    """

    __tablename__ = "route"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "agency_id"],
            ["agency.dataset_id", "agency.agency_id"],
            ondelete="CASCADE",
        ),
    )

    dataset_id: Mapped[int] = _dataset_fk()
    route_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)

    agency_id: Mapped[str] = mapped_column(GTFS_ID)
    short_name: Mapped[str] = mapped_column(Text)
    long_name: Mapped[str | None] = mapped_column(Text)

    #: ICE / IC / EC / ECE / RJ / EN today; RE / RB / S when regional arrives.
    #: A first-class filterable column, not something inferred from feed_id.
    category: Mapped[str] = mapped_column(String(8), index=True)
    line: Mapped[str | None] = mapped_column(String(16))

    route_type: Mapped[int] = mapped_column(SmallInteger)


class Stop(Base):
    """A platform or a station.

    ``stop_times`` reference platform-level stops, every one of which has a
    ``parent_station``. Display and geometry resolve to the parent, or segments
    between two platforms of one station come out near-zero length.
    """

    __tablename__ = "stop"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "parent_station_id"],
            ["stop.dataset_id", "stop.stop_id"],
            ondelete="CASCADE",
        ),
        Index("ix_stop_point", "point", postgresql_using="gist"),
    )

    dataset_id: Mapped[int] = _dataset_fk()
    stop_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)

    name: Mapped[str] = mapped_column(Text)
    parent_station_id: Mapped[str | None] = mapped_column(GTFS_ID)

    #: What to show for a station: ``Berlin Hbf`` rather than the parent's own
    #: ``S+U Berlin Hauptbahnhof``. Chosen at import from the platform names
    #: (``services/gtfs/station_names.py``); ``NULL`` on platforms, and on
    #: datasets imported before the column existed.
    display_name: Mapped[str | None] = mapped_column(Text)

    #: Kept alongside ``point`` because the position engine reads plain floats
    #: and has no reason to round-trip through PostGIS.
    lat: Mapped[float] = mapped_column()
    lon: Mapped[float] = mapped_column()

    #: 1 = station, 0/NULL = platform. Stored as given, defaulted to 0.
    location_type: Mapped[int] = mapped_column(SmallInteger, default=0)
    platform_code: Mapped[str | None] = mapped_column(Text)

    #: Written by the importer, not generated, so the migration carries no
    #: dependency on the geometry->geography cast being IMMUTABLE.
    #:
    #: ``spatial_index=False`` turns off GeoAlchemy2's implicit index-creation
    #: hook; the GiST index is declared in ``__table_args__`` above instead, so
    #: it is visible in the model and emitted exactly once by autogenerate.
    point: Mapped[str] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )

    parent: Mapped["Stop | None"] = relationship(remote_side="[Stop.dataset_id, Stop.stop_id]")


class Calendar(Base):
    """Weekly service pattern. Not every service has one - see Calendar Date."""

    __tablename__ = "calendar"

    dataset_id: Mapped[int] = _dataset_fk()
    service_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)

    monday: Mapped[bool] = mapped_column(Boolean)
    tuesday: Mapped[bool] = mapped_column(Boolean)
    wednesday: Mapped[bool] = mapped_column(Boolean)
    thursday: Mapped[bool] = mapped_column(Boolean)
    friday: Mapped[bool] = mapped_column(Boolean)
    saturday: Mapped[bool] = mapped_column(Boolean)
    sunday: Mapped[bool] = mapped_column(Boolean)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)


class CalendarDate(Base):
    """A single-date addition (1) or removal (2).

    60 of the feed's service_ids appear *only* here, with no calendar.txt row
    at all, so expansion must union both files rather than walk calendar and
    patch it.
    """

    __tablename__ = "calendar_date"

    dataset_id: Mapped[int] = _dataset_fk()
    service_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)

    exception_type: Mapped[int] = mapped_column(SmallInteger)


class Trip(Base):
    """A scheduled journey pattern, undated.

    ``trips.txt`` in this feed has exactly three columns: route_id, service_id,
    trip_id. There is no ``trip_short_name`` and therefore no train number.
    """

    __tablename__ = "trip"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "route_id"],
            ["route.dataset_id", "route.route_id"],
            ondelete="CASCADE",
        ),
    )

    dataset_id: Mapped[int] = _dataset_fk()
    trip_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)

    route_id: Mapped[str] = mapped_column(GTFS_ID)

    #: Deliberately unconstrained: a service_id may exist only in
    #: calendar_dates.txt, so there is no single table to point at.
    service_id: Mapped[str] = mapped_column(GTFS_ID, index=True)


class StopTime(Base):
    """One call, as offsets from the service day start.

    Times are seconds, not ``TIME``: GTFS hours run past midnight and reach 35
    in this feed, which no time type accepts.
    """

    __tablename__ = "stop_time"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "trip_id"],
            ["trip.dataset_id", "trip.trip_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "stop_id"],
            ["stop.dataset_id", "stop.stop_id"],
            ondelete="CASCADE",
        ),
    )

    dataset_id: Mapped[int] = _dataset_fk()
    trip_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)
    #: Starts at 0 in this feed, not 1.
    stop_sequence: Mapped[int] = mapped_column(Integer, primary_key=True)

    stop_id: Mapped[str] = mapped_column(GTFS_ID)
    arrival_seconds: Mapped[int] = mapped_column(Integer)
    departure_seconds: Mapped[int] = mapped_column(Integer)

    #: 100% populated, and the only destination information the feed carries.
    stop_headsign: Mapped[str | None] = mapped_column(Text)
    pickup_type: Mapped[int | None] = mapped_column(SmallInteger)
    drop_off_type: Mapped[int | None] = mapped_column(SmallInteger)


class TripInstance(Base):
    """A trip on a concrete service date, with absolute UTC bounds.

    Midnight crossings (16% of trips) and DST are resolved once here, at
    expansion time, so the worker's hot loop is an indexed range query rather
    than per-tick timezone arithmetic. See ADR-0003.
    """

    __tablename__ = "trip_instance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "trip_id"],
            ["trip.dataset_id", "trip.trip_id"],
            ondelete="CASCADE",
        ),
        Index("ix_trip_instance_starts_at", "dataset_id", "starts_at_utc"),
        Index("ix_trip_instance_ends_at", "dataset_id", "ends_at_utc"),
    )

    dataset_id: Mapped[int] = _dataset_fk()
    service_date: Mapped[date] = mapped_column(Date, primary_key=True)
    trip_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)

    #: Denormalized so category filtering is a single-table predicate. Immutable
    #: within a dataset, so there is nothing to keep in step.
    route_id: Mapped[str] = mapped_column(GTFS_ID)

    starts_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StopTimeInstance(Base):
    """One call on one service date, as an absolute UTC timestamp."""

    __tablename__ = "stop_time_instance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "service_date", "trip_id"],
            [
                "trip_instance.dataset_id",
                "trip_instance.service_date",
                "trip_instance.trip_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "stop_id"],
            ["stop.dataset_id", "stop.stop_id"],
            ondelete="CASCADE",
        ),
    )

    dataset_id: Mapped[int] = _dataset_fk()
    service_date: Mapped[date] = mapped_column(Date, primary_key=True)
    trip_id: Mapped[str] = mapped_column(GTFS_ID, primary_key=True)
    stop_sequence: Mapped[int] = mapped_column(Integer, primary_key=True)

    stop_id: Mapped[str] = mapped_column(GTFS_ID)
    arrival_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    departure_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
