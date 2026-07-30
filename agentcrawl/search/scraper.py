"""
AgentCrawl — Search Engine Scraper
======================================

Direct HTML scraping of search engine results pages (SERPs)
without requiring API keys. Supports Google, Bing, and DuckDuckGo.

⚠️ Note: Scraping search engines may violate their terms of service.
Use responsibly and respect rate limits. For production use,
prefer official APIs (see search/engine.py).

Features:
    - Google SERP scraping
    - Bing SERP scraping
    - DuckDuckGo HTML scraping
    - Automatic result parsing (title, URL, snippet)
    - Pagination support
    - CAPTCHA/block detection
    - User-Agent rotation
    - Configurable rate limiting

Usage:
    from agentcrawl.search.scraper import SearchScraper

    scraper = SearchScraper(engine="google")
    results = await scraper.search("python tutorial", max_results=10)

    # Bing
    scraper = SearchScraper(engine="bing")
    results = await scraper.search("machine learning")

    # DuckDuckGo
    scraper = SearchScraper(engine="duckduckgo")
    results = await scraper.search("web scraping")

    # With pagination
    results = await scraper.search_paginated("python", max_results=30)
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from agentcrawl.search.engine import SearchResult

logger = logging.getLogger("agentcrawl.search.scraper")


# ══════════════════════════════════════════════════════════════
# User-Agent Pool
# ══════════════════════════════════════════════════════════════

USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]


# ══════════════════════════════════════════════════════════════
# Search Scraper
# ══════════════════════════════════════════════════════════════

class SearchScraper:
    """
    Scrapes search engine results pages directly.

    Args:
        engine: Search engine to scrape ('google', 'bing', 'duckduckgo').
        language: Search language code.
        country: Search country code.
        rate_limit_delay: Minimum delay between requests (seconds).
        rotate_user_agent: Whether to rotate User-Agent strings.
        timeout: HTTP request timeout (seconds).
        max_retries: Maximum retry attempts on failure.

    Example:
        >>> scraper = SearchScraper(engine="google")
        >>> results = await scraper.search("python tutorial")
        >>> for r in results:
        ...     print(f"{r.title}: {r.url}")
    """

    SUPPORTED_ENGINES: frozenset[str] = frozenset({"google", "bing", "duckduckgo"})

    def __init__(
        self,
        engine: str = "google",
        language: str = "en",
        country: str = "",
        rate_limit_delay: float = 2.0,
        rotate_user_agent: bool = True,
        timeout: float = 15.0,
        max_retries: int = 2,
    ):
        engine = engine.lower().strip()
        if engine not in self.SUPPORTED_ENGINES:
            raise ValueError(
                f"Unsupported engine: '{engine}'. "
                f"Available: {', '.join(sorted(self.SUPPORTED_ENGINES))}"
            )

        self._engine = engine
        self._language = language
        self._country = country
        self._rate_limit_delay = rate_limit_delay
        self._rotate_user_agent = rotate_user_agent
        self._timeout = timeout
        self._max_retries = max_retries

        self._last_request_time: float = 0.0
        self._total_requests: int = 0
        self._total_blocked: int = 0

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def engine(self) -> str:
        return self._engine

    @property
    def total_requests(self) -> int:
        return self._total_requests

    @property
    def total_blocked(self) -> int:
        return self._total_blocked

    # ──────────────────────────────────────────────────────────
    # Search API
    # ──────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 1,
    ) -> list[SearchResult]:
        """
        Search and return parsed results.

        Args:
            query: Search query string.
            max_results: Maximum results to return.
            page: Page number (1-based).

        Returns:
            List of SearchResult objects.
        """
        await self._rate_limit()

        for attempt in range(self._max_retries + 1):
            try:
                html = await self._fetch_serp(query, page)

                if html is None:
                    return []

                # Check for blocks
                if self._is_blocked(html):
                    self._total_blocked += 1
                    logger.warning(
                        "Search blocked by %s (attempt %d/%d)",
                        self._engine,
                        attempt + 1,
                        self._max_retries + 1,
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._rate_limit_delay * (attempt + 1))
                        continue
                    return []

                # Parse results
                if self._engine == "google":
                    results = self._parse_google(html, max_results, page)
                elif self._engine == "bing":
                    results = self._parse_bing(html, max_results, page)
                else:
                    results = self._parse_duckduckgo(html, max_results)

                self._total_requests += 1
                return results

            except Exception as e:
                logger.warning(
                    "Search scrape error (attempt %d): %s",
                    attempt + 1, e,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._rate_limit_delay)

        return []

    async def search_paginated(
        self,
        query: str,
        max_results: int = 30,
        page_size: int = 10,
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

            # Stop if we got fewer results than expected
            if len(results) < page_size:
                break

        return all_results[:max_results]

    # ──────────────────────────────────────────────────────────
    # Fetching
    # ──────────────────────────────────────────────────────────

    async def _fetch_serp(self, query: str, page: int = 1) -> str | None:
        """Fetch the search engine results page HTML."""
        import httpx

        url, params = self._build_request(query, page)
        headers = self._build_headers()

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, params=params, headers=headers)

                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 429:
                    logger.warning("Rate limited (429) by %s", self._engine)
                    return None
                else:
                    logger.warning(
                        "%s returned status %d",
                        self._engine, resp.status_code,
                    )
                    return None

        except Exception as e:
            logger.warning("Fetch failed: %s", e)
            return None

    def _build_request(
        self,
        query: str,
        page: int,
    ) -> tuple[str, dict[str, str]]:
        """Build the request URL and parameters."""
        if self._engine == "google":
            params: dict[str, str] = {
                "q": query,
                "num": "20",
                "hl": self._language,
            }
            if page > 1:
                params["start"] = str((page - 1) * 10)
            if self._country:
                params["gl"] = self._country
            return "https://www.google.com/search", params

        elif self._engine == "bing":
            params = {
                "q": query,
                "count": "20",
                "setlang": self._language,
            }
            if page > 1:
                params["first"] = str((page - 1) * 10 + 1)
            if self._country:
                params["cc"] = self._country
            return "https://www.bing.com/search", params

        else:  # duckduckgo
            params = {
                "q": query,
                "kl": f"{self._country}-{self._language}" if self._country else self._language,
            }
            return "https://html.duckduckgo.com/html/", params

    def _build_headers(self) -> dict[str, str]:
        """Build request headers."""
        ua = secrets.choice(USER_AGENTS) if self._rotate_user_agent else USER_AGENTS[0]

        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self._language},en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    # ──────────────────────────────────────────────────────────
    # Block Detection
    # ──────────────────────────────────────────────────────────

    def _is_blocked(self, html: str) -> bool:
        """Detect if the response is a CAPTCHA or block page."""
        html_lower = html.lower()

        block_indicators = [
            "captcha",
            "unusual traffic",
            "please verify you are a human",
            "are you a robot",
            "access denied",
            "blocked",
            "rate limit",
            "too many requests",
            "recaptcha",
            "hcaptcha",
            "challenge-platform",
        ]

        return any(indicator in html_lower for indicator in block_indicators)

    # ──────────────────────────────────────────────────────────
    # Parsing: Google
    # ──────────────────────────────────────────────────────────

    def _parse_google(
        self,
        html: str,
        max_results: int,
        page: int,
    ) -> list[SearchResult]:
        """Parse Google SERP HTML."""
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        # Remove script and style tags
        clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)

        # Find result blocks — Google uses <div class="g"> or similar
        # We look for anchor tags with real URLs
        link_pattern = re.compile(
            r'<a[^>]*href="(https?://(?!www\.google\.|accounts\.google\.|support\.google\.|policies\.google\.)[^"]+)"'
            r'[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        position = (page - 1) * 10

        for match in link_pattern.finditer(clean):
            if len(results) >= max_results:
                break

            url = match.group(1).strip()
            inner_html = match.group(2)

            # Extract title text
            title = re.sub(r"<[^>]+>", "", inner_html).strip()
            title = re.sub(r"\s+", " ", title)

            # Skip short/empty titles
            if len(title) < 8:
                continue

            # Skip Google internal
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
        self._extract_snippets_google(clean, results)

        return results

    def _extract_snippets_google(
        self,
        html: str,
        results: list[SearchResult],
    ) -> None:
        """Try to extract snippets for Google results."""
        # Google snippets are typically in <span> or <div> with specific classes
        snippet_pattern = re.compile(
            r'<(?:span|div)[^>]*class="[^"]*(?:BNeawe|s3v9rd|VwiC3b)[^"]*"[^>]*>'
            r'((?:(?!</(?:span|div)>).){40,500})'
            r'</(?:span|div)>',
            re.DOTALL,
        )

        snippets = snippet_pattern.findall(html)
        for i, snippet in enumerate(snippets):
            if i < len(results):
                clean = re.sub(r"<[^>]+>", "", snippet).strip()
                clean = re.sub(r"\s+", " ", clean)
                if len(clean) > 30:
                    results[i].snippet = clean

    # ──────────────────────────────────────────────────────────
    # Parsing: Bing
    # ──────────────────────────────────────────────────────────

    def _parse_bing(
        self,
        html: str,
        max_results: int,
        page: int,
    ) -> list[SearchResult]:
        """Parse Bing SERP HTML."""
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)

        # Bing results are in <li class="b_algo">
        result_pattern = re.compile(
            r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>',
            re.DOTALL,
        )

        position = (page - 1) * 10

        for block_match in result_pattern.finditer(clean):
            if len(results) >= max_results:
                break

            block = block_match.group(1)

            # Extract URL and title from <h2><a href="...">title</a></h2>
            link_match = re.search(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                block,
                re.DOTALL,
            )

            if not link_match:
                continue

            url = link_match.group(1).strip()
            title = re.sub(r"<[^>]+>", "", link_match.group(2)).strip()

            if not title or len(title) < 5:
                continue

            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Extract snippet
            snippet = ""
            snippet_match = re.search(
                r'<p[^>]*>(.*?)</p>',
                block,
                re.DOTALL,
            )
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
                snippet = re.sub(r"\s+", " ", snippet)

            position += 1
            results.append(SearchResult(
                url=url,
                title=title,
                snippet=snippet,
                position=position,
            ))

        return results

    # ──────────────────────────────────────────────────────────
    # Parsing: DuckDuckGo
    # ──────────────────────────────────────────────────────────

    def _parse_duckduckgo(
        self,
        html: str,
        max_results: int,
    ) -> list[SearchResult]:
        """Parse DuckDuckGo HTML results."""
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        # DuckDuckGo HTML version uses specific class names
        _result_pattern = re.compile(
            r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>',
            re.DOTALL,
        )

        # Also try link-based extraction
        link_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        snippet_pattern = re.compile(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        links = list(link_pattern.finditer(html))
        snippets = list(snippet_pattern.finditer(html))

        for i, link_match in enumerate(links):
            if len(results) >= max_results:
                break

            url = link_match.group(1).strip()
            title = re.sub(r"<[^>]+>", "", link_match.group(2)).strip()

            # DuckDuckGo wraps URLs in redirect
            if "uddg=" in url:
                try:
                    parsed = urlparse(url)
                    params = parse_qs(parsed.query)
                    if "uddg" in params:
                        url = params["uddg"][0]
                except Exception:
                    logger.debug("Error extracting uddg param from URL")

            if not url or url.startswith("#"):
                continue

            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Get snippet
            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r"<[^>]+>", "", snippets[i].group(1)).strip()
                snippet = re.sub(r"\s+", " ", snippet)

            results.append(SearchResult(
                url=url,
                title=title,
                snippet=snippet,
                position=i + 1,
            ))

        return results

    # ──────────────────────────────────────────────────────────
    # Rate Limiting
    # ──────────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            # Add jitter to avoid detection
            jitter = secrets.SystemRandom().uniform(0, self._rate_limit_delay * 0.3)
            await asyncio.sleep(self._rate_limit_delay - elapsed + jitter)
        self._last_request_time = time.time()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        return {
            "engine": self._engine,
            "total_requests": self._total_requests,
            "total_blocked": self._total_blocked,
            "block_rate": round(
                self._total_blocked / max(self._total_requests, 1), 3
            ),
            "language": self._language,
            "country": self._country,
            "rate_limit_delay": self._rate_limit_delay,
        }

    def __repr__(self) -> str:
        return (
            f"SearchScraper(engine={self._engine!r}, "
            f"requests={self._total_requests}, "
            f"blocked={self._total_blocked})"
        )
