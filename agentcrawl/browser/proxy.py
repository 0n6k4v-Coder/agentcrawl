"""
AgentCrawl — Proxy Manager
============================

Manages proxy servers for browser automation with support for
multiple rotation strategies, health checking, authentication,
geo-based selection, and usage tracking.

Supported Protocols:
    - HTTP / HTTPS
    - SOCKS5 / SOCKS4

Rotation Strategies:
    - none: Always use the same proxy
    - round_robin: Cycle through proxies sequentially
    - random: Select a proxy at random
    - least_used: Select the proxy with fewest requests
    - weighted: Select based on configured weights
    - fastest: Select based on measured latency

Usage:
    from agentcrawl.browser.proxy import ProxyManager, ProxyServer

    # From config
    from agentcrawl.browser.config import ProxyConfig
    config = ProxyConfig(
        proxy_list=["http://p1:8080", "http://p2:8080", "socks5://p3:1080"],
        rotation="round_robin",
    )
    manager = ProxyManager(config)

    # Get next proxy
    proxy = manager.next()
    print(proxy.to_playwright_dict())

    # Manual proxy list
    manager = ProxyManager.from_urls([
        "http://user:pass@proxy1:8080",
        "http://proxy2:8080",
        "socks5://proxy3:1080",
    ], rotation="least_used")

    # With health checking
    await manager.validate_all()
    healthy = manager.healthy_proxies()

    # Load from file
    manager = ProxyManager.from_file("proxies.txt", rotation="random")

    # Geo-based selection
    proxy = manager.next(country="US")
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from agentcrawl.browser.config import ProxyConfig, ProxyRotationStrategy

logger = logging.getLogger("agentcrawl.browser.proxy")


# ══════════════════════════════════════════════════════════════
# Types & Enums
# ══════════════════════════════════════════════════════════════

class ProxyProtocol(str, Enum):
    """Supported proxy protocols."""
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"
    SOCKS4 = "socks4"


class ProxyStatus(str, Enum):
    """Health status of a proxy server."""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CHECKING = "checking"


# ══════════════════════════════════════════════════════════════
# Proxy Server Model
# ══════════════════════════════════════════════════════════════

@dataclass
class ProxyServer:
    """
    Represents a single proxy server with metadata and usage stats.

    Attributes:
        host: Proxy hostname or IP address.
        port: Proxy port number.
        protocol: Proxy protocol (http, https, socks5, socks4).
        username: Authentication username (optional).
        password: Authentication password (optional).
        country: ISO country code (e.g., 'US', 'TH').
        city: City name.
        weight: Selection weight for weighted rotation.
        status: Current health status.
        latency_ms: Last measured latency in milliseconds.
        total_requests: Total requests routed through this proxy.
        failed_requests: Total failed requests.
        last_used_at: Unix timestamp of last use.
        last_checked_at: Unix timestamp of last health check.
        tags: Arbitrary tags for filtering.
    """
    host: str
    port: int
    protocol: ProxyProtocol = ProxyProtocol.HTTP
    username: str | None = None
    password: str | None = None
    country: str | None = None
    city: str | None = None
    weight: float = 1.0
    status: ProxyStatus = ProxyStatus.UNKNOWN
    latency_ms: float = 0.0
    total_requests: int = 0
    failed_requests: int = 0
    last_used_at: float = 0.0
    last_checked_at: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        """Full proxy URL string."""
        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password}@" if self.password else f"{self.username}@"
        return f"{self.protocol.value}://{auth}{self.host}:{self.port}"

    @property
    def server_url(self) -> str:
        """Proxy URL without authentication (for Playwright 'server' field)."""
        return f"{self.protocol.value}://{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        """Success rate as a ratio (0.0 to 1.0)."""
        if self.total_requests == 0:
            return 1.0
        return (self.total_requests - self.failed_requests) / self.total_requests

    @property
    def is_healthy(self) -> bool:
        """Whether the proxy is considered healthy."""
        return self.status in (ProxyStatus.HEALTHY, ProxyStatus.UNKNOWN)

    @property
    def is_available(self) -> bool:
        """Whether the proxy can be used (healthy and not recently failed)."""
        return self.is_healthy

    def to_playwright_dict(self) -> dict[str, Any]:
        """
        Convert to Playwright proxy format.

        Returns:
            Dictionary suitable for Playwright's proxy option.
        """
        result: dict[str, Any] = {
            "server": self.server_url,
        }
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (password masked)."""
        return {
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol.value,
            "username": self.username,
            "password": "********" if self.password else None,
            "country": self.country,
            "city": self.city,
            "weight": self.weight,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 1),
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 3),
            "last_used_at": self.last_used_at,
            "last_checked_at": self.last_checked_at,
            "tags": self.tags,
        }

    def mark_used(self, success: bool = True) -> None:
        """Record a usage of this proxy."""
        self.total_requests += 1
        if not success:
            self.failed_requests += 1
        self.last_used_at = time.time()

    @classmethod
    def from_url(cls, url: str) -> ProxyServer:
        """
        Parse a proxy URL into a ProxyServer.

        Supported formats:
            http://host:port
            http://user:pass@host:port
            https://host:port
            socks5://host:port
            socks5://user:pass@host:port
            host:port (defaults to http)

        Args:
            url: Proxy URL string.

        Returns:
            ProxyServer instance.
        """
        url = url.strip()

        # Handle bare host:port
        if "://" not in url:
            url = f"http://{url}"

        parsed = urlparse(url)

        protocol_str = parsed.scheme.lower()
        try:
            protocol = ProxyProtocol(protocol_str)
        except ValueError:
            protocol = ProxyProtocol.HTTP

        port = parsed.port
        if port is None:
            port = 1080 if protocol in (ProxyProtocol.SOCKS5, ProxyProtocol.SOCKS4) else 8080

        return cls(
            host=parsed.hostname or "localhost",
            port=port,
            protocol=protocol,
            username=parsed.username,
            password=parsed.password,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxyServer:
        """Create from a dictionary."""
        protocol = data.get("protocol", "http")
        if isinstance(protocol, str):
            try:
                protocol = ProxyProtocol(protocol)
            except ValueError:
                protocol = ProxyProtocol.HTTP

        status = data.get("status", "unknown")
        if isinstance(status, str):
            try:
                status = ProxyStatus(status)
            except ValueError:
                status = ProxyStatus.UNKNOWN

        return cls(
            host=data.get("host", "localhost"),
            port=data.get("port", 8080),
            protocol=protocol,
            username=data.get("username"),
            password=data.get("password"),
            country=data.get("country"),
            city=data.get("city"),
            weight=data.get("weight", 1.0),
            status=status,
            latency_ms=data.get("latency_ms", 0.0),
            total_requests=data.get("total_requests", 0),
            failed_requests=data.get("failed_requests", 0),
            last_used_at=data.get("last_used_at", 0.0),
            last_checked_at=data.get("last_checked_at", 0.0),
            tags=data.get("tags", []),
        )

    def __repr__(self) -> str:
        auth = f"{self.username}@" if self.username else ""
        return (
            f"ProxyServer({self.protocol.value}://{auth}{self.host}:{self.port}, "
            f"status={self.status.value}, requests={self.total_requests})"
        )


# ══════════════════════════════════════════════════════════════
# Proxy Manager
# ══════════════════════════════════════════════════════════════

class ProxyManager:
    """
    Manages a pool of proxy servers with rotation, health checking,
    and usage tracking.

    Args:
        config: ProxyConfig from browser configuration.
        proxies: Optional list of ProxyServer instances (overrides config).
        rotation: Rotation strategy (overrides config).
        bypass: Comma-separated bypass rules.
        max_retries: Maximum retries on proxy failure.
        health_check_timeout: Timeout for health checks in seconds.
        unhealthy_threshold: Failure rate threshold to mark proxy unhealthy.

    Example:
        >>> manager = ProxyManager.from_urls([
        ...     "http://proxy1:8080",
        ...     "http://user:pass@proxy2:8080",
        ...     "socks5://proxy3:1080",
        ... ], rotation="round_robin")
        >>>
        >>> proxy = manager.next()
        >>> print(proxy.to_playwright_dict())
        >>>
        >>> # After request completes
        >>> manager.report_success(proxy)
        >>> # or
        >>> manager.report_failure(proxy)
    """

    def __init__(
        self,
        config: ProxyConfig | None = None,
        proxies: list[ProxyServer] | None = None,
        rotation: ProxyRotationStrategy | str | None = None,
        bypass: str | None = None,
        max_retries: int = 3,
        health_check_timeout: float = 10.0,
        unhealthy_threshold: float = 0.5,
    ):
        self._config = config

        # Determine rotation strategy
        if rotation is not None:
            if isinstance(rotation, str):
                self._rotation = ProxyRotationStrategy(rotation)
            else:
                self._rotation = rotation
        elif config and config.rotation:
            self._rotation = config.rotation
        else:
            self._rotation = ProxyRotationStrategy.NONE

        # Bypass rules
        self._bypass = bypass or (config.bypass if config else None)

        # Settings
        self._max_retries = max_retries
        self._health_check_timeout = health_check_timeout
        self._unhealthy_threshold = unhealthy_threshold

        # Initialize proxy pool
        self._proxies: list[ProxyServer] = []
        self._rr_index = 0  # Round-robin counter
        self._lock = asyncio.Lock()

        if proxies:
            self._proxies = list(proxies)
        elif config:
            self._load_from_config(config)

    # ──────────────────────────────────────────────────────────
    # Factory Methods
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_urls(
        cls,
        urls: list[str],
        rotation: str = "round_robin",
        **kwargs: Any,
    ) -> ProxyManager:
        """
        Create a ProxyManager from a list of proxy URL strings.

        Args:
            urls: List of proxy URLs.
            rotation: Rotation strategy name.
            **kwargs: Additional arguments passed to constructor.

        Returns:
            ProxyManager instance.

        Example:
            >>> manager = ProxyManager.from_urls([
            ...     "http://proxy1:8080",
            ...     "socks5://user:pass@proxy2:1080",
            ... ])
        """
        proxies = [ProxyServer.from_url(url) for url in urls]
        return cls(proxies=proxies, rotation=rotation, **kwargs)

    @classmethod
    def from_file(
        cls,
        filepath: str,
        rotation: str = "round_robin",
        **kwargs: Any,
    ) -> ProxyManager:
        """
        Load proxies from a text file (one URL per line).

        Supports:
            - Plain URLs: http://host:port
            - With auth: http://user:pass@host:port
            - Comments: lines starting with #
            - Empty lines: skipped

        Args:
            filepath: Path to the proxy list file.
            rotation: Rotation strategy name.
            **kwargs: Additional arguments.

        Returns:
            ProxyManager instance.
        """
        proxies: list[ProxyServer] = []
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    proxies.append(ProxyServer.from_url(line))
                except Exception as e:
                    logger.warning("Skipping invalid proxy line '%s': %s", line, e)

        logger.info("Loaded %d proxies from %s", len(proxies), filepath)
        return cls(proxies=proxies, rotation=rotation, **kwargs)

    @classmethod
    def from_config(cls, config: ProxyConfig, **kwargs: Any) -> ProxyManager:
        """
        Create a ProxyManager from a ProxyConfig.

        Args:
            config: ProxyConfig instance.
            **kwargs: Additional arguments.

        Returns:
            ProxyManager instance.
        """
        return cls(config=config, **kwargs)

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def rotation(self) -> ProxyRotationStrategy:
        """Current rotation strategy."""
        return self._rotation

    @rotation.setter
    def rotation(self, value: ProxyRotationStrategy | str) -> None:
        if isinstance(value, str):
            value = ProxyRotationStrategy(value)
        self._rotation = value

    @property
    def bypass(self) -> str | None:
        """Proxy bypass rules."""
        return self._bypass

    @property
    def total_proxies(self) -> int:
        """Total number of proxies in the pool."""
        return len(self._proxies)

    @property
    def healthy_count(self) -> int:
        """Number of healthy proxies."""
        return sum(1 for p in self._proxies if p.is_healthy)

    @property
    def unhealthy_count(self) -> int:
        """Number of unhealthy proxies."""
        return sum(1 for p in self._proxies if not p.is_healthy)

    @property
    def has_proxies(self) -> bool:
        """Whether the pool has any proxies."""
        return len(self._proxies) > 0

    @property
    def total_requests(self) -> int:
        """Total requests across all proxies."""
        return sum(p.total_requests for p in self._proxies)

    @property
    def total_failures(self) -> int:
        """Total failures across all proxies."""
        return sum(p.failed_requests for p in self._proxies)

    # ──────────────────────────────────────────────────────────
    # Proxy Selection
    # ──────────────────────────────────────────────────────────

    def next(
        self,
        country: str | None = None,
        tags: list[str] | None = None,
        exclude: list[ProxyServer] | None = None,
    ) -> ProxyServer | None:
        """
        Get the next proxy according to the rotation strategy.

        Args:
            country: Filter by country code (e.g., 'US', 'TH').
            tags: Filter by tags (proxy must have ALL specified tags).
            exclude: Proxies to exclude from selection (e.g., recently failed).

        Returns:
            ProxyServer instance, or None if no proxies available.

        Example:
            >>> proxy = manager.next()
            >>> proxy = manager.next(country="US")
            >>> proxy = manager.next(tags=["residential", "fast"])
            >>> proxy = manager.next(exclude=[failed_proxy])
        """
        candidates = self._get_candidates(country=country, tags=tags, exclude=exclude)

        if not candidates:
            return None

        if self._rotation == ProxyRotationStrategy.NONE:
            return candidates[0]

        if self._rotation == ProxyRotationStrategy.ROUND_ROBIN:
            return self._select_round_robin(candidates)

        if self._rotation == ProxyRotationStrategy.RANDOM:
            return self._select_random(candidates)

        if self._rotation == ProxyRotationStrategy.LEAST_USED:
            return self._select_least_used(candidates)

        # Weighted and fastest fall back to weighted random
        return self._select_weighted(candidates)

    def next_playwright_dict(
        self,
        country: str | None = None,
        tags: list[str] | None = None,
        exclude: list[ProxyServer] | None = None,
    ) -> dict[str, Any] | None:
        """
        Get the next proxy as a Playwright-compatible dictionary.

        Args:
            country: Filter by country code.
            tags: Filter by tags.
            exclude: Proxies to exclude.

        Returns:
            Playwright proxy dict, or None if no proxies available.
        """
        proxy = self.next(country=country, tags=tags, exclude=exclude)
        if proxy is None:
            return None

        result = proxy.to_playwright_dict()
        if self._bypass:
            result["bypass"] = self._bypass
        return result

    def get_all(self) -> list[ProxyServer]:
        """Get all proxies in the pool."""
        return list(self._proxies)

    def healthy_proxies(self) -> list[ProxyServer]:
        """Get all healthy proxies."""
        return [p for p in self._proxies if p.is_healthy]

    def get_by_country(self, country: str) -> list[ProxyServer]:
        """Get all proxies for a specific country."""
        return [p for p in self._proxies if p.country == country.upper()]

    def get_by_tag(self, tag: str) -> list[ProxyServer]:
        """Get all proxies with a specific tag."""
        return [p for p in self._proxies if tag in p.tags]

    # ──────────────────────────────────────────────────────────
    # Usage Reporting
    # ──────────────────────────────────────────────────────────

    def report_success(self, proxy: ProxyServer) -> None:
        """
        Report a successful request through a proxy.

        Args:
            proxy: The proxy that was used.
        """
        proxy.mark_used(success=True)

        # Recover unhealthy proxy if success rate improves
        if proxy.status == ProxyStatus.UNHEALTHY and proxy.success_rate > self._unhealthy_threshold:
            proxy.status = ProxyStatus.HEALTHY
            logger.info("Proxy %s recovered (success_rate=%.2f)", proxy.host, proxy.success_rate)

    def report_failure(self, proxy: ProxyServer) -> None:
        """
        Report a failed request through a proxy.

        If the failure rate exceeds the threshold, the proxy is
        marked as unhealthy.

        Args:
            proxy: The proxy that failed.
        """
        proxy.mark_used(success=False)

        # Mark unhealthy if failure rate is too high
        if (
            proxy.total_requests >= 5
            and proxy.success_rate < self._unhealthy_threshold
        ):
            proxy.status = ProxyStatus.UNHEALTHY
            logger.warning(
                "Proxy %s marked unhealthy (success_rate=%.2f, failures=%d)",
                proxy.host,
                proxy.success_rate,
                proxy.failed_requests,
            )

    def report_latency(self, proxy: ProxyServer, latency_ms: float) -> None:
        """
        Report measured latency for a proxy.

        Args:
            proxy: The proxy that was measured.
            latency_ms: Latency in milliseconds.
        """
        # Exponential moving average
        if proxy.latency_ms == 0:
            proxy.latency_ms = latency_ms
        else:
            alpha = 0.3
            proxy.latency_ms = alpha * latency_ms + (1 - alpha) * proxy.latency_ms

    # ──────────────────────────────────────────────────────────
    # Pool Management
    # ──────────────────────────────────────────────────────────

    def add(self, proxy: ProxyServer | str) -> None:
        """
        Add a proxy to the pool.

        Args:
            proxy: ProxyServer instance or URL string.
        """
        if isinstance(proxy, str):
            proxy = ProxyServer.from_url(proxy)

        # Avoid duplicates
        for existing in self._proxies:
            if existing.host == proxy.host and existing.port == proxy.port:
                logger.debug("Proxy %s:%d already in pool", proxy.host, proxy.port)
                return

        self._proxies.append(proxy)
        logger.info("Added proxy: %s (total=%d)", proxy, len(self._proxies))

    def add_many(self, proxies: list[ProxyServer | str]) -> None:
        """Add multiple proxies to the pool."""
        for p in proxies:
            self.add(p)

    def remove(self, proxy: ProxyServer) -> bool:
        """
        Remove a proxy from the pool.

        Args:
            proxy: The proxy to remove.

        Returns:
            True if the proxy was found and removed.
        """
        for i, existing in enumerate(self._proxies):
            if existing is proxy or (
                existing.host == proxy.host and existing.port == proxy.port
            ):
                self._proxies.pop(i)
                logger.info("Removed proxy: %s (total=%d)", proxy, len(self._proxies))
                return True
        return False

    def remove_by_host(self, host: str, port: int | None = None) -> int:
        """
        Remove proxies by host (and optionally port).

        Args:
            host: Hostname or IP to remove.
            port: Optional port filter.

        Returns:
            Number of proxies removed.
        """
        before = len(self._proxies)
        self._proxies = [
            p for p in self._proxies
            if not (p.host == host and (port is None or p.port == port))
        ]
        removed = before - len(self._proxies)
        if removed > 0:
            logger.info("Removed %d proxy(ies) for host %s", removed, host)
        return removed

    def clear(self) -> None:
        """Remove all proxies from the pool."""
        self._proxies.clear()
        self._rr_index = 0
        logger.info("Proxy pool cleared")

    def reset_stats(self) -> None:
        """Reset usage statistics for all proxies."""
        for proxy in self._proxies:
            proxy.total_requests = 0
            proxy.failed_requests = 0
            proxy.latency_ms = 0.0
            proxy.last_used_at = 0.0
            proxy.status = ProxyStatus.UNKNOWN
        logger.info("Proxy stats reset")

    # ──────────────────────────────────────────────────────────
    # Health Checking
    # ──────────────────────────────────────────────────────────

    async def validate(
        self,
        proxy: ProxyServer,
        test_url: str = "https://httpbin.org/ip",
        timeout: float | None = None,
    ) -> bool:
        """
        Validate a single proxy by making a test request.

        Args:
            proxy: The proxy to validate.
            test_url: URL to request through the proxy.
            timeout: Request timeout in seconds.

        Returns:
            True if the proxy is working.
        """
        import httpx

        timeout = timeout or self._health_check_timeout
        proxy.status = ProxyStatus.CHECKING

        try:
            proxy_url = proxy.url

            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=httpx.Timeout(timeout),
            ) as client:
                start = time.time()
                response = await client.get(test_url)
                latency = (time.time() - start) * 1000

                if response.status_code == 200:
                    proxy.status = ProxyStatus.HEALTHY
                    proxy.latency_ms = latency
                    proxy.last_checked_at = time.time()
                    logger.debug(
                        "Proxy %s:%d healthy (%.0fms)",
                        proxy.host, proxy.port, latency,
                    )
                    return True
                else:
                    proxy.status = ProxyStatus.UNHEALTHY
                    proxy.last_checked_at = time.time()
                    logger.warning(
                        "Proxy %s:%d returned status %d",
                        proxy.host, proxy.port, response.status_code,
                    )
                    return False

        except Exception as e:
            proxy.status = ProxyStatus.UNHEALTHY
            proxy.last_checked_at = time.time()
            logger.warning(
                "Proxy %s:%d validation failed: %s",
                proxy.host, proxy.port, str(e)[:100],
            )
            return False

    async def validate_all(
        self,
        test_url: str = "https://httpbin.org/ip",
        timeout: float | None = None,
        max_concurrent: int = 10,
    ) -> dict[str, bool]:
        """
        Validate all proxies concurrently.

        Args:
            test_url: URL to request through each proxy.
            timeout: Per-proxy timeout in seconds.
            max_concurrent: Maximum concurrent validations.

        Returns:
            Dictionary mapping proxy URL to health status.
        """
        if not self._proxies:
            return {}

        semaphore = asyncio.Semaphore(max_concurrent)
        results: dict[str, bool] = {}

        async def _check(proxy: ProxyServer) -> None:
            async with semaphore:
                healthy = await self.validate(proxy, test_url, timeout)
                results[proxy.url] = healthy

        tasks = [_check(p) for p in self._proxies]
        await asyncio.gather(*tasks, return_exceptions=True)

        healthy_count = sum(1 for v in results.values() if v)
        logger.info(
            "Validation complete: %d/%d healthy",
            healthy_count,
            len(results),
        )

        return results

    async def remove_unhealthy(self) -> int:
        """
        Remove all unhealthy proxies from the pool.

        Returns:
            Number of proxies removed.
        """
        before = len(self._proxies)
        self._proxies = [p for p in self._proxies if p.is_healthy]
        removed = before - len(self._proxies)
        if removed > 0:
            logger.info("Removed %d unhealthy proxy(ies)", removed)
        return removed

    # ──────────────────────────────────────────────────────────
    # Selection Strategies (Internal)
    # ──────────────────────────────────────────────────────────

    def _get_candidates(
        self,
        country: str | None = None,
        tags: list[str] | None = None,
        exclude: list[ProxyServer] | None = None,
    ) -> list[ProxyServer]:
        """Filter proxies by criteria."""
        candidates = list(self._proxies)

        # Filter unhealthy
        candidates = [p for p in candidates if p.is_available]

        # Filter by country
        if country:
            country_upper = country.upper()
            candidates = [p for p in candidates if p.country == country_upper]

        # Filter by tags
        if tags:
            candidates = [
                p for p in candidates
                if all(tag in p.tags for tag in tags)
            ]

        # Exclude specific proxies
        if exclude:
            exclude_set = {id(p) for p in exclude}
            candidates = [p for p in candidates if id(p) not in exclude_set]

        return candidates

    def _select_round_robin(self, candidates: list[ProxyServer]) -> ProxyServer:
        """Select next proxy in round-robin order."""
        if not candidates:
            raise RuntimeError("No proxy candidates available")
        idx = self._rr_index % len(candidates)
        self._rr_index += 1
        return candidates[idx]

    def _select_random(self, candidates: list[ProxyServer]) -> ProxyServer:
        """Select a random proxy."""
        return secrets.choice(candidates)

    def _select_least_used(self, candidates: list[ProxyServer]) -> ProxyServer:
        """Select the proxy with the fewest total requests."""
        return min(candidates, key=lambda p: p.total_requests)

    def _select_weighted(self, candidates: list[ProxyServer]) -> ProxyServer:
        """Select a proxy using weighted random selection."""
        weights = [p.weight for p in candidates]
        total = sum(weights)
        if total <= 0:
            return secrets.choice(candidates)

        r = secrets.SystemRandom().uniform(0, total)
        cumulative = 0.0
        for proxy, weight in zip(candidates, weights, strict=True):
            cumulative += weight
            if r <= cumulative:
                return proxy

        return candidates[-1]

    def _select_fastest(self, candidates: list[ProxyServer]) -> ProxyServer:
        """Select the proxy with the lowest measured latency."""
        # Filter to proxies with latency data
        with_latency = [p for p in candidates if p.latency_ms > 0]
        if with_latency:
            return min(with_latency, key=lambda p: p.latency_ms)
        # Fall back to random if no latency data
        return secrets.choice(candidates)

    # ──────────────────────────────────────────────────────────
    # Config Loading
    # ──────────────────────────────────────────────────────────

    def _load_from_config(self, config: ProxyConfig) -> None:
        """Load proxies from a ProxyConfig."""
        if config.proxy_list:
            for url in config.proxy_list:
                try:
                    proxy = ProxyServer.from_url(url)
                    self._proxies.append(proxy)
                except Exception as e:
                    logger.warning("Invalid proxy URL '%s': %s", url, e)
        elif config.server:
            proxy = ProxyServer(
                host=urlparse(config.server).hostname or "localhost",
                port=urlparse(config.server).port or 8080,
                protocol=ProxyProtocol(urlparse(config.server).scheme or "http"),
                username=config.username,
                password=config.password,
            )
            self._proxies.append(proxy)

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize the proxy manager state."""
        return {
            "rotation": self._rotation.value,
            "bypass": self._bypass,
            "total_proxies": self.total_proxies,
            "healthy_count": self.healthy_count,
            "unhealthy_count": self.unhealthy_count,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "proxies": [p.to_dict() for p in self._proxies],
        }

    def to_config(self) -> ProxyConfig:
        """Convert back to a ProxyConfig."""
        return ProxyConfig(
            server=self._proxies[0].server_url if self._proxies else None,
            username=self._proxies[0].username if self._proxies else None,
            password=self._proxies[0].password if self._proxies else None,
            bypass=self._bypass,
            rotation=self._rotation,
            proxy_list=[p.url for p in self._proxies],
        )

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics for monitoring."""
        return {
            "rotation": self._rotation.value,
            "bypass": self._bypass,
            "total_proxies": self.total_proxies,
            "healthy": self.healthy_count,
            "unhealthy": self.unhealthy_count,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "overall_success_rate": (
                round(
                    (self.total_requests - self.total_failures) / self.total_requests, 3
                )
                if self.total_requests > 0
                else 1.0
            ),
            "proxies": [p.to_dict() for p in self._proxies],
        }

    def __repr__(self) -> str:
        return (
            f"ProxyManager(proxies={self.total_proxies}, "
            f"healthy={self.healthy_count}, "
            f"rotation={self._rotation.value})"
        )

    def __len__(self) -> int:
        return len(self._proxies)

    def __iter__(self):
        return iter(self._proxies)

    def __bool__(self) -> bool:
        return len(self._proxies) > 0
