"""
AgentCrawl — Web Crawling & Scraping Framework for AI Agents
===============================================================

A production-ready, async-first web crawling and scraping framework
built for AI agents and LLM applications. Converts any website into
clean, LLM-ready Markdown or structured JSON.

Core Features:
    - 🌐 Browser Automation — Playwright with stealth, proxies, fingerprinting
    - 📄 Content Processing — HTML → Markdown, filtering, chunking
    - 🔍 Deep Crawling — BFS, DFS, BestFirst, Adaptive strategies
    - 🤖 AI Extraction — LLM-powered structured data extraction
    - 🔎 Web Search — Multi-provider search integration
    - ⚡ Caching — Memory, Redis, and disk backends
    - 🪝 Hooks — Extensible pipeline event system
    - 🖥️ Dual Mode — Python package + REST API server

Quick Start:
    from agentcrawl import CrawlEngine, CrawlerConfig

    async with CrawlEngine.default() as engine:
        result = await engine.scrape(
            "https://example.com",
            config=CrawlerConfig(output_format="markdown"),
        )
        print(result.markdown)

    # Deep crawl
    from agentcrawl import BFSCrawler
    crawler = BFSCrawler(max_depth=3, max_pages=50)
    urls = await crawler.discover("https://docs.example.com", engine)

    # Structured extraction
    from agentcrawl import LLMExtractor
    from pydantic import BaseModel

    class Product(BaseModel):
        name: str
        price: float

    extractor = LLMExtractor(schema=Product)
    result = await extractor.extract(markdown=content)

    # Web search
    from agentcrawl import SearchEngine
    engine = SearchEngine(provider="duckduckgo")
    results = await engine.search("python tutorial")

Links:
    GitHub:     https://github.com/agentcrawl/agentcrawl
    Docs:       https://docs.agentcrawl.dev
    PyPI:       https://pypi.org/project/agentcrawl/
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "AgentCrawl Team"
__license__ = "Apache-2.0"


# ══════════════════════════════════════════════════════════════
# Top-Level Imports (lightweight, always available)
# ══════════════════════════════════════════════════════════════

from agentcrawl.config.crawler_config import CrawlerConfig
from agentcrawl.config.settings import Settings
from agentcrawl.core.engine import CrawlEngine, CrawlJobResult, CrawlResult

# Alias for CrawlEngine
Crawler = CrawlEngine

# ══════════════════════════════════════════════════════════════
# Lazy Imports (heavy modules loaded on first access)
# ══════════════════════════════════════════════════════════════

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Config
    "BrowserConfig": ("agentcrawl.config.browser_config", "BrowserConfig"),
    "LLMConfig": ("agentcrawl.config.llm_config", "LLMConfig"),
    "CacheConfig": ("agentcrawl.config.cache_config", "CacheConfig"),
    "QueueConfig": ("agentcrawl.config.queue_config", "QueueConfig"),
    "ProxyConfig": ("agentcrawl.config.proxy_config", "ProxyConfig"),
    # Core
    "Pipeline": ("agentcrawl.core.pipeline", "Pipeline"),
    "PipelineContext": ("agentcrawl.core.pipeline", "PipelineContext"),
    "CrawlSession": ("agentcrawl.core.session", "CrawlSession"),
    # Browser
    "BrowserManager": ("agentcrawl.browser.manager", "BrowserManager"),
    # Content
    "HTMLParser": ("agentcrawl.content.html_parser", "HTMLParser"),
    "HTMLToMarkdown": ("agentcrawl.content.html_to_markdown", "HTMLToMarkdown"),
    "html_to_markdown": ("agentcrawl.content.html_to_markdown", "html_to_markdown"),
    "TopicChunker": ("agentcrawl.content.chunker", "TopicChunker"),
    "SentenceChunker": ("agentcrawl.content.chunker", "SentenceChunker"),
    "PruningContentFilter": ("agentcrawl.content.content_filter", "PruningContentFilter"),
    "BM25ContentFilter": ("agentcrawl.content.bm25_filter", "BM25ContentFilter"),
    "CitationExtractor": ("agentcrawl.content.citation", "CitationExtractor"),
    # Extraction
    "LLMExtractor": ("agentcrawl.extraction.llm", "LLMExtractor"),
    "JsonCssExtractor": ("agentcrawl.extraction.json_css", "JsonCssExtractor"),
    "JsonXPathExtractor": ("agentcrawl.extraction.json_xpath", "JsonXPathExtractor"),
    "CosineExtractor": ("agentcrawl.extraction.cosine", "CosineExtractor"),
    "RegexExtractor": ("agentcrawl.extraction.regex", "RegexExtractor"),
    "FitMarkdownExtractor": ("agentcrawl.extraction.fit_markdown", "FitMarkdownExtractor"),
    "TableExtractor": ("agentcrawl.extraction.table", "TableExtractor"),
    "SchemaBuilder": ("agentcrawl.extraction.schema", "SchemaBuilder"),
    "create_extractor": ("agentcrawl.extraction.base", "create_extractor"),
    # Crawling
    "BFSCrawler": ("agentcrawl.crawling.bfs", "BFSCrawler"),
    "DFSCrawler": ("agentcrawl.crawling.dfs", "DFSCrawler"),
    "BestFirstCrawler": ("agentcrawl.crawling.best_first", "BestFirstCrawler"),
    "AdaptiveCrawler": ("agentcrawl.crawling.adaptive", "AdaptiveCrawler"),
    "SinglePageCrawler": ("agentcrawl.crawling.single", "SinglePageCrawler"),
    "DomainMapper": ("agentcrawl.crawling.domain_mapper", "DomainMapper"),
    "SitemapParser": ("agentcrawl.crawling.sitemap_parser", "SitemapParser"),
    "URLFilter": ("agentcrawl.crawling.base", "URLFilter"),
    "URLScorer": ("agentcrawl.crawling.base", "URLScorer"),
    # Search
    "SearchEngine": ("agentcrawl.search.engine", "SearchEngine"),
    # Cache
    "CacheManager": ("agentcrawl.cache.manager", "CacheManager"),
    # Hooks
    "HookExecutor": ("agentcrawl.hooks.executor", "HookExecutor"),
    "HookRegistry": ("agentcrawl.hooks.registry", "HookRegistry"),
    "HookEvent": ("agentcrawl.hooks.executor", "HookEvent"),
    "hook": ("agentcrawl.hooks.registry", "hook"),
    # Output
    "JsonOutputFormatter": ("agentcrawl.output.json", "JsonOutputFormatter"),
    "MarkdownOutputFormatter": ("agentcrawl.output.markdown", "MarkdownOutputFormatter"),
    "HtmlOutputFormatter": ("agentcrawl.output.html", "HtmlOutputFormatter"),
    "ScreenshotHandler": ("agentcrawl.output.screenshot", "ScreenshotHandler"),
}


def __getattr__(name: str) -> object:
    """Lazy import for submodules and classes."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)

    raise AttributeError(f"module 'agentcrawl' has no attribute {name!r}")


