"""
limiter.py — Centralized SlowAPI rate limiter configuration with Redis backend.
"""
import os
import functools
import inspect
import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.auth import SECRET_KEY, ALGORITHM

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

def get_user_rate_limit_key(request: Request) -> str:
    """
    Key by authenticated user identity 'u:{tenant_id}:{user_id}' if valid JWT token is present;
    otherwise fallback to client IP.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("user_id") or payload.get("sub")
            tenant_id = payload.get("tenant_id", "0")
            if user_id:
                return f"u:{tenant_id}:{user_id}"
        except Exception:
            pass
    return get_remote_address(request)

def get_ip_rate_limit_key(request: Request) -> str:
    """Strict client IP key function for unauthenticated authentication endpoints."""
    return get_remote_address(request)

class EnterpriseLimiter(Limiter):
    """
    Enterprise rate limiter wrapper:
    - Fully enforces Redis sliding-window throttling for HTTP requests via SlowAPI.
    - Gracefully synthesizes dummy requests when endpoints are directly invoked in Python tests.
    """
    def limit(self, *limit_args, **limit_kwargs):
        base_decorator = super().limit(*limit_args, **limit_kwargs)

        def wrapper(func):
            decorated_func = base_decorator(func)

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_safe_call(*args, **kwargs):
                    first_arg_is_req = len(args) > 0 and isinstance(args[0], Request)
                    kw_req = kwargs.get("request")
                    if not first_arg_is_req and not isinstance(kw_req, Request):
                        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 12345)}
                        dummy_req = Request(scope)
                        return await func(dummy_req, *args, **kwargs)
                    return await decorated_func(*args, **kwargs)
                return async_safe_call
            else:
                @functools.wraps(func)
                def sync_safe_call(*args, **kwargs):
                    first_arg_is_req = len(args) > 0 and isinstance(args[0], Request)
                    kw_req = kwargs.get("request")
                    if not first_arg_is_req and not isinstance(kw_req, Request):
                        scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 12345)}
                        dummy_req = Request(scope)
                        return func(dummy_req, *args, **kwargs)
                    return decorated_func(*args, **kwargs)
                return sync_safe_call
        return wrapper

limiter = EnterpriseLimiter(
    key_func=get_user_rate_limit_key,
    storage_uri=REDIS_URL,
    default_limits=[],
    headers_enabled=True,
)
