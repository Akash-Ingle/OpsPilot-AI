"""Per-IP rate limiting for the public API.

Uses slowapi (a Starlette/FastAPI wrapper around the `limits` library). Only the
expensive endpoints (LLM analysis, scenario generation) are decorated; cheap
read endpoints and the health check are intentionally left unlimited so they
don't interfere with platform health probes.

Behind a reverse proxy (Render, Fly, etc.) the real client IP arrives in the
`X-Forwarded-For` header, so we key on its first entry and fall back to the
socket peer address for local/direct runs.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First hop is the original client; the rest are proxies.
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_ip,
    enabled=settings.rate_limit_enabled,
    headers_enabled=True,  # emit X-RateLimit-* response headers
)

__all__ = ["limiter"]
