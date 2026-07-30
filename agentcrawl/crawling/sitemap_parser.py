"""
AgentCrawl — Sitemap Parser
===============================

Comprehensive sitemap.xml parser with support for sitemap indexes,
gzipped sitemaps, metadata extraction, and automatic discovery.

Handles:
    - Standard sitemap XML (urlset)
    - Sitemap index files (sitemapindex → child sitemaps)
    - Gzipped sitemaps (.xml.gz)
    - Sitemap references in robots.txt
    - Auto-discovery of common sitemap locations
    - URL metadata (lastmod, changefreq, priority)
    - Nested sitemap indexes (multi-level)

Usage:
    from agentcrawl.crawling.sitemap_parser import SitemapParser

    parser = SitemapParser()

    # Parse a specific sitemap
    entries = await parser.parse("https://example.com/sitemap.xml")
    for entry in entries:
        print(f"{entry.url} (priority={entry.priority}, lastmod={entry.lastmod})")

    # Auto-discover and parse all sitemaps
    entries = await parser.discover_and_parse("https://example.com")
    print(f"Found {len(entries)} URLs across {parser.sitemap_count} sitemaps")

    # Parse sitemap index (follows child sitemaps)
    entries = await parser.parse_index("https://example.com/sitemap_index.xml")

    # Get just URLs
    urls = await parser.get_urls("https://example.com/sitemap.xml")
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import defusedxml.ElementTree as DefusedElementTree

logger = logging.getLogger("agentcrawl.crawling.sitemap")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class SitemapEntry:
    """
    A single URL entry from a sitemap.

    Attributes:
        url: The page URL.
        lastmod: Last modification date (ISO 8601 string).
        changefreq: Change frequency hint (always, hourly, daily, etc.).
        priority: Priority hint (0.0 to 1.0).
        source_sitemap: URL of the sitemap this entry came from.
        images: List of image URLs associated with this entry.
        alternates: Alternate language/version URLs.
    """

    url: str
    lastmod: str = ""
    changefreq: str = ""
    priority: float = 0.5
    source_sitemap: str = ""
    images: list[str] = field(default_factory=list)
    alternates: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "url": self.url,
            "priority": self.priority,
        }
        if self.lastmod:
            d["lastmod"] = self.lastmod
        if self.changefreq:
            d["changefreq"] = self.changefreq
        if self.source_sitemap:
            d["source_sitemap"] = self.source_sitemap
        if self.images:
            d["images"] = self.images
        if self.alternates:
            d["alternates"] = self.alternates
        return d


@dataclass
class SitemapInfo:
    """
    Metadata about a parsed sitemap.

    Attributes:
        url: Sitemap URL.
        entry_count: Number of URL entries.
        is_index: Whether this is a sitemap index.
        child_sitemaps: Child sitemap URLs (for indexes).
        parse_time_ms: Time to parse in milliseconds.
        error: Error message (if parsing failed).
    """

    url: str
    entry_count: int = 0
    is_index: bool = False
    child_sitemaps: list[str] = field(default_factory=list)
    parse_time_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "entry_count": self.entry_count,
            "is_index": self.is_index,
            "child_sitemaps": len(self.child_sitemaps),
            "parse_time_ms": round(self.parse_time_ms, 2),
            "error": self.error,
        }


@dataclass
class SitemapParseResult:
    """
    Complete result of a sitemap parsing operation.

    Attributes:
        entries: All parsed URL entries.
        sitemaps: Info about each sitemap parsed.
        total_urls: Total unique URLs found.
        total_sitemaps: Total sitemaps parsed.
        duration_ms: Total parsing time.
        errors: Errors encountered.
    """

    entries: list[SitemapEntry] = field(default_factory=list)
    sitemaps: list[SitemapInfo] = field(default_factory=list)
    total_urls: int = 0
    total_sitemaps: int = 0
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.total_urls = len(self.entries)
        self.total_sitemaps = len(self.sitemaps)

    @property
    def urls(self) -> list[str]:
        """Get just the URLs."""
        return [e.url for e in self.entries]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_urls": self.total_urls,
            "total_sitemaps": self.total_sitemaps,
            "duration_ms": round(self.duration_ms, 2),
            "errors": self.errors[:10],
            "sitemaps": [s.to_dict() for s in self.sitemaps],
        }


# ══════════════════════════════════════════════════════════════
# Sitemap Parser
# ══════════════════════════════════════════════════════════════


class SitemapParser:
    """
    Comprehensive sitemap.xml parser.

    Supports sitemap indexes, gzipped sitemaps, metadata extraction,
    and automatic discovery from robots.txt and common locations.

    Args:
        max_urls: Maximum URLs to extract.
        max_sitemaps: Maximum sitemaps to parse (for indexes).
        max_depth: Maximum nesting depth for sitemap indexes.
        max_concurrent: Maximum concurrent HTTP requests.
        timeout: HTTP request timeout in seconds.
        include_patterns: URL glob patterns to include.
        exclude_patterns: URL glob patterns to exclude.
        min_priority: Minimum priority to include (0.0 - 1.0).
        follow_robots_sitemap: Follow Sitemap: directives in robots.txt.

    Example:
        >>> parser = SitemapParser(max_urls=1000)
        >>> result = await parser.discover_and_parse("https://example.com")
        >>> print(f"Found {result.total_urls} URLs in {result.total_sitemaps} sitemaps")
    """

    # Common sitemap locations to try during auto-discovery
    COMMON_PATHS: tuple[str, ...] = (
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/sitemapindex.xml",
        "/sitemap/sitemap.xml",
        "/sitemap/sitemap_index.xml",
        "/wp-sitemap.xml",
        "/post-sitemap.xml",
        "/page-sitemap.xml",
        "/category-sitemap.xml",
        "/author-sitemap.xml",
        "/news-sitemap.xml",
        "/video-sitemap.xml",
        "/image-sitemap.xml",
        "/sitemap1.xml",
        "/sitemap.xml.gz",
    )

    # XML namespaces
    NS_SITEMAP = "http://www.sitemaps.org/schemas/sitemap/0.9"
    NS_IMAGE = "http://www.google.com/schemas/sitemap-image/1.1"
    NS_XHTML = "http://www.w3.org/1999/xhtml"

    def __init__(
        self,
        max_urls: int = 10_000,
        max_sitemaps: int = 100,
        max_depth: int = 3,
        max_concurrent: int = 10,
        timeout: float = 15.0,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        min_priority: float = 0.0,
        follow_robots_sitemap: bool = True,
    ):
        self._max_urls = max_urls
        self._max_sitemaps = max_sitemaps
        self._max_depth = max_depth
        self._max_concurrent = max_concurrent
        self._timeout = timeout
        self._include_patterns = include_patterns or []
        self._exclude_patterns = exclude_patterns or []
        self._min_priority = min_priority
        self._follow_robots_sitemap = follow_robots_sitemap

        # State
        self._parsed_sitemaps: set[str] = set()
        self._entries: list[SitemapEntry] = []
        self._sitemap_infos: list[SitemapInfo] = []
        self._errors: list[str] = []

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def sitemap_count(self) -> int:
        """Number of sitemaps parsed."""
        return len(self._sitemap_infos)

    @property
    def entry_count(self) -> int:
        """Number of URL entries found."""
        return len(self._entries)

    @property
    def errors(self) -> list[str]:
        """Errors encountered during parsing."""
        return list(self._errors)

    # ──────────────────────────────────────────────────────────
    # Main API
    # ──────────────────────────────────────────────────────────

    async def parse(self, sitemap_url: str) -> list[SitemapEntry]:
        """
        Parse a single sitemap URL.

        Automatically detects whether the sitemap is a regular
        sitemap or a sitemap index and handles accordingly.

        Args:
            sitemap_url: URL of the sitemap to parse.

        Returns:
            List of SitemapEntry objects.
        """
        self._reset()
        await self._parse_sitemap_url(sitemap_url, depth=0)
        return self._filter_entries(self._entries)

    async def parse_index(self, index_url: str) -> list[SitemapEntry]:
        """
        Parse a sitemap index and all its child sitemaps.

        Args:
            index_url: URL of the sitemap index.

        Returns:
            List of SitemapEntry objects from all child sitemaps.
        """
        self._reset()
        await self._parse_sitemap_url(index_url, depth=0)
        return self._filter_entries(self._entries)

    async def discover_and_parse(self, base_url: str) -> SitemapParseResult:
        """
        Auto-discover and parse all sitemaps for a domain.

        Tries robots.txt references, then common sitemap locations.

        Args:
            base_url: Website base URL.

        Returns:
            SitemapParseResult with all entries and metadata.
        """
        self._reset()
        start_time = time.perf_counter()

        try:
            parsed = urlparse(base_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            origin = base_url.rstrip("/")

        # Phase 1: robots.txt sitemap references
        if self._follow_robots_sitemap:
            await self._discover_from_robots(origin)

        # Phase 2: Common sitemap locations
        await self._discover_common_locations(origin)

        # Build result
        duration = (time.perf_counter() - start_time) * 1000
        filtered = self._filter_entries(self._entries)

        return SitemapParseResult(
            entries=filtered,
            sitemaps=list(self._sitemap_infos),
            duration_ms=duration,
            errors=list(self._errors),
        )

    async def get_urls(self, sitemap_url: str) -> list[str]:
        """
        Get just the URLs from a sitemap (convenience method).

        Args:
            sitemap_url: Sitemap URL.

        Returns:
            List of URL strings.
        """
        entries = await self.parse(sitemap_url)
        return [e.url for e in entries]

    # ──────────────────────────────────────────────────────────
    # Discovery
    # ──────────────────────────────────────────────────────────

    async def _discover_from_robots(self, origin: str) -> None:
        """Find sitemap references in robots.txt."""
        import httpx

        robots_url = f"{origin}/robots.txt"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(robots_url)
                if resp.status_code != 200:
                    return

                for line in resp.text.splitlines():
                    line = line.strip()
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url:
                            await self._parse_sitemap_url(sitemap_url, depth=0)

        except Exception as e:
            logger.debug("Robots.txt sitemap discovery failed: %s", e)

    async def _discover_common_locations(self, origin: str) -> None:
        """Try common sitemap locations."""
        import httpx

        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def _try_path(path: str) -> None:
            if len(self._parsed_sitemaps) >= self._max_sitemaps:
                return
            if len(self._entries) >= self._max_urls:
                return

            url = f"{origin}{path}"
            if url in self._parsed_sitemaps:
                return

            try:
                async with (
                    semaphore,
                    httpx.AsyncClient(
                        timeout=self._timeout,
                        follow_redirects=True,
                    ) as client,
                ):
                    resp = await client.head(url)
                    if resp.status_code == 200:
                        content_type = resp.headers.get("content-type", "")
                        if (
                            "xml" in content_type
                            or "gzip" in content_type
                            or path.endswith(".xml")
                            or path.endswith(".xml.gz")
                        ):
                            await self._parse_sitemap_url(url, depth=0)
            except Exception:
                logger.debug("Error checking sitemap path")

        tasks = [_try_path(path) for path in self.COMMON_PATHS]
        await asyncio.gather(*tasks, return_exceptions=True)

    # ──────────────────────────────────────────────────────────
    # Parsing
    # ──────────────────────────────────────────────────────────

    async def _parse_sitemap_url(self, url: str, depth: int) -> None:
        """
        Fetch and parse a sitemap URL.

        Args:
            url: Sitemap URL.
            depth: Current nesting depth (for sitemap indexes).
        """
        if url in self._parsed_sitemaps:
            return

        if len(self._parsed_sitemaps) >= self._max_sitemaps:
            logger.debug("Max sitemaps reached (%d)", self._max_sitemaps)
            return

        if depth > self._max_depth:
            logger.debug("Max sitemap depth reached (%d)", self._max_depth)
            return

        self._parsed_sitemaps.add(url)
        start_time = time.perf_counter()

        info = SitemapInfo(url=url)

        try:
            content = await self._fetch_content(url)
            if content is None:
                info.error = "Failed to fetch"
                self._errors.append(f"Fetch failed: {url}")
                self._sitemap_infos.append(info)
                return

            # Parse XML
            entries, child_urls, is_index = self._parse_xml(content, url)

            info.is_index = is_index
            info.child_sitemaps = child_urls
            info.entry_count = len(entries)

            if is_index:
                # Parse child sitemaps
                semaphore = asyncio.Semaphore(self._max_concurrent)
                tasks = [
                    self._parse_child(child_url, depth + 1, semaphore) for child_url in child_urls
                ]
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                # Add entries
                self._entries.extend(entries)

        except Exception as e:
            info.error = str(e)
            self._errors.append(f"Parse error {url}: {e}")
            logger.debug("Sitemap parse error %s: %s", url, e)

        info.parse_time_ms = (time.perf_counter() - start_time) * 1000
        self._sitemap_infos.append(info)

    async def _parse_child(
        self,
        url: str,
        depth: int,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Parse a child sitemap with concurrency control."""
        async with semaphore:
            await self._parse_sitemap_url(url, depth)

    async def _fetch_content(self, url: str) -> str | None:
        """
        Fetch sitemap content, handling gzip compression.

        Args:
            url: Sitemap URL.

        Returns:
            Decompressed XML string, or None on failure.
        """
        import httpx

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)

                if resp.status_code != 200:
                    return None

                content = resp.content

                # Check for gzip
                content_encoding = resp.headers.get("content-encoding", "")
                resp.headers.get("content-type", "")

                if "gzip" in content_encoding or url.endswith(".gz"):
                    with contextlib.suppress(Exception):
                        content = gzip.decompress(content)

                # Also try gzip decompression if content starts with gzip magic
                if content[:2] == b"\x1f\x8b":
                    with contextlib.suppress(Exception):
                        content = gzip.decompress(content)

                return content.decode("utf-8", errors="replace")

        except Exception as e:
            logger.debug("Fetch failed %s: %s", url, e)
            return None

    def _parse_xml(
        self,
        xml_content: str,
        source_url: str,
    ) -> tuple[list[SitemapEntry], list[str], bool]:
        """
        Parse sitemap XML content.

        Args:
            xml_content: Raw XML string.
            source_url: Source sitemap URL.

        Returns:
            Tuple of (entries, child_sitemap_urls, is_index).
        """
        # Clean XML
        xml_content = re.sub(r"<\?xml[^?]*\?>", "", xml_content).strip()
        # Remove BOM
        xml_content = xml_content.lstrip("\ufeff")

        try:
            root = DefusedElementTree.fromstring(xml_content)
        except DefusedElementTree.ParseError as e:
            raise ValueError(f"XML parse error: {e}") from e

        # Detect namespace
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        # Check for sitemap index
        sitemap_tags = root.findall(f"{ns}sitemap")
        if sitemap_tags:
            child_urls = []
            for sitemap in sitemap_tags:
                loc = sitemap.find(f"{ns}loc")
                if loc is not None and loc.text:
                    child_urls.append(loc.text.strip())
            return [], child_urls, True

        # Regular sitemap — extract URL entries
        entries: list[SitemapEntry] = []
        url_tags = root.findall(f"{ns}url")

        for url_tag in url_tags:
            if len(self._entries) + len(entries) >= self._max_urls:
                break

            loc = url_tag.find(f"{ns}loc")
            if loc is None or not loc.text:
                continue

            url = loc.text.strip()

            # Extract metadata
            lastmod = ""
            lastmod_el = url_tag.find(f"{ns}lastmod")
            if lastmod_el is not None and lastmod_el.text:
                lastmod = lastmod_el.text.strip()

            changefreq = ""
            changefreq_el = url_tag.find(f"{ns}changefreq")
            if changefreq_el is not None and changefreq_el.text:
                changefreq = changefreq_el.text.strip()

            priority = 0.5
            priority_el = url_tag.find(f"{ns}priority")
            if priority_el is not None and priority_el.text:
                with contextlib.suppress(ValueError):
                    priority = float(priority_el.text.strip())

            # Extract images (Google image sitemap extension)
            images: list[str] = []
            for image_tag in url_tag.iter():
                if "image" in image_tag.tag.lower():
                    img_loc = image_tag.find(f"{{{self.NS_IMAGE}}}loc")
                    if img_loc is None:
                        # Try without namespace
                        for child in image_tag:
                            if "loc" in child.tag.lower() and child.text:
                                images.append(child.text.strip())
                                break
                    elif img_loc.text:
                        images.append(img_loc.text.strip())

            # Extract alternates (xhtml:link rel="alternate")
            alternates: list[dict[str, str]] = []
            for link_tag in url_tag.iter():
                if "link" in link_tag.tag.lower():
                    rel = link_tag.get("rel", "")
                    href = link_tag.get("href", "")
                    hreflang = link_tag.get("hreflang", "")
                    if rel == "alternate" and href:
                        alt: dict[str, str] = {"href": href}
                        if hreflang:
                            alt["hreflang"] = hreflang
                        alternates.append(alt)

            entries.append(
                SitemapEntry(
                    url=url,
                    lastmod=lastmod,
                    changefreq=changefreq,
                    priority=priority,
                    source_sitemap=source_url,
                    images=images,
                    alternates=alternates,
                )
            )

        return entries, [], False

    # ──────────────────────────────────────────────────────────
    # Filtering
    # ──────────────────────────────────────────────────────────

    def _filter_entries(self, entries: list[SitemapEntry]) -> list[SitemapEntry]:
        """Apply filters to sitemap entries."""
        import fnmatch

        filtered: list[SitemapEntry] = []
        seen_urls: set[str] = set()

        for entry in entries:
            # Deduplicate
            if entry.url in seen_urls:
                continue
            seen_urls.add(entry.url)

            # Priority filter
            if entry.priority < self._min_priority:
                continue

            # Include patterns
            if self._include_patterns:
                try:
                    path = urlparse(entry.url).path
                except Exception:
                    path = entry.url

                if not any(
                    fnmatch.fnmatch(path, p) or fnmatch.fnmatch(entry.url, p)
                    for p in self._include_patterns
                ):
                    continue

            # Exclude patterns
            if self._exclude_patterns:
                try:
                    path = urlparse(entry.url).path
                except Exception:
                    path = entry.url

                if any(
                    fnmatch.fnmatch(path, p) or fnmatch.fnmatch(entry.url, p)
                    for p in self._exclude_patterns
                ):
                    continue

            filtered.append(entry)

        return filtered

    # ──────────────────────────────────────────────────────────
    # Reset
    # ──────────────────────────────────────────────────────────

    def _reset(self) -> None:
        """Reset parser state."""
        self._parsed_sitemaps.clear()
        self._entries.clear()
        self._sitemap_infos.clear()
        self._errors.clear()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get parser diagnostics."""
        return {
            "sitemaps_parsed": len(self._sitemap_infos),
            "entries_found": len(self._entries),
            "errors": self._errors[:10],
            "sitemaps": [s.to_dict() for s in self._sitemap_infos],
            "config": {
                "max_urls": self._max_urls,
                "max_sitemaps": self._max_sitemaps,
                "max_depth": self._max_depth,
                "max_concurrent": self._max_concurrent,
                "min_priority": self._min_priority,
                "follow_robots_sitemap": self._follow_robots_sitemap,
            },
        }

    def get_priority_distribution(self) -> dict[str, int]:
        """Get distribution of URL priorities."""
        dist: dict[str, int] = {
            "0.0-0.2": 0,
            "0.2-0.4": 0,
            "0.4-0.6": 0,
            "0.6-0.8": 0,
            "0.8-1.0": 0,
        }
        for entry in self._entries:
            p = entry.priority
            if p < 0.2:
                dist["0.0-0.2"] += 1
            elif p < 0.4:
                dist["0.2-0.4"] += 1
            elif p < 0.6:
                dist["0.4-0.6"] += 1
            elif p < 0.8:
                dist["0.6-0.8"] += 1
            else:
                dist["0.8-1.0"] += 1
        return dist

    def get_changefreq_distribution(self) -> dict[str, int]:
        """Get distribution of changefreq values."""
        dist: dict[str, int] = {}
        for entry in self._entries:
            freq = entry.changefreq or "unset"
            dist[freq] = dist.get(freq, 0) + 1
        return dist

    def __repr__(self) -> str:
        return (
            f"SitemapParser(sitemaps={len(self._sitemap_infos)}, "
            f"entries={len(self._entries)}, "
            f"errors={len(self._errors)})"
        )