def __dir__() -> list[str]:
    """List all available attributes."""
    return sorted(
        list(globals().keys())
        + list(_LAZY_IMPORTS.keys())
    )


# ══════════════════════════════════════════════════════════════
# Convenience Functions
# ══════════════════════════════════════════════════════════════

async def scrape(
    url: str,
    config: CrawlerConfig | None = None,
    settings: Settings | None = None,
) -> CrawlResult:
    """
    Scrape a single page (convenience function).

    Creates a temporary engine, scrapes the URL, and shuts down.
    For repeated scraping, use CrawlEngine directly.

    Args:
        url: URL to scrape.
        config: Per-request configuration.
        settings: Global settings.

    Returns:
        CrawlResult.

    Example:
        >>> import agentcrawl
        >>> result = await agentcrawl.scrape("https://example.com")
        >>> print(result.markdown)
    """
    engine = CrawlEngine.from_settings(settings or Settings())
    async with engine:
        return await engine.scrape(url, config)


async def crawl(
    url: str,
    strategy: object | None = None,
    config: CrawlerConfig | None = None,
    settings: Settings | None = None,
) -> CrawlJobResult:
    """
    Crawl a website (convenience function).

    Args:
        url: Starting URL.
        strategy: Crawling strategy (BFSCrawler, DFSCrawler, etc.).
        config: Per-request configuration.
        settings: Global settings.

    Returns:
        CrawlJobResult.

    Example:
        >>> import agentcrawl
        >>> from agentcrawl import BFSCrawler
        >>> result = await agentcrawl.crawl(
        ...     "https://docs.example.com",
        ...     strategy=BFSCrawler(max_depth=2),
        ... )
    """
    engine = CrawlEngine.from_settings(settings or Settings())
    async with engine:
        return await engine.crawl(url, strategy=strategy, config=config)


