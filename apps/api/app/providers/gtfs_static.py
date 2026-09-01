"""Fetch the static GTFS archive.

Deliberately *not* behind a shared ``TransitDataProvider`` base class. The
static feed returns seven CSV tables from a zip; the realtime feed (Phase 6)
returns protobuf entities at a completely different cadence. They share nothing
but "bytes over HTTP", and no caller ever holds one without knowing which it is.
See ADR-0004.

The feed publishes both ``ETag`` and ``Last-Modified``, so a conditional GET
avoids downloading 415 KB that has not changed. The content hash is still the
authoritative answer to "did anything change", because origin caches lie.
"""

import hashlib
import io
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Self

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

#: The archive is ~415 KB; a slow origin should fail rather than hang a job.
DOWNLOAD_TIMEOUT_SECONDS = 60.0

#: Refuse anything wildly outside the expected size rather than trying to unzip
#: an error page.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class GTFSDownloadError(RuntimeError):
    """The archive could not be fetched or is not a usable zip."""


@dataclass(frozen=True, slots=True)
class FeedMetadata:
    """What the origin says about the current archive, before downloading it."""

    etag: str | None
    last_modified: datetime | None


@dataclass(frozen=True, slots=True)
class DownloadedFeed:
    """A staged archive plus the identity of what was fetched.

    Used as a context manager; the temporary file is removed on exit. The zip
    is not kept: it is re-fetchable, and ``content_sha256`` is the durable
    record of what was imported.
    """

    path: Path
    content_sha256: str
    metadata: FeedMetadata
    archive: zipfile.ZipFile

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.archive.close()
        self.path.unlink(missing_ok=True)

    @contextmanager
    def open_text(self, name: str) -> Iterator[IO[str]]:
        """Open one file inside the archive as UTF-8 text."""
        try:
            handle = self.archive.open(name)
        except KeyError as exc:
            raise GTFSDownloadError(f"{name} is missing from the archive") from exc
        with handle as binary:
            # GTFS mandates UTF-8; a BOM is common enough to strip explicitly.
            yield io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")


class GTFSStaticProvider:
    """Downloads and stages the static GTFS archive."""

    def __init__(self, url: str, *, timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS) -> None:
        if not url:
            raise GTFSDownloadError("GTFS_STATIC_URL is not configured")
        self._url = url
        self._timeout = timeout_seconds

    async def download(self, *, known: FeedMetadata | None = None) -> DownloadedFeed | None:
        """Download the archive, or return ``None`` if the origin answers 304.

        ``known`` carries the previous import's validators; passing it turns
        the request into a conditional GET.
        """
        headers = _conditional_headers(known)

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(self._url, headers=headers)

            if response.status_code == httpx.codes.NOT_MODIFIED:
                logger.info("gtfs.static.not_modified", url=self._url)
                return None

            response.raise_for_status()
            body = response.content

        if len(body) > MAX_ARCHIVE_BYTES:
            raise GTFSDownloadError(f"archive is {len(body)} bytes, refusing to unzip")

        digest = hashlib.sha256(body).hexdigest()
        path = Path(tempfile.mkstemp(prefix="gtfs-", suffix=".zip")[1])
        path.write_bytes(body)

        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            path.unlink(missing_ok=True)
            raise GTFSDownloadError(f"{self._url} did not return a zip archive") from exc

        logger.info(
            "gtfs.static.downloaded",
            url=self._url,
            bytes=len(body),
            sha256=digest[:12],
            members=len(archive.namelist()),
        )
        return DownloadedFeed(
            path=path,
            content_sha256=digest,
            metadata=_metadata_from(response),
            archive=archive,
        )


def _conditional_headers(known: FeedMetadata | None) -> dict[str, str]:
    """Prefer ``ETag``; fall back to ``Last-Modified`` when the origin omits it."""
    if known is None:
        return {}
    if known.etag:
        return {"If-None-Match": known.etag}
    if known.last_modified:
        return {"If-Modified-Since": _to_http_date(known.last_modified)}
    return {}


def _metadata_from(response: httpx.Response) -> FeedMetadata:
    raw_modified = response.headers.get("last-modified")
    last_modified = None
    if raw_modified:
        try:
            last_modified = parsedate_to_datetime(raw_modified).astimezone(UTC)
        except (TypeError, ValueError):
            logger.warning("gtfs.static.unparseable_last_modified", value=raw_modified)
    return FeedMetadata(etag=response.headers.get("etag"), last_modified=last_modified)


def _to_http_date(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
