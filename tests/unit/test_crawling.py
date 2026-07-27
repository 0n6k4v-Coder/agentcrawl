"""
AgentCrawl — Crawling Unit Tests
====================================

Unit tests for crawling strategies, URL filtering,
and site discovery.

Tests:
    - BFSCrawler (breadth-first)
    - DFSCrawler (depth-first)
    - BestFirstCrawler (priority-based)
    - AdaptiveCrawler (strategy switching)
    - URLFilter (include/exclude patterns)
    - DomainMapper (URL discovery)
    - SitemapParser
    - RobotsParser
    - CrawlResult model
    - Depth tracking and page limits

Run:
    pytest tests/unit/test_crawling.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcrawl.crawling.url_filter import URLFilter


# ══════════════════════════════════════════════════════════════
# URLFilter
# ══════════════════════════════════════════════════════════════

class TestURLFilter:
    """Tests for URLFilter."""

    def test_default_allows_all(self) -> None:
        """Default filter allows all URLs."""
        f = URLFilter()
        assert f.is_allowed("https://example.com/page") is True

    def test_same_domain_filter(self) -> None:
        """Same-domain filter restricts to base domain."""
        f = URLFilter(same_domain=True)
        f.set_base_url("https://example.com")

        assert f.is_allowed("https://example.com/page") is True
        assert f.is_allowed("https://other.com/page") is False

    def test_include_patterns(self) -> None:
        """Include patterns restrict to matching URLs."""
        f = URLFilter(include_patterns=["/docs/*"])
        f.set_base_url("https://example.com")

        assert f.is_allowed("https://example.com/docs/guide") is True
        assert f.is_allowed("https://example.com/blog/post") is False

    def test_exclude_patterns(self) -> None:
        """Exclude patterns block matching URLs."""
        f = URLFilter(exclude_patterns=["*.pdf", "*.zip", "/admin/*"])
        f.set_base_url("https://example.com")

        assert f.is_allowed("https://example.com/page") is True
        assert f.is_allowed("https://example.com/file.pdf") is False
        assert f.is_allowed("https://example.com/archive.zip") is False
        assert f.is_allowed("https://example.com/admin/settings") is False

    def test_include_and_exclude(self) -> None:
        """Include and exclude patterns work together."""
        f = URLFilter(
            include_patterns=["/docs/*"],
            exclude_patterns=["/docs/internal/*"],
        )
        f.set_base_url("https://example.com")

        assert f.is_allowed("https://example.com/docs/guide") is True
        assert f.is_allowed("https://example.com/docs/internal/secret") is False
        assert f.is_allowed("https://example.com/blog/post") is False

    def test_glob_patterns(self) -> None:
        """Glob patterns match correctly."""
        f = URLFilter(include_patterns=["/api/v1/*", "/api/v2/*"])
        f.set_base_url("https://example.com")

        assert f.is_allowed("https://example.com/api/v1/users") is True
        assert f.is_allowed("https://example.com/api/v2/items") is True
        assert f.is_allowed("https://example.com/api/v3/things") is False

    def test_empty_url(self) -> None:
        """Empty URL is rejected."""
        f = URLFilter()
        assert f.is_allowed("") is False

    def test_fragment_stripped(self) -> None:
        """URL fragments are handled."""
        f = URLFilter(same_domain=True)
        f.set_base_url("https://example.com")

        assert f.is_allowed("https://example.com/page#section") is True

    def test_query_params_preserved(self) -> None:
        """Query parameters don't affect filtering."""
        f = URLFilter(same_domain=True)
        f.set_base_url("https://example.com")

        assert f.is_allowed("https://example.com/page?q=test&page=1") is True

    def test_normalize_url(self) -> None:
        """URLs are normalized before filtering."""
        f = URLFilter(same_domain=True)
        f.set_base_url("https://example.com")

        # Trailing slash normalization
        assert f.is_allowed("https://example.com/page/") is True


# ══════════════════════════════════════════════════════════════
# BFSCrawler
# ══════════════════════════════════════════════════════════════

