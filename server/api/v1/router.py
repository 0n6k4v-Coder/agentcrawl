"""
AgentCrawl — API v1 Router
==============================

Central router that aggregates all v1 API endpoints.

Registers all route handlers under the /api/v1 prefix with
proper tags, dependencies, and OpenAPI metadata.

Usage:
    from agentcrawl.server.api.v1.router import api_v1_router

    app = FastAPI()
    app.include_router(api_v1_router)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("agentcrawl.server.router")


# ══════════════════════════════════════════════════════════════
# Router
# ══════════════════════════════════════════════════════════════

api_v1_router = APIRouter(
    prefix="/api/v1",
    tags=["v1"],
    responses={
        401: {"description": "Unauthorized"},
        422: {"description": "Validation Error"},
        500: {"description": "Internal Server Error"},
        503: {"description": "Service Unavailable"},
    },
)


# ══════════════════════════════════════════════════════════════
# Dependencies
# ══════════════════════════════════════════════════════════════

def _get_engine(request: Request) -> Any:
    """Get the CrawlEngine from app state."""
    from agentcrawl.server.app import get_state

    state = get_state()
    return state.engine


def _increment_stat(request: Request, stat: str) -> None:
    """Increment a stat counter in app state."""
    from agentcrawl.server.app import get_state

    state = get_state()
    current = getattr(state, stat, 0)
    setattr(state, stat, current + 1)


# ══════════════════════════════════════════════════════════════
# System Endpoints
# ══════════════════════════════════════════════════════════════

@api_v1_router.get("/health", tags=["System"])
async def health_check() -> JSONResponse:
    """
    Health check endpoint.

    Returns server status, uptime, and resource information.
    No authentication required.
    """
    from agentcrawl.server.app import get_state

    state = get_state()
    engine = state.engine

    return JSONResponse(content={
        "status": "healthy",
        "version": _get_version(),
        "uptime_seconds": round(state.uptime_seconds, 1),
        "browser_connected": engine.is_started if engine else False,
        "cache_backend": state.settings.cache_backend if state.settings else "none",
        "active_crawls": state.active_crawls,
        "total_requests": state.total_requests,
        "total_scrapes": state.total_scrapes,
        "total_crawls": state.total_crawls,
    })


@api_v1_router.get("/", tags=["System"])
async def api_info() -> JSONResponse:
    """
    API information endpoint.

    Returns API name, version, and available endpoints.
    """
    return JSONResponse(content={
        "name": "AgentCrawl API",
        "version": _get_version(),
        "api_version": "v1",
        "description": "Web Crawling & Scraping Framework for AI Agents",
        "docs": "/docs",
        "endpoints": {
            "scraping": ["POST /api/v1/scrape", "POST /api/v1/batch/scrape"],
            "crawling": [
                "POST /api/v1/crawl",
                "GET /api/v1/crawl/{job_id}",
                "DELETE /api/v1/crawl/{job_id}",
            ],
            "discovery": ["POST /api/v1/map"],
            "search": ["POST /api/v1/search"],
            "extraction": ["POST /api/v1/extract"],
            "interaction": [
                "POST /api/v1/interact",
                "POST /api/v1/interact/session",
                "GET /api/v1/interact/session/{session_id}",
                "DELETE /api/v1/interact/session/{session_id}",
            ],
            "system": ["GET /api/v1/health", "GET /api/v1/"],
        },
    })


# ══════════════════════════════════════════════════════════════
# Scraping Endpoints
# ══════════════════════════════════════════════════════════════

@api_v1_router.post("/scrape", tags=["Scraping"])
async def scrape_page(request: Request) -> JSONResponse:
    """
    Scrape a single page.

    Converts a web page into clean Markdown, HTML, or structured JSON.
    Supports page actions, content filtering, and chunking.
    """
    from agentcrawl.server.routes.scrape import handle_scrape

    body = await request.json()
    _increment_stat(request, "total_scrapes")
    engine = _get_engine(request)
    return await handle_scrape(engine, body)


@api_v1_router.post("/batch/scrape", tags=["Batch"])
async def batch_scrape(request: Request) -> JSONResponse:
    """
    Scrape multiple URLs in one request.

    Processes URLs concurrently with configurable parallelism.
    Maximum 100 URLs per request.
    """
    from agentcrawl.server.api.v1.batch import handle_batch_scrape

    body = await request.json()
    _increment_stat(request, "total_scrapes")
    engine = _get_engine(request)
    return await handle_batch_scrape(engine, body)


# ══════════════════════════════════════════════════════════════
# Crawling Endpoints
# ══════════════════════════════════════════════════════════════

@api_v1_router.post("/crawl", tags=["Crawling"], status_code=202)
async def start_crawl(request: Request) -> JSONResponse:
    """
    Start an asynchronous crawl job.

    Returns a job_id for tracking progress via GET /crawl/{job_id}.
    Supports BFS, DFS, BestFirst, and Adaptive strategies.
    """
    from agentcrawl.server.api.v1.crawl import handle_start_crawl

    body = await request.json()
    _increment_stat(request, "total_crawls")

    from agentcrawl.server.app import get_state
    get_state().active_crawls += 1

    engine = _get_engine(request)
    return await handle_start_crawl(engine, body)


@api_v1_router.get("/crawl/{job_id}", tags=["Crawling"])
async def get_crawl_status(job_id: str) -> JSONResponse:
    """
    Get crawl job status and results.

    Returns progress for running jobs, full results for completed jobs.
    """
    from agentcrawl.server.api.v1.crawl import handle_get_crawl

    return await handle_get_crawl(job_id)


@api_v1_router.delete("/crawl/{job_id}", tags=["Crawling"])
async def cancel_crawl(job_id: str) -> JSONResponse:
    """
    Cancel a running crawl job.

    Only works for jobs in 'queued' or 'running' status.
    """
    from agentcrawl.server.api.v1.crawl import handle_cancel_crawl

    from agentcrawl.server.app import get_state
    get_state().active_crawls = max(0, get_state().active_crawls - 1)

    return await handle_cancel_crawl(job_id)


# ══════════════════════════════════════════════════════════════
# Discovery Endpoints
# ══════════════════════════════════════════════════════════════

@api_v1_router.post("/map", tags=["Discovery"])
async def map_site(request: Request) -> JSONResponse:
    """
    Discover all URLs on a website.

    Uses sitemap.xml, robots.txt, and link crawling to find URLs.
    Does not scrape page content.
    """
    from agentcrawl.server.api.v1.map import handle_map

    body = await request.json()
    engine = _get_engine(request)
    return await handle_map(engine, body)


# ══════════════════════════════════════════════════════════════
# Search Endpoints
# ══════════════════════════════════════════════════════════════

@api_v1_router.post("/search", tags=["Search"])
async def search_web(request: Request) -> JSONResponse:
    """
    Search the web.

    Supports multiple providers: duckduckgo, tavily, brave, exa, searxng.
    Optionally scrape result pages for full content.
    """
    from agentcrawl.server.routes.search import handle_search

    body = await request.json()
    return await handle_search(body)


# ══════════════════════════════════════════════════════════════
# Extraction Endpoints
# ══════════════════════════════════════════════════════════════

@api_v1_router.post("/extract", tags=["Extraction"])
async def extract_data(request: Request) -> JSONResponse:
    """
    Extract structured data from a URL.

    Supports CSS, XPath, LLM, and regex extraction methods.
    Provide a schema defining the fields to extract.
    """
    from agentcrawl.server.api.v1.extract import handle_extract

    body = await request.json()
    engine = _get_engine(request)
    return await handle_extract(engine, body)


# ══════════════════════════════════════════════════════════════
# Interaction Endpoints
# ══════════════════════════════════════════════════════════════

@api_v1_router.post("/interact", tags=["Interaction"])
async def interact(request: Request) -> JSONResponse:
    """
    Execute browser actions on a page.

    Supports click, type, scroll, wait, screenshot, evaluate,
    and navigate actions. Can maintain session state.
    """
    from agentcrawl.server.api.v1.interact import handle_interact

    body = await request.json()
    engine = _get_engine(request)
    return await handle_interact(engine, body)


@api_v1_router.post("/interact/session", tags=["Interaction"], status_code=201)
async def create_session(request: Request) -> JSONResponse:
    """
    Create an interactive browser session.

    Sessions maintain cookies and browser state across
    multiple interaction requests.
    """
    from agentcrawl.server.api.v1.interact import handle_create_session

    body = await request.json()
    engine = _get_engine(request)
    return await handle_create_session(engine, body)


@api_v1_router.get("/interact/session/{session_id}", tags=["Interaction"])
async def get_session(session_id: str) -> JSONResponse:
    """
    Get interactive session information.

    Returns session status, URL, and action count.
    """
    from agentcrawl.server.api.v1.interact import handle_get_session

    return await handle_get_session(session_id)


@api_v1_router.delete("/interact/session/{session_id}", tags=["Interaction"])
async def destroy_session(session_id: str) -> JSONResponse:
    """
    Destroy an interactive browser session.

    Releases browser resources associated with the session.
    """
    from agentcrawl.server.api.v1.interact import handle_destroy_session

    return await handle_destroy_session(session_id)


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

def _get_version() -> str:
    """Get the AgentCrawl version."""
    try:
        import agentcrawl
        return agentcrawl.__version__
    except Exception:
        return "1.0.0"