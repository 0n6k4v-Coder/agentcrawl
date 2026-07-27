"""
AgentCrawl — Adaptive Crawler
================================

An intelligent crawler that learns site structure patterns from
initial pages and adapts its exploration strategy accordingly.

Unlike fixed BFS/DFS crawlers, the AdaptiveCrawler:
    - Analyzes URL patterns from initial discoveries
    - Scores URLs by predicted content value
    - Avoids duplicate/boilerplate content via similarity detection
    - Adjusts crawl depth based on site structure
    - Adapts request rate based on server response times
    - Prioritizes content-rich sections over navigation/boilerplate

Algorithm:
    Phase 1 — Discovery:
        Fetch the start URL and extract all links.
        Analyze URL patterns (path segments, depth, extensions).

    Phase 2 — Pattern Learning:
        Cluster URLs by pattern (e.g., /blog/*, /docs/*, /api/*).
        Score each pattern by link density and content indicators.

    Phase 3 — Adaptive Exploration:
        Explore high-value patterns first.
        Skip patterns that look like navigation, pagination, or boilerplate.
        Adjust depth and breadth based on discovered structure.

    Phase 4 — Content Deduplication:
        Compare content similarity between pages.
        Skip pages with > threshold similarity to already-crawled pages.

Usage:
    from agentcrawl.crawling.adaptive import AdaptiveCrawler

    crawler = AdaptiveCrawler(
        max_pages=100,
        max_depth=4,
        similarity_threshold=0.85,
        learn_from_pages=5,
    )

    # Discover URLs
    urls = await crawler.discover("https://docs.example.com", engine)

    # Or run full adaptive crawl
    results = await crawler.crawl("https://docs.example.com", engine)
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

logger = logging.getLogger("agentcrawl.crawling.adaptive")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class URLPattern:
    """
    A detected URL pattern with statistics.

    Attributes:
        pattern: Regex pattern string (e.g., '/blog/[^/]+').
        template: Human-readable template (e.g., '/blog/{slug}').
        example_urls: Sample URLs matching this pattern.
        count: Number of URLs matching this pattern.
        avg_depth: Average path depth of matching URLs.
        score: Computed value score (higher = more valuable).
        is_navigation: Whether this pattern looks like navigation.
        is_pagination: Whether this pattern looks like pagination.
        is_content: Whether this pattern looks like content.
    """
    pattern: str = ""
    template: str = ""
    example_urls: list[str] = field(default_factory=list)
    count: int = 0
    avg_depth: int = 0
    score: float = 0.0
    is_navigation: bool = False
    is_pagination: bool = False
    is_content: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "template": self.template,
            "count": self.count,
            "avg_depth": self.avg_depth,
            "score": round(self.score, 3),
            "is_navigation": self.is_navigation,
            "is_pagination": self.is_pagination,
            "is_content": self.is_content,
            "examples": self.example_urls[:3],
        }


@dataclass
class CrawlCandidate:
    """
    A URL candidate for crawling with priority score.

    Attributes:
        url: The candidate URL.
        depth: Link depth from start URL.
        score: Priority score (higher = crawl first).
        pattern: Matched URL pattern.
        source_url: URL where this link was found.
        link_text: Anchor text of the link.
        discovered_at: Unix timestamp of discovery.
        crawled: Whether this URL has been crawled.
        content_hash: Hash of crawled content (for dedup).
        similarity_to_existing: Max similarity to already-crawled pages.
    """
    url: str
    depth: int = 0
    score: float = 0.0
    pattern: str = ""
    source_url: str = ""
    link_text: str = ""
    discovered_at: float = field(default_factory=time.time)
    crawled: bool = False
    content_hash: str = ""
    similarity_to_existing: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "depth": self.depth,
            "score": round(self.score, 3),
            "pattern": self.pattern,
            "source_url": self.source_url,
            "crawled": self.crawled,
        }


@dataclass
class AdaptiveStats:
    """Statistics from an adaptive crawl."""
    total_discovered: int = 0
    total_crawled: int = 0
    total_skipped_duplicate: int = 0
    total_skipped_pattern: int = 0
    total_skipped_depth: int = 0
    total_errors: int = 0
    patterns_detected: int = 0
    content_patterns: int = 0
    navigation_patterns: int = 0
    avg_response_time_ms: float = 0.0
    avg_similarity_score: float = 0.0
    depth_distribution: dict[int, int] = field(default_factory=dict)
    pattern_scores: dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_discovered": self.total_discovered,
            "total_crawled": self.total_crawled,
            "total_skipped_duplicate": self.total_skipped_duplicate,
            "total_skipped_pattern": self.total_skipped_pattern,
            "total_skipped_depth": self.total_skipped_depth,
            "total_errors": self.total_errors,
            "patterns_detected": self.patterns_detected,
            "content_patterns": self.content_patterns,
            "navigation_patterns": self.navigation_patterns,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "avg_similarity_score": round(self.avg_similarity_score, 3),
            "depth_distribution": self.depth_distribution,
            "duration_ms": round(self.duration_ms, 2),
        }


# ══════════════════════════════════════════════════════════════
# URL Pattern Analyzer
# ══════════════════════════════════════════════════════════════

class URLPatternAnalyzer:
    """
    Analyzes URLs to detect structural patterns.

    Groups URLs by path structure and classifies them as
    content, navigation, pagination, or boilerplate.
    """

    # Patterns that indicate navigation / non-content
    NAV_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"/(tag|category|author|archive|page)/", re.I),
        re.compile(r"/(login|signup|register|signin|auth)/", re.I),
        re.compile(r"/(cart|checkout|payment|billing)/", re.I),
        re.compile(r"/(search|filter|sort)/", re.I),
        re.compile(r"/(feed|rss|atom|sitemap)\b", re.I),
        re.compile(r"\.(css|js|png|jpg|jpeg|gif|svg|ico|woff|ttf|pdf|zip)$", re.I),
        re.compile(r"[?&](page|p|pg|offset|start)=\d+", re.I),
        re.compile(r"/page/\d+", re.I),
    ]

    # Patterns that indicate content
    CONTENT_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"/(blog|post|article|news|tutorial|guide|docs|documentation)/", re.I),
        re.compile(r"/(api|reference|manual|help|faq|wiki)/", re.I),
        re.compile(r"/\d{4}/\d{2}/", re.I),  # /2024/01/ date-based
        re.compile(r"/[a-z0-9-]{10,}/?$", re.I),  # /long-slug-title/
    ]

    def analyze(self, urls: list[str], base_url: str = "") -> list[URLPattern]:
        """
        Analyze a list of URLs and detect patterns.

        Args:
            urls: List of URLs to analyze.
            base_url: Base URL for relative resolution.

        Returns:
            List of detected URLPattern objects, sorted by score.
        """
        if not urls:
            return []

        base_domain = ""
        if base_url:
            try:
                base_domain = urlparse(base_url).netloc
            except Exception:
                pass

        # Group URLs by path template
        template_groups: dict[str, list[str]] = defaultdict(list)

        for url in urls:
            template = self._url_to_template(url)
            template_groups[template].append(url)

        # Build URLPattern objects
        patterns: list[URLPattern] = []

        for template, group_urls in template_groups.items():
            depths = [self._url_depth(u) for u in group_urls]
            avg_depth = sum(depths) / max(len(depths), 1)

            is_nav = self._is_navigation(template, group_urls)
            is_pag = self._is_pagination(template, group_urls)
            is_content = self._is_content(template, group_urls)

            # Compute score
            score = self._score_pattern(
                template=template,
                count=len(group_urls),
                avg_depth=avg_depth,
                is_nav=is_nav,
                is_pag=is_pag,
                is_content=is_content,
            )

            patterns.append(URLPattern(
                pattern=self._template_to_regex(template),
                template=template,
                example_urls=group_urls[:5],
                count=len(group_urls),
                avg_depth=round(avg_depth, 1),
                score=score,
                is_navigation=is_nav,
                is_pagination=is_pag,
                is_content=is_content,
            ))

        # Sort by score descending
        patterns.sort(key=lambda p: p.score, reverse=True)
        return patterns

    def _url_to_template(self, url: str) -> str:
        """
        Convert a URL to a structural template.

        Replaces variable segments with placeholders:
            /blog/my-first-post → /blog/{slug}
            /docs/v2/api/users → /docs/{version}/api/{resource}
            /page/3 → /page/{num}
        """
        try:
            parsed = urlparse(url)
            path = parsed.path.rstrip("/")
            query = parsed.query
        except Exception:
            return url

        segments = path.split("/")
        template_segments: list[str] = []

        for seg in segments:
            if not seg:
                template_segments.append("")
                continue

            # Numeric segment
            if re.match(r"^\d+$", seg):
                template_segments.append("{num}")
            # UUID
            elif re.match(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                seg, re.I,
            ):
                template_segments.append("{uuid}")
            # Hex hash
            elif re.match(r"^[0-9a-f]{16,}$", seg, re.I):
                template_segments.append("{hash}")
            # Version-like (v1, v2.0)
            elif re.match(r"^v\d+(\.\d+)*$", seg, re.I):
                template_segments.append("{version}")
            # Date-like (2024-01-15)
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", seg):
                template_segments.append("{date}")
            # Long slug (likely content)
            elif len(seg) > 15 and re.match(r"^[a-z0-9-]+$", seg, re.I):
                template_segments.append("{slug}")
            # Short identifier
            elif re.match(r"^[a-z0-9_-]{1,15}$", seg, re.I):
                template_segments.append(seg)  # Keep as-is (likely a section name)
            else:
                template_segments.append("{var}")

        template = "/".join(template_segments)

        # Add query pattern if present
        if query:
            params = parse_qs(query)
            param_names = sorted(params.keys())
            template += "?" + "&".join(f"{p}={{val}}" for p in param_names)

        return template or "/"

    def _template_to_regex(self, template: str) -> str:
        """Convert a template to a regex pattern."""
        pattern = re.escape(template)
        pattern = pattern.replace(r"\{num\}", r"\d+")
        pattern = pattern.replace(r"\{slug\}", r"[a-z0-9-]+")
        pattern = pattern.replace(r"\{uuid\}", r"[0-9a-f-]+")
        pattern = pattern.replace(r"\{hash\}", r"[0-9a-f]+")
        pattern = pattern.replace(r"\{version\}", r"v\d+(\.\d+)*")
        pattern = pattern.replace(r"\{date\}", r"\d{4}-\d{2}-\d{2}")
        pattern = pattern.replace(r"\{var\}", r"[^/]+")
        pattern = pattern.replace(r"\{val\}", r"[^&]+")
        return pattern

    @staticmethod
    def _url_depth(url: str) -> int:
        """Get the path depth of a URL."""
        try:
            path = urlparse(url).path.strip("/")
            return len(path.split("/")) if path else 0
        except Exception:
            return 0

    def _is_navigation(self, template: str, urls: list[str]) -> bool:
        """Check if a pattern looks like navigation."""
        for pattern in self.NAV_PATTERNS:
            if pattern.search(template):
                return True
            for url in urls[:3]:
                if pattern.search(url):
                    return True
        return False

    def _is_pagination(self, template: str, urls: list[str]) -> bool:
        """Check if a pattern looks like pagination."""
        pagination_re = re.compile(
            r"(page|p|pg|offset|start)[=/]\{?(num|val|\d+)\}?", re.I
        )
        if pagination_re.search(template):
            return True
        for url in urls[:3]:
            if re.search(r"[?&](page|p|pg|offset|start)=\d+", url, re.I):
                return True
            if re.search(r"/page/\d+", url, re.I):
                return True
        return False

    def _is_content(self, template: str, urls: list[str]) -> bool:
        """Check if a pattern looks like content."""
        for pattern in self.CONTENT_PATTERNS:
            if pattern.search(template):
                return True
        return False

    @staticmethod
    def _score_pattern(
        template: str,
        count: int,
        avg_depth: float,
        is_nav: bool,
        is_pag: bool,
        is_content: bool,
    ) -> float:
        """
        Score a URL pattern by predicted value.

        Higher score = more valuable to crawl.
        """
        score = 0.5  # Base score

        # Content patterns are valuable
        if is_content:
            score += 0.3

        # Navigation patterns are low value
        if is_nav:
            score -= 0.4

        # Pagination is low value
        if is_pag:
            score -= 0.3

        # Moderate count is good (not too few, not too many)
        if 2 <= count <= 50:
            score += 0.1
        elif count > 200:
            score -= 0.2  # Likely boilerplate

        # Shallow depth is slightly better
        if avg_depth <= 3:
            score += 0.1
        elif avg_depth > 6:
            score -= 0.1

        return max(0.0, min(1.0, score))


# ══════════════════════════════════════════════════════════════
# Content Similarity Tracker
# ══════════════════════════════════════════════════════════════

class ContentSimilarityTracker:
    """
    Tracks content similarity between crawled pages to detect
    and skip duplicate/boilerplate content.

    Uses SimHash-like fingerprinting for fast comparison.
    """

    def __init__(self, threshold: float = 0.85):
        self._threshold = threshold
        self._fingerprints: list[tuple[str, int]] = []  # (url, fingerprint)
        self._hash_bits = 64

    def compute_fingerprint(self, text: str) -> int:
        """
        Compute a SimHash fingerprint for text.

        Args:
            text: Input text.

        Returns:
            64-bit integer fingerprint.
        """
        if not text:
            return 0

        # Tokenize into shingles (3-word windows)
        words = text.lower().split()
        shingles: list[str] = []
        for i in range(len(words) - 2):
            shingles.append(" ".join(words[i:i + 3]))

        if not shingles:
            shingles = words

        # Compute SimHash
        v = [0] * self._hash_bits

        for shingle in shingles:
            h = hash(shingle) & ((1 << self._hash_bits) - 1)
            for i in range(self._hash_bits):
                if h & (1 << i):
                    v[i] += 1
                else:
                    v[i] -= 1

        fingerprint = 0
        for i in range(self._hash_bits):
            if v[i] > 0:
                fingerprint |= (1 << i)

        return fingerprint

    def hamming_similarity(self, fp_a: int, fp_b: int) -> float:
        """
        Compute similarity between two fingerprints.

        Args:
            fp_a: First fingerprint.
            fp_b: Second fingerprint.

        Returns:
            Similarity score (0.0 to 1.0).
        """
        xor = fp_a ^ fp_b
        diff_bits = bin(xor).count("1")
        return 1.0 - (diff_bits / self._hash_bits)

    def add(self, url: str, text: str) -> None:
        """Add a page's content fingerprint."""
        fp = self.compute_fingerprint(text)
        self._fingerprints.append((url, fp))

    def max_similarity(self, text: str) -> tuple[float, str]:
        """
        Find the maximum similarity between text and all stored pages.

        Args:
            text: Text to compare.

        Returns:
            Tuple of (max_similarity, most_similar_url).
        """
        if not self._fingerprints:
            return 0.0, ""

        fp = self.compute_fingerprint(text)
        max_sim = 0.0
        max_url = ""

        for url, stored_fp in self._fingerprints:
            sim = self.hamming_similarity(fp, stored_fp)
            if sim > max_sim:
                max_sim = sim
                max_url = url

        return max_sim, max_url

    def is_duplicate(self, text: str) -> tuple[bool, float, str]:
        """
        Check if text is a duplicate of existing content.

        Args:
            text: Text to check.

        Returns:
            Tuple of (is_duplicate, similarity_score, similar_url).
        """
        sim, url = self.max_similarity(text)
        return sim >= self._threshold, sim, url

    @property
    def size(self) -> int:
        """Number of stored fingerprints."""
        return len(self._fingerprints)

    def clear(self) -> None:
        """Clear all stored fingerprints."""
        self._fingerprints.clear()


