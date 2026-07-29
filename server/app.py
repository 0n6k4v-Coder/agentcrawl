"""
AgentCrawl — FastAPI Application
====================================

Main FastAPI application for the AgentCrawl REST API server.

Features:
    - Application factory (create_app)
    - Lifespan management (CrawlEngine startup/shutdown)
    - CORS, logging, and error handling middleware
    - API key authentication
    - Rate limiting
    - Route registration
    - Health check and API info endpoints
    - WebSocket support for real-time crawl updates
    - OpenAPI customization

Usage:
    # Start with CLI
    agentcrawl serve --port 8000

    # Start with uvicorn
    uvicorn agentcrawl.server.app:app --host 0.0.0.0 --port 8000

    # Programmatic
    from server.app import create_app
    app = create_app()
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agentcrawl.config.settings import Settings

logger = logging.getLogger("agentcrawl.server")


# ══════════════════════════════════════════════════════════════
# Application State
# ══════════════════════════════════════════════════════════════

class AppState:
    """
    Shared application state.

    Holds the CrawlEngine instance and server metadata.
    """

    def __init__(self) -> None:
        self.engine: Any = None
        self.settings: Settings | None = None
        self.start_time: float = 0.0
        self.total_requests: int = 0
        self.total_scrapes: int = 0
        self.total_crawls: int = 0
        self.active_crawls: int = 0

    @property
    def uptime_seconds(self) -> float:
        if self.start_time == 0:
            return 0.0
        return time.time() - self.start_time


# Global app state
_state = AppState()


def get_state() -> AppState:
    """Get the global application state."""
    return _state


# ══════════════════════════════════════════════════════════════
# Lifespan
# ══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Starts the CrawlEngine on startup and shuts it down on exit.
    """
    from agentcrawl.core.engine import CrawlEngine

    settings = _state.settings or Settings()
    _state.settings = settings
    _state.start_time = time.time()

    logger.info("Starting AgentCrawl server...")
    logger.info("  Browser: %s (headless=%s)", settings.browser.browser_type, settings.browser.headless)
    logger.info("  Cache: %s", settings.cache_backend)
    logger.info("  Log level: %s", settings.log_level)

    # Create and start engine
    engine = CrawlEngine.from_settings(settings)
    await engine.startup()
    _state.engine = engine

    logger.info("AgentCrawl server started")

    yield

    # Shutdown
    logger.info("Shutting down AgentCrawl server...")
    await engine.shutdown()
    _state.engine = None
    logger.info("AgentCrawl server stopped")


# ══════════════════════════════════════════════════════════════
# Application Factory
# ══════════════════════════════════════════════════════════════

