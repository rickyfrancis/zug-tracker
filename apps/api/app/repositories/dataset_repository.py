"""The dataset lifecycle: create, flip, prune, resolve.

GTFS ids are not stable across feed releases, so upserting by id accumulates
orphans forever and truncate-and-reload exposes a window where the API serves an
empty country. Instead every import writes under a fresh :class:`Dataset` and a
pointer flips once the load has completed. See ADR-0002.
"""

from datetime import UTC, date, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.gtfs import Dataset
from app.providers.gtfs_static import FeedMetadata

logger = get_logger(__name__)


class DatasetRepository:
    """Reads and writes :class:`Dataset` rows.

    The "at most one active dataset" rule is enforced by a partial unique index
    in the schema, not by the code here - this class can only ever be the
    second line of defence.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def active(self, feed_id: str) -> Dataset | None:
        """The dataset currently being served, if any."""
        result = await self._session.execute(
            select(Dataset).where(Dataset.feed_id == feed_id, Dataset.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get(self, dataset_id: int) -> Dataset | None:
        return await self._session.get(Dataset, dataset_id)

    async def create(
        self,
        *,
        feed_id: str,
        metadata: FeedMetadata,
        content_sha256: str,
        timezone: str,
        valid_from: date,
        valid_to: date,
    ) -> Dataset:
        """Stage a new, inactive dataset for a load to write into."""
        dataset = Dataset(
            feed_id=feed_id,
            version=build_version(metadata.last_modified, content_sha256),
            etag=metadata.etag,
            last_modified=metadata.last_modified,
            content_sha256=content_sha256,
            timezone=timezone,
            valid_from=valid_from,
            valid_to=valid_to,
            imported_at=datetime.now(UTC),
            is_active=False,
        )
        self._session.add(dataset)
        await self._session.flush()
        logger.info("dataset.created", dataset_id=dataset.id, version=dataset.version)
        return dataset

    async def activate(self, dataset_id: int, *, feed_id: str) -> None:
        """Flip the pointer.

        Both statements run in the caller's transaction: there must be no
        instant at which zero datasets are active, or the API serves an empty
        map for as long as the gap lasts.
        """
        await self._session.execute(
            update(Dataset)
            .where(Dataset.feed_id == feed_id, Dataset.is_active.is_(True))
            .values(is_active=False)
        )
        await self._session.execute(
            update(Dataset).where(Dataset.id == dataset_id).values(is_active=True)
        )
        logger.info("dataset.activated", dataset_id=dataset_id)

    async def prune(self, *, feed_id: str, retain: int) -> list[int]:
        """Delete superseded datasets, keeping the newest ``retain`` of them.

        Retaining one makes a bad import reversible by flipping a boolean, and
        keeps rows from vanishing under a reader that resolved the previous
        dataset id a moment ago. Rows cascade from ``dataset``.
        """
        superseded = await self._session.execute(
            select(Dataset.id)
            .where(Dataset.feed_id == feed_id, Dataset.is_active.is_(False))
            .order_by(Dataset.imported_at.desc(), Dataset.id.desc())
            .offset(retain)
        )
        doomed = list(superseded.scalars())
        if not doomed:
            return []

        await self._session.execute(delete(Dataset).where(Dataset.id.in_(doomed)))
        logger.info("dataset.pruned", dataset_ids=doomed, retained=retain)
        return doomed

    async def discard(self, dataset_id: int) -> None:
        """Remove a dataset whose load failed part-way through."""
        await self._session.execute(delete(Dataset).where(Dataset.id == dataset_id))
        logger.info("dataset.discarded", dataset_id=dataset_id)


def build_version(last_modified: datetime | None, content_sha256: str) -> str:
    """Derive a human-readable version string.

    ``feed_info.feed_version`` cannot be used: it is the constant string
    ``latest-fv-free`` and identifies nothing. The origin's ``Last-Modified``
    dates the release; the hash distinguishes two releases sharing a timestamp.
    """
    stamp = (last_modified or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{content_sha256[:8]}"
