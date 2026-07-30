"""
AgentCrawl — Browser Configuration (Pydantic)
================================================

Pydantic-based browser configuration with environment variable
binding, validation, and conversion to the runtime BrowserConfig
dataclass used by the browser automation layer.

This module serves as the configuration entry point for both
Package Mode (programmatic) and Server Mode (env vars / YAML).

Usage:
    from agentcrawl.config.browser_config import BrowserSettings

    # From environment variables
    settings = BrowserSettings()

    # From keyword arguments
    settings = BrowserSettings(
        headless=True,
        stealth=True,
        browser_type="chromium",
        viewport_width=1920,
        viewport_height=1080,
    )

    # Convert to runtime config
    from agentcrawl.browser.config import BrowserConfig
    runtime_config = settings.to_browser_config()

    # From YAML file
    settings = BrowserSettings.from_yaml("config.yml")

    # From dictionary
    settings = BrowserSettings.from_dict({"headless": True, "stealth": True})
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Mask value for sensitive data
MASK_VALUE = "********"

# ══════════════════════════════════════════════════════════════
# Browser Settings (Pydantic)
# ══════════════════════════════════════════════════════════════

class BrowserSettings(BaseSettings):
    """
    Pydantic-based browser configuration with env var support.

    All fields can be set via environment variables with the
    ``AGENTCRAWL_`` prefix. For example, ``AGENTCRAWL_HEADLESS=false``
    sets ``headless=False``.

    Attributes:
        browser_type: Browser engine ('chromium', 'firefox', 'webkit').
        headless: Run in headless mode.
        stealth: Enable anti-bot stealth mode.
        channel: Browser channel for Chromium ('chrome', 'msedge').
        executable_path: Path to custom browser executable.
        user_agent: Custom User-Agent string.
        viewport_width: Viewport width in pixels.
        viewport_height: Viewport height in pixels.
        device_scale_factor: Device pixel ratio.
        is_mobile: Emulate mobile device.
        has_touch: Enable touch events.
        locale: Browser locale.
        timezone: Browser timezone identifier.
        java_script_enabled: Enable JavaScript.
        ignore_https_errors: Ignore HTTPS certificate errors.
        bypass_csp: Bypass Content-Security-Policy.
        timeout: Default timeout in seconds.
        navigation_timeout: Navigation timeout in seconds.
        proxy_url: Proxy server URL.
        proxy_username: Proxy auth username.
        proxy_password: Proxy auth password.
        proxy_bypass: Proxy bypass rules.
        proxy_rotation: Proxy rotation strategy.
        proxy_list: Comma-separated proxy URLs for rotation.
        max_concurrent: Max concurrent browser pages.
        pool_pre_warm: Pages to pre-create on startup.
        pool_page_ttl: Page TTL in seconds.
        pool_idle_timeout: Idle page timeout in seconds.
        pool_recycle_after: Recycle page after N navigations.
        session_persist: Persist session state.
        session_dir: Session storage directory.
        color_scheme: Preferred color scheme.
        accept_downloads: Accept file downloads.
        download_dir: Download directory.
        extra_args: Additional browser launch arguments (comma-separated).
        slow_mo: Slow down operations (ms, for debugging).
        devtools: Open DevTools (Chromium, headless=False).
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTCRAWL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Engine ────────────────────────────────────────────────
    browser_type: str = Field(
        default="chromium",
        description="Browser engine: chromium, firefox, webkit",
    )
    headless: bool = Field(
        default=True,
        description="Run browser in headless mode",
    )
    stealth: bool = Field(
        default=True,
        description="Enable anti-bot stealth mode",
    )
    channel: str | None = Field(
        default=None,
        description="Browser channel (chrome, msedge, chrome-beta)",
    )
    executable_path: str | None = Field(
        default=None,
        description="Path to custom browser executable",
    )

    # ── Identity ──────────────────────────────────────────────
    user_agent: str | None = Field(
        default=None,
        description="Custom User-Agent string",
    )
    locale: str = Field(
        default="en-US",
        description="Browser locale",
    )
    timezone: str | None = Field(
        default=None,
        description="Browser timezone (e.g., America/New_York)",
    )

    # ── Viewport ──────────────────────────────────────────────
    viewport_width: int = Field(
        default=1280,
        ge=320,
        le=7680,
        description="Viewport width in pixels",
    )
    viewport_height: int = Field(
        default=720,
        ge=240,
        le=4320,
        description="Viewport height in pixels",
    )
    device_scale_factor: float = Field(
        default=1.0,
        ge=0.5,
        le=4.0,
        description="Device pixel ratio",
    )
    is_mobile: bool = Field(
        default=False,
        description="Emulate mobile device",
    )
    has_touch: bool = Field(
        default=False,
        description="Enable touch events",
    )

    # ── Network ───────────────────────────────────────────────
    java_script_enabled: bool = Field(
        default=True,
        description="Enable JavaScript execution",
    )
    ignore_https_errors: bool = Field(
        default=False,
        description="Ignore HTTPS certificate errors",
    )
    bypass_csp: bool = Field(
        default=False,
        description="Bypass Content-Security-Policy",
    )

    # ── Timeouts ──────────────────────────────────────────────
    timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Default timeout in seconds",
    )
    navigation_timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Navigation timeout in seconds",
    )

    # ── Proxy ─────────────────────────────────────────────────
    proxy_url: str | None = Field(
        default=None,
        description="Proxy server URL (http://host:port)",
    )
    proxy_username: str | None = Field(
        default=None,
        description="Proxy authentication username",
    )
    proxy_password: SecretStr | None = Field(
        default=None,
        description="Proxy authentication password",
    )
    proxy_bypass: str | None = Field(
        default=None,
        description="Proxy bypass rules (comma-separated hosts)",
    )
    proxy_rotation: str = Field(
        default="none",
        description="Proxy rotation: none, round_robin, random, least_used",
    )
    proxy_list: str | None = Field(
        default=None,
        description="Comma-separated proxy URLs for rotation",
    )

    # ── Pool ──────────────────────────────────────────────────
    max_concurrent: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Maximum concurrent browser pages",
    )
    pool_pre_warm: int = Field(
        default=1,
        ge=0,
        le=20,
        description="Pages to pre-create on startup",
    )
    pool_page_ttl: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Page TTL in seconds",
    )
    pool_idle_timeout: int = Field(
        default=120,
        ge=10,
        le=1800,
        description="Idle page timeout in seconds",
    )
    pool_recycle_after: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Recycle page after N navigations",
    )

    # ── Session ───────────────────────────────────────────────
    session_persist: bool = Field(
        default=False,
        description="Persist session state (cookies, localStorage)",
    )
    session_dir: str = Field(
        default=".agentcrawl/sessions",
        description="Session storage directory",
    )

    # ── Display ───────────────────────────────────────────────
    color_scheme: str = Field(
        default="light",
        description="Color scheme: light, dark, no-preference",
    )
    accept_downloads: bool = Field(
        default=False,
        description="Accept file downloads",
    )
    download_dir: str | None = Field(
        default=None,
        description="Download directory path",
    )

    # ── Launch ────────────────────────────────────────────────
    extra_args: str | None = Field(
        default=None,
        description="Additional browser args (comma-separated)",
    )
    slow_mo: int = Field(
        default=0,
        ge=0,
        le=10000,
        description="Slow down operations by N ms (debugging)",
    )
    devtools: bool = Field(
        default=False,
        description="Open DevTools (Chromium, headless=False)",
    )

    # ──────────────────────────────────────────────────────────
    # Validators
    # ──────────────────────────────────────────────────────────

    @field_validator("browser_type")
    @classmethod
    def validate_browser_type(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"chromium", "firefox", "webkit"}
        if v not in allowed:
            raise ValueError(
                f"Invalid browser_type '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("proxy_rotation")
    @classmethod
    def validate_proxy_rotation(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"none", "round_robin", "random", "least_used"}
        if v not in allowed:
            raise ValueError(
                f"Invalid proxy_rotation '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("color_scheme")
    @classmethod
    def validate_color_scheme(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"light", "dark", "no-preference"}
        if v not in allowed:
            raise ValueError(
                f"Invalid color_scheme '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @model_validator(mode="after")
    def validate_devtools_requires_visible(self) -> BrowserSettings:
        """DevTools requires headless=False."""
        if self.devtools and self.headless:
            # Auto-correct: disable devtools in headless mode
            object.__setattr__(self, "devtools", False)
        return self

    # ──────────────────────────────────────────────────────────
    # Conversion to Runtime Config
    # ──────────────────────────────────────────────────────────

    def to_browser_config(self) -> Any:
        """
        Convert to the runtime BrowserConfig dataclass used by
        the browser automation layer.

        Returns:
            agentcrawl.browser.config.BrowserConfig instance.
        """
        from agentcrawl.browser.config import (
            BrowserConfig,
            BrowserPoolConfig,
            ProxyConfig,
            ProxyRotationStrategy,
            SessionConfig,
            ViewportConfig,
        )

        # Viewport
        viewport = ViewportConfig(
            width=self.viewport_width,
            height=self.viewport_height,
            device_scale_factor=self.device_scale_factor,
            is_mobile=self.is_mobile,
            has_touch=self.has_touch,
        )

        # Proxy
        proxy = None
        if self.proxy_url:
            proxy_list = []
            if self.proxy_list:
                proxy_list = [
                    p.strip() for p in self.proxy_list.split(",") if p.strip()
                ]

            proxy = ProxyConfig(
                server=self.proxy_url,
                username=self.proxy_username,
                password=self.proxy_password,
                bypass=self.proxy_bypass,
                rotation=ProxyRotationStrategy(self.proxy_rotation),
                proxy_list=proxy_list,
            )

        # Pool
        pool = BrowserPoolConfig(
            max_pages=self.max_concurrent,
            pre_warm=self.pool_pre_warm,
            page_ttl=self.pool_page_ttl,
            idle_timeout=self.pool_idle_timeout,
            recycle_after=self.pool_recycle_after,
        )

        # Session
        session = SessionConfig(
            persist=self.session_persist,
            storage_dir=self.session_dir,
        )

        # Extra args
        extra_args = []
        if self.extra_args:
            extra_args = [
                a.strip() for a in self.extra_args.split(",") if a.strip()
            ]

        return BrowserConfig(
            browser_type=self.browser_type,
            headless=self.headless,
            stealth=self.stealth,
            channel=self.channel,
            executable_path=self.executable_path,
            user_agent=self.user_agent,
            locale=self.locale,
            timezone=self.timezone,
            viewport=viewport,
            proxy=proxy,
            java_script_enabled=self.java_script_enabled,
            ignore_https_errors=self.ignore_https_errors,
            bypass_csp=self.bypass_csp,
            timeout=self.timeout * 1000,  # Convert to ms
            navigation_timeout=self.navigation_timeout * 1000,
            extra_args=extra_args,
            color_scheme=self.color_scheme,
            accept_downloads=self.accept_downloads,
            download_dir=self.download_dir,
            slow_mo=self.slow_mo,
            devtools=self.devtools,
            pool=pool,
            session=session,
        )

    # ──────────────────────────────────────────────────────────
    # Factory Methods
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrowserSettings:
        """
        Create settings from a dictionary.

        Args:
            data: Configuration dictionary.

        Returns:
            BrowserSettings instance.
        """
        return cls(**data)

    @classmethod
    def from_yaml(cls, filepath: str | Path) -> BrowserSettings:
        """
        Load settings from a YAML file.

        Args:
            filepath: Path to the YAML configuration file.

        Returns:
            BrowserSettings instance.

        Example YAML:
            browser_type: chromium
            headless: true
            stealth: true
            viewport_width: 1920
            viewport_height: 1080
            timeout: 30
            max_concurrent: 10
        """
        import yaml

        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {filepath}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Support nested 'browser:' key
        if "browser" in data and isinstance(data["browser"], dict):
            data = data["browser"]

        return cls(**data)

    @classmethod
    def from_env(cls, prefix: str = "AGENTCRAWL") -> BrowserSettings:
        """
        Create settings from environment variables.

        This is equivalent to the default constructor but allows
        a custom prefix.

        Args:
            prefix: Environment variable prefix.

        Returns:
            BrowserSettings instance.
        """
        return cls(_env_prefix=f"{prefix}_")  # type: ignore[call-arg]

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self, exclude_none: bool = True) -> dict[str, Any]:
        """
        Convert to a plain dictionary.

        Args:
            exclude_none: Whether to exclude None values.

        Returns:
            Configuration dictionary.
        """
        return self.model_dump(exclude_none=exclude_none)

    def to_yaml(self, filepath: str | Path) -> None:
        """
        Save settings to a YAML file.

        Args:
            filepath: Output file path.
        """
        import yaml

        data = self.to_dict(exclude_none=True)
        # Mask sensitive fields
        if "proxy_password" in data:
            data["proxy_password"] = MASK_VALUE

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def to_env_string(self) -> str:
        """
        Generate environment variable assignments as a string.

        Returns:
            Multi-line string of KEY=VALUE pairs.
        """
        lines = []
        for key, value in self.to_dict(exclude_none=True).items():
            env_key = f"AGENTCRAWL_{key.upper()}"
            env_value = str(value).lower() if isinstance(value, bool) else str(value)
            lines.append(f"{env_key}={env_value}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────
    # Presets
    # ──────────────────────────────────────────────────────────

    @classmethod
    def preset_default(cls) -> BrowserSettings:
        """Default settings (headless Chromium with stealth)."""
        return cls()

    @classmethod
    def preset_fast(cls) -> BrowserSettings:
        """Optimized for speed."""
        return cls(
            headless=True,
            stealth=False,
            max_concurrent=10,
            pool_pre_warm=3,
            extra_args="--disable-gpu,--disable-dev-shm-usage,--no-sandbox",
        )

    @classmethod
    def preset_stealth_max(cls) -> BrowserSettings:
        """Maximum stealth configuration."""
        return cls(
            headless=True,
            stealth=True,
            viewport_width=1920,
            viewport_height=1080,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone="America/New_York",
            extra_args="--disable-blink-features=AutomationControlled,--disable-infobars",
        )

    @classmethod
    def preset_mobile(cls) -> BrowserSettings:
        """Mobile device emulation."""
        return cls(
            headless=True,
            stealth=True,
            viewport_width=375,
            viewport_height=812,
            device_scale_factor=3.0,
            is_mobile=True,
            has_touch=True,
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
        )

    @classmethod
    def preset_debug(cls) -> BrowserSettings:
        """Debugging configuration (visible browser, slow-mo)."""
        return cls(
            headless=False,
            stealth=False,
            devtools=True,
            slow_mo=500,
            viewport_width=1440,
            viewport_height=900,
        )

    # ──────────────────────────────────────────────────────────
    # Merge / Override
    # ──────────────────────────────────────────────────────────

    def merge(self, overrides: dict[str, Any]) -> BrowserSettings:
        """
        Create a new settings instance with overridden values.

        Args:
            overrides: Dictionary of field names to new values.

        Returns:
            New BrowserSettings with merged values.
        """
        current = self.to_dict(exclude_none=False)
        current.update(overrides)
        return BrowserSettings(**current)

    # ──────────────────────────────────────────────────────────
    # Representation
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"BrowserSettings(browser={self.browser_type}, "
            f"headless={self.headless}, stealth={self.stealth}, "
            f"viewport={self.viewport_width}x{self.viewport_height}, "
            f"max_concurrent={self.max_concurrent})"
        )
