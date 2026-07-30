"""
AgentCrawl — Breadth-First Search Crawler
=============================================

Level-by-level crawler that explores all pages at depth N before
moving to depth N+1. Ideal for:
    - Crawling documentation sites (shallow, wide structure)
    - Discovering the overall site structure quickly
    - Ensuring no section is missed at shallow depths
    - Balanced exploration across all site sections

Algorithm:
    Level 0: [start_url]
    Level 1: [all links from start_url]
    Level 2: [all links from level 1 pages]
    ...
    Level N: [all links from level N-1 pages]

    Stops when:
        - max_depth reached
        - max_pages reached
        - no more URLs to explore

Usage:
    from agentcrawl.crawling.bfs import BFSCrawler

    crawler = BFSCrawler(
        max_depth=3,
        max_pages=100,
        max_concurrent=5,
    )

    # Discover URLs level by level
    urls = await crawler.discover("https://docs.example.com", engine)

    # Full crawl with results
    results = await crawler.crawl("https://docs.example.com", engine)

    # Check level statistics
    print(crawler.level_stats)
    # {0: 1, 1: 15, 2: 42, 3: 38}

    # With URL filtering
    from agentcrawl.crawling.base import URLFilter
    url_filter = URLFilter(
        include_patterns=["/docs/*", "/api/*"],
        exclude_patterns=["/blog/*"],
    )
    crawler = BFSCrawler(url_filter=url_filter, max_depth=4)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.crawling.base import (
    CrawlConfig,
    CrawlStrategy,
    DiscoveredURL,
    URLFilter,
    URLScorer,
)

logger = logging.getLogger("agentcrawl.crawling.bfs")


# ══════════════════════════════════════════════════════════════
# BFS Queue Entry
# ══════════════════════════════════════════════════════════════


@dataclass
class _BFSEntry:
    """Internal BFS queue entry."""

    url: str
    depth: int = 0
    source_url: str = ""
    link_text: str = ""
    score: float = 0.5
    enqueued_at: float = field(default_factory=time.time)


# ══════════════════════════════════════════════════════════════
# BFS Crawler
# ══════════════════════════════════════════════════════════════


class BFSCrawler(CrawlStrategy):
    """
    Breadth-first search crawler.

    Explores all pages at the current depth level before moving
    to the next level. Processes URLs in FIFO order within each
    level, with optional concurrent fetching.

    Args:
        max_depth: Maximum link depth from start URL.
        max_pages: Maximum number of pages to crawl.
        max_concurrent: Maximum concurrent page fetches per level.
        url_filter: URL filter instance.
        url_scorer: URL scorer instance.
        config: Full crawl configuration.
        process_per_level: Whether to process one level at a time
                          (True) or use a continuous queue (False).
        sort_by_score: Sort URLs within a level by score (descending).

    Example:
        >>> crawler = BFSCrawler(max_depth=3, max_pages=100)
        >>> urls = await crawler.discover("https://docs.example.com", engine)
        >>> print(f"Discovered {len(urls)} URLs across {crawler.max_level_reached} levels")
        >>> print(crawler.level_stats)
    """

    strategy_name = "bfs"

    def __init__(
        self,
        max_depth: int = 3,
        max_pages: int = 50,
        max_concurrent: int = 5,
        url_filter: URLFilter | None = None,
        url_scorer: URLScorer | None = None,
        config: CrawlConfig | None = None,
        process_per_level: bool = True,
        sort_by_score: bool = False,
    ):
        super().__init__(
            max_depth=max_depth,
            max_pages=max_pages,
            max_concurrent=max_concurrent,
            url_filter=url_filter,
            url_scorer=url_scorer,
            config=config,
        )

        self._max_concurrent = max_concurrent
        self._process_per_level = process_per_level
        self._sort_by_score = sort_by_score

        # BFS queue (FIFO)
        self._queue: deque[_BFSEntry] = deque()

        # Level tracking
        self._level_stats: dict[int, int] = {}  # depth → pages crawled
        self._level_discovered: dict[int, int] = {}  # depth → URLs discovered
        self._max_level_reached: int = 0

        # Crawl order
        self._crawl_order: list[str] = []

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def queue_size(self) -> int:
        """Current BFS queue size."""
        return len(self._queue)

    @property
    def level_stats(self) -> dict[int, int]:
        """Pages crawled per depth level."""
        return dict(self._level_stats)

    @property
    def level_discovered(self) -> dict[int, int]:
        """URLs discovered per depth level."""
        return dict(self._level_discovered)

    @property
    def max_level_reached(self) -> int:
        """Maximum depth level reached during crawl."""
        return self._max_level_reached

    @property
    def crawl_order(self) -> list[str]:
        """URLs in the order they were crawled."""
        return list(self._crawl_order)

    # ──────────────────────────────────────────────────────────
    # Core Discovery
    # ──────────────────────────────────────────────────────────

    async def _discover_urls(
        self,
        url: str,
        engine: Any,
    ) -> list[DiscoveredURL]:
        """
        BFS URL discovery.

        Args:
            url: Starting URL.
            engine: CrawlEngine instance.

        Returns:
            List of discovered URLs in BFS order.
        """
        # Enqueue start URL
        start_score = self._scorer.score(url, depth=0)
        self._enqueue(url, depth=0, score=start_score)

        if self._process_per_level:
            await self._discover_per_level(engine)
        else:
            await self._discover_continuous(engine)

        return list(self._discovered.values())

    async def _discover_per_level(self, engine: Any) -> None:
        """
        Process one depth level at a time.

        Ensures all pages at depth N are crawled before moving
        to depth N+1.
        """
        pages_crawled = 0

        for depth in range(self._config.max_depth + 1):
            if pages_crawled >= self._config.max_pages:
                break

            # Collect all entries at current depth
            level_entries: list[_BFSEntry] = []
            remaining: deque[_BFSEntry] = deque()

            while self._queue:
                entry = self._queue.popleft()
                if entry.depth == depth:
                    level_entries.append(entry)
                else:
                    remaining.append(entry)

            # Put back entries from deeper levels
            self._queue = remaining

            if not level_entries:
                # No more entries at this level — check if deeper levels exist
                if self._queue:
                    continue
                break

            # Sort by score if configured
            if self._sort_by_score:
                level_entries.sort(key=lambda e: e.score, reverse=True)

            # Limit to remaining page budget
            budget = self._config.max_pages - pages_crawled
            level_entries = level_entries[:budget]

            logger.debug(
                "BFS Level %d: processing %d URLs",
                depth,
                len(level_entries),
            )

            # Crawl level concurrently
            semaphore = asyncio.Semaphore(self._max_concurrent)
            tasks = [self._crawl_entry(entry, engine, semaphore) for entry in level_entries]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            level_crawled = 0
            for result in results:
                if isinstance(result, Exception):
                    logger.debug("Level %d crawl error: %s", depth, result)
                    self._progress.pages_failed += 1
                    continue
                if isinstance(result, str):
                    level_crawled += 1
                    pages_crawled += 1
                    self._crawl_order.append(result)

            # Record level stats
            self._level_stats[depth] = level_crawled
            self._max_level_reached = max(self._max_level_reached, depth)

            logger.debug(
                "BFS Level %d complete: %d crawled, %d in queue",
                depth,
                level_crawled,
                len(self._queue),
            )

            # Rate limiting between levels
            if self._config.delay_between_requests > 0:
                await asyncio.sleep(self._config.delay_between_requests)

    async def _discover_continuous(self, engine: Any) -> None:
        """
        Continuous BFS using a single FIFO queue.

        Processes URLs as they are dequeued without waiting
        for the entire level to complete.
        """
        pages_crawled = 0
        semaphore = asyncio.Semaphore(self._max_concurrent)

        while self._queue and pages_crawled < self._config.max_pages:
            # Dequeue a batch
            batch: list[_BFSEntry] = []
            for _ in range(self._max_concurrent):
                if not self._queue:
                    break
                entry = self._queue.popleft()

                # Skip visited
                normalized = self._filter.normalize(entry.url)
                if normalized in self._visited:
                    continue

                batch.append(entry)

            if not batch:
                continue

            # Crawl batch concurrently
            tasks = [self._crawl_entry(entry, engine, semaphore) for entry in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._progress.pages_failed += 1
                    continue
                if isinstance(result, str):
                    pages_crawled += 1
                    self._crawl_order.append(result)
                    depth = batch[i].depth
                    self._level_stats[depth] = self._level_stats.get(depth, 0) + 1
                    self._max_level_reached = max(self._max_level_reached, depth)

            # Rate limiting
            if self._config.delay_between_requests > 0:
                await asyncio.sleep(self._config.delay_between_requests)

    async def _crawl_entry(
        self,
        entry: _BFSEntry,
        engine: Any,
        semaphore: asyncio.Semaphore,
    ) -> str | None:
        """
        Crawl a single BFS queue entry.

        Args:
            entry: BFS queue entry.
            engine: CrawlEngine instance.
            semaphore: Concurrency limiter.

        Returns:
            The crawled URL, or None if skipped/failed.
        """
        async with semaphore:
            url = entry.url
            depth = entry.depth

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

            # Enqueue discovered URLs
            for disc_url in discovered:
                if disc_url.depth <= self._config.max_depth:
                    self._enqueue(
                        url=disc_url.url,
                        depth=disc_url.depth,
                        score=disc_url.score,
                        source_url=url,
                        link_text=disc_url.link_text,
                    )

                    # Track level discovery stats
                    self._level_discovered[disc_url.depth] = (
                        self._level_discovered.get(disc_url.depth, 0) + 1
                    )

            return url

    # ──────────────────────────────────────────────────────────
    # Queue Operations
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
        Add a URL to the BFS queue.

        Args:
            url: URL to enqueue.
            depth: Link depth.
            score: URL score.
            source_url: Source URL.
            link_text: Anchor text.
        """
        normalized = self._filter.normalize(url)

        # Skip if already discovered
        if normalized in self._discovered:
            return

        # Record discovery
        self._discovered[normalized] = DiscoveredURL(
            url=normalized,
            depth=depth,
            source_url=source_url,
            link_text=link_text,
            score=score,
        )

        # Add to queue
        entry = _BFSEntry(
            url=normalized,
            depth=depth,
            source_url=source_url,
            link_text=link_text,
            score=score,
        )
        self._queue.append(entry)

    # ──────────────────────────────────────────────────────────
    # Reset
    # ──────────────────────────────────────────────────────────

    def _reset(self) -> None:
        """Reset crawler state including BFS queue."""
        super()._reset()
        self._queue.clear()
        self._level_stats.clear()
        self._level_discovered.clear()
        self._max_level_reached = 0
        self._crawl_order.clear()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics."""
        base = super().get_diagnostics()

        # Queue depth distribution
        queue_depths: dict[int, int] = {}
        for entry in self._queue:
            queue_depths[entry.depth] = queue_depths.get(entry.depth, 0) + 1

        base.update(
            {
                "queue_size": len(self._queue),
                "max_level_reached": self._max_level_reached,
                "level_stats": self._level_stats,
                "level_discovered": self._level_discovered,
                "queue_depth_distribution": queue_depths,
                "crawl_order_length": len(self._crawl_order),
                "config": {
                    **base.get("config", {}),
                    "max_concurrent": self._max_concurrent,
                    "process_per_level": self._process_per_level,
                    "sort_by_score": self._sort_by_score,
                },
            }
        )

        return base

    def get_level_summary(self) -> str:
        """
        Get a human-readable summary of level statistics.

        Returns:
            Multi-line summary string.
        """
        lines = [f"BFS Crawl Summary ({self.strategy_name}):"]
        lines.append(f"  Max level reached: {self._max_level_reached}")
        lines.append(f"  Total crawled: {sum(self._level_stats.values())}")
        lines.append(f"  Total discovered: {len(self._discovered)}")
        lines.append("")
        lines.append("  Level | Crawled | Discovered")
        lines.append("  ------|---------|----------")

        for depth in range(self._max_level_reached + 1):
            crawled = self._level_stats.get(depth, 0)
            discovered = self._level_discovered.get(depth, 0)
            lines.append(f"  {depth:>5} | {crawled:>7} | {discovered:>10}")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"BFSCrawler(max_depth={self._config.max_depth}, "
            f"max_pages={self._config.max_pages}, "
            f"queue={len(self._queue)}, "
            f"visited={len(self._visited)}, "
            f"levels={self._max_level_reached})"
        )
