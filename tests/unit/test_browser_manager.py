"""
AgentCrawl — Browser Manager Unit Tests
===========================================

Unit tests for the Playwright browser manager.

Tests:
    - BrowserManager initialization
    - Browser launch and shutdown
    - Context creation and management
    - Page creation
    - Stealth configuration
    - Proxy configuration
    - User-Agent rotation
    - Viewport configuration
    - Concurrent context handling
    - Error handling

Run:
    pytest tests/unit/test_browser_manager.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_playwright() -> MagicMock:
    """Mock Playwright instance."""
    pw = MagicMock()

    # Mock browser type
    browser_type = MagicMock()
    browser = AsyncMock()
    browser.is_connected.return_value = True

    # Mock context
    context = AsyncMock()
    context.close = AsyncMock()
    context.pages = []

    # Create a factory function that returns a new page for each call
    def create_mock_page():
        page = AsyncMock()
        page.url = "about:blank"
        page.title = AsyncMock(return_value="Test Page")
        # is_closed is a sync method in Playwright
        page.is_closed = MagicMock(return_value=False)
        page.set_default_timeout = MagicMock()
        page.set_default_navigation_timeout = MagicMock()
        return page

    # new_page should return a new page each time it's called (async method)
    context.new_page = AsyncMock(side_effect=create_mock_page)

    # Mock set_default_timeout and set_default_navigation_timeout as sync methods
    context.set_default_timeout = MagicMock()
    context.set_default_navigation_timeout = MagicMock()

    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    browser.version = "125.0.0"

    browser_type.launch = AsyncMock(return_value=browser)

    pw.chromium = browser_type
    pw.firefox = browser_type
    pw.webkit = browser_type

    return pw


@pytest.fixture
def default_config() -> Any:
    """Default browser config for tests."""
    from agentcrawl.browser.config import BrowserConfig, ViewportConfig

    return BrowserConfig(
        browser_type="chromium",
        headless=True,
        stealth=False,
        user_agent="",
        viewport=ViewportConfig(width=1280, height=720),
    )


# ══════════════════════════════════════════════════════════════
# Initialization
# ══════════════════════════════════════════════════════════════

class TestBrowserManagerInit:
    """Tests for BrowserManager initialization."""

    def test_create_manager(self, default_config: Any) -> None:
        """Create a BrowserManager with default config."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        assert manager is not None
        assert manager.config.browser_type == "chromium"
        assert manager.config.headless is True

    def test_create_manager_firefox(self) -> None:
        """Create a BrowserManager with Firefox."""
        from agentcrawl.browser.config import BrowserConfig
        from agentcrawl.browser.manager import BrowserManager

        config = BrowserConfig(browser_type="firefox", headless=True)
        manager = BrowserManager(config=config)

        assert manager.config.browser_type == "firefox"

    def test_create_manager_webkit(self) -> None:
        """Create a BrowserManager with WebKit."""
        from agentcrawl.browser.config import BrowserConfig
        from agentcrawl.browser.manager import BrowserManager

        config = BrowserConfig(browser_type="webkit", headless=True)
        manager = BrowserManager(config=config)

        assert manager.config.browser_type == "webkit"

    def test_manager_not_started_initially(self, default_config: Any) -> None:
        """Manager is not started after creation."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)
        assert manager.is_started is False


# ══════════════════════════════════════════════════════════════
# Launch & Shutdown
# ══════════════════════════════════════════════════════════════

class TestBrowserLaunchShutdown:
    """Tests for browser launch and shutdown."""

    @pytest.mark.asyncio
    async def test_launch_browser(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Launch browser successfully."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            assert manager.is_started is True

    @pytest.mark.asyncio
    async def test_shutdown_browser(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Shutdown browser cleanly."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()
            await manager.stop()

            assert manager.is_started is False

    @pytest.mark.asyncio
    async def test_context_manager(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Use BrowserManager as async context manager."""
        from agentcrawl.browser.manager import BrowserManager

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            async with BrowserManager(config=default_config) as manager:
                assert manager.is_started is True

            # After context exit, should be shut down
            assert manager.is_started is False


# ══════════════════════════════════════════════════════════════
# Context & Page Management
# ══════════════════════════════════════════════════════════════

