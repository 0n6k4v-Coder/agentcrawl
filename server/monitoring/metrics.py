"""
AgentCrawl — Server Metrics
===============================

Metrics collection and exposition for the AgentCrawl server.

Features:
    - Counters, gauges, and histograms
    - Request metrics (count, duration, status codes)
    - Scrape/crawl/search operation metrics
    - Cache hit/miss tracking
    - Browser resource metrics
    - Prometheus-compatible text format
    - Metrics middleware for auto-collection
    - /metrics endpoint handler

Usage:
    from server.monitoring.metrics import (
        MetricsCollector,
        MetricsMiddleware,
        get_metrics,
    )

    # Get global collector
    metrics = get_metrics()

    # Record metrics
    metrics.increment("requests_total")
    metrics.observe("request_duration_seconds", 0.25)
    metrics.set_gauge("active_crawls", 3)

    # Middleware
    app.add_middleware(MetricsMiddleware)

    # Prometheus format
    text = metrics.to_prometheus()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse, Response

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger("agentcrawl.server.metrics")


# ══════════════════════════════════════════════════════════════
# Metric Types
# ══════════════════════════════════════════════════════════════


@dataclass
class Counter:
    """Monotonically increasing counter."""

    name: str
    help: str = ""
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount


@dataclass
class Gauge:
    """Value that can go up and down."""

    name: str
    help: str = ""
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)

    def set(self, value: float) -> None:
        self.value = value

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        self.value -= amount


@dataclass
class Histogram:
    """Distribution of values across buckets."""

    name: str
    help: str = ""
    buckets: list[float] = field(
        default_factory=lambda: [
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
            5.0,
            10.0,
        ]
    )
    bucket_counts: list[int] = field(default_factory=list)
    sum: float = 0.0
    count: int = 0
    labels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bucket_counts:
            self.bucket_counts = [0] * (len(self.buckets) + 1)

    def observe(self, value: float) -> None:
        self.sum += value
        self.count += 1

        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self.bucket_counts[i] += 1
                return

        # Overflow bucket
        self.bucket_counts[-1] += 1


# ══════════════════════════════════════════════════════════════
# Metrics Collector
# ══════════════════════════════════════════════════════════════


class MetricsCollector:
    """
    Central metrics collection and exposition.

    Thread-safe collector for counters, gauges, and histograms.

    Example:
        >>> metrics = MetricsCollector()
        >>> metrics.increment("requests_total", labels={"method": "POST"})
        >>> metrics.observe("request_duration_seconds", 0.25)
        >>> print(metrics.to_prometheus())
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._start_time = time.time()

        # Register default metrics
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default server metrics."""
        # HTTP metrics
        self.register_counter(
            "agentcrawl_http_requests_total",
            "Total HTTP requests",
        )
        self.register_histogram(
            "agentcrawl_http_request_duration_seconds",
            "HTTP request duration in seconds",
        )
        self.register_counter(
            "agentcrawl_http_errors_total",
            "Total HTTP errors (4xx + 5xx)",
        )

        # Scrape metrics
        self.register_counter(
            "agentcrawl_scrapes_total",
            "Total scrape operations",
        )
        self.register_counter(
            "agentcrawl_scrape_errors_total",
            "Total scrape errors",
        )
        self.register_histogram(
            "agentcrawl_scrape_duration_seconds",
            "Scrape duration in seconds",
        )
        self.register_histogram(
            "agentcrawl_scrape_word_count",
            "Words per scraped page",
            buckets=[100, 250, 500, 1000, 2000, 5000, 10000],
        )

        # Crawl metrics
        self.register_counter(
            "agentcrawl_crawls_total",
            "Total crawl jobs",
        )
        self.register_counter(
            "agentcrawl_crawl_pages_total",
            "Total pages crawled",
        )
        self.register_gauge(
            "agentcrawl_active_crawls",
            "Currently active crawl jobs",
        )

        # Search metrics
        self.register_counter(
            "agentcrawl_searches_total",
            "Total search operations",
        )

        # Cache metrics
        self.register_counter(
            "agentcrawl_cache_hits_total",
            "Total cache hits",
        )
        self.register_counter(
            "agentcrawl_cache_misses_total",
            "Total cache misses",
        )

        # Browser metrics
        self.register_gauge(
            "agentcrawl_browser_contexts_active",
            "Active browser contexts",
        )
        self.register_counter(
            "agentcrawl_browser_errors_total",
            "Total browser errors",
        )

    # ──────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────

    def register_counter(self, name: str, help_text: str = "") -> None:
        """Register a counter metric."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name, help=help_text)

    def register_gauge(self, name: str, help_text: str = "") -> None:
        """Register a gauge metric."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name, help=help_text)

    def register_histogram(
        self,
        name: str,
        help_text: str = "",
        buckets: list[float] | None = None,
    ) -> None:
        """Register a histogram metric."""
        with self._lock:
            if name not in self._histograms:
                kwargs: dict[str, Any] = {"name": name, "help": help_text}
                if buckets:
                    kwargs["buckets"] = buckets
                self._histograms[name] = Histogram(**kwargs)

    # ──────────────────────────────────────────────────────────
    # Recording
    # ──────────────────────────────────────────────────────────

    def increment(
        self,
        name: str,
        amount: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name)
            self._counters[name].inc(amount)

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge value."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name)
            self._gauges[name].set(value)

    def inc_gauge(self, name: str, amount: float = 1.0) -> None:
        """Increment a gauge."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name)
            self._gauges[name].inc(amount)

    def dec_gauge(self, name: str, amount: float = 1.0) -> None:
        """Decrement a gauge."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name)
            self._gauges[name].dec(amount)

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Observe a histogram value."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name=name)
            self._histograms[name].observe(value)

    # ──────────────────────────────────────────────────────────
    # Convenience Methods
    # ──────────────────────────────────────────────────────────

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_s: float,
    ) -> None:
        """Record an HTTP request."""
        self.increment("agentcrawl_http_requests_total")
        self.observe("agentcrawl_http_request_duration_seconds", duration_s)

        if status_code >= 400:
            self.increment("agentcrawl_http_errors_total")

    def record_scrape(
        self,
        success: bool,
        duration_s: float,
        word_count: int = 0,
        cached: bool = False,
    ) -> None:
        """Record a scrape operation."""
        self.increment("agentcrawl_scrapes_total")
        self.observe("agentcrawl_scrape_duration_seconds", duration_s)

        if success:
            self.observe("agentcrawl_scrape_word_count", float(word_count))
        else:
            self.increment("agentcrawl_scrape_errors_total")

        if cached:
            self.increment("agentcrawl_cache_hits_total")
        else:
            self.increment("agentcrawl_cache_misses_total")

    def record_crawl_start(self) -> None:
        """Record crawl job start."""
        self.increment("agentcrawl_crawls_total")
        self.inc_gauge("agentcrawl_active_crawls")

    def record_crawl_end(self, pages: int) -> None:
        """Record crawl job end."""
        self.dec_gauge("agentcrawl_active_crawls")
        self.increment("agentcrawl_crawl_pages_total", float(pages))

    def record_search(self) -> None:
        """Record a search operation."""
        self.increment("agentcrawl_searches_total")

    # ──────────────────────────────────────────────────────────
    # Exposition
    # ──────────────────────────────────────────────────────────

    def to_prometheus(self) -> str:
        """
        Export metrics in Prometheus text format.

        Returns:
            Prometheus-compatible metrics string.
        """
        lines: list[str] = []

        with self._lock:
            # Counters
            for name, counter in sorted(self._counters.items()):
                if counter.help:
                    lines.append(f"# HELP {name} {counter.help}")
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {counter.value}")
                lines.append("")

            # Gauges
            for name, gauge in sorted(self._gauges.items()):
                if gauge.help:
                    lines.append(f"# HELP {name} {gauge.help}")
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {gauge.value}")
                lines.append("")

            # Histograms
            for name, hist in sorted(self._histograms.items()):
                if hist.help:
                    lines.append(f"# HELP {name} {hist.help}")
                lines.append(f"# TYPE {name} histogram")

                cumulative = 0
                for i, bound in enumerate(hist.buckets):
                    cumulative += hist.bucket_counts[i]
                    lines.append(f'{name}_bucket{{le="{bound}"}} {cumulative}')

                cumulative += hist.bucket_counts[-1]
                lines.append(f'{name}_bucket{{le="+Inf"}} {cumulative}')
                lines.append(f"{name}_sum {hist.sum}")
                lines.append(f"{name}_count {hist.count}")
                lines.append("")

            # Uptime
            uptime = time.time() - self._start_time
            lines.append("# HELP agentcrawl_uptime_seconds Server uptime")
            lines.append("# TYPE agentcrawl_uptime_seconds gauge")
            lines.append(f"agentcrawl_uptime_seconds {uptime:.1f}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Export metrics as a dictionary."""
        with self._lock:
            return {
                "counters": {
                    name: {"value": c.value, "help": c.help} for name, c in self._counters.items()
                },
                "gauges": {
                    name: {"value": g.value, "help": g.help} for name, g in self._gauges.items()
                },
                "histograms": {
                    name: {
                        "count": h.count,
                        "sum": h.sum,
                        "help": h.help,
                    }
                    for name, h in self._histograms.items()
                },
                "uptime_seconds": round(time.time() - self._start_time, 1),
            }

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            for counter in self._counters.values():
                counter.value = 0.0
            for gauge in self._gauges.values():
                gauge.value = 0.0
            for hist in self._histograms.values():
                hist.bucket_counts = [0] * (len(hist.buckets) + 1)
                hist.sum = 0.0
                hist.count = 0


