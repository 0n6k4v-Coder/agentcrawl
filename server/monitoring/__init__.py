"""
AgentCrawl — Server Monitoring Package
==========================================

Health checks, logging, and metrics for the AgentCrawl server.

Modules:
    health   — Health checks and readiness/liveness probes
    logging  — Structured logging, formatters, and middleware
    metrics  — Metrics collection and Prometheus exposition

Quick Start:
    from agentcrawl.server.monitoring import (
        HealthChecker,
        configure_server_logging,
        MetricsCollector,
        MetricsMiddleware,
        RequestIdMiddleware,
    )

    # Logging
    configure_server_logging(level="INFO", json_format=True)

    # Middleware
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(MetricsMiddleware)

    # Health
    checker = HealthChecker(engine=engine)
    report = await checker.check_all()
"""

from __future__ import annotations

# Health
from agentcrawl.server.monitoring.health import (
    ComponentHealth,
    HealthChecker,
    HealthReport,
    HealthStatus,
)

# Logging
from agentcrawl.server.monitoring.logging import (
    AccessLogMiddleware,
    RequestIdMiddleware,
    SensitiveDataFilter,
    ServerColoredFormatter,
    ServerJsonFormatter,
    ServerLogger,
    configure_server_logging,
    get_request_id,
    set_request_id,
)

# Metrics
from agentcrawl.server.monitoring.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
    MetricsMiddleware,
    get_metrics,
    metrics_endpoint,
)


__all__ = [
    # Health
    "HealthChecker",
    "HealthReport",
    "HealthStatus",
    "ComponentHealth",
    # Logging
    "configure_server_logging",
    "RequestIdMiddleware",
    "AccessLogMiddleware",
    "ServerJsonFormatter",
    "ServerColoredFormatter",
    "SensitiveDataFilter",
    "ServerLogger",
    "get_request_id",
    "set_request_id",
    # Metrics
    "MetricsCollector",
    "MetricsMiddleware",
    "Counter",
    "Gauge",
    "Histogram",
    "get_metrics",
    "metrics_endpoint",
]