def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        settings: Optional Settings override.

    Returns:
        Configured FastAPI application.

    Example:
        >>> app = create_app()
        >>> # or
        >>> settings = Settings(port=9000)
        >>> app = create_app(settings)
    """
    if settings:
        _state.settings = settings

    app = FastAPI(
        title="AgentCrawl API",
        description=(
            "Web Crawling & Scraping Framework for AI Agents.\n\n"
            "Convert any website into clean, LLM-ready Markdown or structured JSON."
        ),
        version=_get_version(),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Configure middleware
    _configure_middleware(app)

    # Register routes
    _register_routes(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register startup/shutdown events
    _register_events(app)

    return app


# ══════════════════════════════════════════════════════════════
# Middleware
# ══════════════════════════════════════════════════════════════

def _configure_middleware(app: FastAPI) -> None:
    """Configure all middleware."""

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging
    @app.middleware("http")
    async def log_requests(request: Request, call_next: Any) -> Response:
        start = time.perf_counter()
        _state.total_requests += 1

        response = await call_next(request)

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )

        # Add timing header
        response.headers["X-Response-Time"] = f"{elapsed:.1f}ms"

        return response

    # API key authentication
    @app.middleware("http")
    async def authenticate(request: Request, call_next: Any) -> Response:
        # Skip auth for health and docs
        path = request.url.path
        if path in ("/health", "/", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Check API key if configured
        settings = _state.settings
        if settings and settings.api_key:
            auth_header = request.headers.get("Authorization", "")
            query_key = request.query_params.get("api_key", "")

            expected = f"Bearer {settings.api_key}"

            if auth_header != expected and query_key != settings.api_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Invalid or missing API key",
                        }
                    },
                )

        return await call_next(request)

    # Rate limiting (simple in-memory)
    @app.middleware("http")
    async def rate_limit(request: Request, call_next: Any) -> Response:
        # Simple rate limiting: skip for health/docs
        path = request.url.path
        if path in ("/health", "/", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # TODO: Implement proper rate limiting with Redis
        # For now, just pass through
        return await call_next(request)


# ══════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════

def _register_routes(app: FastAPI) -> None:
    """Register all API routes."""

    # ── Health & Info ─────────────────────────────────────────

    @app.get("/health", tags=["System"])
    async def health_check() -> JSONResponse:
        """
        Health check endpoint.

        Returns server status, uptime, and resource info.
        No authentication required.
        """
        engine = _state.engine

        return JSONResponse(content={
            "status": "healthy",
            "version": _get_version(),
            "uptime_seconds": round(_state.uptime_seconds, 1),
            "browser_connected": engine.is_started if engine else False,
            "cache_backend": _state.settings.cache_backend if _state.settings else "none",
            "active_crawls": _state.active_crawls,
            "total_requests": _state.total_requests,
            "total_scrapes": _state.total_scrapes,
            "total_crawls": _state.total_crawls,
        })

    @app.get("/", tags=["System"])
    async def api_info() -> JSONResponse:
        """
        API information endpoint.

        Returns API name, version, and available endpoints.
        """
        return JSONResponse(content={
            "name": "AgentCrawl API",
            "version": _get_version(),
            "description": "Web Crawling & Scraping Framework for AI Agents",
            "docs": "/docs",
            "endpoints": [
                "POST /scrape",
                "POST /crawl",
                "GET /crawl/{job_id}",
                "DELETE /crawl/{job_id}",
                "POST /map",
                "POST /search",
                "POST /extract",
                "POST /batch/scrape",
                "GET /health",
            ],
        })

    # ── Scrape ────────────────────────────────────────────────

    @app.post("/scrape", tags=["Scraping"])
    async def scrape_page(request: Request) -> JSONResponse:
        """
        Scrape a single page.

        Converts a web page into clean Markdown, HTML, or structured JSON.
        """
        from server.api.v1.scrape import handle_scrape

        body = await request.json()
        _state.total_scrapes += 1
        return await handle_scrape(_state.engine, body)

    # ── Crawl ─────────────────────────────────────────────────

    @app.post("/crawl", tags=["Crawling"], status_code=202)
    async def start_crawl(request: Request) -> JSONResponse:
        """
        Start an asynchronous crawl job.

        Returns a job_id for tracking progress.
        """
        from server.api.v1.crawl import handle_start_crawl

        body = await request.json()
        _state.total_crawls += 1
        _state.active_crawls += 1
        return await handle_start_crawl(_state.engine, body)

    @app.get("/crawl/{job_id}", tags=["Crawling"])
    async def get_crawl_status(job_id: str) -> JSONResponse:
        """Get crawl job status and results."""
        from server.api.v1.crawl import handle_get_crawl

        return await handle_get_crawl(job_id)

    @app.delete("/crawl/{job_id}", tags=["Crawling"])
    async def cancel_crawl(job_id: str) -> JSONResponse:
        """Cancel a running crawl job."""
        from server.api.v1.crawl import handle_cancel_crawl

        result = await handle_cancel_crawl(job_id)
        _state.active_crawls = max(0, _state.active_crawls - 1)
        return result

    # ── Map ───────────────────────────────────────────────────

    @app.post("/map", tags=["Discovery"])
    async def map_site(request: Request) -> JSONResponse:
        """
        Discover all URLs on a website.

        Uses sitemap, robots.txt, and link crawling.
        """
        from server.api.v1.map import handle_map

        body = await request.json()
        return await handle_map(_state.engine, body)

    # ── Search ────────────────────────────────────────────────

    @app.post("/search", tags=["Search"])
    async def search_web(request: Request) -> JSONResponse:
        """
        Search the web.

        Supports multiple providers (DuckDuckGo, Tavily, Brave, etc.).
        """
        from server.api.v1.search import handle_search

        body = await request.json()
        return await handle_search(body)

    # ── Extract ───────────────────────────────────────────────

    @app.post("/extract", tags=["Extraction"])
    async def extract_data(request: Request) -> JSONResponse:
        """
        Extract structured data from a URL.

        Supports CSS, XPath, LLM, and regex extraction methods.
        """
        from server.api.v1.extract import handle_extract

        body = await request.json()
        return await handle_extract(_state.engine, body)

    # ── Batch ─────────────────────────────────────────────────

    @app.post("/batch/scrape", tags=["Batch"])
    async def batch_scrape(request: Request) -> JSONResponse:
        """
        Scrape multiple URLs in one request.

        Processes URLs concurrently with configurable parallelism.
        """
        from server.api.v1.batch import handle_batch_scrape

        body = await request.json()
        return await handle_batch_scrape(_state.engine, body)


# ══════════════════════════════════════════════════════════════
# Error Handlers
# ══════════════════════════════════════════════════════════════

def _register_error_handlers(app: FastAPI) -> None:
    """Register global error handlers."""
    import json

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Any) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Endpoint not found: {request.url.path}",
                }
            },
        )

    @app.exception_handler(422)
    async def validation_handler(request: Request, exc: Any) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": str(exc),
                }
            },
        )

    @app.exception_handler(json.JSONDecodeError)
    async def json_decode_error_handler(request: Request, exc: json.JSONDecodeError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid JSON body",
                    "details": str(exc),
                }
            },
        )

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Any) -> JSONResponse:
        logger.error("Internal error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                }
            },
        )


# ══════════════════════════════════════════════════════════════
# Events
# ══════════════════════════════════════════════════════════════

def _register_events(app: FastAPI) -> None:
    """Register startup/shutdown event handlers."""

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("AgentCrawl API v%s starting...", _get_version())

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("AgentCrawl API shutting down...")


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


# ══════════════════════════════════════════════════════════════
# Module-level app instance (for uvicorn)
# ══════════════════════════════════════════════════════════════

app = create_app()
