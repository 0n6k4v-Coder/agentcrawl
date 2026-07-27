"""
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
    from agentcrawl.server import create_app
    app = create_app()

    # Or via CLI
    agentcrawl serve --port 8000

    # MCP server
    from agentcrawl.server.mcp import create_mcp_server
    server = create_mcp_server()
"""

from __future__ import annotations

# App
from agentcrawl.server.app import AppState, create_app, get_state

# Main
from agentcrawl.server.main import run_server

# API
from agentcrawl.server.api import api_v1_router

# Auth
from agentcrawl.server.auth import (
    APIKeyManager,
    AuthMiddleware,
    JWTManager,
    RateLimiter,
    RateLimitConfig,
)

# Monitoring
from agentcrawl.server.monitoring import (
    HealthChecker,
    MetricsCollector,
    configure_server_logging,
)

# Queue
from agentcrawl.server.queue import (
    MemoryQueueBackend,
    QueueBackend,
    QueueItem,
    WorkerPool,
)


__all__ = [
    # App
    "create_app",
    "get_state",
    "AppState",
    "run_server",
    # API
    "api_v1_router",
    # Auth
    "APIKeyManager",
    "JWTManager",
    "AuthMiddleware",
    "RateLimiter",
    "RateLimitConfig",
    # Monitoring
    "HealthChecker",
    "MetricsCollector",
    "configure_server_logging",
    # Queue
    "QueueBackend",
    "MemoryQueueBackend",
    "QueueItem",
    "WorkerPool",
]