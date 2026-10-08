"""Command-line entrypoints for data management.

Run inside the worker service, which already carries the GTFS environment:

    docker compose run --rm worker python -m app.cli import-data

The running worker already refreshes the feed daily, so these commands are for
forcing the issue: a first import on a fresh database, or a re-import after
changing something about how the feed is parsed. Both paths share one
``GTFSImportService``, and an import taken by the worker meanwhile is detected
rather than duplicated.

``positions`` prints what the position engine makes of the active timetable,
at any instant - the quickest way to check it against a departure board.

``openapi`` prints the API's OpenAPI schema without starting a server or
touching the database; the web app generates its TypeScript types from it.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.logging import configure_logging, get_logger
from app.providers.gtfs_static import GTFSStaticProvider
from app.repositories.dataset_repository import DatasetRepository
from app.services.gtfs.import_service import GTFSImportService
from app.services.positions.position_service import PositionService

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    import_data = subcommands.add_parser(
        "import-data",
        help="Import the static GTFS feed, skipping the download if unchanged",
    )
    import_data.add_argument(
        "--force",
        action="store_true",
        help="Re-import even when the feed is byte-identical to the active dataset",
    )

    subcommands.add_parser(
        "prune",
        help="Delete superseded datasets beyond the retention limit",
    )

    positions = subcommands.add_parser(
        "positions",
        help="Print the estimated position of every running train",
    )
    positions.add_argument(
        "--at",
        type=parse_instant,
        default=None,
        metavar="ISO8601",
        help="Instant to estimate for, e.g. 2026-10-06T14:30+02:00; "
        "no offset means UTC (default: now)",
    )
    subcommands.add_parser(
        "openapi",
        help="Print the API's OpenAPI schema as JSON",
    )
    return parser


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant, reading one without an offset as UTC."""
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 instant: {value!r}") from exc
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)


async def import_data(settings: Settings, *, force: bool) -> int:
    database = Database(settings.database_url)
    try:
        service = GTFSImportService(
            database,
            GTFSStaticProvider(settings.gtfs_static_url),
            feed_id=settings.gtfs_feed_id,
            retention=settings.gtfs_dataset_retention,
        )
        result = await service.run(force=force)
    finally:
        await database.dispose()

    if not result.imported:
        logger.info("cli.import.skipped", status=result.status, feed_id=settings.gtfs_feed_id)
        return EXIT_OK

    logger.info(
        "cli.import.done",
        dataset_id=result.dataset_id,
        version=result.version,
        pruned=result.pruned,
        **result.counts,
    )
    return EXIT_OK


async def prune(settings: Settings) -> int:
    database = Database(settings.database_url)
    try:
        async with database.session() as session:
            pruned = await DatasetRepository(session).prune(
                feed_id=settings.gtfs_feed_id, retain=settings.gtfs_dataset_retention
            )
            await session.commit()
    finally:
        await database.dispose()

    logger.info("cli.prune.done", pruned=pruned, retained=settings.gtfs_dataset_retention)
    return EXIT_OK


async def positions(settings: Settings, *, at: datetime | None) -> int:
    now = at or datetime.now(UTC)
    database = Database(settings.database_url)
    try:
        async with database.session() as session:
            states = await PositionService(session, feed_id=settings.gtfs_feed_id).positions_at(now)
    finally:
        await database.dispose()

    print(f"{len(states)} trains running at {now.isoformat()}")
    for state in sorted(states, key=lambda state: state.display_name):
        segment = f"{state.from_station.name} -> {state.to_station.name}"
        bearing = "  - " if state.bearing is None else f"{state.bearing:3.0f}°"
        print(
            f"{state.display_name:<42} {state.status:<7} {state.progress:4.0%}  "
            f"{state.lat:8.4f} {state.lon:8.4f} {bearing}  {segment}"
        )
    return EXIT_OK


async def openapi() -> int:
    # Imported here: building the app is only needed for this command.
    from app.main import create_app

    # Sorted and indented so the generated web types diff cleanly.
    print(json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    commands: dict[str, Callable[[], Coroutine[Any, Any, int]]] = {
        "import-data": lambda: import_data(settings, force=arguments.force),
        "prune": lambda: prune(settings),
        "positions": lambda: positions(settings, at=arguments.at),
        "openapi": openapi,
    }

    try:
        return asyncio.run(commands[arguments.command]())
    except Exception as exc:  # noqa: BLE001 - a CLI reports failure, it does not traceback
        logger.error("cli.failed", command=arguments.command, error=str(exc))
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
