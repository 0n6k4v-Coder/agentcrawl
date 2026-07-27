"""
AgentCrawl — Browser Installer
==================================

Installs and manages Playwright browsers for AgentCrawl.

Handles:
    - Chromium, Firefox, WebKit installation
    - System dependency installation (Linux)
    - Installation verification
    - Browser version reporting
    - Cleanup of unused browsers

Usage:
    # Install Chromium (default)
    python scripts/install_browsers.py

    # Install all browsers
    python scripts/install_browsers.py --all

    # Install specific browser
    python scripts/install_browsers.py --browser firefox

    # Install with system dependencies (Linux)
    python scripts/install_browsers.py --with-deps

    # Check installed browsers
    python scripts/install_browsers.py --check

    # Force reinstall
    python scripts/install_browsers.py --force

    # Uninstall a browser
    python scripts/install_browsers.py --uninstall webkit
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════

SUPPORTED_BROWSERS: list[str] = ["chromium", "firefox", "webkit"]
DEFAULT_BROWSER: str = "chromium"

# Minimum disk space required (MB)
MIN_DISK_SPACE_MB: int = 500

# Browser download sizes (approximate, MB)
BROWSER_SIZES_MB: dict[str, int] = {
    "chromium": 160,
    "firefox": 80,
    "webkit": 60,
}


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class BrowserInfo:
    """Information about an installed browser."""
    name: str
    installed: bool = False
    version: str = ""
    path: str = ""
    size_mb: float = 0.0
    executable: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "installed": self.installed,
            "version": self.version,
            "path": self.path,
            "size_mb": round(self.size_mb, 1),
        }


@dataclass
class InstallResult:
    """Result of a browser installation."""
    browser: str
    success: bool = False
    duration_s: float = 0.0
    error: str = ""
    message: str = ""


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_step(text: str) -> None:
    """Print a step message."""
    print(f"\n  → {text}")


def print_ok(text: str) -> None:
    """Print a success message."""
    print(f"  ✓ {text}")


def print_warn(text: str) -> None:
    """Print a warning message."""
    print(f"  ⚠ {text}")


def print_error(text: str) -> None:
    """Print an error message."""
    print(f"  ✗ {text}")


def check_disk_space(required_mb: int = MIN_DISK_SPACE_MB) -> bool:
    """Check if there's enough disk space."""
    try:
        total, used, free = shutil.disk_usage("/")
        free_mb = free / (1024 * 1024)
        if free_mb < required_mb:
            print_warn(
                f"Low disk space: {free_mb:.0f}MB available, "
                f"{required_mb}MB recommended"
            )
            return False
        return True
    except Exception:
        return True