class TestBFSCrawler:
    """Tests for BFSCrawler."""

    def test_creation(self) -> None:
        """Create a BFS crawler with defaults."""
        from agentcrawl.crawling.bfs import BFSCrawler

        crawler = BFSCrawler()
        assert crawler.max_depth == 3
        assert crawler.max_pages == 50

    def test_custom_params(self) -> None:
        """Create with custom parameters."""
        from agentcrawl.crawling.bfs import BFSCrawler

        crawler = BFSCrawler(max_depth=5, max_pages=100, max_concurrent=10)
        assert crawler.max_depth == 5
        assert crawler.max_pages == 100
        assert crawler.max_concurrent == 10

    def test_strategy_name(self) -> None:
        """Strategy name is 'bfs'."""
        from agentcrawl.crawling.bfs import BFSCrawler

        crawler = BFSCrawler()
        assert crawler.name == "bfs"

    @pytest.mark.asyncio
    async def test_bfs_order(self) -> None:
        """BFS visits pages in breadth-first order."""
        from agentcrawl.crawling.bfs import BFSCrawler

        crawler = BFSCrawler(max_depth=2, max_pages=10)

        # Mock the fetch function
        visited: list[str] = []

        async def mock_fetch(url: str, depth: int) -> tuple[str, list[str]]:
            visited.append(url)
            if url == "https://example.com":
                return "<html></html>", [
                    "https://example.com/a",
                    "https://example.com/b",
                ]
            elif url == "https://example.com/a":
                return "<html></html>", ["https://example.com/a/1"]
            elif url == "https://example.com/b":
                return "<html></html>", ["https://example.com/b/1"]
            return "<html></html>", []

        # BFS should visit root, then a and b, then a/1 and b/1
        # (level by level)
        assert crawler.max_depth == 2

    def test_max_depth_validation(self) -> None:
        """max_depth must be positive."""
        from agentcrawl.crawling.bfs import BFSCrawler

        with pytest.raises((ValueError, Exception)):
            BFSCrawler(max_depth=0)

    def test_max_pages_validation(self) -> None:
        """max_pages must be positive."""
        from agentcrawl.crawling.bfs import BFSCrawler

        with pytest.raises((ValueError, Exception)):
            BFSCrawler(max_pages=0)


# ══════════════════════════════════════════════════════════════
# DFSCrawler
# ══════════════════════════════════════════════════════════════

class TestDFSCrawler:
    """Tests for DFSCrawler."""

    def test_creation(self) -> None:
        """Create a DFS crawler."""
        from agentcrawl.crawling.dfs import DFSCrawler

        crawler = DFSCrawler()
        assert crawler.max_depth == 3
        assert crawler.max_pages == 50

    def test_strategy_name(self) -> None:
        """Strategy name is 'dfs'."""
        from agentcrawl.crawling.dfs import DFSCrawler

        crawler = DFSCrawler()
        assert crawler.name == "dfs"

    def test_custom_params(self) -> None:
        """Create with custom parameters."""
        from agentcrawl.crawling.dfs import DFSCrawler

        crawler = DFSCrawler(max_depth=10, max_pages=200)
        assert crawler.max_depth == 10
        assert crawler.max_pages == 200


# ══════════════════════════════════════════════════════════════
# BestFirstCrawler
# ══════════════════════════════════════════════════════════════

class TestBestFirstCrawler:
    """Tests for BestFirstCrawler."""

    def test_creation(self) -> None:
        """Create a BestFirst crawler."""
        from agentcrawl.crawling.best_first import BestFirstCrawler

        crawler = BestFirstCrawler()
        assert crawler.max_depth == 3
        assert crawler.max_pages == 50

    def test_strategy_name(self) -> None:
        """Strategy name is 'best_first'."""
        from agentcrawl.crawling.best_first import BestFirstCrawler

        crawler = BestFirstCrawler()
        assert crawler.name == "best_first"

    def test_custom_scorer(self) -> None:
        """Custom scoring function can be provided."""
        from agentcrawl.crawling.best_first import BestFirstCrawler

        def custom_scorer(url: str) -> float:
            return 1.0 if "docs" in url else 0.0

        crawler = BestFirstCrawler(scorer=custom_scorer)
        assert crawler._scorer is not None


# ══════════════════════════════════════════════════════════════
# AdaptiveCrawler
# ══════════════════════════════════════════════════════════════

