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

import hashlib
import json
import logging
import random
import string
from dataclasses import dataclass, field
from typing import Any

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
        rng = random.Random(seed)

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
                (1920, 1080), (2560, 1440), (1366, 768),
                (1536, 864), (1440, 900), (1680, 1050),
            ]
            screen_w, screen_h = rng.choice(resolutions)
            avail_h = screen_h - rng.choice([40, 48, 80])
            dpr = rng.choice([1.0, 1.25, 1.5, 2.0])
            touch_points = 0
        elif platform_category == "mobile":
            resolutions = [
                (375, 812), (390, 844), (414, 896),
                (360, 780), (412, 915),
            ]
            screen_w, screen_h = rng.choice(resolutions)
            avail_h = screen_h
            dpr = rng.choice([2.0, 3.0])
            touch_points = rng.choice([1, 5, 10])
        else:  # tablet
            resolutions = [
                (768, 1024), (810, 1080), (834, 1194),
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
                ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
                ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
                ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
                ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
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
                ("Google Inc. (Intel)", "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630, OpenGL 4.6)"),
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

    return f"""
(() => {{
  'use strict';

  const FP = {fp_json};

  // ──────────────────────────────────────────────────────────
  // 1. Remove navigator.webdriver
  // ──────────────────────────────────────────────────────────
  Object.defineProperty(navigator, 'webdriver', {{
    get: () => undefined,
    configurable: true,
  }});

  // Also patch the prototype
  const originalDesc = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');
  if (originalDesc) {{
    Object.defineProperty(Navigator.prototype, 'webdriver', {{
      get: () => undefined,
      configurable: true,
    }});
  }}

  // ──────────────────────────────────────────────────────────
  // 2. Inject Chrome runtime object
  // ──────────────────────────────────────────────────────────
  if (!window.chrome) {{
    window.chrome = {{
      app: {{
        isInstalled: false,
        InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
        RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }},
        getDetails: () => null,
        getIsInstalled: () => false,
      }},
      runtime: {{
        OnInstalledReason: {{
          CHROME_UPDATE: 'chrome_update',
          INSTALL: 'install',
          SHARED_MODULE_UPDATE: 'shared_module_update',
          UPDATE: 'update',
        }},
        OnRestartRequiredReason: {{
          APP_UPDATE: 'app_update',
          OS_UPDATE: 'os_update',
          PERIODIC: 'periodic',
        }},
        PlatformArch: {{ ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }},
        PlatformNaclArch: {{ ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }},
        PlatformOs: {{ ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' }},
        RequestUpdateCheckStatus: {{ NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }},
        connect: function() {{ return {{ onDisconnect: {{ addListener: function() {{}} }}, onMessage: {{ addListener: function() {{}} }}, postMessage: function() {{}} }}; }},
        sendMessage: function() {{ if (arguments.length > 0 && typeof arguments[arguments.length - 1] === 'function') {{ arguments[arguments.length - 1](); }} }},
      }},
      csi: function() {{ return {{ startE: Date.now(), onloadT: Date.now() + 100, pageT: Date.now() + 100, tran: 15 }}; }},
      loadTimes: function() {{
        return {{
          commitLoadTime: Date.now() / 1000,
          connectionInfo: 'h2',
          finishDocumentLoadTime: Date.now() / 1000,
          finishLoadTime: Date.now() / 1000,
          firstPaintAfterLoadTime: 0,
          firstPaintTime: Date.now() / 1000,
          navigationType: 'Other',
          npnNegotiatedProtocol: 'h2',
          requestTime: Date.now() / 1000 - 0.16,
          startLoadTime: Date.now() / 1000 - 0.16,
          wasAlternateProtocolAvailable: false,
          wasFetchedViaSpdy: true,
          wasNpnNegotiated: true,
        }};
      }},
    }};
  }}

  // ──────────────────────────────────────────────────────────
  // 3. Spoof navigator properties
  // ──────────────────────────────────────────────────────────
  Object.defineProperty(navigator, 'platform', {{
    get: () => FP.platform,
    configurable: true,
  }});

  Object.defineProperty(navigator, 'hardwareConcurrency', {{
    get: () => FP.hardware_concurrency,
    configurable: true,
  }});

  Object.defineProperty(navigator, 'deviceMemory', {{
    get: () => FP.device_memory,
    configurable: true,
  }});

  Object.defineProperty(navigator, 'maxTouchPoints', {{
    get: () => FP.max_touch_points,
    configurable: true,
  }});

  Object.defineProperty(navigator, 'language', {{
    get: () => FP.language,
    configurable: true,
  }});

  Object.defineProperty(navigator, 'languages', {{
    get: () => Object.freeze([...FP.languages]),
    configurable: true,
  }});

  // ──────────────────────────────────────────────────────────
  // 4. Spoof plugins and MIME types
  // ──────────────────────────────────────────────────────────
  const makePlugin = (name, description, filename, mimeTypes) => {{
    const plugin = Object.create(Plugin.prototype);
    Object.defineProperties(plugin, {{
      name: {{ get: () => name, enumerable: true }},
      description: {{ get: () => description, enumerable: true }},
      filename: {{ get: () => filename, enumerable: true }},
      length: {{ get: () => mimeTypes.length, enumerable: true }},
    }});
    mimeTypes.forEach((mt, i) => {{
      Object.defineProperty(plugin, i, {{ get: () => mt, enumerable: true }});
    }});
    return plugin;
  }};

  const pdfMime = Object.create(MimeType.prototype);
  Object.defineProperties(pdfMime, {{
    type: {{ get: () => 'application/pdf', enumerable: true }},
    suffixes: {{ get: () => 'pdf', enumerable: true }},
    description: {{ get: () => 'Portable Document Format', enumerable: true }},
  }});

  const pdfxMime = Object.create(MimeType.prototype);
  Object.defineProperties(pdfxMime, {{
    type: {{ get: () => 'application/x-google-chrome-pdf', enumerable: true }},
    suffixes: {{ get: () => 'pdf', enumerable: true }},
    description: {{ get: () => 'Portable Document Format', enumerable: true }},
  }});

  const chromePlugins = [
    makePlugin('PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),
    makePlugin('Chrome PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),
    makePlugin('Chromium PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),
    makePlugin('Microsoft Edge PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),
    makePlugin('WebKit built-in PDF', 'Portable Document Format', 'internal-pdf-viewer', [pdfMime]),
  ];

  Object.defineProperty(navigator, 'plugins', {{
    get: () => {{
      const list = Object.create(PluginArray.prototype);
      chromePlugins.forEach((p, i) => {{
        Object.defineProperty(list, i, {{ get: () => p, enumerable: true }});
      }});
      Object.defineProperty(list, 'length', {{ get: () => chromePlugins.length, enumerable: true }});
      list.item = (i) => chromePlugins[i] || null;
      list.namedItem = (n) => chromePlugins.find(p => p.name === n) || null;
      list.refresh = () => {{}};
      list[Symbol.iterator] = function* () {{ yield* chromePlugins; }};
      return list;
    }},
    configurable: true,
  }});

  Object.defineProperty(navigator, 'mimeTypes', {{
    get: () => {{
      const list = Object.create(MimeTypeArray.prototype);
      const mimes = [pdfMime, pdfxMime];
      mimes.forEach((m, i) => {{
        Object.defineProperty(list, i, {{ get: () => m, enumerable: true }});
      }});
      Object.defineProperty(list, 'length', {{ get: () => mimes.length, enumerable: true }});
      list.item = (i) => mimes[i] || null;
      list.namedItem = (n) => mimes.find(m => m.type === n) || null;
      list[Symbol.iterator] = function* () {{ yield* mimes; }};
      return list;
    }},
    configurable: true,
  }});

  // ──────────────────────────────────────────────────────────
  // 5. WebGL fingerprint spoofing
  // ──────────────────────────────────────────────────────────
  const getParameterProxy = (originalFn, vendor, renderer) => {{
    return function(param) {{
      const UNMASKED_VENDOR = 37445;
      const UNMASKED_RENDERER = 37446;
      if (param === UNMASKED_VENDOR) return vendor;
      if (param === UNMASKED_RENDERER) return renderer;
      return originalFn.call(this, param);
    }};
  }};

  const patchWebGL = (proto) => {{
    if (!proto) return;
    const originalGetParam = proto.getParameter;
    proto.getParameter = getParameterProxy(
      originalGetParam,
      FP.webgl_vendor,
      FP.webgl_renderer
    );
  }};

  patchWebGL(WebGLRenderingContext.prototype);
  if (typeof WebGL2RenderingContext !== 'undefined') {{
    patchWebGL(WebGL2RenderingContext.prototype);
  }}

  // ──────────────────────────────────────────────────────────
  // 6. Canvas fingerprint noise
  // ──────────────────────────────────────────────────────────
  const CANVAS_SEED = FP.canvas_noise_seed;

  const seededRandom = (seed) => {{
    let s = seed;
    return () => {{
      s = (s * 16807 + 0) % 2147483647;
      return (s - 1) / 2147483646;
    }};
  }};

  const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(type, quality) {{
    const ctx = this.getContext('2d');
    if (ctx && this.width > 16 && this.height > 16) {{
      try {{
        const imageData = ctx.getImageData(0, 0, Math.min(this.width, 4), Math.min(this.height, 4));
        const rng = seededRandom(CANVAS_SEED);
        for (let i = 0; i < imageData.data.length; i += 4) {{
          imageData.data[i] = imageData.data[i] ^ (Math.floor(rng() * 2));
        }}
        ctx.putImageData(imageData, 0, 0);
      }} catch(e) {{}}
    }}
    return originalToDataURL.call(this, type, quality);
  }};

  const originalToBlob = HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob = function(callback, type, quality) {{
    const ctx = this.getContext('2d');
    if (ctx && this.width > 16 && this.height > 16) {{
      try {{
        const imageData = ctx.getImageData(0, 0, Math.min(this.width, 4), Math.min(this.height, 4));
        const rng = seededRandom(CANVAS_SEED + 1);
        for (let i = 0; i < imageData.data.length; i += 4) {{
          imageData.data[i] = imageData.data[i] ^ (Math.floor(rng() * 2));
        }}
        ctx.putImageData(imageData, 0, 0);
      }} catch(e) {{}}
    }}
    return originalToBlob.call(this, callback, type, quality);
  }};

  const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
    const imageData = originalGetImageData.apply(this, args);
    const rng = seededRandom(CANVAS_SEED + 2);
    for (let i = 0; i < imageData.data.length; i += 4) {{
      imageData.data[i] = imageData.data[i] ^ (Math.floor(rng() * 2));
    }}
    return imageData;
  }};

  // ──────────────────────────────────────────────────────────
  // 7. AudioContext fingerprint noise
  // ──────────────────────────────────────────────────────────
  const AUDIO_SEED = FP.audio_noise_seed;

  if (typeof AudioContext !== 'undefined' || typeof webkitAudioContext !== 'undefined') {{
    const AudioCtx = typeof AudioContext !== 'undefined' ? AudioContext : webkitAudioContext;

    const originalCreateOscillator = AudioCtx.prototype.createOscillator;
    const originalCreateDynamicsCompressor = AudioCtx.prototype.createDynamicsCompressor;

    const originalGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(channel) {{
      const data = originalGetChannelData.call(this, channel);
      const rng = seededRandom(AUDIO_SEED + channel);
      for (let i = 0; i < data.length; i += 100) {{
        data[i] = data[i] + (rng() - 0.5) * 0.0001;
      }}
      return data;
    }};
  }}

  // ──────────────────────────────────────────────────────────
  // 8. Screen properties
  // ──────────────────────────────────────────────────────────
  Object.defineProperty(screen, 'width', {{ get: () => FP.screen_width, configurable: true }});
  Object.defineProperty(screen, 'height', {{ get: () => FP.screen_height, configurable: true }});
  Object.defineProperty(screen, 'availWidth', {{ get: () => FP.screen_avail_width, configurable: true }});
  Object.defineProperty(screen, 'availHeight', {{ get: () => FP.screen_avail_height, configurable: true }});
  Object.defineProperty(screen, 'colorDepth', {{ get: () => FP.color_depth, configurable: true }});
  Object.defineProperty(screen, 'pixelDepth', {{ get: () => FP.pixel_depth, configurable: true }});

  Object.defineProperty(window, 'devicePixelRatio', {{
    get: () => FP.device_pixel_ratio,
    configurable: true,
  }});

  // ──────────────────────────────────────────────────────────
  // 9. Permissions API patch
  // ──────────────────────────────────────────────────────────
  if (navigator.permissions) {{
    const originalQuery = navigator.permissions.query;
    navigator.permissions.query = function(descriptor) {{
      if (descriptor.name === 'notifications') {{
        return Promise.resolve({{ state: Notification.permission }});
      }}
      return originalQuery.call(this, descriptor);
    }};
  }}

  // ──────────────────────────────────────────────────────────
  // 10. iframe contentWindow fix
  // ──────────────────────────────────────────────────────────
  const originalAttachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function(init) {{
    return originalAttachShadow.call(this, {{ ...init, mode: 'open' }});
  }};

  // Patch HTMLIFrameElement contentWindow
  const iframeProto = HTMLIFrameElement.prototype;
  const originalContentWindow = Object.getOwnPropertyDescriptor(iframeProto, 'contentWindow');
  if (originalContentWindow && originalContentWindow.get) {{
    Object.defineProperty(iframeProto, 'contentWindow', {{
      get: function() {{
        const win = originalContentWindow.get.call(this);
        if (win) {{
          try {{
            if (!win.chrome) {{
              win.chrome = window.chrome;
            }}
          }} catch(e) {{}}
        }}
        return win;
      }},
      configurable: true,
    }});
  }}

  // ──────────────────────────────────────────────────────────
  // 11. Function.toString() protection
  // ──────────────────────────────────────────────────────────
  const originalToString = Function.prototype.toString;
  const nativeCodeRegex = /^function\\s+\\w+\\(\\)\\s*\\{\\s*\\[native code\\]\\s*\\}$/;

  const patchedFunctions = new Map();

  const registerNative = (obj, prop, originalName) => {{
    const fn = obj[prop];
    if (typeof fn === 'function') {{
      patchedFunctions.set(fn, `function ${{originalName || prop}}() {{ [native code] }}`);
    }}
  }};

  Function.prototype.toString = function() {{
    if (patchedFunctions.has(this)) {{
      return patchedFunctions.get(this);
    }}
    return originalToString.call(this);
  }};

  patchedFunctions.set(Function.prototype.toString, 'function toString() { [native code] }');

  // Register key patched functions as "native"
  registerNative(navigator, 'webdriver', 'get webdriver');
  registerNative(navigator, 'plugins', 'get plugins');
  registerNative(navigator, 'mimeTypes', 'get mimeTypes');
  registerNative(navigator, 'languages', 'get languages');
  registerNative(navigator, 'hardwareConcurrency', 'get hardwareConcurrency');
  registerNative(navigator, 'deviceMemory', 'get deviceMemory');
  registerNative(screen, 'width', 'get width');
  registerNative(screen, 'height', 'get height');
  registerNative(window, 'devicePixelRatio', 'get devicePixelRatio');

  // ──────────────────────────────────────────────────────────
  // 12. NetworkInformation spoofing
  // ──────────────────────────────────────────────────────────
  if (navigator.connection) {{
    Object.defineProperty(navigator.connection, 'rtt', {{
      get: () => 50,
      configurable: true,
    }});
    Object.defineProperty(navigator.connection, 'downlink', {{
      get: () => 10,
      configurable: true,
    }});
    Object.defineProperty(navigator.connection, 'effectiveType', {{
      get: () => '4g',
      configurable: true,
    }});
  }}

  // ──────────────────────────────────────────────────────────
  // 13. Battery API spoofing
  // ──────────────────────────────────────────────────────────
  if (navigator.getBattery) {{
    const originalGetBattery = navigator.getBattery;
    navigator.getBattery = function() {{
      return originalGetBattery.call(this).then(battery => {{
        Object.defineProperty(battery, 'charging', {{ get: () => true, configurable: true }});
        Object.defineProperty(battery, 'chargingTime', {{ get: () => 0, configurable: true }});
        Object.defineProperty(battery, 'dischargingTime', {{ get: () => Infinity, configurable: true }});
        Object.defineProperty(battery, 'level', {{ get: () => 1.0, configurable: true }});
        return battery;
      }});
    }};
  }}

  // ──────────────────────────────────────────────────────────
  // 14. Intl.DateTimeFormat timezone consistency
  // ──────────────────────────────────────────────────────────
  const originalResolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;
  Intl.DateTimeFormat.prototype.resolvedOptions = function() {{
    const opts = originalResolvedOptions.call(this);
    opts.timeZone = FP.timezone;
    return opts;
  }};

  // ──────────────────────────────────────────────────────────
  // 15. Automation-related property cleanup
  // ──────────────────────────────────────────────────────────
  // Remove Playwright/Puppeteer markers
  delete window.__playwright;
  delete window.__pw_manual;
  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
  delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

  // Remove Selenium markers
  delete window._selenium;
  delete window.callSelenium;
  delete window._Selenium_IDE_Recorder;

  // Remove generic automation markers
  const automationProps = [
    'domAutomation', 'domAutomationController',
    'selenium', 'webdriver', 'driver',
    '_phantom', '__nightmare', 'callPhantom',
    '__webdriver_evaluate', '__selenium_evaluate',
    '__webdriver_script_function', '__webdriver_script_func',
    '__webdriver_script_fn', '__fxdriver_evaluate',
    '__driver_unwrapped', '__webdriver_unwrapped',
    '__driver_evaluate', '__lastWatirAlert',
    '__lastWatirConfirm', '__lastWatirPrompt',
    '_Selenium_IDE_Recorder', 'calledSelenium',
    '_selenium', 'callSelenium',
  ];

  for (const prop of automationProps) {{
    try {{
      delete window[prop];
    }} catch(e) {{}}
  }}

  // ──────────────────────────────────────────────────────────
  // 16. Error stack trace cleanup
  // ──────────────────────────────────────────────────────────
  const originalPrepareStackTrace = Error.prepareStackTrace;
  Error.prepareStackTrace = function(error, structuredStackTrace) {{
    const stack = originalPrepareStackTrace
      ? originalPrepareStackTrace(error, structuredStackTrace)
      : structuredStackTrace;
    return stack;
  }};

}})();
"""


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

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def fingerprint(self) -> BrowserFingerprint:
        """The current browser fingerprint."""
        return self._fingerprint

    @property
    def stealth_script(self) -> str:
        """The JavaScript injection script."""
        return self._stealth_script

    @property
    def user_agent(self) -> str:
        """The spoofed User-Agent string."""
        return self._fingerprint.user_agent

    # ──────────────────────────────────────────────────────────
    # Application Methods
    # ──────────────────────────────────────────────────────────

    async def apply_to_context(self, context: Any) -> None:
        """
        Apply stealth patches to a browser context.

        All pages created within this context will automatically
        have the stealth script injected before any page JavaScript.

        Args:
            context: Playwright BrowserContext instance.
        """
        ctx_id = id(context)
        if ctx_id in self._applied_contexts:
            return

        # Inject init script (runs before page JS on every navigation)
        await context.add_init_script(self._stealth_script)

        # Set user agent at context level
        # (Note: Playwright doesn't allow changing UA after context creation,
        #  so this is handled via context options in BrowserManager)

        self._applied_contexts.add(ctx_id)
        logger.debug("Stealth applied to context %d", ctx_id)

    async def apply_to_page(self, page: Any) -> None:
        """
        Apply stealth patches to a single page.

        Use this for pages created outside of a stealth-patched context.

        Args:
            page: Playwright Page instance.
        """
        page_id = id(page)
        if page_id in self._applied_pages:
            return

        # Add init script for future navigations
        await page.add_init_script(self._stealth_script)

        # Execute immediately for current page state
        try:
            await page.evaluate(self._stealth_script)
        except Exception as e:
            logger.debug("Could not evaluate stealth script on current page: %s", e)

        self._applied_pages.add(page_id)
        logger.debug("Stealth applied to page %d", page_id)

    async def apply_to_page_on_navigation(self, page: Any) -> None:
        """
        Register stealth injection on every navigation event.

        This ensures patches are re-applied after SPA navigations
        or page reloads.

        Args:
            page: Playwright Page instance.
        """
        async def _on_frame_navigated(frame: Any) -> None:
            if frame == page.main_frame:
                try:
                    await page.evaluate(self._stealth_script)
                except Exception:
                    pass

        page.on("framenavigated", _on_frame_navigated)
        await self.apply_to_page(page)

    # ──────────────────────────────────────────────────────────
    # Fingerprint Management
    # ──────────────────────────────────────────────────────────

    def regenerate_fingerprint(
        self,
        platform_category: str | None = None,
        os_name: str | None = None,
        seed: int | None = None,
    ) -> BrowserFingerprint:
        """
        Generate a new random fingerprint and rebuild the injection script.

        Args:
            platform_category: Override platform category.
            os_name: Override OS name.
            seed: Random seed for reproducibility.

        Returns:
            The new BrowserFingerprint.
        """
        category = platform_category or self._fingerprint.platform_category
        os = os_name or self._fingerprint.os_name

        self._fingerprint = BrowserFingerprint.generate(
            platform_category=category,
            os_name=os,
            locale=self._config.locale,
            timezone=self._config.timezone,
            seed=seed,
        )

        if self._config.user_agent:
            self._fingerprint.user_agent = self._config.user_agent

        self._stealth_script = _build_stealth_script(self._fingerprint)

        # Clear applied tracking (new script needs re-application)
        self._applied_contexts.clear()
        self._applied_pages.clear()

        logger.info(
            "Fingerprint regenerated (platform=%s, os=%s)",
            self._fingerprint.platform_category,
            self._fingerprint.os_name,
        )

        return self._fingerprint

    def get_context_options_override(self) -> dict[str, Any]:
        """
        Get context options that should be set for fingerprint consistency.

        These options should be merged into BrowserConfig.to_context_options()
        to ensure the browser-level settings match the injected fingerprint.

        Returns:
            Dictionary of Playwright context options.
        """
        return {
            "userAgent": self._fingerprint.user_agent,
            "locale": self._fingerprint.language,
            "timezoneId": self._fingerprint.timezone,
            "viewport": {
                "width": self._fingerprint.screen_width,
                "height": self._fingerprint.screen_height,
            },
            "deviceScaleFactor": self._fingerprint.device_pixel_ratio,
            "isMobile": self._fingerprint.platform_category == "mobile",
            "hasTouch": self._fingerprint.max_touch_points > 0,
            "colorScheme": "light",
        }

    # ──────────────────────────────────────────────────────────
    # Verification
    # ──────────────────────────────────────────────────────────

    async def verify(self, page: Any) -> dict[str, Any]:
        """
        Verify that stealth patches are active on a page.

        Navigates to a test page and checks key indicators.

        Args:
            page: Playwright Page instance (should already have stealth applied).

        Returns:
            Dictionary of verification results.
        """
        results: dict[str, Any] = {}

        try:
            # Check navigator.webdriver
            webdriver = await page.evaluate("() => navigator.webdriver")
            results["webdriver_undefined"] = webdriver is None or webdriver is False

            # Check chrome runtime
            has_chrome = await page.evaluate("() => !!window.chrome")
            results["chrome_runtime"] = has_chrome

            # Check plugins
            plugin_count = await page.evaluate("() => navigator.plugins.length")
            results["plugins_count"] = plugin_count
            results["plugins_present"] = plugin_count > 0

            # Check platform
            platform = await page.evaluate("() => navigator.platform")
            results["platform"] = platform
            results["platform_matches"] = platform == self._fingerprint.platform

            # Check hardware concurrency
            hw = await page.evaluate("() => navigator.hardwareConcurrency")
            results["hardware_concurrency"] = hw
            results["hw_matches"] = hw == self._fingerprint.hardware_concurrency

            # Check languages
            langs = await page.evaluate("() => navigator.languages")
            results["languages"] = langs
            results["languages_match"] = langs == self._fingerprint.languages

            # Check WebGL
            webgl_vendor = await page.evaluate("""() => {
                try {
                    const canvas = document.createElement('canvas');
                    const gl = canvas.getContext('webgl');
                    if (!gl) return null;
                    const ext = gl.getExtension('WEBGL_debug_renderer_info');
                    if (!ext) return null;
                    return gl.getParameter(ext.UNMASKED_VENDOR_WEBGL);
                } catch(e) { return null; }
            }""")
            results["webgl_vendor"] = webgl_vendor
            results["webgl_spoofed"] = webgl_vendor == self._fingerprint.webgl_vendor

            # Check screen
            screen_w = await page.evaluate("() => screen.width")
            results["screen_width"] = screen_w
            results["screen_matches"] = screen_w == self._fingerprint.screen_width

            # Check Function.toString protection
            to_string_native = await page.evaluate("""() => {
                return navigator.hardwareConcurrency.toString !== undefined;
            }""")
            results["function_tostring_patched"] = to_string_native

            # Overall
            checks = [
                results.get("webdriver_undefined", False),
                results.get("chrome_runtime", False),
                results.get("plugins_present", False),
                results.get("platform_matches", False),
                results.get("hw_matches", False),
            ]
            results["overall_pass"] = all(checks)
            results["score"] = f"{sum(checks)}/{len(checks)}"

        except Exception as e:
            results["error"] = str(e)
            results["overall_pass"] = False

        return results

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize adapter state."""
        return {
            "fingerprint": self._fingerprint.to_dict(),
            "applied_contexts": len(self._applied_contexts),
            "applied_pages": len(self._applied_pages),
            "script_length": len(self._stealth_script),
        }

    def __repr__(self) -> str:
        return (
            f"StealthAdapter(platform={self._fingerprint.platform_category}, "
            f"os={self._fingerprint.os_name}, "
            f"chrome={self._fingerprint.chrome_version})"
        )