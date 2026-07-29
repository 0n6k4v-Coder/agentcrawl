"""
AgentCrawl — Batch API Routes
=================================

Handles batch scraping operations via the REST API.

Endpoints:
    POST /batch/scrape — Scrape multiple URLs concurrently

Usage:
    Registered automatically by server/app.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("agentcrawl.server.batch")


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class BatchScrapeRequest(BaseModel):
    """Request body for POST /batch/scrape."""

    urls: list[str] = Field(
        ...,
        description="List of URLs to scrape",
        min_length=1,
        max_length=100,
    )
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
        description="Include page metadata",
    )
    only_main_content: bool = Field(
        default=True,
        description="Extract only main content",
    )
    content_filter: str = Field(
        default="none",
        description="Content filter: none, pruning, bm25",
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
    max_concurrent: int = Field(
        default=5,
        description="Maximum concurrent scrapes",
        ge=1,
        le=20,
    )
    cache: bool = Field(
        default=True,
        description="Enable caching",
    )
    timeout: int = Field(
        default=30,
        description="Per-page timeout in seconds",
    )


class BatchScrapeResultItem(BaseModel):
    """Single result in a batch response."""

    url: str
    success: bool
    status_code: int = 0
    markdown: str = ""
    html: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, Any] = Field(default_factory=dict)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    word_count: int = 0
    token_count: int = 0
    response_time_ms: float = 0.0
    cached: bool = False
    error: str | None = None


class BatchScrapeResponse(BaseModel):
    """Response body for POST /batch/scrape."""

    total: int
    successful: int
    failed: int
    duration_ms: float
    results: list[BatchScrapeResultItem]


# ══════════════════════════════════════════════════════════════
# Handler
# ══════════════════════════════════════════════════════════════

async def handle_batch_scrape(
    engine: Any,
    body: dict[str, Any],
) -> JSONResponse:
    """
    Handle POST /batch/scrape.

    Scrapes multiple URLs concurrently and returns all results.

    Args:
        engine: CrawlEngine instance.
        body: Request body dictionary.

    Returns:
        JSONResponse with batch results.
    """
    # Validate request
    try:
        request = BatchScrapeRequest(**body)
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

    # Build config
    from agentcrawl.config.crawler_config import CrawlerConfig

    config = CrawlerConfig(
        output_format=request.output_format,
        include_links=request.include_links,
        include_metadata=request.include_metadata,
        only_main_content=request.only_main_content,
        content_filter=request.content_filter,
        chunker=request.chunker,
        chunk_max_size=request.chunk_max_size,
        chunk_overlap=request.chunk_overlap,
        cache=request.cache,
        timeout=request.timeout,
    )

    # Execute batch scrape
    start = time.perf_counter()

    try:
        results = await engine.batch_scrape(
            request.urls,
            config=config,
            max_concurrent=request.max_concurrent,
        )
    except Exception as e:
        logger.error("Batch scrape failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "BATCH_SCRAPE_FAILED",
                    "message": str(e),
                }
            },
        )

    elapsed = (time.perf_counter() - start) * 1000

    # Build response
    result_items: list[dict[str, Any]] = []
    successful = 0
    failed = 0

    for result in results:
        item: dict[str, Any] = {
            "url": result.url,
            "success": result.success,
            "status_code": result.status_code,
            "word_count": result.word_count,
            "token_count": result.token_count,
            "response_time_ms": round(result.response_time_ms, 2),
            "cached": result.cached,
            "error": result.error,
        }

        if result.success:
            successful += 1
            item["markdown"] = result.markdown
            item["html"] = result.html
            item["text"] = result.text
            item["metadata"] = result.metadata
            item["links"] = result.links
            item["chunks"] = result.chunks
        else:
            failed += 1

        result_items.append(item)

    response_data = {
        "total": len(results),
        "successful": successful,
        "failed": failed,
        "duration_ms": round(elapsed, 2),
        "results": result_items,
    }

    logger.info(
        "Batch scrape: %d URLs, %d ok, %d fail (%.0fms)",
        len(results),
        successful,
        failed,
        elapsed,
    )

    return JSONResponse(status_code=200, content=response_data)
