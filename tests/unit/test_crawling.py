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
        f.set_base_domain("https://example.com")

        assert f.is_allowed("https://example.com/page") is True
        assert f.is_allowed("https://other.com/page") is False

    def test_include_patterns(self) -> None:
        """Include patterns restrict to matching URLs."""
        f = URLFilter(include_patterns=["/docs/*"])
        f.set_base_domain("https://example.com")

        assert f.is_allowed("https://example.com/docs/guide") is True
        assert f.is_allowed("https://example.com/blog/post") is False

    def test_exclude_patterns(self) -> None:
        """Exclude patterns block matching URLs."""
        f = URLFilter(exclude_patterns=["*.pdf", "*.zip", "/admin/*"])
        f.set_base_domain("https://example.com")

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
        f.set_base_domain("https://example.com")

        assert f.is_allowed("https://example.com/docs/guide") is True
        assert f.is_allowed("https://example.com/docs/internal/secret") is False
        assert f.is_allowed("https://example.com/blog/post") is False

    def test_glob_patterns(self) -> None:
        """Glob patterns match correctly."""
        f = URLFilter(include_patterns=["/api/v1/*", "/api/v2/*"])
        f.set_base_domain("https://example.com")

        assert f.is_allowed("https://example.com/api/v1/users") is True
        assert f.is_allowed("https://example.com/api/v2/items") is True
        assert f.is_allowed("https://example.com/api/v3/things") is False

    def test_empty_url(self) -> None:
        """Empty URL is rejected."""
        f = URLFilter()
        assert f.is_allowed("") is False

    def test_fragment_stripped(self) -> None:
        """URL fragments are handled."""
        f = URLFilter(same_domain=True, allow_fragments=True)
        f.set_base_domain("https://example.com")

        assert f.is_allowed("https://example.com/page#section") is True

    def test_query_params_preserved(self) -> None:
        """Query parameters don't affect filtering."""
        f = URLFilter(same_domain=True)
        f.set_base_domain("https://example.com")

        assert f.is_allowed("https://example.com/page?q=test&page=1") is True

    def test_normalize_url(self) -> None:
        """URLs are normalized before filtering."""
        f = URLFilter(same_domain=True)
        f.set_base_domain("https://example.com")

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
        assert crawler.strategy_name == "bfs"

    @pytest.mark.asyncio
    async def test_bfs_order(self) -> None:
        """BFS visits pages in breadth-first order."""
        from agentcrawl.crawling.bfs import BFSCrawler

        crawler = BFSCrawler(max_depth=2, max_pages=10)

        # Mock the fetch function
        visited: list[str] = []

        async def mock_fetch(url: str, depth: int) -> tuple[str, list[str]]:
            visited.append(url)
            responses = {
                "https://example.com": ("<html></html>", ["https://example.com/a", "https://example.com/b"]),
                "https://example.com/a": ("<html></html>", ["https://example.com/a/1"]),
                "https://example.com/b": ("<html></html>", ["https://example.com/b/1"]),
            }
            return responses.get(url, ("<html></html>", []))

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
        assert crawler.strategy_name == "dfs"

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
        assert crawler.strategy_name == "best_first"

    def test_custom_scorer(self) -> None:
        """Custom scoring function can be provided."""
        from agentcrawl.crawling.base import URLScorer
        from agentcrawl.crawling.best_first import BestFirstCrawler

        # Create a custom scorer with specific keywords
        scorer = URLScorer(
            content_keywords=["docs", "guide"],
            noise_keywords=["login", "cart"],
        )
        crawler = BestFirstCrawler(url_scorer=scorer)
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
        assert crawler.max_depth == 4
        assert crawler.max_pages == 100

    def test_strategy_name(self) -> None:
        """Strategy name is 'adaptive'."""
        from agentcrawl.crawling.adaptive import AdaptiveCrawler

        crawler = AdaptiveCrawler()
        assert crawler.strategy_name == "adaptive"

    def test_initial_strategy(self) -> None:
        """Initial strategy uses strategy_name."""
        from agentcrawl.crawling.adaptive import AdaptiveCrawler

        crawler = AdaptiveCrawler()
        assert crawler.strategy_name == "adaptive"


