"""
AgentCrawl — API Dependencies
=================================

FastAPI dependency injection functions for authentication,
rate limiting, engine access, and request validation.

Usage:
    from server.api.deps import (
        get_engine,
        get_settings,
        verify_api_key,
        rate_limiter,
        validate_url,
    )

    @router.post("/scrape")
    async def scrape(
        engine=Depends(get_engine),
        settings=Depends(get_settings),
    ):
        ...
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Query, Request

logger = logging.getLogger("agentcrawl.server.deps")


# ══════════════════════════════════════════════════════════════
# Engine & State
# ══════════════════════════════════════════════════════════════

def get_state() -> Any:
    """
    Get the global application state.

    Returns:
        AppState instance.
    """
    from server.app import get_state as _get_state

    return _get_state()


def get_engine() -> Any:
    """
    Get the CrawlEngine instance from app state.

    Raises:
        HTTPException: If engine is not started.

    Returns:
        CrawlEngine instance.

    Usage:
        @router.post("/scrape")
        async def scrape(engine=Depends(get_engine)):
            result = await engine.scrape(url)
    """
    state = get_state()
    engine = state.engine

    if engine is None or not engine.is_started:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SERVICE_UNAVAILABLE",
                "message": "CrawlEngine not started. Server may still be initializing.",
            },
        )

    return engine


def get_settings() -> Any:
    """
    Get the global Settings instance.

    Returns:
        Settings instance.
    """
    state = get_state()

    if state.settings is None:
        from agentcrawl.config.settings import Settings

        state.settings = Settings()

    return state.settings


# Type aliases for Annotated dependencies
EngineDep = Annotated[Any, Depends(get_engine)]
SettingsDep = Annotated[Any, Depends(get_settings)]
StateDep = Annotated[Any, Depends(get_state)]


# ══════════════════════════════════════════════════════════════
# Authentication
# ══════════════════════════════════════════════════════════════

async def verify_api_key(
    request: Request,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
    api_key_query: str = Query(default="", alias="api_key"),
) -> str | None:
    """
    Verify API key from multiple sources.

    Checks (in order):
        1. Authorization: Bearer <key> header
        2. X-API-Key header
        3. ?api_key=<key> query parameter

    If no API key is configured on the server, all requests pass.

    Args:
        request: FastAPI request.
        authorization: Authorization header.
        x_api_key: X-API-Key header.
        api_key_query: api_key query parameter.

    Returns:
        The validated API key, or None if no auth required.

    Raises:
        HTTPException: If API key is invalid.
    """
    state = get_state()
    settings = state.settings

    # No API key configured — allow all
    if not settings or not settings.api_key:
        return None

    expected_key = settings.api_key

    # Check Authorization header
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
            if token == expected_key:
                return token

    # Check X-API-Key header
    if x_api_key and x_api_key == expected_key:
        return x_api_key

    # Check query parameter
    if api_key_query and api_key_query == expected_key:
        return api_key_query

    # No valid key found
    raise HTTPException(
        status_code=401,
        detail={
            "code": "UNAUTHORIZED",
            "message": "Invalid or missing API key. "
                       "Provide via Authorization: Bearer <key>, "
                       "X-API-Key header, or ?api_key=<key>.",
        },
    )


# Type alias
ApiKeyDep = Annotated[str | None, Depends(verify_api_key)]


# ══════════════════════════════════════════════════════════════
# Rate Limiting
# ══════════════════════════════════════════════════════════════

class _RateLimitStore:
    """Simple in-memory rate limit tracker."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._window_seconds: float = 60.0
        self._max_requests: int = 100

    def configure(self, max_requests: int, window_seconds: float) -> None:
        """Configure rate limit parameters."""
        self._max_requests = max_requests
        self._window_seconds = window_seconds

    def check(self, client_id: str) -> tuple[bool, int, int]:
        """
        Check if a client is within rate limits.

        Args:
            client_id: Client identifier (IP or API key).

        Returns:
            Tuple of (allowed, remaining, reset_seconds).
        """
        now = time.time()
        cutoff = now - self._window_seconds

        # Clean old entries
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > cutoff
        ]

        current_count = len(self._requests[client_id])
        remaining = max(0, self._max_requests - current_count)
        reset_seconds = int(self._window_seconds)

        if current_count >= self._max_requests:
            # Find when the oldest request expires
            if self._requests[client_id]:
                oldest = min(self._requests[client_id])
                reset_seconds = int(oldest + self._window_seconds - now) + 1
            return False, 0, reset_seconds

        # Record this request
        self._requests[client_id].append(now)
        remaining = max(0, self._max_requests - current_count - 1)

        return True, remaining, reset_seconds


