"""
AgentCrawl — Browser Configuration
=====================================

Defines all configuration options for the Playwright-based browser
automation layer. Supports Chromium, Firefox, and WebKit engines
with stealth mode, proxy rotation, session persistence, and
browser pool management.

Usage:
    from agentcrawl.browser.config import BrowserConfig, ProxyConfig, ViewportConfig

    # Simple
    config = BrowserConfig(headless=True, stealth=True)

    # Full configuration
    config = BrowserConfig(
        browser_type="chromium",
        headless=True,
        stealth=True,
        viewport=ViewportConfig(width=1920, height=1080),
        user_agent="Mozilla/5.0 ...",
        proxy=ProxyConfig(server="http://proxy:8080", username="user", password="pass"),
        locale="en-US",
        timezone="America/New_York",
        java_script_enabled=True,
        ignore_https_errors=False,
        timeout=30_000,
        pool=BrowserPoolConfig(max_pages=5, pre_warm=2),
        extra_args=["--disable-gpu", "--no-sandbox"],
    )

    # From environment variables
    config = BrowserConfig.from_env()

    # From dictionary
    config = BrowserConfig.from_dict({"headless": True, "stealth": True})
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ══════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════

class BrowserType(str, Enum):
    """Supported browser engines."""
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class ProxyRotationStrategy(str, Enum):
    """Proxy rotation strategies."""
    NONE = "none"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"


class ScreenshotFormat(str, Enum):
    """Screenshot output formats."""
    PNG = "png"
    JPEG = "jpeg"


# ══════════════════════════════════════════════════════════════
# Sub-Configuration Models
# ══════════════════════════════════════════════════════════════

@dataclass
class ViewportConfig:
    """
    Browser viewport dimensions.

    Attributes:
        width: Viewport width in pixels.
        height: Viewport height in pixels.
        device_scale_factor: Device scale factor (1 = standard, 2 = retina).
        is_mobile: Whether to emulate a mobile device.
        has_touch: Whether to enable touch events.
        is_landscape: Whether the viewport is in landscape orientation.
    """
    width: int = 1280
    height: int = 720
    device_scale_factor: float = 1.0
    is_mobile: bool = False
    has_touch: bool = False
    is_landscape: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "deviceScaleFactor": self.device_scale_factor,
            "isMobile": self.is_mobile,
            "hasTouch": self.has_touch,
            "isLandscape": self.is_landscape,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ViewportConfig:
        return cls(
            width=data.get("width", 1280),
            height=data.get("height", 720),
            device_scale_factor=data.get("device_scale_factor", data.get("deviceScaleFactor", 1.0)),
            is_mobile=data.get("is_mobile", data.get("isMobile", False)),
            has_touch=data.get("has_touch", data.get("hasTouch", False)),
            is_landscape=data.get("is_landscape", data.get("isLandscape", True)),
        )

    # Common presets
    @classmethod
    def desktop_hd(cls) -> ViewportConfig:
        """1920x1080 desktop viewport."""
        return cls(width=1920, height=1080)

    @classmethod
    def desktop_standard(cls) -> ViewportConfig:
        """1280x720 desktop viewport."""
        return cls(width=1280, height=720)

    @classmethod
    def laptop(cls) -> ViewportConfig:
        """1440x900 laptop viewport."""
        return cls(width=1440, height=900)

    @classmethod
    def tablet(cls) -> ViewportConfig:
        """768x1024 tablet viewport (portrait)."""
        return cls(width=768, height=1024, is_mobile=True, has_touch=True, is_landscape=False)

    @classmethod
    def tablet_landscape(cls) -> ViewportConfig:
        """1024x768 tablet viewport (landscape)."""
        return cls(width=1024, height=768, is_mobile=True, has_touch=True)

    @classmethod
    def mobile(cls) -> ViewportConfig:
        """375x812 mobile viewport (iPhone-like)."""
        return cls(
            width=375, height=812,
            device_scale_factor=3.0,
            is_mobile=True, has_touch=True, is_landscape=False,
        )

    @classmethod
    def mobile_landscape(cls) -> ViewportConfig:
        """812x375 mobile viewport (landscape)."""
        return cls(
            width=812, height=375,
            device_scale_factor=3.0,
            is_mobile=True, has_touch=True,
        )


@dataclass
class ProxyConfig:
    """
    Proxy server configuration.

    Attributes:
        server: Proxy server URL (e.g., 'http://proxy:8080', 'socks5://proxy:1080').
        username: Proxy authentication username.
        password: Proxy authentication password.
        bypass: Comma-separated list of hosts to bypass proxy.
        rotation: Proxy rotation strategy.
        proxy_list: List of proxy servers for rotation.
    """
    server: str | None = None
    username: str | None = None
    password: str | None = None
    bypass: str | None = None
    rotation: ProxyRotationStrategy = ProxyRotationStrategy.NONE
    proxy_list: list[str] = field(default_factory=list)

    def to_playwright_dict(self) -> dict[str, Any] | None:
        """Convert to Playwright proxy format."""
        if not self.server and not self.proxy_list:
            return None

        server = self.server or (self.proxy_list[0] if self.proxy_list else None)
        if not server:
            return None

        result: dict[str, Any] = {"server": server}
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        if self.bypass:
            result["bypass"] = self.bypass
        return result

    @classmethod
    def from_url(cls, url: str) -> ProxyConfig:
        """
        Create ProxyConfig from a URL string.

        Supports formats:
            http://host:port
            http://user:pass@host:port
            socks5://host:port
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return cls(
            server=f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 8080}",
            username=parsed.username,
            password=parsed.password,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxyConfig:
        rotation = data.get("rotation", "none")
        if isinstance(rotation, str):
            rotation = ProxyRotationStrategy(rotation)
        return cls(
            server=data.get("server"),
            username=data.get("username"),
            password=data.get("password"),
            bypass=data.get("bypass"),
            rotation=rotation,
            proxy_list=data.get("proxy_list", []),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.server:
            result["server"] = self.server
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = "********"
        if self.bypass:
            result["bypass"] = self.bypass
        result["rotation"] = self.rotation.value
        if self.proxy_list:
            result["proxy_list"] = self.proxy_list
        return result


@dataclass
class BrowserPoolConfig:
    """
    Browser pool management configuration.

    Attributes:
        max_pages: Maximum number of concurrent browser pages.
        pre_warm: Number of pages to pre-create on startup.
        max_contexts: Maximum number of browser contexts.
        page_ttl: Page time-to-live in seconds (recycle after this).
        idle_timeout: Close idle pages after this many seconds.
        recycle_after: Recycle page after this many navigations.
        health_check_interval: Seconds between pool health checks.
    """
    max_pages: int = 5
    pre_warm: int = 1
    max_contexts: int = 3
    page_ttl: int = 300
    idle_timeout: int = 120
    recycle_after: int = 50
    health_check_interval: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrowserPoolConfig:
        return cls(
            max_pages=data.get("max_pages", 5),
            pre_warm=data.get("pre_warm", 1),
            max_contexts=data.get("max_contexts", 3),
            page_ttl=data.get("page_ttl", 300),
            idle_timeout=data.get("idle_timeout", 120),
            recycle_after=data.get("recycle_after", 50),
            health_check_interval=data.get("health_check_interval", 60),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_pages": self.max_pages,
            "pre_warm": self.pre_warm,
            "max_contexts": self.max_contexts,
            "page_ttl": self.page_ttl,
            "idle_timeout": self.idle_timeout,
            "recycle_after": self.recycle_after,
            "health_check_interval": self.health_check_interval,
        }


@dataclass
class SessionConfig:
    """
    Browser session persistence configuration.

    Attributes:
        persist: Whether to persist session state (cookies, localStorage).
        storage_dir: Directory for storing session state files.
        session_id: Unique session identifier (auto-generated if None).
        cookies: Initial cookies to set.
        local_storage: Initial localStorage key-value pairs.
        restore_on_start: Restore previous session state on startup.
    """
    persist: bool = False
    storage_dir: str = ".agentcrawl/sessions"
    session_id: str | None = None
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    restore_on_start: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionConfig:
        return cls(
            persist=data.get("persist", False),
            storage_dir=data.get("storage_dir", ".agentcrawl/sessions"),
            session_id=data.get("session_id"),
            cookies=data.get("cookies", []),
            local_storage=data.get("local_storage", {}),
            restore_on_start=data.get("restore_on_start", True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "persist": self.persist,
            "storage_dir": self.storage_dir,
            "session_id": self.session_id,
            "cookies_count": len(self.cookies),
            "local_storage_keys": len(self.local_storage),
            "restore_on_start": self.restore_on_start,
        }


@dataclass
class RecordingConfig:
    """
    Browser recording configuration (video, trace, HAR).

    Attributes:
        video_enabled: Record browser video.
        video_dir: Directory for video files.
        video_size: Video dimensions (width, height).
        trace_enabled: Record Playwright trace.
        trace_dir: Directory for trace files.
        har_enabled: Record HTTP Archive.
        har_path: Path for HAR file.
        screenshot_on_error: Capture screenshot on page errors.
    """
    video_enabled: bool = False
    video_dir: str = ".agentcrawl/videos"
    video_size: tuple[int, int] = (1280, 720)
    trace_enabled: bool = False
    trace_dir: str = ".agentcrawl/traces"
    har_enabled: bool = False
    har_path: str = ".agentcrawl/har/recording.har"
    screenshot_on_error: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingConfig:
        video_size = data.get("video_size", (1280, 720))
        if isinstance(video_size, list):
            video_size = tuple(video_size)
        return cls(
            video_enabled=data.get("video_enabled", False),
            video_dir=data.get("video_dir", ".agentcrawl/videos"),
            video_size=video_size,
            trace_enabled=data.get("trace_enabled", False),
            trace_dir=data.get("trace_dir", ".agentcrawl/traces"),
            har_enabled=data.get("har_enabled", False),
            har_path=data.get("har_path", ".agentcrawl/har/recording.har"),
            screenshot_on_error=data.get("screenshot_on_error", False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_enabled": self.video_enabled,
            "video_dir": self.video_dir,
            "video_size": list(self.video_size),
            "trace_enabled": self.trace_enabled,
            "trace_dir": self.trace_dir,
            "har_enabled": self.har_enabled,
            "har_path": self.har_path,
            "screenshot_on_error": self.screenshot_on_error,
        }


@dataclass
class GeolocationConfig:
    """
    Browser geolocation configuration.

    Attributes:
        latitude: Latitude coordinate.
        longitude: Longitude coordinate.
        accuracy: Accuracy in meters.
    """
    latitude: float = 0.0
    longitude: float = 0.0
    accuracy: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy": self.accuracy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GeolocationConfig:
        return cls(
            latitude=data.get("latitude", 0.0),
            longitude=data.get("longitude", 0.0),
            accuracy=data.get("accuracy", 100.0),
        )


# ══════════════════════════════════════════════════════════════
# Main Browser Configuration
# ══════════════════════════════════════════════════════════════

@dataclass
class BrowserConfig:
    """
    Complete browser automation configuration.

    This is the primary configuration object for the browser layer.
    It controls browser engine selection, stealth mode, viewport,
    proxy, session persistence, pooling, and recording.

    Attributes:
        browser_type: Browser engine to use ('chromium', 'firefox', 'webkit').
        headless: Run browser in headless mode (no visible window).
        stealth: Enable stealth mode (anti-bot evasion, fingerprint spoofing).
        channel: Browser channel for Chromium ('chrome', 'msedge', 'chrome-beta').
        executable_path: Path to a custom browser executable.
        user_agent: Custom User-Agent string (None = auto-generated).
        viewport: Viewport dimensions and device emulation.
        proxy: Proxy server configuration.
        locale: Browser locale (e.g., 'en-US', 'th-TH').
        timezone: Browser timezone (e.g., 'America/New_York', 'Asia/Bangkok').
        geolocation: Geolocation override.
        java_script_enabled: Enable JavaScript execution.
        ignore_https_errors: Ignore HTTPS certificate errors.
        bypass_csp: Bypass Content-Security-Policy.
        timeout: Default navigation timeout in milliseconds.
        navigation_timeout: Navigation-specific timeout in milliseconds.
        extra_headers: Additional HTTP headers sent with every request.
        extra_args: Additional browser launch arguments (Chromium flags).
        extensions: List of browser extension paths to load.
        download_dir: Directory for downloaded files.
        pool: Browser pool management settings.
        session: Session persistence settings.
        recording: Video/trace/HAR recording settings.
        accept_downloads: Whether to accept file downloads.
        color_scheme: Preferred color scheme ('light', 'dark', 'no-preference').
        reduced_motion: Emulate reduced motion preference.
        forced_colors: Force colors mode ('active', 'none').
        permissions: Browser permissions to grant (e.g., ['geolocation']).
        http_credentials: HTTP Basic Auth credentials.
        offline: Simulate offline mode.
        devtools: Open DevTools (Chromium only, headless=False).
        slow_mo: Slow down operations by this many milliseconds (debugging).
    """

    # Engine
    browser_type: BrowserType | str = BrowserType.CHROMIUM
    headless: bool = True
    stealth: bool = True
    channel: str | None = None
    executable_path: str | None = None

    # Identity
    user_agent: str | None = None
    locale: str = "en-US"
    timezone: str | None = None
    geolocation: GeolocationConfig | None = None

    # Viewport & Display
    viewport: ViewportConfig = field(default_factory=ViewportConfig)
    color_scheme: str = "light"
    reduced_motion: str = "no-preference"
    forced_colors: str = "none"

    # Network
    proxy: ProxyConfig | None = None
    java_script_enabled: bool = True
    ignore_https_errors: bool = False
    bypass_csp: bool = False
    offline: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)
    http_credentials: dict[str, str] | None = None
    permissions: list[str] = field(default_factory=list)

    # Timeouts
    timeout: int = 30_000
    navigation_timeout: int = 30_000

    # Browser Launch
    extra_args: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    download_dir: str | None = None
    accept_downloads: bool = False
    devtools: bool = False
    slow_mo: int = 0

    # Pool & Session
    pool: BrowserPoolConfig = field(default_factory=BrowserPoolConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)

    def __post_init__(self) -> None:
        # Normalize browser_type
        if isinstance(self.browser_type, str):
            try:
                self.browser_type = BrowserType(self.browser_type.lower())
            except ValueError:
                raise ValueError(
                    f"Unsupported browser type: '{self.browser_type}'. "
                    f"Available: {', '.join(b.value for b in BrowserType)}"
                )

        # Normalize viewport
        if isinstance(self.viewport, dict):
            self.viewport = ViewportConfig.from_dict(self.viewport)

        # Normalize proxy
        if isinstance(self.proxy, dict):
            self.proxy = ProxyConfig.from_dict(self.proxy)

        # Normalize pool
        if isinstance(self.pool, dict):
            self.pool = BrowserPoolConfig.from_dict(self.pool)

        # Normalize session
        if isinstance(self.session, dict):
            self.session = SessionConfig.from_dict(self.session)

        # Normalize recording
        if isinstance(self.recording, dict):
            self.recording = RecordingConfig.from_dict(self.recording)

        # Normalize geolocation
        if isinstance(self.geolocation, dict):
            self.geolocation = GeolocationConfig.from_dict(self.geolocation)

    # ──────────────────────────────────────────────────────────
    # Playwright Integration
    # ──────────────────────────────────────────────────────────

    def to_launch_options(self) -> dict[str, Any]:
        """
        Convert to Playwright browser.launch() options.

        Returns:
            Dictionary of launch options for Playwright.
        """
        opts: dict[str, Any] = {
            "headless": self.headless,
        }

        if self.channel:
            opts["channel"] = self.channel

        if self.executable_path:
            opts["executablePath"] = self.executable_path

        if self.devtools and self.browser_type == BrowserType.CHROMIUM:
            opts["devtools"] = True

        if self.slow_mo > 0:
            opts["slowMo"] = self.slow_mo

        # Build args
        args = list(self.extra_args)
        if self.stealth and self.browser_type == BrowserType.CHROMIUM:
            args.extend(_STEALTH_ARGS)
        if args:
            opts["args"] = args

        # Proxy
        if self.proxy:
            proxy_dict = self.proxy.to_playwright_dict()
            if proxy_dict:
                opts["proxy"] = proxy_dict

        # Extensions (Chromium only, requires headless=False or new headless)
        if self.extensions and self.browser_type == BrowserType.CHROMIUM:
            ext_args = [f"--disable-extensions-except={','.join(self.extensions)}"]
            ext_args.append(f"--load-extension={','.join(self.extensions)}")
            existing = opts.get("args", [])
            opts["args"] = existing + ext_args

        return opts

    def to_context_options(self) -> dict[str, Any]:
        """
        Convert to Playwright browser.new_context() options.

        Returns:
            Dictionary of context options for Playwright.
        """
        opts: dict[str, Any] = {
            "viewport": {
                "width": self.viewport.width,
                "height": self.viewport.height,
            },
            "device_scale_factor": self.viewport.device_scale_factor,
            "is_mobile": self.viewport.is_mobile,
            "has_touch": self.viewport.has_touch,
            "java_script_enabled": self.java_script_enabled,
            "ignore_https_errors": self.ignore_https_errors,
            "bypass_csp": self.bypass_csp,
            "locale": self.locale,
            "color_scheme": self.color_scheme,
            "reduced_motion": self.reduced_motion,
            "forced_colors": self.forced_colors,
            "accept_downloads": self.accept_downloads,
        }

        if self.user_agent:
            opts["userAgent"] = self.user_agent

        if self.timezone:
            opts["timezoneId"] = self.timezone

        if self.geolocation:
            opts["geolocation"] = self.geolocation.to_dict()
            if "geolocation" not in self.permissions:
                self.permissions.append("geolocation")

        if self.permissions:
            opts["permissions"] = self.permissions

        if self.extra_headers:
            opts["extraHTTPHeaders"] = self.extra_headers

        if self.http_credentials:
            opts["httpCredentials"] = self.http_credentials

        if self.offline:
            opts["offline"] = True

        if self.download_dir:
            opts["acceptDownloads"] = True

        # Recording
        if self.recording.video_enabled:
            opts["recordVideo"] = {
                "dir": self.recording.video_dir,
                "size": {
                    "width": self.recording.video_size[0],
                    "height": self.recording.video_size[1],
                },
            }

        if self.recording.har_enabled:
            opts["recordHar"] = {
                "path": self.recording.har_path,
            }

        # Session persistence
        if self.session.persist and self.session.storage_dir:
            opts["storageState"] = self._get_storage_state_path()

        return opts

    def to_page_options(self) -> dict[str, Any]:
        """
        Convert to Playwright page-level options.

        Returns:
            Dictionary of page options.
        """
        return {
            "timeout": self.timeout,
            "navigation_timeout": self.navigation_timeout,
        }

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dictionary (safe for JSON serialization)."""
        result: dict[str, Any] = {
            "browser_type": self.browser_type.value if isinstance(self.browser_type, BrowserType) else self.browser_type,
            "headless": self.headless,
            "stealth": self.stealth,
            "channel": self.channel,
            "executable_path": self.executable_path,
            "user_agent": self.user_agent,
            "locale": self.locale,
            "timezone": self.timezone,
            "viewport": self.viewport.to_dict(),
            "java_script_enabled": self.java_script_enabled,
            "ignore_https_errors": self.ignore_https_errors,
            "bypass_csp": self.bypass_csp,
            "offline": self.offline,
            "timeout": self.timeout,
            "navigation_timeout": self.navigation_timeout,
            "extra_headers": self.extra_headers,
            "extra_args": self.extra_args,
            "extensions": self.extensions,
            "download_dir": self.download_dir,
            "accept_downloads": self.accept_downloads,
            "devtools": self.devtools,
            "slow_mo": self.slow_mo,
            "color_scheme": self.color_scheme,
            "reduced_motion": self.reduced_motion,
            "forced_colors": self.forced_colors,
            "permissions": self.permissions,
            "pool": self.pool.to_dict(),
            "session": self.session.to_dict(),
            "recording": self.recording.to_dict(),
        }

        if self.proxy:
            result["proxy"] = self.proxy.to_dict()

        if self.geolocation:
            result["geolocation"] = self.geolocation.to_dict()

        if self.http_credentials:
            result["http_credentials"] = {"username": self.http_credentials.get("username", "")}

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrowserConfig:
        """Create a BrowserConfig from a dictionary."""
        # Handle nested objects
        viewport = data.get("viewport")
        if isinstance(viewport, dict):
            viewport = ViewportConfig.from_dict(viewport)

        proxy = data.get("proxy")
        if isinstance(proxy, dict):
            proxy = ProxyConfig.from_dict(proxy)
        elif isinstance(proxy, str):
            proxy = ProxyConfig.from_url(proxy)

        pool = data.get("pool")
        if isinstance(pool, dict):
            pool = BrowserPoolConfig.from_dict(pool)

        session = data.get("session")
        if isinstance(session, dict):
            session = SessionConfig.from_dict(session)

        recording = data.get("recording")
        if isinstance(recording, dict):
            recording = RecordingConfig.from_dict(recording)

        geolocation = data.get("geolocation")
        if isinstance(geolocation, dict):
            geolocation = GeolocationConfig.from_dict(geolocation)

        # Filter to known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}

        return cls(
            viewport=viewport or ViewportConfig(),
            proxy=proxy,
            pool=pool or BrowserPoolConfig(),
            session=session or SessionConfig(),
            recording=recording or RecordingConfig(),
            geolocation=geolocation,
            **{k: v for k, v in filtered.items() if k not in (
                "viewport", "proxy", "pool", "session", "recording", "geolocation"
            )},
        )

    # ──────────────────────────────────────────────────────────
    # Environment Variables
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, prefix: str = "AGENTCRAWL") -> BrowserConfig:
        """
        Create a BrowserConfig from environment variables.

        Reads variables like:
            AGENTCRAWL_BROWSER=chromium
            AGENTCRAWL_HEADLESS=true
            AGENTCRAWL_STEALTH=true
            AGENTCRAWL_VIEWPORT_WIDTH=1280
            AGENTCRAWL_VIEWPORT_HEIGHT=720
            AGENTCRAWL_USER_AGENT=...
            AGENTCRAWL_PROXY_URL=http://proxy:8080
            AGENTCRAWL_TIMEOUT=30
            AGENTCRAWL_MAX_CONCURRENT=5
            AGENTCRAWL_LOCALE=en-US
            AGENTCRAWL_TIMEZONE=America/New_York
            AGENTCRAWL_IGNORE_HTTPS_ERRORS=false
            AGENTCRAWL_JAVASCRIPT_ENABLED=true

        Args:
            prefix: Environment variable prefix.

        Returns:
            BrowserConfig populated from environment.
        """
        def _get(key: str, default: str = "") -> str:
            return os.environ.get(f"{prefix}_{key}", default)

        def _get_bool(key: str, default: bool = False) -> bool:
            val = _get(key, str(default)).lower()
            return val in ("true", "1", "yes", "on")

        def _get_int(key: str, default: int = 0) -> int:
            try:
                return int(_get(key, str(default)))
            except ValueError:
                return default

        # Proxy
        proxy_url = _get("PROXY_URL")
        proxy = ProxyConfig.from_url(proxy_url) if proxy_url else None

        # Viewport
        viewport = ViewportConfig(
            width=_get_int("VIEWPORT_WIDTH", 1280),
            height=_get_int("VIEWPORT_HEIGHT", 720),
        )

        # Pool
        pool = BrowserPoolConfig(
            max_pages=_get_int("MAX_CONCURRENT", 5),
            pre_warm=_get_int("POOL_PRE_WARM", 1),
        )

        return cls(
            browser_type=_get("BROWSER", "chromium"),
            headless=_get_bool("HEADLESS", True),
            stealth=_get_bool("STEALTH", True),
            user_agent=_get("USER_AGENT") or None,
            viewport=viewport,
            proxy=proxy,
            locale=_get("LOCALE", "en-US"),
            timezone=_get("TIMEZONE") or None,
            java_script_enabled=_get_bool("JAVASCRIPT_ENABLED", True),
            ignore_https_errors=_get_bool("IGNORE_HTTPS_ERRORS", False),
            timeout=_get_int("TIMEOUT", 30) * 1000,
            navigation_timeout=_get_int("NAVIGATION_TIMEOUT", 30) * 1000,
            pool=pool,
        )

    # ──────────────────────────────────────────────────────────
    # Presets
    # ──────────────────────────────────────────────────────────

    @classmethod
    def default(cls) -> BrowserConfig:
        """Default configuration (headless Chromium with stealth)."""
        return cls()

    @classmethod
    def fast(cls) -> BrowserConfig:
        """Optimized for speed (minimal overhead)."""
        return cls(
            headless=True,
            stealth=False,
            java_script_enabled=True,
            viewport=ViewportConfig(width=1280, height=720),
            pool=BrowserPoolConfig(max_pages=10, pre_warm=3),
            extra_args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--no-first-run",
                "--no-zygote",
                "--single-process",
            ],
        )

    @classmethod
    def stealth_max(cls) -> BrowserConfig:
        """Maximum stealth configuration (anti-bot evasion)."""
        return cls(
            headless=True,
            stealth=True,
            viewport=ViewportConfig(width=1920, height=1080),
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone="America/New_York",
            extra_args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )

    @classmethod
    def mobile_emulation(cls) -> BrowserConfig:
        """Mobile device emulation."""
        return cls(
            headless=True,
            stealth=True,
            viewport=ViewportConfig.mobile(),
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            locale="en-US",
        )

    @classmethod
    def debugging(cls) -> BrowserConfig:
        """Configuration for debugging (visible browser, DevTools, slow-mo)."""
        return cls(
            headless=False,
            stealth=False,
            devtools=True,
            slow_mo=500,
            viewport=ViewportConfig(width=1440, height=900),
        )

    # ──────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────

    def _get_storage_state_path(self) -> str | None:
        """Get the storage state file path for session persistence."""
        if not self.session.persist:
            return None
        session_id = self.session.session_id or "default"
        return f"{self.session.storage_dir}/{session_id}.json"

    def merge(self, overrides: dict[str, Any]) -> BrowserConfig:
        """
        Create a new BrowserConfig with overridden values.

        Args:
            overrides: Dictionary of field names to new values.

        Returns:
            New BrowserConfig with merged values.
        """
        current = self.to_dict()
        current.update(overrides)
        return BrowserConfig.from_dict(current)

    def __repr__(self) -> str:
        bt = self.browser_type.value if isinstance(self.browser_type, BrowserType) else self.browser_type
        return (
            f"BrowserConfig(browser={bt}, headless={self.headless}, "
            f"stealth={self.stealth}, viewport={self.viewport.width}x{self.viewport.height})"
        )


# ══════════════════════════════════════════════════════════════
# Stealth Arguments (Chromium)
# ══════════════════════════════════════════════════════════════

_STEALTH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu",
    "--no-first-run",
    "--no-zygote",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-extensions-with-background-pages",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-features=TranslateUI",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-default-browser-check",
    "--enable-features=NetworkService,NetworkServiceInProcess",
    "--force-color-profile=srgb",
]
