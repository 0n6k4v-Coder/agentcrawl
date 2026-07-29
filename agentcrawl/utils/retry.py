"""
AgentCrawl — Retry Utilities
================================

Retry logic with exponential backoff, jitter, circuit breaker,
and rate limiting for resilient network operations.

Features:
    - Retry decorator (sync and async)
    - Exponential backoff with configurable base and factor
    - Random jitter to prevent thundering herd
    - Retry on specific exception types
    - Custom retry condition function
    - Per-attempt timeout
    - Callback hooks (on_retry, on_success, on_failure)
    - Circuit breaker pattern
    - Simple rate limiter

Usage:
    from agentcrawl.utils.retry import retry, RetryConfig, CircuitBreaker

    # Simple retry
    @retry(max_retries=3, delay=1.0)
    async def fetch_data():
        ...

    # With configuration
    config = RetryConfig(
        max_retries=5,
        base_delay=0.5,
        max_delay=30.0,
        backoff_factor=2.0,
        jitter=True,
        retry_on=(ConnectionError, TimeoutError),
    )

    @retry(config=config)
    async def fetch_page(url):
        ...

    # Circuit breaker
    breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60,
    )

    @breaker
    async def call_api():
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger("agentcrawl.utils.retry")


# ══════════════════════════════════════════════════════════════
# Retry Configuration
# ══════════════════════════════════════════════════════════════

@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries (seconds).
        max_delay: Maximum delay between retries (seconds).
        backoff_factor: Multiplier for exponential backoff.
        jitter: Whether to add random jitter to delays.
        jitter_range: Jitter range as fraction of delay (0.0 - 1.0).
        retry_on: Exception types to retry on (empty = all).
        retry_if: Custom condition function (receives exception).
        timeout: Per-attempt timeout in seconds (0 = no timeout).
        on_retry: Callback on each retry (attempt, exception, delay).
        on_success: Callback on success (attempt, result).
        on_failure: Callback on final failure (attempts, exception).
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_factor: float = 2.0
    jitter: bool = True
    jitter_range: float = 0.25
    retry_on: tuple[type[Exception], ...] = ()
    retry_if: Callable[[Exception], bool] | None = None
    timeout: float = 0.0
    on_retry: Callable[[int, Exception, float], None] | None = None
    on_success: Callable[[int, Any], None] | None = None
    on_failure: Callable[[int, Exception], None] | None = None

    def compute_delay(self, attempt: int) -> float:
        """
        Compute the delay for a given attempt number.

        Args:
            attempt: Attempt number (0-based).

        Returns:
            Delay in seconds.
        """
        # Exponential backoff
        delay = self.base_delay * (self.backoff_factor ** attempt)

        # Cap at max_delay
        delay = min(delay, self.max_delay)

        # Add jitter
        if self.jitter:
            jitter_amount = delay * self.jitter_range
            delay += random.uniform(-jitter_amount, jitter_amount)
            delay = max(0, delay)

        return delay

    def should_retry(self, exception: Exception) -> bool:
        """
        Determine if an exception should trigger a retry.

        Args:
            exception: The exception that occurred.

        Returns:
            True if the operation should be retried.
        """
        # Check retry_on types
        if self.retry_on:
            if not isinstance(exception, self.retry_on):
                return False

        # Check custom condition
        if self.retry_if is not None:
            try:
                return self.retry_if(exception)
            except Exception:
                return False

        return True


# ══════════════════════════════════════════════════════════════
# Retry Decorator
# ══════════════════════════════════════════════════════════════

def retry(
    func: Callable | None = None,
    *,
    max_retries: int = 3,
    delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_on: tuple[type[Exception], ...] | Sequence[type[Exception]] = (),
    retry_if: Callable[[Exception], bool] | None = None,
    timeout: float = 0.0,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    on_success: Callable[[int, Any], None] | None = None,
    on_failure: Callable[[int, Exception], None] | None = None,
) -> Callable:
    """
    Retry decorator with exponential backoff.

    Works with both sync and async functions.

    Args:
        func: Function to decorate (when used without parentheses).
        max_retries: Maximum retry attempts.
        delay: Base delay between retries (seconds).
        max_delay: Maximum delay (seconds).
        backoff_factor: Exponential backoff multiplier.
        jitter: Add random jitter to delays.
        retry_on: Exception types to retry on.
        retry_if: Custom retry condition.
        timeout: Per-attempt timeout (seconds).
        config: Full RetryConfig (overrides individual args).
        on_retry: Callback on each retry.
        on_success: Callback on success.
        on_failure: Callback on final failure.

    Returns:
        Decorated function.

    Example:
        >>> @retry(max_retries=3, delay=1.0, retry_on=(ConnectionError,))
        ... async def fetch(url):
        ...     ...

        >>> @retry(config=RetryConfig(max_retries=5, jitter=True))
        ... def sync_fetch(url):
        ...     ...
    """
    # Build config
    if config is None:
        config = RetryConfig(
            max_retries=max_retries,
            base_delay=delay,
            max_delay=max_delay,
            backoff_factor=backoff_factor,
            jitter=jitter,
            retry_on=tuple(retry_on) if retry_on else (),
            retry_if=retry_if,
            timeout=timeout,
            on_retry=on_retry,
            on_success=on_success,
            on_failure=on_failure,
        )

    def decorator(fn: Callable) -> Callable:
        if _is_async(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await _retry_async(fn, config, args, kwargs)
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return _retry_sync(fn, config, args, kwargs)
            return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


async def _retry_async(
    fn: Callable,
    config: RetryConfig,
    args: tuple,
    kwargs: dict,
) -> Any:
    """Execute an async function with retry logic."""
    last_exception: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            if config.timeout > 0:
                result = await asyncio.wait_for(
                    fn(*args, **kwargs),
                    timeout=config.timeout,
                )
            else:
                result = await fn(*args, **kwargs)

            # Success callback
            if config.on_success:
                config.on_success(attempt, result)

            return result

        except Exception as e:
            last_exception = e

            # Check if we should retry
            if attempt >= config.max_retries:
                break

            if not config.should_retry(e):
                break

            # Compute delay
            delay = config.compute_delay(attempt)

            # Retry callback
            if config.on_retry:
                config.on_retry(attempt + 1, e, delay)

            logger.debug(
                "Retry %d/%d for %s after %.2fs: %s",
                attempt + 1,
                config.max_retries,
                fn.__name__,
                delay,
                e,
            )

            await asyncio.sleep(delay)

    # Final failure
    if config.on_failure and last_exception:
        config.on_failure(config.max_retries + 1, last_exception)

    if last_exception:
        raise last_exception

    raise RuntimeError("Retry failed with no exception")


def _retry_sync(
    fn: Callable,
    config: RetryConfig,
    args: tuple,
    kwargs: dict,
) -> Any:
    """Execute a sync function with retry logic."""
    last_exception: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            result = fn(*args, **kwargs)

            if config.on_success:
                config.on_success(attempt, result)

            return result

        except Exception as e:
            last_exception = e

            if attempt >= config.max_retries:
                break

            if not config.should_retry(e):
                break

            delay = config.compute_delay(attempt)

            if config.on_retry:
                config.on_retry(attempt + 1, e, delay)

            logger.debug(
                "Retry %d/%d for %s after %.2fs: %s",
                attempt + 1,
                config.max_retries,
                fn.__name__,
                delay,
                e,
            )

            time.sleep(delay)

    if config.on_failure and last_exception:
        config.on_failure(config.max_retries + 1, last_exception)

    if last_exception:
        raise last_exception

    raise RuntimeError("Retry failed with no exception")


# ══════════════════════════════════════════════════════════════
# Circuit Breaker
# ══════════════════════════════════════════════════════════════

class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when the circuit breaker is open."""

    def __init__(self, message: str = "Circuit breaker is open"):
        super().__init__(message)


