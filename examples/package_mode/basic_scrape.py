"""
AgentCrawl — Basic Scrape Examples
======================================

Examples of scraping web pages using AgentCrawl in package mode.

Prerequisites:
    pip install agentcrawl
    playwright install chromium

Run:
    python examples/package_mode/basic_scrape.py
"""

from __future__ import annotations

import asyncio

# ══════════════════════════════════════════════════════════════
# Example 1: Simplest Scrape
# ══════════════════════════════════════════════════════════════

async def example_simple() -> None:
    """The simplest possible scrape."""
    from agentcrawl import CrawlEngine

    print("\n[1] Simple Scrape")
    print("-" * 40)

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")

        print(f"  URL: {result.url}")
        print(f"  Status: {result.status_code}")
        print(f"  Words: {result.word_count}")
        print(f"  Time: {result.response_time_ms:.0f}ms")
        print(f"  Content:\n{result.markdown[:300]}")


# ══════════════════════════════════════════════════════════════
# Example 2: Scrape with Configuration
# ══════════════════════════════════════════════════════════════

async def example_with_config() -> None:
    """Scrape with custom configuration."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[2] Scrape with Config")
    print("-" * 40)

    config = CrawlerConfig(
        output_format="markdown",
        include_links=True,
        include_metadata=True,
        only_main_content=True,
        cache=True,
        cache_ttl=3600,
        timeout=30,
    )

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://news.ycombinator.com", config)

        print(f"  Title: {result.metadata.get('title', 'N/A')}")
        print(f"  Description: {result.metadata.get('description', 'N/A')[:100]}")
        print(f"  Links: {len(result.links.get('all', []))}")
        print(f"  Cached: {result.cached}")
        print(f"  Content preview:\n{result.markdown[:300]}")


# ══════════════════════════════════════════════════════════════
# Example 3: Scrape with Page Actions
# ══════════════════════════════════════════════════════════════

async def example_with_actions() -> None:
    """Scrape with browser actions (click, scroll, wait)."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[3] Scrape with Actions")
    print("-" * 40)

    config = CrawlerConfig(
        actions=[
            # Wait for page to load
            {"type": "wait", "milliseconds": 1000},
            # Scroll down to load lazy content
            {"type": "scroll", "direction": "down", "amount": 3},
            # Wait a bit more
            {"type": "wait", "milliseconds": 500},
        ],
        only_main_content=True,
    )

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com", config)

        print(f"  Success: {result.success}")
        print(f"  Words: {result.word_count}")
        print(f"  Content:\n{result.markdown[:300]}")


# ══════════════════════════════════════════════════════════════
# Example 4: Scrape with Content Filter
# ══════════════════════════════════════════════════════════════

async def example_with_filter() -> None:
    """Scrape with content filtering to remove noise."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[4] Scrape with Content Filter")
    print("-" * 40)

    # Without filter
    config_no_filter = CrawlerConfig(
        content_filter="none",
        only_main_content=False,
    )

    # With pruning filter
    config_filtered = CrawlerConfig(
        content_filter="pruning",
        only_main_content=True,
    )

    async with CrawlEngine.default() as engine:
        result_raw = await engine.scrape("https://example.com", config_no_filter)
        result_filtered = await engine.scrape("https://example.com", config_filtered)

        print(f"  Raw word count: {result_raw.word_count}")
        print(f"  Filtered word count: {result_filtered.word_count}")
        print(f"  Reduction: {result_raw.word_count - result_filtered.word_count} words removed")


# ══════════════════════════════════════════════════════════════
# Example 5: Scrape with Chunking (RAG-ready)
# ══════════════════════════════════════════════════════════════

async def example_with_chunking() -> None:
    """Scrape with chunking for RAG pipelines."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[5] Scrape with Chunking")
    print("-" * 40)

    config = CrawlerConfig(
        chunker="topic",
        chunk_max_size=500,
        chunk_overlap=100,
        include_metadata=True,
    )

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com", config)

        print(f"  Total chunks: {len(result.chunks)}")
        print(f"  Total tokens: {result.token_count}")

        for chunk in result.chunks[:3]:
            heading = chunk.get("heading", "N/A")
            tokens = chunk.get("token_count", 0)
            text_preview = chunk.get("text", "")[:100]
            print(f"\n  Chunk: [{heading}] ({tokens} tokens)")
            print(f"    {text_preview}...")


