"""Orchestrates one static GTFS import.

    download -> parse -> load -> expand -> activate -> prune

The load and the activation share **one** transaction, so an import either
becomes visible in its entirety or leaves no trace at all. There is no window in
which a dataset is active but half-loaded, and no window in which zero datasets
are active and the API serves an empty country. Pruning runs afterwards in its
own transaction: losing an old dataset is not a reason to roll back a good
import. See ADR-0002.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Database
from app.core.logging import get_logger
from app.providers.gtfs_static import DownloadedFeed, FeedMetadata, GTFSStaticProvider
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.gtfs_repository import GTFSRepository
from app.services.gtfs.expander import TripExpander
from app.services.gtfs.parser import parse_feed
from app.services.gtfs.rows import FeedContents
from app.services.gtfs.service_calendar import ServiceCalendar

logger = get_logger(__name__)

ImportStatus = Literal["imported", "unchanged", "skipped"]


class GTFSImportError(RuntimeError):
    """The feed cannot be imported as it stands."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    status: ImportStatus
    dataset_id: int | None = None
    version: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    pruned: list[int] = field(default_factory=list)

    @property
    def imported(self) -> bool:
        return self.status == "imported"


class GTFSImportService:
    """Imports the static feed under a new dataset and flips to it."""

    def __init__(
        self,
        database: Database,
        provider: GTFSStaticProvider,
        *,
        feed_id: str,
        retention: int,
    ) -> None:
        self._database = database
        self._provider = provider
        self._feed_id = feed_id
        self._retention = retention

    async def run(self, *, force: bool = False) -> ImportResult:
        known = None if force else await self._known_metadata()

        downloaded = await self._provider.download(known=known)
        if downloaded is None:
            return ImportResult(status="unchanged")

        with downloaded:
            if not force and await self._already_imported(downloaded.content_sha256):
                # The origin re-issued a validator but the bytes are identical.
                logger.info("gtfs.import.unchanged", sha256=downloaded.content_sha256[:12])
                return ImportResult(status="unchanged")

            result = await self._import(downloaded)

        if not result.imported:
            # Nothing was written, so there is nothing to supersede. A skipped
            # import also means another one is in flight, and pruning underneath
            # it is at best pointless.
            return result

        pruned = await self._prune()
        return ImportResult(
            status=result.status,
            dataset_id=result.dataset_id,
            version=result.version,
            counts=result.counts,
            pruned=pruned,
        )

    async def _import(self, downloaded: DownloadedFeed) -> ImportResult:
        feed = parse_feed(downloaded.open_text)
        timezone = _single_timezone(feed)
        calendar = ServiceCalendar.build(feed.calendars, feed.calendar_dates)

        bounds = calendar.bounds()
        if bounds is None:
            raise GTFSImportError("feed defines no service dates at all")
        valid_from, valid_to = bounds

        async with self._database.session() as session:
            if not await _claim_import_lock(session, self._feed_id):
                # The worker refreshes on a schedule and an operator can still
                # run `make import-data` by hand. Without this the two would
                # both load, and the loser would die on the single-active-dataset
                # index after doing all of the work.
                logger.info("gtfs.import.already_running", feed_id=self._feed_id)
                return ImportResult(status="skipped")

            datasets = DatasetRepository(session)
            gtfs = GTFSRepository(session)

            dataset = await datasets.create(
                feed_id=self._feed_id,
                metadata=downloaded.metadata,
                content_sha256=downloaded.content_sha256,
                timezone=timezone,
                valid_from=valid_from,
                valid_to=valid_to,
            )

            counts = {
                "agencies": await gtfs.load_agencies(dataset.id, feed.agencies),
                "routes": await gtfs.load_routes(dataset.id, feed.routes),
                "stops": await gtfs.load_stops(dataset.id, feed.stops),
                "calendars": await gtfs.load_calendars(dataset.id, feed.calendars),
                "calendar_dates": await gtfs.load_calendar_dates(dataset.id, feed.calendar_dates),
                "trips": await gtfs.load_trips(dataset.id, feed.trips),
                "stop_times": await gtfs.load_stop_times(dataset.id, feed.stop_times),
            }

            expander = TripExpander(ZoneInfo(timezone))
            instances, calls = await gtfs.load_instances(
                dataset.id, expander.expand(feed, calendar)
            )
            counts["trip_instances"] = instances
            counts["stop_time_instances"] = calls

            await datasets.activate(dataset.id, feed_id=self._feed_id)
            await session.commit()

            logger.info(
                "gtfs.import.completed",
                dataset_id=dataset.id,
                version=dataset.version,
                valid_from=str(valid_from),
                valid_to=str(valid_to),
                **counts,
            )
            return ImportResult(
                status="imported",
                dataset_id=dataset.id,
                version=dataset.version,
                counts=counts,
            )

    async def _known_metadata(self) -> FeedMetadata | None:
        async with self._database.session() as session:
            active = await DatasetRepository(session).active(self._feed_id)
            if active is None:
                return None
            return FeedMetadata(etag=active.etag, last_modified=active.last_modified)

    async def _already_imported(self, content_sha256: str) -> bool:
        async with self._database.session() as session:
            active = await DatasetRepository(session).active(self._feed_id)
            return active is not None and active.content_sha256 == content_sha256

    async def _prune(self) -> list[int]:
        async with self._database.session() as session:
            pruned = await DatasetRepository(session).prune(
                feed_id=self._feed_id, retain=self._retention
            )
            await session.commit()
            return pruned


async def _claim_import_lock(session: AsyncSession, feed_id: str) -> bool:
    """Take the per-feed import lock, or report that someone else holds it.

    Transaction-scoped, so it is released by the same commit or rollback that
    ends the load - there is no lock to leak if the process dies mid-import.
    Non-blocking on purpose: a second importer has nothing useful to wait for,
    since whatever the first one loads is exactly what the second would.
    """
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _lock_key(feed_id)}
    )
    return bool(result.scalar_one())


def _lock_key(feed_id: str) -> int:
    """A stable signed 64-bit lock key for one feed.

    Keyed per feed so that importing ``rv_free`` later does not queue behind
    ``fv_free``. Advisory lock keys share one namespace across the database,
    so a hash is safer than a hand-picked constant.
    """
    digest = hashlib.blake2b(feed_id.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _single_timezone(feed: FeedContents) -> str:
    """Every agency must agree on the timezone.

    All 13 agencies in fv_free are ``Europe/Berlin``. If that ever stops being
    true the service-day arithmetic becomes per-agency, which is a design change
    rather than a value to pick arbitrarily - so this fails loudly instead.
    """
    timezones = {agency.timezone for agency in feed.agencies}
    if len(timezones) != 1:
        raise GTFSImportError(f"expected exactly one agency timezone, found {sorted(timezones)}")
    return timezones.pop()
