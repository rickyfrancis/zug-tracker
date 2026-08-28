"""Fixtures for tests that need a real PostGIS database.

Composite foreign keys, the partial unique index, ``COPY`` and the atomic swap
have no meaningful fake: each of them is a promise the database makes, and a
stub would only assert that the stub keeps it. The container runs the same
image as ``docker-compose.yml``, and migrations are applied with Alembic so the
migration itself is under test too.
"""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.core.config import get_settings
from app.core.db import Database

pytestmark = pytest.mark.db

API_ROOT = Path(__file__).resolve().parents[2]

#: The same image docker-compose.yml runs, so tests exercise the real PostGIS.
POSTGRES_IMAGE = "postgis/postgis:18-3.6"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        _migrate(url)
        yield url


def _migrate(url: str) -> None:
    """Apply the real migrations, so the migration itself is under test.

    ``alembic/env.py`` deliberately takes its URL from application settings
    rather than alembic.ini, and ``get_settings`` is cached - so pointing it at
    the container means setting the environment *and* dropping the cache.
    """
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture
async def database(postgres_url: str) -> AsyncIterator[Database]:
    """A clean database per test.

    Truncating ``dataset`` is enough: every other table cascades from it.
    """
    db = Database(postgres_url)
    async with db.session() as session:
        await session.execute(text("TRUNCATE dataset RESTART IDENTITY CASCADE"))
        await session.commit()
    try:
        yield db
    finally:
        await db.dispose()
