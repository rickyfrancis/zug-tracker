"""Database engine and session management."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns the async engine and hands out sessions.

    Used by both the API (through a FastAPI dependency) and the worker, which
    has no request lifecycle of its own.
    """

    #: An unreachable database must fail fast rather than hang a request.
    CONNECT_TIMEOUT_SECONDS = 5

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
            connect_args={"connect_timeout": self.CONNECT_TIMEOUT_SECONDS},
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    def session(self) -> AsyncSession:
        return self._session_factory()

    async def dispose(self) -> None:
        await self._engine.dispose()


async def session_scope(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session