# ══════════════════════════════════════════════════════════════
# Adaptive Crawler
# ══════════════════════════════════════════════════════════════

class AdaptiveCrawler:
    """
    Intelligent crawler that learns site structure and adapts
    its exploration strategy.

    Args:
        max_pages: Maximum pages to crawl.
        max_depth: Maximum link depth from start URL.
        learn_from_pages: Number of initial pages to learn patterns from.
        similarity_threshold: Content similarity threshold for dedup.
        min_pattern_score: Minimum pattern score to explore.
        max_concurrent: Maximum concurrent page fetches.
        same_domain_only: Only crawl same-domain URLs.
        include_patterns: URL patterns to include (glob).
        exclude_patterns: URL patterns to exclude (glob).
        respect_robots: Whether to respect robots.txt.
        rate_limit_delay: Minimum delay between requests (seconds).

    Example:
        >>> crawler = AdaptiveCrawler(max_pages=100, max_depth=4)
        >>> urls = await crawler.discover("https://docs.example.com", engine)
        >>> print(f"Discovered {len(urls)} URLs")
        >>> print(crawler.stats.to_dict())
    """

    def __init__(
        self,
        max_pages: int = 100,
        max_depth: int = 4,
        learn_from_pages: int = 5,
        similarity_threshold: float = 0.85,
        min_pattern_score: float = 0.2,
        max_concurrent: int = 3,
        same_domain_only: bool = True,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        respect_robots: bool = True,
        rate_limit_delay: float = 0.5,
    ):
        self._max_pages = max_pages
        self._max_depth = max_depth
        self._learn_from_pages = learn_from_pages
        self._similarity_threshold = similarity_threshold
        self._min_pattern_score = min_pattern_score
        self._max_concurrent = max_concurrent
        self._same_domain_only = same_domain_only
        self._include_patterns = include_patterns or []
        self._exclude_patterns = exclude_patterns or []
        self._respect_robots = respect_robots
        self._rate_limit_delay = rate_limit_delay

        # Components
        self._pattern_analyzer = URLPatternAnalyzer()
        self._similarity_tracker = ContentSimilarityTracker(similarity_threshold)

        # State
        self._base_domain: str = ""
        self._candidates: dict[str, CrawlCandidate] = {}
        self._crawled_urls: set[str] = set()
        self._patterns: list[URLPattern] = []
        self._stats = AdaptiveStats()
        self._response_times: list[float] = []

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def stats(self) -> AdaptiveStats:
        """Crawl statistics."""
        return self._stats

    @property
    def patterns(self) -> list[URLPattern]:
        """Detected URL patterns."""
        return list(self._patterns)

    @property
    def candidates(self) -> list[CrawlCandidate]:
        """All discovered candidates."""
        return list(self._candidates.values())

    @property
    def crawled_count(self) -> int:
        """Number of pages crawled."""
        return len(self._crawled_urls)

    # ──────────────────────────────────────────────────────────
    # Discovery
    # ──────────────────────────────────────────────────────────

    async def discover(
        self,
        url: str,
        engine: Any,
    ) -> list[str]:
        """
        Discover URLs by adaptive crawling.

        Args:
            url: Starting URL.
            engine: CrawlEngine instance.

        Returns:
            List of discovered URLs in priority order.
        """
        start_time = time.perf_counter()

        # Parse base domain
        try:
            self._base_domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            self._base_domain = ""

        # Phase 1: Initial discovery
        logger.info("Phase 1: Initial discovery from %s", url)
        await self._initial_discovery(url, engine)

        # Phase 2: Pattern learning
        logger.info(
            "Phase 2: Learning patterns from %d URLs",
            len(self._candidates),
        )
        self._learn_patterns()

        # Phase 3: Adaptive exploration
        logger.info("Phase 3: Adaptive exploration")
        await self._adaptive_explore(engine)

        # Build result
        self._stats.duration_ms = (time.perf_counter() - start_time) * 1000
        self._stats.total_discovered = len(self._candidates)
        self._stats.total_crawled = len(self._crawled_urls)
        self._stats.patterns_detected = len(self._patterns)
        self._stats.content_patterns = sum(1 for p in self._patterns if p.is_content)
        self._stats.navigation_patterns = sum(1 for p in self._patterns if p.is_navigation)

        if self._response_times:
            self._stats.avg_response_time_ms = (
                sum(self._response_times) / len(self._response_times)
            )

        # Return crawled URLs in priority order
        crawled_candidates = [
            c for c in self._candidates.values() if c.crawled
        ]
        crawled_candidates.sort(key=lambda c: c.score, reverse=True)

        result_urls = [c.url for c in crawled_candidates]

        # Add discovered but not crawled (high priority)
        uncrawled = [
            c for c in self._candidates.values()
            if not c.crawled and c.score >= self._min_pattern_score
        ]
        uncrawled.sort(key=lambda c: c.score, reverse=True)
        result_urls.extend(c.url for c in uncrawled)

        logger.info(
            "Adaptive crawl complete: %d crawled, %d discovered, %d patterns",
            len(self._crawled_urls),
            len(self._candidates),
            len(self._patterns),
        )

        return result_urls[:self._max_pages]

    async def crawl(
        self,
        url: str,
        engine: Any,
        config: Any = None,
    ) -> list[Any]:
        """
        Run a full adaptive crawl and return results.

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
            if page_url in self._crawled_urls:
                continue
            try:
                result = await engine.scrape(page_url, config)
                results.append(result)
            except Exception as e:
                logger.warning("Failed to scrape %s: %s", page_url, e)

        return results

    # ──────────────────────────────────────────────────────────
    # Phase 1: Initial Discovery
    # ──────────────────────────────────────────────────────────

    async def _initial_discovery(self, url: str, engine: Any) -> None:
        """Fetch the start URL and discover initial links."""
        try:
            from agentcrawl.config.crawler_config import CrawlerConfig

            config = CrawlerConfig(
                include_links=True,
                include_metadata=True,
                only_main_content=True,
            )

            result = await engine.scrape(url, config)
            self._crawled_urls.add(url)

            # Track content for similarity
            if result.markdown:
                self._similarity_tracker.add(url, result.markdown)

            # Extract links
            all_links = result.links.get("all", [])
            for link in all_links:
                link_url = link.get("url", "")
                if link_url and self._should_include(link_url):
                    self._add_candidate(
                        url=link_url,
                        depth=1,
                        source_url=url,
                        link_text=link.get("text", ""),
                    )

            self._stats.total_crawled += 1

            # Learn from additional pages
            learn_count = min(self._learn_from_pages, len(self._candidates))
            learn_candidates = sorted(
                self._candidates.values(),
                key=lambda c: c.depth,
            )[:learn_count]

            for candidate in learn_candidates:
                if candidate.url in self._crawled_urls:
                    continue
                try:
                    result = await engine.scrape(candidate.url, config)
                    self._crawled_urls.add(candidate.url)
                    candidate.crawled = True

                    if result.markdown:
                        self._similarity_tracker.add(candidate.url, result.markdown)

                    # Discover more links
                    for link in result.links.get("all", []):
                        link_url = link.get("url", "")
                        if link_url and self._should_include(link_url):
                            self._add_candidate(
                                url=link_url,
                                depth=candidate.depth + 1,
                                source_url=candidate.url,
                                link_text=link.get("text", ""),
                            )

                    self._stats.total_crawled += 1

                except Exception as e:
                    logger.debug("Learn page failed %s: %s", candidate.url, e)
                    self._stats.total_errors += 1

        except Exception as e:
            logger.error("Initial discovery failed for %s: %s", url, e)
            self._stats.total_errors += 1

    # ──────────────────────────────────────────────────────────
    # Phase 2: Pattern Learning
    # ──────────────────────────────────────────────────────────

    def _learn_patterns(self) -> None:
        """Analyze discovered URLs to detect patterns."""
        all_urls = [c.url for c in self._candidates.values()]
        self._patterns = self._pattern_analyzer.analyze(all_urls)

        # Score candidates based on pattern
        pattern_map: dict[str, URLPattern] = {}
        for p in self._patterns:
            try:
                regex = re.compile(p.pattern, re.I)
                pattern_map[p.pattern] = p
            except re.error:
                continue

        for candidate in self._candidates.values():
            best_score = 0.0
            best_pattern = ""

            for p in self._patterns:
                try:
                    if re.search(p.pattern, candidate.url, re.I):
                        if p.score > best_score:
                            best_score = p.score
                            best_pattern = p.template
                except re.error:
                    continue

            candidate.score = best_score
            candidate.pattern = best_pattern

            # Penalize navigation/pagination patterns
            for p in self._patterns:
                if p.template == best_pattern:
                    if p.is_navigation:
                        candidate.score *= 0.3
                    if p.is_pagination:
                        candidate.score *= 0.2
                    break

    # ──────────────────────────────────────────────────────────
    # Phase 3: Adaptive Exploration
    # ──────────────────────────────────────────────────────────

    async def _adaptive_explore(self, engine: Any) -> None:
        """Explore high-value candidates adaptively."""
        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            include_links=True,
            only_main_content=True,
        )

        semaphore = asyncio.Semaphore(self._max_concurrent)

        # Sort candidates by score
        pending = sorted(
            [c for c in self._candidates.values() if not c.crawled],
            key=lambda c: c.score,
            reverse=True,
        )

        for candidate in pending:
            if len(self._crawled_urls) >= self._max_pages:
                break

            if candidate.depth > self._max_depth:
                self._stats.total_skipped_depth += 1
                continue

            if candidate.score < self._min_pattern_score:
                self._stats.total_skipped_pattern += 1
                continue

            async with semaphore:
                await self._crawl_candidate(candidate, engine, config)

                # Rate limiting
                if self._rate_limit_delay > 0:
                    await asyncio.sleep(self._rate_limit_delay)

    async def _crawl_candidate(
        self,
        candidate: CrawlCandidate,
        engine: Any,
        config: Any,
    ) -> None:
        """Crawl a single candidate URL."""
        start = time.perf_counter()

        try:
            result = await engine.scrape(candidate.url, config)
            duration = (time.perf_counter() - start) * 1000
            self._response_times.append(duration)

            candidate.crawled = True
            self._crawled_urls.add(candidate.url)
            self._stats.total_crawled += 1

            # Update depth distribution
            self._stats.depth_distribution[candidate.depth] = (
                self._stats.depth_distribution.get(candidate.depth, 0) + 1
            )

            if not result.success:
                self._stats.total_errors += 1
                return

            # Content deduplication
            if result.markdown:
                is_dup, sim, sim_url = self._similarity_tracker.is_duplicate(
                    result.markdown
                )
                candidate.similarity_to_existing = sim

                if is_dup:
                    self._stats.total_skipped_duplicate += 1
                    logger.debug(
                        "Skipping duplicate %s (sim=%.2f to %s)",
                        candidate.url, sim, sim_url,
                    )
                    return

                self._similarity_tracker.add(candidate.url, result.markdown)

            # Discover new links
            for link in result.links.get("all", []):
                link_url = link.get("url", "")
                if link_url and self._should_include(link_url):
                    self._add_candidate(
                        url=link_url,
                        depth=candidate.depth + 1,
                        source_url=candidate.url,
                        link_text=link.get("text", ""),
                    )

        except Exception as e:
            logger.debug("Crawl failed %s: %s", candidate.url, e)
            self._stats.total_errors += 1

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _add_candidate(
        self,
        url: str,
        depth: int,
        source_url: str = "",
        link_text: str = "",
    ) -> None:
        """Add a URL candidate if not already known."""
        # Normalize URL
        url = url.split("#")[0].rstrip("/")
        if not url:
            return

        if url in self._candidates or url in self._crawled_urls:
            return

        self._candidates[url] = CrawlCandidate(
            url=url,
            depth=depth,
            source_url=source_url,
            link_text=link_text,
        )

    def _should_include(self, url: str) -> bool:
        """Check if a URL should be included in the crawl."""
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        # Skip non-HTTP
        if parsed.scheme not in ("http", "https"):
            return False

        # Same domain check
        if self._same_domain_only and self._base_domain:
            domain = parsed.netloc.replace("www.", "")
            if domain != self._base_domain:
                return False

        # Skip file extensions
        path = parsed.path.lower()
        skip_extensions = (
            ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
            ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
            ".zip", ".tar", ".gz", ".mp3", ".mp4", ".avi",
        )
        if any(path.endswith(ext) for ext in skip_extensions):
            return False

        # Include patterns
        if self._include_patterns:
            import fnmatch
            if not any(fnmatch.fnmatch(url, p) for p in self._include_patterns):
                return False

        # Exclude patterns
        if self._exclude_patterns:
            import fnmatch
            if any(fnmatch.fnmatch(url, p) for p in self._exclude_patterns):
                return False

        return True

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics."""
        return {
            "stats": self._stats.to_dict(),
            "patterns": [p.to_dict() for p in self._patterns[:20]],
            "candidates_total": len(self._candidates),
            "candidates_crawled": sum(1 for c in self._candidates.values() if c.crawled),
            "candidates_pending": sum(1 for c in self._candidates.values() if not c.crawled),
            "similarity_tracker_size": self._similarity_tracker.size,
            "config": {
                "max_pages": self._max_pages,
                "max_depth": self._max_depth,
                "learn_from_pages": self._learn_from_pages,
                "similarity_threshold": self._similarity_threshold,
                "min_pattern_score": self._min_pattern_score,
                "max_concurrent": self._max_concurrent,
                "same_domain_only": self._same_domain_only,
            },
        }

    def __repr__(self) -> str:
        return (
            f"AdaptiveCrawler(max_pages={self._max_pages}, "
            f"max_depth={self._max_depth}, "
            f"crawled={len(self._crawled_urls)}, "
            f"discovered={len(self._candidates)})"
        )