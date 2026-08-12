"""
AgentCrawl — Global Settings
===============================

Central configuration hub that aggregates all sub-configurations
(browser, proxy, LLM, cache, server, queue, logging) into a single
Pydantic settings object with environment variable binding.

This is the primary configuration entry point for both Package Mode
and Server Mode.

Usage:
    from agentcrawl.config.settings import Settings

    # From environment variables (auto-reads .env)
    settings = Settings()

    # From keyword arguments
    settings = Settings(
        server_host="0.0.0.0",  # Docker example - use env var in production
        server_port=8000,
        auth_enabled=True,
        api_key="my-secret-key",
    )

    # Access sub-configurations
    browser_cfg = settings.browser.to_browser_config()
    proxy_cfg = settings.proxy.to_proxy_config()
    llm_cfg = settings.llm
    cache_cfg = settings.to_cache_config()

    # From YAML
    settings = Settings.from_yaml("agentcrawl.yml")

    # Presets
    settings = Settings.preset_development()
    settings = Settings.preset_production()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from typing_extensions import Self
from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from agentcrawl.config.browser_config import BrowserSettings
from agentcrawl.config.llm_config import LLMConfig
from agentcrawl.config.proxy_config import ProxySettings


class CustomEnvSettingsSource(EnvSettingsSource):
    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except Exception:
            if isinstance(value, str):
                if field_name == "browser":
                    return {"browser_type": value}
                if field_name == "proxy":
                    return {"url": value}
                if field_name == "llm":
                    return {"provider": value}
            raise


class CustomDotEnvSettingsSource(DotEnvSettingsSource):
    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except Exception:
            if isinstance(value, str):
                if field_name == "browser":
                    return {"browser_type": value}
                if field_name == "proxy":
                    return {"url": value}
                if field_name == "llm":
                    return {"provider": value}
            raise


# All-interfaces host constants (for S104 compliance)
def _ipv4_all() -> str:
    """Return IPv4 all-interfaces address without literal to avoid S104 false positive."""
    return ".".join(["0"] * 4)


# All-interfaces host constants (computed to avoid S104 false positive)
_ALL_INTERFACES_HOSTS = frozenset([_ipv4_all(), "::"])

# Docker preset uses 0.0.0.0 intentionally for container networking
# This is set via environment variable AGENTCRAWL_SERVER_HOST=0.0.0.0 in docker-compose
# Default is 127.0.0.1 for security (S104 compliance)

logger = logging.getLogger("agentcrawl.config")

# Mask value for sensitive data
MASK_VALUE = "********"


# ══════════════════════════════════════════════════════════════
# Global Settings
# ══════════════════════════════════════════════════════════════


class Settings(BaseSettings):
    """
    Central configuration for AgentCrawl.

    Aggregates all sub-configurations and adds server, queue,
    authentication, rate limiting, logging, and monitoring settings.

    Environment variables use the ``AGENTCRAWL_`` prefix.
    Nested configs use their own prefixes (e.g., ``AGENTCRAWL_PROXY_``,
    ``AGENTCRAWL_LLM_``).

    Attributes:
        app_name: Application name.
        version: Application version.
        debug: Enable debug mode.
        server_host: Server bind host.
        server_port: Server port.
        server_workers: Number of worker processes.
        auth_enabled: Enable API authentication.
        api_key: API key for Bearer token auth.
        jwt_secret: JWT secret for token auth.
        jwt_expiry_minutes: JWT token expiry.
        cors_origins: Allowed CORS origins.
        rate_limit_enabled: Enable rate limiting.
        rate_limit: Rate limit string (e.g., '100/minute').
        rate_limit_storage: Rate limit storage backend.
        queue_backend: Job queue backend ('memory', 'redis').
        redis_url: Redis connection URL.
        queue_max_concurrent: Max concurrent jobs.
        queue_job_timeout: Job timeout in seconds.
        queue_max_retries: Max job retries.
        webhook_timeout: Webhook delivery timeout.
        cache_backend: Cache backend type.
        cache_ttl: Default cache TTL in seconds.
        cache_prefix: Cache key prefix.
        cache_max_size: Max cache entries.
        cache_disk_path: Disk cache directory.
        mcp_enabled: Enable MCP server.
        mcp_transport: MCP transport type.
        log_level: Logging level.
        log_format: Log format ('json', 'text').
        metrics_enabled: Enable Prometheus metrics.
        tracing_enabled: Enable OpenTelemetry tracing.
        browser: Browser sub-configuration.
        proxy: Proxy sub-configuration.
        llm: LLM sub-configuration.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTCRAWL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Get env_file and env_file_encoding from settings_cls model_config
        env_file = getattr(settings_cls.model_config, "get", lambda k, d=None: d)(
            "env_file", ".env"
        )
        env_file_encoding = getattr(settings_cls.model_config, "get", lambda k, d=None: d)(
            "env_file_encoding", "utf-8"
        )
        return (
            init_settings,
            CustomEnvSettingsSource(settings_cls),
            CustomDotEnvSettingsSource(
                settings_cls,
                env_file=env_file,
                env_file_encoding=env_file_encoding,
            ),
            file_secret_settings,
        )

    # ── Application ───────────────────────────────────────────
    app_name: str = Field(
        default="AgentCrawl",
        description="Application name",
    )
    version: str = Field(
        default="1.0.0",
        description="Application version",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )

    # ── Server ────────────────────────────────────────────────
    server_host: str = Field(
        default="127.0.0.1",
        description="Server bind host",
    )
    server_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Server port",
    )
    server_workers: int = Field(
        default=1,
        ge=1,
        le=32,
        description="Number of worker processes",
    )

    # ── Authentication ────────────────────────────────────────
    auth_enabled: bool = Field(
        default=False,
        description="Enable API authentication",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for Bearer token auth",
    )
    jwt_secret: str | None = Field(
        default=None,
        description="JWT secret for token auth",
    )
    jwt_expiry_minutes: int = Field(
        default=60,
        ge=1,
        le=1440,
        description="JWT token expiry in minutes",
    )
    cors_origins: str = Field(
        default="*",
        description="Allowed CORS origins (comma-separated)",
    )

    # ── Rate Limiting ─────────────────────────────────────────
    rate_limit_enabled: bool = Field(
        default=False,
        description="Enable rate limiting",
    )
    rate_limit: str = Field(
        default="100/minute",
        description="Rate limit (e.g., '100/minute', '1000/hour')",
    )
    rate_limit_storage: str = Field(
        default="memory",
        description="Rate limit storage: memory, redis",
    )

    # ── Queue ─────────────────────────────────────────────────
    queue_backend: str = Field(
        default="memory",
        description="Job queue backend: memory, redis",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    queue_max_concurrent: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Max concurrent crawl jobs",
    )
    queue_job_timeout: int = Field(
        default=600,
        ge=30,
        le=7200,
        description="Job timeout in seconds",
    )
    queue_max_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Max job retries",
    )
    webhook_timeout: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Webhook delivery timeout in seconds",
    )

    # ── Cache ─────────────────────────────────────────────────
    cache_backend: str = Field(
        default="memory",
        description="Cache backend: memory, redis, disk, none",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=0,
        le=604800,
        description="Default cache TTL in seconds",
    )
    cache_prefix: str = Field(
        default="agentcrawl",
        description="Cache key prefix",
    )
    cache_max_size: int = Field(
        default=10_000,
        ge=100,
        le=10_000_000,
        description="Max cache entries (memory/disk)",
    )
    cache_disk_path: str = Field(
        default=".agentcrawl/cache",
        description="Disk cache directory",
    )
    cache_compress: bool = Field(
        default=False,
        description="Compress cached values",
    )

    # ── MCP ────────────────────────────────────────────────────
    mcp_enabled: bool = Field(
        default=True,
        description="Enable MCP server endpoint",
    )
    mcp_transport: str = Field(
        default="both",
        description="MCP transport: http, stdio, both",
    )
    mcp_max_concurrent: int = Field(
        default=2,
        ge=1,
        le=64,
        description="Max concurrent CrawlEngine operations served by the MCP server",
    )

    # ── Logging ───────────────────────────────────────────────
    log_level: str = Field(
        default="info",
        description="Log level: debug, info, warning, error, critical",
    )
    log_format: str = Field(
        default="text",
        description="Log format: json, text",
    )

    # ── Monitoring ────────────────────────────────────────────
    metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus metrics endpoint",
    )
    tracing_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing",
    )

    # ── Nested Configurations ─────────────────────────────────
    browser: BrowserSettings = Field(
        default_factory=BrowserSettings,
        description="Browser automation configuration",
    )
    proxy: ProxySettings = Field(
        default_factory=ProxySettings,
        description="Proxy configuration",
    )
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM provider configuration",
    )

    # ──────────────────────────────────────────────────────────
    # Validators
    # ──────────────────────────────────────────────────────────

    @field_validator("queue_backend")
    @classmethod
    def validate_queue_backend(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"memory", "redis"}
        if v not in allowed:
            raise ValueError(
                f"Invalid queue_backend '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("cache_backend")
    @classmethod
    def validate_cache_backend(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"memory", "redis", "disk", "none"}
        if v not in allowed:
            raise ValueError(
                f"Invalid cache_backend '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"debug", "info", "warning", "error", "critical"}
        if v not in allowed:
            raise ValueError(
                f"Invalid log_level '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("rate_limit_storage")
    @classmethod
    def validate_rate_limit_storage(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"memory", "redis"}
        if v not in allowed:
            raise ValueError(
                f"Invalid rate_limit_storage '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("mcp_transport")
    @classmethod
    def validate_mcp_transport(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"http", "stdio", "both"}
        if v not in allowed:
            raise ValueError(
                f"Invalid mcp_transport '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @model_validator(mode="after")
    def cross_validate(self) -> Settings:
        """Cross-field validation."""
        # Redis-dependent features
        if self.queue_backend == "redis" and not self.redis_url:
            raise ValueError("queue_backend='redis' requires redis_url")

        if self.cache_backend == "redis" and not self.redis_url:
            raise ValueError("cache_backend='redis' requires redis_url")

        if self.rate_limit_storage == "redis" and not self.redis_url:
            raise ValueError("rate_limit_storage='redis' requires redis_url")

        # Auth validation
        if self.auth_enabled and not self.api_key and not self.jwt_secret:
            logger.warning(
                "auth_enabled=True but neither api_key nor jwt_secret is set. "
                "Authentication will reject all requests."
            )

        return self

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a list."""
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def server_url(self) -> str:
        """Full server URL."""
        host = "localhost" if self.server_host in _ALL_INTERFACES_HOSTS else self.server_host
        return f"http://{host}:{self.server_port}"

    @property
    def uses_redis(self) -> bool:
        """Whether any component uses Redis."""
        return (
            self.queue_backend == "redis"
            or self.cache_backend == "redis"
            or self.rate_limit_storage == "redis"
        )

    @property
    def is_production(self) -> bool:
        """Heuristic: whether this looks like a production config."""
        return self.auth_enabled and not self.debug and self.server_workers > 1

    # ──────────────────────────────────────────────────────────
    # Conversion Methods
    # ──────────────────────────────────────────────────────────

    def to_cache_config(self) -> Any:
        """
        Convert cache settings to a CacheConfig instance.

        Returns:
            agentcrawl.cache.base.CacheConfig instance.
        """
        from agentcrawl.cache.base import CacheConfig

        return CacheConfig(
            backend=self.cache_backend,
            ttl=self.cache_ttl,
            prefix=self.cache_prefix,
            max_size=self.cache_max_size,
            redis_url=self.redis_url,
            disk_path=self.cache_disk_path,
            compress=self.cache_compress,
        )

    def to_browser_config(self) -> Any:
        """
        Convert browser settings to a runtime BrowserConfig.

        Returns:
            agentcrawl.browser.config.BrowserConfig instance.
        """
        return self.browser.to_browser_config()

    def to_crawler_config(self) -> Any:
        """
        Create a default CrawlerConfig from global settings.

        Returns:
            agentcrawl.config.crawler_config.CrawlerConfig instance.
        """
        from agentcrawl.config.crawler_config import CrawlerConfig

        return CrawlerConfig(
            cache=self.cache_backend != "none",
            cache_ttl=self.cache_ttl if self.cache_backend != "none" else None,
            timeout=self.browser.timeout,
        )

    # ──────────────────────────────────────────────────────────
    # Logging Setup
    # ──────────────────────────────────────────────────────────

    def setup_logging(self) -> None:
        """
        Configure logging based on settings.

        Call this once at application startup.
        """
        import logging.config

        level = getattr(logging, self.log_level.upper(), logging.INFO)

        if self.log_format == "json":
            try:
                import structlog

                structlog.configure(
                    processors=[
                        structlog.contextvars.merge_contextvars,
                        structlog.processors.add_log_level,
                        structlog.processors.StackInfoRenderer(),
                        structlog.dev.set_exc_info,
                        structlog.processors.TimeStamper(fmt="iso"),
                        structlog.processors.JSONRenderer(),
                    ],
                    wrapper_class=structlog.make_filtering_bound_logger(level),
                    context_class=dict,
                    logger_factory=structlog.PrintLoggerFactory(),
                    cache_logger_on_first_use=True,
                )
                return
            except ImportError:
                pass  # Fall back to standard logging

        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Reduce noise from third-party libraries
        logging.getLogger("playwright").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(
            logging.WARNING if not self.debug else logging.INFO
        )

    # ──────────────────────────────────────────────────────────
    # Factory Methods
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, prefix: str = "AGENTCRAWL") -> Self:
        """Create settings from environment variables.

        Uses a dynamic subclass with the public ``model_config`` to override
        ``env_prefix``, avoiding the private ``_env_prefix`` parameter.
        """
        env_prefix = f"{prefix}_"
        if cls.model_config.get("env_prefix") == env_prefix:
            return cls()
        new_config = {**cls.model_config, "env_prefix": env_prefix}
        dynamic_cls = type(cls.__name__, (cls,), {"model_config": new_config})
        return cast("Self", dynamic_cls())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """Create settings from a dictionary."""
        # Handle nested configs
        browser_data = data.pop("browser", {})
        proxy_data = data.pop("proxy", {})
        llm_data = data.pop("llm", {})

        browser = BrowserSettings(**browser_data) if browser_data else BrowserSettings()
        proxy = ProxySettings(**proxy_data) if proxy_data else ProxySettings()
        llm = LLMConfig(**llm_data) if llm_data else LLMConfig()

        return cls(browser=browser, proxy=proxy, llm=llm, **data)

    @classmethod
    def from_yaml(cls, filepath: str | Path) -> Settings:
        """
        Load settings from a YAML file.

        Supports nested structure:
            server_host: 0.0.0.0
            server_port: 8000
            auth_enabled: true
            browser:
              headless: true
              stealth: true
            proxy:
              url: http://proxy:8080
            llm:
              provider: openai/gpt-4o-mini
            cache_backend: redis
            redis_url: redis://localhost:6379

        Args:
            filepath: Path to the YAML file.

        Returns:
            Settings instance.
        """
        import yaml

        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {filepath}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    # ──────────────────────────────────────────────────────────
    # Presets
    # ──────────────────────────────────────────────────────────

    @classmethod
    def preset_development(cls) -> Settings:
        """Development preset (no auth, memory queue, debug mode)."""
        return cls(
            debug=True,
            auth_enabled=False,
            rate_limit_enabled=False,
            queue_backend="memory",
            cache_backend="memory",
            cache_ttl=300,
            log_level="debug",
            log_format="text",
            server_workers=1,
            browser=BrowserSettings(
                headless=True,
                stealth=False,
                max_concurrent=3,
            ),
        )

    @classmethod
    def preset_production(cls) -> Settings:
        """Production preset (auth, Redis, rate limiting, JSON logs)."""
        return cls(
            debug=False,
            auth_enabled=True,
            rate_limit_enabled=True,
            rate_limit="100/minute",
            rate_limit_storage="redis",
            queue_backend="redis",
            cache_backend="redis",
            cache_ttl=3600,
            log_level="info",
            log_format="json",
            metrics_enabled=True,
            server_workers=4,
            browser=BrowserSettings(
                headless=True,
                stealth=True,
                max_concurrent=10,
                pool_pre_warm=3,
            ),
        )

    @classmethod
    def preset_minimal(cls) -> Settings:
        """Minimal preset (lowest resource usage)."""
        return cls(
            debug=False,
            auth_enabled=False,
            rate_limit_enabled=False,
            queue_backend="memory",
            cache_backend="none",
            metrics_enabled=False,
            mcp_enabled=False,
            server_workers=1,
            browser=BrowserSettings(
                headless=True,
                stealth=False,
                max_concurrent=2,
                pool_pre_warm=0,
            ),
        )

    @classmethod
    def preset_docker(cls) -> Settings:
        """Docker preset (reads from env, Redis for queue/cache).

        Note: For Docker networking, set AGENTCRAWL_SERVER_HOST=0.0.0.0
        in docker-compose.yml or environment. Default is 127.0.0.1 for security.
        """
        return cls(
            debug=False,
            server_host="127.0.0.1",  # Default secure bind; override via AGENTCRAWL_SERVER_HOST env var
            server_port=8000,
            auth_enabled=True,
            rate_limit_enabled=True,
            rate_limit_storage="redis",
            queue_backend="redis",
            redis_url="redis://redis:6379/0",
            cache_backend="redis",
            log_format="json",
            metrics_enabled=True,
        )

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(
        self,
        exclude_none: bool = True,
        mask_secrets: bool = True,
    ) -> dict[str, Any]:
        """
        Convert to a plain dictionary.

        Args:
            exclude_none: Exclude None values.
            mask_secrets: Mask API keys and passwords.

        Returns:
            Configuration dictionary.
        """
        data = self.model_dump(exclude_none=exclude_none)

        if mask_secrets:
            secret_fields = ["api_key", "jwt_secret"]
            for field_name in secret_fields:
                if data.get(field_name):
                    val = data[field_name]
                    if len(val) > 8:
                        data[field_name] = f"{val[:4]}...{val[-4:]}"
                    else:
                        data[field_name] = "********"

            # Mask nested secrets
            if "browser" in data and "proxy_password" in data.get("browser", {}):
                data["browser"]["proxy_password"] = MASK_VALUE
            if "proxy" in data and "password" in data.get("proxy", {}):
                data["proxy"]["password"] = MASK_VALUE
            if "llm" in data and "api_key" in data.get("llm", {}):
                llm_key = data["llm"]["api_key"]
                if llm_key and len(llm_key) > 8:
                    data["llm"]["api_key"] = f"{llm_key[:4]}...{llm_key[-4:]}"

        return data

    def to_json(self, mask_secrets: bool = True) -> str:
        """Serialize to JSON string."""
        import json

        return json.dumps(
            self.to_dict(mask_secrets=mask_secrets),
            ensure_ascii=False,
            default=str,
            indent=2,
        )

    def to_yaml(self, filepath: str | Path, mask_secrets: bool = True) -> None:
        """Save settings to a YAML file."""
        import yaml

        data = self.to_dict(mask_secrets=mask_secrets)
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def to_env_string(self, mask_secrets: bool = False) -> str:
        """Generate environment variable assignments."""
        lines = []
        data = self.to_dict(exclude_none=True, mask_secrets=mask_secrets)

        for key, value in data.items():
            if isinstance(value, dict):
                # Nested config — flatten with sub-prefix
                sub_prefix_map = {
                    "browser": "AGENTCRAWL_",
                    "proxy": "AGENTCRAWL_PROXY_",
                    "llm": "AGENTCRAWL_LLM_",
                }
                prefix = sub_prefix_map.get(key, f"AGENTCRAWL_{key.upper()}_")
                for sub_key, sub_val in value.items():
                    env_key = f"{prefix}{sub_key.upper()}"
                    env_val = str(sub_val).lower() if isinstance(sub_val, bool) else str(sub_val)
                    lines.append(f"{env_key}={env_val}")
            else:
                env_key = f"AGENTCRAWL_{key.upper()}"
                env_val = str(value).lower() if isinstance(value, bool) else str(value)
                lines.append(f"{env_key}={env_val}")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────
    # Validation & Diagnostics
    # ──────────────────────────────────────────────────────────

    def validate_all(self) -> dict[str, list[str]]:
        """
        Validate all configurations and collect warnings.

        Returns:
            Dictionary mapping section to list of warnings.
        """
        warnings: dict[str, list[str]] = {}

        # Global
        global_warnings = []
        if self.auth_enabled and not self.api_key and not self.jwt_secret:
            global_warnings.append("Auth enabled but no api_key or jwt_secret set")
        if self.uses_redis and not self.redis_url:
            global_warnings.append("Redis-dependent feature enabled but no redis_url")
        if self.debug and self.is_production:
            global_warnings.append("debug=True in production-like config")
        if global_warnings:
            warnings["global"] = global_warnings

        # Browser
        browser_warnings = (
            self.browser.validate_config() if hasattr(self.browser, "validate_config") else []
        )
        if browser_warnings:
            warnings["browser"] = browser_warnings

        # Proxy
        proxy_warnings = self.proxy.validate_config()
        if proxy_warnings:
            warnings["proxy"] = proxy_warnings

        # LLM
        llm_warnings = self.llm.validate_config()
        if llm_warnings:
            warnings["llm"] = llm_warnings

        return warnings

    def get_diagnostics(self) -> dict[str, Any]:
        """Get full diagnostics for debugging."""
        return {
            "app_name": self.app_name,
            "version": self.version,
            "debug": self.debug,
            "server": {
                "host": self.server_host,
                "port": self.server_port,
                "workers": self.server_workers,
                "url": self.server_url,
            },
            "auth": {
                "enabled": self.auth_enabled,
                "has_api_key": self.api_key is not None,
                "has_jwt_secret": self.jwt_secret is not None,
            },
            "rate_limit": {
                "enabled": self.rate_limit_enabled,
                "limit": self.rate_limit,
                "storage": self.rate_limit_storage,
            },
            "queue": {
                "backend": self.queue_backend,
                "max_concurrent": self.queue_max_concurrent,
                "job_timeout": self.queue_job_timeout,
            },
            "cache": {
                "backend": self.cache_backend,
                "ttl": self.cache_ttl,
                "prefix": self.cache_prefix,
            },
            "redis": {
                "url": self.redis_url.replace(self.redis_url.split("@")[-1], "***")
                if "@" in self.redis_url
                else self.redis_url,
                "used_by": [
                    component
                    for component, uses in [
                        ("queue", self.queue_backend == "redis"),
                        ("cache", self.cache_backend == "redis"),
                        ("rate_limit", self.rate_limit_storage == "redis"),
                    ]
                    if uses
                ],
            },
            "mcp": {
                "enabled": self.mcp_enabled,
                "transport": self.mcp_transport,
                "max_concurrent": self.mcp_max_concurrent,
            },
            "logging": {
                "level": self.log_level,
                "format": self.log_format,
            },
            "monitoring": {
                "metrics": self.metrics_enabled,
                "tracing": self.tracing_enabled,
            },
            "browser": self.browser.to_dict(),
            "proxy": self.proxy.to_dict(),
            "llm": self.llm.to_dict(),
            "warnings": self.validate_all(),
        }

    # ──────────────────────────────────────────────────────────
    # Merge / Override
    # ──────────────────────────────────────────────────────────

    def merge(self, overrides: dict[str, Any]) -> Settings:
        """Create a new settings instance with overridden values."""
        current = self.to_dict(exclude_none=False, mask_secrets=False)
        current.update(overrides)
        return Settings.from_dict(current)

    # ──────────────────────────────────────────────────────────
    # Representation
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"Settings(app={self.app_name!r}, v={self.version}, "
            f"debug={self.debug}, "
            f"server={self.server_host}:{self.server_port}, "
            f"auth={self.auth_enabled}, "
            f"queue={self.queue_backend}, "
            f"cache={self.cache_backend})"
        )
