"""
AgentCrawl — Google Search Provider
=======================================

Google search integration via Custom Search API, SerpAPI, or
direct HTML scraping.

Methods (in priority order):
    1. Google Custom Search JSON API (official, requires API key + CX)
    2. SerpAPI (third-party, requires API key)
    3. Direct HTML scraping (fallback, no API key, may be rate-limited)

Usage:
    from agentcrawl.search.google import GoogleSearchProvider

    # Via Custom Search API
    provider = GoogleSearchProvider(
        api_key="YOUR_API_KEY",
        cx="YOUR_SEARCH_ENGINE_ID",
    )
    results = await provider.search("python tutorial", max_results=10)

    # Via SerpAPI
    provider = GoogleSearchProvider(
        api_key="YOUR_SERPAPI_KEY",
        method="serpapi",
    )
    results = await provider.search("machine learning")

    # Direct scraping (no API key)
    provider = GoogleSearchProvider(method="scrape")
    results = await provider.search("web scraping python")
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import quote_plus, urlparse

from agentcrawl.search.engine import SearchProvider, SearchResult

logger = logging.getLogger("agentcrawl.search.google")


# ══════════════════════════════════════════════════════════════
# Google Search Provider
# ══════════════════════════════════════════════════════════════

class GoogleSearchProvider(SearchProvider):
    """
    Google search provider with multiple access methods.

    Args:
        api_key: API key (for Custom Search or SerpAPI).
        cx: Custom Search Engine ID (for Custom Search API).
        method: Access method ('custom_search', 'serpapi', 'scrape').
        language: Search language (e.g., 'en', 'th').
        country: Search country (e.g., 'us', 'th').
        safe_search: Safe search level ('off', 'medium', 'high').
        rate_limit_delay: Minimum delay between requests (seconds).

    Example:
        >>> provider = GoogleSearchProvider(
        ...     api_key="...",
        ...     cx="...",
        ...     method="custom_search",
        ... )
        >>> results = await provider.search("python asyncio", max_results=10)
    """

    name = "google"

    def __init__(
        self,
        api_key: str = "",
        cx: str = "",
        method: str = "auto",
        language: str = "en",
        country: str = "",
        safe_search: str = "off",
        rate_limit_delay: float = 1.0,
        **kwargs: Any,
    ):
        super().__init__(api_key=api_key, **kwargs)

        self._cx = cx
        self._language = language
        self._country = country
        self._safe_search = safe_search
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time: float = 0.0

        # Determine method
        if method == "auto":
            if api_key and cx:
                self._method = "custom_search"
            elif api_key:
                self._method = "serpapi"
            else:
                self._method = "scrape"
        else:
            self._method = method

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def method(self) -> str:
        """Current access method."""
        return self._method

    # ──────────────────────────────────────────────────────────
    # Search API
    # ──────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 10,
        start: int = 1,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """
        Search Google and return results.

        Args:
            query: Search query.
            max_results: Maximum results (max 10 per page for Custom Search).
            start: Starting result index (1-based, for pagination).
            **kwargs: Additional options.

        Returns:
            List of SearchResult objects.
        """
        # Rate limiting
        await self._rate_limit()

        if self._method == "custom_search":
            return await self._search_custom_search(query, max_results, start)
        elif self._method == "serpapi":
            return await self._search_serpapi(query, max_results, start)
        else:
            return await self._search_scrape(query, max_results)

    async def search_paginated(
        self,
        query: str,
        max_results: int = 30,
        page_size: int = 10,
    ) -> list[SearchResult]:
        """
        Search with pagination to get more than 10 results.

        Args:
            query: Search query.
            max_results: Total maximum results.
            page_size: Results per page (max 10 for Custom Search).

        Returns:
            List of SearchResult objects.
        """
        all_results: list[SearchResult] = []
        start = 1

        while len(all_results) < max_results:
            batch_size = min(page_size, max_results - len(all_results))
            results = await self.search(
                query=query,
                max_results=batch_size,
                start=start,
            )

            if not results:
                break

            all_results.extend(results)
            start += len(results)

            # Stop if we got fewer results than requested
            if len(results) < batch_size:
                break

        return all_results[:max_results]

    # ──────────────────────────────────────────────────────────
    # Method: Custom Search API
    # ──────────────────────────────────────────────────────────

    async def _search_custom_search(
        self,
        query: str,
        max_results: int,
        start: int = 1,
    ) -> list[SearchResult]:
        """Search via Google Custom Search JSON API."""
        import httpx

        if not self._api_key or not self._cx:
            raise ValueError(
                "Google Custom Search requires api_key and cx. "
                "Get them from https://developers.google.com/custom-search/v1/overview"
            )

        results: list[SearchResult] = []

        params: dict[str, Any] = {
            "key": self._api_key,
            "cx": self._cx,
            "q": query,
            "num": min(max_results, 10),  # API max is 10 per request
            "start": start,
        }

        if self._language:
            params["lr"] = f"lang_{self._language}"

        if self._country:
            params["gl"] = self._country

        if self._safe_search != "off":
            params["safe"] = self._safe_search

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params,
                )

                if resp.status_code != 200:
                    logger.warning(
                        "Google Custom Search API error: %d — %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return results

                data = resp.json()

                for i, item in enumerate(data.get("items", [])):
                    results.append(SearchResult(
                        url=item.get("link", ""),
                        title=item.get("title", ""),
                        snippet=item.get("snippet", ""),
                        position=start + i,
                        raw=item,
                    ))

        except Exception as e:
            logger.warning("Google Custom Search failed: %s", e)

        return results

    # ──────────────────────────────────────────────────────────
    # Method: SerpAPI
    # ──────────────────────────────────────────────────────────

    async def _search_serpapi(
        self,
        query: str,
        max_results: int,
        start: int = 1,
    ) -> list[SearchResult]:
        """Search via SerpAPI."""
        import httpx

        if not self._api_key:
            raise ValueError("SerpAPI requires an API key")

        results: list[SearchResult] = []

        params: dict[str, Any] = {
            "api_key": self._api_key,
            "engine": "google",
            "q": query,
            "num": min(max_results, 10),
            "start": start - 1,  # SerpAPI uses 0-based offset
        }

        if self._language:
            params["hl"] = self._language

        if self._country:
            params["gl"] = self._country

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    "https://serpapi.com/search.json",
                    params=params,
                )

                if resp.status_code != 200:
                    logger.warning("SerpAPI error: %d", resp.status_code)
                    return results

                data = resp.json()

                for i, item in enumerate(
                    data.get("organic_results", [])
                ):
                    results.append(SearchResult(
                        url=item.get("link", ""),
                        title=item.get("title", ""),
                        snippet=item.get("snippet", ""),
                        position=item.get("position", start + i),
                        raw=item,
                    ))

        except Exception as e:
            logger.warning("SerpAPI search failed: %s", e)

        return results

    # ──────────────────────────────────────────────────────────
    # Method: Direct Scraping
    # ──────────────────────────────────────────────────────────

    async def _search_scrape(
        self,
        query: str,
        max_results: int,
    ) -> list[SearchResult]:
        """Search by scraping Google HTML results."""
        import httpx

        results: list[SearchResult] = []

        params: dict[str, str] = {
            "q": query,
            "num": str(min(max_results, 20)),
        }

        if self._language:
            params["hl"] = self._language

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": f"{self._language},en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
            ) as client:
                resp = await client.get(
                    "https://www.google.com/search",
                    params=params,
                    headers=headers,
                )

                if resp.status_code != 200:
                    logger.warning(
                        "Google scrape error: %d", resp.status_code
                    )
                    return results

                html = resp.text

                # Check for CAPTCHA
                if "captcha" in html.lower() or "unusual traffic" in html.lower():
                    logger.warning("Google CAPTCHA detected — scraping blocked")
                    return results

                # Parse results from HTML
                results = self._parse_google_html(html, max_results)

        except Exception as e:
            logger.warning("Google scrape failed: %s", e)

        return results

    def _parse_google_html(
        self,
        html: str,
        max_results: int,
    ) -> list[SearchResult]:
        """
        Parse Google search results from HTML.

        Uses regex-based extraction for reliability without
        requiring a full HTML parser.
        """
        results: list[SearchResult] = []

        # Pattern for search result blocks
        # Google's HTML structure varies, so we use multiple patterns

        # Pattern 1: Standard result links
        link_pattern = re.compile(
            r'<a[^>]*href="(https?://(?!www\.google\.|accounts\.google\.|support\.google\.)[^"]+)"'
            r'[^>]*>(?:<[^>]*>)*([^<]{10,})(?:<[^>]*>)*</a>',
            re.DOTALL,
        )

        seen_urls: set[str] = set()
        position = 0

        for match in link_pattern.finditer(html):
            if position >= max_results:
                break

            url = match.group(1).strip()
            title = match.group(2).strip()

            # Clean title
            title = re.sub(r"<[^>]+>", "", title).strip()

            # Skip non-result links
            if not title or len(title) < 10:
                continue

            # Skip Google internal URLs
            parsed = urlparse(url)
            if "google." in parsed.netloc:
                continue

            # Deduplicate
            if url in seen_urls:
                continue
            seen_urls.add(url)

            position += 1
            results.append(SearchResult(
                url=url,
                title=title,
                snippet="",
                position=position,
            ))

        # Try to extract snippets
        snippet_pattern = re.compile(
            r'<span[^>]*class="[^"]*"[^>]*>((?:(?!<span).){50,400})</span>',
            re.DOTALL,
        )

        snippets = snippet_pattern.findall(html)
        for i, snippet in enumerate(snippets):
            if i < len(results):
                clean = re.sub(r"<[^>]+>", "", snippet).strip()
                if len(clean) > 30:
                    results[i].snippet = clean

        return results

    # ──────────────────────────────────────────────────────────
    # Rate Limiting
    # ──────────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
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
            "method": self._method,
            "language": self._language,
            "country": self._country,
            "safe_search": self._safe_search,
            "has_api_key": bool(self._api_key),
            "has_cx": bool(self._cx),
        }

    def __repr__(self) -> str:
        return (
            f"GoogleSearchProvider(method={self._method!r}, "
            f"lang={self._language!r})"
        )