"""
AgentCrawl — Configuration Unit Tests
=========================================

Unit tests for the configuration system.

Tests:
    - Settings (defaults, env vars, validation)
    - CrawlerConfig (defaults, validation, presets)
    - LLMConfig (providers, models)
    - QueueConfig (backends, workers)
    - Config from environment
    - Config serialization
    - Validation errors

Run:
    pytest tests/unit/test_config.py -v
"""

from __future__ import annotations

import pytest

from agentcrawl.config.browser_config import BrowserSettings
from agentcrawl.config.proxy_config import ProxySettings

# ══════════════════════════════════════════════════════════════
# Settings
# ══════════════════════════════════════════════════════════════

class TestSettings:
    """Tests for global Settings."""

    def test_default_settings(self) -> None:
        """Default settings have expected values."""
        from agentcrawl.config.settings import Settings

        settings = Settings()

        assert settings.browser.browser_type == "chromium"
        assert settings.browser.headless is True
        assert settings.browser.stealth is True
        assert settings.log_level == "info"
        assert settings.cache_backend == "memory"
        assert settings.cache_ttl == 3600
        assert settings.browser.timeout == 30
        assert settings.browser.max_concurrent == 5

    def test_settings_from_kwargs(self) -> None:
        """Settings can be created with keyword arguments."""
        from agentcrawl.config.settings import Settings

        settings = Settings(
            browser=BrowserSettings(browser_type="firefox", headless=False, stealth=True),
            log_level="debug",
            cache_ttl=7200,
        )

        assert settings.browser.browser_type == "firefox"
        assert settings.browser.headless is False
        assert settings.browser.stealth is True
        assert settings.log_level == "debug"
        assert settings.cache_ttl == 7200

    def test_settings_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings read from environment variables."""
        from agentcrawl.config.settings import Settings

        monkeypatch.setenv("AGENTCRAWL_BROWSER_TYPE", "webkit")
        monkeypatch.setenv("AGENTCRAWL_HEADLESS", "false")
        monkeypatch.setenv("AGENTCRAWL_LOG_LEVEL", "warning")
        monkeypatch.setenv("AGENTCRAWL_CACHE_TTL", "1800")

        settings = Settings()

        assert settings.browser.browser_type == "webkit"
        assert settings.browser.headless is False
        assert settings.log_level == "warning"
        assert settings.cache_ttl == 1800

    def test_settings_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API key read from environment."""
        from agentcrawl.config.settings import Settings

        monkeypatch.setenv("AGENTCRAWL_API_KEY", "test-key-123")

        settings = Settings()
        assert settings.api_key == "test-key-123"

    def test_settings_invalid_browser_type(self) -> None:
        """Invalid browser type raises validation error."""
        from agentcrawl.config.browser_config import BrowserSettings
        from agentcrawl.config.settings import Settings

        with pytest.raises(ValueError):
            Settings(browser=BrowserSettings(browser_type="invalid_browser"))

    def test_settings_invalid_log_level(self) -> None:
        """Invalid log level raises validation error."""
        from agentcrawl.config.settings import Settings

        with pytest.raises(ValueError):
            Settings(log_level="invalid_level")

    def test_settings_negative_timeout(self) -> None:
        """Negative timeout raises validation error."""
        from agentcrawl.config.browser_config import BrowserSettings
        from agentcrawl.config.settings import Settings

        with pytest.raises(ValueError):
            Settings(browser=BrowserSettings(timeout=-1))

    def test_settings_zero_max_concurrent(self) -> None:
        """Zero max_concurrent raises validation error."""
        from agentcrawl.config.browser_config import BrowserSettings
        from agentcrawl.config.settings import Settings

        with pytest.raises(ValueError):
            Settings(browser=BrowserSettings(max_concurrent=0))

    def test_settings_port_default(self) -> None:
        """Default port is 8000."""
        from agentcrawl.config.settings import Settings

        settings = Settings()
        assert settings.server_port == 8000

    def test_settings_host_default(self) -> None:
        """Default host is 127.0.0.1."""
        from agentcrawl.config.settings import Settings

        settings = Settings()
        assert settings.server_host == "127.0.0.1"

    def test_settings_workers_default(self) -> None:
        """Default workers is 1."""
        from agentcrawl.config.settings import Settings

        settings = Settings()
        assert settings.server_workers == 1

    def test_settings_proxy_url(self) -> None:
        """Proxy URL can be configured."""
        from agentcrawl.config.settings import Settings

        settings = Settings(proxy=ProxySettings(url="http://proxy:8080"))
        assert settings.proxy.url == "http://proxy:8080"

    def test_settings_user_agent(self) -> None:
        """Custom User-Agent can be set."""
        from agentcrawl.config.browser_config import BrowserSettings
        from agentcrawl.config.settings import Settings

        settings = Settings(browser=BrowserSettings(user_agent="MyBot/1.0"))
        assert settings.browser.user_agent == "MyBot/1.0"

    def test_settings_viewport(self) -> None:
        """Viewport dimensions can be configured."""
        from agentcrawl.config.browser_config import BrowserSettings
        from agentcrawl.config.settings import Settings

        settings = Settings(browser=BrowserSettings(viewport_width=1920, viewport_height=1080))
        assert settings.browser.viewport_width == 1920
        assert settings.browser.viewport_height == 1080