# ══════════════════════════════════════════════════════════════
# Example 6: Access All Result Fields
# ══════════════════════════════════════════════════════════════

async def example_result_fields() -> None:
    """Demonstrate all CrawlResult fields."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[6] Result Fields")
    print("-" * 40)

    config = CrawlerConfig(
        include_links=True,
        include_metadata=True,
        include_citations=True,
    )

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com", config)

        print(f"  url: {result.url}")
        print(f"  success: {result.success}")
        print(f"  status_code: {result.status_code}")
        print(f"  word_count: {result.word_count}")
        print(f"  token_count: {result.token_count}")
        print(f"  response_time_ms: {result.response_time_ms:.1f}")
        print(f"  cached: {result.cached}")
        print(f"  request_id: {result.request_id}")
        print(f"  metadata keys: {list(result.metadata.keys())}")
        print(f"  links count: {len(result.links.get('all', []))}")
        print(f"  citations count: {len(result.citations)}")
        print(f"  markdown length: {len(result.markdown)} chars")
        print(f"  html length: {len(result.html)} chars")
        print(f"  error: {result.error}")


# ══════════════════════════════════════════════════════════════
# Example 7: Error Handling
# ══════════════════════════════════════════════════════════════

async def example_error_handling() -> None:
    """Handle scrape errors gracefully."""
    from agentcrawl import CrawlEngine

    print("\n[7] Error Handling")
    print("-" * 40)

    urls = [
        "https://example.com",
        "https://this-domain-does-not-exist-12345.com",
        "https://httpbin.org/status/404",
    ]

    async with CrawlEngine.default() as engine:
        for url in urls:
            result = await engine.scrape(url)

            if result.success:
                print(f"  ✓ {url} — {result.word_count} words")
            else:
                print(f"  ✗ {url} — {result.error}")


# ══════════════════════════════════════════════════════════════
# Example 8: Batch Scrape
# ══════════════════════════════════════════════════════════════

async def example_batch() -> None:
    """Scrape multiple URLs concurrently."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[8] Batch Scrape")
    print("-" * 40)

    urls = [
        "https://example.com",
        "https://www.iana.org/domains/example",
        "https://httpbin.org/html",
    ]

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
    )

    async with CrawlEngine.default() as engine:
        import time
        start = time.perf_counter()

        results = await engine.batch_scrape(urls, config, max_concurrent=3)

        elapsed = (time.perf_counter() - start) * 1000

        print(f"  Scraped {len(results)} pages in {elapsed:.0f}ms")

        for result in results:
            status = "✓" if result.success else "✗"
            print(f"  {status} {result.url} — {result.word_count} words")


# ══════════════════════════════════════════════════════════════
# Example 9: Convenience Function
# ══════════════════════════════════════════════════════════════

async def example_convenience() -> None:
    """Use the top-level convenience function."""
    import agentcrawl

    print("\n[9] Convenience Function")
    print("-" * 40)

    result = await agentcrawl.scrape("https://example.com")
    print(f"  Title: {result.metadata.get('title', 'N/A')}")
    print(f"  Words: {result.word_count}")
    print(f"  Content:\n{result.markdown[:200]}")


# ══════════════════════════════════════════════════════════════
# Example 10: JSON Output
# ══════════════════════════════════════════════════════════════

async def example_json_output() -> None:
    """Get result as JSON."""
    from agentcrawl import CrawlEngine

    print("\n[10] JSON Output")
    print("-" * 40)

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")

        # Convert to dict
        data = result.to_dict()
        print(f"  Keys: {list(data.keys())}")

        # Convert to JSON string
        json_str = result.to_json()
        print(f"  JSON length: {len(json_str)} chars")
        print(f"  Preview: {json_str[:200]}...")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

async def main() -> None:
    """Run all examples."""
    print("=" * 50)
    print("  AgentCrawl — Basic Scrape Examples")
    print("=" * 50)

    await example_simple()
    await example_with_config()
    await example_with_actions()
    await example_with_filter()
    await example_with_chunking()
    await example_result_fields()
    await example_error_handling()
    await example_batch()
    await example_convenience()
    await example_json_output()

    print("\n" + "=" * 50)
    print("  All examples completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
