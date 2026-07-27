"""
AgentCrawl — Engine Unit Tests
==================================

Unit tests for the CrawlEngine core orchestrator.

Tests:
    - Engine creation and configuration
    - Startup and shutdown lifecycle
    - scrape() method
    - batch_scrape() method
    - crawl() method
    - map() method
    - search() convenience method
    - extract() method
    - Context manager protocol
    - Error handling
    - State management

Run:
    pytest tests/unit/test_engine.py -v
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
def settings() -> Any:
    """Test settings."""
    from agentcrawl.config.settings import Settings

    return Settings(
        log_level="WARNING",
        headless=True,
        cache_backend="memory",
        cache_ttl=60,
    )


@pytest.fixture
def config() -> Any:
    """Test crawler config."""
    from agentcrawl.config.crawler_config import CrawlerConfig

    return CrawlerConfig(
        output_format="markdown",
        include_links=True,
        include_metadata=True,
        only_main_content=True,
        cache=False,
        timeout=15,
    )


# ══════════════════════════════════════════════════════════════
# Engine Creation
# ══════════════════════════════════════════════════════════════

class TestEngineCreation:
    """Tests for CrawlEngine creation."""

    def test_create_engine(self, settings: Any) -> None:
        """Create engine from settings."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        assert engine is not None
        assert engine.is_started is False

    def test_create_engine_default(self) -> None:
        """Create engine with default settings."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.default()
        assert engine is not None

    def test_engine_not_started_initially(self, settings: Any) -> None:
        """Engine is not started after creation."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        assert engine.is_started is False

    def test_engine_has_settings(self, settings: Any) -> None:
        """Engine stores settings."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        assert engine._settings is not None
        assert engine._settings.browser_type == "chromium"

    def test_engine_repr(self, settings: Any) -> None:
        """Engine has a useful repr."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        repr_str = repr(engine)
        assert "CrawlEngine" in repr_str


# ══════════════════════════════════════════════════════════════
# Lifecycle
# ══════════════════════════════════════════════════════════════

class TestEngineLifecycle:
    """Tests for engine startup and shutdown."""

    @pytest.mark.asyncio
    async def test_startup(self, settings: Any) -> None:
        """Engine starts up successfully."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            await engine.startup()
            assert engine.is_started is True

    @pytest.mark.asyncio
    async def test_shutdown(self, settings: Any) -> None:
        """Engine shuts down cleanly."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.shutdown = AsyncMock()
            mock_bm.is_started = True

            await engine.startup()
            await engine.shutdown()

            assert engine.is_started is False

    @pytest.mark.asyncio
    async def test_double_startup(self, settings: Any) -> None:
        """Double startup is idempotent."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            await engine.startup()
            await engine.startup()  # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_without_startup(self, settings: Any) -> None:
        """Shutdown without startup is safe."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        await engine.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_context_manager(self, settings: Any) -> None:
        """Engine works as async context manager."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.shutdown = AsyncMock()
            mock_bm.is_started = True

            async with engine:
                assert engine.is_started is True

            assert engine.is_started is False


# ══════════════════════════════════════════════════════════════
# Scrape
# ══════════════════════════════════════════════════════════════

class TestEngineScrape:
    """Tests for engine.scrape() method."""

    @pytest.mark.asyncio
    async def test_scrape_not_started(self, settings: Any, config: Any) -> None:
        """Scrape before startup raises error."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with pytest.raises(RuntimeError, match="not started"):
            await engine.scrape("https://example.com", config)

    @pytest.mark.asyncio
    async def test_scrape_returns_result(self, settings: Any, config: Any) -> None:
        """Scrape returns a ScrapeResult."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Test"
        mock_result.word_count = 10

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.shutdown = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "_scrape_page", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.return_value = mock_result

                await engine.startup()
                result = await engine.scrape("https://example.com", config)

                assert result.success is True
                assert result.url == "https://example.com"

    @pytest.mark.asyncio
    async def test_scrape_empty_url(self, settings: Any, config: Any) -> None:
        """Scrape with empty URL raises error."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            await engine.startup()

            with pytest.raises((ValueError, RuntimeError)):
                await engine.scrape("", config)

    @pytest.mark.asyncio
    async def test_scrape_default_config(self, settings: Any) -> None:
        """Scrape with default config."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "_scrape_page", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.return_value = mock_result

                await engine.startup()
                result = await engine.scrape("https://example.com")

                assert result is not None


# ══════════════════════════════════════════════════════════════
# Batch Scrape
# ══════════════════════════════════════════════════════════════

class TestEngineBatchScrape:
    """Tests for engine.batch_scrape() method."""

    @pytest.mark.asyncio
    async def test_batch_scrape_multiple_urls(self, settings: Any, config: Any) -> None:
        """Batch scrape processes multiple URLs."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.url = "https://example.com"

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.return_value = mock_result

                await engine.startup()
                results = await engine.batch_scrape(
                    ["https://example.com/1", "https://example.com/2"],
                    config,
                )

                assert len(results) == 2

    @pytest.mark.asyncio
    async def test_batch_scrape_empty_list(self, settings: Any, config: Any) -> None:
        """Batch scrape with empty list returns empty."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            await engine.startup()
            results = await engine.batch_scrape([], config)

            assert len(results) == 0

    @pytest.mark.asyncio
    async def test_batch_scrape_concurrency(self, settings: Any, config: Any) -> None:
        """Batch scrape respects max_concurrent."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.return_value = mock_result

                await engine.startup()
                results = await engine.batch_scrape(
                    [f"https://example.com/{i}" for i in range(10)],
                    config,
                    max_concurrent=3,
                )

                assert len(results) == 10


