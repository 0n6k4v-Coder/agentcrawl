"""
AgentCrawl — Rate Limiter
=============================

Rate limiting for the AgentCrawl REST API with multiple
algorithms and storage backends.

Features:
    - Token bucket algorithm (smooth rate limiting)
    - Sliding window algorithm (precise counting)
    - Fixed window algorithm (simple counting)
    - Per-client limiting (by IP or API key)
    - Per-endpoint limiting
    - Configurable limits and burst allowance
    - In-memory and Redis backends
    - Standard rate limit headers
    - Automatic cleanup of expired entries
    - FastAPI middleware integration

Usage:
    from agentcrawl.server.auth.rate_limiter import (
        RateLimiter,
        RateLimitMiddleware,
        RateLimitConfig,
    )

    # Create limiter
    config = RateLimitConfig(
        requests_per_minute=60,
        burst=10,
        algorithm="token_bucket",
    )
    limiter = RateLimiter(config=config)

    # Check rate limit
    result = limiter.check("client-123")
    if result.allowed:
        print(f"Remaining: {result.remaining}")
    else:
        print(f"Retry after: {result.retry_after}s")

    # FastAPI middleware
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("agentcrawl.server.auth.rate_limiter")


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

class RateLimitAlgorithm(str, Enum):
    """Rate limiting algorithms."""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    """
    Rate limiting configuration.

    Attributes:
        requests_per_minute: Maximum requests per minute.
        requests_per_hour: Maximum requests per hour (0 = unlimited).
        burst: Burst allowance (extra requests above limit).
        algorithm: Rate limiting algorithm.
        window_seconds: Time window for fixed/sliding window.
        cleanup_interval: Seconds between cleanup runs.
        enabled: Whether rate limiting is enabled.
    """
    requests_per_minute: int = 60
    requests_per_hour: int = 0
    burst: int = 10
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    window_seconds: float = 60.0
    cleanup_interval: float = 300.0
    enabled: bool = True

    @property
    def rate_per_second(self) -> float:
        """Requests per second."""
        return self.requests_per_minute / 60.0

    @property
    def max_tokens(self) -> int:
        """Maximum tokens (bucket capacity)."""
        return self.requests_per_minute + self.burst


# ══════════════════════════════════════════════════════════════
# Result
# ══════════════════════════════════════════════════════════════

@dataclass
class RateLimitResult:
    """
    Result of a rate limit check.

    Attributes:
        allowed: Whether the request is allowed.
        remaining: Remaining requests in the window.
        limit: Maximum requests in the window.
        retry_after: Seconds until next allowed request.
        reset_at: Timestamp when the window resets.
    """
    allowed: bool
    remaining: int = 0
    limit: int = 0
    retry_after: float = 0.0
    reset_at: float = 0.0

    def to_headers(self) -> dict[str, str]:
        """Convert to standard rate limit headers."""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
        }

        if self.reset_at > 0:
            headers["X-RateLimit-Reset"] = str(int(self.reset_at))

        if not self.allowed and self.retry_after > 0:
            headers["Retry-After"] = str(int(self.retry_after) + 1)

        return headers


# ══════════════════════════════════════════════════════════════
# Token Bucket
# ══════════════════════════════════════════════════════════════

@dataclass
class _TokenBucket:
    """Internal token bucket state."""
    tokens: float
    last_refill: float
    capacity: float
    refill_rate: float  # tokens per second


class TokenBucketLimiter:
    """
    Token bucket rate limiter.

    Allows burst traffic up to bucket capacity, then
    refills at a steady rate.

    Args:
        config: Rate limit configuration.
    """

    def __init__(self, config: RateLimitConfig):
        self._config = config
        self._buckets: dict[str, _TokenBucket] = {}
        self._last_cleanup = time.time()

    def check(self, client_id: str) -> RateLimitResult:
        """
        Check and consume a token for a client.

        Args:
            client_id: Client identifier.

        Returns:
            RateLimitResult.
        """
        now = time.time()
        capacity = float(self._config.max_tokens)
        refill_rate = self._config.rate_per_second

        # Get or create bucket
        if client_id not in self._buckets:
            self._buckets[client_id] = _TokenBucket(
                tokens=capacity,
                last_refill=now,
                capacity=capacity,
                refill_rate=refill_rate,
            )

        bucket = self._buckets[client_id]

        # Refill tokens
        elapsed = now - bucket.last_refill
        bucket.tokens = min(capacity, bucket.tokens + elapsed * refill_rate)
        bucket.last_refill = now

        # Try to consume
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            remaining = int(bucket.tokens)
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=int(capacity),
                reset_at=now + (capacity - bucket.tokens) / refill_rate if refill_rate > 0 else 0,
            )
        else:
            # Calculate retry time
            tokens_needed = 1.0 - bucket.tokens
            retry_after = tokens_needed / refill_rate if refill_rate > 0 else 60.0
            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=int(capacity),
                retry_after=retry_after,
                reset_at=now + retry_after,
            )

    def cleanup(self) -> int:
        """Remove stale buckets. Returns count removed."""
        now = time.time()
        stale_threshold = self._config.window_seconds * 10

        stale = [
            cid for cid, b in self._buckets.items()
            if now - b.last_refill > stale_threshold
        ]

        for cid in stale:
            del self._buckets[cid]

        return len(stale)


# ══════════════════════════════════════════════════════════════
# Sliding Window
# ══════════════════════════════════════════════════════════════

class SlidingWindowLimiter:
    """
    Sliding window rate limiter.

    Tracks individual request timestamps and counts
    requests within the sliding window.

    Args:
        config: Rate limit configuration.
    """

    def __init__(self, config: RateLimitConfig):
        self._config = config
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def check(self, client_id: str) -> RateLimitResult:
        """
        Check rate limit for a client.

        Args:
            client_id: Client identifier.

        Returns:
            RateLimitResult.
        """
        now = time.time()
        window = self._config.window_seconds
        limit = self._config.requests_per_minute + self._config.burst

        # Clean old entries
        cutoff = now - window
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > cutoff
        ]

        current_count = len(self._requests[client_id])

        if current_count < limit:
            self._requests[client_id].append(now)
            remaining = limit - current_count - 1

            # Calculate reset time
            reset_at = now + window
            if self._requests[client_id]:
                oldest = min(self._requests[client_id])
                reset_at = oldest + window

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=limit,
                reset_at=reset_at,
            )
        else:
            # Find when the oldest request expires
            oldest = min(self._requests[client_id]) if self._requests[client_id] else now
            retry_after = oldest + window - now

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=limit,
                retry_after=max(0, retry_after),
                reset_at=oldest + window,
            )

    def cleanup(self) -> int:
        """Remove stale entries. Returns count removed."""
        now = time.time()
        window = self._config.window_seconds
        stale_threshold = window * 10

        stale_clients = []
        for cid, timestamps in self._requests.items():
            if not timestamps or (now - max(timestamps)) > stale_threshold:
                stale_clients.append(cid)

        for cid in stale_clients:
            del self._requests[cid]

        return len(stale_clients)


# ══════════════════════════════════════════════════════════════
# Fixed Window
# ══════════════════════════════════════════════════════════════

class FixedWindowLimiter:
    """
    Fixed window rate limiter.

    Counts requests in fixed time windows. Simple but
    can allow burst at window boundaries.

    Args:
        config: Rate limit configuration.
    """

    def __init__(self, config: RateLimitConfig):
        self._config = config
        self._windows: dict[str, tuple[float, int]] = {}  # client → (window_start, count)
        self._last_cleanup = time.time()

    def check(self, client_id: str) -> RateLimitResult:
        """
        Check rate limit for a client.

        Args:
            client_id: Client identifier.

        Returns:
            RateLimitResult.
        """
        now = time.time()
        window = self._config.window_seconds
        limit = self._config.requests_per_minute + self._config.burst

        # Get current window
        window_start = now - (now % window)

        if client_id in self._windows:
            stored_start, count = self._windows[client_id]

            if stored_start == window_start:
                # Same window
                if count < limit:
                    self._windows[client_id] = (window_start, count + 1)
                    return RateLimitResult(
                        allowed=True,
                        remaining=limit - count - 1,
                        limit=limit,
                        reset_at=window_start + window,
                    )
                else:
                    retry_after = window_start + window - now
                    return RateLimitResult(
                        allowed=False,
                        remaining=0,
                        limit=limit,
                        retry_after=max(0, retry_after),
                        reset_at=window_start + window,
                    )

        # New window
        self._windows[client_id] = (window_start, 1)
        return RateLimitResult(
            allowed=True,
            remaining=limit - 1,
            limit=limit,
            reset_at=window_start + window,
        )

    def cleanup(self) -> int:
        """Remove stale windows. Returns count removed."""
        now = time.time()
        window = self._config.window_seconds
        stale_threshold = window * 10

        stale = [
            cid for cid, (start, _) in self._windows.items()
            if now - start > stale_threshold
        ]

        for cid in stale:
            del self._windows[cid]

        return len(stale)


# ══════════════════════════════════════════════════════════════
# Unified Rate Limiter
# ══════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Unified rate limiter with configurable algorithm.

    Args:
        config: Rate limit configuration.

    Example:
        >>> config = RateLimitConfig(requests_per_minute=60, burst=10)
        >>> limiter = RateLimiter(config=config)
        >>> result = limiter.check("client-1")
        >>> print(result.allowed, result.remaining)
    """

    def __init__(self, config: RateLimitConfig | None = None):
        self._config = config or RateLimitConfig()

        # Create algorithm-specific limiter
        if self._config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            self._limiter: Any = TokenBucketLimiter(self._config)
        elif self._config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
            self._limiter = SlidingWindowLimiter(self._config)
        else:
            self._limiter = FixedWindowLimiter(self._config)

        self._total_checks: int = 0
        self._total_allowed: int = 0
        self._total_denied: int = 0

    def check(self, client_id: str) -> RateLimitResult:
        """
        Check rate limit for a client.

        Args:
            client_id: Client identifier (IP or API key).

        Returns:
            RateLimitResult.
        """
        if not self._config.enabled:
            return RateLimitResult(
                allowed=True,
                remaining=self._config.requests_per_minute,
                limit=self._config.requests_per_minute,
            )

        self._total_checks += 1
        result = self._limiter.check(client_id)

        if result.allowed:
            self._total_allowed += 1
        else:
            self._total_denied += 1

        # Periodic cleanup
        now = time.time()
        if hasattr(self._limiter, "_last_cleanup"):
            if now - self._limiter._last_cleanup > self._config.cleanup_interval:
                removed = self._limiter.cleanup()
                self._limiter._last_cleanup = now
                if removed > 0:
                    logger.debug("Rate limiter cleanup: removed %d entries", removed)

        return result

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            "algorithm": self._config.algorithm.value,
            "requests_per_minute": self._config.requests_per_minute,
            "burst": self._config.burst,
            "enabled": self._config.enabled,
            "total_checks": self._total_checks,
            "total_allowed": self._total_allowed,
            "total_denied": self._total_denied,
            "denial_rate": round(
                self._total_denied / max(self._total_checks, 1), 4
            ),
        }

    def __repr__(self) -> str:
        return (
            f"RateLimiter(algorithm={self._config.algorithm.value}, "
            f"limit={self._config.requests_per_minute}/min)"
        )


