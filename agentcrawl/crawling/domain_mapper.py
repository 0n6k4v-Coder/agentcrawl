"""
AgentCrawl — Domain Mapper
==============================

Discovers all URLs on a website without scraping page content.
Uses sitemap.xml, robots.txt, and shallow link crawling to build
a complete URL map of a domain.

This is the engine behind the ``/map`` API endpoint and the
``engine.map()`` method.

Discovery Sources (in priority order):
    1. sitemap.xml — Fastest, most complete (if available)
    2. robots.txt  — Sitemap references and allowed paths
    3. Link crawl  — Shallow crawl to discover remaining URLs

Usage:
    from agentcrawl.crawling.domain_mapper import DomainMapper

    mapper = DomainMapper(
        max_urls=500,
        use_sitemap=True,
        use_robots=True,
        use_link_crawl=True,
    )

    # Discover all URLs
    urls = await mapper.discover("https://docs.example.com")
    print(f"Found {len(urls)} URLs")

    # With filtering
    mapper = DomainMapper(
        max_urls=1000,
        include_patterns=["/docs/*", "/api/*"],
        exclude_patterns=["/blog/*", "*.pdf"],
    )
    urls = await mapper.discover("https://example.com")

    # Get URL patterns
    patterns = mapper.analyze_patterns(urls)
    for p in patterns:
        print(f"{p['template']}: {p['count']} URLs")
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import defusedxml.ElementTree as DefusedElementTree

logger = logging.getLogger("agentcrawl.crawling.domain_mapper")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class MapResult:
    """
    Result of a domain mapping operation.

    Attributes:
        urls: List of discovered URLs.
        total_urls: Total number of unique URLs found.
        sitemap_urls: URLs found via sitemap.xml.
        robots_urls: URLs found via robots.txt.
        crawl_urls: URLs found via link crawling.
        patterns: Detected URL patterns.
        duration_ms: Total discovery time.
        sources: Which sources were used.
        errors: Errors encountered during discovery.
    """

    urls: list[str] = field(default_factory=list)
    total_urls: int = 0
    sitemap_urls: int = 0
    robots_urls: int = 0
    crawl_urls: int = 0
    patterns: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.total_urls = len(self.urls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_urls": self.total_urls,
            "sitemap_urls": self.sitemap_urls,
            "robots_urls": self.robots_urls,
            "crawl_urls": self.crawl_urls,
            "sources": self.sources,
            "duration_ms": round(self.duration_ms, 2),
            "patterns": self.patterns[:20],
            "errors": self.errors[:10],
            "urls": self.urls,
        }


@dataclass
class URLPatternInfo:
    """Information about a detected URL pattern."""

    template: str
    count: int
    examples: list[str] = field(default_factory=list)
    avg_depth: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "count": self.count,
            "examples": self.examples[:3],
            "avg_depth": round(self.avg_depth, 1),
        }


# ══════════════════════════════════════════════════════════════
# Domain Mapper
# ══════════════════════════════════════════════════════════════


class DomainMapper:
    """
    Discovers all URLs on a website without scraping content.

    Combines sitemap parsing, robots.txt analysis, and shallow
    link crawling to build a comprehensive URL map.

    Args:
        max_urls: Maximum URLs to discover.
        use_sitemap: Whether to parse sitemap.xml.
        use_robots: Whether to parse robots.txt.
        use_link_crawl: Whether to do shallow link crawling.
        crawl_depth: Maximum depth for link crawling.
        crawl_max_pages: Maximum pages to fetch during link crawl.
        include_patterns: URL glob patterns to include.
        exclude_patterns: URL glob patterns to exclude.
        exclude_extensions: File extensions to exclude.
        same_domain: Only include same-domain URLs.
        max_concurrent: Maximum concurrent HTTP requests.
        timeout: HTTP request timeout in seconds.

    Example:
        >>> mapper = DomainMapper(max_urls=500)
        >>> urls = await mapper.discover("https://docs.example.com")
        >>> print(f"Found {len(urls)} URLs")
    """

    # Common sitemap locations
    SITEMAP_PATHS: tuple[str, ...] = (
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/sitemapindex.xml",
        "/sitemap/sitemap.xml",
        "/wp-sitemap.xml",
        "/post-sitemap.xml",
        "/page-sitemap.xml",
    )

    # File extensions to exclude by default
    DEFAULT_EXCLUDE_EXTENSIONS: frozenset[str] = frozenset(
        {
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
            ".xml",
            ".json",
            ".txt",
            ".csv",
            ".rss",
            ".atom",
        }
    )

    def __init__(
        self,
        max_urls: int = 500,
        use_sitemap: bool = True,
        use_robots: bool = True,
        use_link_crawl: bool = True,
        crawl_depth: int = 2,
        crawl_max_pages: int = 20,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        exclude_extensions: list[str] | None = None,
        same_domain: bool = True,
        max_concurrent: int = 10,
        timeout: float = 15.0,
    ):
        self._max_urls = max_urls
        self._use_sitemap = use_sitemap
        self._use_robots = use_robots
        self._use_link_crawl = use_link_crawl
        self._crawl_depth = crawl_depth
        self._crawl_max_pages = crawl_max_pages
        self._include_patterns = include_patterns or []
        self._exclude_patterns = exclude_patterns or []
        self._exclude_extensions = {
            ext.lower() for ext in (exclude_extensions or self.DEFAULT_EXCLUDE_EXTENSIONS)
        }
        self._same_domain = same_domain
        self._max_concurrent = max_concurrent
        self._timeout = timeout

        # State
        self._base_domain: str = ""
        self._base_url: str = ""
        self._discovered: set[str] = set()
        self._sitemap_count: int = 0
        self._robots_count: int = 0
        self._crawl_count: int = 0
        self._errors: list[str] = []
        self._sources: list[str] = []

    # ──────────────────────────────────────────────────────────
    # Main API
    # ──────────────────────────────────────────────────────────

    async def discover(self, url: str) -> list[str]:
        """
        Discover all URLs on a website.

        Args:
            url: Website URL to map.

        Returns:
            List of discovered URLs.
        """
        start_time = time.perf_counter()

        # Parse base domain
        try:
            parsed = urlparse(url)
            self._base_domain = parsed.netloc.replace("www.", "")
            self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        except Exception as e:
            logger.error("Invalid URL: %s", e)
            return []

        logger.info(
            "Starting domain mapping for %s (max_urls=%d)",
            self._base_domain,
            self._max_urls,
        )

        # Phase 1: Sitemap
        if self._use_sitemap:
            await self._discover_from_sitemap()

        # Phase 2: Robots.txt
        if self._use_robots:
            await self._discover_from_robots()

        # Phase 3: Link crawl
        if self._use_link_crawl and len(self._discovered) < self._max_urls:
            await self._discover_from_crawl(url)

        # Build result
        urls = self._filter_urls(sorted(self._discovered))
        duration = (time.perf_counter() - start_time) * 1000

        logger.info(
            "Domain mapping complete: %d URLs found in %.0fms (sitemap=%d, robots=%d, crawl=%d)",
            len(urls),
            duration,
            self._sitemap_count,
            self._robots_count,
            self._crawl_count,
        )

        return urls[: self._max_urls]

    async def discover_with_result(self, url: str) -> MapResult:
        """
        Discover URLs and return a detailed MapResult.

        Args:
            url: Website URL to map.

        Returns:
            MapResult with URLs and statistics.
        """
        start_time = time.perf_counter()

        urls = await self.discover(url)
        duration = (time.perf_counter() - start_time) * 1000

        patterns = self.analyze_patterns(urls)

        return MapResult(
            urls=urls,
            sitemap_urls=self._sitemap_count,
            robots_urls=self._robots_count,
            crawl_urls=self._crawl_count,
            patterns=[p.to_dict() for p in patterns],
            duration_ms=duration,
            sources=list(self._sources),
            errors=list(self._errors),
        )

    # ──────────────────────────────────────────────────────────
    # Phase 1: Sitemap Discovery
    # ──────────────────────────────────────────────────────────

    async def _discover_from_sitemap(self) -> None:
        """Discover URLs from sitemap.xml files."""
        import httpx

        self._sources.append("sitemap")
        semaphore = asyncio.Semaphore(self._max_concurrent)

        # Try common sitemap locations
        sitemap_urls_to_try = [f"{self._base_url}{path}" for path in self.SITEMAP_PATHS]

        # Also try sitemap referenced in robots.txt (done later)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            for sitemap_url in sitemap_urls_to_try:
                if len(self._discovered) >= self._max_urls:
                    break

                try:
                    async with semaphore:
                        resp = await client.get(sitemap_url)
                        if resp.status_code == 200:
                            content_type = resp.headers.get("content-type", "")
                            if "xml" in content_type or "text/xml" in content_type:
                                await self._parse_sitemap(resp.text, client, semaphore)
                                logger.debug(
                                    "Parsed sitemap: %s (%d URLs total)",
                                    sitemap_url,
                                    len(self._discovered),
                                )
                except Exception as e:
                    logger.debug("Sitemap fetch failed %s: %s", sitemap_url, e)

    async def _parse_sitemap(
        self,
        xml_content: str,
        client: Any,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """
        Parse a sitemap XML document.

        Handles both sitemap index files (containing references to
        other sitemaps) and regular sitemap files (containing URLs).
        """
        try:
            # Remove XML declaration issues
            xml_content = re.sub(r"<\?xml[^?]*\?>", "", xml_content).strip()

            root = DefusedElementTree.fromstring(xml_content)
        except DefusedElementTree.ParseError as e:
            logger.debug("Sitemap XML parse error: %s", e)
            self._errors.append(f"Sitemap parse error: {e}")
            return

        # Detect namespace
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        # Check if this is a sitemap index
        sitemap_tags = root.findall(f"{ns}sitemap")
        if sitemap_tags:
            # Sitemap index — fetch child sitemaps
            child_urls = []
            for sitemap in sitemap_tags:
                loc = sitemap.find(f"{ns}loc")
                if loc is not None and loc.text:
                    child_urls.append(loc.text.strip())

            # Fetch child sitemaps concurrently
            tasks = [
                self._fetch_and_parse_child_sitemap(url, client, semaphore) for url in child_urls
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            return

        # Regular sitemap — extract URLs
        url_tags = root.findall(f"{ns}url")
        for url_tag in url_tags:
            if len(self._discovered) >= self._max_urls:
                break

            loc = url_tag.find(f"{ns}loc")
            if loc is not None and loc.text:
                url = loc.text.strip()
                if self._is_valid_url(url):
                    self._discovered.add(url)
                    self._sitemap_count += 1

    async def _fetch_and_parse_child_sitemap(
        self,
        url: str,
        client: Any,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Fetch and parse a child sitemap from a sitemap index."""
        try:
            async with semaphore:
                resp = await client.get(url)
                if resp.status_code == 200:
                    await self._parse_sitemap(resp.text, client, semaphore)
        except Exception as e:
            logger.debug("Child sitemap fetch failed %s: %s", url, e)

    # ──────────────────────────────────────────────────────────
    # Phase 2: Robots.txt Discovery
    # ──────────────────────────────────────────────────────────

    async def _discover_from_robots(self) -> None:
        """Discover URLs and sitemap references from robots.txt."""
        import httpx

        self._sources.append("robots")
        robots_url = f"{self._base_url}/robots.txt"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(robots_url)
                if resp.status_code != 200:
                    return

                content = resp.text

                # Extract sitemap references
                for line in content.splitlines():
                    line = line.strip()
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url:
                            # Fetch this sitemap
                            try:
                                sem = asyncio.Semaphore(self._max_concurrent)
                                sitemap_resp = await client.get(sitemap_url)
                                if sitemap_resp.status_code == 200:
                                    await self._parse_sitemap(sitemap_resp.text, client, sem)
                            except Exception as e:
                                logger.debug(
                                    "Robots sitemap fetch failed %s: %s",
                                    sitemap_url,
                                    e,
                                )

                # Extract allowed paths as URL hints
                for line in content.splitlines():
                    line = line.strip()
                    if line.lower().startswith("allow:"):
                        path = line.split(":", 1)[1].strip()
                        if path and path != "/":
                            full_url = f"{self._base_url}{path}"
                            if self._is_valid_url(full_url):
                                self._discovered.add(full_url)
                                self._robots_count += 1

        except Exception as e:
            logger.debug("Robots.txt fetch failed: %s", e)
            self._errors.append(f"Robots.txt error: {e}")

    # ──────────────────────────────────────────────────────────
    # Phase 3: Link Crawl Discovery
    # ──────────────────────────────────────────────────────────

    async def _discover_from_crawl(self, start_url: str) -> None:
        """Discover URLs by shallow link crawling."""
        import httpx

        self._sources.append("crawl")

        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(start_url, 0)]
        pages_fetched = 0

        semaphore = asyncio.Semaphore(self._max_concurrent)

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            while queue and pages_fetched < self._crawl_max_pages:
                if len(self._discovered) >= self._max_urls:
                    break

                # Get next batch
                batch: list[tuple[str, int]] = []
                while queue and len(batch) < self._max_concurrent:
                    url, depth = queue.pop(0)
                    normalized = self._normalize_url(url)
                    if normalized not in visited:
                        visited.add(normalized)
                        batch.append((url, depth))

                if not batch:
                    continue

                # Fetch batch concurrently
                tasks = [
                    self._fetch_links_from_page(url, depth, client, semaphore, queue)
                    for url, depth in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        continue
                    if result:
                        pages_fetched += 1
                        self._crawl_count += 1

    async def _fetch_links_from_page(
        self,
        url: str,
        depth: int,
        client: Any,
        semaphore: asyncio.Semaphore,
        queue: list[tuple[str, int]],
    ) -> bool:
        """
        Fetch a page and extract links (without full parsing).

        Uses regex-based link extraction for speed.
        """
        if depth >= self._crawl_depth:
            return False

        try:
            async with semaphore:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": "AgentCrawl/1.0 (URL Mapper)",
                        "Accept": "text/html",
                    },
                )

                if resp.status_code != 200:
                    return False

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type:
                    return False

                html = resp.text

                # Extract links using regex (fast, no full parsing)
                href_pattern = re.compile(
                    r'<a\s+[^>]*href=["\']([^"\']+)["\']',
                    re.IGNORECASE,
                )

                for match in href_pattern.finditer(html):
                    href = match.group(1).strip()

                    # Skip non-HTTP links
                    if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
                        continue

                    # Resolve relative URLs
                    absolute_url = urljoin(url, href)

                    # Validate and add
                    if self._is_valid_url(absolute_url):
                        normalized = self._normalize_url(absolute_url)
                        if normalized not in self._discovered:
                            self._discovered.add(normalized)

                            # Add to queue for further crawling
                            if depth + 1 < self._crawl_depth:
                                queue.append((absolute_url, depth + 1))

                return True

        except Exception as e:
            logger.debug("Link crawl fetch failed %s: %s", url, e)
            return False

    # ──────────────────────────────────────────────────────────
    # URL Validation & Filtering
    # ──────────────────────────────────────────────────────────

    def _is_valid_url(self, url: str) -> bool:
        """Check if a URL is valid and should be included."""
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        # Must be HTTP/HTTPS
        if parsed.scheme not in ("http", "https"):
            return False

        # Must have a hostname
        if not parsed.netloc:
            return False

        # Same domain check
        if self._same_domain and self._base_domain:
            domain = parsed.netloc.replace("www.", "")
            if domain != self._base_domain:
                return False

        # Extension check
        path_lower = parsed.path.lower()
        return all(not path_lower.endswith(ext) for ext in self._exclude_extensions)

    def _filter_urls(self, urls: list[str]) -> list[str]:
        """Apply include/exclude patterns to a list of URLs."""
        import fnmatch

        filtered: list[str] = []

        for url in urls:
            try:
                path = urlparse(url).path
            except Exception as e:
                logger.debug("Failed to parse URL %s: %s", url, e)
                continue

            # Include patterns
            if self._include_patterns and not any(
                fnmatch.fnmatch(path, p) or fnmatch.fnmatch(url, p) for p in self._include_patterns
            ):
                continue

            # Exclude patterns
            if self._exclude_patterns and any(
                fnmatch.fnmatch(path, p) or fnmatch.fnmatch(url, p) for p in self._exclude_patterns
            ):
                continue

            filtered.append(url)

        return filtered

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize a URL for deduplication."""
        try:
            parsed = urlparse(url)
            # Remove fragment
            normalized = parsed._replace(fragment="").geturl()
            # Strip trailing slash (except root)
            if normalized.endswith("/") and normalized.count("/") > 3:
                normalized = normalized.rstrip("/")
            return normalized
        except Exception:
            return url

    # ──────────────────────────────────────────────────────────
    # Pattern Analysis
    # ──────────────────────────────────────────────────────────

    def analyze_patterns(self, urls: list[str]) -> list[URLPatternInfo]:
        """
        Analyze URL patterns from a list of URLs.

        Args:
            urls: List of URLs to analyze.

        Returns:
            List of URLPatternInfo sorted by count.
        """
        template_groups: dict[str, list[str]] = defaultdict(list)

        for url in urls:
            template = self._url_to_template(url)
            template_groups[template].append(url)

        patterns: list[URLPatternInfo] = []

        for template, group_urls in template_groups.items():
            depths = []
            for u in group_urls:
                try:
                    path = urlparse(u).path.strip("/")
                    depths.append(len(path.split("/")) if path else 0)
                except Exception:
                    depths.append(0)

            avg_depth = sum(depths) / max(len(depths), 1)

            patterns.append(
                URLPatternInfo(
                    template=template,
                    count=len(group_urls),
                    examples=group_urls[:3],
                    avg_depth=avg_depth,
                )
            )

        patterns.sort(key=lambda p: p.count, reverse=True)
        return patterns

    @staticmethod
    def _url_to_template(url: str) -> str:
        """Convert a URL to a structural template."""
        try:
            parsed = urlparse(url)
            path = parsed.path.rstrip("/")
        except Exception:
            return url

        segments = path.split("/")
        template_segments: list[str] = []

        for seg in segments:
            if not seg:
                template_segments.append("")
            elif re.match(r"^\d+$", seg):
                template_segments.append("{num}")
            elif re.match(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                seg,
                re.I,
            ):
                template_segments.append("{uuid}")
            elif re.match(r"^[0-9a-f]{16,}$", seg, re.I):
                template_segments.append("{hash}")
            elif re.match(r"^v\d+(\.\d+)*$", seg, re.I):
                template_segments.append("{version}")
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", seg):
                template_segments.append("{date}")
            elif len(seg) > 15 and re.match(r"^[a-z0-9-]+$", seg, re.I):
                template_segments.append("{slug}")
            else:
                template_segments.append(seg)

        return "/".join(template_segments) or "/"

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get mapper diagnostics."""
        return {
            "base_domain": self._base_domain,
            "discovered_count": len(self._discovered),
            "sitemap_count": self._sitemap_count,
            "robots_count": self._robots_count,
            "crawl_count": self._crawl_count,
            "sources": self._sources,
            "errors": self._errors[:10],
            "config": {
                "max_urls": self._max_urls,
                "use_sitemap": self._use_sitemap,
                "use_robots": self._use_robots,
                "use_link_crawl": self._use_link_crawl,
                "crawl_depth": self._crawl_depth,
                "crawl_max_pages": self._crawl_max_pages,
                "same_domain": self._same_domain,
                "include_patterns": self._include_patterns,
                "exclude_patterns": self._exclude_patterns,
            },
        }

    def __repr__(self) -> str:
        return (
            f"DomainMapper(domain={self._base_domain!r}, "
            f"discovered={len(self._discovered)}, "
            f"max_urls={self._max_urls})"
        )