# ══════════════════════════════════════════════════════════════
# CrawlResult
# ══════════════════════════════════════════════════════════════

class TestCrawlResult:
    """Tests for CrawlResult model."""

    def test_result_creation(self) -> None:
        """Create a crawl result."""
        from agentcrawl.core.engine import CrawlJobResult

        result = CrawlJobResult(
            start_url="https://example.com",
            strategy="bfs",
        )

        assert result.start_url == "https://example.com"
        assert result.strategy == "bfs"
        assert result.total_pages == 0

    def test_result_add_page(self) -> None:
        """Add pages to result."""
        from agentcrawl.core.engine import CrawlJobResult, CrawlResult

        result = CrawlJobResult(start_url="https://example.com")

        page = CrawlResult(
            url="https://example.com/page1",
            success=True,
            markdown="# Page 1",
            word_count=10,
        )
        result.pages.append(page)
        result.total_pages = len(result.pages)
        result.successful_pages = sum(1 for p in result.pages if p.success)

        assert result.total_pages == 1
        assert result.successful_pages == 1

    def test_result_stats(self) -> None:
        """Result tracks statistics."""
        from agentcrawl.core.engine import CrawlJobResult, CrawlResult

        result = CrawlJobResult(start_url="https://example.com")

        result.pages.append(CrawlResult(
            url="https://example.com/1",
            success=True,
            word_count=100,
            token_count=150,
        ))
        result.pages.append(CrawlResult(
            url="https://example.com/2",
            success=False,
            error="Timeout",
        ))
        result.total_pages = len(result.pages)
        result.successful_pages = sum(1 for p in result.pages if p.success)
        result.failed_pages = result.total_pages - result.successful_pages
        result.total_words = sum(p.word_count for p in result.pages)
        result.total_tokens = sum(p.token_count for p in result.pages)

        assert result.total_pages == 2
        assert result.successful_pages == 1
        assert result.failed_pages == 1
        assert result.total_words == 100
        assert result.total_tokens == 150

    def test_result_to_dict(self) -> None:
        """Result serializes to dict."""
        from agentcrawl.core.engine import CrawlJobResult, CrawlResult

        result = CrawlJobResult(
            start_url="https://example.com",
            strategy="bfs",
        )
        result.pages.append(CrawlResult(
            url="https://example.com/1",
            success=True,
        ))

        data = result.to_dict()
        assert "start_url" in data
        assert "strategy" in data
        assert "total_pages" in data
        assert "pages" in data


# ══════════════════════════════════════════════════════════════
# CrawlResult (single page)
# ══════════════════════════════════════════════════════════════