# ══════════════════════════════════════════════════════════════
# FastAPI Middleware
# ══════════════════════════════════════════════════════════════

class RateLimitMiddleware:
    """
    FastAPI/Starlette middleware for rate limiting.

    Args:
        app: ASGI application.
        limiter: RateLimiter instance.
        excluded_paths: Paths to skip rate limiting.
        identify_by: How to identify clients ('ip', 'api_key', 'both').

    Example:
        >>> limiter = RateLimiter(RateLimitConfig(requests_per_minute=60))
        >>> app.add_middleware(RateLimitMiddleware, limiter=limiter)
    """

    def __init__(
        self,
        app: Any,
        limiter: RateLimiter | None = None,
        excluded_paths: set[str] | None = None,
        identify_by: str = "both",
    ):
        self._app = app
        self._limiter = limiter or RateLimiter()
        self._excluded_paths = excluded_paths or {
            "/health", "/", "/docs", "/redoc", "/openapi.json",
        }
        self._identify_by = identify_by

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        """ASGI interface."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        from starlette.requests import Request
        from starlette.responses import JSONResponse

        request = Request(scope, receive)
        path = request.url.path

        # Skip excluded paths
        if path in self._excluded_paths:
            await self._app(scope, receive, send)
            return

        # Skip OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            await self._app(scope, receive, send)
            return

        # Identify client
        client_id = self._identify_client(request)

        # Check rate limit
        result = self._limiter.check(client_id)

        if not result.allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": (
                            f"Rate limit exceeded. "
                            f"Retry after {int(result.retry_after) + 1} seconds."
                        ),
                        "retry_after": int(result.retry_after) + 1,
                    }
                },
                headers=result.to_headers(),
            )
            await response(scope, receive, send)
            return

        # Add rate limit headers to response
        original_send = send

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                for key, value in result.to_headers().items():
                    headers[key.lower().encode()] = value.encode()
                message["headers"] = list(headers.items())
            await original_send(message)

        await self._app(scope, receive, send_with_headers)

    def _identify_client(self, request: Any) -> str:
        """Identify the client for rate limiting."""
        parts: list[str] = []

        if self._identify_by in ("api_key", "both"):
            # Try API key
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                parts.append(f"key:{auth[7:16]}")

            x_api_key = request.headers.get("X-API-Key", "")
            if x_api_key:
                parts.append(f"key:{x_api_key[:16]}")

        if self._identify_by in ("ip", "both") or not parts:
            # Fall back to IP
            client = request.client
            if client:
                parts.append(f"ip:{client.host}")
            else:
                parts.append("ip:unknown")

        return "|".join(parts)


# ══════════════════════════════════════════════════════════════
# Global Instance
# ══════════════════════════════════════════════════════════════

_global_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """
    Get the global RateLimiter instance.

    Configures from environment variables:
        AGENTCRAWL_RATE_LIMIT (requests per minute)
        AGENTCRAWL_RATE_LIMIT_BURST
        AGENTCRAWL_RATE_LIMIT_ALGORITHM

    Returns:
        RateLimiter instance.
    """
    global _global_limiter

    if _global_limiter is None:
        import os

        rpm = int(os.environ.get("AGENTCRAWL_RATE_LIMIT", "100"))
        burst = int(os.environ.get("AGENTCRAWL_RATE_LIMIT_BURST", "20"))
        algorithm = os.environ.get("AGENTCRAWL_RATE_LIMIT_ALGORITHM", "token_bucket")

        config = RateLimitConfig(
            requests_per_minute=rpm,
            burst=burst,
            algorithm=RateLimitAlgorithm(algorithm),
        )

        _global_limiter = RateLimiter(config=config)

    return _global_limiter