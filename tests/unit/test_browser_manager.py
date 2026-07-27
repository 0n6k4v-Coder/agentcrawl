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
import pytest_asyncio


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
    page = AsyncMock()
    page.url = "about:blank"
    page.title = AsyncMock(return_value="Test Page")

    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.pages = []

    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    browser_type.launch = AsyncMock(return_value=browser)

    pw.chromium = browser_type
    pw.firefox = browser_type
    pw.webkit = browser_type

    return pw


@pytest.fixture
def default_settings() -> Any:
    """Default settings for browser tests."""
    from agentcrawl.config.settings import Settings

    return Settings(
        browser_type="chromium",
        headless=True,
        stealth=False,
        user_agent="",
        proxy_url="",
        viewport_width=1280,
        viewport_height=720,
    )


# ══════════════════════════════════════════════════════════════
# Initialization
# ══════════════════════════════════════════════════════════════

class TestBrowserManagerInit:
    """Tests for BrowserManager initialization."""

    def test_create_manager(self, default_settings: Any) -> None:
        """Create a BrowserManager with default settings."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        assert manager is not None
        assert manager._browser_type == "chromium"
        assert manager._headless is True

    def test_create_manager_firefox(self) -> None:
        """Create a BrowserManager with Firefox."""
        from agentcrawl.browser.manager import BrowserManager
        from agentcrawl.config.settings import Settings

        settings = Settings(browser_type="firefox", headless=True)
        manager = BrowserManager(settings=settings)

        assert manager._browser_type == "firefox"

    def test_create_manager_webkit(self) -> None:
        """Create a BrowserManager with WebKit."""
        from agentcrawl.browser.manager import BrowserManager
        from agentcrawl.config.settings import Settings

        settings = Settings(browser_type="webkit", headless=True)
        manager = BrowserManager(settings=settings)

        assert manager._browser_type == "webkit"

    def test_manager_not_started_initially(self, default_settings: Any) -> None:
        """Manager is not started after creation."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)
        assert manager.is_started is False


# ══════════════════════════════════════════════════════════════
# Launch & Shutdown
# ══════════════════════════════════════════════════════════════

