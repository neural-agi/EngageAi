"""API authentication and request rate limiting helpers."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections import deque
from collections.abc import MutableMapping
from secrets import compare_digest
from time import monotonic
from typing import Deque

from fastapi import Header
from fastapi import HTTPException
from fastapi import Request
from fastapi import status

from app.config import get_settings


logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """Track request counts per API key over a rolling one-minute window."""

    def __init__(self) -> None:
        """Initialize the limiter state."""

        self._requests: MutableMapping[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._window_seconds = 60.0

    def allow(self, key: str, limit: int) -> bool:
        """Return ``True`` when the request is within the configured limit."""

        safe_limit = max(limit, 1)
        now = monotonic()
        cutoff = now - self._window_seconds

        with self._lock:
            request_times = self._requests[key]
            while request_times and request_times[0] <= cutoff:
                request_times.popleft()

            if len(request_times) >= safe_limit:
                return False

            request_times.append(now)
            return True


rate_limiter = InMemoryRateLimiter()


async def require_api_access(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
) -> str:
    """Validate the API key header and enforce a per-minute request limit."""

    settings = get_settings()
    configured_api_key = (settings.api_key or "").strip()
    client_host = request.client.host if request.client else "unknown"
    request_path = request.url.path

    if not configured_api_key:
        logger.error(
            "API request rejected because API key auth is not configured",
            extra={"path": request_path, "client_host": client_host},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured. Set API_KEY in the environment.",
        )

    provided_api_key = (x_api_key or "").strip()
    if not provided_api_key or not compare_digest(provided_api_key, configured_api_key):
        logger.warning(
            "Rejected unauthorized API request",
            extra={"path": request_path, "client_host": client_host},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )

    if not rate_limiter.allow(provided_api_key, settings.api_rate_limit_per_minute):
        logger.warning(
            "Rejected API request due to rate limit violation",
            extra={
                "path": request_path,
                "client_host": client_host,
                "rate_limit_per_minute": settings.api_rate_limit_per_minute,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
        )

    return provided_api_key
