""""
AgentCrawl — Server Package
===============================

REST API server, MCP server, and background job processing
for AgentCrawl.

Subpackages:
    api         — REST API routes and dependencies
    auth        — Authentication, authorization, rate limiting
    schemas     — Pydantic request/response models
    monitoring  — Health checks, logging, metrics
    queue       — Job queue backends and workers
    mcp         — Model Context Protocol server

Quick Start:
    # Start REST API server
    from server.app import create_app
    app = create_app()

    # Or via CLI
    python -m server

    # MCP server
    from server.mcp import create_mcp_server
    server = create_mcp_server()
"""

from __future__ import annotations

# API
from server.api import api_v1_router

# App
from server.app import AppState, create_app, get_state

# Auth
from server.auth import (
    APIKeyManager,
    AuthMiddleware,
    JWTManager,
    RateLimitConfig,
    RateLimiter,
)

# Main
from server.main import run_server

# Monitoring
from server.monitoring import (
    HealthChecker,
    MetricsCollector,
    configure_server_logging,
)

# Queue
from server.queue import (
    MemoryQueueBackend,
    QueueBackend,
    QueueItem,
    WorkerPool,
)

__all__ = [
    # Auth
    "APIKeyManager",
    "AppState",
    "AuthMiddleware",
    # Monitoring
    "HealthChecker",
    "JWTManager",
    "MemoryQueueBackend",
    "MetricsCollector",
    # Queue
    "QueueBackend",
    "QueueItem",
    "RateLimitConfig",
    "RateLimiter",
    "WorkerPool",
    # API
    "api_v1_router",
    "configure_server_logging",
    # App
    "create_app",
    "get_state",
    "run_server",
]
