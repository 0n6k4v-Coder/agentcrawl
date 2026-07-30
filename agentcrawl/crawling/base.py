"""
AgentCrawl — Crawl Strategy Base
====================================

Abstract base class and shared utilities for all crawling strategies
(BFS, DFS, BestFirst, Adaptive). Defines the interface for URL
discovery, filtering, scoring, and crawl execution.

Architecture:
    CrawlStrategy (ABC)
    ├── BFSCrawler          — Breadth-first exploration
    ├── DFSCrawler          — Depth-first exploration
    ├── BestFirstCrawler    — Priority-based exploration
    └── AdaptiveCrawler     — Pattern-learning exploration

Usage:
    from agentcrawl.crawling.base import (
        CrawlStrategy,
        URLFilter,
        URLScorer,
        CrawlConfig,
    )

    # Custom strategy
    class MyCrawler(CrawlStrategy):
        async def _discover_urls(self, url, engine):
            # ... custom discovery logic ...
            return urls

    # URL filtering
    url_filter = URLFilter(
        include_patterns=["/docs/*", "/api/*"],
        exclude_patterns=["/blog/*", "*.pdf"],
        same_domain=True,
    )

    # URL scoring
    scorer = URLScorer()
    score = scorer.score("https://example.com/docs/guide")
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger("agentcrawl.crawling")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class CrawlConfig:
    """
    Configuration for a crawl operation.

    Attributes:
        max_depth: Maximum link depth from start URL.
        max_pages: Maximum number of pages to crawl.
        max_concurrent: Maximum concurrent page fetches.
        same_domain: Only crawl URLs on the same domain.
        include_patterns: URL glob patterns to include.
        exclude_patterns: URL glob patterns to exclude.
        include_extensions: File extensions to include (empty = all HTML).
        exclude_extensions: File extensions to exclude.
        respect_robots: Whether to respect robots.txt.
        delay_between_requests: Minimum delay between requests (seconds).
        timeout_per_page: Timeout per page in seconds.
        retry_on_failure: Whether to retry failed pages.
        max_retries: Maximum retry attempts.
        score_threshold: Minimum URL score to crawl (0.0 - 1.0).
        deduplicate_content: Skip pages with duplicate content.
        similarity_threshold: Content similarity threshold for dedup.
        progress_callback: Callback for progress updates.
    """

    max_depth: int = 3
    max_pages: int = 50
    max_concurrent: int = 3
    same_domain: bool = True
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    include_extensions: list[str] = field(default_factory=list)
    exclude_extensions: list[str] = field(
        default_factory=lambda: [
            ".css",
            ".js",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
        ]
    )
    respect_robots: bool = True
    delay_between_requests: float = 0.3
    timeout_per_page: int = 30
    retry_on_failure: bool = True
    max_retries: int = 2
    score_threshold: float = 0.0
    deduplicate_content: bool = False
    similarity_threshold: float = 0.85
    progress_callback: Callable[[int, int, str], None] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "max_pages": self.max_pages,
            "max_concurrent": self.max_concurrent,
            "same_domain": self.same_domain,
            "include_patterns": self.include_patterns,
            "exclude_patterns": self.exclude_patterns,
            "exclude_extensions": self.exclude_extensions,
            "respect_robots": self.respect_robots,
            "delay_between_requests": self.delay_between_requests,
            "score_threshold": self.score_threshold,
            "deduplicate_content": self.deduplicate_content,
        }


@dataclass
class DiscoveredURL:
    """
    A URL discovered during crawling.

    Attributes:
        url: The discovered URL.
        depth: Link depth from start URL.
        source_url: URL where this link was found.
        link_text: Anchor text of the link.
        score: Relevance/priority score.
        discovered_at: Unix timestamp of discovery.
    """

    url: str
    depth: int = 0
    source_url: str = ""
    link_text: str = ""
    score: float = 0.5
    discovered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "depth": self.depth,
            "source_url": self.source_url,
            "link_text": self.link_text[:100],
            "score": round(self.score, 3),
        }


@dataclass
class CrawlProgress:
    """
    Progress state of a crawl operation.

    Attributes:
        pages_discovered: Total URLs discovered.
        pages_crawled: Pages successfully crawled.
        pages_failed: Pages that failed.
        pages_skipped: Pages skipped (filter, dedup, depth).
        pages_pending: Pages waiting to be crawled.
        current_depth: Current exploration depth.
        current_url: URL currently being crawled.
        elapsed_ms: Elapsed time in milliseconds.
        is_complete: Whether the crawl is finished.
    """

    pages_discovered: int = 0
    pages_crawled: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    pages_pending: int = 0
    current_depth: int = 0
    current_url: str = ""
    elapsed_ms: float = 0.0
    is_complete: bool = False

    @property
    def completion_ratio(self) -> float:
        total = self.pages_crawled + self.pages_failed + self.pages_pending
        if total == 0:
            return 0.0
        return (self.pages_crawled + self.pages_failed) / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages_discovered": self.pages_discovered,
            "pages_crawled": self.pages_crawled,
            "pages_failed": self.pages_failed,
            "pages_skipped": self.pages_skipped,
            "pages_pending": self.pages_pending,
            "current_depth": self.current_depth,
            "current_url": self.current_url,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "completion_ratio": round(self.completion_ratio, 3),
            "is_complete": self.is_complete,
        }


# ══════════════════════════════════════════════════════════════
# URL Filter
# ══════════════════════════════════════════════════════════════


class URLFilter:
    """
    Filters URLs based on patterns, domain, depth, and extensions.

    Args:
        include_patterns: Glob patterns to include (e.g., ['/docs/*']).
        exclude_patterns: Glob patterns to exclude (e.g., ['/blog/*']).
        same_domain: Only allow same-domain URLs.
        base_domain: Base domain for same_domain check.
        max_depth: Maximum allowed depth.
        exclude_extensions: File extensions to exclude.
        include_extensions: File extensions to include (empty = all).
        exclude_query_params: Strip these query parameters.
        allow_fragments: Whether to allow URL fragments (#).

    Example:
        >>> filter = URLFilter(
        ...     include_patterns=["/docs/*", "/api/*"],
        ...     exclude_patterns=["/blog/*", "*.pdf"],
        ...     same_domain=True,
        ... )
        >>> filter.is_allowed("https://example.com/docs/guide")
        True
        >>> filter.is_allowed("https://example.com/blog/post")
        False
    """

    def __init__(
        self,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        same_domain: bool = True,
        base_domain: str = "",
        max_depth: int = 10,
        exclude_extensions: list[str] | None = None,
        include_extensions: list[str] | None = None,
        exclude_query_params: list[str] | None = None,
        allow_fragments: bool = False,
    ):
        self._include_patterns = include_patterns or []
        self._exclude_patterns = exclude_patterns or []
        self._same_domain = same_domain
        self._base_domain = base_domain.replace("www.", "")
        self._max_depth = max_depth
        self._exclude_extensions = {ext.lower() for ext in (exclude_extensions or [])}
        self._include_extensions = {ext.lower() for ext in (include_extensions or [])}
        self._exclude_query_params = set(exclude_query_params or [])
        self._allow_fragments = allow_fragments

        # Deduplication tracking
        self._seen_urls: set[str] = set()

    def set_base_domain(self, url: str) -> None:
        """Set the base domain from a URL."""
        with contextlib.suppress(Exception):
            self._base_domain = urlparse(url).netloc.replace("www.", "")

    def is_allowed(self, url: str, depth: int = 0) -> bool:
        """
        Check if a URL is allowed by the filter.

        Args:
            url: URL to check.
            depth: Link depth from start URL.

        Returns:
            True if the URL passes all filter rules.
        """
        # Depth check
        if depth > self._max_depth:
            return False

        try:
            parsed = urlparse(url)
        except Exception:
            return False

        # Scheme check
        if parsed.scheme not in ("http", "https"):
            return False

        # Domain check
        if self._same_domain and self._base_domain:
            domain = parsed.netloc.replace("www.", "")
            if domain != self._base_domain:
                return False

        # Fragment check
        if not self._allow_fragments and parsed.fragment:
            return False

        # Extension check
        path_lower = parsed.path.lower()
        if self._exclude_extensions:
            for ext in self._exclude_extensions:
                if path_lower.endswith(ext):
                    return False

        if self._include_extensions and not any(
            path_lower.endswith(ext) for ext in self._include_extensions
        ):
            return False

        # Include patterns
        if self._include_patterns:
            path = parsed.path
            if not any(
                fnmatch.fnmatch(path, p) or fnmatch.fnmatch(url, p) for p in self._include_patterns
            ):
                return False

        # Exclude patterns
        if self._exclude_patterns:
            path = parsed.path
            if any(
                fnmatch.fnmatch(path, p) or fnmatch.fnmatch(url, p) for p in self._exclude_patterns
            ):
                return False

        return True

    def normalize(self, url: str) -> str:
        """
        Normalize a URL for deduplication.

        Removes fragments, strips trailing slashes, and removes
        excluded query parameters.
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return url

        # Remove fragment
        if not self._allow_fragments:
            parsed = parsed._replace(fragment="")

        # Remove excluded query params
        if self._exclude_query_params and parsed.query:
            from urllib.parse import parse_qs, urlencode

            params = parse_qs(parsed.query)
            filtered = {k: v for k, v in params.items() if k not in self._exclude_query_params}
            new_query = urlencode(filtered, doseq=True)
            parsed = parsed._replace(query=new_query)

        # Rebuild
        normalized = parsed.geturl()

        # Strip trailing slash (except root)
        if normalized.endswith("/") and normalized.count("/") > 3:
            normalized = normalized.rstrip("/")

        return normalized

    # Deduplication methods
    def is_seen(self, url: str) -> bool:
        """Check if URL has been seen before (normalized)."""
        normalized = self.normalize(url)
        return normalized in self._seen_urls

    def mark_seen(self, url: str) -> None:
        """Mark a URL as seen."""
        normalized = self.normalize(url)
        self._seen_urls.add(normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_patterns": self._include_patterns,
            "exclude_patterns": self._exclude_patterns,
            "same_domain": self._same_domain,
            "base_domain": self._base_domain,
            "max_depth": self._max_depth,
            "exclude_extensions": list(self._exclude_extensions),
        }

    def __repr__(self) -> str:
        return (
            f"URLFilter(same_domain={self._same_domain}, "
            f"include={len(self._include_patterns)}, "
            f"exclude={len(self._exclude_patterns)})"
        )


# ══════════════════════════════════════════════════════════════
# URL Scorer
# ══════════════════════════════════════════════════════════════


class URLScorer:
    """
    Scores URLs by predicted content value.

    Uses heuristics based on URL structure, path keywords,
    depth, and link text to estimate how valuable a page
    will be to crawl.

    Args:
        content_keywords: Keywords that indicate content pages.
        noise_keywords: Keywords that indicate noise pages.
        depth_penalty: Score penalty per depth level.
        link_text_weight: Weight for link text relevance.

    Example:
        >>> scorer = URLScorer()
        >>> score = scorer.score(
        ...     "https://example.com/docs/getting-started",
        ...     link_text="Getting Started Guide",
        ... )
        >>> print(f"Score: {score:.2f}")
    """

    DEFAULT_CONTENT_KEYWORDS: tuple[str, ...] = (
        "guide",
        "tutorial",
        "docs",
        "documentation",
        "reference",
        "api",
        "manual",
        "help",
        "faq",
        "wiki",
        "blog",
        "post",
        "article",
        "news",
        "learn",
        "how-to",
        "howto",
        "getting-started",
        "quickstart",
        "overview",
        "introduction",
        "setup",
        "install",
        "configuration",
        "examples",
        "sample",
        "demo",
    )

    DEFAULT_NOISE_KEYWORDS: tuple[str, ...] = (
        "login",
        "signin",
        "signup",
        "register",
        "auth",
        "cart",
        "checkout",
        "payment",
        "billing",
        "pricing",
        "search",
        "filter",
        "sort",
        "tag",
        "category",
        "page",
        "feed",
        "rss",
        "atom",
        "sitemap",
        "about",
        "contact",
        "privacy",
        "terms",
        "legal",
        "careers",
        "jobs",
        "press",
        "media",
    )

    def __init__(
        self,
        content_keywords: Sequence[str] | None = None,
        noise_keywords: Sequence[str] | None = None,
        depth_penalty: float = 0.05,
        link_text_weight: float = 0.2,
    ):
        self._content_keywords = {
            kw.lower()
            for kw in (
                content_keywords if content_keywords is not None else self.DEFAULT_CONTENT_KEYWORDS
            )
        }
        self._noise_keywords = {
            kw.lower()
            for kw in (
                noise_keywords if noise_keywords is not None else self.DEFAULT_NOISE_KEYWORDS
            )
        }
        self._depth_penalty = depth_penalty
        self._link_text_weight = link_text_weight

    def score(
        self,
        url: str,
        depth: int = 0,
        link_text: str = "",
    ) -> float:
        """
        Score a URL by predicted value.

        Args:
            url: URL to score.
            depth: Link depth from start URL.
            link_text: Anchor text of the link.

        Returns:
            Score between 0.0 (low value) and 1.0 (high value).
        """
        score = 0.5  # Base score

        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            segments = [s for s in path.split("/") if s]
        except Exception:
            return 0.0

        # Content keyword bonus
        for kw in self._content_keywords:
            if kw in path:
                score += 0.15
                break

        # Noise keyword penalty
        for kw in self._noise_keywords:
            if kw in path:
                score -= 0.2
                break

        # Path structure analysis
        if segments:
            # Slug-like segments (long, hyphenated) suggest content
            for seg in segments:
                if len(seg) > 15 and "-" in seg:
                    score += 0.1
                    break

            # Numeric segments suggest pagination or IDs
            numeric_count = sum(1 for s in segments if s.isdigit())
            if numeric_count > 0:
                score -= 0.05 * numeric_count

        # Depth penalty
        score -= self._depth_penalty * depth

        # Link text relevance
        if link_text and self._link_text_weight > 0:
            text_lower = link_text.lower()
            text_score = 0.0
            for kw in self._content_keywords:
                if kw in text_lower:
                    text_score += 0.1
                    break
            # Longer link text is usually more descriptive
            if len(link_text) > 20:
                text_score += 0.05
            score += text_score * self._link_text_weight

        # Query string penalty (often indicates dynamic/filter pages)
        if parsed.query:
            score -= 0.1

        return max(0.0, min(1.0, score))

    def score_batch(
        self,
        urls: list[tuple[str, int, str]],
    ) -> list[float]:
        """
        Score multiple URLs.

        Args:
            urls: List of (url, depth, link_text) tuples.

        Returns:
            List of scores.
        """
        return [self.score(url, depth, text) for url, depth, text in urls]

    def __repr__(self) -> str:
        return (
            f"URLScorer(content_kw={len(self._content_keywords)}, "
            f"noise_kw={len(self._noise_keywords)})"
        )


# ══════════════════════════════════════════════════════════════
# Crawl Strategy ABC
# ══════════════════════════════════════════════════════════════


class CrawlStrategy(ABC):
    """
    Abstract base class for all crawling strategies.

    Subclasses must implement:
        - strategy_name: Strategy identifier.
        - _discover_urls: Core URL discovery logic.

    The base class provides:
        - URL filtering and normalization
        - URL scoring
        - Progress tracking
        - Crawl execution orchestration
        - robots.txt checking

    Args:
        max_depth: Maximum link depth.
        max_pages: Maximum pages to crawl.
        url_filter: URL filter instance.
        url_scorer: URL scorer instance.
        config: Full crawl configuration.

    Example:
        >>> class MyCrawler(CrawlStrategy):
        ...     strategy_name = "my_strategy"
        ...     async def _discover_urls(self, url, engine):
        ...         # Custom discovery logic
        ...         return [DiscoveredURL(url="...", depth=1)]
        ...
        >>> crawler = MyCrawler(max_depth=3, max_pages=50)
        >>> urls = await crawler.discover("https://example.com", engine)
    """

    strategy_name: str = "base"

    def __init__(
        self,
        max_depth: int = 3,
        max_pages: int = 50,
        max_concurrent: int = 3,
        url_filter: URLFilter | None = None,
        url_scorer: URLScorer | None = None,
        config: CrawlConfig | None = None,
    ):
        if max_depth <= 0:
            raise ValueError("max_depth must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")

        self._config = config or CrawlConfig(
            max_depth=max_depth,
            max_pages=max_pages,
            max_concurrent=max_concurrent,
        )
        self._config.max_depth = max_depth
        self._config.max_pages = max_pages
        self._config.max_concurrent = max_concurrent

        self._filter = url_filter or URLFilter(
            include_patterns=self._config.include_patterns,
            exclude_patterns=self._config.exclude_patterns,
            same_domain=self._config.same_domain,
            max_depth=self._config.max_depth,
            exclude_extensions=self._config.exclude_extensions,
        )
        self._scorer = url_scorer or URLScorer()

        # State
        self._visited: set[str] = set()
        self._discovered: dict[str, DiscoveredURL] = {}
        self._progress = CrawlProgress()
        self._start_time: float = 0.0
        self._robots_allowed: dict[str, bool] = {}

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def config(self) -> CrawlConfig:
        """Crawl configuration."""
        return self._config

    @property
    def progress(self) -> CrawlProgress:
        """Current crawl progress."""
        self._progress.elapsed_ms = (time.time() - self._start_time) * 1000
        return self._progress

    @property
    def max_depth(self) -> int:
        """Maximum crawl depth."""
        return self._config.max_depth

    @property
    def max_pages(self) -> int:
        """Maximum pages to crawl."""
        return self._config.max_pages

    @property
    def max_concurrent(self) -> int:
        """Maximum concurrent requests."""
        return self._config.max_concurrent

    @property
    def visited_count(self) -> int:
        """Number of visited URLs."""
        return len(self._visited)

    @property
    def discovered_count(self) -> int:
        """Number of discovered URLs."""
        return len(self._discovered)

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    async def discover(
        self,
        url: str,
        engine: Any,
    ) -> list[str]:
        """
        Discover URLs by crawling from a start URL.

        Args:
            url: Starting URL.
            engine: CrawlEngine instance.

        Returns:
            List of discovered URLs in priority order.
        """
        self._reset()
        self._start_time = time.time()
        self._filter.set_base_domain(url)

        logger.info(
            "Starting %s crawl from %s (max_depth=%d, max_pages=%d)",
            self.strategy_name,
            url,
            self._config.max_depth,
            self._config.max_pages,
        )

        # Check robots.txt
        if self._config.respect_robots:
            await self._check_robots(url, engine)

        # Run strategy-specific discovery
        await self._discover_urls(url, engine)

        # Update progress
        self._progress.pages_discovered = len(self._discovered)
        self._progress.is_complete = True
        self._progress.elapsed_ms = (time.time() - self._start_time) * 1000

        # Return URLs sorted by score
        sorted_urls = sorted(
            self._discovered.values(),
            key=lambda u: u.score,
            reverse=True,
        )

        result = [u.url for u in sorted_urls[: self._config.max_pages]]

        logger.info(
            "%s crawl complete: %d discovered, %d visited, %.0fms",
            self.strategy_name,
            len(self._discovered),
            len(self._visited),
            self._progress.elapsed_ms,
        )

        return result

    async def crawl(
        self,
        url: str,
        engine: Any,
        config: Any = None,
    ) -> list[Any]:
        """
        Crawl a website and return results.

        Args:
            url: Starting URL.
            engine: CrawlEngine instance.
            config: CrawlerConfig for scraping.

        Returns:
            List of CrawlResult objects.
        """
        urls = await self.discover(url, engine)
        results = []

        for page_url in urls:
            try:
                result = await engine.scrape(page_url, config)
                results.append(result)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", page_url, e)

        return results

    # ──────────────────────────────────────────────────────────
    # Abstract Method
    # ──────────────────────────────────────────────────────────

    @abstractmethod
    async def _discover_urls(
        self,
        url: str,
        engine: Any,
    ) -> list[DiscoveredURL]:
        """
        Core URL discovery logic. Must be implemented by subclasses.

        Args:
            url: Starting URL.
            engine: CrawlEngine instance.

        Returns:
            List of discovered URLs.
        """
        ...

    # ──────────────────────────────────────────────────────────
    # Shared Utilities
    # ──────────────────────────────────────────────────────────

    async def _fetch_links(
        self,
        url: str,
        engine: Any,
        depth: int = 0,
    ) -> list[DiscoveredURL]:
        """
        Fetch a page and extract links.

        Args:
            url: URL to fetch.
            engine: CrawlEngine instance.
            depth: Current depth.

        Returns:
            List of discovered URLs from this page.
        """
        from agentcrawl.config.crawler_config import CrawlerConfig

        normalized = self._filter.normalize(url)

        if normalized in self._visited:
            return []

        self._visited.add(normalized)
        self._progress.current_url = url
        self._progress.current_depth = depth

        try:
            config = CrawlerConfig(
                include_links=True,
                include_metadata=False,
                only_main_content=False,
                cache=True,
            )

            result = await engine.scrape(url, config)

            if not result.success:
                self._progress.pages_failed += 1
                return []

            self._progress.pages_crawled += 1

            # Extract and filter links
            discovered: list[DiscoveredURL] = []
            all_links = result.links.get("all", [])

            for link in all_links:
                link_url = link.get("url", "")
                if not link_url:
                    continue

                # Resolve relative URLs
                absolute_url = urljoin(url, link_url)
                normalized_link = self._filter.normalize(absolute_url)

                # Filter
                if not self._filter.is_allowed(normalized_link, depth + 1):
                    self._progress.pages_skipped += 1
                    continue

                if normalized_link in self._visited or normalized_link in self._discovered:
                    continue

                # Score
                link_text = link.get("text", "")
                score = self._scorer.score(normalized_link, depth + 1, link_text)

                if score < self._config.score_threshold:
                    self._progress.pages_skipped += 1
                    continue

                discovered_url = DiscoveredURL(
                    url=normalized_link,
                    depth=depth + 1,
                    source_url=url,
                    link_text=link_text,
                    score=score,
                )

                self._discovered[normalized_link] = discovered_url
                discovered.append(discovered_url)

            self._progress.pages_discovered = len(self._discovered)
            self._progress.pages_pending = len(self._discovered) - len(self._visited)

            # Progress callback
            if self._config.progress_callback:
                self._config.progress_callback(
                    self._progress.pages_crawled,
                    self._config.max_pages,
                    url,
                )

            return discovered

        except Exception as e:
            logger.debug("Failed to fetch links from %s: %s", url, e)
            self._progress.pages_failed += 1
            return []

    async def _check_robots(self, url: str, engine: Any) -> None:
        """Check robots.txt for crawl permissions."""
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    self._parse_robots(resp.text, parsed.path)
        except Exception as e:
            logger.debug("robots.txt check failed: %s", e)

    def _parse_robots(self, robots_text: str, path: str) -> None:
        """Parse robots.txt and check if path is allowed."""
        # Simple robots.txt parser
        current_agent = ""
        disallowed: list[str] = []

        for line in robots_text.splitlines():
            line = line.strip()
            if line.lower().startswith("user-agent:"):
                current_agent = line.split(":", 1)[1].strip()
            elif line.lower().startswith("disallow:") and current_agent == "*":
                disallow_path = line.split(":", 1)[1].strip()
                if disallow_path:
                    disallowed.append(disallow_path)

        for dp in disallowed:
            if path.startswith(dp):
                self._robots_allowed[path] = False
                return

        self._robots_allowed[path] = True

    def _is_robots_allowed(self, url: str) -> bool:
        """Check if a URL is allowed by robots.txt."""
        if not self._config.respect_robots:
            return True

        try:
            path = urlparse(url).path
        except Exception:
            return True

        return self._robots_allowed.get(path, True)

    def _reset(self) -> None:
        """Reset crawler state."""
        self._visited.clear()
        self._discovered.clear()
        self._progress = CrawlProgress()
        self._robots_allowed.clear()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get crawler diagnostics."""
        return {
            "strategy": self.strategy_name,
            "config": self._config.to_dict(),
            "progress": self.progress.to_dict(),
            "visited_count": len(self._visited),
            "discovered_count": len(self._discovered),
            "filter": self._filter.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(max_depth={self._config.max_depth}, "
            f"max_pages={self._config.max_pages}, "
            f"visited={len(self._visited)}, "
            f"discovered={len(self._discovered)})"
        )