# ══════════════════════════════════════════════════════════════
# Middleware
# ══════════════════════════════════════════════════════════════


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware that automatically collects HTTP request metrics.

    Records request count, duration, and status codes for
    every request.

    Example:
        >>> app.add_middleware(MetricsMiddleware)
    """

    def __init__(self, app: Any, collector: MetricsCollector | None = None):
        super().__init__(app)
        self._metrics = collector or get_metrics()

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - start

        # Record metrics
        self._metrics.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_s=duration,
        )

        return response


# ══════════════════════════════════════════════════════════════
# Metrics Endpoint
# ══════════════════════════════════════════════════════════════


async def metrics_endpoint(request: Request) -> PlainTextResponse:
    """
    Prometheus metrics endpoint handler.

    Usage:
        from server.monitoring.metrics import metrics_endpoint

        @app.get("/metrics")
        async def metrics(request: Request):
            return await metrics_endpoint(request)
    """
    metrics = get_metrics()
    return PlainTextResponse(
        content=metrics.to_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ══════════════════════════════════════════════════════════════
# Global Instance
# ══════════════════════════════════════════════════════════════

_global_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """
    Get the global MetricsCollector instance.

    Returns:
        MetricsCollector instance.
    """
    global _global_metrics

    if _global_metrics is None:
        _global_metrics = MetricsCollector()

    return _global_metrics
