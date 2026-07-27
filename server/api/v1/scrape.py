"""
AgentCrawl — Scrape API Routes
==================================

Handles single-page scraping operations via the REST API.

Endpoints:
    POST /scrape — Scrape a single page

Usage:
    Registered automatically by server/app.py or router.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("agentcrawl.server.scrape")


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class ScrapeRequest(BaseModel):
    """Request body for POST /scrape."""

    url: str = Field(..., description="URL to scrape")
    output_format: str = Field(
        default="markdown",
        description="Output format: markdown, json, html, text",
    )
    include_links: bool = Field(
        default=True,
        description="Include extracted links",
    )
    include_metadata: bool = Field(
        default=True,
        description="Include page metadata (title, description, og:tags)",
    )
    include_screenshot: bool = Field(
        default=False,
        description="Capture a page screenshot (base64)",
    )
    include_citations: bool = Field(
        default=False,
        description="Extract citation references [1], [2], etc.",
    )
    only_main_content: bool = Field(
        default=True,
        description="Extract only main content (skip nav, footer, sidebar)",
    )
    selectors: list[str] = Field(
        default_factory=list,
        description="CSS selectors to target specific content",
    )
    exclude_selectors: list[str] = Field(
        default_factory=list,
        description="CSS selectors to exclude from extraction",
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Browser actions to execute before extraction",
    )
    content_filter: str = Field(
        default="none",
        description="Content filter: none, pruning, bm25",
    )
    content_filter_query: str = Field(
        default="",
        description="Query for BM25 content filter",
    )
    chunker: str = Field(
        default="none",
        description="Chunker: none, fixed, sentence, topic, regex",
    )
    chunk_max_size: int = Field(
        default=1000,
        description="Maximum chunk size in tokens",
    )
    chunk_overlap: int = Field(
        default=200,
        description="Chunk overlap in tokens",
    )
    cache: bool = Field(
        default=True,
        description="Enable response caching",
    )
    cache_ttl: int = Field(
        default=3600,
        description="Cache TTL in seconds",
    )
    timeout: int = Field(
        default=30,
        description="Page load timeout in seconds",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Custom HTTP headers",
    )


class ScrapeResponse(BaseModel):
    """Response body for POST /scrape."""

    url: str
    success: bool
    status_code: int = 0
    markdown: str = ""
    html: str = ""
    raw_html: str = ""
    text: str = ""
    json: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    extracted_data: Any = None
    screenshot: str = ""
    error: str | None = None
    response_time_ms: float = 0.0
    word_count: int = 0
    token_count: int = 0
    cached: bool = False
    request_id: str = ""


# ══════════════════════════════════════════════════════════════
# Handler
# ══════════════════════════════════════════════════════════════

async def handle_scrape(
    engine: Any,
    body: dict[str, Any],
) -> JSONResponse:
    """
    Handle POST /scrape.

    Scrapes a single page and returns processed content.

    Args:
        engine: CrawlEngine instance.
        body: Request body dictionary.

    Returns:
        JSONResponse with scrape result.
    """
    # Validate request
    try:
        request = ScrapeRequest(**body)
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

    # Validate URL
    if not request.url or not request.url.strip():
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "URL is required",
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

    # Build CrawlerConfig
    from agentcrawl.config.crawler_config import CrawlerConfig

    config = CrawlerConfig(
        output_format=request.output_format,
        include_links=request.include_links,
        include_metadata=request.include_metadata,
        include_screenshot=request.include_screenshot,
        include_citations=request.include_citations,
        only_main_content=request.only_main_content,
        selectors=request.selectors,
        exclude_selectors=request.exclude_selectors,
        actions=request.actions,
        content_filter=request.content_filter,
        content_filter_query=request.content_filter_query,
        chunker=request.chunker,
        chunk_max_size=request.chunk_max_size,
        chunk_overlap=request.chunk_overlap,
        cache=request.cache,
        cache_ttl=request.cache_ttl,
        timeout=request.timeout,
    )

    # Execute scrape
    start = time.perf_counter()

    try:
        result = await engine.scrape(request.url, config)
    except Exception as e:
        logger.error("Scrape failed for %s: %s", request.url, e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "SCRAPE_FAILED",
                    "message": str(e),
                    "url": request.url,
                }
            },
        )

    elapsed = (time.perf_counter() - start) * 1000

    # Build response
    response_data: dict[str, Any] = {
        "url": result.url,
        "success": result.success,
        "status_code": result.status_code,
        "response_time_ms": round(result.response_time_ms or elapsed, 2),
        "word_count": result.word_count,
        "token_count": result.token_count,
        "cached": result.cached,
        "request_id": result.request_id,
        "error": result.error,
    }

    # Include content fields based on output_format
    if result.success:
        response_data["markdown"] = result.markdown
        response_data["html"] = result.html
        response_data["text"] = result.text

        if request.include_metadata:
            response_data["metadata"] = result.metadata

        if request.include_links:
            response_data["links"] = result.links

        if request.include_citations:
            response_data["citations"] = result.citations

        if result.chunks:
            response_data["chunks"] = result.chunks

        if result.extracted_data is not None:
            response_data["extracted_data"] = _serialize(result.extracted_data)

        if request.include_screenshot and result.screenshot:
            response_data["screenshot"] = result.screenshot

    logger.info(
        "Scrape: %s → %s (%d words, %.0fms, cached=%s)",
        request.url,
        "ok" if result.success else f"fail({result.error})",
        result.word_count,
        elapsed,
        result.cached,
    )

    return JSONResponse(status_code=200, content=response_data)


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

def _serialize(data: Any) -> Any:
    """Serialize data to JSON-compatible format."""
    if data is None:
        return None

    if hasattr(data, "model_dump"):
        return data.model_dump()

    if hasattr(data, "dict"):
        return data.dict()

    if isinstance(data, list):
        return [_serialize(item) for item in data]

    if isinstance(data, dict):
        return {k: _serialize(v) for k, v in data.items()}

    return data