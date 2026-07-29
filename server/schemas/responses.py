"""
AgentCrawl — Response Schemas
=================================

Pydantic models for all REST API response bodies.

Each schema includes:
    - Typed fields with descriptions
    - Serialization helpers
    - Error response format
    - Pagination metadata

Usage:
    from server.schemas.responses import (
        ScrapeResponse,
        ErrorResponse,
        CrawlJobStatusResponse,
    )

    # Build response
    response = ScrapeResponse(
        url="https://example.com",
        success=True,
        markdown="# Example",
        word_count=100,
    )
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ══════════════════════════════════════════════════════════════
# Error
# ══════════════════════════════════════════════════════════════

class ErrorDetail(BaseModel):
    """Error detail object."""

    code: str = Field(
        ...,
        description="Machine-readable error code",
        examples=["SCRAPE_FAILED"],
    )
    message: str = Field(
        ...,
        description="Human-readable error message",
        examples=["Page returned status 404"],
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional error context",
    )
    request_id: str = Field(
        default="",
        description="Request identifier for debugging",
    )


class ErrorResponse(BaseModel):
    """
    Standard error response.

    Example:
        {
            "error": {
                "code": "SCRAPE_FAILED",
                "message": "Page returned status 404",
                "details": {"url": "https://example.com", "status_code": 404},
                "request_id": "req_abc123"
            }
        }
    """

    error: ErrorDetail


# ══════════════════════════════════════════════════════════════
# Scrape
# ══════════════════════════════════════════════════════════════

class ScrapeResponse(BaseModel):
    """
    Response for POST /scrape.

    Example:
        {
            "url": "https://example.com",
            "success": true,
            "status_code": 200,
            "markdown": "# Example Domain\\n\\n...",
            "metadata": {"title": "Example Domain"},
            "word_count": 125,
            "response_time_ms": 2340.5
        }
    """

    url: str = Field(description="Scraped URL")
    success: bool = Field(description="Whether the scrape succeeded")
    status_code: int = Field(default=0, description="HTTP status code")
    markdown: str = Field(default="", description="Clean Markdown content")
    html: str = Field(default="", description="Cleaned HTML content")
    text: str = Field(default="", description="Plain text content")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Page metadata (title, description, og:tags)",
    )
    links: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted links (internal, external, all)",
    )
    citations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Citation references",
    )
    chunks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Content chunks (for RAG)",
    )
    extracted_data: Any = Field(
        default=None,
        description="Extracted structured data",
    )
    screenshot: str = Field(
        default="",
        description="Base64-encoded screenshot",
    )
    error: str | None = Field(default=None, description="Error message")
    response_time_ms: float = Field(default=0.0, description="Response time in ms")
    word_count: int = Field(default=0, description="Word count")
    token_count: int = Field(default=0, description="Estimated token count")
    cached: bool = Field(default=False, description="Whether result was cached")
    request_id: str = Field(default="", description="Request identifier")


# ══════════════════════════════════════════════════════════════
# Crawl
# ══════════════════════════════════════════════════════════════

class CrawlJobStatusResponse(BaseModel):
    """
    Response for GET /crawl/{job_id} (in-progress).

    Example:
        {
            "job_id": "job_a1b2c3d4",
            "status": "running",
            "pages_crawled": 15,
            "total_pages": 50,
            "progress": 0.30
        }
    """

    job_id: str = Field(description="Job identifier")
    status: str = Field(
        description="Job status: queued, running, completed, failed, cancelled",
    )
    start_url: str = Field(default="", description="Starting URL")
    strategy: str = Field(default="bfs", description="Crawl strategy")
    pages_crawled: int = Field(default=0, description="Pages crawled so far")
    pages_failed: int = Field(default=0, description="Pages failed")
    total_pages: int = Field(default=0, description="Total pages (when known)")
    progress: float = Field(default=0.0, description="Progress ratio (0.0-1.0)")
    elapsed_ms: float = Field(default=0.0, description="Elapsed time in ms")
    created_at: float = Field(default=0.0, description="Creation timestamp")


class CrawlPageResult(BaseModel):
    """A single page result within a crawl."""

    url: str = Field(description="Page URL")
    success: bool = Field(description="Whether the page was scraped")
    status_code: int = Field(default=0, description="HTTP status code")
    markdown: str = Field(default="", description="Page content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Page metadata")
    word_count: int = Field(default=0, description="Word count")
    token_count: int = Field(default=0, description="Token count")
    response_time_ms: float = Field(default=0.0, description="Response time")
    error: str | None = Field(default=None, description="Error message")


class CrawlJobResultResponse(BaseModel):
    """
    Response for GET /crawl/{job_id} (completed).

    Example:
        {
            "job_id": "job_a1b2c3d4",
            "status": "completed",
            "total_pages": 42,
            "successful_pages": 40,
            "total_words": 15000,
            "pages": [...]
        }
    """

    job_id: str = Field(description="Job identifier")
    status: str = Field(description="Job status")
    start_url: str = Field(default="", description="Starting URL")
    strategy: str = Field(default="bfs", description="Crawl strategy")
    total_pages: int = Field(default=0, description="Total pages")
    successful_pages: int = Field(default=0, description="Successful pages")
    failed_pages: int = Field(default=0, description="Failed pages")
    total_words: int = Field(default=0, description="Total words")
    total_tokens: int = Field(default=0, description="Total tokens")
    duration_ms: float = Field(default=0.0, description="Total duration")
    error: str | None = Field(default=None, description="Error message")
    pages: list[CrawlPageResult] = Field(
        default_factory=list,
        description="Page results",
    )


class CrawlStartResponse(BaseModel):
    """
    Response for POST /crawl (202 Accepted).

    Example:
        {
            "job_id": "job_a1b2c3d4",
            "status": "queued",
            "message": "Crawl job queued"
        }
    """

    job_id: str = Field(description="Job identifier")
    status: str = Field(default="queued", description="Initial status")
    message: str = Field(default="Crawl job queued", description="Status message")


# ══════════════════════════════════════════════════════════════
# Map
# ══════════════════════════════════════════════════════════════

class MapResponse(BaseModel):
    """
    Response for POST /map.

    Example:
        {
            "total_urls": 245,
            "sitemap_urls": 200,
            "robots_urls": 5,
            "crawl_urls": 40,
            "urls": ["https://docs.example.com/guide", ...]
        }
    """

    total_urls: int = Field(description="Total URLs discovered")
    sitemap_urls: int = Field(default=0, description="URLs from sitemap")
    robots_urls: int = Field(default=0, description="URLs from robots.txt")
    crawl_urls: int = Field(default=0, description="URLs from link crawling")
    sources: list[str] = Field(
        default_factory=list,
        description="Discovery sources used",
    )
    duration_ms: float = Field(default=0.0, description="Discovery duration")
    urls: list[str] = Field(
        default_factory=list,
        description="Discovered URLs",
    )


# ══════════════════════════════════════════════════════════════
# Search
# ══════════════════════════════════════════════════════════════

class SearchResultItem(BaseModel):
    """A single search result."""

    url: str = Field(description="Result URL")
    title: str = Field(default="", description="Page title")
    snippet: str = Field(default="", description="Text snippet")
    position: int = Field(default=0, description="Result position")
    domain: str = Field(default="", description="Domain name")
    score: float = Field(default=0.0, description="Relevance score")
    published_date: str = Field(default="", description="Publication date")

    # Populated when scrape_results=True
    markdown: str = Field(default="", description="Scraped content")
    word_count: int = Field(default=0, description="Word count")
    scrape_success: bool | None = Field(default=None, description="Scrape status")


class SearchResponse(BaseModel):
    """
    Response for POST /search.

    Example:
        {
            "query": "python asyncio",
            "results": [...],
            "total_results": 5,
            "provider": "duckduckgo",
            "duration_ms": 1200
        }
    """

    query: str = Field(description="Search query")
    results: list[SearchResultItem] = Field(
        default_factory=list,
        description="Search results",
    )
    total_results: int = Field(default=0, description="Total results")
    answer: str = Field(default="", description="Direct answer (if available)")
    provider: str = Field(default="duckduckgo", description="Search provider")
    duration_ms: float = Field(default=0.0, description="Search duration")
    error: str | None = Field(default=None, description="Error message")


# ══════════════════════════════════════════════════════════════
# Extract
# ══════════════════════════════════════════════════════════════

class ExtractResponse(BaseModel):
    """
    Response for POST /extract.

    Example:
        {
            "url": "https://shop.example.com/product/1",
            "success": true,
            "method": "css",
            "data": {"title": "Widget", "price": "$9.99"},
            "duration_ms": 2500
        }
    """

    url: str = Field(description="Source URL")
    success: bool = Field(description="Whether extraction succeeded")
    method: str = Field(default="css", description="Extraction method")
    data: Any = Field(default=None, description="Extracted data")
    duration_ms: float = Field(default=0.0, description="Extraction duration")
    word_count: int = Field(default=0, description="Source page word count")
    error: str | None = Field(default=None, description="Error message")


# ══════════════════════════════════════════════════════════════
# Batch
# ══════════════════════════════════════════════════════════════

class BatchResultItem(BaseModel):
    """A single result in a batch response."""

    url: str = Field(description="Page URL")
    success: bool = Field(description="Whether scrape succeeded")
    status_code: int = Field(default=0, description="HTTP status code")
    markdown: str = Field(default="", description="Page content")
    html: str = Field(default="", description="HTML content")
    text: str = Field(default="", description="Plain text")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata")
    links: dict[str, Any] = Field(default_factory=dict, description="Links")
    chunks: list[dict[str, Any]] = Field(default_factory=list, description="Chunks")
    word_count: int = Field(default=0, description="Word count")
    token_count: int = Field(default=0, description="Token count")
    response_time_ms: float = Field(default=0.0, description="Response time")
    cached: bool = Field(default=False, description="Cached result")
    error: str | None = Field(default=None, description="Error message")


class BatchScrapeResponse(BaseModel):
    """
    Response for POST /batch/scrape.

    Example:
        {
            "total": 3,
            "successful": 3,
            "failed": 0,
            "duration_ms": 5000,
            "results": [...]
        }
    """

    total: int = Field(description="Total URLs")
    successful: int = Field(description="Successful scrapes")
    failed: int = Field(description="Failed scrapes")
    duration_ms: float = Field(default=0.0, description="Total duration")
    results: list[BatchResultItem] = Field(
        default_factory=list,
        description="Individual results",
    )


# ══════════════════════════════════════════════════════════════
# Interact
# ══════════════════════════════════════════════════════════════

class InteractResponse(BaseModel):
    """
    Response for POST /interact.

    Example:
        {
            "session_id": "sess_abc123",
            "success": true,
            "actions_executed": 3,
            "duration_ms": 1500,
            "url": "https://example.com",
            "title": "Example"
        }
    """

    session_id: str = Field(description="Session identifier")
    success: bool = Field(description="Whether actions succeeded")
    actions_executed: int = Field(default=0, description="Actions executed")
    duration_ms: float = Field(default=0.0, description="Duration")
    url: str = Field(default="", description="Current page URL")
    title: str = Field(default="", description="Current page title")
    content: str = Field(default="", description="Page content (if requested)")
    html: str = Field(default="", description="Page HTML (if requested)")
    screenshot: str = Field(default="", description="Base64 screenshot")
    action_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Individual action results",
    )
    error: str | None = Field(default=None, description="Error message")


class SessionResponse(BaseModel):
    """
    Response for session endpoints.

    Example:
        {
            "session_id": "sess_abc123",
            "status": "created",
            "url": "https://example.com"
        }
    """

    session_id: str = Field(description="Session identifier")
    status: str = Field(description="Session status")
    url: str = Field(default="", description="Current URL")
    title: str = Field(default="", description="Current title")
    actions_executed: int = Field(default=0, description="Actions executed")
    age_seconds: float = Field(default=0.0, description="Session age")
    is_active: bool = Field(default=True, description="Whether session is active")


# ══════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════

class ComponentHealthResponse(BaseModel):
    """Health status of a single component."""

    name: str = Field(description="Component name")
    status: str = Field(description="Status: healthy, degraded, unhealthy")
    message: str = Field(default="", description="Status message")
    latency_ms: float = Field(default=0.0, description="Check latency")
    details: dict[str, Any] = Field(default_factory=dict, description="Details")


class HealthResponse(BaseModel):
    """
    Response for GET /health.

    Example:
        {
            "status": "healthy",
            "version": "1.0.0",
            "uptime_seconds": 3600,
            "browser_connected": true,
            "components": [...]
        }
    """

    status: str = Field(description="Overall status: healthy, degraded, unhealthy")
    version: str = Field(default="", description="Application version")
    uptime_seconds: float = Field(default=0.0, description="Server uptime")
    timestamp: str = Field(default="", description="Report timestamp")
    browser_connected: bool = Field(default=False, description="Browser status")
    cache_backend: str = Field(default="none", description="Cache backend")
    active_crawls: int = Field(default=0, description="Active crawl jobs")
    total_requests: int = Field(default=0, description="Total requests")
    total_scrapes: int = Field(default=0, description="Total scrapes")
    total_crawls: int = Field(default=0, description="Total crawls")
    components: list[ComponentHealthResponse] = Field(
        default_factory=list,
        description="Component health details",
    )
    resources: dict[str, Any] = Field(
        default_factory=dict,
        description="Resource usage",
    )


# ══════════════════════════════════════════════════════════════
# Pagination
# ══════════════════════════════════════════════════════════════

class PaginationMeta(BaseModel):
    """Pagination metadata for list endpoints."""

    page: int = Field(default=1, description="Current page")
    per_page: int = Field(default=20, description="Items per page")
    total_items: int = Field(default=0, description="Total items")
    total_pages: int = Field(default=0, description="Total pages")
    has_next: bool = Field(default=False, description="Has next page")
    has_prev: bool = Field(default=False, description="Has previous page")


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    data: list[Any] = Field(default_factory=list, description="Page items")
    pagination: PaginationMeta = Field(
        default_factory=PaginationMeta,
        description="Pagination metadata",
    )


# ══════════════════════════════════════════════════════════════
# API Info
# ══════════════════════════════════════════════════════════════

class APIInfoResponse(BaseModel):
    """
    Response for GET /.

    Example:
        {
            "name": "AgentCrawl API",
            "version": "1.0.0",
            "endpoints": [...]
        }
    """

    name: str = Field(default="AgentCrawl API", description="API name")
    version: str = Field(default="", description="API version")
    api_version: str = Field(default="v1", description="API version identifier")
    description: str = Field(
        default="Web Crawling & Scraping Framework for AI Agents",
        description="API description",
    )
    docs: str = Field(default="/docs", description="Documentation URL")
    endpoints: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Available endpoints by category",
    )
