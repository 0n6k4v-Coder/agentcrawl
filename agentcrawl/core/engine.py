"""
AgentCrawl — Core Crawl Engine
=================================

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
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.browser.config import BrowserConfig
from agentcrawl.browser.manager import BrowserManager
from agentcrawl.config.crawler_config import CrawlerConfig, OutputFormat
from agentcrawl.config.settings import Settings

logger = logging.getLogger("agentcrawl.core.engine")


# ══════════════════════════════════════════════════════════════
# Result Models
# ══════════════════════════════════════════════════════════════

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
        links: Extracted links (internal, external).
        citations: Extracted citations.
        chunks: Content chunks (if chunking enabled).
        extracted_data: Structured extraction result.
        screenshot: Base64 screenshot (if enabled).
        error: Error message (if failed).
        response_time_ms: Total response time in milliseconds.
        word_count: Word count of extracted content.
        token_count: Estimated token count.
        cached: Whether the result came from cache.
        request_id: Unique request identifier.
    """
    url: str = ""
    success: bool = True
    status_code: int = 200
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
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return (
            f"CrawlResult({status} {self.url}, "
            f"words={self.word_count}, "
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
        self.total_pages = len(self.pages)
        self.successful_pages = sum(1 for p in self.pages if p.success)
        self.failed_pages = self.total_pages - self.successful_pages
        self.total_words = sum(p.word_count for p in self.pages)
        self.total_tokens = sum(p.token_count for p in self.pages)

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


# ══════════════════════════════════════════════════════════════
# Engine Statistics
# ══════════════════════════════════════════════════════════════

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
            "cache_hit_rate": round(
                self.total_cache_hits / max(self.total_cache_hits + self.total_cache_misses, 1), 3
            ),
            "total_words_extracted": self.total_words_extracted,
            "total_tokens_extracted": self.total_tokens_extracted,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
        }


# ══════════════════════════════════════════════════════════════
# Crawl Engine
# ══════════════════════════════════════════════════════════════

