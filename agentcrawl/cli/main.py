"""AgentCrawl CLI — Command-line interface for AgentCrawl."""

import click
from rich.console import Console

from agentcrawl import __version__

console = Console()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="agentcrawl")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """AgentCrawl — Web Crawling & Scraping Framework for AI Agents."""
    if ctx.invoked_subcommand is None:
        console.print(f"[bold cyan]AgentCrawl v{__version__}[/bold cyan]")
        console.print("Web Crawling & Scraping Framework for AI Agents")
        console.print("\nRun [bold]agentcrawl --help[/bold] for available commands.")
        console.print(
            "\n[dim]Package Mode:[/dim]  [cyan]pip install agentcrawl[/cyan] → [green]from agentcrawl import CrawlEngine[/green]"
        )
        console.print(
            "[dim]Server Mode:[/dim]    [cyan]git clone + docker compose up[/cyan] → [green]python -m server[/green]"
        )


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
@click.option("--port", default=8000, help="Bind port (default: 8000)")
@click.option("--workers", default=1, help="Number of worker processes (default: 1)")
def serve(host: str, port: int, workers: int) -> None:
    """Start the API server."""
    try:
        from server.main import run_server
    except ImportError:
        console.print(
            "[red]Server not available.[/red]\n"
            "Option 1: [cyan]pip install -e '.[server]'[/cyan]  (from repo root)\n"
            "Option 2: [cyan]docker compose up[/cyan]",
            style="red",
        )
        raise SystemExit(1) from None
    run_server(host=host, port=port, workers=workers)


@cli.command()
def install_browsers() -> None:
    """Install Playwright browsers."""
    import asyncio
    import sys

    console.print("Installing Playwright browsers...")

    async def _install() -> tuple[int, str]:
        # Use asyncio subprocess with explicit args - no shell, no user input
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stderr.decode()

    returncode, stderr = asyncio.run(_install())
    if returncode == 0:
        console.print("[green]Browsers installed successfully![/green]")
    else:
        console.print(f"[red]Failed to install browsers:[/red]\n{stderr}")
        raise SystemExit(1) from None


@cli.command()
@click.argument("url")
@click.option(
    "--format", "output_format", default="markdown", type=click.Choice(["markdown", "html", "json"])
)
@click.option("--headless/--no-headless", default=True)
def scrape(url: str, output_format: str, headless: bool) -> None:
    """Scrape a single URL (package mode)."""
    import asyncio

    from agentcrawl.browser.config import BrowserConfig
    from agentcrawl.config.crawler_config import CrawlerConfig
    from agentcrawl.core.engine import CrawlEngine as Crawler

    async def _scrape() -> None:
        async with Crawler(browser_config=BrowserConfig(headless=headless)) as crawler:
            result = await crawler.scrape(
                url=url,
                config=CrawlerConfig(output_format=output_format),
            )
            if output_format == "json":
                import json

                console.print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            else:
                console.print(result.markdown or result.text or "")

    asyncio.run(_scrape())


@cli.command()
@click.argument("query")
@click.option("--max-results", default=5, help="Maximum results (default: 5)")
@click.option("--provider", default="duckduckgo", help="Search provider (default: duckduckgo)")
def search(query: str, max_results: int, provider: str) -> None:
    """Search the web (package mode)."""
    import asyncio

    from agentcrawl.search.engine import SearchEngine

    async def _search() -> None:
        engine = SearchEngine(provider=provider)
        response = await engine.search(query, max_results=max_results)
        results = getattr(response, "results", []) if hasattr(response, "results") else response
        for i, r in enumerate(results, 1):
            console.print(f"[bold]{i}.[/bold] [cyan]{getattr(r, 'title', '')}[/cyan]")
            console.print(f"    [dim]{getattr(r, 'url', '')}[/dim]")
            console.print(f"    {getattr(r, 'snippet', '')[:150]}...")
            console.print()

    asyncio.run(_search())


def main() -> None:
    """Entry point for agentcrawl CLI."""
    cli()


if __name__ == "__main__":
    main()
