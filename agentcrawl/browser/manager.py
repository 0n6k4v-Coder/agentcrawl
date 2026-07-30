"""
AgentCrawl — Browser Manager
===============================

Manages the complete Playwright browser lifecycle including launch,
context creation, page acquisition, stealth injection, session
persistence, and graceful shutdown.

The BrowserManager is the single entry point for all browser operations
within AgentCrawl. It is used by both Package Mode (direct import) and
Server Mode (FastAPI workers) through the shared CrawlEngine.

Architecture:
    BrowserManager
    ├── Playwright instance (async)
    ├── Browser instance (Chromium / Firefox / WebKit)
    ├── BrowserContext pool
    │   ├── Context 1 (session A)
    │   │   ├── Page 1
    │   │   └── Page 2
    │   └── Context 2 (session B)
    │       └── Page 3
    ├── StealthAdapter (anti-bot injection)
    ├── ProxyManager (rotation)
    └── SessionStore (persistence)

Usage:
    from agentcrawl.browser.manager import BrowserManager
    from agentcrawl.browser.config import BrowserConfig

    # Async context manager (recommended)
    async with BrowserManager(BrowserConfig(headless=True)) as manager:
        page = await manager.acquire_page()
        try:
            await page.goto("https://example.com")
            content = await page.content()
        finally:
            await manager.release_page(page)

    # Manual lifecycle
    manager = BrowserManager(BrowserConfig())
    await manager.start()
    page = await manager.acquire_page()
    # ... use page ...
    await manager.release_page(page)
    await manager.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.browser.config import (
    BrowserConfig,
    BrowserType,
)


# Helper functions for async file I/O using asyncio.to_thread
async def _async_path_exists(path: str) -> bool:
    """Check if path exists using asyncio.to_thread."""
    return await asyncio.to_thread(os.path.exists, path)


async def _async_path_join(*args: str) -> str:
    """Join paths using asyncio.to_thread."""
    return await asyncio.to_thread(os.path.join, *args)


async def _async_makedirs(path: str, exist_ok: bool = True) -> None:
    """Create directories using asyncio.to_thread."""
    await asyncio.to_thread(os.makedirs, path, exist_ok=exist_ok)


async def _async_remove(path: str) -> None:
    """Remove file using asyncio.to_thread."""
    await asyncio.to_thread(os.remove, path)


async def _async_listdir(path: str) -> list[str]:
    """List directory using asyncio.to_thread."""
    return await asyncio.to_thread(os.listdir, path)


async def _async_write_file(path: str, content: str, encoding: str = "utf-8") -> None:
    """Write file using asyncio.to_thread."""

    def _write():
        with open(path, "w", encoding=encoding) as f:
            f.write(content)

    await asyncio.to_thread(_write)


async def _async_read_json(path: str) -> Any:
    """Read and parse JSON file using asyncio.to_thread."""

    def _read():
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    return await asyncio.to_thread(_read)


async def _async_write_json(path: str, data: Any, encoding: str = "utf-8") -> None:
    """Write JSON file using asyncio.to_thread."""

    def _write():
        with open(path, "w", encoding=encoding) as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write)


logger = logging.getLogger("agentcrawl.browser.manager")


# ══════════════════════════════════════════════════════════════
# Exceptions
# ══════════════════════════════════════════════════════════════


class BrowserManagerError(Exception):
    """Base exception for BrowserManager errors."""

    pass


class BrowserNotStartedError(BrowserManagerError):
    """Raised when trying to use the manager before start()."""

    pass


class BrowserLaunchError(BrowserManagerError):
    """Raised when the browser fails to launch."""

    pass


class PageAcquisitionError(BrowserManagerError):
    """Raised when a page cannot be acquired from the pool."""

    pass


class PoolExhaustedError(BrowserManagerError):
    """Raised when all pages in the pool are in use."""

    pass


# ══════════════════════════════════════════════════════════════
# Tracked Resources
# ══════════════════════════════════════════════════════════════


@dataclass
class _TrackedPage:
    """Internal wrapper for a managed Playwright page."""

    page: Any
    context: Any
    page_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    navigation_count: int = 0
    in_use: bool = False
    session_id: str | None = None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_used_at

    @property
    def needs_recycle(self) -> bool:
        return False  # Determined by pool config


@dataclass
class _TrackedContext:
    """Internal wrapper for a managed Playwright browser context."""

    context: Any
    context_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)
    session_id: str | None = None
    pages: list[_TrackedPage] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# Browser Manager
# ══════════════════════════════════════════════════════════════


class BrowserManager:
    """
    Manages the Playwright browser lifecycle and page pool.

    Provides a high-level interface for acquiring and releasing
    browser pages with automatic stealth injection, proxy rotation,
    session persistence, and resource cleanup.

    Args:
        config: Browser configuration. Uses default if None.

    Example:
        >>> async with BrowserManager(BrowserConfig(headless=True)) as manager:
        ...     page = await manager.acquire_page()
        ...     try:
        ...         await page.goto("https://example.com")
        ...         html = await page.content()
        ...     finally:
        ...         await manager.release_page(page)
    """

    def __init__(self, config: BrowserConfig | None = None):
        self._config = config or BrowserConfig()
        self._playwright: Any = None
        self._browser: Any = None
        self._started = False
        self._starting = False
        self._lock = asyncio.Lock()

        # Resource tracking
        self._contexts: dict[str, _TrackedContext] = {}
        self._pages: dict[str, _TrackedPage] = {}
        self._available_pages: asyncio.Queue[_TrackedPage] = asyncio.Queue()

        # Stealth adapter (lazy import to avoid circular deps)
        self._stealth_adapter: Any = None

        # Proxy rotation state
        self._proxy_index = 0

        # Stats
        self._stats = {
            "pages_created": 0,
            "pages_recycled": 0,
            "pages_acquired": 0,
            "pages_released": 0,
            "contexts_created": 0,
            "errors": 0,
        }

        # Background tasks
        self._health_check_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def config(self) -> BrowserConfig:
        """Current browser configuration."""
        return self._config

    @property
    def is_started(self) -> bool:
        """Whether the browser has been launched."""
        return self._started

    @property
    def browser(self) -> Any:
        """The underlying Playwright Browser instance."""
        if not self._started or self._browser is None:
            raise BrowserNotStartedError(
                "Browser not started. Call start() or use 'async with' first."
            )
        return self._browser

    @property
    def active_page_count(self) -> int:
        """Number of pages currently in use."""
        return sum(1 for p in self._pages.values() if p.in_use)

    @property
    def total_page_count(self) -> int:
        """Total number of managed pages (in use + available)."""
        return len(self._pages)

    @property
    def available_page_count(self) -> int:
        """Number of pages available for acquisition."""
        return self._available_pages.qsize()

    @property
    def stats(self) -> dict[str, int]:
        """Manager statistics."""
        return {
            **self._stats,
            "active_pages": self.active_page_count,
            "total_pages": self.total_page_count,
            "available_pages": self.available_page_count,
            "active_contexts": len(self._contexts),
        }

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Launch the browser and initialize the page pool.

        This method is idempotent — calling it multiple times
        has no effect if the browser is already running.

        Raises:
            BrowserLaunchError: If the browser fails to launch.
        """
        async with self._lock:
            if self._started or self._starting:
                return

            self._starting = True
            logger.info(
                "Starting BrowserManager (browser=%s, headless=%s, stealth=%s)",
                self._config.browser_type,
                self._config.headless,
                self._config.stealth,
            )

            try:
                # 1. Launch Playwright
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()

                # 2. Select browser engine
                launcher = self._get_launcher()

                # 3. Build launch options
                launch_opts = self._config.to_launch_options()
                logger.debug("Launch options: %s", launch_opts)

                # 4. Launch browser
                self._browser = await launcher.launch(**launch_opts)
                self._started = True

                logger.info(
                    "Browser launched: %s (version=%s)",
                    self._config.browser_type,
                    self._browser.version,
                )

                # 5. Initialize stealth adapter
                if self._config.stealth:
                    await self._init_stealth()

                # 6. Pre-warm page pool
                await self._pre_warm_pool()

                # 7. Start background tasks
                self._start_background_tasks()

            except Exception as e:
                self._stats["errors"] += 1
                # Cleanup on failure
                await self._cleanup_playwright()
                raise BrowserLaunchError(
                    f"Failed to launch {self._config.browser_type}: {e}"
                ) from e
            finally:
                self._starting = False

    async def stop(self) -> None:
        """
        Gracefully shut down the browser and release all resources.

        Closes all pages, contexts, and the browser instance.
        Persists session state if configured.
        """
        async with self._lock:
            if not self._started:
                return

            logger.info("Stopping BrowserManager...")

            # 1. Cancel background tasks
            await self._stop_background_tasks()

            # 2. Persist sessions
            await self._persist_sessions()

            # 3. Close all pages
            for tracked in list(self._pages.values()):
                try:
                    if not tracked.page.is_closed():
                        await tracked.page.close()
                except Exception as e:
                    logger.debug("Error closing page %s: %s", tracked.page_id, e)
            self._pages.clear()

            # 4. Close all contexts
            for tracked_ctx in list(self._contexts.values()):
                try:
                    await tracked_ctx.context.close()
                except Exception as e:
                    logger.debug("Error closing context %s: %s", tracked_ctx.context_id, e)
            self._contexts.clear()

            # 5. Drain available pages queue
            while not self._available_pages.empty():
                try:
                    self._available_pages.get_nowait()
                except asyncio.QueueEmpty:
                    break

            # 6. Close browser
            if self._browser:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug("Error closing browser: %s", e)
                self._browser = None

            # 7. Stop Playwright
            await self._cleanup_playwright()

            self._started = False
            logger.info(
                "BrowserManager stopped. Stats: %s",
                self._stats,
            )

    async def restart(self) -> None:
        """Restart the browser (stop + start)."""
        logger.info("Restarting BrowserManager...")
        await self.stop()
        await self.start()

    async def __aenter__(self) -> BrowserManager:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ──────────────────────────────────────────────────────────
    # Page Acquisition & Release
    # ──────────────────────────────────────────────────────────

    async def acquire_page(
        self,
        session_id: str | None = None,
        timeout: float = 30.0,
        new_context: bool = False,
        context_options: dict[str, Any] | None = None,
    ) -> Any:
        """
        Acquire a browser page from the pool.

        If a pre-warmed page is available, it is returned immediately.
        Otherwise, a new page is created (up to the pool limit).

        Args:
            session_id: Optional session ID for context reuse.
            timeout: Maximum seconds to wait for an available page.
            new_context: Force creation of a new browser context.
            context_options: Additional context options to override defaults.

        Returns:
            Playwright Page instance.

        Raises:
            BrowserNotStartedError: If the browser is not running.
            PoolExhaustedError: If the pool is full and no pages are available.
            PageAcquisitionError: If page creation fails.
        """
        if not self._started:
            raise BrowserNotStartedError("Browser not started")

        # Try to get an available page from the pool
        if not new_context and session_id is None:
            try:
                tracked = self._available_pages.get_nowait()

                # Validate the page is still usable
                if self._is_page_healthy(tracked):
                    tracked.in_use = True
                    tracked.last_used_at = time.time()
                    self._stats["pages_acquired"] += 1
                    logger.debug("Acquired pooled page %s", tracked.page_id)
                    return tracked.page
                else:
                    # Page is stale — recycle it
                    await self._recycle_page(tracked)
            except asyncio.QueueEmpty:
                pass

        # Check pool limits
        if self.total_page_count >= self._config.pool.max_pages:
            # Wait for a page to become available
            try:
                tracked = await asyncio.wait_for(
                    self._available_pages.get(),
                    timeout=timeout,
                )
                if self._is_page_healthy(tracked):
                    tracked.in_use = True
                    tracked.last_used_at = time.time()
                    self._stats["pages_acquired"] += 1
                    return tracked.page
                else:
                    await self._recycle_page(tracked)
            except asyncio.TimeoutError as err:
                raise PoolExhaustedError(
                    f"No pages available (max={self._config.pool.max_pages}, "
                    f"active={self.active_page_count}). "
                    f"Consider increasing pool.max_pages or request timeout."
                ) from err

        # Create a new page
        try:
            tracked = await self._create_page(
                session_id=session_id,
                new_context=new_context,
                context_options=context_options,
            )
            tracked.in_use = True
            self._stats["pages_acquired"] += 1
            self._stats["pages_created"] += 1
            logger.debug(
                "Created new page %s (total=%d, active=%d)",
                tracked.page_id,
                self.total_page_count,
                self.active_page_count,
            )
            return tracked.page
        except Exception as e:
            self._stats["errors"] += 1
            raise PageAcquisitionError(f"Failed to create page: {e}") from e

    async def release_page(self, page: Any) -> None:
        """
        Release a page back to the pool.

        The page is cleaned (cookies cleared if no session, navigation
        history reset) and made available for reuse.

        Args:
            page: The Playwright Page instance to release.
        """
        tracked = self._find_tracked_page(page)
        if tracked is None:
            logger.warning("Attempted to release an unmanaged page")
            return

        tracked.in_use = False
        tracked.last_used_at = time.time()
        self._stats["pages_released"] += 1

        # Check if page needs recycling
        if self._should_recycle(tracked):
            await self._recycle_page(tracked)
            return

        # Clean page state for reuse
        try:
            await self._clean_page(tracked)
        except Exception as e:
            logger.debug("Error cleaning page %s: %s", tracked.page_id, e)
            await self._recycle_page(tracked)
            return

        # Return to pool
        self._available_pages.put_nowait(tracked)
        logger.debug(
            "Released page %s back to pool (available=%d)",
            tracked.page_id,
            self.available_page_count,
        )

    async def acquire_context(
        self,
        session_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        """
        Acquire a dedicated browser context (for isolated sessions).

        Args:
            session_id: Optional session identifier for context reuse.
            options: Additional context options.

        Returns:
            Playwright BrowserContext instance.
        """
        if not self._started:
            raise BrowserNotStartedError("Browser not started")

        # Reuse existing context for session
        if session_id:
            for tracked_ctx in self._contexts.values():
                if tracked_ctx.session_id == session_id:
                    return tracked_ctx.context

        # Create new context
        tracked_ctx = await self._create_context(
            session_id=session_id,
            options=options,
        )
        return tracked_ctx.context

    # ──────────────────────────────────────────────────────────
    # Context Management
    # ──────────────────────────────────────────────────────────

    async def _create_context(
        self,
        session_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> _TrackedContext:
        """Create a new browser context with configured options."""
        context_opts = self._config.to_context_options()

        # Apply proxy rotation
        if self._config.proxy and self._config.proxy.rotation.value != "none":
            proxy = self._get_next_proxy()
            if proxy:
                context_opts["proxy"] = proxy

        # Override with custom options
        if options:
            context_opts.update(options)

        # Session persistence — load storage state
        if session_id and self._config.session.persist:
            storage_path = await self._get_session_path(session_id)
            if await _async_path_exists(storage_path):
                context_opts["storageState"] = storage_path
                logger.debug("Restored session state from %s", storage_path)

        context = await self._browser.new_context(**context_opts)

        # Apply stealth scripts to context
        if self._config.stealth and self._stealth_adapter:
            await self._stealth_adapter.apply_to_context(context)

        # Set default timeouts
        context.set_default_timeout(self._config.timeout)
        context.set_default_navigation_timeout(self._config.navigation_timeout)

        tracked = _TrackedContext(
            context=context,
            session_id=session_id,
        )
        self._contexts[tracked.context_id] = tracked
        self._stats["contexts_created"] += 1

        logger.debug(
            "Created context %s (session=%s, total=%d)",
            tracked.context_id,
            session_id or "anonymous",
            len(self._contexts),
        )

        return tracked

    async def close_context(self, context: Any) -> None:
        """Close a specific browser context and all its pages."""
        tracked_ctx = None
        for tc in self._contexts.values():
            if tc.context == context:
                tracked_ctx = tc
                break

        if tracked_ctx is None:
            logger.warning("Attempted to close an unmanaged context")
            return

        # Close all pages in this context
        for tracked_page in list(tracked_ctx.pages):
            try:
                if not tracked_page.page.is_closed():
                    await tracked_page.page.close()
            except Exception:
                logger.debug("Ignored exception", exc_info=True)
            self._pages.pop(tracked_page.page_id, None)

        # Persist session if needed
        if tracked_ctx.session_id and self._config.session.persist:
            await self._save_session(tracked_ctx)

        # Close context
        try:
            await tracked_ctx.context.close()
        except Exception as e:
            logger.debug("Error closing context: %s", e)

        self._contexts.pop(tracked_ctx.context_id, None)
        logger.debug("Closed context %s", tracked_ctx.context_id)

    # ──────────────────────────────────────────────────────────
    # Page Creation & Recycling
    # ──────────────────────────────────────────────────────────

    async def _create_page(
        self,
        session_id: str | None = None,
        new_context: bool = False,
        context_options: dict[str, Any] | None = None,
    ) -> _TrackedPage:
        """Create a new page in a new or existing context."""
        # Get or create context
        if new_context or session_id:
            tracked_ctx = await self._create_context(
                session_id=session_id,
                options=context_options,
            )
        elif self._contexts:
            # Reuse most recent context
            tracked_ctx = list(self._contexts.values())[-1]
        else:
            tracked_ctx = await self._create_context()

        # Create page
        page = await tracked_ctx.context.new_page()

        # Apply stealth to page
        if self._config.stealth and self._stealth_adapter:
            await self._stealth_adapter.apply_to_page(page)

        # Set page-level timeouts
        page.set_default_timeout(self._config.timeout)
        page.set_default_navigation_timeout(self._config.navigation_timeout)

        # Block unnecessary resources for performance
        if self._config.stealth:
            await self._setup_resource_blocking(page)

        tracked = _TrackedPage(
            page=page,
            context=tracked_ctx.context,
            session_id=session_id,
        )
        tracked_ctx.pages.append(tracked)
        self._pages[tracked.page_id] = tracked

        return tracked

    async def _recycle_page(self, tracked: _TrackedPage) -> None:
        """Close a page and remove it from tracking."""
        try:
            if not tracked.page.is_closed():
                await tracked.page.close()
        except Exception as e:
            logger.debug("Error closing page during recycle: %s", e)

        self._pages.pop(tracked.page_id, None)

        # Remove from context tracking
        for tracked_ctx in self._contexts.values():
            tracked_ctx.pages = [p for p in tracked_ctx.pages if p.page_id != tracked.page_id]

        self._stats["pages_recycled"] += 1
        logger.debug("Recycled page %s", tracked.page_id)

    async def _clean_page(self, tracked: _TrackedPage) -> None:
        """Clean page state for reuse (clear cookies, storage, history)."""
        page = tracked.page

        if page.is_closed():
            return

        # Navigate to blank page to reset state
        try:
            await page.goto("about:blank", timeout=5000)
        except Exception:
            logger.debug("Ignored exception", exc_info=True)

        # Clear cookies if not session-bound
        if not tracked.session_id:
            try:
                context = tracked.context
                await context.clear_cookies()
            except Exception:
                logger.debug("Ignored exception", exc_info=True)

        # Clear localStorage and sessionStorage
        try:
            await page.evaluate("""() => {
                try { localStorage.clear(); } catch(e) {}
                try { sessionStorage.clear(); } catch(e) {}
            }""")
        except Exception:
            logger.debug("Ignored exception", exc_info=True)

    def _is_page_healthy(self, tracked: _TrackedPage) -> bool:
        """Check if a page is still usable."""
        if tracked.page.is_closed():
            return False

        # Check TTL
        return not tracked.age_seconds > self._config.pool.page_ttl

    def _should_recycle(self, tracked: _TrackedPage) -> bool:
        """Determine if a page should be recycled after release."""
        # Exceeded navigation count
        if tracked.navigation_count >= self._config.pool.recycle_after:
            return True

        # Exceeded TTL
        if tracked.age_seconds > self._config.pool.page_ttl:
            return True

        # Page is closed
        return bool(tracked.page.is_closed())

    # ──────────────────────────────────────────────────────────
    # Pool Management
    # ──────────────────────────────────────────────────────────

    async def _pre_warm_pool(self) -> None:
        """Pre-create pages for immediate availability."""
        pre_warm = self._config.pool.pre_warm
        if pre_warm <= 0:
            return

        logger.info("Pre-warming page pool with %d page(s)...", pre_warm)

        for i in range(pre_warm):
            try:
                tracked = await self._create_page()
                tracked.in_use = False
                self._available_pages.put_nowait(tracked)
                self._stats["pages_created"] += 1
            except Exception as e:
                logger.warning("Failed to pre-warm page %d: %s", i + 1, e)

        logger.info(
            "Pool pre-warmed: %d page(s) available",
            self._available_pages.qsize(),
        )

    async def resize_pool(self, max_pages: int) -> None:
        """
        Resize the page pool.

        Args:
            max_pages: New maximum number of concurrent pages.
        """
        old_max = self._config.pool.max_pages
        self._config.pool.max_pages = max_pages
        logger.info("Pool resized: %d → %d max pages", old_max, max_pages)

        # If shrinking, close excess idle pages
        if max_pages < old_max:
            while self.total_page_count > max_pages and not self._available_pages.empty():
                try:
                    tracked = self._available_pages.get_nowait()
                    await self._recycle_page(tracked)
                except asyncio.QueueEmpty:
                    break

    # ──────────────────────────────────────────────────────────
    # Stealth
    # ──────────────────────────────────────────────────────────

    async def _init_stealth(self) -> None:
        """Initialize the stealth adapter."""
        try:
            from agentcrawl.browser.stealth import StealthAdapter

            self._stealth_adapter = StealthAdapter(self._config)
            logger.info("Stealth adapter initialized")
        except ImportError:
            logger.warning("StealthAdapter not available. Stealth mode disabled.")
            self._stealth_adapter = None

    async def _setup_resource_blocking(self, page: Any) -> None:
        """Block unnecessary resources for performance."""
        blocked_types = {"image", "media", "font", "stylesheet"}

        async def _route_handler(route: Any) -> None:
            request = route.request
            if request.resource_type in blocked_types:
                await route.abort()
            else:
                await route.continue_()

        # Only block if not explicitly disabled
        # (some scraping needs images/fonts for layout accuracy)
        # This is a lightweight default — can be overridden per-request
        pass  # Resource blocking is opt-in via CrawlerConfig

    # ──────────────────────────────────────────────────────────
    # Proxy Rotation
    # ──────────────────────────────────────────────────────────

    def _get_next_proxy(self) -> dict[str, Any] | None:
        """Get the next proxy from the rotation pool."""
        proxy_config = self._config.proxy
        if not proxy_config:
            return None

        if not proxy_config.proxy_list:
            return proxy_config.to_playwright_dict()

        strategy = proxy_config.rotation

        if strategy.value == "none":
            return proxy_config.to_playwright_dict()

        if strategy.value == "round_robin":
            proxy_url = proxy_config.proxy_list[self._proxy_index % len(proxy_config.proxy_list)]
            self._proxy_index += 1
            return {"server": proxy_url}

        if strategy.value == "random":
            import secrets

            proxy_url = secrets.choice(proxy_config.proxy_list)
            return {"server": proxy_url}

        if strategy.value == "least_used":
            # Simple implementation: round-robin as fallback
            proxy_url = proxy_config.proxy_list[self._proxy_index % len(proxy_config.proxy_list)]
            self._proxy_index += 1
            return {"server": proxy_url}

        return proxy_config.to_playwright_dict()

    # ──────────────────────────────────────────────────────────
    # Session Persistence
    # ──────────────────────────────────────────────────────────

    async def _get_session_path(self, session_id: str) -> str:
        """Get the file path for a session's storage state."""
        storage_dir = self._config.session.storage_dir
        # Note: we don't create dir here as it's sync; caller should ensure it exists
        return await _async_path_join(storage_dir, f"{session_id}.json")

    async def _save_session(self, tracked_ctx: _TrackedContext) -> None:
        """Save a context's storage state to disk."""
        if not tracked_ctx.session_id:
            return

        path = await self._get_session_path(tracked_ctx.session_id)
        try:
            storage_state = await tracked_ctx.context.storage_state()
            await _async_write_json(path, storage_state)
            logger.debug("Saved session state: %s", path)
        except Exception as e:
            logger.warning("Failed to save session %s: %s", tracked_ctx.session_id, e)

    async def _persist_sessions(self) -> None:
        """Persist all active sessions to disk."""
        if not self._config.session.persist:
            return

        for tracked_ctx in self._contexts.values():
            if tracked_ctx.session_id:
                await self._save_session(tracked_ctx)

    async def clear_session(self, session_id: str) -> None:
        """Delete a persisted session."""
        path = await self._get_session_path(session_id)
        if await _async_path_exists(path):
            await _async_remove(path)
            logger.info("Cleared session: %s", session_id)

        # Close active context for this session
        for tracked_ctx in list(self._contexts.values()):
            if tracked_ctx.session_id == session_id:
                await self.close_context(tracked_ctx.context)

    async def list_sessions(self) -> list[str]:
        """List all persisted session IDs."""
        storage_dir = self._config.session.storage_dir
        if not await _async_path_exists(storage_dir):
            return []
        files = await _async_listdir(storage_dir)
        return [f.replace(".json", "") for f in files if f.endswith(".json")]

    # ──────────────────────────────────────────────────────────
    # Background Tasks
    # ──────────────────────────────────────────────────────────

    def _start_background_tasks(self) -> None:
        """Start background health check and cleanup tasks."""
        interval = self._config.pool.health_check_interval
        if interval > 0:
            self._health_check_task = asyncio.create_task(self._health_check_loop(interval))
            self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval))

    async def _stop_background_tasks(self) -> None:
        """Cancel background tasks."""
        for task in (self._health_check_task, self._cleanup_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._health_check_task = None
        self._cleanup_task = None

    async def _health_check_loop(self, interval: int) -> None:
        """Periodically check browser health."""
        while self._started:
            try:
                await asyncio.sleep(interval)
                if not self._started:
                    break

                # Check browser is alive
                if self._browser and not self._browser.is_connected():
                    logger.error("Browser disconnected! Attempting restart...")
                    await self.restart()
                    return

                logger.debug(
                    "Health check OK: %d pages (%d active), %d contexts",
                    self.total_page_count,
                    self.active_page_count,
                    len(self._contexts),
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error: %s", e)

    async def _cleanup_loop(self, interval: int) -> None:
        """Periodically clean up stale pages and contexts."""
        while self._started:
            try:
                await asyncio.sleep(interval)
                if not self._started:
                    break

                cleaned = 0

                # Clean up idle pages
                for tracked in list(self._pages.values()):
                    if not tracked.in_use and tracked.idle_seconds > self._config.pool.idle_timeout:
                        await self._recycle_page(tracked)
                        cleaned += 1

                # Clean up empty contexts
                for tracked_ctx in list(self._contexts.values()):
                    if not tracked_ctx.pages:
                        with contextlib.suppress(Exception):
                            await tracked_ctx.context.close()
                        self._contexts.pop(tracked_ctx.context_id, None)
                        cleaned += 1

                if cleaned > 0:
                    logger.debug("Cleanup: removed %d stale resource(s)", cleaned)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Cleanup error: %s", e)

    # ──────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────

    def _get_launcher(self) -> Any:
        """Get the Playwright browser launcher for the configured engine."""
        if self._playwright is None:
            raise BrowserNotStartedError("Playwright not initialized")

        browser_type = self._config.browser_type
        if isinstance(browser_type, str):
            browser_type = BrowserType(browser_type)

        launchers = {
            BrowserType.CHROMIUM: self._playwright.chromium,
            BrowserType.FIREFOX: self._playwright.firefox,
            BrowserType.WEBKIT: self._playwright.webkit,
        }

        launcher = launchers.get(browser_type)
        if launcher is None:
            raise BrowserLaunchError(f"Unsupported browser type: {browser_type}")
        return launcher

    def _find_tracked_page(self, page: Any) -> _TrackedPage | None:
        """Find the tracked wrapper for a Playwright page."""
        for tracked in self._pages.values():
            if tracked.page == page:
                return tracked
        return None

    async def _cleanup_playwright(self) -> None:
        """Stop the Playwright instance."""
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.debug("Error stopping Playwright: %s", e)
            self._playwright = None

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """
        Get detailed diagnostics for debugging.

        Returns:
            Dictionary with manager state, pool info, and stats.
        """
        pages_info = []
        for tracked in self._pages.values():
            pages_info.append(
                {
                    "page_id": tracked.page_id,
                    "in_use": tracked.in_use,
                    "age_seconds": round(tracked.age_seconds, 1),
                    "idle_seconds": round(tracked.idle_seconds, 1),
                    "navigation_count": tracked.navigation_count,
                    "session_id": tracked.session_id,
                    "is_closed": tracked.page.is_closed(),
                }
            )

        contexts_info = []
        for tracked_ctx in self._contexts.values():
            contexts_info.append(
                {
                    "context_id": tracked_ctx.context_id,
                    "session_id": tracked_ctx.session_id,
                    "page_count": len(tracked_ctx.pages),
                    "age_seconds": round(time.time() - tracked_ctx.created_at, 1),
                }
            )

        return {
            "started": self._started,
            "config": {
                "browser_type": str(self._config.browser_type),
                "headless": self._config.headless,
                "stealth": self._config.stealth,
                "pool": self._config.pool.to_dict(),
            },
            "stats": self.stats,
            "pages": pages_info,
            "contexts": contexts_info,
            "browser_connected": (self._browser.is_connected() if self._browser else False),
        }

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"BrowserManager(browser={self._config.browser_type}, "
            f"status={status}, pages={self.total_page_count})"
        )
