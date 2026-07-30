"""
AgentCrawl — Depth-First Search Crawler
===========================================

Depth-first crawler that explores as deep as possible along each
branch before backtracking. Ideal for:
    - Crawling deep documentation hierarchies
    - Following conversation threads or comment chains
    - Exploring nested category structures
    - Finding deep-linked content quickly

Algorithm:
    1. Push start URL onto the stack.
    2. Pop the top URL from the stack.
    3. Fetch the page and extract links.
    4. Push discovered links onto the stack (LIFO order).
    5. Repeat until max_pages, max_depth, or stack is empty.

    The LIFO nature of the stack ensures the most recently
    discovered URL is explored next, creating depth-first behavior.

Usage:
    from agentcrawl.crawling.dfs import DFSCrawler

    crawler = DFSCrawler(
        max_depth=5,
        max_pages=100,
    )

    # Discover URLs depth-first
    urls = await crawler.discover("https://docs.example.com", engine)

    # Full crawl with results
    results = await crawler.crawl("https://docs.example.com", engine)

    # Check exploration path
    print(crawler.current_path)
    print(crawler.max_depth_reached)

    # With backtracking limit
    crawler = DFSCrawler(
        max_depth=10,
        max_pages=200,
        max_backtracks=50,
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.crawling.base import (
    CrawlConfig,
    CrawlStrategy,
    DiscoveredURL,
    URLFilter,
    URLScorer,
)

logger = logging.getLogger("agentcrawl.crawling.dfs")


# ══════════════════════════════════════════════════════════════
# DFS Stack Entry
# ══════════════════════════════════════════════════════════════

@dataclass
class _DFSEntry:
    """Internal DFS stack entry."""
    url: str
    depth: int = 0
    source_url: str = ""
    link_text: str = ""
    score: float = 0.5
    pushed_at: float = field(default_factory=time.time)
    parent_path: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# DFS Crawler
# ══════════════════════════════════════════════════════════════

class DFSCrawler(CrawlStrategy):
    """
    Depth-first search crawler.

    Explores as deep as possible along each branch before
    backtracking. Uses a LIFO stack to ensure the most recently
    discovered URL is explored next.

    Args:
        max_depth: Maximum link depth from start URL.
        max_pages: Maximum number of pages to crawl.
        max_concurrent: Maximum concurrent page fetches.
        url_filter: URL filter instance.
        url_scorer: URL scorer instance.
        config: Full crawl configuration.
        max_backtracks: Maximum backtracking steps (0 = unlimited).
        push_order: Order to push discovered links ('first', 'last', 'score').
                    'first' = push in discovery order (last link explored first).
                    'last' = push in reverse order (first link explored first).
                    'score' = push by score (highest score explored first).
        prioritize_deep: Bonus score for deeper links.

    Example:
        >>> crawler = DFSCrawler(max_depth=5, max_pages=100)
        >>> urls = await crawler.discover("https://docs.example.com", engine)
        >>> print(f"Max depth reached: {crawler.max_depth_reached}")
        >>> print(f"Backtracks: {crawler.backtrack_count}")
    """

    strategy_name = "dfs"

    def __init__(
        self,
        max_depth: int = 3,
        max_pages: int = 50,
        max_concurrent: int = 1,
        url_filter: URLFilter | None = None,
        url_scorer: URLScorer | None = None,
        config: CrawlConfig | None = None,
        max_backtracks: int = 0,
        push_order: str = "score",
        prioritize_deep: bool = True,
    ):
        super().__init__(
            max_depth=max_depth,
            max_pages=max_pages,
            url_filter=url_filter,
            url_scorer=url_scorer,
            config=config,
        )

        self._max_concurrent = max_concurrent
        self._max_backtracks = max_backtracks
        self._push_order = push_order
        self._prioritize_deep = prioritize_deep

        # DFS stack (LIFO)
        self._stack: list[_DFSEntry] = []

        # Path tracking
        self._current_path: list[str] = []
        self._max_depth_reached: int = 0
        self._backtrack_count: int = 0

        # Depth distribution
        self._depth_stats: dict[int, int] = {}

        # Crawl order
        self._crawl_order: list[str] = []

        # Branch tracking
        self._branches_explored: int = 0
        self._deepest_path: list[str] = []

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def stack_size(self) -> int:
        """Current DFS stack size."""
        return len(self._stack)

    @property
    def current_path(self) -> list[str]:
        """Current exploration path (URLs from root to current)."""
        return list(self._current_path)

    @property
    def max_depth_reached(self) -> int:
        """Maximum depth reached during crawl."""
        return self._max_depth_reached

    @property
    def backtrack_count(self) -> int:
        """Number of backtracking steps taken."""
        return self._backtrack_count

    @property
    def branches_explored(self) -> int:
        """Number of branches explored."""
        return self._branches_explored

    @property
    def deepest_path(self) -> list[str]:
        """The deepest exploration path found."""
        return list(self._deepest_path)

    @property
    def depth_stats(self) -> dict[int, int]:
        """Pages crawled per depth level."""
        return dict(self._depth_stats)

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
        DFS URL discovery using a LIFO stack.

        Args:
            url: Starting URL.
            engine: CrawlEngine instance.

        Returns:
            List of discovered URLs in DFS order.
        """
        # Push start URL
        start_score = self._scorer.score(url, depth=0)
        self._push(url, depth=0, score=start_score)

        pages_crawled = 0
        semaphore = asyncio.Semaphore(self._max_concurrent)

        while self._stack and pages_crawled < self._config.max_pages:
            # Check backtrack limit
            if self._max_backtracks > 0 and self._backtrack_count >= self._max_backtracks:
                logger.info(
                    "Backtrack limit reached (%d), stopping DFS",
                    self._max_backtracks,
                )
                break

            # Pop next entry from stack
            entry = self._pop()
            if entry is None:
                break

            # Update current path
            self._update_path(entry)

            # Crawl the entry
            result = await self._crawl_entry(entry, engine, semaphore)

            if result:
                pages_crawled += 1
                self._crawl_order.append(result)

                # Track depth stats
                depth = entry.depth
                self._depth_stats[depth] = self._depth_stats.get(depth, 0) + 1
                self._max_depth_reached = max(self._max_depth_reached, depth)

                # Track deepest path
                if len(entry.parent_path) + 1 > len(self._deepest_path):
                    self._deepest_path = [*entry.parent_path, entry.url]

            # Rate limiting
            if self._config.delay_between_requests > 0:
                await asyncio.sleep(self._config.delay_between_requests)

        return list(self._discovered.values())

    async def _crawl_entry(
        self,
        entry: _DFSEntry,
        engine: Any,
        semaphore: asyncio.Semaphore,
    ) -> str | None:
        """
        Crawl a single DFS stack entry.

        Args:
            entry: DFS stack entry.
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
                self._backtrack_count += 1
                return None

            # Check robots
            if not self._is_robots_allowed(url):
                self._progress.pages_skipped += 1
                return None

            # Fetch and extract links
            discovered = await self._fetch_links(url, engine, depth)

            if discovered is None:
                self._backtrack_count += 1
                return None

            # Push discovered URLs onto stack
            if discovered:
                self._branches_explored += 1

                # Sort before pushing based on push_order
                if self._push_order == "score":
                    discovered.sort(key=lambda d: d.score, reverse=True)
                elif self._push_order == "last":
                    discovered.reverse()
                # 'first' = natural order (last pushed = first popped)

                for disc_url in discovered:
                    if disc_url.depth <= self._config.max_depth:
                        # Apply depth priority bonus
                        score = disc_url.score
                        if self._prioritize_deep:
                            score += 0.02 * disc_url.depth

                        self._push(
                            url=disc_url.url,
                            depth=disc_url.depth,
                            score=score,
                            source_url=url,
                            link_text=disc_url.link_text,
                            parent_path=[*entry.parent_path, url],
                        )
            else:
                # Leaf node — backtrack
                self._backtrack_count += 1

            return url

    # ──────────────────────────────────────────────────────────
    # Stack Operations
    # ──────────────────────────────────────────────────────────

    def _push(
        self,
        url: str,
        depth: int = 0,
        score: float = 0.5,
        source_url: str = "",
        link_text: str = "",
        parent_path: list[str] | None = None,
    ) -> None:
        """
        Push a URL onto the DFS stack.

        Args:
            url: URL to push.
            depth: Link depth.
            score: URL score.
            source_url: Source URL.
            link_text: Anchor text.
            parent_path: Path from root to parent.
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

        # Push to stack
        entry = _DFSEntry(
            url=normalized,
            depth=depth,
            source_url=source_url,
            link_text=link_text,
            score=score,
            parent_path=parent_path or [],
        )
        self._stack.append(entry)

    def _pop(self) -> _DFSEntry | None:
        """
        Pop the top entry from the DFS stack.

        Skips already-visited URLs.

        Returns:
            DFSEntry, or None if stack is empty.
        """
        while self._stack:
            entry = self._stack.pop()

            # Skip visited
            normalized = self._filter.normalize(entry.url)
            if normalized in self._visited:
                continue

            return entry

        return None

    def _update_path(self, entry: _DFSEntry) -> None:
        """Update the current exploration path."""
        self._current_path = [*entry.parent_path, entry.url]

    # ──────────────────────────────────────────────────────────
    # Reset
    # ──────────────────────────────────────────────────────────

    def _reset(self) -> None:
        """Reset crawler state including DFS stack."""
        super()._reset()
        self._stack.clear()
        self._current_path.clear()
        self._max_depth_reached = 0
        self._backtrack_count = 0
        self._depth_stats.clear()
        self._crawl_order.clear()
        self._branches_explored = 0
        self._deepest_path.clear()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics."""
        base = super().get_diagnostics()

        # Stack depth distribution
        stack_depths: dict[int, int] = {}
        for entry in self._stack:
            stack_depths[entry.depth] = stack_depths.get(entry.depth, 0) + 1

        base.update({
            "stack_size": len(self._stack),
            "max_depth_reached": self._max_depth_reached,
            "backtrack_count": self._backtrack_count,
            "branches_explored": self._branches_explored,
            "depth_stats": self._depth_stats,
            "stack_depth_distribution": stack_depths,
            "current_path_length": len(self._current_path),
            "deepest_path_length": len(self._deepest_path),
            "deepest_path": self._deepest_path[:10],
            "crawl_order_length": len(self._crawl_order),
            "config": {
                **base.get("config", {}),
                "max_concurrent": self._max_concurrent,
                "max_backtracks": self._max_backtracks,
                "push_order": self._push_order,
                "prioritize_deep": self._prioritize_deep,
            },
        })

        return base

    def get_path_summary(self) -> str:
        """
        Get a human-readable summary of the exploration.

        Returns:
            Multi-line summary string.
        """
        lines = [f"DFS Crawl Summary ({self.strategy_name}):"]
        lines.append(f"  Max depth reached: {self._max_depth_reached}")
        lines.append(f"  Backtracks: {self._backtrack_count}")
        lines.append(f"  Branches explored: {self._branches_explored}")
        lines.append(f"  Total crawled: {sum(self._depth_stats.values())}")
        lines.append(f"  Total discovered: {len(self._discovered)}")
        lines.append("")

        if self._deepest_path:
            lines.append(f"  Deepest path ({len(self._deepest_path)} levels):")
            for i, url in enumerate(self._deepest_path[:10]):
                indent = "    " + "  " * i
                # Truncate URL for display
                display_url = url if len(url) <= 80 else url[:77] + "..."
                lines.append(f"{indent}→ {display_url}")
            if len(self._deepest_path) > 10:
                lines.append(f"    ... ({len(self._deepest_path) - 10} more)")

        lines.append("")
        lines.append("  Depth | Crawled")
        lines.append("  ------|--------")
        for depth in sorted(self._depth_stats.keys()):
            count = self._depth_stats[depth]
            lines.append(f"  {depth:>5} | {count:>7}")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"DFSCrawler(max_depth={self._config.max_depth}, "
            f"max_pages={self._config.max_pages}, "
            f"stack={len(self._stack)}, "
            f"visited={len(self._visited)}, "
            f"depth={self._max_depth_reached}, "
            f"backtracks={self._backtrack_count})"
        )
