"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis

logger = get_logger(__name__)

DESCRIPTION = """
Live tracking of German long-distance trains.

Positions are derived from GTFS schedules and, where available, GTFS-Realtime
updates - each train reports whether its position is `realtime` or `scheduled`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = Database(settings.database_url)
        app.state.redis = create_redis(settings.redis_url)
        logger.info("api.startup", environment=settings.environment)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.database.dispose()
            logger.info("api.shutdown")

    app = FastAPI(
        title="zug-tracker API",
        description=DESCRIPTION,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    # Available before startup so request handlers and tests share one config.
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()
