"""
AgentCrawl — Search API Routes
==================================

Handles web search operations via the REST API.

Endpoints:
    POST /search — Search the web

Supported providers:
    - duckduckgo (default, no API key)
    - tavily (AI-optimized)
    - brave
    - exa (neural search)
    - searxng (self-hosted)

Usage:
    Registered automatically by server/app.py or router.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("agentcrawl.server.search")


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class SearchRequest(BaseModel):
    """Request body for POST /search."""

    query: str = Field(..., description="Search query string", min_length=1)
    max_results: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of results",
    )
    provider: str = Field(
        default="duckduckgo",
        description="Search provider: duckduckgo, tavily, brave, exa, searxng",
    )
    api_key: str = Field(
        default="",
        description="Provider API key (if required)",
    )
    scrape_results: bool = Field(
        default=False,
        description="Scrape each result page for full content",
    )
    include_answer: bool = Field(
        default=False,
        description="Include direct answer (provider-dependent)",
    )
    language: str = Field(
        default="en",
        description="Search language code",
    )
    time_range: str = Field(
        default="",
        description="Time range filter: day, week, month, year",
    )
    safe_search: bool = Field(
        default=False,
        description="Enable safe search",
    )


class SearchResultItem(BaseModel):
    """A single search result."""

    url: str
    title: str
    snippet: str
    position: int = 0
    domain: str = ""
    score: float = 0.0
    published_date: str = ""

    # Populated when scrape_results=True
    markdown: str = ""
    word_count: int = 0
    scrape_success: bool | None = None


class SearchResponse(BaseModel):
    """Response body for POST /search."""

    query: str
    results: list[SearchResultItem]
    total_results: int
    answer: str = ""
    provider: str
    duration_ms: float
    error: str | None = None


# ══════════════════════════════════════════════════════════════
# Handler
# ══════════════════════════════════════════════════════════════

async def handle_search(body: dict[str, Any]) -> JSONResponse:
    """
    Handle POST /search.

    Searches the web using the specified provider and returns
    structured results.

    Args:
        body: Request body dictionary.

    Returns:
        JSONResponse with search results.
    """
    # Validate request
    try:
        request = SearchRequest(**body)
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

    # Validate provider
    valid_providers = {"duckduckgo", "tavily", "brave", "exa", "searxng", "google"}
    if request.provider not in valid_providers:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_PROVIDER",
                    "message": (
                        f"Invalid provider: '{request.provider}'. "
                        f"Must be one of: {', '.join(sorted(valid_providers))}"
                    ),
                }
            },
        )

    # Execute search
    start = time.perf_counter()

    try:
        from agentcrawl.search.engine import SearchEngine

        engine = SearchEngine(
            provider=request.provider,
            api_key=request.api_key,
        )

        # Build provider-specific kwargs
        search_kwargs: dict[str, Any] = {}
        if request.include_answer:
            search_kwargs["include_answer"] = True
        if request.language:
            search_kwargs["language"] = request.language
        if request.time_range:
            search_kwargs["time_range"] = request.time_range

        response = await engine.search_with_response(
            query=request.query,
            max_results=request.max_results,
            **search_kwargs,
        )

    except ValueError as e:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "PROVIDER_ERROR",
                    "message": str(e),
                }
            },
        )
    except Exception as e:
        logger.error("Search failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "SEARCH_FAILED",
                    "message": str(e),
                }
            },
        )

    elapsed = (time.perf_counter() - start) * 1000

    # Build result items
    result_items: list[dict[str, Any]] = []
    for r in response.results:
        item: dict[str, Any] = {
            "url": r.url,
            "title": r.title,
            "snippet": r.snippet,
            "position": r.position,
            "domain": r.domain,
            "score": r.score,
            "published_date": r.published_date,
        }
        result_items.append(item)

    # Optionally scrape results
    if request.scrape_results and result_items:
        result_items = await _scrape_search_results(result_items)

    # Build response
    response_data = {
        "query": request.query,
        "results": result_items,
        "total_results": len(result_items),
        "answer": response.answer,
        "provider": request.provider,
        "duration_ms": round(elapsed, 2),
        "error": response.error,
    }

    logger.info(
        "Search: \"%s\" (%s) → %d results (%.0fms)",
        request.query[:50],
        request.provider,
        len(result_items),
        elapsed,
    )

    return JSONResponse(status_code=200, content=response_data)


# ══════════════════════════════════════════════════════════════
# Result Scraping
# ══════════════════════════════════════════════════════════════

async def _scrape_search_results(
    results: list[dict[str, Any]],
    max_scrape: int = 5,
) -> list[dict[str, Any]]:
    """
    Scrape search result pages for full content.

    Args:
        results: Search result items.
        max_scrape: Maximum pages to scrape.

    Returns:
        Results with scraped content added.
    """
    from agentcrawl import CrawlEngine, CrawlerConfig

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        content_filter="pruning",
        cache=True,
        cache_ttl=3600,
        timeout=15,
    )

    urls = [r["url"] for r in results[:max_scrape] if r.get("url")]

    if not urls:
        return results

    try:
        async with CrawlEngine.default() as engine:
            scrape_results = await engine.batch_scrape(
                urls,
                config=config,
                max_concurrent=3,
            )

            # Map results by URL
            scrape_map = {r.url: r for r in scrape_results}

            for item in results:
                url = item.get("url", "")
                if url in scrape_map:
                    sr = scrape_map[url]
                    item["markdown"] = sr.markdown[:3000] if sr.success else ""
                    item["word_count"] = sr.word_count
                    item["scrape_success"] = sr.success

    except Exception as e:
        logger.warning("Failed to scrape search results: %s", e)
        for item in results:
            item["scrape_success"] = False

    return results
