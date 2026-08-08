"""Tests for agentcrawl.browser.config module.

Covers:
- ViewportConfig presets (desktop_hd, mobile, tablet, etc.)
- ViewportConfig.from_dict with camelCase keys
- ProxyConfig.to_playwright_dict (with/without auth)
- ProxyConfig.from_url (with and without auth)
- ProxyConfig.from_dict
- ProxyConfig.to_dict
- BrowserPoolConfig presets
- SessionConfig to_dict/from_dict
- RecordingConfig (video_size list conversion)
- GeolocationConfig to_dict/from_dict
- BrowserConfig.__post_init__ (dict normalization)
- BrowserConfig invalid browser type
- BrowserConfig.to_launch_options (stealth args, extensions, channel)
- BrowserConfig.to_context_options (geolocation, permissions, recording)
- BrowserConfig.to_page_options
- BrowserConfig.to_dict / from_dict
- BrowserConfig.from_env
- BrowserConfig presets (default, fast, stealth_max, mobile_emulation, debugging)
- BrowserConfig.merge
- BrowserConfig.__repr__
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from agentcrawl.browser.config import (
    BrowserConfig,
    BrowserPoolConfig,
    BrowserType,
    GeolocationConfig,
    ProxyConfig,
    ProxyRotationStrategy,
    RecordingConfig,
    SessionConfig,
    ViewportConfig,
)

# ══════════════════════════════════════════════════════════════
# ViewportConfig Presets
# ══════════════════════════════════════════════════════════════


class TestViewportPresets:
    def test_desktop_hd(self) -> None:
        vp = ViewportConfig.desktop_hd()
        assert vp.width == 1920
        assert vp.height == 1080

    def test_desktop_standard(self) -> None:
        vp = ViewportConfig.desktop_standard()
        assert vp.width == 1280
        assert vp.height == 720

    def test_laptop(self) -> None:
        vp = ViewportConfig.laptop()
        assert vp.width == 1440
        assert vp.height == 900

    def test_tablet(self) -> None:
        vp = ViewportConfig.tablet()
        assert vp.is_mobile is True
        assert vp.has_touch is True
        assert vp.is_landscape is False

    def test_tablet_landscape(self) -> None:
        vp = ViewportConfig.tablet_landscape()
        assert vp.is_mobile is True
        assert vp.has_touch is True

    def test_mobile(self) -> None:
        vp = ViewportConfig.mobile()
        assert vp.device_scale_factor == 3.0
        assert vp.is_mobile is True
        assert vp.is_landscape is False

    def test_mobile_landscape(self) -> None:
        vp = ViewportConfig.mobile_landscape()
        assert vp.width == 812
        assert vp.height == 375
        assert vp.device_scale_factor == 3.0


class TestViewportConfig:
    def test_to_dict(self) -> None:
        vp = ViewportConfig(width=100, height=200)
        d = vp.to_dict()
        assert d["width"] == 100
        assert d["height"] == 200
        assert d["isMobile"] is False

    def test_from_dict_camelcase(self) -> None:
        vp = ViewportConfig.from_dict({"width": 800, "isMobile": True, "deviceScaleFactor": 2.0})
        assert vp.width == 800
        assert vp.is_mobile is True
        assert vp.device_scale_factor == 2.0


# ══════════════════════════════════════════════════════════════
# ProxyConfig
# ══════════════════════════════════════════════════════════════


class TestProxyConfig:
    def test_to_playwright_dict_no_server(self) -> None:
        proxy = ProxyConfig()
        assert proxy.to_playwright_dict() is None

    def test_to_playwright_dict_with_proxy_list(self) -> None:
        proxy = ProxyConfig(proxy_list=["http://proxy1:8080", "http://proxy2:8080"])
        result = proxy.to_playwright_dict()
        assert result is not None
        assert result["server"] == "http://proxy1:8080"

    def test_to_playwright_dict_with_credentials(self) -> None:
        proxy = ProxyConfig(
            server="http://proxy:8080",
            username="user",
            password=SecretStr("pass"),
            bypass="*.local",
        )
        result = proxy.to_playwright_dict()
        assert result["server"] == "http://proxy:8080"
        assert result["username"] == "user"
        assert result["password"] == "pass"  # noqa: S105
        assert result["bypass"] == "*.local"

    def test_from_url_simple(self) -> None:
        proxy = ProxyConfig.from_url("http://host:8080")
        assert proxy.server == "http://host:8080"
        assert proxy.username is None
        assert proxy.password is None

    def test_from_url_with_auth(self) -> None:
        proxy = ProxyConfig.from_url("http://user:pass@host:8080")
        assert proxy.server == "http://host:8080"
        assert proxy.username == "user"
        assert proxy.password.get_secret_value() == "pass"

    def test_from_url_no_port(self) -> None:
        proxy = ProxyConfig.from_url("http://host")
        assert proxy.server == "http://host:8080"

    def test_from_dict(self) -> None:
        proxy = ProxyConfig.from_dict(
            {
                "server": "http://proxy:8080",
                "rotation": "round_robin",
                "proxy_list": ["http://p1:8080"],
            }
        )
        assert proxy.server == "http://proxy:8080"
        assert proxy.rotation == ProxyRotationStrategy.ROUND_ROBIN

    def test_from_dict_string_rotation(self) -> None:
        proxy = ProxyConfig.from_dict({"rotation": "random"})
        assert proxy.rotation == ProxyRotationStrategy.RANDOM

    def test_to_dict_with_all_fields(self) -> None:
        proxy = ProxyConfig(
            server="http://proxy:8080",
            username="user",
            password=SecretStr("pass"),
            bypass="*.local",
            rotation=ProxyRotationStrategy.ROUND_ROBIN,
            proxy_list=["http://p1:8080"],
        )
        d = proxy.to_dict()
        assert d["server"] == "http://proxy:8080"
        assert d["username"] == "user"
        assert d["password"] == "********"  # noqa: S105
        assert d["bypass"] == "*.local"
        assert d["rotation"] == "round_robin"
        assert d["proxy_list"] == ["http://p1:8080"]

    def test_to_dict_minimal(self) -> None:
        proxy = ProxyConfig()
        d = proxy.to_dict()
        assert d["rotation"] == "none"
        assert "server" not in d


# ══════════════════════════════════════════════════════════════
# BrowserPoolConfig
# ══════════════════════════════════════════════════════════════


class TestBrowserPoolConfig:
    def test_defaults(self) -> None:
        pool = BrowserPoolConfig()
        assert pool.max_pages == 5
        assert pool.pre_warm == 1
        assert pool.max_contexts == 3
        assert pool.page_ttl == 300

    def test_from_dict(self) -> None:
        pool = BrowserPoolConfig.from_dict(
            {
                "max_pages": 10,
                "pre_warm": 2,
                "max_contexts": 5,
                "page_ttl": 600,
                "idle_timeout": 240,
                "recycle_after": 100,
                "health_check_interval": 30,
            }
        )
        assert pool.max_pages == 10
        assert pool.pre_warm == 2
        assert pool.max_contexts == 5

    def test_to_dict(self) -> None:
        pool = BrowserPoolConfig(max_pages=8, pre_warm=3)
        d = pool.to_dict()
        assert d["max_pages"] == 8
        assert d["pre_warm"] == 3


# ══════════════════════════════════════════════════════════════
# SessionConfig
# ══════════════════════════════════════════════════════════════


class TestSessionConfig:
    def test_defaults(self) -> None:
        session = SessionConfig()
        assert session.persist is False
        assert session.restore_on_start is True

    def test_from_dict(self) -> None:
        session = SessionConfig.from_dict(
            {
                "persist": True,
                "storage_dir": ".agentcrawl/sessions",
                "session_id": "abc123",
            }
        )
        assert session.persist is True
        assert session.storage_dir == ".agentcrawl/sessions"
        assert session.session_id == "abc123"

    def test_to_dict(self) -> None:
        session = SessionConfig(persist=True, cookies=[{"name": "x"}], local_storage={"k": "v"})
        d = session.to_dict()
        assert d["persist"] is True
        assert d["cookies_count"] == 1
        assert d["local_storage_keys"] == 1


# ══════════════════════════════════════════════════════════════
# RecordingConfig
# ══════════════════════════════════════════════════════════════


class TestRecordingConfig:
    def test_defaults(self) -> None:
        rec = RecordingConfig()
        assert rec.video_enabled is False
        assert rec.trace_enabled is False
        assert rec.har_enabled is False

    def test_from_dict_with_list_video_size(self) -> None:
        rec = RecordingConfig.from_dict(
            {
                "video_enabled": True,
                "video_size": [1920, 1080],
                "trace_enabled": True,
                "har_enabled": True,
            }
        )
        assert rec.video_enabled is True
        assert rec.video_size == (1920, 1080)
        assert rec.trace_enabled is True

    def test_to_dict(self) -> None:
        rec = RecordingConfig(video_size=(1280, 720), screenshot_on_error=True)
        d = rec.to_dict()
        assert d["video_size"] == [1280, 720]
        assert d["screenshot_on_error"] is True


# ══════════════════════════════════════════════════════════════
# GeolocationConfig
# ══════════════════════════════════════════════════════════════


class TestGeolocationConfig:
    def test_defaults(self) -> None:
        geo = GeolocationConfig()
        assert geo.latitude == 0.0
        assert geo.longitude == 0.0
        assert geo.accuracy == 100.0

    def test_to_dict(self) -> None:
        geo = GeolocationConfig(latitude=40.7, longitude=-74.0, accuracy=50.0)
        d = geo.to_dict()
        assert d["latitude"] == 40.7
        assert d["longitude"] == -74.0
        assert d["accuracy"] == 50.0

    def test_from_dict(self) -> None:
        geo = GeolocationConfig.from_dict({"latitude": 40.7, "longitude": -74.0})
        assert geo.latitude == 40.7
        assert geo.longitude == -74.0


# ══════════════════════════════════════════════════════════════
# BrowserConfig __post_init__
# ══════════════════════════════════════════════════════════════


class TestBrowserConfigPostInit:
    def test_invalid_browser_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported browser type"):
            BrowserConfig(browser_type="safari")

    def test_dict_viewport_normalized(self) -> None:
        config = BrowserConfig(viewport={"width": 1920, "height": 1080})
        assert config.viewport.width == 1920
        assert config.viewport.height == 1080

    def test_dict_proxy_normalized(self) -> None:
        config = BrowserConfig(proxy={"server": "http://proxy:8080"})
        assert config.proxy.server == "http://proxy:8080"

    def test_dict_pool_normalized(self) -> None:
        config = BrowserConfig(pool={"max_pages": 10})
        assert config.pool.max_pages == 10

    def test_dict_session_normalized(self) -> None:
        config = BrowserConfig(session={"persist": True})
        assert config.session.persist is True

    def test_dict_recording_normalized(self) -> None:
        config = BrowserConfig(recording={"video_enabled": True})
        assert config.recording.video_enabled is True

    def test_dict_geolocation_normalized(self) -> None:
        config = BrowserConfig(geolocation={"latitude": 40.7, "longitude": -74.0})
        assert config.geolocation.latitude == 40.7


# ══════════════════════════════════════════════════════════════
# BrowserConfig to_launch_options
# ══════════════════════════════════════════════════════════════


class TestBrowserConfigLaunchOptions:
    def test_to_launch_options_headless(self) -> None:
        config = BrowserConfig()
        opts = config.to_launch_options()
        assert opts["headless"] is True

    def test_to_launch_options_with_channel(self) -> None:
        config = BrowserConfig(channel="chrome")
        opts = config.to_launch_options()
        assert opts["channel"] == "chrome"

    def test_to_launch_options_executable_path(self) -> None:
        config = BrowserConfig(executable_path="/usr/bin/chrome")
        opts = config.to_launch_options()
        assert opts["executablePath"] == "/usr/bin/chrome"

    def test_to_launch_options_stealth_args(self) -> None:
        config = BrowserConfig(stealth=True)
        opts = config.to_launch_options()
        assert "args" in opts
        assert "--disable-blink-features=AutomationControlled" in opts["args"]

    def test_to_launch_options_devtools_chromium(self) -> None:
        config = BrowserConfig(browser_type="chromium", devtools=True)
        opts = config.to_launch_options()
        assert opts["devtools"] is True

    def test_to_launch_options_no_devtools_firefox(self) -> None:
        config = BrowserConfig(browser_type="firefox", devtools=True)
        opts = config.to_launch_options()
        assert "devtools" not in opts

    def test_to_launch_options_slow_mo(self) -> None:
        config = BrowserConfig(slow_mo=500)
        opts = config.to_launch_options()
        assert opts["slowMo"] == 500

    def test_to_launch_options_extensions(self) -> None:
        config = BrowserConfig(extensions=["/ext1", "/ext2"])
        opts = config.to_launch_options()
        assert "--disable-extensions-except=/ext1,/ext2" in opts["args"]
        assert "--load-extension=/ext1,/ext2" in opts["args"]

    def test_to_launch_options_proxy(self) -> None:
        config = BrowserConfig(proxy=ProxyConfig(server="http://proxy:8080"))
        opts = config.to_launch_options()
        assert opts["proxy"]["server"] == "http://proxy:8080"

    def test_to_launch_options_no_proxy(self) -> None:
        config = BrowserConfig()
        opts = config.to_launch_options()
        assert "proxy" not in opts

    def test_to_launch_options_no_stealth_firefox(self) -> None:
        config = BrowserConfig(browser_type="firefox", stealth=True)
        opts = config.to_launch_options()
        assert "args" not in opts


# ══════════════════════════════════════════════════════════════
# BrowserConfig to_context_options
# ══════════════════════════════════════════════════════════════


class TestBrowserConfigContextOptions:
    def test_to_context_options_basic(self) -> None:
        config = BrowserConfig()
        opts = config.to_context_options()
        assert opts["viewport"]["width"] == 1280
        assert opts["locale"] == "en-US"

    def test_to_context_options_user_agent(self) -> None:
        config = BrowserConfig(user_agent="MyBot/1.0")
        opts = config.to_context_options()
        assert opts["userAgent"] == "MyBot/1.0"

    def test_to_context_options_timezone(self) -> None:
        config = BrowserConfig(timezone="America/New_York")
        opts = config.to_context_options()
        assert opts["timezoneId"] == "America/New_York"

    def test_to_context_options_geolocation(self) -> None:
        config = BrowserConfig(geolocation=GeolocationConfig(latitude=40.7, longitude=-74.0))
        opts = config.to_context_options()
        assert opts["geolocation"]["latitude"] == 40.7
        assert "geolocation" in config.permissions

    def test_to_context_options_permissions(self) -> None:
        config = BrowserConfig(permissions=["geolocation", "notifications"])
        opts = config.to_context_options()
        assert opts["permissions"] == ["geolocation", "notifications"]

    def test_to_context_options_extra_headers(self) -> None:
        config = BrowserConfig(extra_headers={"X-Custom": "value"})
        opts = config.to_context_options()
        assert opts["extraHTTPHeaders"] == {"X-Custom": "value"}

    def test_to_context_options_http_credentials(self) -> None:
        config = BrowserConfig(http_credentials={"username": "user", "password": "pass"})
        opts = config.to_context_options()
        assert opts["httpCredentials"]["username"] == "user"

    def test_to_context_options_offline(self) -> None:
        config = BrowserConfig(offline=True)
        opts = config.to_context_options()
        assert opts["offline"] is True

    def test_to_context_options_download_dir(self) -> None:
        config = BrowserConfig(download_dir=".agentcrawl/downloads")
        opts = config.to_context_options()
        assert opts["acceptDownloads"] is True

    def test_to_context_options_video(self) -> None:
        config = BrowserConfig(
            recording=RecordingConfig(video_enabled=True, video_dir=".agentcrawl/videos")
        )
        opts = config.to_context_options()
        assert opts["recordVideo"]["dir"] == ".agentcrawl/videos"

    def test_to_context_options_har(self) -> None:
        config = BrowserConfig(
            recording=RecordingConfig(har_enabled=True, har_path=".agentcrawl/har/recording.har")
        )
        opts = config.to_context_options()
        assert opts["recordHar"]["path"] == ".agentcrawl/har/recording.har"

    def test_to_context_options_session_persist(self) -> None:
        config = BrowserConfig(
            session=SessionConfig(
                persist=True, storage_dir=".agentcrawl/sessions", session_id="sid"
            )
        )
        opts = config.to_context_options()
        assert opts["storageState"] == ".agentcrawl/sessions/sid.json"

    def test_to_context_options_session_not_persist(self) -> None:
        config = BrowserConfig(
            session=SessionConfig(persist=False, storage_dir=".agentcrawl/sessions")
        )
        opts = config.to_context_options()
        assert "storageState" not in opts


class TestBrowserConfigPageOptions:
    def test_to_page_options(self) -> None:
        config = BrowserConfig(timeout=60000, navigation_timeout=30000)
        opts = config.to_page_options()
        assert opts["timeout"] == 60000
        assert opts["navigation_timeout"] == 30000


# ══════════════════════════════════════════════════════════════
# BrowserConfig serialization
# ══════════════════════════════════════════════════════════════


class TestBrowserConfigSerialization:
    def test_to_dict(self) -> None:
        config = BrowserConfig(user_agent="MyBot/1.0")
        d = config.to_dict()
        assert d["browser_type"] == "chromium"
        assert d["user_agent"] == "MyBot/1.0"
        assert d["viewport"]["width"] == 1280
        assert "proxy" not in d

    def test_to_dict_with_proxy(self) -> None:
        config = BrowserConfig(
            proxy=ProxyConfig(server="http://proxy:8080", password=SecretStr("pass"))
        )
        d = config.to_dict()
        assert d["proxy"]["server"] == "http://proxy:8080"
        assert d["proxy"]["password"] == "********"  # noqa: S105

    def test_to_dict_with_geolocation(self) -> None:
        config = BrowserConfig(geolocation=GeolocationConfig(latitude=40.7, longitude=-74.0))
        d = config.to_dict()
        assert d["geolocation"]["latitude"] == 40.7

    def test_to_dict_with_http_credentials(self) -> None:
        config = BrowserConfig(http_credentials={"username": "user"})
        d = config.to_dict()
        assert d["http_credentials"]["username"] == "user"

    def test_from_dict_proxy_url(self) -> None:
        config = BrowserConfig.from_dict({"proxy": "http://proxy:8080"})
        assert config.proxy.server == "http://proxy:8080"

    def test_from_dict_str_proxy(self) -> None:
        config = BrowserConfig.from_dict({"proxy": "http://host:8080"})
        assert config.proxy.server == "http://host:8080"

    def test_repr(self) -> None:
        config = BrowserConfig(browser_type="chromium", headless=True, stealth=True)
        repr_str = repr(config)
        assert "BrowserConfig" in repr_str
        assert "chromium" in repr_str


# ══════════════════════════════════════════════════════════════
# BrowserConfig.from_env
# ══════════════════════════════════════════════════════════════


class TestBrowserConfigFromEnv:
    def test_from_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ["AGENTCRAWL_BROWSER", "AGENTCRAWL_HEADLESS", "AGENTCRAWL_STEALTH"]:
            monkeypatch.delenv(key, raising=False)
        config = BrowserConfig.from_env()
        assert config.browser_type == BrowserType.CHROMIUM
        assert config.headless is True
        assert config.stealth is True

    def test_from_env_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTCRAWL_BROWSER", "firefox")
        monkeypatch.setenv("AGENTCRAWL_HEADLESS", "false")
        monkeypatch.setenv("AGENTCRAWL_STEALTH", "false")
        monkeypatch.setenv("AGENTCRAWL_TIMEOUT", "60")
        monkeypatch.setenv("AGENTCRAWL_MAX_CONCURRENT", "10")
        monkeypatch.setenv("AGENTCRAWL_LOCALE", "th-TH")
        monkeypatch.setenv("AGENTCRAWL_TIMEZONE", "Asia/Bangkok")
        monkeypatch.setenv("AGENTCRAWL_IGNORE_HTTPS_ERRORS", "true")
        monkeypatch.setenv("AGENTCRAWL_JAVASCRIPT_ENABLED", "false")
        monkeypatch.setenv("AGENTCRAWL_VIEWPORT_WIDTH", "1920")
        monkeypatch.setenv("AGENTCRAWL_VIEWPORT_HEIGHT", "1080")
        monkeypatch.setenv("AGENTCRAWL_USER_AGENT", "TestBot/1.0")
        monkeypatch.setenv("AGENTCRAWL_PROXY_URL", "http://proxy:8080")
        monkeypatch.setenv("AGENTCRAWL_NAVIGATION_TIMEOUT", "45")

        config = BrowserConfig.from_env()
        assert config.browser_type == BrowserType.FIREFOX
        assert config.headless is False
        assert config.stealth is False
        assert config.timeout == 60000
        assert config.navigation_timeout == 45000
        assert config.pool.max_pages == 10
        assert config.locale == "th-TH"
        assert config.timezone == "Asia/Bangkok"
        assert config.ignore_https_errors is True
        assert config.java_script_enabled is False
        assert config.viewport.width == 1920
        assert config.viewport.height == 1080
        assert config.user_agent == "TestBot/1.0"
        assert config.proxy.server == "http://proxy:8080"

    def test_from_env_invalid_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTCRAWL_TIMEOUT", "not_a_number")
        config = BrowserConfig.from_env()
        assert config.timeout == 30000  # falls back to default


# ══════════════════════════════════════════════════════════════
# BrowserConfig Presets
# ══════════════════════════════════════════════════════════════


class TestBrowserConfigPresets:
    def test_default_preset(self) -> None:
        config = BrowserConfig.default()
        assert config.browser_type == BrowserType.CHROMIUM
        assert config.stealth is True

    def test_fast_preset(self) -> None:
        config = BrowserConfig.fast()
        assert config.stealth is False
        assert config.pool.max_pages == 10
        assert "--disable-gpu" in config.extra_args

    def test_stealth_max_preset(self) -> None:
        config = BrowserConfig.stealth_max()
        assert config.stealth is True
        assert config.viewport.width == 1920
        assert config.user_agent is not None
        assert "Chrome/125" in config.user_agent

    def test_mobile_emulation_preset(self) -> None:
        config = BrowserConfig.mobile_emulation()
        assert config.viewport.is_mobile is True
        assert "iPhone" in config.user_agent

    def test_debugging_preset(self) -> None:
        config = BrowserConfig.debugging()
        assert config.headless is False
        assert config.devtools is True
        assert config.slow_mo == 500


# ══════════════════════════════════════════════════════════════
# BrowserConfig merge
# ══════════════════════════════════════════════════════════════


class TestBrowserConfigMerge:
    def test_merge(self) -> None:
        config = BrowserConfig(browser_type="chromium", headless=True)
        merged = config.merge({"browser_type": "firefox", "headless": False})
        assert merged.browser_type == BrowserType.FIREFOX
        assert merged.headless is False

    def test_merge_proxy_string(self) -> None:
        config = BrowserConfig()
        merged = config.merge({"proxy": "http://proxy:8080"})
        assert merged.proxy.server == "http://proxy:8080"