_rate_store = _RateLimitStore()


async def rate_limiter(
    request: Request,
    api_key: str | None = Depends(verify_api_key),
) -> None:
    """
    Rate limiting dependency.

    Limits requests per client (by API key or IP address).

    Raises:
        HTTPException: If rate limit exceeded (429).
    """
    # Skip rate limiting for health/docs
    path = request.url.path
    if path in ("/health", "/", "/docs", "/redoc", "/openapi.json"):
        return

    # Identify client
    client_id = api_key or request.client.host if request.client else "unknown"

    # Check rate limit
    allowed, remaining, reset_seconds = _rate_store.check(client_id)

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "RATE_LIMITED",
                "message": f"Rate limit exceeded. Retry after {reset_seconds} seconds.",
                "retry_after": reset_seconds,
            },
            headers={
                "Retry-After": str(reset_seconds),
                "X-RateLimit-Limit": str(_rate_store._max_requests),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_seconds),
            },
        )


# Type alias
RateLimitDep = Annotated[None, Depends(rate_limiter)]


# ══════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════

def validate_url(url: str) -> str:
    """
    Validate and normalize a URL.

    Args:
        url: URL string.

    Returns:
        Normalized URL.

    Raises:
        HTTPException: If URL is invalid.
    """
    from agentcrawl.utils.url import is_valid_url, normalize_url

    if not url or not url.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "URL is required",
            },
        )

    url = url.strip()

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    if not is_valid_url(url):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_URL",
                "message": f"Invalid URL: {url}",
            },
        )

    return normalize_url(url)


def validate_urls(urls: list[str], max_count: int = 100) -> list[str]:
    """
    Validate a list of URLs.

    Args:
        urls: List of URL strings.
        max_count: Maximum allowed URLs.

    Returns:
        List of validated URLs.

    Raises:
        HTTPException: If validation fails.
    """
    if not urls:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "At least one URL is required",
            },
        )

    if len(urls) > max_count:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": f"Maximum {max_count} URLs per request",
            },
        )

    return [validate_url(u) for u in urls]


# ══════════════════════════════════════════════════════════════
# Pagination
# ══════════════════════════════════════════════════════════════

class PaginationParams:
    """
    Pagination query parameters.

    Usage:
        @router.get("/results")
        async def list_results(pagination=Depends(PaginationParams)):
            offset = pagination.offset
            limit = pagination.limit
    """

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Page number"),
        per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.per_page = per_page

    @property
    def offset(self) -> int:
        """Offset for database queries."""
        return (self.page - 1) * self.per_page

    @property
    def limit(self) -> int:
        """Limit for database queries."""
        return self.per_page


PaginationDep = Annotated[PaginationParams, Depends(PaginationParams)]


# ══════════════════════════════════════════════════════════════
# Optional Engine (for endpoints that can work without engine)
# ══════════════════════════════════════════════════════════════

def get_engine_optional() -> Any | None:
    """
    Get CrawlEngine if available, None otherwise.

    Useful for endpoints that can return partial results
    without a running engine.
    """
    try:
        state = get_state()
        engine = state.engine
        if engine and engine.is_started:
            return engine
    except Exception:
        pass
    return None


OptionalEngineDep = Annotated[Any | None, Depends(get_engine_optional)]
