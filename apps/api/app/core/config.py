"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "production", "test"]


class Settings(BaseSettings):
    """Runtime configuration shared by the API and the worker.

    Every value has a development-friendly default so the app can boot without a
    ``.env`` file; deployments override them through environment variables.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Environment = "development"
    log_level: str = "INFO"

    # psycopg (v3) serves both the async engine and the synchronous Alembic
    # engine, so a single URL scheme works everywhere.
    database_url: str = "postgresql+psycopg://zug:zug@localhost:5432/zug"
    redis_url: str = "redis://localhost:6379/0"

    # Comma-separated so it stays readable in docker-compose and Coolify.
    cors_origins: str = "http://localhost:3000"

    worker_interval_seconds: float = 10.0
    worker_heartbeat_key: str = "zug:worker:heartbeat"

    gtfs_static_url: str = ""
    # Populated in Phase 6 (realtime polling).
    gtfs_realtime_url: str = ""

    #: Identifies the feed a dataset came from. Adding regional trains later is
    #: an import under a second feed_id, not a migration.
    gtfs_feed_id: str = "fv_free"

    #: Superseded datasets kept after an import. One makes a bad import
    #: reversible and keeps rows from vanishing under an in-flight reader.
    gtfs_dataset_retention: int = 1

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def heartbeat_ttl_seconds(self) -> int:
        """How long a worker heartbeat stays valid before it is considered stale."""
        return max(int(self.worker_interval_seconds * 3), 5)


@lru_cache
def get_settings() -> Settings:
    return Settings()
