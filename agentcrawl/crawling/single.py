"""
AgentCrawl — Single Page Crawler
====================================

A minimal crawler that fetches and processes exactly one page
without following any links. Used as the default strategy for
simple scrape operations and as a building block for more
complex crawlers.

This is the simplest crawl strategy — it fetches a single URL,
extracts content, and returns. No link following, no recursion,
no queue management.

Use cases:
    - Simple single-page scraping
    - Default strategy when no crawl strategy is specified
    - Building block for custom crawlers
    - Testing and debugging
    - API endpoint: POST /scrape

Usage:
    from agentcrawl.crawling.single import SinglePageCrawler

    crawler = SinglePageCrawler()

    # Discover (returns just the start URL)
    urls = await crawler.discover("https://example.com", engine)
    # → ["https://example.com"]

    # Crawl (scrapes the single page)
    results = await crawler.crawl("https://example.com", engine)
    # → [CrawlResult(...)]

    # With page actions
    crawler = SinglePageCrawler(
        actions=[
            {"type": "click", "selector": "#accept-cookies"},
            {"type": "scroll", "direction": "down", "amount": 3},
            {"type": "wait", "milliseconds": 1000},
        ],
    )
    results = await crawler.crawl("https://example.com", engine)

    # With wait condition
    crawler = SinglePageCrawler(
        wait_for_selector="#content-loaded",
        wait_timeout=10000,
    )
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agentcrawl.crawling.base import (
    CrawlConfig,
    CrawlStrategy,
    DiscoveredURL,
    URLFilter,
    URLScorer,
)

logger = logging.getLogger("agentcrawl.crawling.single")


# ══════════════════════════════════════════════════════════════
# Single Page Crawler
# ══════════════════════════════════════════════════════════════

class SinglePageCrawler(CrawlStrategy):
    """
    Single-page crawler that fetches exactly one URL.

    Does not follow links or recurse. Simply fetches the target
    URL, extracts content, and returns.

    Args:
        actions: Page actions to execute before extraction.
        wait_for_selector: CSS selector to wait for before extraction.
        wait_timeout: Timeout for wait_for_selector in milliseconds.
        wait_for_load_state: Load state to wait for ('load',
                            'domcontentloaded', 'networkidle').
        wait_milliseconds: Fixed wait time in milliseconds.
        include_links: Whether to extract links (without following).
        include_screenshot: Whether to capture a screenshot.
        url_filter: URL filter instance.
        url_scorer: URL scorer instance.
        config: Crawl configuration.

    Example:
        >>> crawler = SinglePageCrawler(
        ...     actions=[{"type": "click", "selector": "#btn"}],
        ...     wait_for_selector="#content",
        ... )
        >>> results = await crawler.crawl("https://example.com", engine)
        >>> print(results[0].markdown)
    """

    strategy_name = "single"

    def __init__(
        self,
        actions: list[dict[str, Any]] | None = None,
        wait_for_selector: str | None = None,
        wait_timeout: int = 30_000,
        wait_for_load_state: str = "domcontentloaded",
        wait_milliseconds: int = 0,
        include_links: bool = True,
        include_screenshot: bool = False,
        url_filter: URLFilter | None = None,
        url_scorer: URLScorer | None = None,
        config: CrawlConfig | None = None,
    ):
        # Single page: max_depth=0, max_pages=1
        super().__init__(
            max_depth=0,
            max_pages=1,
            url_filter=url_filter,
            url_scorer=url_scorer,
            config=config or CrawlConfig(max_depth=0, max_pages=1),
        )

        self._actions = actions or []
        self._wait_for_selector = wait_for_selector
        self._wait_timeout = wait_timeout
        self._wait_for_load_state = wait_for_load_state
        self._wait_milliseconds = wait_milliseconds
        self._include_links = include_links
        self._include_screenshot = include_screenshot

        # Timing
        self._fetch_time_ms: float = 0.0
        self._action_time_ms: float = 0.0
        self._wait_time_ms: float = 0.0

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def actions(self) -> list[dict[str, Any]]:
        """Configured page actions."""
        return list(self._actions)

    @property
    def fetch_time_ms(self) -> float:
        """Time taken to fetch the page."""
        return self._fetch_time_ms

    @property
    def action_time_ms(self) -> float:
        """Time taken to execute page actions."""
        return self._action_time_ms

    @property
    def wait_time_ms(self) -> float:
        """Time spent waiting."""
        return self._wait_time_ms

    # ──────────────────────────────────────────────────────────
    # Core Discovery
    # ──────────────────────────────────────────────────────────

    async def _discover_urls(
        self,
        url: str,
        engine: Any,
    ) -> list[DiscoveredURL]:
        """
        Single-page discovery — returns just the start URL.

        Args:
            url: The URL to scrape.
            engine: CrawlEngine instance.

        Returns:
            List containing a single DiscoveredURL.
        """
        score = self._scorer.score(url, depth=0)

        discovered = DiscoveredURL(
            url=url,
            depth=0,
            source_url="",
            link_text="",
            score=score,
        )

        self._discovered[url] = discovered
        return [discovered]

    # ──────────────────────────────────────────────────────────
    # Override Crawl for Single Page
    # ──────────────────────────────────────────────────────────

    async def crawl(
        self,
        url: str,
        engine: Any,
        config: Any = None,
    ) -> list[Any]:
        """
        Scrape a single page with full processing.

        Overrides the base crawl to provide single-page-specific
        behavior with actions, waits, and screenshots.

        Args:
            url: URL to scrape.
            engine: CrawlEngine instance.
            config: CrawlerConfig override.

        Returns:
            List containing a single CrawlResult.
        """
        self._reset()
        self._start_time = time.time()

        from agentcrawl.config.crawler_config import CrawlerConfig

        # Build config with single-page settings
        if config is None:
            config = CrawlerConfig()

        # Apply single-page overrides
        if self._actions:
            config.actions = self._actions

        if self._wait_for_selector:
            from agentcrawl.config.crawler_config import WaitOptions, WaitStrategy
            config.wait = WaitOptions(
                strategy=WaitStrategy.SELECTOR,
                selector=self._wait_for_selector,
                timeout_ms=self._wait_timeout,
            )

        if self._wait_milliseconds > 0:
            from agentcrawl.config.crawler_config import WaitOptions, WaitStrategy
            config.wait = WaitOptions(
                strategy=WaitStrategy.TIMEOUT,
                milliseconds=self._wait_milliseconds,
            )

        if self._include_screenshot:
            config.include_screenshot = True

        config.include_links = self._include_links

        # Scrape
        start = time.perf_counter()
        try:
            result = await engine.scrape(url, config)
            self._fetch_time_ms = (time.perf_counter() - start) * 1000

            self._visited.add(url)
            self._progress.pages_crawled = 1
            self._progress.is_complete = True
            self._progress.elapsed_ms = (time.time() - self._start_time) * 1000

            return [result]

        except Exception as e:
            self._fetch_time_ms = (time.perf_counter() - start) * 1000
            self._progress.pages_failed = 1
            self._progress.is_complete = True
            self._progress.elapsed_ms = (time.time() - self._start_time) * 1000

            from agentcrawl.core.engine import CrawlResult
            return [CrawlResult(
                url=url,
                success=False,
                error=str(e),
                response_time_ms=self._fetch_time_ms,
            )]

    # ──────────────────────────────────────────────────────────
    # Convenience Methods
    # ──────────────────────────────────────────────────────────

    async def scrape(
        self,
        url: str,
        engine: Any,
        config: Any = None,
    ) -> Any:
        """
        Scrape a single page and return the result directly.

        Convenience method that returns a single CrawlResult
        instead of a list.

        Args:
            url: URL to scrape.
            engine: CrawlEngine instance.
            config: CrawlerConfig override.

        Returns:
            CrawlResult.
        """
        results = await self.crawl(url, engine, config)
        return results[0] if results else None

    # ──────────────────────────────────────────────────────────
    # Reset
    # ──────────────────────────────────────────────────────────

    def _reset(self) -> None:
        """Reset crawler state."""
        super()._reset()
        self._fetch_time_ms = 0.0
        self._action_time_ms = 0.0
        self._wait_time_ms = 0.0

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics."""
        base = super().get_diagnostics()

        base.update({
            "fetch_time_ms": round(self._fetch_time_ms, 2),
            "action_time_ms": round(self._action_time_ms, 2),
            "wait_time_ms": round(self._wait_time_ms, 2),
            "actions_count": len(self._actions),
            "wait_for_selector": self._wait_for_selector,
            "wait_for_load_state": self._wait_for_load_state,
            "wait_milliseconds": self._wait_milliseconds,
            "include_links": self._include_links,
            "include_screenshot": self._include_screenshot,
        })

        return base

    def __repr__(self) -> str:
        parts = ["SinglePageCrawler(url_count=1"]
        if self._actions:
            parts.append(f"actions={len(self._actions)}")
        if self._wait_for_selector:
            parts.append(f"wait='{self._wait_for_selector}'")
        parts.append(f"visited={len(self._visited)}")
        return ", ".join(parts) + ")"