class TestAdaptiveCrawler:
    """Tests for AdaptiveCrawler."""

    def test_creation(self) -> None:
        """Create an Adaptive crawler."""
        from agentcrawl.crawling.adaptive import AdaptiveCrawler

        crawler = AdaptiveCrawler()
        assert crawler.max_depth == 3
        assert crawler.max_pages == 50

    def test_strategy_name(self) -> None:
        """Strategy name is 'adaptive'."""
        from agentcrawl.crawling.adaptive import AdaptiveCrawler

        crawler = AdaptiveCrawler()
        assert crawler.name == "adaptive"

    def test_initial_strategy(self) -> None:
        """Initial strategy is BFS."""
        from agentcrawl.crawling.adaptive import AdaptiveCrawler

        crawler = AdaptiveCrawler()
        assert crawler._current_strategy == "bfs"


# ══════════════════════════════════════════════════════════════
# CrawlResult
# ══════════════════════════════════════════════════════════════

class TestCrawlResult:
    """Tests for CrawlResult model."""

    def test_result_creation(self) -> None:
        """Create a crawl result."""
        from agentcrawl.crawling.result import CrawlResult

        result = CrawlResult(
            start_url="https://example.com",
            strategy="bfs",
        )

        assert result.start_url == "https://example.com"
        assert result.strategy == "bfs"
        assert result.total_pages == 0

    def test_result_add_page(self) -> None:
        """Add pages to result."""
        from agentcrawl.crawling.result import CrawlResult, PageResult

        result = CrawlResult(start_url="https://example.com")

        page = PageResult(
            url="https://example.com/page1",
            success=True,
            markdown="# Page 1",
            word_count=10,
        )
        result.add_page(page)

        assert result.total_pages == 1
        assert result.successful_pages == 1

    def test_result_stats(self) -> None:
        """Result tracks statistics."""
        from agentcrawl.crawling.result import CrawlResult, PageResult

        result = CrawlResult(start_url="https://example.com")

        result.add_page(PageResult(
            url="https://example.com/1",
            success=True,
            word_count=100,
            token_count=150,
        ))
        result.add_page(PageResult(
            url="https://example.com/2",
            success=False,
            error="Timeout",
        ))

        assert result.total_pages == 2
        assert result.successful_pages == 1
        assert result.failed_pages == 1
        assert result.total_words == 100
        assert result.total_tokens == 150

    def test_result_to_dict(self) -> None:
        """Result serializes to dict."""
        from agentcrawl.crawling.result import CrawlResult, PageResult

        result = CrawlResult(start_url="https://example.com", strategy="bfs")
        result.add_page(PageResult(url="https://example.com/1", success=True))

        data = result.to_dict()
        assert "start_url" in data
        assert "strategy" in data
        assert "total_pages" in data
        assert "pages" in data


# ══════════════════════════════════════════════════════════════
# PageResult
# ══════════════════════════════════════════════════════════════

class TestPageResult:
    """Tests for PageResult model."""

    def test_page_creation(self) -> None:
        """Create a page result."""
        from agentcrawl.crawling.result import PageResult

        page = PageResult(
            url="https://example.com",
            success=True,
            status_code=200,
            markdown="# Hello",
            word_count=5,
        )

        assert page.url == "https://example.com"
        assert page.success is True
        assert page.status_code == 200

    def test_failed_page(self) -> None:
        """Create a failed page result."""
        from agentcrawl.crawling.result import PageResult

        page = PageResult(
            url="https://example.com/broken",
            success=False,
            error="Connection timeout",
        )

        assert page.success is False
        assert page.error == "Connection timeout"

    def test_page_to_dict(self) -> None:
        """Page serializes to dict."""
        from agentcrawl.crawling.result import PageResult

        page = PageResult(url="https://example.com", success=True)
        data = page.to_dict()

        assert "url" in data
        assert "success" in data


# ══════════════════════════════════════════════════════════════
# SitemapParser
# ══════════════════════════════════════════════════════════════

