"""
AgentCrawl — Configuration Layer
===================================

Centralized configuration with Pydantic validation, environment
variable binding, and YAML/dict loading. Provides settings for
every layer of the system: browser, proxy, LLM, cache, server,
queue, and per-request crawl options.

Modules:
    settings        — Global Settings (aggregates all sub-configs)
    browser_config  — Browser automation settings (Pydantic)
    crawler_config  — Per-request crawl configuration (dataclass)
    llm_config      — LLM provider settings (Pydantic)
    proxy_config    — Proxy settings (Pydantic)

Quick Start:
    # Global settings (reads .env automatically)
    from agentcrawl.config import Settings

    settings = Settings()
    settings.setup_logging()

    # Per-request crawl config
    from agentcrawl.config import CrawlerConfig

    config = CrawlerConfig(output_format="markdown", cache=True)

    # LLM config
    from agentcrawl.config import LLMConfig

    llm = LLMConfig(provider="openai/gpt-4o-mini", temperature=0.1)

    # Browser settings
    from agentcrawl.config import BrowserSettings

    browser = BrowserSettings(headless=True, stealth=True)

    # Proxy settings
    from agentcrawl.config import ProxySettings

    proxy = ProxySettings(url="http://proxy:8080", rotation="round_robin")

    # From YAML
    settings = Settings.from_yaml("agentcrawl.yml")

    # Presets
    settings = Settings.preset_development()
    settings = Settings.preset_production()
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# Browser Configuration
# ──────────────────────────────────────────────────────────────
from agentcrawl.config.browser_config import BrowserSettings

# ──────────────────────────────────────────────────────────────
# Crawler Run Configuration
# ──────────────────────────────────────────────────────────────
from agentcrawl.config.crawler_config import (
    ChunkerType,
    ContentFilterType,
    CrawlerConfig,
    OutputFormat,
    ScreenshotOptions,
    WaitOptions,
    WaitStrategy,
)

# ──────────────────────────────────────────────────────────────
# LLM Configuration
# ──────────────────────────────────────────────────────────────
from agentcrawl.config.llm_config import LLMConfig

# ──────────────────────────────────────────────────────────────
# Proxy Configuration
# ──────────────────────────────────────────────────────────────
from agentcrawl.config.proxy_config import ProxySettings

# ──────────────────────────────────────────────────────────────
# Global Settings
# ──────────────────────────────────────────────────────────────
from agentcrawl.config.settings import Settings

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Global
    "Settings",
    # Browser
    "BrowserSettings",
    # Crawler
    "CrawlerConfig",
    "OutputFormat",
    "ContentFilterType",
    "ChunkerType",
    "WaitStrategy",
    "ScreenshotOptions",
    "WaitOptions",
    # LLM
    "LLMConfig",
    # Proxy
    "ProxySettings",
]