class CircuitBreaker:
    """
    Circuit breaker pattern for fault tolerance.

    Prevents cascading failures by stopping calls to a failing
    service after a threshold of consecutive failures.

    States:
        CLOSED    — Normal operation, calls pass through.
        OPEN      — Too many failures, calls are rejected immediately.
        HALF_OPEN — After recovery timeout, allow one test call.

    Args:
        failure_threshold: Consecutive failures before opening.
        recovery_timeout: Seconds to wait before half-open test.
        success_threshold: Successes in half-open before closing.
        excluded_exceptions: Exceptions that don't count as failures.

    Example:
        >>> breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        >>>
        >>> @breaker
        ... async def call_api():
        ...     ...
        >>>
        >>> # Or use as context manager
        >>> async with breaker:
        ...     await call_api()
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
        excluded_exceptions: tuple[type[Exception], ...] = (),
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold
        self._excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._total_calls = 0
        self._total_failures = 0
        self._total_rejected = 0

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        # Check if we should transition from OPEN to HALF_OPEN
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info("Circuit breaker → HALF_OPEN")

        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    # ──────────────────────────────────────────────────────────
    # Decorator
    # ──────────────────────────────────────────────────────────

    def __call__(self, func: Callable) -> Callable:
        """Use as a decorator."""
        if _is_async(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self._call_async(func, args, kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return self._call_sync(func, args, kwargs)
            return sync_wrapper

    async def _call_async(
        self,
        fn: Callable,
        args: tuple,
        kwargs: dict,
    ) -> Any:
        """Execute with circuit breaker (async)."""
        self._check_state()
        self._total_calls += 1

        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            if isinstance(e, self._excluded_exceptions):
                raise
            self._on_failure()
            raise

    def _call_sync(
        self,
        fn: Callable,
        args: tuple,
        kwargs: dict,
    ) -> Any:
        """Execute with circuit breaker (sync)."""
        self._check_state()
        self._total_calls += 1

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            if isinstance(e, self._excluded_exceptions):
                raise
            self._on_failure()
            raise

    # ──────────────────────────────────────────────────────────
    # Context Manager
    # ──────────────────────────────────────────────────────────

    async def __aenter__(self) -> CircuitBreaker:
        self._check_state()
        self._total_calls += 1
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> bool:
        if exc_val is None:
            self._on_success()
        elif not isinstance(exc_val, self._excluded_exceptions):
            self._on_failure()
        return False  # Don't suppress exceptions

    # ──────────────────────────────────────────────────────────
    # State Management
    # ──────────────────────────────────────────────────────────

    def _check_state(self) -> None:
        """Check if calls are allowed."""
        state = self.state  # Triggers OPEN → HALF_OPEN check

        if state == CircuitState.OPEN:
            self._total_rejected += 1
            raise CircuitBreakerError(
                f"Circuit breaker is OPEN. "
                f"Retry after {self._recovery_timeout}s."
            )

    def _on_success(self) -> None:
        """Handle a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info("Circuit breaker → CLOSED")
        else:
            self._failure_count = 0

    def _on_failure(self) -> None:
        """Handle a failed call."""
        self._total_failures += 1
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Failed during half-open test → back to open
            self._state = CircuitState.OPEN
            self._success_count = 0
            logger.warning("Circuit breaker → OPEN (half-open test failed)")

        elif self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker → OPEN (%d consecutive failures)",
                self._failure_count,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info("Circuit breaker reset → CLOSED")

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_rejected": self._total_rejected,
            "failure_threshold": self._failure_threshold,
            "recovery_timeout": self._recovery_timeout,
        }

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(state={self.state.value}, "
            f"failures={self._failure_count}/{self._failure_threshold})"
        )