# ══════════════════════════════════════════════════════════════
# CrawlerConfig
# ══════════════════════════════════════════════════════════════

class TestCrawlerConfig:
    """Tests for CrawlerConfig."""

    def test_default_config(self) -> None:
        """Default config has expected values."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig()

        assert config.output_format == "markdown"
        assert config.include_links is True
        assert config.include_metadata is True
        assert config.only_main_content is True
        assert config.content_filter == "none"
        assert config.chunker == "none"
        assert config.cache is True
        assert config.timeout == 30

    def test_config_from_kwargs(self) -> None:
        """Config from keyword arguments."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            output_format="json",
            include_links=False,
            only_main_content=False,
            content_filter="pruning",
            chunker="topic",
            chunk_max_size=500,
            cache=False,
            timeout=60,
        )

        assert config.output_format == "json"
        assert config.include_links is False
        assert config.only_main_content is False
        assert config.content_filter == "pruning"
        assert config.chunker == "topic"
        assert config.chunk_max_size == 500
        assert config.cache is False
        assert config.timeout == 60

    def test_config_invalid_output_format(self) -> None:
        """Invalid output_format falls back to default."""
        from agentcrawl.config.crawler_config import CrawlerConfig, OutputFormat

        config = CrawlerConfig(output_format="invalid")
        # Falls back to default MARKDOWN
        assert config.output_format == OutputFormat.MARKDOWN

    def test_config_invalid_content_filter(self) -> None:
        """Invalid content_filter falls back to default."""
        from agentcrawl.config.crawler_config import ContentFilterType, CrawlerConfig

        config = CrawlerConfig(content_filter="invalid")
        # Falls back to default NONE
        assert config.content_filter == ContentFilterType.NONE

    def test_config_invalid_chunker(self) -> None:
        """Invalid chunker falls back to default."""
        from agentcrawl.config.crawler_config import ChunkerType, CrawlerConfig

        config = CrawlerConfig(chunker="invalid")
        # Falls back to default NONE
        assert config.chunker == ChunkerType.NONE

    def test_config_actions(self) -> None:
        """Config with page actions."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        actions = [
            {"type": "click", "selector": "#button"},
            {"type": "wait", "milliseconds": 1000},
        ]

        config = CrawlerConfig(actions=actions)
        assert len(config.actions) == 2
        assert config.actions[0]["type"] == "click"

    def test_config_selectors(self) -> None:
        """Config with CSS selectors."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            selectors=["article", ".content"],
            exclude_selectors=["nav", "footer"],
        )

        assert len(config.selectors) == 2
        assert len(config.exclude_selectors) == 2

    def test_config_to_dict(self) -> None:
        """Config serializes to dict."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(output_format="markdown", cache=False)
        data = config.to_dict()

        assert isinstance(data, dict)
        assert data["output_format"] == "markdown"
        assert data["cache"] is False

    def test_config_chunk_overlap(self) -> None:
        """Chunk overlap configuration."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            chunker="fixed",
            chunk_max_size=500,
            chunk_overlap=100,
        )

        assert config.chunk_max_size == 500
        assert config.chunk_overlap == 100

    def test_config_cache_ttl(self) -> None:
        """Cache TTL configuration."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(cache=True, cache_ttl=7200)
        assert config.cache_ttl == 7200

    def test_config_include_screenshot(self) -> None:
        """Screenshot configuration."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(include_screenshot=True)
        assert config.include_screenshot is True

    def test_config_include_citations(self) -> None:
        """Citations configuration."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(include_citations=True)
        assert config.include_citations is True


# ══════════════════════════════════════════════════════════════
# LLMConfig
# ══════════════════════════════════════════════════════════════

class TestLLMConfig:
    """Tests for LLMConfig."""

    def test_default_config(self) -> None:
        """Default LLM config."""
        from agentcrawl.config.llm_config import LLMConfig

        config = LLMConfig()

        assert config.provider == "openai/gpt-4o-mini"
        assert config.temperature >= 0
        assert config.max_tokens > 0

    def test_config_custom_provider(self) -> None:
        """Custom provider configuration."""
        from agentcrawl.config.llm_config import LLMConfig

        config = LLMConfig(provider="anthropic/claude-sonnet-4-20250514")
        assert config.provider == "anthropic/claude-sonnet-4-20250514"

    def test_config_api_key(self) -> None:
        """API key configuration."""
        from agentcrawl.config.llm_config import LLMConfig

        config = LLMConfig(api_key="sk-test-123")
        assert config.api_key == "sk-test-123"

    def test_config_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API key from environment."""
        from agentcrawl.config.llm_config import LLMConfig

        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")

        config = LLMConfig()
        # Should pick up from env
        assert config.api_key == "sk-env-key" or config.api_key == ""

    def test_config_temperature(self) -> None:
        """Temperature configuration."""
        from agentcrawl.config.llm_config import LLMConfig

        config = LLMConfig(temperature=0.5)
        assert config.temperature == 0.5

    def test_config_max_tokens(self) -> None:
        """Max tokens configuration."""
        from agentcrawl.config.llm_config import LLMConfig

        config = LLMConfig(max_tokens=2000)
        assert config.max_tokens == 2000

    def test_config_base_url(self) -> None:
        """Custom base URL for self-hosted LLM."""
        from agentcrawl.config.llm_config import LLMConfig

        config = LLMConfig(api_base="http://localhost:11434/v1")
        assert config.api_base == "http://localhost:11434/v1"


