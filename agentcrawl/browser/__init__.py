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
from typing import Any

logger = logging.getLogger("agentcrawl.browser")

# ──────────────────────────────────────────────────────────────
# Configuration (always available)
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# Actions (always available — no Playwright import needed)
# ──────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────
# Manager & Pool (require Playwright at runtime, not import time)
# ──────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────
# Proxy (always available)
# ──────────────────────────────────────────────────────────────
from agentcrawl.browser.proxy import (
    ProxyManager,
    ProxyProtocol,
    ProxyServer,
    ProxyStatus,
)

# ──────────────────────────────────────────────────────────────
# Stealth (always available)
# ──────────────────────────────────────────────────────────────
from agentcrawl.browser.stealth import (
    BrowserFingerprint,
    StealthAdapter,
)

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Config
    "BrowserConfig",
    "BrowserPoolConfig",
    "BrowserType",
    "GeolocationConfig",
    "ProxyConfig",
    "ProxyRotationStrategy",
    "RecordingConfig",
    "ScreenshotFormat",
    "SessionConfig",
    "ViewportConfig",
    # Manager
    "BrowserManager",
    "BrowserManagerError",
    "BrowserLaunchError",
    "BrowserNotStartedError",
    "PageAcquisitionError",
    "PoolExhaustedError",
    # Pool
    "AcquirePriority",
    "BrowserPool",
    "PageState",
    "PoolEventType",
    "PoolStats",
    "PooledPage",
    # Proxy
    "ProxyManager",
    "ProxyProtocol",
    "ProxyServer",
    "ProxyStatus",
    # Stealth
    "BrowserFingerprint",
    "StealthAdapter",
    # Actions
    "Action",
    "ActionResult",
    "ActionStatus",
    "ActionType",
    "ActionExecutionError",
    "PageActions",
    "PageActionsBuilder",
    "ScrollDirection",
    "WaitCondition",
]
