"""
AgentCrawl — Stealth Adapter
===============================

Anti-bot evasion and browser fingerprint spoofing for Playwright.
Injects JavaScript patches into every page and context to make
automated browsers indistinguishable from real user sessions.

Patches Applied:
    - navigator.webdriver removal
    - Chrome runtime object injection
    - Plugin and MIME type spoofing
    - WebGL vendor/renderer randomization
    - Canvas fingerprint noise injection
    - AudioContext fingerprint noise
    - Hardware concurrency & device memory spoofing
    - Platform & user-agent consistency
    - Screen resolution consistency
    - Permissions API patching
    - iframe contentWindow fix
    - Function.toString() protection
    - Connection type (NetworkInformation) spoofing
    - Battery API spoofing
    - Intl.DateTimeFormat timezone consistency

Usage:
    from agentcrawl.browser.stealth import StealthAdapter
    from agentcrawl.browser.config import BrowserConfig

    config = BrowserConfig(stealth=True)
    adapter = StealthAdapter(config)

    # Apply to a browser context (all pages within)
    await adapter.apply_to_context(context)

    # Apply to a single page
    await adapter.apply_to_page(page)

    # Get the current fingerprint
    print(adapter.fingerprint)
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

from agentcrawl.browser.config import BrowserConfig

logger = logging.getLogger("agentcrawl.browser.stealth")


# ══════════════════════════════════════════════════════════════
# Fingerprint Data Model
# ══════════════════════════════════════════════════════════════


@dataclass
class BrowserFingerprint:
    """
    A complete browser fingerprint profile used for spoofing.

    All values are randomized on creation unless explicitly set,
    ensuring each browser session has a unique but consistent
    fingerprint.

    Attributes:
        user_agent: Full User-Agent string.
        platform: navigator.platform value.
        language: Primary language (e.g., 'en-US').
        languages: Accept-Language list.
        hardware_concurrency: navigator.hardwareConcurrency.
        device_memory: navigator.deviceMemory (GB).
        max_touch_points: navigator.maxTouchPoints.
        screen_width: screen.width.
        screen_height: screen.height.
        screen_avail_width: screen.availWidth.
        screen_avail_height: screen.availHeight.
        color_depth: screen.colorDepth.
        pixel_depth: screen.pixelDepth.
        device_pixel_ratio: window.devicePixelRatio.
        timezone: Intl timezone identifier.
        webgl_vendor: WebGL UNMASKED_VENDOR_WEBGL.
        webgl_renderer: WebGL UNMASKED_RENDERER_WEBGL.
        canvas_noise_seed: Seed for canvas noise injection.
        audio_noise_seed: Seed for AudioContext noise.
        chrome_version: Chrome major version for runtime injection.
        platform_category: 'desktop', 'mobile', or 'tablet'.
        os_name: Operating system name.
        browser_name: Browser name.
    """

    user_agent: str = ""
    platform: str = "Win32"
    language: str = "en-US"
    languages: list[str] = field(default_factory=lambda: ["en-US", "en"])
    hardware_concurrency: int = 8
    device_memory: int = 8
    max_touch_points: int = 0
    screen_width: int = 1920
    screen_height: int = 1080
    screen_avail_width: int = 1920
    screen_avail_height: int = 1040
    color_depth: int = 24
    pixel_depth: int = 24
    device_pixel_ratio: float = 1.0
    timezone: str = "America/New_York"
    webgl_vendor: str = "Google Inc. (NVIDIA)"
    webgl_renderer: str = "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    canvas_noise_seed: int = 0
    audio_noise_seed: int = 0
    chrome_version: int = 125
    platform_category: str = "desktop"
    os_name: str = "Windows"
    browser_name: str = "Chrome"

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_agent": self.user_agent,
            "platform": self.platform,
            "language": self.language,
            "languages": self.languages,
            "hardware_concurrency": self.hardware_concurrency,
            "device_memory": self.device_memory,
            "max_touch_points": self.max_touch_points,
            "screen": {
                "width": self.screen_width,
                "height": self.screen_height,
                "avail_width": self.screen_avail_width,
                "avail_height": self.screen_avail_height,
                "color_depth": self.color_depth,
                "pixel_depth": self.pixel_depth,
            },
            "device_pixel_ratio": self.device_pixel_ratio,
            "timezone": self.timezone,
            "webgl": {
                "vendor": self.webgl_vendor,
                "renderer": self.webgl_renderer,
            },
            "platform_category": self.platform_category,
            "os_name": self.os_name,
            "browser_name": self.browser_name,
            "chrome_version": self.chrome_version,
        }

    @classmethod
    def generate(
        cls,
        platform_category: str = "desktop",
        os_name: str | None = None,
        locale: str = "en-US",
        timezone: str | None = None,
        seed: int | None = None,
    ) -> BrowserFingerprint:
        """
        Generate a randomized but internally consistent fingerprint.

        Args:
            platform_category: 'desktop', 'mobile', or 'tablet'.
            os_name: Force a specific OS ('Windows', 'macOS', 'Linux', 'Android', 'iOS').
            locale: Primary locale for language settings.
            timezone: Force a specific timezone.
            seed: Random seed for reproducibility.

        Returns:
            BrowserFingerprint with randomized values.
        """
        rng = random.Random(seed)  # noqa: S311 - deterministic seed for fingerprint, not crypto

        # OS selection
        if os_name is None:
            if platform_category == "desktop":
                os_name = rng.choice(["Windows", "macOS", "Linux"])
            elif platform_category == "mobile":
                os_name = rng.choice(["Android", "iOS"])
            else:
                os_name = rng.choice(["Android", "iOS"])

        # Chrome version
        chrome_version = rng.randint(120, 130)

        # Platform & User-Agent
        if os_name == "Windows":
            platform = "Win32"
            ua_os = "Windows NT 10.0; Win64; x64"
        elif os_name == "macOS":
            platform = "MacIntel"
            mac_ver = rng.choice(["10_15_7", "14_0", "14_5"])
            ua_os = f"Macintosh; Intel Mac OS X {mac_ver}"
        elif os_name == "Linux":
            platform = "Linux x86_64"
            ua_os = "X11; Linux x86_64"
        elif os_name == "Android":
            platform = "Linux armv8l"
            android_ver = rng.choice(["13", "14"])
            ua_os = f"Linux; Android {android_ver}; Pixel 7"
        elif os_name == "iOS":
            platform = "iPhone"
            ios_ver = rng.choice(["17_0", "17_5", "16_6"])
            ua_os = f"iPhone; CPU iPhone OS {ios_ver} like Mac OS X"
        else:
            platform = "Win32"
            ua_os = "Windows NT 10.0; Win64; x64"

        if platform_category == "mobile" and os_name == "iOS":
            user_agent = (
                f"Mozilla/5.0 ({ua_os}) AppleWebKit/605.1.15 "
                f"(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            )
            browser_name = "Safari"
        elif platform_category == "mobile":
            user_agent = (
                f"Mozilla/5.0 ({ua_os}) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36"
            )
            browser_name = "Chrome"
        else:
            user_agent = (
                f"Mozilla/5.0 ({ua_os}) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36"
            )
            browser_name = "Chrome"

        # Screen resolution
        if platform_category == "desktop":
            resolutions = [
                (1920, 1080),
                (2560, 1440),
                (1366, 768),
                (1536, 864),
                (1440, 900),
                (1680, 1050),
            ]
            screen_w, screen_h = rng.choice(resolutions)
            avail_h = screen_h - rng.choice([40, 48, 80])
            dpr = rng.choice([1.0, 1.25, 1.5, 2.0])
            touch_points = 0
        elif platform_category == "mobile":
            resolutions = [
                (375, 812),
                (390, 844),
                (414, 896),
                (360, 780),
                (412, 915),
            ]
            screen_w, screen_h = rng.choice(resolutions)
            avail_h = screen_h
            dpr = rng.choice([2.0, 3.0])
            touch_points = rng.choice([1, 5, 10])
        else:  # tablet
            resolutions = [
                (768, 1024),
                (810, 1080),
                (834, 1194),
                (800, 1280),
            ]
            screen_w, screen_h = rng.choice(resolutions)
            avail_h = screen_h
            dpr = rng.choice([2.0])
            touch_points = rng.choice([5, 10])

        # Hardware
        if platform_category == "desktop":
            hw_concurrency = rng.choice([4, 8, 12, 16])
            dev_memory = rng.choice([4, 8, 16, 32])
        else:
            hw_concurrency = rng.choice([4, 6, 8])
            dev_memory = rng.choice([4, 6, 8])

        # WebGL
        if os_name == "Windows":
            gpus = [
                (
                    "Google Inc. (NVIDIA)",
                    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                ),
                (
                    "Google Inc. (NVIDIA)",
                    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                ),
                (
                    "Google Inc. (AMD)",
                    "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                ),
                (
                    "Google Inc. (Intel)",
                    "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                ),
            ]
        elif os_name == "macOS":
            gpus = [
                ("Apple Inc.", "Apple M1 Pro"),
                ("Apple Inc.", "Apple M2"),
                ("Apple Inc.", "Apple M3"),
                ("AMD", "AMD Radeon Pro 5500M OpenGL Engine"),
            ]
        else:
            gpus = [
                (
                    "Google Inc. (Intel)",
                    "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630, OpenGL 4.6)",
                ),
                ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650, OpenGL 4.5)"),
            ]
        webgl_vendor, webgl_renderer = rng.choice(gpus)

        # Timezone
        if timezone is None:
            tz_map = {
                "en-US": "America/New_York",
                "en-GB": "Europe/London",
                "th-TH": "Asia/Bangkok",
                "ja-JP": "Asia/Tokyo",
                "de-DE": "Europe/Berlin",
                "fr-FR": "Europe/Paris",
            }
            timezone = tz_map.get(locale, "America/New_York")

        # Languages
        lang_base = locale.split("-")[0]
        languages = [locale]
        if lang_base != "en":
            languages.append("en")
        languages.append(lang_base)

        return cls(
            user_agent=user_agent,
            platform=platform,
            language=locale,
            languages=languages,
            hardware_concurrency=hw_concurrency,
            device_memory=dev_memory,
            max_touch_points=touch_points,
            screen_width=screen_w,
            screen_height=screen_h,
            screen_avail_width=screen_w,
            screen_avail_height=avail_h,
            color_depth=24,
            pixel_depth=24,
            device_pixel_ratio=dpr,
            timezone=timezone,
            webgl_vendor=webgl_vendor,
            webgl_renderer=webgl_renderer,
            canvas_noise_seed=rng.randint(1, 999999),
            audio_noise_seed=rng.randint(1, 999999),
            chrome_version=chrome_version,
            platform_category=platform_category,
            os_name=os_name,
            browser_name=browser_name,
        )


# ══════════════════════════════════════════════════════════════
# JavaScript Injection Scripts
# ══════════════════════════════════════════════════════════════


def _build_stealth_script(fp: BrowserFingerprint) -> str:
    """
    Build the complete stealth injection script for a fingerprint.

    This script is injected into every page via addInitScript
    and runs before any page JavaScript.
    """
    fp_json = json.dumps(fp.to_dict())

    # Build the script by concatenation to avoid format string issues with
    # JavaScript braces, backslashes, and template literals.
    parts = []
    parts.append("(() => {")
    parts.append("  'use strict';")
    parts.append("")
    parts.append(f"  const FP = {fp_json};")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 1. Remove navigator.webdriver")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  Object.defineProperty(navigator, 'webdriver', {")
    parts.append("    get: () => undefined,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  // Also patch the prototype")
    parts.append(
        "  const originalDesc = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');"
    )
    parts.append("  if (originalDesc) {")
    parts.append("    Object.defineProperty(Navigator.prototype, 'webdriver', {")
    parts.append("      get: () => undefined,")
    parts.append("      configurable: true,")
    parts.append("    });")
    parts.append("  }")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 2. Inject Chrome runtime object")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  if (!window.chrome) {")
    parts.append("    window.chrome = {")
    parts.append("      app: {")
    parts.append("        isInstalled: false,")
    parts.append(
        "        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },"
    )
    parts.append(
        "        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },"
    )
    parts.append("        getDetails: () => null,")
    parts.append("        getIsInstalled: () => false,")
    parts.append("      },")
    parts.append("      runtime: {")
    parts.append("        OnInstalledReason: {")
    parts.append("          CHROME_UPDATE: 'chrome_update',")
    parts.append("          INSTALL: 'install',")
    parts.append("          SHARED_MODULE_UPDATE: 'shared_module_update',")
    parts.append("          UPDATE: 'update',")
    parts.append("        },")
    parts.append("        OnRestartRequiredReason: {")
    parts.append("          APP_UPDATE: 'app_update',")
    parts.append("          OS_UPDATE: 'os_update',")
    parts.append("          PERIODIC: 'periodic',")
    parts.append("        },")
    parts.append(
        "        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },"
    )
    parts.append(
        "        PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },"
    )
    parts.append(
        "        PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },"
    )
    parts.append(
        "        RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' },"
    )
    parts.append(
        "        connect: function() { return { onDisconnect: { addListener: function() {} }, onMessage: { addListener: function() {} }, postMessage: function() {} }; },"
    )
    parts.append(
        "        sendMessage: function() { if (arguments.length > 0 && typeof arguments[arguments.length - 1] === 'function') { arguments[arguments.length - 1](); } },"
    )
    parts.append("      },")
    parts.append(
        "      csi: function() { return { startE: Date.now(), onloadT: Date.now() + 100, pageT: Date.now() + 100, tran: 15 }; },"
    )
    parts.append("      loadTimes: function() {")
    parts.append("        return {")
    parts.append("          commitLoadTime: Date.now() / 1000,")
    parts.append("          connectionInfo: 'h2',")
    parts.append("          finishDocumentLoadTime: Date.now() / 1000,")
    parts.append("          finishLoadTime: Date.now() / 1000,")
    parts.append("          firstPaintAfterLoadTime: 0,")
    parts.append("          firstPaintTime: Date.now() / 1000,")
    parts.append("          navigationType: 'Other',")
    parts.append("          npnNegotiatedProtocol: 'h2',")
    parts.append("          requestTime: Date.now() / 1000 - 0.16,")
    parts.append("          startLoadTime: Date.now() / 1000 - 0.16,")
    parts.append("          wasAlternateProtocolAvailable: false,")
    parts.append("          wasFetchedViaSpdy: true,")
    parts.append("          wasNpnNegotiated: true,")
    parts.append("        };")
    parts.append("      },")
    parts.append("    };")
    parts.append("  }")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 3. Spoof navigator properties")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  Object.defineProperty(navigator, 'platform', {")
    parts.append("    get: () => FP.platform,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  Object.defineProperty(navigator, 'hardwareConcurrency', {")
    parts.append("    get: () => FP.hardware_concurrency,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  Object.defineProperty(navigator, 'deviceMemory', {")
    parts.append("    get: () => FP.device_memory,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  Object.defineProperty(navigator, 'maxTouchPoints', {")
    parts.append("    get: () => FP.max_touch_points,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  Object.defineProperty(navigator, 'language', {")
    parts.append("    get: () => FP.language,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  Object.defineProperty(navigator, 'languages', {")
    parts.append("    get: () => Object.freeze([...FP.languages]),")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 4. Spoof plugins and MIME types")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const makePlugin = (name, description, filename, mimeTypes) => {")
    parts.append("    const plugin = Object.create(Plugin.prototype);")
    parts.append("    Object.defineProperties(plugin, {")
    parts.append("      name: { get: () => name, enumerable: true },")
    parts.append("      description: { get: () => description, enumerable: true },")
    parts.append("      filename: { get: () => filename, enumerable: true },")
    parts.append("      length: { get: () => mimeTypes.length, enumerable: true },")
    parts.append("    });")
    parts.append("    mimeTypes.forEach((mt, i) => {")
    parts.append("      Object.defineProperty(plugin, i, { get: () => mt, enumerable: true });")
    parts.append("    });")
    parts.append("    return plugin;")
    parts.append("  };")
    parts.append("")
    parts.append("  const pdfMime = Object.create(MimeType.prototype);")
    parts.append("  Object.defineProperties(pdfMime, {")
    parts.append("    type: { get: () => 'application/pdf', enumerable: true },")
    parts.append("    suffixes: { get: () => 'pdf', enumerable: true },")
    parts.append("    description: { get: () => 'Portable Document Format', enumerable: true },")
    parts.append("  });")
    parts.append("")
    parts.append("  const pdfxMime = Object.create(MimeType.prototype);")
    parts.append("  Object.defineProperties(pdfxMime, {")
    parts.append("    type: { get: () => 'application/x-google-chrome-pdf', enumerable: true },")
    parts.append("    suffixes: { get: () => 'pdf', enumerable: true },")
    parts.append("    description: { get: () => 'Portable Document Format', enumerable: true },")
    parts.append("  });")
    parts.append("")
    parts.append("  const chromePlugins = [")
    parts.append(
        "    makePlugin('PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),"
    )
    parts.append(
        "    makePlugin('Chrome PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),"
    )
    parts.append(
        "    makePlugin('Chromium PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),"
    )
    parts.append(
        "    makePlugin('Microsoft Edge PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),"
    )
    parts.append(
        "    makePlugin('WebKit built-in PDF', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),"
    )
    parts.append("  ];")
    parts.append("")
    parts.append("  Object.defineProperty(navigator, 'plugins', {")
    parts.append("    get: () => {")
    parts.append("      const list = Object.create(PluginArray.prototype);")
    parts.append("      chromePlugins.forEach((p, i) => {")
    parts.append("        Object.defineProperty(list, i, { get: () => p, enumerable: true });")
    parts.append("      });")
    parts.append(
        "      Object.defineProperty(list, 'length', { get: () => chromePlugins.length, enumerable: true });"
    )
    parts.append("      list.item = (i) => chromePlugins[i] || null;")
    parts.append("      list.namedItem = (n) => chromePlugins.find(p => p.name === n) || null;")
    parts.append("      return list;")
    parts.append("    },")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  Object.defineProperty(navigator, 'mimeTypes', {")
    parts.append("    get: () => {")
    parts.append("      const list = Object.create(MimeTypeArray.prototype);")
    parts.append("      const mimes = [pdfMime, pdfxMime];")
    parts.append("      mimes.forEach((m, i) => {")
    parts.append("        Object.defineProperty(list, i, { get: () => m, enumerable: true });")
    parts.append("      });")
    parts.append(
        "      Object.defineProperty(list, 'length', { get: () => mimes.length, enumerable: true });"
    )
    parts.append("      list.item = (i) => mimes[i] || null;")
    parts.append("      list.namedItem = (n) => mimes.find(m => m.type === n) || null;")
    parts.append("      return list;")
    parts.append("    },")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 5. Spoof screen properties")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  Object.defineProperty(screen, 'width', {")
    parts.append("    get: () => FP.screen_width,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("  Object.defineProperty(screen, 'height', {")
    parts.append("    get: () => FP.screen_height,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("  Object.defineProperty(screen, 'availWidth', {")
    parts.append("    get: () => FP.screen_avail_width,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("  Object.defineProperty(screen, 'availHeight', {")
    parts.append("    get: () => FP.screen_avail_height,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("  Object.defineProperty(screen, 'colorDepth', {")
    parts.append("    get: () => FP.color_depth,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("  Object.defineProperty(screen, 'pixelDepth', {")
    parts.append("    get: () => FP.pixel_depth,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  Object.defineProperty(window, 'devicePixelRatio', {")
    parts.append("    get: () => FP.device_pixel_ratio,")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 6. WebGL fingerprint spoofing")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const originalGetParameter = WebGLRenderingContext.prototype.getParameter;")
    parts.append("  WebGLRenderingContext.prototype.getParameter = function(parameter) {")
    parts.append("    // UNMASKED_VENDOR_WEBGL = 0x9245")
    parts.append("    // UNMASKED_RENDERER_WEBGL = 0x9246")
    parts.append("    if (parameter === 0x9245) {")
    parts.append("      return FP.webgl_vendor;")
    parts.append("    }")
    parts.append("    if (parameter === 0x9246) {")
    parts.append("      return FP.webgl_renderer;")
    parts.append("    }")
    parts.append("    return originalGetParameter.call(this, parameter);")
    parts.append("  };")
    parts.append("")
    parts.append("  const originalGetParameter2 = WebGL2RenderingContext.prototype.getParameter;")
    parts.append("  WebGL2RenderingContext.prototype.getParameter = function(parameter) {")
    parts.append("    if (parameter === 0x9245) {")
    parts.append("      return FP.webgl_vendor;")
    parts.append("    }")
    parts.append("    if (parameter === 0x9246) {")
    parts.append("      return FP.webgl_renderer;")
    parts.append("    }")
    parts.append("    return originalGetParameter2.call(this, parameter);")
    parts.append("  };")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 7. Canvas fingerprint noise injection")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const canvasNoiseSeed = FP.canvas_noise_seed;")
    parts.append("  let canvasNoiseCounter = 0;")
    parts.append("")
    parts.append("  const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;")
    parts.append("  HTMLCanvasElement.prototype.toDataURL = function(type, quality) {")
    parts.append("    if (this.width > 0 && this.height > 0) {")
    parts.append("      const ctx = this.getContext('2d');")
    parts.append("      if (ctx) {")
    parts.append("        // Generate deterministic noise based on seed")
    parts.append(
        "        const noise = ((canvasNoiseSeed + canvasNoiseCounter) * 9301 + 49297) % 233280;"
    )
    parts.append("        canvasNoiseCounter++;")
    parts.append("        const opacity = (noise / 233280) * 0.01; // 0-1% opacity noise")
    parts.append("        ctx.save();")
    parts.append("        ctx.globalAlpha = opacity;")
    parts.append("        ctx.fillStyle = '#ffffff';")
    parts.append("        ctx.fillRect(0, 0, 1, 1);")
    parts.append("        ctx.restore();")
    parts.append("      }")
    parts.append("    }")
    parts.append("    return originalToDataURL.call(this, type, quality);")
    parts.append("  };")
    parts.append("")
    parts.append("  const originalToBlob = HTMLCanvasElement.prototype.toBlob;")
    parts.append("  HTMLCanvasElement.prototype.toBlob = function(callback, type, quality) {")
    parts.append("    if (this.width > 0 && this.height > 0) {")
    parts.append("      const ctx = this.getContext('2d');")
    parts.append("      if (ctx) {")
    parts.append(
        "        const noise = ((canvasNoiseSeed + canvasNoiseCounter) * 9301 + 49297) % 233280;"
    )
    parts.append("        canvasNoiseCounter++;")
    parts.append("        const opacity = (noise / 233280) * 0.01;")
    parts.append("        ctx.save();")
    parts.append("        ctx.globalAlpha = opacity;")
    parts.append("        ctx.fillStyle = '#ffffff';")
    parts.append("        ctx.fillRect(0, 0, 1, 1);")
    parts.append("        ctx.restore();")
    parts.append("      }")
    parts.append("    }")
    parts.append("    return originalToBlob.call(this, callback, type, quality);")
    parts.append("  };")
    parts.append("")
    parts.append("  const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;")
    parts.append("  CanvasRenderingContext2D.prototype.getImageData = function(sx, sy, sw, sh) {")
    parts.append("    const imageData = originalGetImageData.call(this, sx, sy, sw, sh);")
    parts.append("    if (imageData && imageData.data.length > 0) {")
    parts.append(
        "      const noise = ((canvasNoiseSeed + canvasNoiseCounter) * 9301 + 49297) % 233280;"
    )
    parts.append("      canvasNoiseCounter++;")
    parts.append("      const noiseValue = Math.floor((noise / 233280) * 2); // 0 or 1")
    parts.append("      // Apply subtle noise to a few random pixels")
    parts.append("      for (let i = 0; i < Math.min(4, imageData.data.length / 4); i++) {")
    parts.append("        const idx = Math.floor(Math.random() * (imageData.data.length / 4)) * 4;")
    parts.append("        imageData.data[idx] = Math.min(255, imageData.data[idx] + noiseValue);")
    parts.append(
        "        imageData.data[idx + 1] = Math.min(255, imageData.data[idx + 1] + noiseValue);"
    )
    parts.append(
        "        imageData.data[idx + 2] = Math.min(255, imageData.data[idx + 2] + noiseValue);"
    )
    parts.append("      }")
    parts.append("    }")
    parts.append("    return imageData;")
    parts.append("  };")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 8. AudioContext fingerprint noise")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const audioNoiseSeed = FP.audio_noise_seed;")
    parts.append("  const originalCreateOscillator = AudioContext.prototype.createOscillator;")
    parts.append("  AudioContext.prototype.createOscillator = function() {")
    parts.append("    const osc = originalCreateOscillator.call(this);")
    parts.append("    const originalStart = osc.start;")
    parts.append("    osc.start = function(when) {")
    parts.append("      // Add subtle frequency drift based on seed")
    parts.append("      const drift = ((audioNoiseSeed * 9301 + 49297) % 233280) / 233280 * 0.001;")
    parts.append("      osc.frequency.value = osc.frequency.value * (1 + drift);")
    parts.append("      return originalStart.call(this, when);")
    parts.append("    };")
    parts.append("    return osc;")
    parts.append("  };")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 9. Permissions API patching")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const originalQuery = navigator.permissions?.query;")
    parts.append("  if (originalQuery) {")
    parts.append("    navigator.permissions.query = function(permissionDesc) {")
    parts.append("      // Override notifications permission to 'prompt' instead of 'default'")
    parts.append("      if (permissionDesc && permissionDesc.name === 'notifications') {")
    parts.append("        return Promise.resolve({ state: 'prompt', onchange: null });")
    parts.append("      }")
    parts.append("      return originalQuery.call(this, permissionDesc);")
    parts.append("    };")
    parts.append("  }")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 10. iframe contentWindow fix")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const originalFrameElement = HTMLIFrameElement.prototype.contentWindow;")
    parts.append("  Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {")
    parts.append("    get: function() {")
    parts.append("      try {")
    parts.append("        return originalFrameElement.get.call(this);")
    parts.append("      } catch (e) {")
    parts.append("        // Return a safe proxy for cross-origin iframes")
    parts.append("        return {")
    parts.append("          location: { href: 'about:blank' },")
    parts.append("          document: { referrer: '' },")
    parts.append("          navigator: { userAgent: FP.user_agent },")
    parts.append("        };")
    parts.append("      }")
    parts.append("    },")
    parts.append("    configurable: true,")
    parts.append("  });")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 11. Function.toString() protection")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const originalToString = Function.prototype.toString;")
    parts.append(
        "  const nativeCodeRegex = /^function\\\\s+\\\\w+\\\\(\\\\)\\\\s*\\\\{\\\\s*\\\\[native code\\\\]\\\\s*\\\\}$/;"
    )
    parts.append("")
    parts.append("  const patchedFunctions = new Map();")
    parts.append("")
    parts.append("  const registerNative = (obj, prop, originalName) => {")
    parts.append("    const fn = obj[prop];")
    parts.append("    if (typeof fn === 'function') {")
    parts.append(
        "      patchedFunctions.set(fn, `function ${originalName || prop}() { [native code] }`);"
    )
    parts.append("    }")
    parts.append("  };")
    parts.append("")
    parts.append("  Function.prototype.toString = function() {")
    parts.append("    if (patchedFunctions.has(this)) {")
    parts.append("      return patchedFunctions.get(this);")
    parts.append("    }")
    parts.append("    return originalToString.call(this);")
    parts.append("  };")
    parts.append("")
    parts.append(
        "  patchedFunctions.set(Function.prototype.toString, 'function toString() { [native code] }');"
    )
    parts.append("")
    parts.append('  // Register key patched functions as "native"')
    parts.append("  registerNative(navigator, 'webdriver', 'get webdriver');")
    parts.append("  registerNative(navigator, 'plugins', 'get plugins');")
    parts.append("  registerNative(navigator, 'mimeTypes', 'get mimeTypes');")
    parts.append("  registerNative(navigator, 'languages', 'get languages');")
    parts.append("  registerNative(navigator, 'hardwareConcurrency', 'get hardwareConcurrency');")
    parts.append("  registerNative(navigator, 'deviceMemory', 'get deviceMemory');")
    parts.append("  registerNative(screen, 'width', 'get width');")
    parts.append("  registerNative(screen, 'height', 'get height');")
    parts.append("  registerNative(window, 'devicePixelRatio', 'get devicePixelRatio');")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 12. NetworkInformation spoofing")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  if (navigator.connection) {")
    parts.append("    Object.defineProperty(navigator.connection, 'rtt', {")
    parts.append("      get: () => 50,")
    parts.append("      configurable: true,")
    parts.append("    });")
    parts.append("    Object.defineProperty(navigator.connection, 'downlink', {")
    parts.append("      get: () => 10,")
    parts.append("      configurable: true,")
    parts.append("    });")
    parts.append("    Object.defineProperty(navigator.connection, 'effectiveType', {")
    parts.append("      get: () => '4g',")
    parts.append("      configurable: true,")
    parts.append("    });")
    parts.append("  }")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 13. Battery API spoofing")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  if (navigator.getBattery) {")
    parts.append("    const originalGetBattery = navigator.getBattery;")
    parts.append("    navigator.getBattery = function() {")
    parts.append("      return originalGetBattery.call(this).then(battery => {")
    parts.append(
        "        Object.defineProperty(battery, 'charging', { get: () => true, configurable: true });"
    )
    parts.append(
        "        Object.defineProperty(battery, 'chargingTime', { get: () => 0, configurable: true });"
    )
    parts.append(
        "        Object.defineProperty(battery, 'dischargingTime', { get: () => Infinity, configurable: true });"
    )
    parts.append(
        "        Object.defineProperty(battery, 'level', { get: () => 1.0, configurable: true });"
    )
    parts.append("        return battery;")
    parts.append("      });")
    parts.append("    };")
    parts.append("  }")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 14. Intl.DateTimeFormat timezone consistency")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const originalResolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;")
    parts.append("  Intl.DateTimeFormat.prototype.resolvedOptions = function() {")
    parts.append("    const opts = originalResolvedOptions.call(this);")
    parts.append("    opts.timeZone = FP.timezone;")
    parts.append("    return opts;")
    parts.append("  };")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 15. Automation-related property cleanup")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // Remove Playwright/Puppeteer markers")
    parts.append("  delete window.__playwright;")
    parts.append("  delete window.__pw_manual;")
    parts.append("  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;")
    parts.append("  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;")
    parts.append("  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;")
    parts.append("")
    parts.append("  // Remove Selenium markers")
    parts.append("  delete window._selenium;")
    parts.append("  delete window.callSelenium;")
    parts.append("  delete window._Selenium_IDE_Recorder;")
    parts.append("")
    parts.append("  // Remove generic automation markers")
    parts.append("  const automationProps = [")
    parts.append("    'domAutomation', 'domAutomationController',")
    parts.append("    'selenium', 'webdriver', 'driver',")
    parts.append("    '_phantom', '__nightmare', 'callPhantom',")
    parts.append("    '__webdriver_evaluate', '__selenium_evaluate',")
    parts.append("    '__webdriver_script_function', '__webdriver_script_func',")
    parts.append("    '__webdriver_script_fn', '__fxdriver_evaluate',")
    parts.append("    '__driver_unwrapped', '__webdriver_unwrapped',")
    parts.append("    '__driver_evaluate', '__lastWatirAlert',")
    parts.append("    '__lastWatirConfirm', '__lastWatirPrompt',")
    parts.append("    '_Selenium_IDE_Recorder', 'calledSelenium',")
    parts.append("    '_selenium', 'callSelenium',")
    parts.append("  ];")
    parts.append("")
    parts.append("  for (const prop of automationProps) {")
    parts.append("    try {")
    parts.append("      delete window[prop];")
    parts.append("    } catch(e) {}")
    parts.append("  }")
    parts.append("")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  // 16. Error stack trace cleanup")
    parts.append("  // ──────────────────────────────────────────────────────────")
    parts.append("  const originalPrepareStackTrace = Error.prepareStackTrace;")
    parts.append("  Error.prepareStackTrace = function(error, structuredStackTrace) {")
    parts.append("    const stack = originalPrepareStackTrace")
    parts.append("      ? originalPrepareStackTrace(error, structuredStackTrace)")
    parts.append("      : structuredStackTrace;")
    parts.append("    return stack;")
    parts.append("  };")
    parts.append("")
    parts.append("})();")

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════
# Stealth Adapter
# ══════════════════════════════════════════════════════════════


class StealthAdapter:
    """
    Applies anti-bot evasion patches to Playwright browser contexts and pages.

    Generates a randomized browser fingerprint and injects JavaScript
    patches that make the automated browser indistinguishable from a
    real user session.

    Args:
        config: Browser configuration.
        fingerprint: Optional pre-built fingerprint (auto-generated if None).
        platform_category: Platform type for fingerprint generation.
        seed: Random seed for reproducible fingerprints.

    Example:
        >>> adapter = StealthAdapter(BrowserConfig(stealth=True))
        >>> await adapter.apply_to_context(context)
        >>> page = await context.new_page()
        >>> # Page is now stealth-patched
    """

    def __init__(
        self,
        config: BrowserConfig | None = None,
        fingerprint: BrowserFingerprint | None = None,
        platform_category: str = "desktop",
        seed: int | None = None,
    ):
        self._config = config or BrowserConfig()

        # Generate or use provided fingerprint
        if fingerprint:
            self._fingerprint = fingerprint
        else:
            # Determine platform category from config
            if self._config.viewport.is_mobile:
                platform_category = "mobile"
            elif self._config.viewport.has_touch and self._config.viewport.width < 1024:
                platform_category = "tablet"

            self._fingerprint = BrowserFingerprint.generate(
                platform_category=platform_category,
                locale=self._config.locale,
                timezone=self._config.timezone,
                seed=seed,
            )

        # Override user agent if set in config
        if self._config.user_agent:
            self._fingerprint.user_agent = self._config.user_agent

        # Build the injection script
        self._stealth_script = _build_stealth_script(self._fingerprint)

        # Track applied contexts/pages
        self._applied_contexts: set[int] = set()
        self._applied_pages: set[int] = set()

        logger.info(
            "StealthAdapter initialized (platform=%s, os=%s, browser=%s, chrome=%d)",
            self._fingerprint.platform_category,
            self._fingerprint.os_name,
            self._fingerprint.browser_name,
            self._fingerprint.chrome_version,
        )

    @property
    def fingerprint(self) -> BrowserFingerprint:
        """Get the current browser fingerprint."""
        return self._fingerprint

    @property
    def stealth_script(self) -> str:
        """Get the JavaScript stealth injection script."""
        return self._stealth_script

    async def apply_to_context(self, context: BrowserContext) -> None:
        """
        Apply stealth patches to a browser context.

        All pages created from this context will inherit the patches.

        Args:
            context: Playwright BrowserContext.
        """
        ctx_id = id(context)
        if ctx_id in self._applied_contexts:
            logger.debug("Stealth already applied to context %s", ctx_id)
            return

        await context.add_init_script(self._stealth_script)
        self._applied_contexts.add(ctx_id)
        logger.debug("Stealth patches applied to context %s", ctx_id)

    async def apply_to_page(self, page: Page) -> None:
        """
        Apply stealth patches to a specific page.

        Args:
            page: Playwright Page.
        """
        page_id = id(page)
        if page_id in self._applied_pages:
            logger.debug("Stealth already applied to page %s", page_id)
            return

        await page.add_init_script(self._stealth_script)
        self._applied_pages.add(page_id)
        logger.debug("Stealth patches applied to page %s", page_id)

    async def apply_to_browser(self, browser: Browser) -> None:
        """
        Apply stealth patches to all contexts in a browser.

        Note: This applies to existing contexts. New contexts
        created after this call will NOT have the patches unless
        you call apply_to_context on them.

        Args:
            browser: Playwright Browser.
        """
        for context in browser.contexts:
            await self.apply_to_context(context)
        logger.info("Stealth patches applied to %d existing contexts", len(browser.contexts))

    def reset(self) -> None:
        """Reset the adapter (clears tracking, generates new fingerprint)."""
        self._applied_contexts.clear()
        self._applied_pages.clear()
        self._fingerprint = BrowserFingerprint.generate(
            platform_category=self._fingerprint.platform_category,
            locale=self._fingerprint.language,
            timezone=self._fingerprint.timezone,
        )
        self._stealth_script = _build_stealth_script(self._fingerprint)
        logger.info("StealthAdapter reset with new fingerprint")


# ══════════════════════════════════════════════════════════════
# Convenience Functions
# ══════════════════════════════════════════════════════════════


async def apply_stealth(
    target: BrowserContext | Page | Browser,
    config: BrowserConfig | None = None,
    fingerprint: BrowserFingerprint | None = None,
    platform_category: str = "desktop",
    seed: int | None = None,
) -> StealthAdapter:
    """
    Convenience function to apply stealth patches to a target.

    Args:
        target: BrowserContext, Page, or Browser to patch.
        config: Optional browser configuration.
        fingerprint: Optional pre-built fingerprint.
        platform_category: Platform type for fingerprint generation.
        seed: Random seed for reproducible fingerprints.

    Returns:
        StealthAdapter instance (useful for accessing fingerprint).
    """
    adapter = StealthAdapter(
        config=config,
        fingerprint=fingerprint,
        platform_category=platform_category,
        seed=seed,
    )

    if hasattr(target, "new_page"):  # Browser
        await adapter.apply_to_browser(target)
    elif hasattr(target, "add_init_script"):  # Page
        await adapter.apply_to_page(target)
    elif hasattr(target, "contexts"):  # BrowserContext
        await adapter.apply_to_context(target)
    else:
        raise TypeError(f"Unsupported target type: {type(target)}")

    return adapter


def generate_fingerprint(
    platform_category: str = "desktop",
    os_name: str | None = None,
    locale: str = "en-US",
    timezone: str | None = None,
    seed: int | None = None,
) -> BrowserFingerprint:
    """
    Generate a randomized browser fingerprint.

    Args:
        platform_category: 'desktop', 'mobile', or 'tablet'.
        os_name: Force a specific OS ('Windows', 'macOS', 'Linux', 'Android', 'iOS').
        locale: Primary locale for language settings.
        timezone: Force a specific timezone.
        seed: Random seed for reproducibility.

    Returns:
        BrowserFingerprint with randomized values.
    """
    return BrowserFingerprint.generate(
        platform_category=platform_category,
        os_name=os_name,
        locale=locale,
        timezone=timezone,
        seed=seed,
    )