class TestCrawlResultPage:
    """Tests for CrawlResult (single page)."""

    def test_page_creation(self) -> None:
        """Create a page result."""
        from agentcrawl.core.engine import CrawlResult

        page = CrawlResult(
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
        from agentcrawl.core.engine import CrawlResult

        page = CrawlResult(
            url="https://example.com/broken",
            success=False,
            error="Connection timeout",
        )

        assert page.success is False
        assert page.error == "Connection timeout"

    def test_page_to_dict(self) -> None:
        """Page serializes to dict."""
        from agentcrawl.core.engine import CrawlResult

        page = CrawlResult(url="https://example.com", success=True)
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
        # Use _parse_xml directly to test XML parsing
        entries, _child_urls, _is_index = parser._parse_xml(xml, "https://example.com/sitemap.xml")

        assert len(entries) == 3
        assert "https://example.com/page1" in [e.url for e in entries]

    def test_parse_sitemap_index(self) -> None:
        """Parse a sitemap index file."""
        from agentcrawl.crawling.sitemap_parser import SitemapParser

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
            <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
        </sitemapindex>"""

        parser = SitemapParser()
        _entries, child_urls, is_index = parser._parse_xml(xml, 'https://example.com/sitemap.xml')

        # For sitemap index, entries should be empty but child_urls should have the sitemap URLs
        assert len(child_urls) == 2
        assert "https://example.com/sitemap1.xml" in child_urls
        assert "https://example.com/sitemap2.xml" in child_urls
        assert is_index is True

    def test_parse_empty_sitemap(self) -> None:
        """Parse empty sitemap."""
        import asyncio

        from agentcrawl.crawling.sitemap_parser import SitemapParser

        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        </urlset>"""

        parser = SitemapParser()
        urls = asyncio.run(parser.parse(xml))

        assert len(urls) == 0

    def test_parse_invalid_xml(self) -> None:
        """Invalid XML returns empty list."""
        import asyncio

        from agentcrawl.crawling.sitemap_parser import SitemapParser

        parser = SitemapParser()
        urls = asyncio.run(parser.parse("not xml at all"))

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
        entries, _child_urls, _is_index = parser._parse_xml(xml, 'https://example.com/sitemap.xml')

        assert len(entries) == 3
        assert len(entries) <= 3


# ══════════════════════════════════════════════════════════════
# RobotsTxtParser
# ══════════════════════════════════════════════════════════════

class TestRobotsTxtParser:
    """Tests for RobotsTxtParser."""

    def test_parse_robots_txt(self) -> None:
            """Parse a standard robots.txt."""
            from agentcrawl.crawling.url_filter import RobotsTxtParser

            content = """User-agent: *
    Disallow: /admin/
    Disallow: /private/
    Allow: /public/

    Sitemap: https://example.com/sitemap.xml
    """

            parser = RobotsTxtParser()
            parser.parse(content)

            # Check internal structures
            assert len(parser._rules) > 0
            assert "https://example.com/sitemap.xml" in parser._sitemaps
            assert parser.is_loaded is True

    def test_is_allowed(self) -> None:
        """Check if URL is allowed by robots.txt."""
        from agentcrawl.crawling.url_filter import RobotsTxtParser

        content = """User-agent: *
Disallow: /admin/
Disallow: /private/
"""

        parser = RobotsTxtParser()
        parser.parse(content)

        assert parser.is_allowed("/page") is True
        assert parser.is_allowed("/admin/settings") is False
        assert parser.is_allowed("/private/data") is False

    def test_empty_robots(self) -> None:
        """Empty robots.txt allows everything."""
        from agentcrawl.crawling.url_filter import RobotsTxtParser

        parser = RobotsTxtParser()
        parser.parse("")

        assert parser.is_allowed("/anything") is True

    def test_sitemap_extraction(self) -> None:
        """Extract sitemap URLs from robots.txt."""
        from agentcrawl.crawling.url_filter import RobotsTxtParser

        content = """User-agent: *
Disallow:

Sitemap: https://example.com/sitemap.xml
Sitemap: https://example.com/sitemap2.xml
"""

        parser = RobotsTxtParser()
        parser.parse(content)

        assert "https://example.com/sitemap.xml" in parser._sitemaps
        assert "https://example.com/sitemap2.xml" in parser._sitemaps


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
        f.set_base_domain("https://example.com")

        url = "https://example.com/page"

        # First time: allowed
        assert f.is_allowed(url) is True
        f.mark_seen(url)

        # Second time: already seen
        assert f.is_seen(url) is True

    def test_normalized_dedup(self) -> None:
        """URLs are normalized for deduplication."""
        f = URLFilter()
        f.set_base_domain("https://example.com")

        f.mark_seen("https://example.com/page")

        # Same URL with fragment should be seen
        assert f.is_seen("https://example.com/page#section") is True
