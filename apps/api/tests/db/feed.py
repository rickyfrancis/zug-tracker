"""A miniature feed, and a provider that serves it, for tests needing a database.

Shared by the import tests and by the position engine's tests, so the trains
being positioned are the ones the importer is proven to load.
"""

import hashlib
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.db import Database
from app.providers.gtfs_static import DownloadedFeed, FeedMetadata
from app.services.gtfs.import_service import GTFSImportService

FEED_ID = "test_fv"

# A miniature feed with the shapes that matter: a non-standard routes.txt column
# order, a bare route_short_name, a platform under a parent station, a service
# defined only in calendar_dates.txt, and a trip crossing midnight. Station and
# platform names are fv_free's real ones, so the parent's own name is never the
# one to show, and a platform and a headsign carry a track range.
FEED = {
    "agency.txt": (
        "agency_id,agency_name,agency_url,agency_timezone,agency_lang\n"
        "8,DB Fernverkehr AG,https://www.bahn.de,Europe/Berlin,de\n"
    ),
    "routes.txt": (
        "route_long_name,route_short_name,agency_id,route_type,route_id\n"
        ",ICE 10,8,2,77\n"
        ",ICE,8,2,18\n"
    ),
    "stops.txt": (
        "stop_name,parent_station,stop_id,stop_lat,stop_lon,location_type,platform_code\n"
        "S+U Berlin Hauptbahnhof,,900003201,52.525589,13.369548,1,\n"
        "Berlin Hbf,900003201,8098160,52.525589,13.369548,,1\n"
        '"München, Hauptbahnhof",,800000261,48.140232,11.558335,1,\n'
        "München Hbf Gl.5-10,800000261,8000261,48.140232,11.558335,,5\n"
    ),
    "calendar.txt": (
        "monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date,service_id\n"
        "1,1,1,1,1,0,0,20260824,20260828,weekday\n"
    ),
    # 'oneoff' has no calendar.txt row at all.
    "calendar_dates.txt": "service_id,exception_type,date\noneoff,1,20260829\nweekday,2,20260826\n",
    "trips.txt": "route_id,service_id,trip_id\n77,weekday,day-trip\n18,oneoff,night-trip\n",
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,"
        "stop_headsign,pickup_type,drop_off_type\n"
        "day-trip,08:00:00,08:05:00,8098160,0,München Hbf Gl.5-10,,\n"
        "day-trip,12:00:00,12:00:00,8000261,1,München Hbf,,\n"
        "night-trip,23:00:00,23:05:00,8098160,0,München Hbf,,\n"
        "night-trip,27:54:00,27:54:00,8000261,1,München Hbf,,\n"
    ),
}


class StubProvider:
    """Serves a synthetic archive instead of the live feed.

    Mirrors ``GTFSStaticProvider``'s contract: ``None`` means "not modified".
    """

    def __init__(self, files: dict[str, str], *, etag: str = '"v1"') -> None:
        self.files = dict(files)
        self.etag = etag
        self.calls = 0

    async def download(self, *, known: FeedMetadata | None = None) -> DownloadedFeed | None:
        self.calls += 1
        if known is not None and known.etag == self.etag:
            return None
        return _archive(self.files, etag=self.etag)


def _archive(files: dict[str, str], *, etag: str) -> DownloadedFeed:
    path = Path(tempfile.mkstemp(prefix="gtfs-test-", suffix=".zip")[1])
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return DownloadedFeed(
        path=path,
        content_sha256=digest,
        metadata=FeedMetadata(etag=etag, last_modified=datetime(2026, 8, 22, tzinfo=UTC)),
        archive=zipfile.ZipFile(path),
    )


def service(database: Database, provider: object, *, retention: int = 1) -> GTFSImportService:
    return GTFSImportService(
        database,
        provider,  # type: ignore[arg-type]
        feed_id=FEED_ID,
        retention=retention,
    )
