"""Best-effort synchronous Redis access for request-path counters.

The tracking hub uses redis.asyncio; services that run synchronously (OTP
verification, dispatch bookkeeping) mirror their counters here. When
REDIS_URL is unset or Redis is unreachable, every call degrades to a no-op —
the database columns remain the durable source of truth."""

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("redis.sync")

_client = None
_initialized = False


def get_redis_sync():
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    if not settings.redis_url:
        return None
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        client.ping()
        _client = client
        logger.info("redis_sync_connected url=%s", settings.redis_url)
    except Exception:
        logger.warning("redis_sync_unavailable; database-only counters in effect")
        _client = None
    return _client


def incr_with_ttl(key: str, ttl_seconds: int) -> int | None:
    client = get_redis_sync()
    if client is None:
        return None
    try:
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        count, _ = pipe.execute()
        return int(count)
    except Exception:
        logger.warning("redis_sync_incr_failed key=%s", key)
        return None


def delete_key(key: str) -> None:
    client = get_redis_sync()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        logger.warning("redis_sync_delete_failed key=%s", key)