def check_playwright_installed() -> bool:
    """Check if Playwright is installed."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def check_internet_connection() -> bool:
    """Basic internet connectivity check."""
    try:
        import urllib.request
        urllib.request.urlopen("https://playwright.azureedge.net", timeout=5)
        return True
    except Exception:
        try:
            urllib.request.urlopen("https://cdn.playwright.dev", timeout=5)
            return True
        except Exception:
            return False


def get_playwright_browsers_path() -> Path:
    """Get the Playwright browsers installation path."""
    # Check environment variable first
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        return Path(env_path)

    # Default location
    system = platform.system()
    home = Path.home()

    if system == "Windows":
        return home / "AppData" / "Local" / "ms-playwright"
    elif system == "Darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    else:
        return home / ".cache" / "ms-playwright"


def get_browser_size_mb(browser_path: Path) -> float:
    """Calculate the size of a browser installation in MB."""
    if not browser_path.exists():
        return 0.0

    total = 0
    for f in browser_path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size

    return total / (1024 * 1024)


# ══════════════════════════════════════════════════════════════
# Installation
# ══════════════════════════════════════════════════════════════

def install_browser(
    browser: str,
    with_deps: bool = False,
    force: bool = False,
) -> InstallResult:
    """
    Install a Playwright browser.

    Args:
        browser: Browser name ('chromium', 'firefox', 'webkit').
        with_deps: Install system dependencies (Linux only).
        force: Force reinstall even if already installed.

    Returns:
        InstallResult.
    """
    result = InstallResult(browser=browser)
    start = time.time()

    print_step(f"Installing {browser}...")

    # Build command
    cmd = [sys.executable, "-m", "playwright", "install"]

    if with_deps and platform.system() == "Linux":
        cmd.append("--with-deps")

    if force:
        cmd.append("--force")

    cmd.append(browser)

    # Run installation
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )

        result.duration_s = time.time() - start

        if proc.returncode == 0:
            result.success = True
            result.message = f"{browser} installed successfully"
            print_ok(f"{browser} installed ({result.duration_s:.1f}s)")
        else:
            result.error = proc.stderr.strip() or proc.stdout.strip()
            print_error(f"{browser} installation failed")
            if result.error:
                print(f"    {result.error[:200]}")

    except subprocess.TimeoutExpired:
        result.duration_s = time.time() - start
        result.error = "Installation timed out (600s)"
        print_error("Installation timed out")

    except FileNotFoundError:
        result.duration_s = time.time() - start
        result.error = "Playwright CLI not found"
        print_error(
            "Playwright not found. Install with: pip install playwright"
        )

    except Exception as e:
        result.duration_s = time.time() - start
        result.error = str(e)
        print_error(f"Installation error: {e}")

    return result


def install_system_deps() -> bool:
    """
    Install system dependencies for Playwright browsers (Linux only).

    Returns:
        True if successful.
    """
    if platform.system() != "Linux":
        print_warn("System dependencies are only needed on Linux")
        return True

    print_step("Installing system dependencies...")

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode == 0:
            print_ok("System dependencies installed")
            return True
        else:
            print_error("Failed to install system dependencies")
            if proc.stderr:
                print(f"    {proc.stderr[:200]}")
            return False

    except Exception as e:
        print_error(f"Error installing dependencies: {e}")
        return False


def uninstall_browser(browser: str) -> bool:
    """
    Uninstall a Playwright browser.

    Args:
        browser: Browser name.

    Returns:
        True if successful.
    """
    browsers_path = get_playwright_browsers_path()

    # Find browser directories
    browser_dirs = list(browsers_path.glob(f"{browser}-*"))

    if not browser_dirs:
        print_warn(f"{browser} is not installed")
        return True

    print_step(f"Uninstalling {browser}...")

    for browser_dir in browser_dirs:
        try:
            shutil.rmtree(browser_dir)
            print_ok(f"Removed {browser_dir.name}")
        except Exception as e:
            print_error(f"Failed to remove {browser_dir}: {e}")
            return False

    return True


# ══════════════════════════════════════════════════════════════
# Verification
# ══════════════════════════════════════════════════════════════

def check_browsers() -> list[BrowserInfo]:
    """
    Check which browsers are installed.

    Returns:
        List of BrowserInfo objects.
    """
    browsers_path = get_playwright_browsers_path()
    results: list[BrowserInfo] = []

    for browser_name in SUPPORTED_BROWSERS:
        info = BrowserInfo(name=browser_name)

        # Find browser directories
        browser_dirs = sorted(browsers_path.glob(f"{browser_name}-*"))

        if browser_dirs:
            info.installed = True
            info.path = str(browser_dirs[-1])  # Latest version

            # Extract version from directory name
            dir_name = browser_dirs[-1].name
            parts = dir_name.split("-")
            if len(parts) >= 2:
                info.version = parts[-1]

            # Calculate size
            info.size_mb = get_browser_size_mb(browser_dirs[-1])

            # Find executable
            executables = list(browser_dirs[-1].rglob(
                "chrome" if browser_name == "chromium"
                else "firefox" if browser_name == "firefox"
                else "WebKitWebProcess"
            ))
            if executables:
                info.executable = str(executables[0])

        results.append(info)

    return results


def verify_browser(browser: str) -> bool:
    """
    Verify a browser can be launched.

    Args:
        browser: Browser name.

    Returns:
        True if the browser launches successfully.
    """
    print_step(f"Verifying {browser}...")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            launcher = getattr(p, browser, None)
            if launcher is None:
                print_error(f"Unknown browser: {browser}")
                return False

            browser_instance = launcher.launch(headless=True)
            page = browser_instance.new_page()
            page.goto("about:blank")
            title = page.title()
            browser_instance.close()

            print_ok(f"{browser} verified (page title: '{title}')")
            return True

    except Exception as e:
        print_error(f"{browser} verification failed: {e}")
        return False


def print_browser_report(browsers: list[BrowserInfo]) -> None:
    """Print a formatted browser status report."""
    print_header("Installed Browsers")

    browsers_path = get_playwright_browsers_path()
    print(f"\n  Browsers path: {browsers_path}")
    print(f"  Platform: {platform.system()} {platform.machine()}")
    print()

    header = f"  {'Browser':<12} {'Status':<12} {'Version':<15} {'Size':>10}"
    print(header)
    print(f"  {'-' * 52}")

    for info in browsers:
        status = "✓ Installed" if info.installed else "✗ Missing"
        version = info.version if info.installed else "-"
        size = f"{info.size_mb:.1f} MB" if info.installed else "-"

        print(f"  {info.name:<12} {status:<12} {version:<15} {size:>10}")

    print()

    total_size = sum(b.size_mb for b in browsers if b.installed)
    installed_count = sum(1 for b in browsers if b.installed)
    print(f"  Total: {installed_count}/{len(browsers)} browsers, {total_size:.1f} MB")


# ══════════════════════════════════════════════════════════════
# Pre-flight Checks
# ══════════════════════════════════════════════════════════════

def run_preflight_checks() -> bool:
    """
    Run pre-flight checks before installation.

    Returns:
        True if all checks pass.
    """
    print_header("Pre-flight Checks")
    all_ok = True

    # Check Python version
    py_version = sys.version_info
    if py_version >= (3, 10):
        print_ok(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        print_error(f"Python 3.10+ required (found {py_version.major}.{py_version.minor})")
        all_ok = False

    # Check Playwright
    if check_playwright_installed():
        try:
            import playwright
            version = getattr(playwright, "__version__", "unknown")
            print_ok(f"Playwright installed (v{version})")
        except Exception:
            print_ok("Playwright installed")
    else:
        print_error("Playwright not installed")
        print("    Install with: pip install playwright")
        all_ok = False

    # Check disk space
    if check_disk_space():
        print_ok("Disk space OK")
    else:
        all_ok = False

    # Check internet
    if check_internet_connection():
        print_ok("Internet connection OK")
    else:
        print_warn("Could not verify internet connection")

    return all_ok


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install and manage Playwright browsers for AgentCrawl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/install_browsers.py                    # Install Chromium
  python scripts/install_browsers.py --all              # Install all browsers
  python scripts/install_browsers.py --browser firefox  # Install Firefox
  python scripts/install_browsers.py --with-deps        # Install + system deps
  python scripts/install_browsers.py --check            # Check installed browsers
  python scripts/install_browsers.py --verify           # Verify browsers work
  python scripts/install_browsers.py --uninstall webkit # Remove WebKit
        """,
    )

    parser.add_argument(
        "--browser",
        choices=SUPPORTED_BROWSERS,
        default=DEFAULT_BROWSER,
        help=f"Browser to install (default: {DEFAULT_BROWSER})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Install all supported browsers",
    )
    parser.add_argument(
        "--with-deps",
        action="store_true",
        help="Install system dependencies (Linux only)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reinstall even if already installed",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check installed browsers and exit",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify browsers can launch",
    )
    parser.add_argument(
        "--uninstall",
        choices=SUPPORTED_BROWSERS,
        help="Uninstall a browser",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip pre-flight checks",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print_header("AgentCrawl — Browser Installer")

    # Check mode
    if args.check:
        browsers = check_browsers()
        print_browser_report(browsers)
        return

    # Verify mode
    if args.verify:
        browsers_to_verify = SUPPORTED_BROWSERS if args.all else [args.browser]
        for browser in browsers_to_verify:
            verify_browser(browser)
        return

    # Uninstall mode
    if args.uninstall:
        uninstall_browser(args.uninstall)
        return

    # Pre-flight checks
    if not args.skip_checks:
        if not run_preflight_checks():
            print_error("\nPre-flight checks failed. Fix the issues above.")
            sys.exit(1)

    # Determine browsers to install
    browsers_to_install = SUPPORTED_BROWSERS if args.all else [args.browser]

    # Install system deps if requested
    if args.with_deps:
        if not install_system_deps():
            print_warn("System deps installation failed, continuing...")

    # Install browsers
    print_header(f"Installing Browsers: {', '.join(browsers_to_install)}")

    results: list[InstallResult] = []
    for browser in browsers_to_install:
        result = install_browser(
            browser=browser,
            with_deps=False,  # Deps handled separately
            force=args.force,
        )
        results.append(result)

    # Summary
    print_header("Installation Summary")

    success_count = sum(1 for r in results if r.success)
    fail_count = sum(1 for r in results if not r.success)
    total_time = sum(r.duration_s for r in results)

    for r in results:
        status = "✓" if r.success else "✗"
        print(f"  {status} {r.browser}: {r.message or r.error}")

    print(f"\n  Total: {success_count} succeeded, {fail_count} failed ({total_time:.1f}s)")

    # Post-install verification
    if success_count > 0:
        print()
        for r in results:
            if r.success:
                verify_browser(r.browser)

    # Final browser report
    print()
    browsers = check_browsers()
    print_browser_report(browsers)

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()