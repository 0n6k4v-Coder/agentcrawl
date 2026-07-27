"""
AgentCrawl — REST API Client Examples
=========================================

Examples of interacting with the AgentCrawl REST API server
using httpx (async HTTP client).

Prerequisites:
    pip install httpx

    # Start the server first:
    agentcrawl serve --port 8000

Run:
    python examples/server_mode/api_client.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:
    print("httpx is required. Install with: pip install httpx")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

BASE_URL = "http://localhost:8000"
API_KEY = ""  # Set if server requires auth

HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
}

if API_KEY:
    HEADERS["Authorization"] = f"Bearer {API_KEY}"


# ══════════════════════════════════════════════════════════════
# Client Class
# ══════════════════════════════════════════════════════════════

class AgentCrawlClient:
    """
    Async HTTP client for the AgentCrawl REST API.

    Args:
        base_url: Server base URL.
        api_key: API key for authentication.
        timeout: Request timeout in seconds.

    Example:
        >>> client = AgentCrawlClient("http://localhost:8000")
        >>> result = await client.scrape("https://example.com")
        >>> print(result["markdown"])
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        api_key: str = "",
        timeout: float = 60.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    # ──────────────────────────────────────────────────────────
    # Health
    # ──────────────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Check server health."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────────────────────
    # Scrape
    # ──────────────────────────────────────────────────────────

    async def scrape(
        self,
        url: str,
        output_format: str = "markdown",
        include_links: bool = True,
        include_metadata: bool = True,
        only_main_content: bool = True,
        content_filter: str = "none",
        chunker: str = "none",
        actions: list[dict] | None = None,
        cache: bool = True,
    ) -> dict[str, Any]:
        """
        Scrape a single page.

        Args:
            url: URL to scrape.
            output_format: Output format.
            include_links: Include links.
            include_metadata: Include metadata.
            only_main_content: Only main content.
            content_filter: Content filter type.
            chunker: Chunker type.
            actions: Page actions.
            cache: Enable caching.

        Returns:
            Scrape result dictionary.
        """
        payload: dict[str, Any] = {
            "url": url,
            "output_format": output_format,
            "include_links": include_links,
            "include_metadata": include_metadata,
            "only_main_content": only_main_content,
            "content_filter": content_filter,
            "chunker": chunker,
            "cache": cache,
        }

        if actions:
            payload["actions"] = actions

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/scrape",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────────────────────
    # Crawl
    # ──────────────────────────────────────────────────────────

    async def crawl(
        self,
        url: str,
        strategy: str = "bfs",
        max_depth: int = 3,
        max_pages: int = 50,
        output_format: str = "markdown",
    ) -> dict[str, Any]:
        """
        Start a crawl job.

        Returns:
            Job info with job_id.
        """
        payload = {
            "url": url,
            "strategy": strategy,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "output_format": output_format,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/crawl",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_crawl_status(self, job_id: str) -> dict[str, Any]:
        """Get crawl job status."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self._base_url}/crawl/{job_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def wait_for_crawl(
        self,
        job_id: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        """
        Wait for a crawl job to complete.

        Args:
            job_id: Job ID.
            poll_interval: Seconds between status checks.
            timeout: Maximum wait time.

        Returns:
            Final job result.
        """
        start = time.time()

        while time.time() - start < timeout:
            status = await self.get_crawl_status(job_id)

            if status.get("status") in ("completed", "failed", "cancelled"):
                return status

            pages = status.get("pages_crawled", 0)
            total = status.get("total_pages", "?")
            print(f"    Progress: {pages}/{total} pages...")

            await asyncio.sleep(poll_interval)

        raise TimeoutError(f"Crawl job {job_id} timed out after {timeout}s")

    async def cancel_crawl(self, job_id: str) -> dict[str, Any]:
        """Cancel a running crawl job."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{self._base_url}/crawl/{job_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────────────────────
    # Map
    # ──────────────────────────────────────────────────────────

    async def map(
        self,
        url: str,
        max_urls: int = 500,
        use_sitemap: bool = True,
    ) -> dict[str, Any]:
        """Discover URLs on a website."""
        payload = {
            "url": url,
            "max_urls": max_urls,
            "use_sitemap": use_sitemap,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/map",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = 5,
        provider: str = "duckduckgo",
    ) -> dict[str, Any]:
        """Search the web."""
        payload = {
            "query": query,
            "max_results": max_results,
            "provider": provider,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/search",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────────────────────
    # Extract
    # ──────────────────────────────────────────────────────────

    async def extract(
        self,
        url: str,
        schema: dict[str, Any],
        method: str = "css",
    ) -> dict[str, Any]:
        """Extract structured data from a URL."""
        payload = {
            "url": url,
            "schema": schema,
            "method": method,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/extract",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    # ──────────────────────────────────────────────────────────
    # Batch
    # ──────────────────────────────────────────────────────────

    async def batch_scrape(
        self,
        urls: list[str],
        output_format: str = "markdown",
        max_concurrent: int = 5,
    ) -> dict[str, Any]:
        """Scrape multiple URLs."""
        payload = {
            "urls": urls,
            "output_format": output_format,
            "max_concurrent": max_concurrent,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url}/batch/scrape",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()


# ══════════════════════════════════════════════════════════════
# Examples
# ══════════════════════════════════════════════════════════════

async def example_health() -> None:
    """Check server health."""
    print("\n[1] Health Check")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        health = await client.health()
        print(f"  Status: {health.get('status')}")
        print(f"  Version: {health.get('version')}")
        print(f"  Uptime: {health.get('uptime_seconds', 0):.0f}s")
        print(f"  Browser: {health.get('browser_connected')}")
    except httpx.ConnectError:
        print("  ✗ Server not running. Start with: agentcrawl serve")


async def example_scrape() -> None:
    """Scrape a single page."""
    print("\n[2] Scrape")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        result = await client.scrape(
            "https://example.com",
            include_links=True,
            include_metadata=True,
        )

        print(f"  URL: {result.get('url')}")
        print(f"  Status: {result.get('status_code')}")
        print(f"  Words: {result.get('word_count')}")
        print(f"  Time: {result.get('response_time_ms', 0):.0f}ms")
        print(f"  Cached: {result.get('cached')}")
        print(f"  Markdown:\n{result.get('markdown', '')[:300]}")

    except httpx.ConnectError:
        print("  ✗ Server not running")


async def example_scrape_with_actions() -> None:
    """Scrape with page actions."""
    print("\n[3] Scrape with Actions")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        result = await client.scrape(
            "https://example.com",
            actions=[
                {"type": "wait", "milliseconds": 1000},
                {"type": "scroll", "direction": "down", "amount": 2},
            ],
        )

        print(f"  Success: {result.get('success')}")
        print(f"  Words: {result.get('word_count')}")

    except httpx.ConnectError:
        print("  ✗ Server not running")


async def example_crawl() -> None:
    """Start a crawl job and wait for completion."""
    print("\n[4] Crawl Job")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        # Start crawl
        job = await client.crawl(
            "https://example.com",
            strategy="bfs",
            max_depth=1,
            max_pages=3,
        )

        job_id = job.get("job_id", "")
        print(f"  Job ID: {job_id}")
        print(f"  Status: {job.get('status')}")

        # Wait for completion
        if job_id:
            print("\n  Waiting for completion...")
            result = await client.wait_for_crawl(job_id, poll_interval=1.0, timeout=60)

            print(f"  Final status: {result.get('status')}")
            print(f"  Pages: {result.get('total_pages', 0)}")
            print(f"  Words: {result.get('total_words', 0)}")

    except httpx.ConnectError:
        print("  ✗ Server not running")
    except TimeoutError as e:
        print(f"  ✗ {e}")


async def example_map() -> None:
    """Discover URLs on a website."""
    print("\n[5] Map (URL Discovery)")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        result = await client.map("https://example.com", max_urls=20)

        print(f"  Total URLs: {result.get('total_urls', 0)}")
        print(f"  Duration: {result.get('duration_ms', 0):.0f}ms")

        urls = result.get("urls", [])
        for url in urls[:5]:
            print(f"    • {url}")

    except httpx.ConnectError:
        print("  ✗ Server not running")


async def example_search() -> None:
    """Search the web."""
    print("\n[6] Search")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        result = await client.search("python asyncio tutorial", max_results=5)

        print(f"  Query: {result.get('query')}")
        print(f"  Results: {len(result.get('results', []))}")

        for r in result.get("results", [])[:3]:
            print(f"\n  • {r.get('title', 'N/A')}")
            print(f"    {r.get('url', '')}")

    except httpx.ConnectError:
        print("  ✗ Server not running")


async def example_extract() -> None:
    """Extract structured data."""
    print("\n[7] Extract")
    print("-" * 45)

    client = AgentCrawlClient()

    schema = {
        "name": "Page Info",
        "fields": [
            {"name": "title", "selector": "h1", "type": "text"},
            {"name": "link", "selector": "a", "type": "attribute", "attribute": "href"},
        ],
    }

    try:
        result = await client.extract(
            "https://example.com",
            schema=schema,
            method="css",
        )

        print(f"  Success: {result.get('success')}")
        print(f"  Data: {json.dumps(result.get('data', {}), indent=4)}")

    except httpx.ConnectError:
        print("  ✗ Server not running")


async def example_batch() -> None:
    """Batch scrape multiple URLs."""
    print("\n[8] Batch Scrape")
    print("-" * 45)

    client = AgentCrawlClient()

    urls = [
        "https://example.com",
        "https://www.iana.org/domains/example",
    ]

    try:
        result = await client.batch_scrape(urls, max_concurrent=2)

        print(f"  Total: {result.get('total', 0)}")
        print(f"  Successful: {result.get('successful', 0)}")
        print(f"  Failed: {result.get('failed', 0)}")
        print(f"  Duration: {result.get('duration_ms', 0):.0f}ms")

        for r in result.get("results", []):
            status = "✓" if r.get("success") else "✗"
            print(f"    {status} {r.get('url')} ({r.get('word_count', 0)} words)")

    except httpx.ConnectError:
        print("  ✗ Server not running")


async def example_error_handling() -> None:
    """Handle API errors."""
    print("\n[9] Error Handling")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        # Scrape a non-existent page
        result = await client.scrape("https://this-domain-does-not-exist-12345.com")
        print(f"  Success: {result.get('success')}")
        print(f"  Error: {result.get('error')}")

    except httpx.HTTPStatusError as e:
        print(f"  HTTP Error: {e.response.status_code}")
        print(f"  Body: {e.response.text[:200]}")

    except httpx.ConnectError:
        print("  ✗ Server not running")


async def example_full_workflow() -> None:
    """Complete workflow: search → scrape → extract."""
    print("\n[10] Full Workflow")
    print("-" * 45)

    client = AgentCrawlClient()

    try:
        # Step 1: Health check
        print("  Step 1: Health check")
        health = await client.health()
        print(f"    Server: {health.get('status')}")

        # Step 2: Search
        print("\n  Step 2: Search")
        search_result = await client.search("python documentation", max_results=3)
        results = search_result.get("results", [])
        print(f"    Found {len(results)} results")

        # Step 3: Scrape first result
        if results:
            url = results[0].get("url", "")
            print(f"\n  Step 3: Scrape {url}")
            scrape_result = await client.scrape(url)
            print(f"    Words: {scrape_result.get('word_count', 0)}")
            print(f"    Title: {scrape_result.get('metadata', {}).get('title', 'N/A')}")

        # Step 4: Map
        print("\n  Step 4: Map")
        map_result = await client.map("https://example.com", max_urls=10)
        print(f"    URLs found: {map_result.get('total_urls', 0)}")

        print("\n  ✓ Workflow completed")

    except httpx.ConnectError:
        print("  ✗ Server not running")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

async def main() -> None:
    """Run all examples."""
    print("=" * 55)
    print("  AgentCrawl — REST API Client Examples")
    print(f"  Server: {BASE_URL}")
    print("=" * 55)

    await example_health()
    await example_scrape()
    await example_scrape_with_actions()
    await example_crawl()
    await example_map()
    await example_search()
    await example_extract()
    await example_batch()
    await example_error_handling()
    await example_full_workflow()

    print("\n" + "=" * 55)
    print("  All examples completed!")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())