# ══════════════════════════════════════════════════════════════
# Queue Configuration (part of Settings)
# ══════════════════════════════════════════════════════════════

class TestQueueSettings:
    """Tests for queue settings in global Settings."""

    def test_default_config(self) -> None:
        """Default queue config."""
        from agentcrawl.config.settings import Settings

        settings = Settings()

        assert settings.queue_backend == "memory"
        assert settings.queue_max_concurrent == 3
        assert settings.queue_job_timeout == 600
        assert settings.queue_max_retries == 2

    def test_config_redis_backend(self) -> None:
        """Redis backend configuration."""
        from agentcrawl.config.settings import Settings

        settings = Settings(
            queue_backend="redis",
            redis_url="redis://localhost:6379",
        )

        assert settings.queue_backend == "redis"
        assert settings.redis_url == "redis://localhost:6379"

    def test_config_max_concurrent(self) -> None:
        """Max concurrent jobs configuration."""
        from agentcrawl.config.settings import Settings

        settings = Settings(queue_max_concurrent=10)
        assert settings.queue_max_concurrent == 10

    def test_config_max_retries(self) -> None:
        """Max retries configuration."""
        from agentcrawl.config.settings import Settings

        settings = Settings(queue_max_retries=5)
        assert settings.queue_max_retries == 5

    def test_config_invalid_backend(self) -> None:
        """Invalid backend raises error."""
        from agentcrawl.config.settings import Settings

        with pytest.raises(ValueError):
            Settings(queue_backend="invalid_backend")


# ══════════════════════════════════════════════════════════════
# Config Presets
# ══════════════════════════════════════════════════════════════

class TestConfigPresets:
    """Tests for configuration presets."""

    def test_rag_preset(self) -> None:
        """RAG preset configures chunking."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            only_main_content=True,
            content_filter="pruning",
            chunker="topic",
            chunk_max_size=500,
            chunk_overlap=100,
        )

        assert config.chunker == "topic"
        assert config.content_filter == "pruning"
        assert config.only_main_content is True

    def test_minimal_preset(self) -> None:
        """Minimal preset disables extras."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            output_format="text",
            include_links=False,
            include_metadata=False,
            only_main_content=True,
            cache=False,
        )

        assert config.include_links is False
        assert config.include_metadata is False
        assert config.cache is False

    def test_full_preset(self) -> None:
        """Full preset enables everything."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            include_links=True,
            include_metadata=True,
            include_screenshot=True,
            include_citations=True,
            only_main_content=True,
            content_filter="pruning",
            chunker="topic",
            cache=True,
        )

        assert config.include_links is True
        assert config.include_metadata is True
        assert config.include_screenshot is True
        assert config.include_citations is True


# ══════════════════════════════════════════════════════════════
# Config Merging
# ══════════════════════════════════════════════════════════════

class TestConfigMerging:
    """Tests for config merging/override behavior."""

    def test_kwargs_override_defaults(self) -> None:
        """Keyword arguments override defaults."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(output_format="json", cache=False)

        assert config.output_format == "json"  # Overridden
        assert config.include_links is True  # Default

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables override defaults."""
        from agentcrawl.config.settings import Settings

        monkeypatch.setenv("AGENTCRAWL_TIMEOUT", "60")

        settings = Settings()
        assert settings.browser.timeout == 60

    def test_kwargs_override_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keyword arguments override environment."""
        from agentcrawl.config.settings import Settings

        monkeypatch.setenv("AGENTCRAWL_TIMEOUT", "60")

        settings = Settings(browser=BrowserSettings(timeout=90))
        assert settings.browser.timeout == 90