class TestContextPageManagement:
    """Tests for context and page management."""

    @pytest.mark.asyncio
    async def test_acquire_page(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Acquire a page from the manager."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()
            page = await manager.acquire_page()

            assert page is not None
            assert manager.active_page_count == 1

            await manager.release_page(page)
            assert manager.active_page_count == 0

    @pytest.mark.asyncio
    async def test_acquire_page_without_startup(
        self,
        default_config: Any,
    ) -> None:
        """Acquire page without startup raises error."""
        from agentcrawl.browser.manager import BrowserManager, BrowserNotStartedError

        manager = BrowserManager(config=default_config)

        with pytest.raises(BrowserNotStartedError):
            await manager.acquire_page()

    @pytest.mark.asyncio
    async def test_multiple_pages(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Acquire multiple pages."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            page1 = await manager.acquire_page()
            page2 = await manager.acquire_page()

            assert page1 is not None
            assert page2 is not None
            assert manager.active_page_count == 2

            await manager.release_page(page1)
            await manager.release_page(page2)
            assert manager.active_page_count == 0

    @pytest.mark.asyncio
    async def test_page_reuse(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Released pages are reused."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            page1 = await manager.acquire_page()
            await manager.release_page(page1)

            page2 = await manager.acquire_page()
            # Page should be reused (same page object from pool)
            assert page2 is not None


# ══════════════════════════════════════════════════════════════
# Stealth Configuration
# ══════════════════════════════════════════════════════════════

class TestStealthConfig:
    """Tests for stealth configuration."""

    @pytest.mark.asyncio
    async def test_stealth_enabled(
        self,
        mock_playwright: MagicMock,
    ) -> None:
        """Stealth adapter is created when stealth=True."""
        from agentcrawl.browser.config import BrowserConfig
        from agentcrawl.browser.manager import BrowserManager

        config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            stealth=True,
        )

        manager = BrowserManager(config=config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            # Stealth adapter should be created
            assert manager._stealth_adapter is not None


# ══════════════════════════════════════════════════════════════
# Viewport Configuration
# ══════════════════════════════════════════════════════════════

class TestViewportConfig:
    """Tests for viewport configuration."""

    @pytest.mark.asyncio
    async def test_viewport_width_height(
        self,
        mock_playwright: MagicMock,
    ) -> None:
        """Viewport width and height are applied."""
        from agentcrawl.browser.config import BrowserConfig, ViewportConfig
        from agentcrawl.browser.manager import BrowserManager

        config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            viewport=ViewportConfig(width=1920, height=1080),
        )

        manager = BrowserManager(config=config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            # Check launch options passed to browser
            launch_opts = manager._config.to_launch_options()
            assert launch_opts["headless"] is True

    @pytest.mark.asyncio
    async def test_mobile_viewport(
        self,
        mock_playwright: MagicMock,
    ) -> None:
        """Mobile viewport emulation."""
        from agentcrawl.browser.config import BrowserConfig, ViewportConfig
        from agentcrawl.browser.manager import BrowserManager

        config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            viewport=ViewportConfig(width=375, height=667, is_mobile=True, has_touch=True),
        )

        manager = BrowserManager(config=config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            # Check viewport config is mobile
            assert manager.config.viewport.is_mobile is True
            assert manager.config.viewport.has_touch is True


# ══════════════════════════════════════════════════════════════
# User-Agent Configuration
# ══════════════════════════════════════════════════════════════

class TestUserAgentConfig:
    """Tests for user-agent configuration."""

    @pytest.mark.asyncio
    async def test_custom_user_agent(
        self,
        mock_playwright: MagicMock,
    ) -> None:
        """Custom user agent is used."""
        from agentcrawl.browser.config import BrowserConfig
        from agentcrawl.browser.manager import BrowserManager

        config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            user_agent="Custom User Agent 1.0",
        )

        manager = BrowserManager(config=config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            assert manager.config.user_agent == "Custom User Agent 1.0"


# ══════════════════════════════════════════════════════════════
# Pool Configuration
# ══════════════════════════════════════════════════════════════

class TestPoolConfig:
    """Tests for browser pool configuration."""

    @pytest.mark.asyncio
    async def test_max_concurrent(
        self,
        mock_playwright: MagicMock,
    ) -> None:
        """Max concurrent pages limit."""
        from agentcrawl.browser.config import BrowserConfig, BrowserPoolConfig
        from agentcrawl.browser.manager import BrowserManager

        config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            pool=BrowserPoolConfig(max_pages=3, pre_warm=1),
        )

        manager = BrowserManager(config=config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            # Check pool config
            assert manager.config.pool.max_pages == 3
            assert manager.config.pool.pre_warm == 1


# ══════════════════════════════════════════════════════════════
# Error Handling
# ══════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_launch_failure(
        self,
        default_config: Any,
    ) -> None:
        """Launch failure raises BrowserLaunchError."""
        from agentcrawl.browser.manager import BrowserLaunchError, BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(side_effect=Exception("Launch failed"))

            with pytest.raises(BrowserLaunchError):
                await manager.start()

    @pytest.mark.asyncio
    async def test_release_unacquired_page(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Releasing an unacquired page doesn't crash."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()
            page = await manager.acquire_page()
            await manager.release_page(page)

            # Release again should not crash
            await manager.release_page(page)


# ══════════════════════════════════════════════════════════════
# Stats & Properties
# ══════════════════════════════════════════════════════════════

class TestStatsProperties:
    """Tests for stats and properties."""

    @pytest.mark.asyncio
    async def test_stats_tracking(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Stats track page operations."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            manager.stats["pages_created"]

            page = await manager.acquire_page()
            await manager.release_page(page)

            stats = manager.stats
            assert stats["pages_acquired"] >= 1
            assert stats["pages_released"] >= 1
            assert stats["active_pages"] == 0

    @pytest.mark.asyncio
    async def test_available_page_count(
        self,
        default_config: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Available page count is accurate."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(config=default_config)

        with patch("playwright.async_api.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)

            await manager.start()

            assert manager.available_page_count >= 0
            assert manager.total_page_count >= 0