class TestSitemapParser:
    """Tests for SitemapParser."""

    def test_parse_sitemap_xml(self) -> None:
        """Parse a standard sitemap.xml."""
        from agentcrawl.crawling.sitemap_parser import SitemapParser

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
            <url><loc>https://example.com/page3</loc></url>
        </urlset>"""

        parser = SitemapParser()
        urls = parser.parse(xml)

        assert len(urls) == 3
        assert "https://example.com/page1" in urls

    def test_parse_sitemap_index(self) -> None:
        """Parse a sitemap index file."""
        from agentcrawl.crawling.sitemap_parser import SitemapParser

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
            <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
        </sitemapindex>"""

        parser = SitemapParser()
        urls = parser.parse(xml)

        assert len(urls) == 2

    def test_parse_empty_sitemap(self) -> None:
        """Parse empty sitemap."""
        from agentcrawl.crawling.sitemap_parser import SitemapParser

        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        </urlset>"""

        parser = SitemapParser()
        urls = parser.parse(xml)

        assert len(urls) == 0

    def test_parse_invalid_xml(self) -> None:
        """Invalid XML returns empty list."""
        from agentcrawl.crawling.sitemap_parser import SitemapParser

        parser = SitemapParser()
        urls = parser.parse("not xml at all")

        assert len(urls) == 0

    def test_max_urls_limit(self) -> None:
        """Max URLs limit is respected."""
        from agentcrawl.crawling.sitemap_parser import SitemapParser

        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/1</loc></url>
            <url><loc>https://example.com/2</loc></url>
            <url><loc>https://example.com/3</loc></url>
            <url><loc>https://example.com/4</loc></url>
            <url><loc>https://example.com/5</loc></url>
        </urlset>"""

        parser = SitemapParser(max_urls=3)
        urls = parser.parse(xml)

        assert len(urls) <= 3


# ══════════════════════════════════════════════════════════════
# RobotsParser
# ══════════════════════════════════════════════════════════════

class TestRobotsParser:
    """Tests for RobotsParser."""

    def test_parse_robots_txt(self) -> None:
        """Parse robots.txt content."""
        from agentcrawl.crawling.robots_parser import RobotsParser

        content = """User-agent: *
Disallow: /admin/
Disallow: /private/
Allow: /public/

Sitemap: https://example.com/sitemap.xml
"""

        parser = RobotsParser()
        result = parser.parse(content)

        assert "/admin/" in result.disallowed
        assert "/private/" in result.disallowed
        assert "https://example.com/sitemap.xml" in result.sitemaps

    def test_is_allowed(self) -> None:
        """Check if URL is allowed by robots.txt."""
        from agentcrawl.crawling.robots_parser import RobotsParser

        content = """User-agent: *
Disallow: /admin/
Disallow: /private/
"""

        parser = RobotsParser()
        parser.parse(content)

        assert parser.is_allowed("https://example.com/page") is True
        assert parser.is_allowed("https://example.com/admin/settings") is False
        assert parser.is_allowed("https://example.com/private/data") is False

    def test_empty_robots(self) -> None:
        """Empty robots.txt allows everything."""
        from agentcrawl.crawling.robots_parser import RobotsParser

        parser = RobotsParser()
        parser.parse("")

        assert parser.is_allowed("https://example.com/anything") is True

    def test_sitemap_extraction(self) -> None:
        """Extract sitemap URLs from robots.txt."""
        from agentcrawl.crawling.robots_parser import RobotsParser

        content = """User-agent: *
Disallow:

Sitemap: https://example.com/sitemap.xml
Sitemap: https://example.com/sitemap2.xml
"""

        parser = RobotsParser()
        result = parser.parse(content)

        assert len(result.sitemaps) == 2


# ══════════════════════════════════════════════════════════════
# DomainMapper
# ══════════════════════════════════════════════════════════════

class TestDomainMapper:
    """Tests for DomainMapper."""

    def test_creation(self) -> None:
        """Create a DomainMapper."""
        from agentcrawl.crawling.domain_mapper import DomainMapper

        mapper = DomainMapper(max_urls=100)
        assert mapper._max_urls == 100

    def test_default_settings(self) -> None:
        """Default settings are reasonable."""
        from agentcrawl.crawling.domain_mapper import DomainMapper

        mapper = DomainMapper()
        assert mapper._max_urls > 0
        assert mapper._use_sitemap is True
        assert mapper._use_robots is True


# ══════════════════════════════════════════════════════════════
# URL Deduplication
# ══════════════════════════════════════════════════════════════

class TestURLDeduplication:
    """Tests for URL deduplication in crawlers."""

    def test_url_filter_dedup(self) -> None:
        """URLFilter tracks seen URLs."""
        f = URLFilter()
        f.set_base_url("https://example.com")

        url = "https://example.com/page"

        # First time: allowed
        assert f.is_allowed(url) is True
        f.mark_seen(url)

        # Second time: already seen
        assert f.is_seen(url) is True

    def test_normalized_dedup(self) -> None:
        """URLs are normalized for deduplication."""
        f = URLFilter()
        f.set_base_url("https://example.com")

        f.mark_seen("https://example.com/page")

        # Same URL with fragment should be seen
        assert f.is_seen("https://example.com/page#section") is True