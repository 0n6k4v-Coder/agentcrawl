"""
AgentCrawl — Browser Page Pool
================================

A dedicated, production-grade page pool for managing concurrent
Playwright browser pages with semaphore-based concurrency control,
pre-warming, health checking, recycling, and priority queuing.

The BrowserPool can be used standalone or as the underlying pool
mechanism within BrowserManager.

Architecture:
    BrowserPool
    ├── Semaphore (concurrency limiter)
    ├── Available Queue (idle pages ready for use)
    ├── Active Set (pages currently in use)
    ├── Pre-warmer (background page creation)
    ├── Health Checker (periodic validation)
    └── Recycler (stale page cleanup)

Usage:
    from agentcrawl.browser.pool import BrowserPool
    from agentcrawl.browser.config import BrowserConfig, BrowserPoolConfig

    config = BrowserConfig(
        pool=BrowserPoolConfig(max_pages=10, pre_warm=3),
    )

    async with BrowserPool(config) as pool:
        # Acquire a page
        page = await pool.acquire()
        try:
            await page.goto("https://example.com")
            html = await page.content()
        finally:
            await pool.release(page)

        # Batch acquire
        pages = await pool.acquire_batch(5)
        try:
            # ... use pages concurrently ...
            pass
        finally:
            await pool.release_batch(pages)

        # Pool stats
        print(pool.stats)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentcrawl.browser.config import BrowserConfig

logger = logging.getLogger("agentcrawl.browser.pool")


# ══════════════════════════════════════════════════════════════
# Types & Enums
# ══════════════════════════════════════════════════════════════

class PageState(str, Enum):
    """Lifecycle state of a pooled page."""
    CREATING = "creating"
    IDLE = "idle"
    IN_USE = "in_use"
    RECYCLING = "recycling"
    CLOSED = "closed"


class AcquirePriority(int, Enum):
    """Priority levels for page acquisition."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class PoolEventType(str, Enum):
    """Pool lifecycle events for monitoring."""
    PAGE_CREATED = "page_created"
    PAGE_ACQUIRED = "page_acquired"
    PAGE_RELEASED = "page_released"
    PAGE_RECYCLED = "page_recycled"
    PAGE_CLOSED = "page_closed"
    POOL_EXHAUSTED = "pool_exhausted"
    POOL_RESIZED = "pool_resized"
    HEALTH_CHECK_FAILED = "health_check_failed"
    PRE_WARM_COMPLETE = "pre_warm_complete"


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class PooledPage:
    """
    A page managed by the pool with lifecycle metadata.

    Attributes:
        page: The underlying Playwright Page instance.
        context: The browser context this page belongs to.
        page_id: Unique identifier for this pooled page.
        state: Current lifecycle state.
        created_at: Unix timestamp of creation.
        last_acquired_at: Unix timestamp of last acquisition.
        last_released_at: Unix timestamp of last release.
        acquisition_count: Total times this page has been acquired.
        navigation_count: Total navigations performed on this page.
        error_count: Number of errors encountered on this page.
        session_id: Optional session binding.
        metadata: Arbitrary metadata attached to this page.
    """
    page: Any
    context: Any
    page_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    state: PageState = PageState.CREATING
    created_at: float = field(default_factory=time.time)
    last_acquired_at: float = 0.0
    last_released_at: float = 0.0
    acquisition_count: int = 0
    navigation_count: int = 0
    error_count: int = 0
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        """Total age of this page in seconds."""
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        """Seconds since last release (0 if never released or currently in use)."""
        if self.state == PageState.IN_USE:
            return 0.0
        if self.last_released_at == 0.0:
            return time.time() - self.created_at
        return time.time() - self.last_released_at

    @property
    def in_use_seconds(self) -> float:
        """Seconds this page has been in current use."""
        if self.state != PageState.IN_USE or self.last_acquired_at == 0.0:
            return 0.0
        return time.time() - self.last_acquired_at

    @property
    def is_expired(self) -> bool:
        """Whether the page has exceeded its TTL (checked against pool config)."""
        return False  # Determined by pool config at check time

    @property
    def is_healthy(self) -> bool:
        """Basic health check — page is not closed."""
        try:
            return not self.page.is_closed()
        except Exception:
            return False

    def mark_acquired(self) -> None:
        """Mark this page as acquired."""
        self.state = PageState.IN_USE
        self.last_acquired_at = time.time()
        self.acquisition_count += 1

    def mark_released(self) -> None:
        """Mark this page as released back to the pool."""
        self.state = PageState.IDLE
        self.last_released_at = time.time()

    def mark_recycling(self) -> None:
        """Mark this page for recycling."""
        self.state = PageState.RECYCLING

    def mark_closed(self) -> None:
        """Mark this page as closed."""
        self.state = PageState.CLOSED

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for diagnostics."""
        return {
            "page_id": self.page_id,
            "state": self.state.value,
            "age_seconds": round(self.age_seconds, 1),
            "idle_seconds": round(self.idle_seconds, 1),
            "in_use_seconds": round(self.in_use_seconds, 1),
            "acquisition_count": self.acquisition_count,
            "navigation_count": self.navigation_count,
            "error_count": self.error_count,
            "session_id": self.session_id,
            "is_healthy": self.is_healthy,
        }


@dataclass
class PoolStats:
    """
    Aggregate statistics for the page pool.

    All counters are cumulative since pool creation.
    """
    pages_created: int = 0
    pages_acquired: int = 0
    pages_released: int = 0
    pages_recycled: int = 0
    pages_closed: int = 0
    acquire_timeouts: int = 0
    acquire_waits: int = 0
    health_check_failures: int = 0
    errors: int = 0
    total_acquire_wait_ms: float = 0.0
    total_page_use_ms: float = 0.0

    @property
    def avg_acquire_wait_ms(self) -> float:
        if self.pages_acquired == 0:
            return 0.0
        return self.total_acquire_wait_ms / self.pages_acquired

    @property
    def avg_page_use_ms(self) -> float:
        if self.pages_released == 0:
            return 0.0
        return self.total_page_use_ms / self.pages_released

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages_created": self.pages_created,
            "pages_acquired": self.pages_acquired,
            "pages_released": self.pages_released,
            "pages_recycled": self.pages_recycled,
            "pages_closed": self.pages_closed,
            "acquire_timeouts": self.acquire_timeouts,
            "acquire_waits": self.acquire_waits,
            "health_check_failures": self.health_check_failures,
            "errors": self.errors,
            "avg_acquire_wait_ms": round(self.avg_acquire_wait_ms, 2),
            "avg_page_use_ms": round(self.avg_page_use_ms, 2),
        }


@dataclass
class _AcquireRequest:
    """Internal: a pending page acquisition request."""
    future: asyncio.Future[PooledPage]
    priority: AcquirePriority = AcquirePriority.NORMAL
    requested_at: float = field(default_factory=time.time)
    session_id: str | None = None
    context_options: dict[str, Any] | None = None


# ══════════════════════════════════════════════════════════════
# Event Callback Type
# ══════════════════════════════════════════════════════════════

PoolEventCallback = Callable[[PoolEventType, dict[str, Any]], Coroutine[Any, Any, None]]


# ══════════════════════════════════════════════════════════════
# Browser Pool
# ══════════════════════════════════════════════════════════════

class BrowserPool:
    """
    Production-grade browser page pool with concurrency control.

    Manages a pool of Playwright pages with:
    - Semaphore-based concurrency limiting
    - Priority-based acquisition queue
    - Automatic pre-warming
    - Periodic health checking
    - TTL and usage-based recycling
    - Event callbacks for monitoring
    - Graceful shutdown with drain

    Args:
        config: Browser configuration (uses pool settings).
        page_factory: Async callable that creates a new (page, context) tuple.
                      If None, a default factory using BrowserManager is used.
        on_event: Optional async callback for pool events.

    Example:
        >>> async def my_page_factory():
        ...     # Create page + context via your preferred method
        ...     return page, context
        ...
        >>> pool = BrowserPool(
        ...     config=BrowserConfig(pool=BrowserPoolConfig(max_pages=10)),
        ...     page_factory=my_page_factory,
        ... )
        >>> async with pool:
        ...     page = await pool.acquire()
        ...     try:
        ...         await page.goto("https://example.com")
        ...     finally:
        ...         await pool.release(page)
    """

    def __init__(
        self,
        config: BrowserConfig | None = None,
        page_factory: Callable[[], Coroutine[Any, Any, tuple[Any, Any]]] | None = None,
        on_event: PoolEventCallback | None = None,
    ):
        self._config = config or BrowserConfig()
        self._pool_config = self._config.pool
        self._page_factory = page_factory
        self._on_event = on_event

        # Concurrency control
        self._semaphore = asyncio.Semaphore(self._pool_config.max_pages)

        # Page tracking
        self._all_pages: dict[str, PooledPage] = {}
        self._idle_pages: asyncio.Queue[PooledPage] = asyncio.Queue()
        self._active_pages: dict[str, PooledPage] = {}

        # Priority queue for waiting requests
        self._waiting_requests: list[_AcquireRequest] = []
        self._waiting_lock = asyncio.Lock()

        # State
        self._started = False
        self._shutting_down = False
        self._lock = asyncio.Lock()

        # Stats
        self._stats = PoolStats()

        # Background tasks
        self._health_check_task: asyncio.Task | None = None
        self._recycler_task: asyncio.Task | None = None
        self._pre_warm_task: asyncio.Task | None = None

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def is_started(self) -> bool:
        """Whether the pool has been initialized."""
        return self._started

    @property
    def max_pages(self) -> int:
        """Maximum number of concurrent pages."""
        return self._pool_config.max_pages

    @property
    def total_pages(self) -> int:
        """Total number of pages (idle + active + creating)."""
        return len(self._all_pages)

    @property
    def active_pages(self) -> int:
        """Number of pages currently in use."""
        return len(self._active_pages)

    @property
    def idle_pages(self) -> int:
        """Number of idle pages available for acquisition."""
        return self._idle_pages.qsize()

    @property
    def waiting_requests(self) -> int:
        """Number of requests waiting for a page."""
        return len(self._waiting_requests)

    @property
    def utilization(self) -> float:
        """Pool utilization ratio (0.0 to 1.0)."""
        if self._pool_config.max_pages == 0:
            return 0.0
        return self.active_pages / self._pool_config.max_pages

    @property
    def stats(self) -> PoolStats:
        """Cumulative pool statistics."""
        return self._stats

    @property
    def config(self) -> BrowserConfig:
        """Current browser configuration."""
        return self._config

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Initialize the pool and pre-warm pages.

        Idempotent — safe to call multiple times.
        """
        async with self._lock:
            if self._started:
                return

            logger.info(
                "Starting BrowserPool (max_pages=%d, pre_warm=%d)",
                self._pool_config.max_pages,
                self._pool_config.pre_warm,
            )

            self._started = True
            self._shutting_down = False

            # Pre-warm pages in background
            if self._pool_config.pre_warm > 0:
                self._pre_warm_task = asyncio.create_task(self._pre_warm())

            # Start background maintenance
            self._start_maintenance_tasks()

            logger.info("BrowserPool started")

    async def stop(self, drain_timeout: float = 30.0) -> None:
        """
        Gracefully shut down the pool.

        Waits for active pages to be released (up to drain_timeout),
        then force-closes all remaining pages.

        Args:
            drain_timeout: Maximum seconds to wait for active pages.
        """
        async with self._lock:
            if not self._started:
                return

            logger.info("Stopping BrowserPool (drain_timeout=%.1fs)...", drain_timeout)
            self._shutting_down = True

            # Cancel background tasks
            await self._stop_maintenance_tasks()

            # Wait for active pages to drain
            if self._active_pages:
                logger.info(
                    "Waiting for %d active page(s) to drain...",
                    len(self._active_pages),
                )
                deadline = time.time() + drain_timeout
                while self._active_pages and time.time() < deadline:
                    await asyncio.sleep(0.5)

                if self._active_pages:
                    logger.warning(
                        "Force-closing %d page(s) after drain timeout",
                        len(self._active_pages),
                    )

            # Cancel waiting requests
            async with self._waiting_lock:
                for req in self._waiting_requests:
                    if not req.future.done():
                        req.future.cancel()
                self._waiting_requests.clear()

            # Close all pages
            for pooled in list(self._all_pages.values()):
                await self._close_page(pooled)

            self._all_pages.clear()
            self._active_pages.clear()

            # Drain idle queue
            while not self._idle_pages.empty():
                try:
                    self._idle_pages.get_nowait()
                except asyncio.QueueEmpty:
                    break

            self._started = False
            self._shutting_down = False

            logger.info(
                "BrowserPool stopped. Stats: %s",
                self._stats.to_dict(),
            )

    async def __aenter__(self) -> BrowserPool:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ──────────────────────────────────────────────────────────
    # Page Acquisition
    # ──────────────────────────────────────────────────────────

    async def acquire(
        self,
        timeout: float = 30.0,
        priority: AcquirePriority = AcquirePriority.NORMAL,
        session_id: str | None = None,
        context_options: dict[str, Any] | None = None,
    ) -> PooledPage:
        """
        Acquire a page from the pool.

        If an idle page is available, it is returned immediately.
        If the pool is at capacity, the request waits (with priority)
        until a page is released or the timeout expires.

        Args:
            timeout: Maximum seconds to wait for a page.
            priority: Request priority (higher = served first).
            session_id: Optional session binding.
            context_options: Additional context options for new pages.

        Returns:
            PooledPage wrapper containing the Playwright page.

        Raises:
            asyncio.TimeoutError: If no page becomes available in time.
            RuntimeError: If the pool is not started.
        """
        if not self._started:
            raise RuntimeError("Pool not started. Call start() first.")

        if self._shutting_down:
            raise RuntimeError("Pool is shutting down. Cannot acquire new pages.")

        wait_start = time.time()

        # Fast path: try to get an idle page immediately
        pooled = self._try_get_idle_page()
        if pooled is not None:
            self._mark_acquired(pooled)
            wait_ms = (time.time() - wait_start) * 1000
            self._stats.total_acquire_wait_ms += wait_ms
            await self._emit_event(PoolEventType.PAGE_ACQUIRED, {
                "page_id": pooled.page_id,
                "wait_ms": round(wait_ms, 2),
                "from": "idle",
            })
            return pooled

        # Try to create a new page if under capacity
        if self.total_pages < self._pool_config.max_pages:
            acquired = await self._semaphore_acquire(timeout=0.1)
            if acquired:
                try:
                    pooled = await self._create_page(
                        session_id=session_id,
                        context_options=context_options,
                    )
                    self._mark_acquired(pooled)
                    wait_ms = (time.time() - wait_start) * 1000
                    self._stats.total_acquire_wait_ms += wait_ms
                    await self._emit_event(PoolEventType.PAGE_ACQUIRED, {
                        "page_id": pooled.page_id,
                        "wait_ms": round(wait_ms, 2),
                        "from": "new",
                    })
                    return pooled
                except Exception:
                    self._semaphore.release()
                    raise

        # Slow path: wait for a page to become available
        self._stats.acquire_waits += 1
        logger.debug(
            "Pool at capacity (%d/%d). Waiting for page (priority=%s, timeout=%.1fs)...",
            self.active_pages,
            self.max_pages,
            priority.name,
            timeout,
        )

        loop = asyncio.get_event_loop()
        future: asyncio.Future[PooledPage] = loop.create_future()
        request = _AcquireRequest(
            future=future,
            priority=priority,
            session_id=session_id,
            context_options=context_options,
        )

        async with self._waiting_lock:
            self._waiting_requests.append(request)
            # Sort by priority (highest first), then by request time (FIFO)
            self._waiting_requests.sort(
                key=lambda r: (-r.priority.value, r.requested_at)
            )

        try:
            pooled = await asyncio.wait_for(future, timeout=timeout)
            wait_ms = (time.time() - wait_start) * 1000
            self._stats.total_acquire_wait_ms += wait_ms
            await self._emit_event(PoolEventType.PAGE_ACQUIRED, {
                "page_id": pooled.page_id,
                "wait_ms": round(wait_ms, 2),
                "from": "wait",
            })
            return pooled
        except asyncio.TimeoutError:
            self._stats.acquire_timeouts += 1
            await self._emit_event(PoolEventType.POOL_EXHAUSTED, {
                "timeout": timeout,
                "active_pages": self.active_pages,
                "max_pages": self.max_pages,
                "waiting_requests": len(self._waiting_requests),
            })
            raise asyncio.TimeoutError(
                f"Could not acquire page within {timeout}s. "
                f"Pool: {self.active_pages}/{self.max_pages} active, "
                f"{len(self._waiting_requests)} waiting."
            )
        finally:
            async with self._waiting_lock:
                self._waiting_requests = [
                    r for r in self._waiting_requests if r is not request
                ]

    async def release(self, pooled_or_page: PooledPage | Any) -> None:
        """
        Release a page back to the pool.

        The page is cleaned and made available for the next request.
        If there are waiting requests, the page is handed off directly.

        Args:
            pooled_or_page: PooledPage wrapper or raw Playwright Page.
        """
        # Resolve PooledPage
        if isinstance(pooled_or_page, PooledPage):
            pooled = pooled_or_page
        else:
            pooled = self._find_by_page(pooled_or_page)
            if pooled is None:
                logger.warning("Released an unmanaged page — ignoring")
                return

        use_ms = pooled.in_use_seconds * 1000
        self._stats.total_page_use_ms += use_ms
        self._stats.pages_released += 1

        # Remove from active set
        self._active_pages.pop(pooled.page_id, None)

        # Check if page should be recycled
        if self._should_recycle(pooled):
            await self._recycle_page(pooled)
            # Try to fulfill a waiting request with a new page
            await self._try_fulfill_waiting()
            return

        # Clean the page for reuse
        try:
            await self._clean_page(pooled)
        except Exception as e:
            logger.debug("Error cleaning page %s: %s", pooled.page_id, e)
            await self._recycle_page(pooled)
            await self._try_fulfill_waiting()
            return

        pooled.mark_released()

        # Check if there's a waiting request
        fulfilled = await self._try_fulfill_waiting_with(pooled)
        if not fulfilled:
            # Return to idle queue
            self._idle_pages.put_nowait(pooled)

        # Release semaphore slot
        self._semaphore.release()

        await self._emit_event(PoolEventType.PAGE_RELEASED, {
            "page_id": pooled.page_id,
            "use_ms": round(use_ms, 2),
            "navigation_count": pooled.navigation_count,
        })

    async def acquire_batch(
        self,
        count: int,
        timeout: float = 60.0,
        priority: AcquirePriority = AcquirePriority.NORMAL,
    ) -> list[PooledPage]:
        """
        Acquire multiple pages at once.

        Args:
            count: Number of pages to acquire.
            timeout: Maximum seconds to wait for all pages.
            priority: Request priority.

        Returns:
            List of PooledPage instances.

        Raises:
            asyncio.TimeoutError: If not all pages can be acquired in time.
        """
        if count > self._pool_config.max_pages:
            raise ValueError(
                f"Requested {count} pages but pool max is {self._pool_config.max_pages}"
            )

        pages: list[PooledPage] = []
        deadline = time.time() + timeout

        try:
            for i in range(count):
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError(
                        f"Batch acquire timed out after acquiring {i}/{count} pages"
                    )
                pooled = await self.acquire(
                    timeout=remaining,
                    priority=priority,
                )
                pages.append(pooled)
        except Exception:
            # Release any acquired pages on failure
            await self.release_batch(pages)
            raise

        return pages

    async def release_batch(self, pages: list[PooledPage | Any]) -> None:
        """Release multiple pages back to the pool."""
        for page in pages:
            try:
                await self.release(page)
            except Exception as e:
                logger.warning("Error releasing page in batch: %s", e)

    # ──────────────────────────────────────────────────────────
    # Pool Management
    # ──────────────────────────────────────────────────────────

    async def resize(self, max_pages: int) -> None:
        """
        Resize the pool capacity.

        If shrinking, excess idle pages are closed. Active pages
        are not affected.

        Args:
            max_pages: New maximum page count.
        """
        old_max = self._pool_config.max_pages
        self._pool_config.max_pages = max_pages

        # Adjust semaphore
        diff = max_pages - old_max
        if diff > 0:
            for _ in range(diff):
                self._semaphore.release()
        elif diff < 0:
            for _ in range(-diff):
                try:
                    self._semaphore._value = max(0, self._semaphore._value - 1)  # type: ignore[attr-defined]
                except Exception:
                    pass

        # Close excess idle pages if shrinking
        if max_pages < old_max:
            while self.total_pages > max_pages and not self._idle_pages.empty():
                try:
                    pooled = self._idle_pages.get_nowait()
                    await self._recycle_page(pooled)
                except asyncio.QueueEmpty:
                    break

        await self._emit_event(PoolEventType.POOL_RESIZED, {
            "old_max": old_max,
            "new_max": max_pages,
        })

        logger.info("Pool resized: %d → %d max pages", old_max, max_pages)

    async def drain(self, timeout: float = 30.0) -> None:
        """
        Drain the pool — close all idle pages and wait for active ones.

        Args:
            timeout: Maximum seconds to wait for active pages.
        """
        logger.info("Draining pool...")

        # Close all idle pages
        while not self._idle_pages.empty():
            try:
                pooled = self._idle_pages.get_nowait()
                await self._recycle_page(pooled)
            except asyncio.QueueEmpty:
                break

        # Wait for active pages
        if self._active_pages:
            deadline = time.time() + timeout
            while self._active_pages and time.time() < deadline:
                await asyncio.sleep(0.5)

        logger.info(
            "Pool drained. Active: %d, Total: %d",
            self.active_pages,
            self.total_pages,
        )

    # ──────────────────────────────────────────────────────────
    # Page Creation & Recycling
    # ──────────────────────────────────────────────────────────

    async def _create_page(
        self,
        session_id: str | None = None,
        context_options: dict[str, Any] | None = None,
    ) -> PooledPage:
        """Create a new page using the page factory."""
        if self._page_factory is None:
            raise RuntimeError(
                "No page_factory provided. Pass a factory callable to BrowserPool "
                "or use BrowserManager which provides its own factory."
            )

        page, context = await self._page_factory()

        pooled = PooledPage(
            page=page,
            context=context,
            state=PageState.IDLE,
            session_id=session_id,
        )

        self._all_pages[pooled.page_id] = pooled
        self._stats.pages_created += 1

        await self._emit_event(PoolEventType.PAGE_CREATED, {
            "page_id": pooled.page_id,
            "total_pages": self.total_pages,
        })

        return pooled

    async def _recycle_page(self, pooled: PooledPage) -> None:
        """Close and remove a page from the pool."""
        pooled.mark_recycling()
        await self._close_page(pooled)
        self._all_pages.pop(pooled.page_id, None)
        self._active_pages.pop(pooled.page_id, None)
        self._stats.pages_recycled += 1

        await self._emit_event(PoolEventType.PAGE_RECYCLED, {
            "page_id": pooled.page_id,
            "age_seconds": round(pooled.age_seconds, 1),
            "acquisition_count": pooled.acquisition_count,
            "navigation_count": pooled.navigation_count,
            "reason": self._get_recycle_reason(pooled),
        })

    async def _close_page(self, pooled: PooledPage) -> None:
        """Close the underlying Playwright page."""
        try:
            if not pooled.page.is_closed():
                await pooled.page.close()
        except Exception as e:
            logger.debug("Error closing page %s: %s", pooled.page_id, e)

        pooled.mark_closed()
        self._stats.pages_closed += 1

        await self._emit_event(PoolEventType.PAGE_CLOSED, {
            "page_id": pooled.page_id,
        })

    async def _clean_page(self, pooled: PooledPage) -> None:
        """Reset page state for reuse."""
        page = pooled.page

        if page.is_closed():
            raise RuntimeError("Page is closed")

        # Navigate to blank
        try:
            await page.goto("about:blank", timeout=5000)
        except Exception:
            pass

        # Clear storage
        try:
            await page.evaluate("""() => {
                try { localStorage.clear(); } catch(e) {}
                try { sessionStorage.clear(); } catch(e) {}
            }""")
        except Exception:
            pass

        # Clear cookies if not session-bound
        if not pooled.session_id and pooled.context:
            try:
                await pooled.context.clear_cookies()
            except Exception:
                pass

    def _should_recycle(self, pooled: PooledPage) -> bool:
        """Determine if a page should be recycled after release."""
        # Page is closed or unhealthy
        if not pooled.is_healthy:
            return True

        # Exceeded navigation count
        if pooled.navigation_count >= self._pool_config.recycle_after:
            return True

        # Exceeded TTL
        if pooled.age_seconds > self._pool_config.page_ttl:
            return True

        # Too many errors
        if pooled.error_count >= 5:
            return True

        return False

    def _get_recycle_reason(self, pooled: PooledPage) -> str:
        """Get a human-readable reason for recycling."""
        if not pooled.is_healthy:
            return "unhealthy"
        if pooled.navigation_count >= self._pool_config.recycle_after:
            return f"navigation_limit ({pooled.navigation_count})"
        if pooled.age_seconds > self._pool_config.page_ttl:
            return f"ttl_expired ({pooled.age_seconds:.0f}s)"
        if pooled.error_count >= 5:
            return f"error_limit ({pooled.error_count})"
        return "manual"

    # ──────────────────────────────────────────────────────────
    # Waiting Request Fulfillment
    # ──────────────────────────────────────────────────────────

    async def _try_fulfill_waiting(self) -> None:
        """Try to fulfill a waiting request by creating a new page."""
        async with self._waiting_lock:
            if not self._waiting_requests:
                return

            if self.total_pages >= self._pool_config.max_pages:
                return

            request = self._waiting_requests[0]

        try:
            pooled = await self._create_page(
                session_id=request.session_id,
                context_options=request.context_options,
            )
            self._mark_acquired(pooled)

            async with self._waiting_lock:
                if request in self._waiting_requests:
                    self._waiting_requests.remove(request)

            if not request.future.done():
                request.future.set_result(pooled)

        except Exception as e:
            logger.warning("Failed to create page for waiting request: %s", e)

    async def _try_fulfill_waiting_with(self, pooled: PooledPage) -> bool:
        """Try to hand off a released page to a waiting request."""
        async with self._waiting_lock:
            if not self._waiting_requests:
                return False

            request = self._waiting_requests.pop(0)

        if request.future.done():
            return False

        self._mark_acquired(pooled)
        request.future.set_result(pooled)
        return True

    # ──────────────────────────────────────────────────────────
    # Pre-warming
    # ──────────────────────────────────────────────────────────

    async def _pre_warm(self) -> None:
        """Pre-create pages for immediate availability."""
        count = self._pool_config.pre_warm
        logger.info("Pre-warming %d page(s)...", count)

        created = 0
        for i in range(count):
            if self._shutting_down:
                break
            try:
                await self._semaphore.acquire()
                pooled = await self._create_page()
                pooled.mark_released()
                self._idle_pages.put_nowait(pooled)
                created += 1
            except Exception as e:
                logger.warning("Pre-warm page %d failed: %s", i + 1, e)
                self._semaphore.release()

        await self._emit_event(PoolEventType.PRE_WARM_COMPLETE, {
            "requested": count,
            "created": created,
        })

        logger.info("Pre-warm complete: %d/%d pages created", created, count)

    # ──────────────────────────────────────────────────────────
    # Background Maintenance
    # ──────────────────────────────────────────────────────────

    def _start_maintenance_tasks(self) -> None:
        """Start background health check and recycler tasks."""
        interval = self._pool_config.health_check_interval
        if interval <= 0:
            return

        self._health_check_task = asyncio.create_task(
            self._health_check_loop(interval)
        )
        self._recycler_task = asyncio.create_task(
            self._recycler_loop(interval)
        )

    async def _stop_maintenance_tasks(self) -> None:
        """Cancel background maintenance tasks."""
        for task in (self._health_check_task, self._recycler_task, self._pre_warm_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._health_check_task = None
        self._recycler_task = None
        self._pre_warm_task = None

    async def _health_check_loop(self, interval: int) -> None:
        """Periodically validate page health."""
        while self._started and not self._shutting_down:
            try:
                await asyncio.sleep(interval)
                if not self._started:
                    break

                unhealthy = []
                for pooled in list(self._all_pages.values()):
                    if pooled.state == PageState.IDLE and not pooled.is_healthy:
                        unhealthy.append(pooled)

                if unhealthy:
                    logger.warning(
                        "Health check: %d unhealthy page(s) found",
                        len(unhealthy),
                    )
                    self._stats.health_check_failures += len(unhealthy)

                    for pooled in unhealthy:
                        # Remove from idle queue
                        await self._recycle_page(pooled)

                    await self._emit_event(PoolEventType.HEALTH_CHECK_FAILED, {
                        "unhealthy_count": len(unhealthy),
                    })

                    # Replenish pool
                    for _ in unhealthy:
                        await self._try_fulfill_waiting()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error: %s", e)

    async def _recycler_loop(self, interval: int) -> None:
        """Periodically recycle stale idle pages."""
        while self._started and not self._shutting_down:
            try:
                await asyncio.sleep(interval)
                if not self._started:
                    break

                recycled = 0
                idle_timeout = self._pool_config.idle_timeout

                # Check idle pages in the queue
                pages_to_check: list[PooledPage] = []
                while not self._idle_pages.empty():
                    try:
                        pages_to_check.append(self._idle_pages.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                for pooled in pages_to_check:
                    if pooled.idle_seconds > idle_timeout or not pooled.is_healthy:
                        await self._recycle_page(pooled)
                        recycled += 1
                    else:
                        # Put back
                        self._idle_pages.put_nowait(pooled)

                if recycled > 0:
                    logger.debug("Recycler: cleaned %d stale page(s)", recycled)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Recycler error: %s", e)

    # ──────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────

    def _try_get_idle_page(self) -> PooledPage | None:
        """Try to get a healthy idle page from the queue (non-blocking)."""
        attempts = self._idle_pages.qsize()
        for _ in range(attempts):
            try:
                pooled = self._idle_pages.get_nowait()
            except asyncio.QueueEmpty:
                return None

            if pooled.is_healthy and pooled.state == PageState.IDLE:
                return pooled
            else:
                # Unhealthy — schedule recycling (fire and forget)
                asyncio.create_task(self._recycle_page(pooled))

        return None

    def _mark_acquired(self, pooled: PooledPage) -> None:
        """Mark a page as acquired and track it."""
        pooled.mark_acquired()
        self._active_pages[pooled.page_id] = pooled
        self._stats.pages_acquired += 1

    def _find_by_page(self, page: Any) -> PooledPage | None:
        """Find a PooledPage by its underlying Playwright page."""
        for pooled in self._all_pages.values():
            if pooled.page == page:
                return pooled
        return None

    async def _semaphore_acquire(self, timeout: float = 0.0) -> bool:
        """Try to acquire the semaphore with optional timeout."""
        if timeout <= 0:
            if self._semaphore._value > 0:  # type: ignore[attr-defined]
                await self._semaphore.acquire()
                return True
            return False

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _emit_event(
        self,
        event_type: PoolEventType,
        data: dict[str, Any],
    ) -> None:
        """Emit a pool event to the registered callback."""
        if self._on_event:
            try:
                await self._on_event(event_type, data)
            except Exception as e:
                logger.debug("Event callback error: %s", e)

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """
        Get detailed pool diagnostics.

        Returns:
            Dictionary with pool state, page details, and stats.
        """
        pages = [p.to_dict() for p in self._all_pages.values()]

        return {
            "started": self._started,
            "shutting_down": self._shutting_down,
            "max_pages": self._pool_config.max_pages,
            "total_pages": self.total_pages,
            "active_pages": self.active_pages,
            "idle_pages": self.idle_pages,
            "waiting_requests": self.waiting_requests,
            "utilization": round(self.utilization, 3),
            "stats": self._stats.to_dict(),
            "pages": pages,
            "config": {
                "pre_warm": self._pool_config.pre_warm,
                "page_ttl": self._pool_config.page_ttl,
                "idle_timeout": self._pool_config.idle_timeout,
                "recycle_after": self._pool_config.recycle_after,
                "health_check_interval": self._pool_config.health_check_interval,
            },
        }

    def get_page_info(self, page_id: str) -> dict[str, Any] | None:
        """Get info for a specific page by ID."""
        pooled = self._all_pages.get(page_id)
        if pooled is None:
            return None
        return pooled.to_dict()

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"BrowserPool(status={status}, "
            f"pages={self.total_pages}/{self.max_pages}, "
            f"active={self.active_pages}, idle={self.idle_pages})"
        )
