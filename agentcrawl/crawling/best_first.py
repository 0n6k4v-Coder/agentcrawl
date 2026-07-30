"""
AgentCrawl — Best-First Crawler
===================================

Priority-based crawler that always explores the highest-scored
URL next, using a max-heap priority queue.

Unlike BFS (breadth-first) or DFS (depth-first), BestFirst
crawling selects the next URL based on a computed relevance
score, making it ideal for:
    - Finding the most relevant pages quickly
    - Crawling large sites with limited page budgets
    - Prioritizing content pages over navigation/boilerplate

Algorithm:
    1. Score the start URL and push to priority queue.
    2. Pop the highest-scored URL from the queue.
    3. Fetch the page and extract links.
    4. Score each discovered link.
    5. Push qualifying links to the priority queue.
    6. Repeat until max_pages or queue is empty.

Usage:
    from agentcrawl.crawling.best_first import BestFirstCrawler

    crawler = BestFirstCrawler(
        max_pages=50,
        max_depth=4,
        score_threshold=0.3,
    )

    # Discover URLs (highest priority first)
    urls = await crawler.discover("https://docs.example.com", engine)

    # Full crawl with results
    results = await crawler.crawl("https://docs.example.com", engine)

    # With custom scoring
    from agentcrawl.crawling.base import URLScorer
    scorer = URLScorer(
        content_keywords=["guide", "tutorial", "api"],
        noise_keywords=["login", "cart", "search"],
    )
    crawler = BestFirstCrawler(url_scorer=scorer, max_pages=100)
"""

from __future__ import annotations

import asyncio
import heapq
import logging
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.crawling.base import (
    CrawlConfig,
    CrawlStrategy,
    DiscoveredURL,
    URLFilter,
    URLScorer,
)

logger = logging.getLogger("agentcrawl.crawling.best_first")


# ══════════════════════════════════════════════════════════════
# Priority Queue Entry
# ══════════════════════════════════════════════════════════════

@dataclass(order=True)
class _PriorityEntry:
    """
    Internal priority queue entry.

    Uses negative score for max-heap behavior with heapq (min-heap).
    Ties are broken by discovery time (FIFO).
    """
    priority: float  # Negative score (lower = higher priority)
    sequence: int  # Tie-breaker (FIFO order)
    url: str = field(compare=False)
    depth: int = field(compare=False, default=0)
    source_url: str = field(compare=False, default="")
    link_text: str = field(compare=False, default="")
    score: float = field(compare=False, default=0.0)


# ══════════════════════════════════════════════════════════════
# Best-First Crawler
# ══════════════════════════════════════════════════════════════

