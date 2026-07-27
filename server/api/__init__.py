"""
AgentCrawl — Server API Package
===================================

REST API layer for AgentCrawl server.

Modules:
    v1      — Version 1 API endpoints
    deps    — FastAPI dependency injection

Usage:
    from agentcrawl.server.api import api_v1_router

    app = FastAPI()
    app.include_router(api_v1_router)
"""

from __future__ import annotations

from agentcrawl.server.api.v1 import api_v1_router

__all__ = [
    "api_v1_router",
]