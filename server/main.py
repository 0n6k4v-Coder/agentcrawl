"""
AgentCrawl — Server Entry Point
===================================

Main entry point for running the AgentCrawl REST API server.

Usage:
    # CLI
    agentcrawl serve --port 8000

    # Direct
    python -m agentcrawl.server.main --port 8000

    # Uvicorn
    uvicorn agentcrawl.server.app:app --host 0.0.0.0 --port 8000

Options:
    --host          Bind host (default: 0.0.0.0)
    --port          Bind port (default: 8000)
    --workers       Number of worker processes (default: 1)
    --api-key       API key for authentication
    --log-level     Log level (default: info)
    --reload        Enable auto-reload (development)
    --no-banner     Suppress startup banner
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

# ══════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════

BANNER = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   █████╗  ██████╗ ███████╗███╗   ██╗████████╗             ║
║  ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝             ║
║  ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║                ║
║  ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║                ║
║  ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║                ║
║  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝                ║
║         C R A W L   —   A I   A G E N T S                 ║
║                                                           ║
║  Web Crawling & Scraping Framework for AI Agents          ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"""


def print_banner(
    host: str,
    port: int,
    workers: int,
    version: str,
) -> None:
    """Print the startup banner."""
    print(BANNER)
    print(f"  Version:  {version}")
    print(f"  Server:   http://{host}:{port}")
    print(f"  Docs:     http://{host}:{port}/docs")
    print(f"  Health:   http://{host}:{port}/health")
    print(f"  Workers:  {workers}")
    print()


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════


def load_settings(args: argparse.Namespace) -> Any:
    """
    Load Settings from CLI args and environment.

    CLI args take priority over environment variables.
    """
    from agentcrawl.config.settings import Settings

    # Build overrides from CLI args
    overrides: dict[str, Any] = {}

    if args.host:
        overrides["host"] = args.host
    if args.port:
        overrides["port"] = args.port
    if args.workers:
        overrides["workers"] = args.workers
    if args.api_key:
        overrides["api_key"] = args.api_key
    if args.log_level:
        overrides["log_level"] = args.log_level

    return Settings(**overrides)


# ══════════════════════════════════════════════════════════════
# Server Runner
# ══════════════════════════════════════════════════════════════


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    workers: int = 1,
    reload: bool = False,
    log_level: str = "info",
    api_key: str = "",
    no_banner: bool = False,
) -> None:
    """
    Run the AgentCrawl server with uvicorn.

    Args:
        host: Bind host.
        port: Bind port.
        workers: Number of worker processes.
        reload: Enable auto-reload (development only).
        log_level: Uvicorn log level.
        api_key: API key for authentication.
        no_banner: Suppress startup banner.
    """
    import uvicorn

    # Set environment variables for the app
    if api_key:
        os.environ["AGENTCRAWL_API_KEY"] = api_key

    os.environ["AGENTCRAWL_HOST"] = host
    os.environ["AGENTCRAWL_PORT"] = str(port)
    os.environ["AGENTCRAWL_WORKERS"] = str(workers)
    os.environ["AGENTCRAWL_LOG_LEVEL"] = log_level

    # Print banner
    if not no_banner:
        version = _get_version()
        print_banner(host, port, workers, version)

    # Configure uvicorn
    uvicorn_kwargs: dict[str, Any] = {
        "app": "server.app:app",
        "host": host,
        "port": port,
        "log_level": log_level,
        "access_log": True,
        "timeout_keep_alive": 65,
        "limit_concurrency": 100,
    }

    if reload:
        uvicorn_kwargs["reload"] = True
        uvicorn_kwargs["reload_dirs"] = ["agentcrawl"]
        if workers > 1:
            print("  ⚠ Reload mode: forcing workers=1")
            workers = 1

    if workers > 1 and not reload:
        uvicorn_kwargs["workers"] = workers

    # Run
    try:
        uvicorn.run(**uvicorn_kwargs)
    except KeyboardInterrupt:
        print("\n  Server stopped by user")
    except Exception as e:
        print(f"\n  Server error: {e}")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="agentcrawl-serve",
        description="AgentCrawl REST API Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  agentcrawl serve
  agentcrawl serve --port 9000
  agentcrawl serve --workers 4 --api-key "secret"
  agentcrawl serve --reload --log-level debug
  python -m agentcrawl.server.main --port 8000
        """,
    )

    parser.add_argument(
        "--host",
        default=os.environ.get("AGENTCRAWL_HOST", "127.0.0.1"),
        help="Bind host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AGENTCRAWL_PORT", "8000")),
        help="Bind port (default: 8000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("AGENTCRAWL_WORKERS", "1")),
        help="Number of worker processes (default: 1)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("AGENTCRAWL_API_KEY", ""),
        help="API key for authentication",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default=os.environ.get("AGENTCRAWL_LOG_LEVEL", "info"),
        help="Log level (default: info)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development only)",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Suppress startup banner",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AgentCrawl {_get_version()}",
    )

    return parser.parse_args()


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════


def _get_version() -> str:
    """Get the AgentCrawl version."""
    try:
        import agentcrawl

        return agentcrawl.__version__
    except Exception:
        return "1.0.0"


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════


def main() -> None:
    """Main entry point."""
    args = parse_args()

    run_server(
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        log_level=args.log_level,
        api_key=args.api_key,
        no_banner=args.no_banner,
    )


if __name__ == "__main__":
    main()
