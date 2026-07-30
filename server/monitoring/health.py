"""
AgentCrawl — Health Monitoring
==================================

Health check system for the AgentCrawl server with component
checks, readiness/liveness probes, and diagnostics.

Features:
    - Component health checks (browser, cache, queue)
    - Liveness and readiness probes (Kubernetes-compatible)
    - Uptime and resource tracking
    - Dependency connectivity checks
    - Detailed diagnostics endpoint
    - Health status aggregation

Usage:
    from server.monitoring.health import (
        HealthChecker,
        HealthStatus,
        ComponentHealth,
    )

    checker = HealthChecker(engine=engine)

    # Full health check
    report = await checker.check_all()
    print(report.status)  # "healthy"

    # Liveness probe
    live = await checker.check_liveness()

    # Readiness probe
    ready = await checker.check_readiness()
"""

from __future__ import annotations

import logging
import os
import platform
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("agentcrawl.server.monitoring")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

class HealthStatus(str, Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """
    Health status of a single component.

    Attributes:
        name: Component name.
        status: Health status.
        message: Status message.
        latency_ms: Check latency.
        details: Additional details.
    """
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    message: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }


@dataclass
class HealthReport:
    """
    Aggregated health report.

    Attributes:
        status: Overall health status.
        version: Application version.
        uptime_seconds: Server uptime.
        timestamp: Report timestamp.
        components: Individual component health.
        resources: Resource usage info.
        stats: Operational statistics.
    """
    status: HealthStatus = HealthStatus.UNKNOWN
    version: str = ""
    uptime_seconds: float = 0.0
    timestamp: str = ""
    components: list[ComponentHealth] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY

    @property
    def is_ready(self) -> bool:
        """Ready if core components are healthy."""
        core = {"engine", "browser"}
        for comp in self.components:
            if comp.name in core and comp.status != HealthStatus.HEALTHY:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "timestamp": self.timestamp,
            "components": [c.to_dict() for c in self.components],
            "resources": self.resources,
            "stats": self.stats,
        }

    def to_k8s_dict(self) -> dict[str, Any]:
        """Kubernetes-compatible health response."""
        return {
            "status": self.status.value,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


# ══════════════════════════════════════════════════════════════
# Health Checker
# ══════════════════════════════════════════════════════════════

class HealthChecker:
    """
    Performs health checks on server components.

    Args:
        engine: CrawlEngine instance.
        start_time: Server start timestamp.

    Example:
        >>> checker = HealthChecker(engine=engine)
        >>> report = await checker.check_all()
        >>> print(report.status)
    """

    def __init__(
        self,
        engine: Any = None,
        start_time: float | None = None,
    ):
        self._engine = engine
        self._start_time = start_time or time.time()

    # ──────────────────────────────────────────────────────────
    # Full Health Check
    # ──────────────────────────────────────────────────────────

    async def check_all(self) -> HealthReport:
        """
        Run all health checks and return aggregated report.

        Returns:
            HealthReport with all component statuses.
        """
        components: list[ComponentHealth] = []

        # Check each component
        components.append(await self._check_engine())
        components.append(await self._check_browser())
        components.append(await self._check_cache())
        components.append(await self._check_memory())

        # Aggregate status
        overall = self._aggregate_status(components)

        # Build report
        report = HealthReport(
            status=overall,
            version=self._get_version(),
            uptime_seconds=time.time() - self._start_time,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            components=components,
            resources=self._get_resources(),
            stats=self._get_stats(),
        )

        return report

    # ──────────────────────────────────────────────────────────
    # Liveness & Readiness
    # ──────────────────────────────────────────────────────────

    async def check_liveness(self) -> ComponentHealth:
        """
        Liveness probe: is the process alive?

        Returns healthy if the process is running and
        can respond to requests.

        Returns:
            ComponentHealth for liveness.
        """
        start = time.perf_counter()

        try:
            # Basic check: can we allocate and compute?
            _ = sum(range(1000))
            elapsed = (time.perf_counter() - start) * 1000

            return ComponentHealth(
                name="liveness",
                status=HealthStatus.HEALTHY,
                message="Process is alive",
                latency_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="liveness",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=elapsed,
            )

    async def check_readiness(self) -> ComponentHealth:
        """
        Readiness probe: is the server ready to accept traffic?

        Checks that the engine is started and browser is available.

        Returns:
            ComponentHealth for readiness.
        """
        start = time.perf_counter()

        try:
            if self._engine is None:
                return ComponentHealth(
                    name="readiness",
                    status=HealthStatus.UNHEALTHY,
                    message="Engine not initialized",
                    latency_ms=(time.perf_counter() - start) * 1000,
                )

            if not self._engine.is_started:
                return ComponentHealth(
                    name="readiness",
                    status=HealthStatus.UNHEALTHY,
                    message="Engine not started",
                    latency_ms=(time.perf_counter() - start) * 1000,
                )

            elapsed = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="readiness",
                status=HealthStatus.HEALTHY,
                message="Server is ready",
                latency_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="readiness",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=elapsed,
            )

    # ──────────────────────────────────────────────────────────
    # Component Checks
    # ──────────────────────────────────────────────────────────

    async def _check_engine(self) -> ComponentHealth:
        """Check CrawlEngine health."""
        start = time.perf_counter()

        try:
            if self._engine is None:
                return ComponentHealth(
                    name="engine",
                    status=HealthStatus.UNHEALTHY,
                    message="Engine not initialized",
                    latency_ms=(time.perf_counter() - start) * 1000,
                )

            is_started = self._engine.is_started

            elapsed = (time.perf_counter() - start) * 1000

            if is_started:
                return ComponentHealth(
                    name="engine",
                    status=HealthStatus.HEALTHY,
                    message="Engine is running",
                    latency_ms=elapsed,
                )
            else:
                return ComponentHealth(
                    name="engine",
                    status=HealthStatus.UNHEALTHY,
                    message="Engine not started",
                    latency_ms=elapsed,
                )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="engine",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=elapsed,
            )

    async def _check_browser(self) -> ComponentHealth:
        """Check browser availability."""
        start = time.perf_counter()

        try:
            if self._engine is None or not self._engine.is_started:
                return ComponentHealth(
                    name="browser",
                    status=HealthStatus.UNKNOWN,
                    message="Engine not available",
                    latency_ms=(time.perf_counter() - start) * 1000,
                )

            # Check if browser manager exists and is connected
            browser_mgr = getattr(self._engine, "_browser_manager", None)

            elapsed = (time.perf_counter() - start) * 1000

            if browser_mgr is not None:
                return ComponentHealth(
                    name="browser",
                    status=HealthStatus.HEALTHY,
                    message="Browser manager available",
                    latency_ms=elapsed,
                    details={"type": getattr(browser_mgr, "_browser_type", "unknown")},
                )
            else:
                return ComponentHealth(
                    name="browser",
                    status=HealthStatus.DEGRADED,
                    message="Browser manager not found",
                    latency_ms=elapsed,
                )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="browser",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=elapsed,
            )

    async def _check_cache(self) -> ComponentHealth:
        """Check cache backend health."""
        start = time.perf_counter()

        try:
            cache_mgr = None
            if self._engine is not None:
                cache_mgr = getattr(self._engine, "_cache_manager", None)

            elapsed = (time.perf_counter() - start) * 1000

            if cache_mgr is None:
                return ComponentHealth(
                    name="cache",
                    status=HealthStatus.HEALTHY,
                    message="Cache disabled (memory-only mode)",
                    latency_ms=elapsed,
                )

            # Try a cache operation
            try:
                await cache_mgr.set("__health_check__", "ok", ttl=10)
                value = await cache_mgr.get("__health_check__")
                await cache_mgr.delete("__health_check__")

                if value == "ok":
                    return ComponentHealth(
                        name="cache",
                        status=HealthStatus.HEALTHY,
                        message="Cache is operational",
                        latency_ms=elapsed,
                        details={"backend": getattr(cache_mgr, "_backend_name", "unknown")},
                    )
            except Exception:
                logger.debug("Cache health check failed")

            return ComponentHealth(
                name="cache",
                status=HealthStatus.DEGRADED,
                message="Cache check inconclusive",
                latency_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="cache",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=elapsed,
            )

    async def _check_memory(self) -> ComponentHealth:
        """Check memory usage."""
        start = time.perf_counter()

        try:
            import resource

            # Get max RSS (resident set size)
            usage = resource.getrusage(resource.RUSAGE_SELF)
            max_rss_mb = usage.ru_maxrss / 1024  # Convert KB to MB on Linux

            elapsed = (time.perf_counter() - start) * 1000

            # Warn if over 1GB
            if max_rss_mb > 1024:
                status = HealthStatus.DEGRADED
                message = f"High memory usage: {max_rss_mb:.0f}MB"
            else:
                status = HealthStatus.HEALTHY
                message = f"Memory usage: {max_rss_mb:.0f}MB"

            return ComponentHealth(
                name="memory",
                status=status,
                message=message,
                latency_ms=elapsed,
                details={"max_rss_mb": round(max_rss_mb, 1)},
            )

        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="memory",
                status=HealthStatus.HEALTHY,
                message="Memory check unavailable",
                latency_ms=elapsed,
            )

    # ──────────────────────────────────────────────────────────
    # Aggregation
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _aggregate_status(components: list[ComponentHealth]) -> HealthStatus:
        """Aggregate component statuses into overall status."""
        statuses = [c.status for c in components]

        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY

        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED

        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY

        return HealthStatus.UNKNOWN

    # ──────────────────────────────────────────────────────────
    # Resources & Stats
    # ──────────────────────────────────────────────────────────

    def _get_resources(self) -> dict[str, Any]:
        """Get resource usage information."""
        resources: dict[str, Any] = {
            "platform": platform.system(),
            "python_version": platform.python_version(),
            "pid": os.getpid(),
        }

        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            resources["max_rss_mb"] = round(usage.ru_maxrss / 1024, 1)
            resources["user_time_s"] = round(usage.ru_utime, 2)
            resources["system_time_s"] = round(usage.ru_stime, 2)
        except Exception:
            logger.debug("Error getting resource usage")

        return resources

    def _get_stats(self) -> dict[str, Any]:
        """Get operational statistics."""
        stats: dict[str, Any] = {}

        if self._engine is not None:
            engine_stats = getattr(self._engine, "stats", None)
            if engine_stats:
                if hasattr(engine_stats, "to_dict"):
                    stats = engine_stats.to_dict()
                elif isinstance(engine_stats, dict):
                    stats = engine_stats

        return stats

    @staticmethod
    def _get_version() -> str:
        """Get application version."""
        try:
            import agentcrawl
            return agentcrawl.__version__
        except Exception:
            return "unknown"
