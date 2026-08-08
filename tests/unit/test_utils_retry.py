"""Tests for agentcrawl.utils.retry module."""

import asyncio

import pytest

from agentcrawl.utils.retry import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    RateLimiter,
    RetryConfig,
    retry,
    retry_with_backoff,
)


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_default_config(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.backoff_factor == 2.0
        assert config.jitter is True

    def test_custom_config(self):
        config = RetryConfig(
            max_retries=5,
            base_delay=0.5,
            max_delay=10.0,
            backoff_factor=3.0,
            jitter=False,
        )
        assert config.max_retries == 5
        assert config.base_delay == 0.5
        assert config.max_delay == 10.0
        assert config.backoff_factor == 3.0
        assert config.jitter is False

    def test_compute_delay_no_jitter(self):
        config = RetryConfig(jitter=False, base_delay=1.0, backoff_factor=2.0)
        # attempt 0: 1.0 * 2^0 = 1.0
        assert config.compute_delay(0) == 1.0
        # attempt 1: 1.0 * 2^1 = 2.0
        assert config.compute_delay(1) == 2.0
        # attempt 2: 1.0 * 2^2 = 4.0
        assert config.compute_delay(2) == 4.0

    def test_compute_delay_max_delay_cap(self):
        config = RetryConfig(jitter=False, base_delay=10.0, max_delay=5.0, backoff_factor=2.0)
        assert config.compute_delay(10) == 5.0

    def test_compute_delay_with_jitter(self):
        config = RetryConfig(jitter=True, base_delay=1.0, backoff_factor=2.0, jitter_range=0.1)
        delay = config.compute_delay(1)
        # Should be around 2.0 ± 0.2
        assert 1.8 <= delay <= 2.2

    def test_compute_delay_jitter_non_negative(self):
        config = RetryConfig(jitter=True, base_delay=0.01, jitter_range=1.0)
        delay = config.compute_delay(0)
        assert delay >= 0

    def test_should_retry_no_retry_on(self):
        config = RetryConfig(retry_on=())
        assert config.should_retry(Exception()) is True

    def test_should_retry_with_matching_type(self):
        config = RetryConfig(retry_on=(ValueError,))
        assert config.should_retry(ValueError("test")) is True

    def test_should_retry_with_non_matching_type(self):
        config = RetryConfig(retry_on=(ValueError,))
        assert config.should_retry(TypeError("test")) is False

    def test_should_retry_custom_condition_true(self):
        config = RetryConfig(retry_if=lambda e: isinstance(e, RuntimeError))
        assert config.should_retry(RuntimeError()) is True

    def test_should_retry_custom_condition_false(self):
        config = RetryConfig(retry_if=lambda e: isinstance(e, RuntimeError))
        assert config.should_retry(ValueError()) is False

    def test_should_retry_custom_condition_exception(self):
        def bad_condition(e):
            raise RuntimeError("condition error")

        config = RetryConfig(retry_if=bad_condition)
        assert config.should_retry(ValueError()) is False


class TestRetrySync:
    """Tests for sync retry decorator."""

    def test_success_on_first_try(self):
        call_count = 0

        @retry(max_retries=3, delay=0, jitter=False)
        def func():
            nonlocal call_count
            call_count += 1
            return "success"

        assert func() == "success"
        assert call_count == 1

    def test_retries_and_succeeds(self):
        call_count = 0

        @retry(max_retries=3, delay=0, jitter=False)
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "success"

        assert func() == "success"
        assert call_count == 3

    def test_retries_exhausted(self):
        call_count = 0

        @retry(max_retries=2, delay=0, jitter=False)
        def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            func()
        assert call_count == 3  # 1 initial + 2 retries

    def test_no_retry_on_non_matching_exception(self):
        call_count = 0

        @retry(max_retries=3, delay=0, jitter=False, retry_on=(ValueError,))
        def func():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            func()
        assert call_count == 1

    def test_on_retry_callback(self):
        callbacks = []

        @retry(
            max_retries=2,
            delay=0,
            jitter=False,
            on_retry=lambda attempt, exc, delay: callbacks.append((attempt, str(exc))),
        )
        def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            func()

        assert len(callbacks) == 2

    def test_on_success_callback(self):
        callbacks = []

        @retry(
            max_retries=2,
            delay=0,
            jitter=False,
            on_success=lambda attempt, result: callbacks.append((attempt, result)),
        )
        def func():
            return "ok"

        result = func()
        assert result == "ok"
        assert callbacks == [(0, "ok")]

    def test_on_failure_callback(self):
        callbacks = []

        @retry(
            max_retries=2,
            delay=0,
            jitter=False,
            on_failure=lambda attempts, exc: callbacks.append((attempts, str(exc))),
        )
        def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            func()

        assert callbacks == [(3, "fail")]

    def test_with_config_object(self):
        config = RetryConfig(max_retries=2, jitter=False)
        call_count = 0

        @retry(config=config)
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("fail")
            return "ok"

        assert func() == "ok"
        assert call_count == 2

    def test_retry_as_decorator_without_parens(self):
        call_count = 0

        @retry
        def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert func() == "ok"
        assert call_count == 1

    def test_retry_with_backoff(self):
        @retry_with_backoff(max_retries=0, base_delay=0)
        def func():
            return "ok"

        assert func() == "ok"

    def test_retry_with_backoff_retries(self):
        call_count = 0

        decorated = retry_with_backoff(max_retries=2, base_delay=0)
        decorated(lambda: _fail_then_succeed())

        # The inner function needs state tracking

        @retry_with_backoff(max_retries=2, base_delay=0)
        def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "success"

        assert failing_func() == "success"


def _fail_then_succeed():
    """Helper that always succeeds."""
    return "success"


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_closed(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_open is False

    def test_repr(self):
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        repr_str = repr(breaker)
        assert "CircuitBreaker" in repr_str
        assert "closed" in repr_str

    def test_half_open_to_closed_on_success(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01, success_threshold=1)

        call_count = 0

        @breaker
        def func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("fail")
            return "ok"

        with pytest.raises(ValueError):
            func()

        with pytest.raises(ValueError):
            func()

        # Now circuit should be open
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open is True

        # Wait for recovery
        import time

        time.sleep(0.02)

        # Should transition to half-open
        assert breaker.state == CircuitState.HALF_OPEN

        # Success in half-open with success_threshold=1 closes immediately
        result = func()
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    def test_excluded_exceptions_not_counted(self):
        breaker = CircuitBreaker(
            failure_threshold=1, recovery_timeout=60, excluded_exceptions=(ValueError,)
        )

        call_count = 0

        @breaker
        def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("excluded")

        with pytest.raises(ValueError):
            func()

        # Should still be closed since exception was excluded
        assert breaker.state == CircuitState.CLOSED
        assert call_count == 1

    def test_breaker_opens_after_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        call_count = 0

        @breaker
        def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        for _ in range(3):
            with pytest.raises(ValueError):
                func()

        assert breaker.state == CircuitState.OPEN

    def test_breaker_rejects_when_open(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        call_count = 0

        @breaker
        def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(ValueError):
            func()

        # Circuit is now open
        with pytest.raises(CircuitBreakerError):
            func()

        assert call_count == 1

    def test_get_stats(self):
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        stats = breaker.get_stats()
        assert stats["state"] == "closed"
        assert stats["failure_threshold"] == 5
        assert stats["recovery_timeout"] == 30
        assert stats["total_calls"] == 0

    def test_reset(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        @breaker
        def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            func()

        assert breaker.state == CircuitState.OPEN
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerAsync:
    """Tests for async circuit breaker."""

    @pytest.mark.asyncio
    async def test_async_success(self):
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

        @breaker
        async def func():
            return "ok"

        result = await func()
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_async_failure(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        call_count = 0

        @breaker
        async def func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("fail")
            return "ok"

        with pytest.raises(ValueError):
            await func()

        with pytest.raises(ValueError):
            await func()

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_async_rejected_when_open(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        @breaker
        async def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await func()

        with pytest.raises(CircuitBreakerError):
            await func()

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

        async with breaker:
            pass  # success

        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_async_context_manager_failure(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("fail")

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_async_context_manager_excluded_exception(self):
        breaker = CircuitBreaker(
            failure_threshold=1, recovery_timeout=60, excluded_exceptions=(ValueError,)
        )

        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("excluded")

        # Should be closed since ValueError is excluded
        assert breaker.state == CircuitState.CLOSED


class TestRateLimiter:
    """Tests for RateLimiter."""

    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        limiter = RateLimiter(max_calls=5, window_seconds=60)
        await limiter.acquire()
        await limiter.acquire()
        assert limiter.available == 3

    @pytest.mark.asyncio
    async def test_acquire_waits_when_full(self):
        limiter = RateLimiter(max_calls=1, window_seconds=0.05)
        await limiter.acquire()
        # This should wait for the window to expire
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.03  # Should have waited

    @pytest.mark.asyncio
    async def test_try_acquire_success(self):
        limiter = RateLimiter(max_calls=3, window_seconds=60)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is True
        assert limiter.available == 1

    @pytest.mark.asyncio
    async def test_try_acquire_rate_limited(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False

    def test_available_property(self):
        limiter = RateLimiter(max_calls=5, window_seconds=60)
        assert limiter.available == 5

    def test_repr(self):
        limiter = RateLimiter(max_calls=10, window_seconds=60)
        repr_str = repr(limiter)
        assert "RateLimiter" in repr_str
        assert "10" in repr_str


class TestCircuitBreakerError:
    """Tests for CircuitBreakerError."""

    def test_default_message(self):
        error = CircuitBreakerError()
        assert str(error) == "Circuit breaker is open"

    def test_custom_message(self):
        error = CircuitBreakerError("custom message")
        assert str(error) == "custom message"


class TestCircuitState:
    """Tests for CircuitState enum."""

    def test_state_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestRetryAsync:
    """Tests for async retry decorator."""

    @pytest.mark.asyncio
    async def test_async_success_on_first_try(self):
        call_count = 0

        @retry(max_retries=3, delay=0, jitter=False)
        async def func():
            nonlocal call_count
            call_count += 1
            return "success"

        assert await func() == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_retries_and_succeeds(self):
        call_count = 0

        @retry(max_retries=3, delay=0, jitter=False)
        async def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "success"

        assert await func() == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_retries_exhausted(self):
        @retry(max_retries=2, delay=0, jitter=False)
        async def func():
            raise ValueError("always fails")

        with pytest.raises(ValueError):
            await func()

    @pytest.mark.asyncio
    async def test_async_no_retry_on_non_matching(self):
        call_count = 0

        @retry(max_retries=3, delay=0, jitter=False, retry_on=(ValueError,))
        async def func():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            await func()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_callbacks(self):
        on_retry_called = []
        on_success_called = []
        on_failure_called = []

        @retry(
            max_retries=2,
            delay=0,
            jitter=False,
            on_retry=lambda a, e, d: on_retry_called.append(a),
            on_success=lambda a, r: on_success_called.append(a),
            on_failure=lambda a, e: on_failure_called.append(a),
        )
        async def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await func()

        assert len(on_retry_called) == 2
        assert len(on_failure_called) == 1
        assert len(on_success_called) == 0

    @pytest.mark.asyncio
    async def test_async_with_timeout(self):
        @retry(max_retries=1, delay=0, jitter=False, timeout=0.01)
        async def slow_func():
            await asyncio.sleep(1)
            return "ok"

        with pytest.raises(asyncio.TimeoutError):
            await slow_func()

    @pytest.mark.asyncio
    async def test_async_excluded_exceptions(self):
        call_count = 0

        @retry(max_retries=3, delay=0, jitter=False, retry_on=(ValueError,))
        async def func():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            await func()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_success_no_retries(self):
        call_count = 0

        @retry(max_retries=0, delay=0, jitter=False)
        async def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert await func() == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_max_retries_zero(self):
        call_count = 0

        @retry(max_retries=0, delay=0, jitter=False)
        async def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await func()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_on_success_callback(self):
        callbacks = []

        @retry(
            max_retries=2, delay=0, jitter=False, on_success=lambda a, r: callbacks.append((a, r))
        )
        async def func():
            return "ok"

        result = await func()
        assert result == "ok"
        assert callbacks == [(0, "ok")]

    @pytest.mark.asyncio
    async def test_async_on_failure_callback(self):
        callbacks = []

        @retry(
            max_retries=1,
            delay=0,
            jitter=False,
            on_failure=lambda a, e: callbacks.append((a, str(e))),
        )
        async def func():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await func()

        assert callbacks == [(2, "fail")]
