"""Alembic environment.

The database URL comes from application settings rather than alembic.ini, so
migrations use the same configuration as the running services.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.models.base import Base

# Importing the models package registers every table on Base.metadata, which is
# what autogenerate compares against. Phase 2 adds the GTFS models there.
import app.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # PostGIS manages these itself; autogenerate must not try to drop them.
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


#: Tables PostGIS creates and manages itself.
POSTGIS_TABLES = frozenset({"spatial_ref_sys"})


def _include_object(obj: object, name: str | None, type_: str, *_: object) -> bool:
    return not (type_ == "table" and name in POSTGIS_TABLES)


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
