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
    "APIInfoResponse",
    "ActionStep",
    "BatchResultItem",
    "BatchScrapeRequest",
    "BatchScrapeResponse",
    "ComponentHealthResponse",
    "CrawlJobResultResponse",
    "CrawlJobStatusResponse",
    "CrawlPageResult",
    "CrawlRequest",
    "CrawlStartResponse",
    "ErrorDetail",
    "ErrorResponse",
    "ExtractRequest",
    "ExtractResponse",
    "HealthResponse",
    "InteractRequest",
    "InteractResponse",
    "MapRequest",
    "MapResponse",
    "PaginatedResponse",
    "PaginationMeta",
    # Requests
    "ScrapeRequest",
    # Responses
    "ScrapeResponse",
    "SearchRequest",
    "SearchResponse",
    "SearchResultItem",
    "SessionCreateRequest",
    "SessionResponse",
]