# ══════════════════════════════════════════════════════════════
# Rate Limiter
# ══════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Simple token bucket rate limiter.

    Limits the number of operations per time window.

    Args:
        max_calls: Maximum calls per window.
        window_seconds: Time window in seconds.

    Example:
        >>> limiter = RateLimiter(max_calls=10, window_seconds=60)
        >>>
        >>> async def fetch():
        ...     await limiter.acquire()
        ...     # ... make request ...
    """

    def __init__(self, max_calls: int = 10, window_seconds: float = 60.0):
        self._max_calls = max_calls
        self._window = window_seconds
        self._calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Wait until a call is allowed.

        Blocks if the rate limit has been reached.
        """
        async with self._lock:
            now = time.time()

            # Remove expired calls
            cutoff = now - self._window
            self._calls = [t for t in self._calls if t > cutoff]

            # Check limit
            if len(self._calls) >= self._max_calls:
                # Wait for the oldest call to expire
                oldest = self._calls[0]
                wait_time = oldest + self._window - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    # Clean up again after waiting
                    now = time.time()
                    cutoff = now - self._window
                    self._calls = [t for t in self._calls if t > cutoff]

            # Record this call
            self._calls.append(time.time())

    def try_acquire(self) -> bool:
        """
        Try to acquire without waiting.

        Returns:
            True if a call is allowed, False if rate limited.
        """
        now = time.time()
        cutoff = now - self._window
        self._calls = [t for t in self._calls if t > cutoff]

        if len(self._calls) >= self._max_calls:
            return False

        self._calls.append(now)
        return True

    @property
    def available(self) -> int:
        """Number of calls available in the current window."""
        now = time.time()
        cutoff = now - self._window
        active = sum(1 for t in self._calls if t > cutoff)
        return max(0, self._max_calls - active)

    def __repr__(self) -> str:
        return (
            f"RateLimiter(max={self._max_calls}/{self._window}s, "
            f"available={self.available})"
        )


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

def _is_async(func: Callable) -> bool:
    """Check if a function is async."""
    return asyncio.iscoroutinefunction(func)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Callable:
    """
    Shorthand for a simple retry with exponential backoff.

    Args:
        max_retries: Maximum retries.
        base_delay: Base delay in seconds.

    Returns:
        Retry decorator.
    """
    return retry(
        max_retries=max_retries,
        delay=base_delay,
        backoff_factor=2.0,
        jitter=True,
    )
