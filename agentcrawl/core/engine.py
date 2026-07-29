"""
AgentCrawl — Core Crawl Engine
==================================

The central orchestrator that coordinates all layers (browser,
content processing, extraction, caching) into a unified pipeline.
Shared by both Package Mode and Server Mode.

Pipeline:
    URL → Fetch (Browser) → Parse (HTML) → Extract (Markdown/JSON)
        → Filter (BM25/Pruning) → Chunk (Topic/Sentence/Regex)
        → Citations → Output (CrawlResult)

Usage:
    from agentcrawl.core.engine import CrawlEngine
    from agentcrawl.config import Settings, CrawlerConfig

    # From settings
    engine = CrawlEngine.from_settings(Settings())
    await engine.startup()

    # Scrape a page
    result = await engine.scrape(
        url="https://example.com",
        config=CrawlerConfig(output_format="markdown"),
    )
    print(result.markdown)

    # Crawl a website
    results = await engine.crawl(
        url="https://docs.example.com",
        strategy=BFSCrawler(max_depth=3, max_pages=50),
    )

    # Search
    results = await engine.search(query="python tutorial", max_results=5)

    # Shutdown
    await engine.shutdown()

    # Or use as context manager
    async with CrawlEngine.from_settings(settings) as engine:
        result = await engine.scrape("https://example.com")
        print(result.markdown)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from agentcrawl.browser.manager import BrowserManager
from agentcrawl.config.crawler_config import CrawlerConfig
from agentcrawl.config.settings import Settings

if TYPE_CHECKING:
    from agentcrawl.browser.config import BrowserConfig

logger = logging.getLogger("agentcrawl.core.engine")


# ═══════════════════════════════════════════════════════════════
# Result Models
# ═══════════════════════════════════════════════════════════════

@dataclass
class CrawlResult:
    """
    Result of a single page scrape.

    Attributes:
        url: The scraped URL.
        success: Whether the scrape was successful.
        status_code: HTTP status code.
        markdown: Clean Markdown content.
        html: Cleaned HTML content.
        raw_html: Original raw HTML.
        json: Structured JSON output.
        text: Plain text content.
        metadata: Page metadata (title, description, og:tags).
        links: Extracted links (internal, external, all).
        citations: Extracted citations for content.
        chunks: Content chunks for RAG.
        extracted_data: Structured extraction result.
        screenshot: Base64 screenshot (if enabled).
        error: Error message (if failed).
        response_time_ms: Total response time in milliseconds.
        word_count: Word count of extracted content.
        token_count: Estimated token count.
        cached: Whether the result came from cache.
        request_id: Unique request identifier.
    """
    url: str
    success: bool = False
    status_code: int = 0
    markdown: str = ""
    html: str = ""
    raw_html: str = ""
    json: dict[str, Any] | None = None
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    links: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    extracted_data: Any = None
    screenshot: str = ""
    error: str | None = None
    response_time_ms: float = 0.0
    word_count: int = 0
    token_count: int = 0
    cached: bool = False
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])

    def __post_init__(self) -> None:
        if self.word_count == 0 and self.markdown:
            self.word_count = len(self.markdown.split())
        if self.token_count == 0 and self.markdown:
            self.token_count = max(1, len(self.markdown) // 4)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "url": self.url,
            "success": self.success,
            "status_code": self.status_code,
            "markdown": self.markdown,
            "metadata": self.metadata,
            "links": self.links,
            "word_count": self.word_count,
            "token_count": self.token_count,
            "response_time_ms": round(self.response_time_ms, 2),
            "cached": self.cached,
            "request_id": self.request_id,
        }

        if self.html:
            result["html"] = self.html
        if self.json:
            result["json"] = self.json
        if self.citations:
            result["citations"] = self.citations
        if self.chunks:
            result["chunks"] = self.chunks
        if self.extracted_data is not None:
            result["extracted_data"] = self.extracted_data
        if self.screenshot:
            result["screenshot"] = self.screenshot[:100] + "..."
        if self.error:
            result["error"] = self.error

        return result

    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def __repr__(self) -> str:
        status_icon = "✓" if self.success else "✗"
        return (
            f"CrawlResult({status_icon} {self.status_code}, "
            f"url={self.url!r}, "
            f"time={self.response_time_ms:.0f}ms"
            f"{', cached' if self.cached else ''})"
        )


@dataclass
class CrawlJobResult:
    """
    Result of a multi-page crawl job.

    Attributes:
        job_id: Unique job identifier.
        start_url: Starting URL.
        pages: List of CrawlResult for each page.
        total_pages: Total pages crawled.
        successful_pages: Pages scraped successfully.
        failed_pages: Pages that failed.
        total_words: Total word count across all pages.
        total_tokens: Total estimated tokens.
        duration_ms: Total crawl duration.
        strategy: Crawling strategy used.
        status: Job status ('completed', 'partial', 'failed').
    """
    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    start_url: str = ""
    pages: list[CrawlResult] = field(default_factory=list)
    total_pages: int = 0
    successful_pages: int = 0
    failed_pages: int = 0
    total_words: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0
    strategy: str = ""
    status: str = "completed"

    def __post_init__(self) -> None:
        self._update_stats()

    def _update_stats(self) -> None:
        """Recalculate statistics from pages."""
        self.total_pages = len(self.pages)
        self.successful_pages = sum(1 for p in self.pages if p.success)
        self.failed_pages = self.total_pages - self.successful_pages
        self.total_words = sum(p.word_count for p in self.pages)
        self.total_tokens = sum(p.token_count for p in self.pages)

    def add_page(self, page: CrawlResult) -> None:
        """Add a page and update statistics."""
        self.pages.append(page)
        self._update_stats()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "start_url": self.start_url,
            "total_pages": self.total_pages,
            "successful_pages": self.successful_pages,
            "failed_pages": self.failed_pages,
            "total_words": self.total_words,
            "total_tokens": self.total_tokens,
            "duration_ms": round(self.duration_ms, 2),
            "strategy": self.strategy,
            "status": self.status,
            "pages": [p.to_dict() for p in self.pages],
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ════════════════════════════════════════════════════════════════
# Engine Statistics
# ════════════════════════════════════════════════════════════════

@dataclass
class EngineStats:
    """Cumulative engine statistics."""
    total_scrapes: int = 0
    total_crawls: int = 0
    total_searches: int = 0
    total_maps: int = 0
    total_pages_scraped: int = 0
    total_errors: int = 0
    total_cache_hits: int = 0
    total_cache_misses: int = 0
    total_words_extracted: int = 0
    total_tokens_extracted: int = 0
    avg_response_time_ms: float = 0.0
    _total_response_time_ms: float = 0.0

    def record_scrape(self, result: CrawlResult) -> None:
        self.total_scrapes += 1
        self.total_pages_scraped += 1
        self._total_response_time_ms += result.response_time_ms
        self.avg_response_time_ms = (
            self._total_response_time_ms / self.total_scrapes
        )
        if not result.success:
            self.total_errors += 1
        if result.cached:
            self.total_cache_hits += 1
        else:
            self.total_cache_misses += 1
        if result.success:
            self.total_words_extracted += result.word_count
            self.total_tokens_extracted += result.token_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_scrapes": self.total_scrapes,
            "total_crawls": self.total_crawls,
            "total_searches": self.total_searches,
            "total_maps": self.total_maps,
            "total_pages_scraped": self.total_pages_scraped,
            "total_errors": self.total_errors,
            "total_cache_hits": self.total_cache_hits,
            "total_cache_misses": self.total_cache_misses,
            "total_words_extracted": self.total_words_extracted,
            "total_tokens_extracted": self.total_tokens_extracted,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
        }


# ════════════════════════════════════════════════════════════════
# CrawlEngine
# ════════════════════════════════════════════════════════════════

class CrawlEngine:
    """
    Main crawl engine coordinating all pipeline stages.

    Features:
        - Multi-browser support (Chromium, Firefox, WebKit)
        - Configurable content processing pipeline
        - Content filtering (Pruning, BM25)
        - Content chunking (Topic, Sentence, Regex, Fixed)
        - Structured extraction (CSS, XPath, LLM, Regex)
        - Caching (memory, disk, Redis)
        - Concurrent page processing
        - Session persistence

    Example:
        >>> engine = CrawlEngine.from_settings(Settings())
        >>> await engine.startup()
        >>> result = await engine.scrape("https://example.com")
        >>> print(result.markdown)
        >>> await engine.shutdown()
    """

    def __init__(
        self,
        browser_config: BrowserConfig | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._browser_config = browser_config
        self._settings = settings or Settings()
        self._browser_manager: BrowserManager | None = None
        self._cache_manager: Any = None
        self._is_started = False
        self._stats = EngineStats()

    @classmethod
    def from_settings(cls, settings: Settings) -> CrawlEngine:
        """Create engine from settings."""
        return cls(settings=settings)

    @classmethod
    def from_browser_config(cls, config: BrowserConfig) -> CrawlEngine:
        """Create engine from browser config."""
        return cls(browser_config=config)

    @classmethod
    def default(cls) -> CrawlEngine:
        """Create engine with default settings."""
        return cls()

    # ═══════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════

    async def startup(self) -> None:
        """Start the engine (initialize browser, cache, etc.)."""
        if self._is_started:
            return

        # Initialize browser
        self._browser_manager = BrowserManager(
            config=self._browser_config,
        )
        await self._browser_manager.start()

        # Initialize cache
        if self._settings.cache_backend != "none":
            from agentcrawl.cache.manager import CacheManager
            self._cache_manager = CacheManager(
                backend=self._settings.cache_backend,
                ttl=self._settings.cache_ttl,
            )
            await self._cache_manager.start()

        self._is_started = True
        logger.info("CrawlEngine started")

    async def shutdown(self) -> None:
        """Shutdown the engine."""
        if not self._is_started:
            return

        if self._browser_manager:
            await self._browser_manager.stop()
            self._browser_manager = None

        if self._cache_manager:
            await self._cache_manager.stop()
            self._cache_manager = None

        self._is_started = False
        logger.info("CrawlEngine shutdown")

    async def __aenter__(self) -> CrawlEngine:
        await self.startup()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.shutdown()

    @property
    def is_started(self) -> bool:
        return self._is_started

    @property
    def stats(self) -> EngineStats:
        return self._stats

    def _ensure_started(self) -> None:
        if not self._is_started:
            raise RuntimeError("Engine not started. Call startup() first.")

    # ═══════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════

    async def scrape(
        self,
        url: str,
        config: CrawlerConfig | None = None,
    ) -> CrawlResult:
        """
        Scrape a single page.

        Args:
            url: URL to scrape.
            config: Per-request configuration.

        Returns:
            CrawlResult with scraped content.
        """
        self._ensure_started()
        config = config or CrawlerConfig()
        return await self._scrape_page(url, config)

    async def _scrape_page(
        self,
        url: str,
        config: CrawlerConfig,
    ) -> CrawlResult:
        """Internal scrape implementation with caching."""
        # Check cache
        if config.cache and self._cache_manager:
            cache_key = self._build_cache_key(url, config)
            cached = await self._cache_manager.get(cache_key)
            if cached:
                # Handle both dict and CrawlResult objects
                if hasattr(cached, 'cached'):
                    cached.cached = True
                    self._stats.record_scrape(cached)
                    return cached
                elif isinstance(cached, dict):
                    cached["cached"] = True
                    # Convert dict back to CrawlResult
                    cached_obj = CrawlResult(**cached)
                    cached_obj.cached = True
                    self._stats.record_scrape(cached_obj)
                    return cached_obj

        # Scrape
        start_time = time.perf_counter()
        result = await self._fetch_and_process(url, config)
        result.response_time_ms = (time.perf_counter() - start_time) * 1000
        result.request_id = str(uuid.uuid4())[:12]

        # Cache result
        if config.cache and self._cache_manager and result.success:
            cache_key = self._build_cache_key(url, config)
            # Convert to dict for proper JSON serialization
            await self._cache_manager.set(cache_key, result.to_dict(), ttl=config.cache_ttl)

        self._stats.record_scrape(result)
        return result

    def _build_cache_key(self, url: str, config: CrawlerConfig) -> str:
        # Build cache key
                key_parts = [
                    url,
                    config.output_format if isinstance(config.output_format, str) else config.output_format.value,
                    str(config.include_links),
                    str(config.only_main_content),
                    config.content_filter or "",
                    config.chunker or "",
                ]
                return hashlib.sha256("|".join(key_parts).encode()).hexdigest()[:32]

    async def _fetch_and_process(
        self,
        url: str,
        config: CrawlerConfig,
    ) -> CrawlResult:
        """
        Fetch page and process through pipeline.

        Pipeline:
            1. Fetch HTML via browser
            2. Parse HTML
            3. Convert to Markdown/JSON
            4. Content filtering (if enabled)
            5. Chunking (if enabled)
            6. Citations extraction
        """
        from agentcrawl.core.pipeline import Pipeline, PipelineContext

        result = CrawlResult(url=url)

        if not self._browser_manager:
            result.error = "Browser not initialized"
            return result

        # Create pipeline with browser manager and cache manager
        pipeline = Pipeline.scrape_pipeline(
            browser_manager=self._browser_manager,
            cache_manager=self._cache_manager if config.cache else None,
        )

        # Execute pipeline
        ctx = PipelineContext(url=url, config=config)
        await pipeline.execute(ctx)

        # Copy pipeline results to CrawlResult
        result.markdown = ctx.markdown
        result.html = ctx.html
        result.text = ctx.text
        result.raw_html = ctx.raw_html
        result.status_code = ctx.status_code
        result.metadata = ctx.metadata
        result.links = ctx.links
        result.chunks = ctx.chunks
        result.citations = ctx.citations
        result.extracted_data = ctx.extracted_data
        result.screenshot = ctx.screenshot
        result.success = ctx.status_code == 200 and ctx.error is None
        result.error = ctx.error
        result.word_count = ctx.word_count
        result.token_count = ctx.token_count

        return result

    async def batch_scrape(
        self,
        urls: list[str],
        config: CrawlerConfig | None = None,
        max_concurrent: int = 5,
    ) -> list[CrawlResult]:
        """
        Scrape multiple URLs concurrently.

        Args:
            urls: List of URLs to scrape.
            config: Per-request configuration.
            max_concurrent: Maximum concurrent scrapes.

        Returns:
            List of CrawlResult in same order as input.
        """
        self._ensure_started()
        config = config or CrawlerConfig()

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _scrape_with_sem(url: str) -> CrawlResult:
            async with semaphore:
                return await self.scrape(url, config)

        results = await asyncio.gather(
            *[_scrape_with_sem(url) for url in urls],
            return_exceptions=True,
        )

        # Convert exceptions to failed results
        processed: list[CrawlResult] = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                processed.append(CrawlResult(
                    url=url,
                    success=False,
                    error=str(result),
                ))
            else:
                processed.append(result)

        return processed

    async def crawl(
        self,
        url: str,
        strategy: Any = None,
        config: CrawlerConfig | None = None,
    ) -> CrawlJobResult:
        """
        Crawl a website starting from a URL.

        Args:
            url: Starting URL.
            strategy: Crawling strategy (BFSCrawler, DFSCrawler, etc.).
            config: Per-request configuration.

        Returns:
            CrawlJobResult with all scraped pages.
        """
        self._ensure_started()
        config = config or CrawlerConfig()
        start_time = time.perf_counter()

        job = CrawlJobResult(
            start_url=url,
            strategy=type(strategy).__name__ if strategy else "bfs",
        )

        try:
            # Get URLs to crawl
            if strategy is not None:
                urls = await strategy.discover(url, self)
            else:
                # Default: simple BFS
                from agentcrawl.crawling.bfs import BFSCrawler
                default_strategy = BFSCrawler(max_depth=2, max_pages=20)
                urls = await default_strategy.discover(url, self)

            # Scrape each URL
            for page_url in urls:
                try:
                    result = await self.scrape(page_url, config)
                    job.add_page(result)
                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", page_url, e)
                    job.add_page(CrawlResult(
                        url=page_url,
                        success=False,
                        error=str(e),
                    ))

            job.status = "completed"

        except Exception as e:
            logger.error("Crawl failed: %s", e)
            job.status = "failed"

        job.duration_ms = (time.perf_counter() - start_time) * 1000
        self._stats.total_crawls += 1
        return job

    async def search(
        self,
        query: str,
        max_results: int = 5,
        scrape: bool = True,
        config: CrawlerConfig | None = None,
        **kwargs: Any,
    ) -> list[CrawlResult]:
        """
        Search the web and optionally scrape results.

        Args:
            query: Search query.
            max_results: Maximum results to return.
            scrape: Whether to scrape result pages.
            config: Per-request configuration.

        Returns:
            List of CrawlResult for search results.
        """
        self._ensure_started()
        config = config or CrawlerConfig()

        try:
            from agentcrawl.search.engine import SearchEngine

            engine = SearchEngine()
            search_results = await engine.search(query, max_results=max_results)

            if not scrape:
                # Return basic results
                results = []
                for sr in search_results:
                    results.append(CrawlResult(
                        url=sr.get("url", ""),
                        markdown=sr.get("snippet", ""),
                        metadata={"title": sr.get("title", "")},
                        success=True,
                    ))
                self._stats.total_searches += 1
                return results

            # Scrape each result
            urls = [sr.get("url", "") for sr in search_results if sr.get("url")]
            return await self.batch_scrape(urls, config)

        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    async def extract(
        self,
        url: str,
        schema: dict[str, Any] | Any,
        config: CrawlerConfig | None = None,
    ) -> CrawlResult:
        """
        Extract structured data from a page.

        Args:
            url: URL to extract from.
            schema: Extraction schema (CSS, XPath, LLM, etc.).
            config: Per-request configuration.

        Returns:
            CrawlResult with extracted_data populated.
        """
        self._ensure_started()
        config = config or CrawlerConfig()

        result = await self.scrape(url, config)
        if result.success:
            # Apply extraction
            from agentcrawl.extraction.base import create_extractor

            # Support both strategy instance and method name string
            if config.extraction is not None:
                if isinstance(config.extraction, str):
                    method = config.extraction
                else:
                    # It's an ExtractionStrategy instance
                    from agentcrawl.extraction.base import ExtractionStrategy
                    if isinstance(config.extraction, ExtractionStrategy):
                        extractor = config.extraction
                        result.extracted_data = await extractor.extract(
                            html=result.html,
                            markdown=result.markdown,
                        )
                        return result
                    method = "llm"  # default
            else:
                method = "llm"  # default

            extractor = create_extractor(method, schema=schema)
            result.extracted_data = await extractor.extract(
                html=result.html,
                markdown=result.markdown,
            )
        return result

    async def map_site(
        self,
        url: str,
        max_pages: int = 100,
        config: CrawlerConfig | None = None,
    ) -> list[str]:
        """
        Map all URLs on a website.

        Args:
            url: Starting URL.
            max_pages: Maximum pages to discover.
            config: Per-request configuration.

        Returns:
            List of discovered URLs.
        """
        self._ensure_started()
        from agentcrawl.crawling.bfs import BFSCrawler

        crawler = BFSCrawler(max_depth=3, max_pages=max_pages)
        return await crawler.discover(url, self)


if __name__ == "__main__":
    import asyncio

    async def main():
        async with CrawlEngine.from_settings(Settings()) as engine:
            result = await engine.scrape("https://example.com")
            print(f"Success: {result.success}")
            print(f"Markdown length: {len(result.markdown)}")

    asyncio.run(main())
