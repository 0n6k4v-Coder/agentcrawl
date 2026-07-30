"""
AgentCrawl — Map API Routes
===============================

Handles website URL discovery via the REST API.

Endpoints:
    POST /map — Discover all URLs on a website

Discovery methods:
    - sitemap.xml parsing
    - robots.txt parsing
    - Link crawling (breadth-first)

Usage:
    Registered automatically by server/app.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("agentcrawl.server.map")


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class MapRequest(BaseModel):
    """Request body for POST /map."""

    url: str = Field(..., description="Website URL to discover URLs from")
    max_urls: int = Field(
        default=500,
        ge=1,
        le=10000,
        description="Maximum URLs to discover",
    )
    use_sitemap: bool = Field(
        default=True,
        description="Parse sitemap.xml for URLs",
    )
    use_robots: bool = Field(
        default=True,
        description="Parse robots.txt for URLs",
    )
    use_link_crawl: bool = Field(
        default=True,
        description="Crawl links to discover more URLs",
    )
    include_patterns: list[str] = Field(
        default_factory=list,
        description="URL include patterns (glob)",
    )
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="URL exclude patterns (glob)",
    )
    same_domain: bool = Field(
        default=True,
        description="Restrict discovery to the same domain",
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum crawl depth for link discovery",
    )
    timeout: int = Field(
        default=60,
        description="Overall timeout in seconds",
    )


class MapResponse(BaseModel):
    """Response body for POST /map."""

    total_urls: int
    sitemap_urls: int
    robots_urls: int
    crawl_urls: int
    sources: list[str]
    duration_ms: float
    urls: list[str]


# ══════════════════════════════════════════════════════════════
# Handler
# ══════════════════════════════════════════════════════════════

async def handle_map(
    engine: Any,
    body: dict[str, Any],
) -> JSONResponse:
    """
    Handle POST /map.

    Discovers URLs on a website using sitemap, robots.txt,
    and link crawling.

    Args:
        engine: CrawlEngine instance.
        body: Request body dictionary.

    Returns:
        JSONResponse with discovered URLs.
    """
    # Validate request
    try:
        request = MapRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid request: {e}",
                }
            },
        )

    # Check engine
    if engine is None or not engine.is_started:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "Engine not started",
                }
            },
        )

    # Execute discovery
    start = time.perf_counter()

    try:
        result = await _discover_urls(engine, request)
    except Exception as e:
        logger.error("URL discovery failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "MAP_FAILED",
                    "message": str(e),
                }
            },
        )

    elapsed = (time.perf_counter() - start) * 1000

    # Build response
    response_data = {
        "total_urls": result["total_urls"],
        "sitemap_urls": result["sitemap_urls"],
        "robots_urls": result["robots_urls"],
        "crawl_urls": result["crawl_urls"],
        "sources": result["sources"],
        "duration_ms": round(elapsed, 2),
        "urls": result["urls"],
    }

    logger.info(
        "Map: %s → %d URLs (sitemap=%d, robots=%d, crawl=%d) in %.0fms",
        request.url,
        result["total_urls"],
        result["sitemap_urls"],
        result["robots_urls"],
        result["crawl_urls"],
        elapsed,
    )

    return JSONResponse(status_code=200, content=response_data)


# ══════════════════════════════════════════════════════════════
# Discovery Logic
# ══════════════════════════════════════════════════════════════

async def _discover_urls(
    engine: Any,
    request: MapRequest,
) -> dict[str, Any]:
    """
    Execute URL discovery using multiple methods.

    Args:
        engine: CrawlEngine instance.
        request: Validated request.

    Returns:
        Discovery result dictionary.
    """
    from agentcrawl.crawling.domain_mapper import DomainMapper
    from agentcrawl.utils.url import normalize_url

    # Use DomainMapper for unified discovery
    mapper = DomainMapper(
        max_urls=request.max_urls,
        use_sitemap=request.use_sitemap,
        use_robots=request.use_robots,
        use_link_crawl=request.use_link_crawl,
        max_depth=request.max_depth,
    )

    # Discover
    urls = await mapper.discover(request.url)

    # Apply filters
    if request.include_patterns or request.exclude_patterns:
        urls = _filter_urls(
            urls,
            request.include_patterns,
            request.exclude_patterns,
        )

    # Apply same_domain filter
    if request.same_domain:
        from agentcrawl.utils.url import get_base_domain

        base_domain = get_base_domain(request.url)
        urls = [
            u for u in urls
            if get_base_domain(u) == base_domain
        ]

    # Deduplicate and normalize
    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in urls:
        normalized = normalize_url(url)
        if normalized not in seen:
            seen.add(normalized)
            unique_urls.append(url)

    # Limit
    unique_urls = unique_urls[:request.max_urls]

    # Determine sources
    sources: list[str] = []
    if request.use_sitemap:
        sources.append("sitemap")
    if request.use_robots:
        sources.append("robots")
    if request.use_link_crawl:
        sources.append("crawl")

    # Count by source (approximate)
    sitemap_count = 0
    robots_count = 0
    crawl_count = len(unique_urls)

    # If we have sitemap/robots info from mapper, use it
    if hasattr(mapper, "_sitemap_urls"):
        sitemap_count = len(mapper._sitemap_urls)
    if hasattr(mapper, "_robots_urls"):
        robots_count = len(mapper._robots_urls)

    crawl_count = max(0, len(unique_urls) - sitemap_count - robots_count)

    return {
        "total_urls": len(unique_urls),
        "sitemap_urls": sitemap_count,
        "robots_urls": robots_count,
        "crawl_urls": crawl_count,
        "sources": sources,
        "urls": unique_urls,
    }


def _filter_urls(
    urls: list[str],
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> list[str]:
    """
    Filter URLs by include/exclude glob patterns.

    Args:
        urls: List of URLs.
        include_patterns: Patterns to include.
        exclude_patterns: Patterns to exclude.

    Returns:
        Filtered URL list.
    """
    from agentcrawl.utils.url import url_matches_pattern

    result: list[str] = []

    for url in urls:
        # Include check
        if include_patterns and not any(url_matches_pattern(url, p) for p in include_patterns):
            continue

        # Exclude check
        if exclude_patterns and any(url_matches_pattern(url, p) for p in exclude_patterns):
            continue

        result.append(url)

    return result
