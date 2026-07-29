"""
AgentCrawl — Server Schemas Package
=======================================

Pydantic request and response models for the AgentCrawl REST API.

Modules:
    requests  — Request body schemas with validation
    responses — Response body schemas with serialization

Usage:
    from server.schemas import (
        ScrapeRequest,
        ScrapeResponse,
        ErrorResponse,
    )

    # Validate request
    req = ScrapeRequest(url="https://example.com")

    # Build response
    resp = ScrapeResponse(url=req.url, success=True, markdown="...")
"""

from __future__ import annotations

# Requests
from server.schemas.requests import (
    ActionStep,
    BatchScrapeRequest,
    CrawlRequest,
    ExtractRequest,
    InteractRequest,
    MapRequest,
    ScrapeRequest,
    SearchRequest,
    SessionCreateRequest,
)

# Responses
from server.schemas.responses import (
    APIInfoResponse,
    BatchResultItem,
    BatchScrapeResponse,
    ComponentHealthResponse,
    CrawlJobResultResponse,
    CrawlJobStatusResponse,
    CrawlPageResult,
    CrawlStartResponse,
    ErrorDetail,
    ErrorResponse,
    ExtractResponse,
    HealthResponse,
    InteractResponse,
    MapResponse,
    PaginatedResponse,
    PaginationMeta,
    ScrapeResponse,
    SearchResponse,
    SearchResultItem,
    SessionResponse,
)

__all__ = [
    # Requests
    "ScrapeRequest",
    "CrawlRequest",
    "MapRequest",
    "SearchRequest",
    "ExtractRequest",
    "BatchScrapeRequest",
    "InteractRequest",
    "SessionCreateRequest",
    "ActionStep",
    # Responses
    "ScrapeResponse",
    "CrawlStartResponse",
    "CrawlJobStatusResponse",
    "CrawlJobResultResponse",
    "CrawlPageResult",
    "MapResponse",
    "SearchResponse",
    "SearchResultItem",
    "ExtractResponse",
    "BatchScrapeResponse",
    "BatchResultItem",
    "InteractResponse",
    "SessionResponse",
    "HealthResponse",
    "ComponentHealthResponse",
    "ErrorResponse",
    "ErrorDetail",
    "PaginationMeta",
    "PaginatedResponse",
    "APIInfoResponse",
]
