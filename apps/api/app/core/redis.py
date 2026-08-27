"""Redis client factory.

Redis holds temporary realtime state only (worker heartbeat now, GTFS-Realtime
updates from Phase 6). Durable transport data lives in PostgreSQL.
"""

from redis.asyncio import Redis

#: Keep connection attempts short: an unreachable Redis must surface as a
#: failed health check, not as a hanging request.
DEFAULT_TIMEOUT_SECONDS = 2.0


def create_redis(url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> Redis:
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
    )
