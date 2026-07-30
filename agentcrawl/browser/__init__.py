"""
AgentCrawl — Browser Automation Layer
=======================================

Playwright-based browser automation with stealth support, page pooling,
proxy rotation, and declarative page actions.

Modules:
    config   — Browser, proxy, viewport, pool, and session configuration
    manager  — Browser lifecycle management (launch, context, page, shutdown)
    pool     — Concurrent page pool with semaphore-based limiting
    proxy    — Proxy server management with rotation strategies
    stealth  — Anti-bot evasion and fingerprint spoofing
    actions  — Declarative page interaction (click, scroll, type, wait, etc.)

Quick Start:
    from agentcrawl.browser import BrowserManager, BrowserConfig

    async with BrowserManager(BrowserConfig(headless=True, stealth=True)) as manager:
        page = await manager.acquire_page()
        try:
            await page.goto("https://example.com")
            html = await page.content()
        finally:
            await manager.release_page(page)

    # With page actions
    from agentcrawl.browser import PageActions

    actions = PageActions([
        {"type": "wait", "selector": "#content"},
        {"type": "click", "selector": "#load-more"},
        {"type": "scroll", "direction": "down", "amount": 3},
    ])
    results = await actions.execute(page)

    # With proxy rotation
    from agentcrawl.browser import ProxyManager

    proxy_mgr = ProxyManager.from_urls([
        "http://proxy1:8080",
        "http://user:pass@proxy2:8080",
    ], rotation="round_robin")
    proxy = proxy_mgr.next()

    # With stealth fingerprint
    from agentcrawl.browser import StealthAdapter, BrowserFingerprint

    fp = BrowserFingerprint.generate(platform_category="desktop", os_name="Windows")
    adapter = StealthAdapter(fingerprint=fp)
    await adapter.apply_to_context(context)
"""

from __future__ import annotations

import logging

from agentcrawl.browser.actions import (
    Action,
    ActionExecutionError,
    ActionResult,
    ActionStatus,
    ActionType,
    PageActions,
    PageActionsBuilder,
    ScrollDirection,
    WaitCondition,
)
from agentcrawl.browser.config import (
    BrowserConfig,
    BrowserPoolConfig,
    BrowserType,
    GeolocationConfig,
    ProxyConfig,
    ProxyRotationStrategy,
    RecordingConfig,
    ScreenshotFormat,
    SessionConfig,
    ViewportConfig,
)
from agentcrawl.browser.manager import (
    BrowserLaunchError,
    BrowserManager,
    BrowserManagerError,
    BrowserNotStartedError,
    PageAcquisitionError,
    PoolExhaustedError,
)
from agentcrawl.browser.pool import (
    AcquirePriority,
    BrowserPool,
    PageState,
    PooledPage,
    PoolEventType,
    PoolStats,
)
from agentcrawl.browser.proxy import (
    ProxyManager,
    ProxyProtocol,
    ProxyServer,
    ProxyStatus,
)
from agentcrawl.browser.stealth import (
    BrowserFingerprint,
    StealthAdapter,
)

logger = logging.getLogger("agentcrawl.browser")

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Pool
    "AcquirePriority",
    # Actions
    "Action",
    "ActionExecutionError",
    "ActionResult",
    "ActionStatus",
    "ActionType",
    # Config
    "BrowserConfig",
    # Stealth
    "BrowserFingerprint",
    # Manager
    "BrowserLaunchError",
    "BrowserManager",
    "BrowserManagerError",
    "BrowserNotStartedError",
    "BrowserPool",
    "BrowserPoolConfig",
    "BrowserType",
    "GeolocationConfig",
    "PageAcquisitionError",
    "PageActions",
    "PageActionsBuilder",
    "PageState",
    "PoolEventType",
    "PoolExhaustedError",
    "PoolStats",
    "PooledPage",
    "ProxyConfig",
    # Proxy
    "ProxyManager",
    "ProxyProtocol",
    "ProxyRotationStrategy",
    "ProxyServer",
    "ProxyStatus",
    "RecordingConfig",
    "ScreenshotFormat",
    "ScrollDirection",
    "SessionConfig",
    "StealthAdapter",
    "ViewportConfig",
    "WaitCondition",
]

__all__ = [
    # Pool
    "AcquirePriority",
    # Actions
    "Action",
    "ActionExecutionError",
    "ActionResult",
    "ActionStatus",
    "ActionType",
    # Config
    "BrowserConfig",
    # Stealth
    "BrowserFingerprint",
    "BrowserLaunchError",
    # Manager
    "BrowserManager",
    "BrowserManagerError",
    "BrowserNotStartedError",
    "BrowserPool",
    "BrowserPoolConfig",
    "BrowserType",
    "GeolocationConfig",
    "PageAcquisitionError",
    "PageActions",
    "PageActionsBuilder",
    "PageState",
    "PoolEventType",
    "PoolExhaustedError",
    "PoolStats",
    "PooledPage",
    "ProxyConfig",
    # Proxy
    "ProxyManager",
    "ProxyProtocol",
    "ProxyRotationStrategy",
    "ProxyServer",
    "ProxyStatus",
    "RecordingConfig",
    "ScreenshotFormat",
    "ScrollDirection",
    "SessionConfig",
    "StealthAdapter",
    "ViewportConfig",
    "WaitCondition",
]
