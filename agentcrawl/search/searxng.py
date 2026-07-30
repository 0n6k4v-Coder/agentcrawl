"""
AgentCrawl — SearXNG Search Provider
=======================================

Search via a SearXNG metasearch instance. SearXNG is a free,
open-source metasearch engine that aggregates results from
multiple search engines (Google, Bing, DuckDuckGo, etc.)
without tracking.

Advantages:
    - No API key required (self-hosted)
    - Aggregates results from 70+ search engines
    - Privacy-focused (no tracking)
    - Configurable engine selection
    - JSON API for programmatic access

Prerequisites:
    A running SearXNG instance with JSON format enabled.
    Enable JSON in settings.yml:
        search:
            formats:
                - html
                - json

Usage:
    from agentcrawl.search.searxng import SearXNGProvider

    # Connect to a SearXNG instance
    provider = SearXNGProvider(
        base_url="http://localhost:8888",
    )
    results = await provider.search("python tutorial")

    # With specific engines
    provider = SearXNGProvider(
        base_url="https://searx.example.com",
        engines=["google", "bing", "duckduckgo"],
    )
    results = await provider.search("machine learning", max_results=20)

    # Search categories
    results = await provider.search(
        "python",
        categories="it",
        time_range="month",
    )
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from agentcrawl.search.engine import SearchProvider, SearchResult

logger = logging.getLogger("agentcrawl.search.searxng")


# ══════════════════════════════════════════════════════════════
# SearXNG Provider
# ══════════════════════════════════════════════════════════════


class SearXNGProvider(SearchProvider):
    """
    SearXNG metasearch provider.

    Queries a SearXNG instance's JSON API and parses the
    aggregated results.

    Args:
        base_url: SearXNG instance URL (e.g., 'http://localhost:8888').
        api_key: Optional API key (if instance requires authentication).
        engines: List of search engines to use (empty = all).
        categories: Search categories ('general', 'images', 'news',
                   'videos', 'it', 'science', 'files', 'music').
        language: Search language code.
        time_range: Time range filter ('day', 'week', 'month', 'year').
        safe_search: Safe search level (0=off, 1=moderate, 2=strict).
        timeout: HTTP request timeout (seconds).
        rate_limit_delay: Minimum delay between requests (seconds).

    Example:
        >>> provider = SearXNGProvider(
        ...     base_url="http://localhost:8888",
        ...     engines=["google", "bing"],
        ... )
        >>> results = await provider.search("python asyncio")
        >>> for r in results:
        ...     print(f"{r.title}: {r.url}")
    """

    name = "searxng"

    # Available search categories
    CATEGORIES: tuple[str, ...] = (
        "general",
        "images",
        "news",
        "videos",
        "it",
        "science",
        "files",
        "music",
        "map",
        "social media",
    )

    # Available time ranges
    TIME_RANGES: tuple[str, ...] = ("day", "week", "month", "year")

    def __init__(
        self,
        base_url: str = "http://localhost:8888",
        api_key: str = "",
        engines: list[str] | None = None,
        categories: str = "general",
        language: str = "en",
        time_range: str = "",
        safe_search: int = 0,
        timeout: float = 15.0,
        rate_limit_delay: float = 1.0,
        **kwargs: Any,
    ):
        super().__init__(api_key=api_key, **kwargs)

        # Normalize base URL
        self._base_url = base_url.rstrip("/")
        self._engines = engines or []
        self._categories = categories
        self._language = language
        self._time_range = time_range
        self._safe_search = safe_search
        self._timeout = timeout
        self._rate_limit_delay = rate_limit_delay

        self._last_request_time: float = 0.0
        self._total_requests: int = 0
        self._total_errors: int = 0

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def engines(self) -> list[str]:
        return list(self._engines)

    @property
    def total_requests(self) -> int:
        return self._total_requests

    # ──────────────────────────────────────────────────────────
    # Search API
    # ──────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 1,
        engines: list[str] | None = None,
        categories: str | None = None,
        time_range: str | None = None,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """
        Search via SearXNG JSON API.

        Args:
            query: Search query string.
            max_results: Maximum results to return.
            page: Page number (1-based).
            engines: Override engines for this search.
            categories: Override categories for this search.
            time_range: Override time range for this search.
            **kwargs: Additional parameters.

        Returns:
            List of SearchResult objects.
        """
        await self._rate_limit()

        import httpx

        # Build parameters
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "pageno": page,
            "language": self._language,
            "safesearch": self._safe_search,
        }

        # Engines
        search_engines = engines or self._engines
        if search_engines:
            params["engines"] = ",".join(search_engines)

        # Categories
        search_categories = categories or self._categories
        if search_categories:
            params["categories"] = search_categories

        # Time range
        search_time_range = time_range or self._time_range
        if search_time_range and search_time_range in self.TIME_RANGES:
            params["time_range"] = search_time_range

        # Headers
        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/search",
                    params=params,
                    headers=headers,
                )

                self._total_requests += 1

                if resp.status_code != 200:
                    self._total_errors += 1
                    logger.warning(
                        "SearXNG API error: %d — %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return []

                data = resp.json()
                return self._parse_response(data, max_results, page)

        except httpx.TimeoutException:
            self._total_errors += 1
            logger.warning("SearXNG request timed out")
            return []
        except Exception as e:
            self._total_errors += 1
            logger.warning("SearXNG search failed: %s", e)
            return []

    async def search_paginated(
        self,
        query: str,
        max_results: int = 50,
        page_size: int = 20,
    ) -> list[SearchResult]:
        """
        Search with pagination.

        Args:
            query: Search query.
            max_results: Total maximum results.
            page_size: Results per page.

        Returns:
            List of SearchResult objects.
        """
        all_results: list[SearchResult] = []
        page = 1

        while len(all_results) < max_results:
            results = await self.search(
                query=query,
                max_results=page_size,
                page=page,
            )

            if not results:
                break

            all_results.extend(results)
            page += 1

            if len(results) < page_size:
                break

        return all_results[:max_results]

    # ──────────────────────────────────────────────────────────
    # Response Parsing
    # ──────────────────────────────────────────────────────────

    def _parse_response(
        self,
        data: dict[str, Any],
        max_results: int,
        page: int,
    ) -> list[SearchResult]:
        """
        Parse SearXNG JSON API response.

        Args:
            data: JSON response dictionary.
            max_results: Maximum results to return.
            page: Current page number.

        Returns:
            List of SearchResult objects.
        """
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        raw_results = data.get("results", [])

        for i, item in enumerate(raw_results):
            if len(results) >= max_results:
                break

            url = item.get("url", "").strip()
            if not url:
                continue

            # Deduplicate
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = item.get("title", "").strip()
            snippet = item.get("content", "").strip()
            engine = item.get("engine", "")
            score = item.get("score", 0.0)
            published = item.get("publishedDate", "")
            category = item.get("category", "")

            # Extract domain
            domain = ""
            from urllib.parse import urlparse

            with contextlib.suppress(Exception):
                domain = urlparse(url).netloc.replace("www.", "")

            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    position=(page - 1) * max_results + i + 1,
                    domain=domain,
                    published_date=published,
                    score=float(score) if score else 0.0,
                    raw={
                        "engine": engine,
                        "category": category,
                        **item,
                    },
                )
            )

        return results

    # ──────────────────────────────────────────────────────────
    # Instance Management
    # ──────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """
        Check if the SearXNG instance is healthy.

        Returns:
            Health status dictionary.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Try the health endpoint
                resp = await client.get(f"{self._base_url}/healthz")
                if resp.status_code == 200:
                    return {"status": "healthy", "url": self._base_url}

                # Fallback: try the config endpoint
                resp = await client.get(f"{self._base_url}/config")
                if resp.status_code == 200:
                    config = resp.json()
                    return {
                        "status": "healthy",
                        "url": self._base_url,
                        "version": config.get("version", "unknown"),
                        "engines": len(config.get("engines", [])),
                    }

                return {
                    "status": "unhealthy",
                    "url": self._base_url,
                    "status_code": resp.status_code,
                }

        except Exception as e:
            return {
                "status": "unreachable",
                "url": self._base_url,
                "error": str(e),
            }

    async def get_config(self) -> dict[str, Any]:
        """
        Get the SearXNG instance configuration.

        Returns:
            Configuration dictionary.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}/config")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        return dict(data)
        except Exception as e:
            logger.warning("Failed to get SearXNG config: %s", e)

        return {}

    async def get_engines(self) -> list[dict[str, Any]]:
        """
        Get available search engines from the SearXNG instance.

        Returns:
            List of engine info dictionaries.
        """
        config = await self.get_config()
        engines = config.get("engines", [])

        return [
            {
                "name": e.get("name", ""),
                "shortcut": e.get("shortcut", ""),
                "categories": e.get("categories", []),
                "enabled": e.get("enabled", True),
            }
            for e in engines
        ]

    # ──────────────────────────────────────────────────────────
    # Rate Limiting
    # ──────────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "base_url": self._base_url,
            "engines": self._engines,
            "categories": self._categories,
            "language": self._language,
            "time_range": self._time_range,
            "safe_search": self._safe_search,
            "total_requests": self._total_requests,
            "total_errors": self._total_errors,
        }

    def __repr__(self) -> str:
        return (
            f"SearXNGProvider(url={self._base_url!r}, "
            f"engines={self._engines or 'all'}, "
            f"requests={self._total_requests})"
        )
