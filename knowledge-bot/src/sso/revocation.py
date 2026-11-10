"""
revocation.py — Centralized Enterprise Session Revocation & Token Blacklist.

Provides immediate session termination upon employee offboarding, IdP backchannel logout,
or security incidents by tracking revoked users, tenants, and JWT tokens in Redis.
"""

import time
import logging
from typing import Optional
import redis
from src.config import REDIS_URL

logger = logging.getLogger(__name__)

# Singleton Redis client for revocation checks
_redis_client: Optional[redis.Redis] = None
# In-memory fallback if Redis is temporarily unreachable
_memory_revoked_users: dict = {}
_memory_revoked_tenants: dict = {}
_memory_revoked_tokens: set = set()
_memory_assertions: dict = {}


def get_redis_client() -> Optional[redis.Redis]:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2.0)
            _redis_client.ping()
        except Exception as e:
            logger.warning(f"SSO Revocation Redis connection notice (using memory fallback): {e}")
            _redis_client = None
    return _redis_client


def revoke_user_sessions(user_id: int, ttl_seconds: int = 86400) -> bool:
    """
    Revoke all active sessions for a user issued prior to now.
    Sets revocation timestamp in Redis with standard 24h TTL.
    """
    now_ts = int(time.time())
    _memory_revoked_users[user_id] = now_ts

    r = get_redis_client()
    if r:
        try:
            r.set(f"sso:revoked_user:{user_id}", str(now_ts), ex=ttl_seconds)
            logger.info(f"Revoked all sessions for user_id={user_id} at ts={now_ts}")
            return True
        except Exception as e:
            logger.error(f"Failed to record user revocation in Redis: {e}")
    return True


def revoke_tenant_sessions(tenant_id: int, ttl_seconds: int = 86400) -> bool:
    """Revoke all active sessions for an entire tenant (e.g. upon suspension)."""
    now_ts = int(time.time())
    _memory_revoked_tenants[tenant_id] = now_ts

    r = get_redis_client()
    if r:
        try:
            r.set(f"sso:revoked_tenant:{tenant_id}", str(now_ts), ex=ttl_seconds)
            logger.info(f"Revoked all sessions for tenant_id={tenant_id} at ts={now_ts}")
            return True
        except Exception as e:
            logger.error(f"Failed to record tenant revocation in Redis: {e}")
    return True


def blacklist_token(jti: str, expires_in_seconds: int = 86400, ttl_seconds: Optional[int] = None) -> bool:
    """Add a specific JWT ID (jti) to the token blacklist."""
    if not jti:
        return False
    _memory_revoked_tokens.add(jti)

    effective_ttl = ttl_seconds if ttl_seconds is not None else expires_in_seconds

    r = get_redis_client()
    if r:
        try:
            r.set(f"sso:blacklist_token:{jti}", "1", ex=effective_ttl)
            logger.info(f"Blacklisted token jti={jti} (ttl={effective_ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Failed to blacklist token in Redis: {e}")
    return True


def is_session_revoked(
    user_id: int,
    tenant_id: Optional[int] = None,
    token_iat: Optional[int] = None
) -> bool:
    """
    Checks if a user's session or their tenant's sessions have been revoked
    after the token's issued-at timestamp (iat).
    """
    token_time = token_iat or 0
    now = time.time()

    # 1. Check in-memory fallback
    if user_id in _memory_revoked_users and _memory_revoked_users[user_id] >= token_time:
        return True
    if tenant_id and tenant_id in _memory_revoked_tenants and _memory_revoked_tenants[tenant_id] >= token_time:
        return True

    # 2. Check Redis
    r = get_redis_client()
    if r:
        try:
            # Check user revocation
            user_rev = r.get(f"sso:revoked_user:{user_id}")
            if user_rev and int(user_rev) >= token_time:
                return True

            # Check tenant revocation
            if tenant_id:
                tenant_rev = r.get(f"sso:revoked_tenant:{tenant_id}")
                if tenant_rev and int(tenant_rev) >= token_time:
                    return True
        except Exception as e:
            logger.warning(f"Error checking session revocation in Redis: {e}")

    return False


def is_token_blacklisted(jti: str) -> bool:
    """Checks whether a token's jti is in the blacklist."""
    if not jti:
        return False
    if jti in _memory_revoked_tokens:
        return True

    r = get_redis_client()
    if r:
        try:
            return bool(r.exists(f"sso:blacklist_token:{jti}"))
        except Exception as e:
            logger.warning(f"Error checking token blacklist in Redis: {e}")
    return False


def check_and_record_assertion_id(assertion_id: str, ttl_seconds: int = 600) -> bool:
    """
    Checks if a SAML Assertion ID has already been processed to prevent replay attacks (CWE-294).
    Returns True if the assertion is fresh and was recorded; False if it was already used.
    """
    if not assertion_id:
        return True

    r = get_redis_client()
    if r:
        try:
            res = r.set(f"sso:saml:assertion:{assertion_id}", "1", ex=ttl_seconds, nx=True)
            return bool(res)
        except Exception as e:
            logger.error(f"Redis assertion replay check error: {e}")

    # In-memory fallback
    now = time.time()
    expired = [k for k, exp in _memory_assertions.items() if exp < now]
    for k in expired:
        _memory_assertions.pop(k, None)

    if assertion_id in _memory_assertions:
        return False

    _memory_assertions[assertion_id] = now + ttl_seconds
    return True