async def search(
    query: str,
    max_results: int = 5,
    provider: str = "duckduckgo",
    api_key: str = "",
    scrape_results: bool = False,
) -> list[dict[str, object]]:
    """
    Search the web (convenience function).

    Args:
        query: Search query.
        max_results: Maximum results.
        provider: Search provider name.
        api_key: Provider API key (if required).
        scrape_results: Whether to scrape each result page.

    Returns:
        List of search result dictionaries.

    Example:
        >>> import agentcrawl
        >>> results = await agentcrawl.search("python tutorial")
    """
    from agentcrawl.search.engine import SearchEngine

    engine = SearchEngine(provider=provider, api_key=api_key)
    return await engine.search(query, max_results=max_results)


async def map_site(
    url: str,
    max_urls: int = 500,
) -> list[str]:
    """
    Discover all URLs on a website (convenience function).

    Args:
        url: Website URL.
        max_urls: Maximum URLs to discover.

    Returns:
        List of discovered URLs.

    Example:
        >>> import agentcrawl
        >>> urls = await agentcrawl.map_site("https://example.com")
    """
    from agentcrawl.crawling.domain_mapper import DomainMapper

    mapper = DomainMapper(max_urls=max_urls)
    return await mapper.discover(url)


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

__all__ = [
    "AdaptiveCrawler",
    # Crawling
    "BFSCrawler",
    "BM25ContentFilter",
    "BestFirstCrawler",
    # Lazy imports (available on access)
    # Config
    "BrowserConfig",
    # Browser
    "BrowserManager",
    "CacheConfig",
    # Cache
    "CacheManager",
    "CitationExtractor",
    "CosineExtractor",
    # Core (always imported)
    "CrawlEngine",
    "CrawlJobResult",
    "CrawlResult",
    "CrawlSession",
    "Crawler",
    "CrawlerConfig",
    "DFSCrawler",
    "DomainMapper",
    "FitMarkdownExtractor",
    # Content
    "HTMLParser",
    "HTMLToMarkdown",
    "HookEvent",
    # Hooks
    "HookExecutor",
    "HookRegistry",
    "HtmlOutputFormatter",
    "JsonCssExtractor",
    # Output
    "JsonOutputFormatter",
    "JsonXPathExtractor",
    "LLMConfig",
    # Extraction
    "LLMExtractor",
    "MarkdownOutputFormatter",
    # Core
    "Pipeline",
    "PipelineContext",
    "ProxyConfig",
    "PruningContentFilter",
    "QueueConfig",
    "RegexExtractor",
    "SchemaBuilder",
    "ScreenshotHandler",
    # Search
    "SearchEngine",
    "SentenceChunker",
    "Settings",
    "SinglePageCrawler",
    "SitemapParser",
    "TableExtractor",
    "TopicChunker",
    "URLFilter",
    "URLScorer",
    # Version
    "__version__",
    "crawl",
    "create_extractor",
    "hook",
    "html_to_markdown",
    "map_site",
    # Convenience functions
    "scrape",
    "search",
]