class CrawlEngine:
    """
    Core crawl engine that orchestrates all layers.

    Coordinates browser automation, content processing, extraction,
    filtering, chunking, and caching into a unified pipeline.

    Args:
        browser_config: Browser automation configuration.
        settings: Global settings (for cache, LLM, etc.).

    Example:
        >>> engine = CrawlEngine.from_settings(Settings())
        >>> async with engine:
        ...     result = await engine.scrape("https://example.com")
        ...     print(result.markdown)
    """

    def __init__(
        self,
        browser_config: BrowserConfig | None = None,
        settings: Settings | None = None,
    ):
        self._settings = settings or Settings()
        self._browser_config = browser_config or self._settings.to_browser_config()

        # Components (initialized on startup)
        self._browser_manager: BrowserManager | None = None
        self._cache_manager: Any = None  # CacheManager
        self._html_converter: Any = None  # HTMLToMarkdown
        self._citation_extractor: Any = None  # CitationExtractor

        # State
        self._started = False
        self._starting = False
        self._lock = asyncio.Lock()

        # Stats
        self._stats = EngineStats()

    # ──────────────────────────────────────────────────────────
    # Factory Methods
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_settings(cls, settings: Settings) -> CrawlEngine:
        """
        Create an engine from global settings.

        Args:
            settings: Global Settings instance.

        Returns:
            CrawlEngine instance.
        """
        browser_config = settings.to_browser_config()
        return cls(browser_config=browser_config, settings=settings)

    @classmethod
    def from_browser_config(cls, config: BrowserConfig) -> CrawlEngine:
        """Create an engine from a browser config only."""
        return cls(browser_config=config)

    @classmethod
    def default(cls) -> CrawlEngine:
        """Create an engine with default settings."""
        return cls()

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def is_started(self) -> bool:
        """Whether the engine has been initialized."""
        return self._started

    @property
    def browser_manager(self) -> BrowserManager:
        """The browser manager instance."""
        if self._browser_manager is None:
            raise RuntimeError("Engine not started. Call startup() first.")
        return self._browser_manager

    @property
    def stats(self) -> EngineStats:
        """Engine statistics."""
        return self._stats

    @property
    def settings(self) -> Settings:
        """Global settings."""
        return self._settings

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """
        Initialize all engine components.

        Launches the browser, initializes cache, and prepares
        content processing tools.
        """
        async with self._lock:
            if self._started or self._starting:
                return

            self._starting = True
            logger.info("Starting CrawlEngine...")

            try:
                # 1. Initialize browser manager
                self._browser_manager = BrowserManager(self._browser_config)
                await self._browser_manager.start()

                # 2. Initialize cache
                await self._init_cache()

                # 3. Initialize content tools
                self._init_content_tools()

                self._started = True
                logger.info("CrawlEngine started successfully")

            except Exception as e:
                logger.error("CrawlEngine startup failed: %s", e)
                await self._cleanup()
                raise
            finally:
                self._starting = False

    async def shutdown(self) -> None:
        """Shut down all engine components and release resources."""
        async with self._lock:
            if not self._started:
                return

            logger.info("Shutting down CrawlEngine...")
            await self._cleanup()
            self._started = False
            logger.info(
                "CrawlEngine stopped. Stats: %s",
                self._stats.to_dict(),
            )

    async def _cleanup(self) -> None:
        """Clean up all components."""
        if self._browser_manager:
            await self._browser_manager.stop()
            self._browser_manager = None

        if self._cache_manager:
            await self._cache_manager.stop()
            self._cache_manager = None

    async def __aenter__(self) -> CrawlEngine:
        await self.startup()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.shutdown()

    # ──────────────────────────────────────────────────────────
    # Component Initialization
    # ──────────────────────────────────────────────────────────

    async def _init_cache(self) -> None:
        """Initialize the cache manager."""
        try:
            from agentcrawl.cache.manager import CacheManager

            cache_config = self._settings.to_cache_config()
            self._cache_manager = CacheManager(config=cache_config)
            await self._cache_manager.start()
            logger.info("Cache initialized (backend=%s)", self._settings.cache_backend)
        except Exception as e:
            logger.warning("Cache initialization failed: %s", e)
            self._cache_manager = None

    def _init_content_tools(self) -> None:
        """Initialize content processing tools."""
        from agentcrawl.content.html_to_markdown import HTMLToMarkdown, MarkdownOptions
        from agentcrawl.content.citation import CitationExtractor

        self._html_converter = HTMLToMarkdown(MarkdownOptions(
            include_links=True,
            include_images=False,
            code_block_style="fenced",
        ))
        self._citation_extractor = CitationExtractor(
            deduplicate=True,
            include_context=True,
        )

    # ──────────────────────────────────────────────────────────
    # Core Operations
    # ──────────────────────────────────────────────────────────

    async def scrape(
        self,
        url: str,
        config: CrawlerConfig | None = None,
    ) -> CrawlResult:
        """
        Scrape a single page.

        Pipeline:
            1. Check cache
            2. Fetch page (browser)
            3. Parse HTML
            4. Convert to Markdown/JSON
            5. Apply content filter
            6. Apply chunker
            7. Extract citations
            8. Run extraction strategy
            9. Cache result
            10. Return CrawlResult

        Args:
            url: URL to scrape.
            config: Per-request configuration.

        Returns:
            CrawlResult with extracted content.
        """
        self._ensure_started()
        config = config or CrawlerConfig()
        start_time = time.perf_counter()

        # Check cache
        if config.cache and self._cache_manager:
            cached = await self._get_from_cache(url, config)
            if cached is not None:
                cached.cached = True
                cached.response_time_ms = (time.perf_counter() - start_time) * 1000
                self._stats.record_scrape(cached)
                return cached

        # Fetch page
        result = await self._fetch_and_process(url, config)
        result.response_time_ms = (time.perf_counter() - start_time) * 1000

        # Cache result
        if config.cache and self._cache_manager and result.success:
            await self._put_to_cache(url, config, result)

        self._stats.record_scrape(result)
        return result

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
                    job.pages.append(result)
                except Exception as e:
                    logger.warning("Failed to scrape %s: %s", page_url, e)
                    job.pages.append(CrawlResult(
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
            max_results: Maximum results.
            scrape: Whether to scrape each result page.
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
                # Return search results without scraping
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
            results = []
            for sr in search_results:
                url = sr.get("url", "")
                if url:
                    result = await self.scrape(url, config)
                    result.metadata["search_title"] = sr.get("title", "")
                    result.metadata["search_snippet"] = sr.get("snippet", "")
                    results.append(result)

            self._stats.total_searches += 1
            return results

        except ImportError:
            logger.warning("Search module not available")
            return []
        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    async def map(
        self,
        url: str,
        max_urls: int = 500,
        use_sitemap: bool = True,
        use_robots: bool = True,
        **kwargs: Any,
    ) -> list[str]:
        """
        Discover all URLs on a website.

        Args:
            url: Website URL.
            max_urls: Maximum URLs to discover.
            use_sitemap: Parse sitemap.xml.
            use_robots: Parse robots.txt.

        Returns:
            List of discovered URLs.
        """
        self._ensure_started()

        try:
            from agentcrawl.crawling.domain_mapper import DomainMapper

            mapper = DomainMapper(
                max_urls=max_urls,
                use_sitemap=use_sitemap,
                use_robots=use_robots,
            )
            urls = await mapper.discover(url)
            self._stats.total_maps += 1
            return urls

        except ImportError:
            logger.warning("DomainMapper not available, falling back to link extraction")
            # Fallback: scrape the page and extract links
            result = await self.scrape(url, CrawlerConfig(include_links=True))
            all_links = result.links.get("all", [])
            return [l["url"] for l in all_links[:max_urls]]

        except Exception as e:
            logger.error("Map failed: %s", e)
            return []

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
            List of CrawlResult (same order as input URLs).
        """
        self._ensure_started()
        config = config or CrawlerConfig()
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _scrape_one(url: str) -> CrawlResult:
            async with semaphore:
                try:
                    return await self.scrape(url, config)
                except Exception as e:
                    return CrawlResult(url=url, success=False, error=str(e))

        tasks = [_scrape_one(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def extract(
        self,
        url: str,
        schema: Any = None,
        method: str = "llm",
        config: CrawlerConfig | None = None,
        **kwargs: Any,
    ) -> CrawlResult:
        """
        Extract structured data from a URL.

        Args:
            url: URL to extract from.
            schema: Extraction schema (Pydantic model or JSON schema).
            method: Extraction method ('llm', 'css', 'xpath').
            config: Per-request configuration.

        Returns:
            CrawlResult with extracted_data populated.
        """
        self._ensure_started()
        config = config or CrawlerConfig()

        # Set up extraction strategy
        if method == "css" and schema:
            from agentcrawl.extraction.json_css import JsonCssExtractor
            config.extraction = JsonCssExtractor(schema=schema)
        elif method == "xpath" and schema:
            from agentcrawl.extraction.json_xpath import JsonXPathExtractor
            config.extraction = JsonXPathExtractor(schema=schema)
        elif schema:
            from agentcrawl.extraction.llm import LLMExtractor
            from agentcrawl.config.llm_config import LLMConfig
            config.extraction = LLMExtractor(
                schema=schema,
                llm_config=self._settings.llm,
            )

        return await self.scrape(url, config)

    # ──────────────────────────────────────────────────────────
    # Internal Pipeline
    # ──────────────────────────────────────────────────────────

    async def _fetch_and_process(
        self,
        url: str,
        config: CrawlerConfig,
    ) -> CrawlResult:
        """
        Fetch a page and run the full processing pipeline.

        Args:
            url: URL to fetch.
            config: Request configuration.

        Returns:
            CrawlResult.
        """
        result = CrawlResult(url=url)

        try:
            # 1. Acquire browser page
            page = await self._browser_manager.acquire_page(
                timeout=config.timeout,
            )

            try:
                # 2. Execute page actions (if any)
                if config.actions:
                    from agentcrawl.browser.actions import PageActions
                    actions = PageActions(
                        config.actions if isinstance(config.actions, list) else [],
                    )
                    await actions.execute(page)

                # 3. Wait conditions
                await self._apply_wait(page, config)

                # 4. Navigate to URL
                response = await page.goto(
                    url,
                    timeout=config.navigation_timeout_ms,
                    wait_until="domcontentloaded",
                )

                if response:
                    result.status_code = response.status

                # 5. Wait for content
                await self._wait_for_content(page, config)

                # 6. Get raw HTML
                raw_html = await page.content()
                result.raw_html = raw_html

                # 7. Screenshot (if enabled)
                if config.include_screenshot or config.screenshot.enabled:
                    try:
                        screenshot_bytes = await page.screenshot(
                            full_page=config.screenshot.full_page,
                            type=config.screenshot.format,
                        )
                        import base64
                        result.screenshot = base64.b64encode(screenshot_bytes).decode()
                    except Exception as e:
                        logger.debug("Screenshot failed: %s", e)

            finally:
                await self._browser_manager.release_page(page)

            # 8. Parse HTML
            from agentcrawl.content.html_parser import HTMLParser

            parser = HTMLParser(raw_html, base_url=url)

            # 9. Extract metadata
            if config.include_metadata:
                meta = parser.get_metadata()
                result.metadata = meta.to_dict()

            # 10. Extract links
            if config.include_links:
                links = parser.get_links(base_url=url)
                result.links = {
                    "internal": [l.to_dict() for l in links["internal"]],
                    "external": [l.to_dict() for l in links["external"]],
                    "all": [l.to_dict() for l in links["all"]],
                }

            # 11. Get main content
            main_content = parser.get_main_content(
                include_selectors=config.selectors or None,
                exclude_selectors=config.exclude_selectors or None,
                only_main=config.only_main_content,
            )

            # 12. Convert to output format
            output_format = config.output_format
            if isinstance(output_format, str):
                output_format = OutputFormat(output_format)

            if output_format == OutputFormat.MARKDOWN:
                result.markdown = self._html_converter.convert(main_content.html)
                result.text = main_content.text
            elif output_format == OutputFormat.HTML:
                result.html = main_content.html
                result.markdown = self._html_converter.convert(main_content.html)
                result.text = main_content.text
            elif output_format == OutputFormat.JSON:
                result.json = {
                    "url": url,
                    "content": main_content.text,
                    "metadata": result.metadata,
                    "links": result.links,
                }
                result.markdown = self._html_converter.convert(main_content.html)
            else:
                result.text = main_content.text
                result.markdown = main_content.text

            # 13. Apply content filter
            if config.content_filter and config.content_filter != "none":
                result = self._apply_content_filter(result, config)

            # 14. Apply chunker
            if config.chunker and config.chunker != "none":
                result = self._apply_chunker(result, config)

            # 15. Extract citations
            if config.include_citations and result.markdown:
                citation_result = self._citation_extractor.extract(result.markdown)
                result.citations = [c.to_dict() for c in citation_result.citations]

            # 16. Run extraction strategy
            if config.extraction:
                try:
                    extracted = await config.extraction.extract(
                        html=main_content.html,
                        markdown=result.markdown,
                        url=url,
                    )
                    result.extracted_data = extracted
                except Exception as e:
                    logger.warning("Extraction failed: %s", e)

            result.success = True

        except Exception as e:
            logger.error("Scrape failed for %s: %s", url, e)
            result.success = False
            result.error = str(e)

        return result

    async def _apply_wait(self, page: Any, config: CrawlerConfig) -> None:
        """Apply wait conditions before navigation."""
        wait = config.wait
        if wait.strategy.value == "selector" and wait.selector:
            try:
                await page.wait_for_selector(
                    wait.selector,
                    timeout=wait.timeout_ms,
                )
            except Exception:
                pass
        elif wait.strategy.value == "timeout" and wait.milliseconds > 0:
            await asyncio.sleep(wait.milliseconds / 1000.0)

    async def _wait_for_content(self, page: Any, config: CrawlerConfig) -> None:
        """Wait for page content to be ready."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass

        # Additional wait for JS-rendered content
        if config.wait.strategy.value == "networkidle":
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

    def _apply_content_filter(
        self,
        result: CrawlResult,
        config: CrawlerConfig,
    ) -> CrawlResult:
        """Apply content filter to the result."""
        try:
            from agentcrawl.content.content_filter import create_content_filter_from_config

            content_filter = create_content_filter_from_config(config)
            if content_filter and result.markdown:
                filter_result = content_filter.apply(result.markdown)
                result.markdown = filter_result.filtered_text
                result.text = filter_result.filtered_text
        except Exception as e:
            logger.debug("Content filter failed: %s", e)

        return result

    def _apply_chunker(
        self,
        result: CrawlResult,
        config: CrawlerConfig,
    ) -> CrawlResult:
        """Apply chunker to the result."""
        try:
            from agentcrawl.content.chunker import create_chunker_from_config

            chunker = create_chunker_from_config(config)
            if chunker and result.markdown:
                chunk_result = chunker.chunk(
                    result.markdown,
                    metadata={"url": result.url},
                )
                result.chunks = [c.to_dict() for c in chunk_result.chunks]
        except Exception as e:
            logger.debug("Chunker failed: %s", e)

        return result

    # ──────────────────────────────────────────────────────────
    # Cache Operations
    # ──────────────────────────────────────────────────────────

    async def _get_from_cache(
        self,
        url: str,
        config: CrawlerConfig,
    ) -> CrawlResult | None:
        """Try to get a cached result."""
        if not self._cache_manager:
            return None

        try:
            cache_key = self._cache_manager.key_generator.from_url(
                url,
                output_format=str(config.output_format),
                extra={"suffix": config.cache_key_suffix()},
            )
            cached_data = await self._cache_manager.get(cache_key)
            if cached_data:
                return CrawlResult(**cached_data)
        except Exception as e:
            logger.debug("Cache get failed: %s", e)

        return None

    async def _put_to_cache(
        self,
        url: str,
        config: CrawlerConfig,
        result: CrawlResult,
    ) -> None:
        """Store a result in cache."""
        if not self._cache_manager:
            return

        try:
            cache_key = self._cache_manager.key_generator.from_url(
                url,
                output_format=str(config.output_format),
                extra={"suffix": config.cache_key_suffix()},
            )
            ttl = config.cache_ttl or self._settings.cache_ttl
            await self._cache_manager.set(
                cache_key,
                result.to_dict(),
                ttl=ttl,
            )
        except Exception as e:
            logger.debug("Cache set failed: %s", e)

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get full engine diagnostics."""
        diag: dict[str, Any] = {
            "started": self._started,
            "stats": self._stats.to_dict(),
            "browser": (
                self._browser_manager.get_diagnostics()
                if self._browser_manager
                else None
            ),
            "cache": (
                self._cache_manager.get_stats()
                if self._cache_manager
                else None
            ),
            "settings": {
                "cache_backend": self._settings.cache_backend,
                "queue_backend": self._settings.queue_backend,
                "browser_type": str(self._browser_config.browser_type),
                "headless": self._browser_config.headless,
                "stealth": self._browser_config.stealth,
            },
        }
        return diag

    def _ensure_started(self) -> None:
        """Raise if the engine hasn't been started."""
        if not self._started:
            raise RuntimeError(
                "CrawlEngine not started. Call startup() or use 'async with' first."
            )

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"CrawlEngine(browser={self._browser_config.browser_type}, "
            f"status={status}, "
            f"scrapes={self._stats.total_scrapes})"
        )