# ══════════════════════════════════════════════════════════════
# Crawl
# ══════════════════════════════════════════════════════════════

class TestEngineCrawl:
    """Tests for engine.crawl() method."""

    @pytest.mark.asyncio
    async def test_crawl_not_started(self, settings: Any) -> None:
        """Crawl before startup raises error."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with pytest.raises(RuntimeError, match="not started"):
            await engine.crawl("https://example.com")

    @pytest.mark.asyncio
    async def test_crawl_returns_result(self, settings: Any) -> None:
        """Crawl returns a CrawlResult."""
        from agentcrawl.core.engine import CrawlEngine
        from agentcrawl.crawling.result import CrawlResult

        engine = CrawlEngine.from_settings(settings)

        mock_result = CrawlResult(start_url="https://example.com", strategy="bfs")

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "_execute_crawl", new_callable=AsyncMock) as mock_crawl:
                mock_crawl.return_value = mock_result

                await engine.startup()
                result = await engine.crawl("https://example.com")

                assert result.start_url == "https://example.com"


# ══════════════════════════════════════════════════════════════
# Map
# ══════════════════════════════════════════════════════════════

class TestEngineMap:
    """Tests for engine.map() method."""

    @pytest.mark.asyncio
    async def test_map_returns_urls(self, settings: Any) -> None:
        """Map returns discovered URLs."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch("agentcrawl.core.engine.DomainMapper") as MockMapper:
                mock_instance = MagicMock()
                mock_instance.discover = AsyncMock(return_value=[
                    "https://example.com/page1",
                    "https://example.com/page2",
                ])
                MockMapper.return_value = mock_instance

                await engine.startup()
                urls = await engine.map("https://example.com")

                assert len(urls) == 2


# ══════════════════════════════════════════════════════════════
# Search
# ══════════════════════════════════════════════════════════════

class TestEngineSearch:
    """Tests for engine.search() convenience method."""

    @pytest.mark.asyncio
    async def test_search_delegates(self, settings: Any) -> None:
        """Search delegates to SearchEngine."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        mock_results = [
            {"title": "Result 1", "url": "https://example.com/1"},
        ]

        with patch("agentcrawl.core.engine.SearchEngine") as MockSearch:
            mock_instance = MagicMock()
            mock_instance.search = AsyncMock(return_value=mock_results)
            MockSearch.return_value = mock_instance

            results = await engine.search("test query", max_results=5)

            assert len(results) == 1


# ══════════════════════════════════════════════════════════════
# Extract
# ══════════════════════════════════════════════════════════════

class TestEngineExtract:
    """Tests for engine.extract() method."""

    @pytest.mark.asyncio
    async def test_extract_not_started(self, settings: Any) -> None:
        """Extract before startup raises error."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with pytest.raises(RuntimeError, match="not started"):
            await engine.extract("https://example.com", schema={})

    @pytest.mark.asyncio
    async def test_extract_returns_data(self, settings: Any) -> None:
        """Extract returns structured data."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_data = {"title": "Test", "price": "$10"}

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "_extract_data", new_callable=AsyncMock) as mock_extract:
                mock_extract.return_value = mock_result

                await engine.startup()
                result = await engine.extract(
                    "https://example.com",
                    schema={"fields": [{"name": "title", "selector": "h1"}]},
                )

                assert result.success is True


# ══════════════════════════════════════════════════════════════
# State Management
# ══════════════════════════════════════════════════════════════

class TestEngineState:
    """Tests for engine state management."""

    def test_is_started_false_initially(self, settings: Any) -> None:
        """is_started is False before startup."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        assert engine.is_started is False

    @pytest.mark.asyncio
    async def test_is_started_true_after_startup(self, settings: Any) -> None:
        """is_started is True after startup."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            await engine.startup()
            assert engine.is_started is True

    @pytest.mark.asyncio
    async def test_is_started_false_after_shutdown(self, settings: Any) -> None:
        """is_started is False after shutdown."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.shutdown = AsyncMock()
            mock_bm.is_started = True

            await engine.startup()
            await engine.shutdown()

            assert engine.is_started is False


# ══════════════════════════════════════════════════════════════
# Error Handling
# ══════════════════════════════════════════════════════════════

class TestEngineErrors:
    """Tests for engine error handling."""

    @pytest.mark.asyncio
    async def test_scrape_error_returns_failed_result(self, settings: Any, config: Any) -> None:
        """Scrape error returns a failed result, not exception."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "_scrape_page", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.side_effect = Exception("Network error")

                await engine.startup()

                # Should return failed result, not raise
                result = await engine.scrape("https://example.com", config)
                assert result.success is False
                assert result.error is not None

    @pytest.mark.asyncio
    async def test_batch_scrape_partial_failure(self, settings: Any, config: Any) -> None:
        """Batch scrape handles partial failures."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)

        success_result = MagicMock()
        success_result.success = True
        success_result.url = "https://example.com/1"

        fail_result = MagicMock()
        fail_result.success = False
        fail_result.url = "https://example.com/2"
        fail_result.error = "Timeout"

        with patch.object(engine, "_browser_manager") as mock_bm:
            mock_bm.startup = AsyncMock()
            mock_bm.is_started = True

            with patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.side_effect = [success_result, fail_result]

                await engine.startup()
                results = await engine.batch_scrape(
                    ["https://example.com/1", "https://example.com/2"],
                    config,
                )

                assert len(results) == 2
                assert results[0].success is True
                assert results[1].success is False