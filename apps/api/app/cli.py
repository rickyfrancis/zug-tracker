"""Command-line entrypoints for data management.

Run inside the worker service, which already carries the GTFS environment:

    docker compose run --rm worker python -m app.cli import-data

The running worker already refreshes the feed daily, so these commands are for
forcing the issue: a first import on a fresh database, or a re-import after
changing something about how the feed is parsed. Both paths share one
``GTFSImportService``, and an import taken by the worker meanwhile is detected
rather than duplicated.
"""

import argparse
import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.logging import configure_logging, get_logger
from app.providers.gtfs_static import GTFSStaticProvider
from app.repositories.dataset_repository import DatasetRepository
from app.services.gtfs.import_service import GTFSImportService

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
    return parser


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


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    commands: dict[str, Callable[[], Coroutine[Any, Any, int]]] = {
        "import-data": lambda: import_data(settings, force=arguments.force),
        "prune": lambda: prune(settings),
    }

    try:
        return asyncio.run(commands[arguments.command]())
    except Exception as exc:  # noqa: BLE001 - a CLI reports failure, it does not traceback
        logger.error("cli.failed", command=arguments.command, error=str(exc))
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