class BestFirstCrawler(CrawlStrategy):
    """
    Priority-based crawler using a max-heap priority queue.

    Always explores the highest-scored URL next, making it
    efficient for finding relevant content within a limited
    page budget.

    Args:
        max_depth: Maximum link depth from start URL.
        max_pages: Maximum number of pages to crawl.
        max_concurrent: Maximum concurrent page fetches.
        score_threshold: Minimum URL score to enqueue.
        url_filter: URL filter instance.
        url_scorer: URL scorer instance.
        config: Full crawl configuration.
        decay_factor: Score decay per depth level (0.0 - 1.0).
        diversity_bonus: Bonus for exploring new URL patterns.
        allow_revisit: Whether to allow revisiting URLs at lower depth.

    Example:
        >>> crawler = BestFirstCrawler(
        ...     max_pages=50,
        ...     max_depth=4,
        ...     score_threshold=0.3,
        ... )
        >>> urls = await crawler.discover("https://docs.example.com", engine)
        >>> print(f"Discovered {len(urls)} URLs")
        >>> print(crawler.progress.to_dict())
    """

    strategy_name = "best_first"

    def __init__(
        self,
        max_depth: int = 3,
        max_pages: int = 50,
        max_concurrent: int = 3,
        score_threshold: float = 0.0,
        url_filter: URLFilter | None = None,
        url_scorer: URLScorer | None = None,
        config: CrawlConfig | None = None,
        decay_factor: float = 0.05,
        diversity_bonus: float = 0.05,
        allow_revisit: bool = False,
    ):
        super().__init__(
            max_depth=max_depth,
            max_pages=max_pages,
            url_filter=url_filter,
            url_scorer=url_scorer,
            config=config,
        )

        self._max_concurrent = max_concurrent
        self._score_threshold = score_threshold
        self._decay_factor = decay_factor
        self._diversity_bonus = diversity_bonus
        self._allow_revisit = allow_revisit

        # Priority queue (min-heap with negated scores)
        self._queue: list[_PriorityEntry] = []
        self._sequence: int = 0

        # Pattern tracking for diversity bonus
        self._seen_patterns: set[str] = set()

        # Crawl order tracking
        self._crawl_order: list[str] = []

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def queue_size(self) -> int:
        """Current priority queue size."""
        return len(self._queue)

    @property
    def crawl_order(self) -> list[str]:
        """URLs in the order they were crawled."""
        return list(self._crawl_order)

    @property
    def top_score(self) -> float:
        """Score of the highest-priority URL in the queue."""
        if self._queue:
            return -self._queue[0].priority
        return 0.0

    # ──────────────────────────────────────────────────────────
    # Core Discovery
    # ──────────────────────────────────────────────────────────

    async def _discover_urls(
        self,
        url: str,
        engine: Any,
    ) -> list[DiscoveredURL]:
        """
        Best-first URL discovery using priority queue.

        Args:
            url: Starting URL.
            engine: CrawlEngine instance.

        Returns:
            List of discovered URLs in priority order.
        """
        # Score and enqueue the start URL
        start_score = self._scorer.score(url, depth=0)
        self._enqueue(url, depth=0, score=start_score)

        # Main crawl loop
        pages_crawled = 0
        semaphore = asyncio.Semaphore(self._max_concurrent)

        while self._queue and pages_crawled < self._config.max_pages:
            # Get next batch of URLs to crawl
            batch = self._dequeue_batch(self._max_concurrent)
            if not batch:
                break

            # Crawl batch concurrently
            tasks = [
                self._crawl_entry(entry, engine, semaphore)
                for entry in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.debug("Batch crawl error: %s", result)
                    self._progress.pages_failed += 1
                    continue

                if isinstance(result, str):
                    pages_crawled += 1
                    self._crawl_order.append(result)

            # Rate limiting
            if self._config.delay_between_requests > 0:
                await asyncio.sleep(self._config.delay_between_requests)

        return list(self._discovered.values())

    async def _crawl_entry(
        self,
        entry: _PriorityEntry,
        engine: Any,
        semaphore: asyncio.Semaphore,
    ) -> str | None:
        """
        Crawl a single priority queue entry.

        Args:
            entry: Priority queue entry.
            engine: CrawlEngine instance.
            semaphore: Concurrency limiter.

        Returns:
            The crawled URL, or None if skipped/failed.
        """
        async with semaphore:
            url = entry.url
            depth = entry.depth

            # Check if already visited
            normalized = self._filter.normalize(url)
            if normalized in self._visited and not self._allow_revisit:
                return None

            # Check depth
            if depth > self._config.max_depth:
                self._progress.pages_skipped += 1
                return None

            # Check robots
            if not self._is_robots_allowed(url):
                self._progress.pages_skipped += 1
                return None

            # Fetch and extract links
            discovered = await self._fetch_links(url, engine, depth)

            if discovered is None:
                return None

            # Score and enqueue discovered URLs
            for disc_url in discovered:
                # Apply depth decay
                decayed_score = disc_url.score * (1.0 - self._decay_factor * disc_url.depth)

                # Apply diversity bonus
                pattern = self._extract_pattern(disc_url.url)
                if pattern not in self._seen_patterns:
                    decayed_score += self._diversity_bonus
                    self._seen_patterns.add(pattern)

                # Check threshold
                if decayed_score < self._score_threshold:
                    self._progress.pages_skipped += 1
                    continue

                # Enqueue
                self._enqueue(
                    url=disc_url.url,
                    depth=disc_url.depth,
                    score=decayed_score,
                    source_url=url,
                    link_text=disc_url.link_text,
                )

            return url

    # ──────────────────────────────────────────────────────────
    # Priority Queue Operations
    # ──────────────────────────────────────────────────────────

    def _enqueue(
        self,
        url: str,
        depth: int = 0,
        score: float = 0.5,
        source_url: str = "",
        link_text: str = "",
    ) -> None:
        """
        Add a URL to the priority queue.

        Args:
            url: URL to enqueue.
            depth: Link depth.
            score: Priority score.
            source_url: URL where this link was found.
            link_text: Anchor text.
        """
        normalized = self._filter.normalize(url)

        # Skip if already discovered (unless allow_revisit)
        if normalized in self._discovered and not self._allow_revisit:
            return

        # Create discovered URL record
        if normalized not in self._discovered:
            self._discovered[normalized] = DiscoveredURL(
                url=normalized,
                depth=depth,
                source_url=source_url,
                link_text=link_text,
                score=score,
            )

        # Push to priority queue (negate score for max-heap)
        entry = _PriorityEntry(
            priority=-score,
            sequence=self._sequence,
            url=normalized,
            depth=depth,
            source_url=source_url,
            link_text=link_text,
            score=score,
        )
        heapq.heappush(self._queue, entry)
        self._sequence += 1

    def _dequeue(self) -> _PriorityEntry | None:
        """
        Pop the highest-priority URL from the queue.

        Returns:
            PriorityEntry, or None if queue is empty.
        """
        while self._queue:
            entry = heapq.heappop(self._queue)

            # Skip already visited
            normalized = self._filter.normalize(entry.url)
            if normalized in self._visited and not self._allow_revisit:
                continue

            return entry

        return None

    def _dequeue_batch(self, count: int) -> list[_PriorityEntry]:
        """
        Pop up to `count` highest-priority URLs from the queue.

        Args:
            count: Maximum entries to dequeue.

        Returns:
            List of PriorityEntry objects.
        """
        batch: list[_PriorityEntry] = []
        for _ in range(count):
            entry = self._dequeue()
            if entry is None:
                break
            batch.append(entry)
        return batch

    # ──────────────────────────────────────────────────────────
    # Pattern Extraction
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_pattern(url: str) -> str:
        """
        Extract a structural pattern from a URL for diversity tracking.

        Args:
            url: URL to analyze.

        Returns:
            Pattern string (e.g., '/docs/{slug}', '/api/{version}/users').
        """
        try:
            from urllib.parse import urlparse
            path = urlparse(url).path.rstrip("/")
            segments = path.split("/")

            pattern_segments: list[str] = []
            for seg in segments:
                if not seg:
                    pattern_segments.append("")
                elif seg.isdigit():
                    pattern_segments.append("{num}")
                elif len(seg) > 15 and "-" in seg:
                    pattern_segments.append("{slug}")
                else:
                    pattern_segments.append(seg)

            return "/".join(pattern_segments) or "/"
        except Exception:
            return url

    # ──────────────────────────────────────────────────────────
    # Reset
    # ──────────────────────────────────────────────────────────

    def _reset(self) -> None:
        """Reset crawler state including priority queue."""
        super()._reset()
        self._queue.clear()
        self._sequence = 0
        self._seen_patterns.clear()
        self._crawl_order.clear()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics."""
        base = super().get_diagnostics()

        # Top 10 queued URLs
        top_queued = []
        temp_queue = list(self._queue)
        temp_queue.sort()
        for entry in temp_queue[:10]:
            top_queued.append({
                "url": entry.url,
                "score": entry.score,
                "depth": entry.depth,
            })

        base.update({
            "queue_size": len(self._queue),
            "top_score": self.top_score,
            "crawl_order_length": len(self._crawl_order),
            "seen_patterns": len(self._seen_patterns),
            "top_queued": top_queued,
            "config": {
                **base.get("config", {}),
                "max_concurrent": self._max_concurrent,
                "score_threshold": self._score_threshold,
                "decay_factor": self._decay_factor,
                "diversity_bonus": self._diversity_bonus,
                "allow_revisit": self._allow_revisit,
            },
        })

        return base

    def get_score_distribution(self) -> dict[str, int]:
        """
        Get the distribution of scores across discovered URLs.

        Returns:
            Dictionary mapping score ranges to counts.
        """
        ranges = {
            "0.0-0.2": 0,
            "0.2-0.4": 0,
            "0.4-0.6": 0,
            "0.6-0.8": 0,
            "0.8-1.0": 0,
        }

        for disc in self._discovered.values():
            s = disc.score
            if s < 0.2:
                ranges["0.0-0.2"] += 1
            elif s < 0.4:
                ranges["0.2-0.4"] += 1
            elif s < 0.6:
                ranges["0.4-0.6"] += 1
            elif s < 0.8:
                ranges["0.6-0.8"] += 1
            else:
                ranges["0.8-1.0"] += 1

        return ranges

    def __repr__(self) -> str:
        return (
            f"BestFirstCrawler(max_pages={self._config.max_pages}, "
            f"max_depth={self._config.max_depth}, "
            f"queue={len(self._queue)}, "
            f"visited={len(self._visited)}, "
            f"discovered={len(self._discovered)})"
        )
