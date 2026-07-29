"""
AgentCrawl — API v1 Package
===============================

Version 1 of the AgentCrawl REST API.

Modules:
    router    — Central APIRouter with all endpoints
    scrape    — Single page scraping
    crawl     — Async crawl job management
    map       — URL discovery
    search    — Web search
    extract   — Structured data extraction
    batch     — Batch scraping
    interact  — Browser interaction and sessions

Usage:
    from server.api.v1 import api_v1_router

    app = FastAPI()
    app.include_router(api_v1_router)
"""

from __future__ import annotations

from server.api.v1.router import api_v1_router

__all__ = [
    "api_v1_router",
]
