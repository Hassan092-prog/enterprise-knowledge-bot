"""
cache.py — Lightweight cross-process Redis cache versioning helpers.

Allows Celery workers and FastAPI instances to invalidate per-tenant
in-memory caches (BM25 indices, NetworkX graphs) cleanly without coupling
retrieval/graph modules to SSO or Celery internals.
"""
import os
import time
from typing import Optional

from src.logger import get_logger

logger = get_logger(__name__)

_redis_client = None
_redis_last_fail: float = 0.0
_REDIS_RETRY_COOLDOWN = 30.0


def _get_redis_client():
    """Return a cached Redis client with fast timeout and cooldown backoff."""
    global _redis_client, _redis_last_fail
    if _redis_client is not None:
        return _redis_client

    now = time.monotonic()
    if (now - _redis_last_fail) < _REDIS_RETRY_COOLDOWN:
        return None

    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as exc:
        _redis_last_fail = now
        logger.debug("Redis cache versioning unavailable (%s); falling back to local RAM.", exc)
        return None


def get_cache_version(key: str) -> Optional[str]:
    """Return current cache version string ('0' if unset), or None if Redis unavailable."""
    global _redis_client, _redis_last_fail
    client = _get_redis_client()
    if client is None:
        return None
    try:
        val = client.get(key)
        return str(val) if val is not None else "0"
    except Exception:
        _redis_client = None
        _redis_last_fail = time.monotonic()
        return None


def bump_cache_version(key: str) -> Optional[str]:
    """Atomically increment cache version in Redis and return new version string."""
    global _redis_client, _redis_last_fail
    client = _get_redis_client()
    if client is None:
        return None
    try:
        val = client.incr(key)
        return str(val)
    except Exception:
        _redis_client = None
        _redis_last_fail = time.monotonic()
        return None

