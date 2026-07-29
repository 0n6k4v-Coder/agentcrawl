"""
AgentCrawl — Proxy Configuration (Pydantic)
===============================================

Pydantic-based proxy configuration with environment variable binding,
validation, proxy list loading (from string, file, or URL), and
conversion to runtime ProxyConfig / ProxyManager objects.

Usage:
    from agentcrawl.config.proxy_config import ProxySettings

    # From environment variables
    settings = ProxySettings()

    # From keyword arguments
    settings = ProxySettings(
        proxy_url="http://user:pass@proxy:8080",
        rotation="round_robin",
    )

    # With proxy list
    settings = ProxySettings(
        proxy_list="http://p1:8080,http://p2:8080,socks5://p3:1080",
        rotation="least_used",
    )

    # Load proxies from file
    settings = ProxySettings.from_file("proxies.txt", rotation="random")

    # Convert to runtime objects
    proxy_config = settings.to_proxy_config()      # For BrowserConfig
    proxy_manager = settings.to_proxy_manager()    # For standalone use

    # Validate connectivity
    results = await settings.validate_proxies()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("agentcrawl.config.proxy")


# ══════════════════════════════════════════════════════════════
# Proxy Settings (Pydantic)
# ══════════════════════════════════════════════════════════════

class ProxySettings(BaseSettings):
    """
    Pydantic-based proxy configuration with env var support.

    All fields can be set via environment variables with the
    ``AGENTCRAWL_PROXY_`` prefix.

    Attributes:
        enabled: Whether proxy is enabled.
        url: Primary proxy server URL.
        username: Proxy authentication username.
        password: Proxy authentication password.
        bypass: Comma-separated hosts to bypass proxy.
        rotation: Rotation strategy ('none', 'round_robin', 'random', 'least_used').
        proxy_list: Comma-separated proxy URLs for rotation.
        proxy_file: Path to a file containing proxy URLs (one per line).
        proxy_url_source: URL to fetch proxy list from.
        country_filter: Filter proxies by country code (e.g., 'US', 'TH').
        protocol_filter: Filter by protocol ('http', 'https', 'socks5').
        health_check: Whether to validate proxies before use.
        health_check_url: URL used for proxy health checks.
        health_check_timeout: Timeout for health checks in seconds.
        unhealthy_threshold: Failure rate (0-1) to mark proxy unhealthy.
        max_retries: Max retries per request on proxy failure.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTCRAWL_PROXY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Core ──────────────────────────────────────────────────
    enabled: bool = Field(
        default=False,
        description="Whether proxy is enabled",
    )
    url: str | None = Field(
        default=None,
        description="Primary proxy server URL (http://host:port)",
    )
    username: str | None = Field(
        default=None,
        description="Proxy authentication username",
    )
    password: str | None = Field(
        default=None,
        description="Proxy authentication password",
    )
    bypass: str | None = Field(
        default=None,
        description="Comma-separated hosts to bypass proxy",
    )

    # ── Rotation ──────────────────────────────────────────────
    rotation: str = Field(
        default="none",
        description="Rotation strategy: none, round_robin, random, least_used",
    )
    proxy_list: str | None = Field(
        default=None,
        description="Comma-separated proxy URLs for rotation",
    )
    proxy_file: str | None = Field(
        default=None,
        description="Path to file with proxy URLs (one per line)",
    )
    proxy_url_source: str | None = Field(
        default=None,
        description="URL to fetch proxy list from",
    )

    # ── Filtering ─────────────────────────────────────────────
    country_filter: str | None = Field(
        default=None,
        description="Filter proxies by country code (e.g., US, TH)",
    )
    protocol_filter: str | None = Field(
        default=None,
        description="Filter by protocol: http, https, socks5, socks4",
    )

    # ── Health Check ──────────────────────────────────────────
    health_check: bool = Field(
        default=False,
        description="Validate proxies before use",
    )
    health_check_url: str = Field(
        default="https://httpbin.org/ip",
        description="URL used for proxy health checks",
    )
    health_check_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Health check timeout in seconds",
    )
    unhealthy_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Failure rate threshold to mark proxy unhealthy",
    )

    # ── Retry ─────────────────────────────────────────────────
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retries per request on proxy failure",
    )

    # ──────────────────────────────────────────────────────────
    # Validators
    # ──────────────────────────────────────────────────────────

    @field_validator("rotation")
    @classmethod
    def validate_rotation(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"none", "round_robin", "random", "least_used"}
        if v not in allowed:
            raise ValueError(
                f"Invalid rotation '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        parsed = urlparse(v if "://" in v else f"http://{v}")
        if not parsed.hostname:
            raise ValueError(f"Invalid proxy URL: '{v}' — missing hostname")
        return v

    @field_validator("protocol_filter")
    @classmethod
    def validate_protocol_filter(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.lower().strip()
        allowed = {"http", "https", "socks5", "socks4"}
        if v not in allowed:
            raise ValueError(
                f"Invalid protocol_filter '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @model_validator(mode="after")
    def auto_enable(self) -> ProxySettings:
        """Auto-enable proxy if URL or list is provided."""
        if not self.enabled and (self.url or self.proxy_list or self.proxy_file):
            object.__setattr__(self, "enabled", True)
        return self

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def has_proxy(self) -> bool:
        """Whether any proxy is configured."""
        return bool(self.url or self.proxy_list or self.proxy_file)

    @property
    def proxy_urls(self) -> list[str]:
        """
        Get all configured proxy URLs as a list.

        Merges proxy_list, proxy_file, and primary url.
        """
        urls: list[str] = []

        # From proxy_list string
        if self.proxy_list:
            for u in self.proxy_list.split(","):
                u = u.strip()
                if u:
                    urls.append(u)

        # From proxy_file
        if self.proxy_file:
            file_urls = self._load_from_file(self.proxy_file)
            urls.extend(file_urls)

        # Primary URL (add last if not already present)
        if self.url and self.url not in urls:
            urls.append(self.url)

        return urls

    @property
    def proxy_count(self) -> int:
        """Number of configured proxies."""
        return len(self.proxy_urls)

    @property
    def needs_auth(self) -> bool:
        """Whether proxy authentication is configured."""
        return bool(self.username)

    # ──────────────────────────────────────────────────────────
    # Conversion to Runtime Objects
    # ──────────────────────────────────────────────────────────

    def to_proxy_config(self) -> Any:
        """
        Convert to the runtime ProxyConfig dataclass used by
        the browser automation layer.

        Returns:
            agentcrawl.browser.config.ProxyConfig instance,
            or None if proxy is disabled.
        """
        if not self.enabled or not self.has_proxy:
            return None

        from agentcrawl.browser.config import ProxyConfig, ProxyRotationStrategy

        return ProxyConfig(
            server=self.url,
            username=self.username,
            password=self.password,
            bypass=self.bypass,
            rotation=ProxyRotationStrategy(self.rotation),
            proxy_list=self.proxy_urls,
        )

    def to_proxy_manager(self) -> Any:
        """
        Convert to a ProxyManager instance for standalone use.

        Returns:
            agentcrawl.browser.proxy.ProxyManager instance,
            or None if proxy is disabled.
        """
        if not self.enabled or not self.has_proxy:
            return None

        from agentcrawl.browser.proxy import ProxyManager, ProxyServer

        proxies = [ProxyServer.from_url(u) for u in self.proxy_urls]

        # Apply filters
        if self.country_filter:
            proxies = [
                p for p in proxies
                if p.country is None or p.country == self.country_filter.upper()
            ]

        if self.protocol_filter:
            proxies = [
                p for p in proxies
                if p.protocol.value == self.protocol_filter
            ]

        return ProxyManager(
            proxies=proxies,
            rotation=self.rotation,
            bypass=self.bypass,
            max_retries=self.max_retries,
            health_check_timeout=self.health_check_timeout,
            unhealthy_threshold=self.unhealthy_threshold,
        )

    def to_playwright_dict(self) -> dict[str, Any] | None:
        """
        Convert to Playwright-compatible proxy dictionary.

        Returns:
            Playwright proxy dict, or None if proxy is disabled.
        """
        if not self.enabled:
            return None

        server = self.url
        if not server and self.proxy_urls:
            server = self.proxy_urls[0]

        if not server:
            return None

        # Ensure protocol prefix
        if "://" not in server:
            server = f"http://{server}"

        result: dict[str, Any] = {"server": server}

        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        if self.bypass:
            result["bypass"] = self.bypass

        return result

    # ──────────────────────────────────────────────────────────
    # Proxy List Loading
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_from_file(filepath: str) -> list[str]:
        """
        Load proxy URLs from a text file.

        Supports:
            - One URL per line
            - Comments (lines starting with #)
            - Empty lines (skipped)
            - host:port format (defaults to http://)

        Args:
            filepath: Path to the proxy list file.

        Returns:
            List of proxy URL strings.
        """
        path = Path(filepath)
        if not path.exists():
            logger.warning("Proxy file not found: %s", filepath)
            return []

        urls: list[str] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Normalize
                if "://" not in line:
                    line = f"http://{line}"
                urls.append(line)

        logger.info("Loaded %d proxies from %s", len(urls), filepath)
        return urls

    async def _load_from_url(self, url: str) -> list[str]:
        """
        Fetch proxy list from a remote URL.

        Args:
            url: URL returning a text list of proxies.

        Returns:
            List of proxy URL strings.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url)
                response.raise_for_status()

                urls: list[str] = []
                for line in response.text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "://" not in line:
                        line = f"http://{line}"
                    urls.append(line)

                logger.info("Loaded %d proxies from %s", len(urls), url)
                return urls

        except Exception as e:
            logger.warning("Failed to fetch proxy list from %s: %s", url, e)
            return []

    async def load_proxies(self) -> list[str]:
        """
        Load all proxies from all configured sources.

        Merges proxy_list, proxy_file, and proxy_url_source.

        Returns:
            Deduplicated list of proxy URLs.
        """
        urls: list[str] = []

        # From inline list
        if self.proxy_list:
            for u in self.proxy_list.split(","):
                u = u.strip()
                if u:
                    if "://" not in u:
                        u = f"http://{u}"
                    urls.append(u)

        # From file
        if self.proxy_file:
            urls.extend(self._load_from_file(self.proxy_file))

        # From remote URL
        if self.proxy_url_source:
            remote = await self._load_from_url(self.proxy_url_source)
            urls.extend(remote)

        # Primary URL
        if self.url and self.url not in urls:
            urls.append(self.url)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)

        return unique

    # ──────────────────────────────────────────────────────────
    # Validation
    # ──────────────────────────────────────────────────────────

    async def validate_proxies(
        self,
        test_url: str | None = None,
        timeout: float | None = None,
        max_concurrent: int = 10,
    ) -> dict[str, bool]:
        """
        Validate all configured proxies by making test requests.

        Args:
            test_url: URL to test against (default: health_check_url).
            timeout: Per-proxy timeout (default: health_check_timeout).
            max_concurrent: Max concurrent validations.

        Returns:
            Dictionary mapping proxy URL to health status.
        """
        import asyncio

        import httpx

        urls = await self.load_proxies()
        if not urls:
            return {}

        test_url = test_url or self.health_check_url
        timeout = timeout or self.health_check_timeout
        results: dict[str, bool] = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _check(proxy_url: str) -> None:
            async with semaphore:
                try:
                    async with httpx.AsyncClient(
                        proxy=proxy_url,
                        timeout=httpx.Timeout(timeout),
                    ) as client:
                        resp = await client.get(test_url)
                        results[proxy_url] = resp.status_code == 200
                except Exception:
                    results[proxy_url] = False

        tasks = [_check(u) for u in urls]
        await asyncio.gather(*tasks, return_exceptions=True)

        healthy = sum(1 for v in results.values() if v)
        logger.info(
            "Proxy validation: %d/%d healthy",
            healthy,
            len(results),
        )

        return results

    def validate_config(self) -> list[str]:
        """
        Validate configuration and return warnings.

        Returns:
            List of warning messages.
        """
        warnings: list[str] = []

        if self.enabled and not self.has_proxy:
            warnings.append("Proxy enabled but no proxy URL or list configured")

        if self.rotation != "none" and self.proxy_count <= 1:
            warnings.append(
                f"Rotation '{self.rotation}' configured but only "
                f"{self.proxy_count} proxy available"
            )

        if self.needs_auth and not self.password:
            warnings.append("Proxy username set but password is missing")

        if self.proxy_file and not Path(self.proxy_file).exists():
            warnings.append(f"Proxy file not found: {self.proxy_file}")

        if self.health_check and not self.health_check_url:
            warnings.append("Health check enabled but no health_check_url set")

        return warnings

    # ──────────────────────────────────────────────────────────
    # Factory Methods
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, prefix: str = "AGENTCRAWL_PROXY") -> ProxySettings:
        """Create settings from environment variables."""
        return cls(_env_prefix=f"{prefix}_")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxySettings:
        """Create settings from a dictionary."""
        return cls(**data)

    @classmethod
    def from_file(
        cls,
        filepath: str,
        rotation: str = "round_robin",
        **kwargs: Any,
    ) -> ProxySettings:
        """
        Create settings with proxies loaded from a file.

        Args:
            filepath: Path to proxy list file.
            rotation: Rotation strategy.
            **kwargs: Additional settings overrides.

        Returns:
            ProxySettings instance.
        """
        return cls(
            enabled=True,
            proxy_file=filepath,
            rotation=rotation,
            **kwargs,
        )

    @classmethod
    def from_urls(
        cls,
        urls: list[str],
        rotation: str = "round_robin",
        **kwargs: Any,
    ) -> ProxySettings:
        """
        Create settings from a list of proxy URLs.

        Args:
            urls: List of proxy URL strings.
            rotation: Rotation strategy.
            **kwargs: Additional settings overrides.

        Returns:
            ProxySettings instance.
        """
        return cls(
            enabled=True,
            proxy_list=",".join(urls),
            rotation=rotation,
            **kwargs,
        )

    @classmethod
    def disabled(cls) -> ProxySettings:
        """Create a disabled proxy configuration."""
        return cls(enabled=False)

    # ──────────────────────────────────────────────────────────
    # Presets
    # ──────────────────────────────────────────────────────────

    @classmethod
    def preset_single(cls, url: str, **kwargs: Any) -> ProxySettings:
        """Single proxy, no rotation."""
        return cls(enabled=True, url=url, rotation="none", **kwargs)

    @classmethod
    def preset_rotating(cls, urls: list[str], **kwargs: Any) -> ProxySettings:
        """Rotating proxy pool (round-robin)."""
        return cls.from_urls(urls, rotation="round_robin", **kwargs)

    @classmethod
    def preset_random(cls, urls: list[str], **kwargs: Any) -> ProxySettings:
        """Random proxy selection."""
        return cls.from_urls(urls, rotation="random", **kwargs)

    @classmethod
    def preset_authenticated(
        cls,
        url: str,
        username: str,
        password: str,
        **kwargs: Any,
    ) -> ProxySettings:
        """Single authenticated proxy."""
        return cls(
            enabled=True,
            url=url,
            username=username,
            password=password,
            rotation="none",
            **kwargs,
        )

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self, exclude_none: bool = True, mask_password: bool = True) -> dict[str, Any]:
        """
        Convert to a plain dictionary.

        Args:
            exclude_none: Exclude None values.
            mask_password: Mask the password in output.

        Returns:
            Configuration dictionary.
        """
        data = self.model_dump(exclude_none=exclude_none)

        if mask_password and "password" in data and data["password"]:
            data["password"] = "********"

        # Add computed fields
        data["proxy_count"] = self.proxy_count
        data["has_proxy"] = self.has_proxy

        return data

    def to_json(self, mask_password: bool = True) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(
            self.to_dict(mask_password=mask_password),
            ensure_ascii=False,
            default=str,
        )

    def to_env_string(self) -> str:
        """Generate environment variable assignments."""
        lines = []
        for key, value in self.to_dict(exclude_none=True, mask_password=False).items():
            env_key = f"AGENTCRAWL_PROXY_{key.upper()}"
            if isinstance(value, bool):
                env_value = str(value).lower()
            else:
                env_value = str(value)
            lines.append(f"{env_key}={env_value}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────
    # Merge / Override
    # ──────────────────────────────────────────────────────────

    def merge(self, overrides: dict[str, Any]) -> ProxySettings:
        """Create a new settings instance with overridden values."""
        current = self.model_dump()
        current.update(overrides)
        return ProxySettings(**current)

    def with_rotation(self, strategy: str) -> ProxySettings:
        """Return a copy with a different rotation strategy."""
        return self.merge({"rotation": strategy})

    def with_proxies(self, urls: list[str]) -> ProxySettings:
        """Return a copy with a different proxy list."""
        return self.merge({"proxy_list": ",".join(urls), "enabled": True})

    # ──────────────────────────────────────────────────────────
    # Representation
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        if not self.enabled:
            return "ProxySettings(disabled)"
        return (
            f"ProxySettings(enabled=True, "
            f"proxies={self.proxy_count}, "
            f"rotation={self.rotation!r})"
        )
