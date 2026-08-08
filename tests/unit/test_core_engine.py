"""Additional tests for agentcrawl.core.engine module.

Covers:
- CrawlResult dataclass (to_dict, to_json, __post_init__, __repr__)
- CrawlJobResult dataclass (add_page, to_dict, to_json, _update_stats)
- EngineStats (record_scrape, to_dict)
- CrawlEngine caching paths
- CrawlEngine error handling and edge cases
- _build_cache_key
- crawl() with default strategy and error paths
- search() with scrape=False and error paths
- extract() with ExtractionStrategy instance and default method
- map_site()
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══ Fixtures ═══


@pytest.fixture
def settings() -> Any:
    """Test settings."""
    from agentcrawl.config.browser_config import BrowserSettings
    from agentcrawl.config.settings import Settings

    return Settings(
        log_level="WARNING",
        browser=BrowserSettings(headless=True),
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


# ═══ CrawlResult Tests ═══


class TestCrawlResult:
    """Tests for CrawlResult dataclass."""

    def test_post_init_word_count(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(url="https://example.com", markdown="one two three four")
        assert result.word_count == 4

    def test_post_init_word_count_zero(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(url="https://example.com", markdown="")
        assert result.word_count == 0

    def test_post_init_token_count(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(url="https://example.com", markdown="one two three four five six seven eight")
        # 8 words * ~4 = 32 chars, but token_count = max(1, len(markdown)//4)
        assert result.token_count == len("one two three four five six seven eight") // 4

    def test_post_init_token_count_short_text(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(url="https://example.com", markdown="hi")
        assert result.token_count == 1  # max(1, ...)

    def test_to_dict_basic(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com",
            success=True,
            status_code=200,
            markdown="# Hello",
        )
        d = result.to_dict()
        assert d["url"] == "https://example.com"
        assert d["success"] is True
        assert d["status_code"] == 200
        assert d["markdown"] == "# Hello"

    def test_to_dict_with_html(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com",
            success=True,
            html="<p>Hello</p>",
        )
        d = result.to_dict()
        assert d["html"] == "<p>Hello</p>"

    def test_to_dict_with_json(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com",
            success=True,
            json={"key": "value"},
        )
        d = result.to_dict()
        assert d["json"] == {"key": "value"}

    def test_to_dict_with_citations(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com",
            success=True,
            citations=[{"number": 1, "url": "https://ref.com"}],
        )
        d = result.to_dict()
        assert d["citations"] == [{"number": 1, "url": "https://ref.com"}]

    def test_to_dict_with_chunks(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com",
            success=True,
            chunks=[{"text": "chunk1"}],
        )
        d = result.to_dict()
        assert d["chunks"] == [{"text": "chunk1"}]

    def test_to_dict_with_extracted_data(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com",
            success=True,
            extracted_data={"title": "Test"},
        )
        d = result.to_dict()
        assert d["extracted_data"] == {"title": "Test"}

    def test_to_dict_with_screenshot(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        long_screenshot = "a" * 200
        result = CrawlResult(
            url="https://example.com",
            success=True,
            screenshot=long_screenshot,
        )
        d = result.to_dict()
        assert d["screenshot"].endswith("...")
        assert len(d["screenshot"]) <= 103  # 100 chars + "..."

    def test_to_dict_with_error(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com",
            success=False,
            error="Timeout",
        )
        d = result.to_dict()
        assert d["error"] == "Timeout"

    def test_to_json(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(url="https://example.com", success=True, markdown="# Hello")
        import json

        data = json.loads(result.to_json())
        assert data["url"] == "https://example.com"
        assert data["success"] is True

    def test_repr(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(url="https://example.com", success=True, status_code=200)
        repr_str = repr(result)
        assert "CrawlResult" in repr_str
        assert "200" in repr_str
        assert "https://example.com" in repr_str

    def test_repr_not_success(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(url="https://example.com", success=False, status_code=404)
        repr_str = repr(result)
        assert "✗" in repr_str

    def test_repr_cached(self) -> None:
        from agentcrawl.core.engine import CrawlResult

        result = CrawlResult(
            url="https://example.com", success=True, status_code=200, cached=True,
        )
        repr_str = repr(result)
        assert "cached" in repr_str


# ═══ CrawlJobResult Tests ═══


class TestCrawlJobResult:
    """Tests for CrawlJobResult dataclass."""

    def test_post_init_empty_pages(self) -> None:
        from agentcrawl.core.engine import CrawlJobResult

        job = CrawlJobResult()
        assert job.total_pages == 0
        assert job.successful_pages == 0
        assert job.failed_pages == 0
        assert job.total_words == 0
        assert job.total_tokens == 0

    def test_add_page_success(self) -> None:
        from agentcrawl.core.engine import CrawlJobResult, CrawlResult

        job = CrawlJobResult()
        page = CrawlResult(url="https://example.com", success=True, word_count=100, token_count=25)
        job.add_page(page)
        assert job.total_pages == 1
        assert job.successful_pages == 1
        assert job.failed_pages == 0
        assert job.total_words == 100
        assert job.total_tokens == 25

    def test_add_page_failure(self) -> None:
        from agentcrawl.core.engine import CrawlJobResult, CrawlResult

        job = CrawlJobResult()
        page = CrawlResult(url="https://example.com", success=False, error="Timeout")
        job.add_page(page)
        assert job.total_pages == 1
        assert job.successful_pages == 0
        assert job.failed_pages == 1

    def test_add_multiple_pages(self) -> None:
        from agentcrawl.core.engine import CrawlJobResult, CrawlResult

        job = CrawlJobResult()
        job.add_page(CrawlResult(url="https://a.com", success=True, word_count=50))
        job.add_page(CrawlResult(url="https://b.com", success=True, word_count=30))
        job.add_page(CrawlResult(url="https://c.com", success=False))
        assert job.total_pages == 3
        assert job.successful_pages == 2
        assert job.failed_pages == 1
        assert job.total_words == 80

    def test_to_dict(self) -> None:
        from agentcrawl.core.engine import CrawlJobResult

        job = CrawlJobResult(
            job_id="abc123",
            start_url="https://example.com",
            strategy="bfs",
            status="completed",
        )
        d = job.to_dict()
        assert d["job_id"] == "abc123"
        assert d["start_url"] == "https://example.com"
        assert d["strategy"] == "bfs"
        assert d["status"] == "completed"
        assert d["total_pages"] == 0
        assert d["pages"] == []

    def test_to_json(self) -> None:
        from agentcrawl.core.engine import CrawlJobResult, CrawlResult

        job = CrawlJobResult(job_id="abc", start_url="https://example.com")
        job.add_page(CrawlResult(url="https://example.com", success=True))
        import json

        data = json.loads(job.to_json())
        assert data["job_id"] == "abc"
        assert len(data["pages"]) == 1


# ═══ EngineStats Tests ═══


class TestEngineStats:
    """Tests for EngineStats dataclass."""

    def test_default_stats(self) -> None:
        from agentcrawl.core.engine import EngineStats

        stats = EngineStats()
        assert stats.total_scrapes == 0
        assert stats.total_crawls == 0
        assert stats.total_searches == 0
        assert stats.total_maps == 0
        assert stats.total_pages_scraped == 0
        assert stats.total_errors == 0
        assert stats.total_cache_hits == 0
        assert stats.total_cache_misses == 0

    def test_record_scrape_success(self) -> None:
        from agentcrawl.core.engine import CrawlResult, EngineStats

        stats = EngineStats()
        result = CrawlResult(
            url="https://example.com",
            success=True,
            word_count=100,
            token_count=25,
            response_time_ms=500.0,
        )
        stats.record_scrape(result)
        assert stats.total_scrapes == 1
        assert stats.total_pages_scraped == 1
        assert stats.total_errors == 0
        assert stats.total_cache_misses == 1
        assert stats.total_words_extracted == 100
        assert stats.total_tokens_extracted == 25
        assert stats.avg_response_time_ms == 500.0

    def test_record_scrape_failure(self) -> None:
        from agentcrawl.core.engine import CrawlResult, EngineStats

        stats = EngineStats()
        result = CrawlResult(
            url="https://example.com",
            success=False,
            error="Timeout",
        )
        stats.record_scrape(result)
        assert stats.total_scrapes == 1
        assert stats.total_errors == 1
        assert stats.total_cache_hits == 0

    def test_record_scrape_cached(self) -> None:
        from agentcrawl.core.engine import CrawlResult, EngineStats

        stats = EngineStats()
        result = CrawlResult(
            url="https://example.com",
            success=True,
            cached=True,
        )
        stats.record_scrape(result)
        assert stats.total_cache_hits == 1
        assert stats.total_cache_misses == 0

    def test_record_multiple_scrapes(self) -> None:
        from agentcrawl.core.engine import CrawlResult, EngineStats

        stats = EngineStats()
        r1 = CrawlResult(url="https://a.com", success=True, response_time_ms=100.0)
        r2 = CrawlResult(url="https://b.com", success=True, response_time_ms=300.0)
        stats.record_scrape(r1)
        stats.record_scrape(r2)
        assert stats.total_scrapes == 2
        assert stats.avg_response_time_ms == 200.0

    def test_stats_to_dict(self) -> None:
        from agentcrawl.core.engine import EngineStats

        stats = EngineStats()
        d = stats.to_dict()
        assert "total_scrapes" in d
        assert "total_crawls" in d
        assert "total_searches" in d
        assert "avg_response_time_ms" in d


# ═══ Engine Creation ═══


class TestEngineCreation:
    """Tests for engine creation edge cases."""

    def test_engine_stats_property(self, settings: Any) -> None:
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        assert engine.stats is not None
        assert engine.stats.total_scrapes == 0

    def test_ensure_started_raises(self, settings: Any) -> None:
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        with pytest.raises(RuntimeError, match="not started"):
            engine._ensure_started()


# ═══ Engine Caching Tests ═══


class TestEngineCaching:
    """Tests for caching paths in CrawlEngine."""

    @pytest.mark.asyncio
    async def test_scrape_with_cache_hit_dict(self, settings: Any) -> None:
        """Test scrape returns from cache (dict value) instead of fetching."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(
            return_value={"url": "https://example.com", "markdown": "# cached", "success": True}
        )
        engine._cache_manager = mock_cache

        config = CrawlerConfig_mock(cache=True)
        result = await engine.scrape("https://example.com", config)
        assert result.cached is True
        assert result.success is True
        assert result.markdown == "# cached"

    @pytest.mark.asyncio
    async def test_scrape_with_cache_hit_crawl_result(self, settings: Any) -> None:
        """Test scrape returns from cache (CrawlResult value)."""
        from agentcrawl.core.engine import CrawlEngine, CrawlResult

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        cached_result = CrawlResult(url="https://example.com", success=True, markdown="# cached")
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=cached_result)
        engine._cache_manager = mock_cache

        config = CrawlerConfig_mock(cache=True)
        result = await engine.scrape("https://example.com", config)
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_scrape_with_cache_hit_object(self, settings: Any) -> None:
        """Test scrape returns from cache (object with .cached attribute)."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        cached_obj = MagicMock()
        cached_obj.cached = False
        cached_obj.success = True
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=cached_obj)
        engine._cache_manager = mock_cache

        config = CrawlerConfig_mock(cache=True)
        result = await engine.scrape("https://example.com", config)
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_scrape_cache_miss_then_set(self, settings: Any) -> None:
        """Test scrape with cache miss — fetches and caches result."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock(return_value=True)
        engine._cache_manager = mock_cache

        mock_result = MagicMock()
        mock_result.success = True

        with patch.object(engine, "_fetch_and_process", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_result
            config = CrawlerConfig_mock(cache=True)
            await engine.scrape("https://example.com", config)
            mock_cache.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scrape_cache_not_enabled(self, settings: Any) -> None:
        """Test scrape without cache enabled."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.raw_html = ""
        mock_result.html = ""
        mock_result.text = ""
        mock_result.status_code = 200
        mock_result.metadata = {}
        mock_result.links = {}
        mock_result.chunks = []
        mock_result.citations = []
        mock_result.extracted_data = None
        mock_result.screenshot = ""
        mock_result.error = None
        mock_result.success = True
        mock_result.word_count = 2
        mock_result.token_count = 1

        with patch.object(engine, "_fetch_and_process", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_result
            config = CrawlerConfig_mock(cache=False)
            result = await engine.scrape("https://example.com", config)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_scrape_cache_not_set_on_failure(self, settings: Any) -> None:
        """Test cache is not set when scrape fails."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        engine._cache_manager = mock_cache

        mock_result = MagicMock()
        mock_result.success = False

        with patch.object(engine, "_fetch_and_process", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_result
            config = CrawlerConfig_mock(cache=True)
            await engine.scrape("https://example.com", config)
            mock_cache.set.assert_not_awaited()

    def test_build_cache_key(self, settings: Any) -> None:
        """Test _build_cache_key produces consistent keys."""
        from agentcrawl.config.crawler_config import CrawlerConfig
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        config = CrawlerConfig(output_format="markdown", include_links=True, only_main_content=True)
        key1 = engine._build_cache_key("https://example.com", config)
        key2 = engine._build_cache_key("https://example.com", config)
        assert key1 == key2
        assert len(key1) == 32  # sha256 hexdigest[:32]

    def test_build_cache_key_enum_format(self, settings: Any) -> None:
        """Test _build_cache_key with enum output_format."""
        from agentcrawl.config.crawler_config import CrawlerConfig
        from agentcrawl.core.engine import CrawlEngine
        from agentcrawl.core.types import OutputFormat

        engine = CrawlEngine.from_settings(settings)
        config = CrawlerConfig(
            output_format=OutputFormat.JSON,
            include_links=False,
            only_main_content=False,
        )
        key = engine._build_cache_key("https://example.com", config)
        assert len(key) == 32


# ═══ Engine Crawl Tests ═══


class TestEngineCrawlEdgeCases:
    """Tests for engine.crawl() edge cases."""

    @pytest.mark.asyncio
    async def test_crawl_default_strategy(self, settings: Any) -> None:
        """Test crawl with default strategy (None)."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_crawler = MagicMock()
        mock_crawler.discover = AsyncMock(return_value=["https://a.com/page1"])
        mock_result = MagicMock()
        mock_result.success = True

        with (
            patch("agentcrawl.crawling.bfs.BFSCrawler") as mock_bfs_cls,
            patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape,
        ):
            mock_bfs_cls.return_value = mock_crawler
            mock_scrape.return_value = mock_result
            result = await engine.crawl("https://a.com")
            assert result.strategy == "bfs"
            assert result.total_pages == 1

    @pytest.mark.asyncio
    async def test_crawl_exception_handling(self, settings: Any) -> None:
        """Test crawl handles exceptions gracefully."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_crawler = MagicMock()
        mock_crawler.discover = AsyncMock(side_effect=Exception("Crawl error!"))

        with patch("agentcrawl.crawling.bfs.BFSCrawler") as mock_bfs_cls:
            mock_bfs_cls.return_value = mock_crawler
            result = await engine.crawl("https://a.com")
            assert result.status == "failed"
            assert result.total_pages == 0

    @pytest.mark.asyncio
    async def test_crawl_scrape_exception(self, settings: Any) -> None:
        """Test crawl handles per-page scrape failures."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_crawler = MagicMock()
        mock_crawler.discover = AsyncMock(return_value=["https://a.com/page1"])

        with (
            patch("agentcrawl.crawling.bfs.BFSCrawler") as mock_bfs_cls,
            patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape,
        ):
            mock_bfs_cls.return_value = mock_crawler
            mock_scrape.side_effect = Exception("Page error")
            result = await engine.crawl("https://a.com")
            assert result.total_pages == 1
            assert result.failed_pages == 1
            assert result.status == "completed"


# ═══ Engine Search Tests ═══


class TestEngineSearchEdgeCases:
    """Tests for engine.search() edge cases."""

    @pytest.mark.asyncio
    async def test_search_not_scrape(self, settings: Any) -> None:
        """Test search without scraping results."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_search_results = [
            {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
            {"title": "Result 2", "url": "https://example.com/2", "snippet": "Snippet 2"},
        ]

        with patch("agentcrawl.search.engine.SearchEngine") as mock_search_cls:
            mock_search = MagicMock()
            mock_search.search = AsyncMock(return_value=mock_search_results)
            mock_search_cls.return_value = mock_search

            results = await engine.search("test", max_results=5, scrape=False)
            assert len(results) == 2
            assert results[0].success is True
            assert results[0].markdown == "Snippet 1"

    @pytest.mark.asyncio
    async def test_search_exception(self, settings: Any) -> None:
        """Test search handles exceptions."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        with patch("agentcrawl.search.engine.SearchEngine") as mock_search_cls:
            mock_search = MagicMock()
            mock_search.search = AsyncMock(side_effect=Exception("Search error"))
            mock_search_cls.return_value = mock_search

            results = await engine.search("test", scrape=True)
            assert results == []

    @pytest.mark.asyncio
    async def test_search_no_scrape_no_url(self, settings: Any) -> None:
        """Test search without scrape and missing url in result."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_search_results = [{"title": "No URL", "snippet": "No URL here"}]

        with patch("agentcrawl.search.engine.SearchEngine") as mock_search_cls:
            mock_search = MagicMock()
            mock_search.search = AsyncMock(return_value=mock_search_results)
            mock_search_cls.return_value = mock_search

            results = await engine.search("test", scrape=False)
            assert len(results) == 1
            assert results[0].url == ""


# ═══ Engine Extract Tests ═══


class TestEngineExtractEdgeCases:
    """Tests for engine.extract() edge cases."""

    @pytest.mark.asyncio
    async def test_extract_with_extraction_strategy_instance(self, settings: Any) -> None:
        """Test extract with an ExtractionStrategy instance in config."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.html = "<html></html>"
        mock_result.markdown = "# Hello"
        mock_result.extracted_data = {"title": "Test"}

        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value={"title": "Test"})

        with (
            patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape,
            patch("agentcrawl.extraction.base.create_extractor") as mock_create,
        ):
            mock_scrape.return_value = mock_result
            mock_create.return_value = mock_extractor
            config = _make_config(extraction=mock_extractor)
            result = await engine.extract("https://example.com", schema={}, config=config)
            mock_extractor.extract.assert_awaited_once()
            assert result.extracted_data == {"title": "Test"}

    @pytest.mark.asyncio
    async def test_extract_default_method(self, settings: Any) -> None:
        """Test extract with default LLM method."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_result = MagicMock()
        mock_result.success = False  # Not successful, so extraction won't happen

        with patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.return_value = mock_result
            result = await engine.extract("https://example.com", schema={})
            assert result.success is False

    @pytest.mark.asyncio
    async def test_extract_with_extraction_config(self, settings: Any) -> None:
        """Test extract with extraction configured in CrawlerConfig."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.html = "<html></html>"
        mock_result.markdown = "# Hello"

        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value={"key": "value"})

        config = _make_config(extraction=mock_extractor)
        with (
            patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape,
            patch("agentcrawl.extraction.base.create_extractor") as mock_create,
        ):
            mock_scrape.return_value = mock_result
            mock_create.return_value = mock_extractor
            await engine.extract("https://example.com", schema={}, config=config)
            mock_extractor.extract.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_extraction_is_string(self, settings: Any) -> None:
        """Test extract with extraction as a string method name."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.html = "<html></html>"
        mock_result.markdown = "# Hello"

        with (
            patch.object(engine, "scrape", new_callable=AsyncMock) as mock_scrape,
            patch("agentcrawl.extraction.base.create_extractor") as mock_create,
        ):
            mock_scrape.return_value = mock_result
            mock_extractor = AsyncMock()
            mock_extractor.extract = AsyncMock(return_value={"data": "test"})
            mock_create.return_value = mock_extractor

            config = CrawlerConfig_mock(extraction="css")
            await engine.extract("https://example.com", schema={}, config=config)
            mock_create.assert_called_once()


# ═══ Engine map_site Tests ═══


class TestEngineMapSite:
    """Tests for engine.map_site()."""

    @pytest.mark.asyncio
    async def test_map_site_returns_urls(self, settings: Any) -> None:
        """Test map_site returns discovered URLs."""
        from agentcrawl.core.engine import CrawlEngine

        engine = CrawlEngine.from_settings(settings)
        engine._is_started = True

        mock_crawler = MagicMock()
        mock_crawler.discover = AsyncMock(
            return_value=["https://a.com/1", "https://a.com/2", "https://a.com/3"]
        )

        with patch("agentcrawl.crawling.bfs.BFSCrawler") as mock_bfs_cls:
            mock_bfs_cls.return_value = mock_crawler
            urls = await engine.map_site("https://a.com", max_pages=100)
            assert len(urls) == 3
            assert "https://a.com/1" in urls


# ═══ Helper ═══


def _make_config(**kwargs: Any) -> Any:
    """Create a CrawlerConfig mock with proper attributes.

    Filters kwargs to only valid dataclass fields, and sets extra attrs separately.
    """
    from agentcrawl.config.crawler_config import CrawlerConfig

    defaults = {
        "output_format": "markdown",
        "include_links": True,
        "include_metadata": True,
        "only_main_content": True,
        "cache": False,
        "timeout": 30,
    }
    defaults.update(kwargs)
    valid_fields = {k: v for k, v in defaults.items() if k in CrawlerConfig.__dataclass_fields__}
    config = CrawlerConfig(**valid_fields)
    # Set any extra attributes that aren't in the dataclass (e.g. extraction)
    for k, v in kwargs.items():
        if k not in CrawlerConfig.__dataclass_fields__:
            setattr(config, k, v)
    return config


# Alias for use in tests
CrawlerConfig_mock = _make_config
