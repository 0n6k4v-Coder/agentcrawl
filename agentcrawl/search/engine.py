"""
AgentCrawl — Search Engine
==============================

Web search integration with multiple provider support. Searches
the web and optionally scrapes result pages for full content.

Supported Providers:
    - DuckDuckGo (default, no API key required)
    - Google (via SerpAPI or custom endpoint)
    - Bing (via Azure API)
    - Brave Search API
    - Tavily API
    - Exa API

Usage:
    from agentcrawl.search.engine import SearchEngine

    engine = SearchEngine(provider="duckduckgo")

    # Basic search
    results = await engine.search("python asyncio tutorial")
    for r in results:
        print(f"{r['title']}: {r['url']}")

    # With options
    results = await engine.search(
        query="machine learning",
        max_results=10,
        include_answer=True,
    )

    # Search and scrape
    engine = SearchEngine(provider="tavily", api_key="...")
    results = await engine.search_and_scrape(
        query="python web scraping",
        max_results=5,
        crawl_engine=crawl_engine,
    )
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.search")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class SearchResult:
    """
    A single search result.

    Attributes:
        url: Result URL.
        title: Page title.
        snippet: Text snippet/description.
        position: Result position (1-based).
        domain: Extracted domain.
        published_date: Publication date (if available).
        score: Relevance score (provider-specific).
        raw: Raw result data from the provider.
    """

    url: str = ""
    title: str = ""
    snippet: str = ""
    position: int = 0
    domain: str = ""
    published_date: str = ""
    score: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.domain and self.url:
            from urllib.parse import urlparse

            with contextlib.suppress(Exception):
                self.domain = urlparse(self.url).netloc.replace("www.", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "position": self.position,
            "domain": self.domain,
            "published_date": self.published_date,
            "score": self.score,
        }


@dataclass
class SearchResponse:
    """
    Complete search response with metadata.

    Attributes:
        query: The search query.
        results: List of search results.
        total_results: Total results reported by provider.
        answer: Direct answer (if available).
        provider: Search provider used.
        duration_ms: Search duration in milliseconds.
        error: Error message (if failed).
    """

    query: str = ""
    results: list[SearchResult] = field(default_factory=list)
    total_results: int = 0
    answer: str = ""
    provider: str = ""
    duration_ms: float = 0.0
    error: str | None = None

    @property
    def result_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results,
            "answer": self.answer,
            "provider": self.provider,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
        }


# ══════════════════════════════════════════════════════════════
# Search Providers
# ══════════════════════════════════════════════════════════════


class SearchProvider:
    """Base class for search providers."""

    name: str = "base"

    def __init__(self, api_key: str = "", **kwargs: Any):
        self._api_key = api_key

    async def search(
        self,
        query: str,
        max_results: int = 10,
        **kwargs: Any,
    ) -> list[SearchResult]:
        raise NotImplementedError


class DuckDuckGoProvider(SearchProvider):
    """
    DuckDuckGo search provider (no API key required).

    Uses the DuckDuckGo HTML search endpoint.
    """

    name = "duckduckgo"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        **kwargs: Any,
    ) -> list[SearchResult]:
        import httpx

        results: list[SearchResult] = []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; AgentCrawl/1.0)",
                    },
                )

                if resp.status_code != 200:
                    return results

                # Parse HTML results
                import re

                # Find result blocks
                result_pattern = re.compile(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                    r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                    re.DOTALL,
                )

                for i, match in enumerate(result_pattern.finditer(resp.text)):
                    if i >= max_results:
                        break

                    url = match.group(1).strip()
                    title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
                    snippet = re.sub(r"<[^>]+>", "", match.group(3)).strip()

                    # DuckDuckGo wraps URLs in a redirect
                    if "uddg=" in url:
                        from urllib.parse import parse_qs, urlparse

                        parsed = urlparse(url)
                        params = parse_qs(parsed.query)
                        if "uddg" in params:
                            url = params["uddg"][0]

                    results.append(
                        SearchResult(
                            url=url,
                            title=title,
                            snippet=snippet,
                            position=i + 1,
                        )
                    )

        except Exception as e:
            logger.warning("DuckDuckGo search failed: %s", e)

        return results


class TavilyProvider(SearchProvider):
    """
    Tavily search provider (requires API key).

    Tavily is optimized for AI agents with clean, structured results.
    """

    name = "tavily"

    def __init__(self, api_key: str = "", **kwargs: Any):
        super().__init__(api_key, **kwargs)
        self._base_url = "https://api.tavily.com"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        include_answer: bool = False,
        search_depth: str = "basic",
        **kwargs: Any,
    ) -> list[SearchResult]:
        import httpx

        if not self._api_key:
            raise ValueError("Tavily API key required")

        results: list[SearchResult] = []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._base_url}/search",
                    json={
                        "api_key": self._api_key,
                        "query": query,
                        "max_results": max_results,
                        "include_answer": include_answer,
                        "search_depth": search_depth,
                    },
                )

                if resp.status_code != 200:
                    logger.warning("Tavily API error: %d", resp.status_code)
                    return results

                data = resp.json()

                for i, item in enumerate(data.get("results", [])):
                    results.append(
                        SearchResult(
                            url=item.get("url", ""),
                            title=item.get("title", ""),
                            snippet=item.get("content", ""),
                            position=i + 1,
                            score=item.get("score", 0.0),
                            raw=item,
                        )
                    )

        except Exception as e:
            logger.warning("Tavily search failed: %s", e)

        return results


class BraveProvider(SearchProvider):
    """
    Brave Search API provider (requires API key).
    """

    name = "brave"

    def __init__(self, api_key: str = "", **kwargs: Any):
        super().__init__(api_key, **kwargs)
        self._base_url = "https://api.search.brave.com/res/v1/web/search"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        **kwargs: Any,
    ) -> list[SearchResult]:
        import httpx

        if not self._api_key:
            raise ValueError("Brave API key required")

        results: list[SearchResult] = []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    self._base_url,
                    params={"q": query, "count": max_results},
                    headers={
                        "X-Subscription-Token": self._api_key,
                        "Accept": "application/json",
                    },
                )

                if resp.status_code != 200:
                    return results

                data = resp.json()

                for i, item in enumerate(data.get("web", {}).get("results", [])):
                    results.append(
                        SearchResult(
                            url=item.get("url", ""),
                            title=item.get("title", ""),
                            snippet=item.get("description", ""),
                            position=i + 1,
                            published_date=item.get("age", ""),
                            raw=item,
                        )
                    )

        except Exception as e:
            logger.warning("Brave search failed: %s", e)

        return results


class ExaProvider(SearchProvider):
    """
    Exa (formerly Metaphor) search provider (requires API key).

    Neural/semantic search optimized for AI applications.
    """

    name = "exa"

    def __init__(self, api_key: str = "", **kwargs: Any):
        super().__init__(api_key, **kwargs)
        self._base_url = "https://api.exa.ai"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_type: str = "neural",
        **kwargs: Any,
    ) -> list[SearchResult]:
        import httpx

        if not self._api_key:
            raise ValueError("Exa API key required")

        results: list[SearchResult] = []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._base_url}/search",
                    json={
                        "query": query,
                        "numResults": max_results,
                        "type": search_type,
                        "useAutoprompt": True,
                    },
                    headers={
                        "x-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                )

                if resp.status_code != 200:
                    return results

                data = resp.json()

                for i, item in enumerate(data.get("results", [])):
                    results.append(
                        SearchResult(
                            url=item.get("url", ""),
                            title=item.get("title", ""),
                            snippet=item.get("text", "")[:300],
                            position=i + 1,
                            score=item.get("score", 0.0),
                            published_date=item.get("publishedDate", ""),
                            raw=item,
                        )
                    )

        except Exception as e:
            logger.warning("Exa search failed: %s", e)

        return results


# ══════════════════════════════════════════════════════════════
# Provider Registry
# ══════════════════════════════════════════════════════════════

PROVIDERS: dict[str, type[SearchProvider]] = {
    "duckduckgo": DuckDuckGoProvider,
    "tavily": TavilyProvider,
    "brave": BraveProvider,
    "exa": ExaProvider,
}


# ══════════════════════════════════════════════════════════════
# Search Engine
# ══════════════════════════════════════════════════════════════


class SearchEngine:
    """
    Web search engine with multiple provider support.

    Args:
        provider: Search provider name ('duckduckgo', 'tavily', 'brave', 'exa').
        api_key: API key for the provider (if required).
        default_max_results: Default maximum results per search.
        timeout: Search timeout in seconds.
        rate_limit_delay: Minimum delay between searches (seconds).

    Example:
        >>> engine = SearchEngine(provider="duckduckgo")
        >>> results = await engine.search("python tutorial")
        >>> for r in results:
        ...     print(f"{r.title}: {r.url}")
    """

    def __init__(
        self,
        provider: str = "duckduckgo",
        api_key: str = "",
        default_max_results: int = 10,
        timeout: float = 30.0,
        rate_limit_delay: float = 1.0,
    ):
        self._provider_name = provider.lower().strip()
        self._api_key = api_key
        self._default_max_results = default_max_results
        self._timeout = timeout
        self._rate_limit_delay = rate_limit_delay

        # Initialize provider
        provider_cls = PROVIDERS.get(self._provider_name)
        if provider_cls is None:
            raise ValueError(
                f"Unknown search provider: '{provider}'. "
                f"Available: {', '.join(sorted(PROVIDERS.keys()))}"
            )

        self._provider = provider_cls(api_key=api_key)

        # Stats
        self._total_searches: int = 0
        self._total_results: int = 0
        self._last_search_time: float = 0.0

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def total_searches(self) -> int:
        return self._total_searches

    # ──────────────────────────────────────────────────────────
    # Search API
    # ──────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Search the web and return results.

        Args:
            query: Search query string.
            max_results: Maximum results (uses default if None).
            **kwargs: Provider-specific options.

        Returns:
            List of result dictionaries.
        """
        max_results = max_results or self._default_max_results

        # Rate limiting
        elapsed = time.time() - self._last_search_time
        if elapsed < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - elapsed)

        self._last_search_time = time.time()
        start = time.perf_counter()

        try:
            results = await asyncio.wait_for(
                self._provider.search(
                    query=query,
                    max_results=max_results,
                    **kwargs,
                ),
                timeout=self._timeout,
            )

            duration = (time.perf_counter() - start) * 1000
            self._total_searches += 1
            self._total_results += len(results)

            logger.info(
                "Search '%s': %d results in %.0fms (%s)",
                query[:50],
                len(results),
                duration,
                self._provider_name,
            )

            return [r.to_dict() for r in results]

        except asyncio.TimeoutError:
            logger.warning("Search timed out: '%s'", query[:50])
            return []
        except Exception as e:
            logger.warning("Search failed: '%s' — %s", query[:50], e)
            return []

    async def search_with_response(
        self,
        query: str,
        max_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        """
        Search and return a full SearchResponse with metadata.

        Args:
            query: Search query.
            max_results: Maximum results.
            **kwargs: Provider-specific options.

        Returns:
            SearchResponse object.
        """
        max_results = max_results or self._default_max_results
        start = time.perf_counter()

        try:
            results = await asyncio.wait_for(
                self._provider.search(
                    query=query,
                    max_results=max_results,
                    **kwargs,
                ),
                timeout=self._timeout,
            )

            duration = (time.perf_counter() - start) * 1000
            self._total_searches += 1
            self._total_results += len(results)

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider=self._provider_name,
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return SearchResponse(
                query=query,
                provider=self._provider_name,
                duration_ms=duration,
                error=str(e),
            )

    async def search_and_scrape(
        self,
        query: str,
        max_results: int = 5,
        crawl_engine: Any = None,
        config: Any = None,
        **kwargs: Any,
    ) -> list[Any]:
        """
        Search the web and scrape each result page.

        Args:
            query: Search query.
            max_results: Maximum search results to scrape.
            crawl_engine: CrawlEngine instance for scraping.
            config: CrawlerConfig for scraping.
            **kwargs: Provider-specific search options.

        Returns:
            List of CrawlResult objects.
        """
        # Search
        search_results = await self.search(
            query=query,
            max_results=max_results,
            **kwargs,
        )

        if not search_results:
            return []

        if crawl_engine is None:
            # Return search results without scraping
            from agentcrawl.core.engine import CrawlResult

            return [
                CrawlResult(
                    url=r.get("url", ""),
                    markdown=r.get("snippet", ""),
                    metadata={"title": r.get("title", "")},
                    success=True,
                )
                for r in search_results
            ]

        # Scrape each result
        results = []
        for sr in search_results:
            url = sr.get("url", "")
            if not url:
                continue

            try:
                result = await crawl_engine.scrape(url, config)
                result.metadata["search_title"] = sr.get("title", "")
                result.metadata["search_snippet"] = sr.get("snippet", "")
                result.metadata["search_position"] = sr.get("position", 0)
                results.append(result)
            except Exception as e:
                logger.warning("Failed to scrape search result %s: %s", url, e)

        return results

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        return {
            "provider": self._provider_name,
            "total_searches": self._total_searches,
            "total_results": self._total_results,
            "avg_results_per_search": round(self._total_results / max(self._total_searches, 1), 1),
            "default_max_results": self._default_max_results,
            "timeout": self._timeout,
            "rate_limit_delay": self._rate_limit_delay,
        }

    def __repr__(self) -> str:
        return f"SearchEngine(provider={self._provider_name!r}, searches={self._total_searches})"