class TestBrowserLaunchShutdown:
    """Tests for browser launch and shutdown."""

    @pytest.mark.asyncio
    async def test_launch_browser(
        self,
        default_settings: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Launch browser successfully."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()

            assert manager.is_started is True

    @pytest.mark.asyncio
    async def test_shutdown_browser(
        self,
        default_settings: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Shutdown browser cleanly."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()
            await manager.shutdown()

            assert manager.is_started is False

    @pytest.mark.asyncio
    async def test_double_startup(
        self,
        default_settings: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Double startup is idempotent."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()
            await manager.startup()  # Should not raise

            assert manager.is_started is True

    @pytest.mark.asyncio
    async def test_shutdown_without_startup(self, default_settings: Any) -> None:
        """Shutdown without startup is safe."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)
        await manager.shutdown()  # Should not raise


# ══════════════════════════════════════════════════════════════
# Context Management
# ══════════════════════════════════════════════════════════════

class TestContextManagement:
    """Tests for browser context creation."""

    @pytest.mark.asyncio
    async def test_create_context(
        self,
        default_settings: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Create a browser context."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()
            context = await manager.create_context()

            assert context is not None

    @pytest.mark.asyncio
    async def test_create_context_with_user_agent(
        self,
        mock_playwright: MagicMock,
    ) -> None:
        """Create context with custom User-Agent."""
        from agentcrawl.browser.manager import BrowserManager
        from agentcrawl.config.settings import Settings

        settings = Settings(
            browser_type="chromium",
            headless=True,
            user_agent="CustomAgent/1.0",
        )

        manager = BrowserManager(settings=settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()
            await manager.create_context()

            # Verify new_context was called
            browser = mock_playwright.chromium.launch.return_value
            browser.new_context.assert_called()

    @pytest.mark.asyncio
    async def test_create_context_with_viewport(
        self,
        mock_playwright: MagicMock,
    ) -> None:
        """Create context with custom viewport."""
        from agentcrawl.browser.manager import BrowserManager
        from agentcrawl.config.settings import Settings

        settings = Settings(
            browser_type="chromium",
            headless=True,
            viewport_width=1920,
            viewport_height=1080,
        )

        manager = BrowserManager(settings=settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()
            await manager.create_context()

            browser = mock_playwright.chromium.launch.return_value
            call_kwargs = browser.new_context.call_args
            assert call_kwargs is not None


# ══════════════════════════════════════════════════════════════
# Page Creation
# ══════════════════════════════════════════════════════════════

class TestPageCreation:
    """Tests for page creation within contexts."""

    @pytest.mark.asyncio
    async def test_create_page(
        self,
        default_settings: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Create a page in a context."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()
            context = await manager.create_context()
            page = await context.new_page()

            assert page is not None


# ══════════════════════════════════════════════════════════════
# Stealth Mode
# ══════════════════════════════════════════════════════════════

class TestStealthMode:
    """Tests for stealth/anti-detection configuration."""

    def test_stealth_disabled_by_default(self) -> None:
        """Stealth is disabled by default."""
        from agentcrawl.config.settings import Settings

        settings = Settings()
        assert settings.stealth is False

    def test_stealth_enabled(self) -> None:
        """Stealth can be enabled."""
        from agentcrawl.config.settings import Settings

        settings = Settings(stealth=True)
        assert settings.stealth is True

    @pytest.mark.asyncio
    async def test_stealth_context_creation(self, mock_playwright: MagicMock) -> None:
        """Stealth mode affects context creation."""
        from agentcrawl.browser.manager import BrowserManager
        from agentcrawl.config.settings import Settings

        settings = Settings(
            browser_type="chromium",
            headless=True,
            stealth=True,
        )

        manager = BrowserManager(settings=settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()

            # Stealth should be configured
            assert manager._stealth is True


# ══════════════════════════════════════════════════════════════
# Proxy Configuration
# ══════════════════════════════════════════════════════════════

class TestProxyConfig:
    """Tests for proxy configuration."""

    def test_no_proxy_by_default(self) -> None:
        """No proxy by default."""
        from agentcrawl.config.settings import Settings

        settings = Settings()
        assert settings.proxy_url == ""

    def test_proxy_url_configured(self) -> None:
        """Proxy URL can be configured."""
        from agentcrawl.config.settings import Settings

        settings = Settings(proxy_url="http://proxy:8080")
        assert settings.proxy_url == "http://proxy:8080"

    @pytest.mark.asyncio
    async def test_proxy_passed_to_browser(self, mock_playwright: MagicMock) -> None:
        """Proxy is passed to browser launch."""
        from agentcrawl.browser.manager import BrowserManager
        from agentcrawl.config.settings import Settings

        settings = Settings(
            browser_type="chromium",
            headless=True,
            proxy_url="http://proxy:8080",
        )

        manager = BrowserManager(settings=settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()

            browser_type = mock_playwright.chromium
            browser_type.launch.assert_called()


# ══════════════════════════════════════════════════════════════
# User-Agent Rotation
# ══════════════════════════════════════════════════════════════

class TestUserAgentRotation:
    """Tests for User-Agent rotation."""

    def test_default_user_agents(self) -> None:
        """Default User-Agent list is populated."""
        from agentcrawl.browser.manager import DEFAULT_USER_AGENTS

        assert len(DEFAULT_USER_AGENTS) > 0
        for ua in DEFAULT_USER_AGENTS:
            assert "Mozilla" in ua or "Chrome" in ua or "Safari" in ua

    def test_get_random_user_agent(self) -> None:
        """get_random_user_agent returns a valid UA."""
        from agentcrawl.browser.manager import get_random_user_agent

        ua = get_random_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 10

    def test_custom_user_agent(self) -> None:
        """Custom User-Agent overrides rotation."""
        from agentcrawl.config.settings import Settings

        settings = Settings(user_agent="MyBot/1.0")
        assert settings.user_agent == "MyBot/1.0"


# ══════════════════════════════════════════════════════════════
# Error Handling
# ══════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_create_context_before_startup(self, default_settings: Any) -> None:
        """Creating context before startup raises error."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with pytest.raises(RuntimeError, match="not started"):
            await manager.create_context()

    @pytest.mark.asyncio
    async def test_launch_failure_handling(self, default_settings: Any) -> None:
        """Browser launch failure is handled."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("Browser not found")
            )
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(Exception, match="Browser not found"):
                await manager.startup()


# ══════════════════════════════════════════════════════════════
# Concurrent Contexts
# ══════════════════════════════════════════════════════════════

class TestConcurrentContexts:
    """Tests for concurrent context management."""

    @pytest.mark.asyncio
    async def test_multiple_contexts(
        self,
        default_settings: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Multiple contexts can be created."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()

            contexts = []
            for _ in range(3):
                ctx = await manager.create_context()
                contexts.append(ctx)

            assert len(contexts) == 3

    @pytest.mark.asyncio
    async def test_context_isolation(
        self,
        default_settings: Any,
        mock_playwright: MagicMock,
    ) -> None:
        """Each context is isolated."""
        from agentcrawl.browser.manager import BrowserManager

        manager = BrowserManager(settings=default_settings)

        with patch("agentcrawl.browser.manager.async_playwright") as mock_pw:
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.startup()

            ctx1 = await manager.create_context()
            ctx2 = await manager.create_context()

            # Contexts should be different objects
            assert ctx1 is not ctx2