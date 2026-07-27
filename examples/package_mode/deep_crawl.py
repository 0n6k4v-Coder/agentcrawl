"""
AgentCrawl — Deep Crawl Examples
====================================

Examples of multi-page website crawling using different strategies.

Prerequisites:
    pip install agentcrawl
    playwright install chromium

Run:
    python examples/package_mode/deep_crawl.py
"""

from __future__ import annotations

import asyncio
import time


# ══════════════════════════════════════════════════════════════
# Example 1: BFS Crawl (Breadth-First)
# ══════════════════════════════════════════════════════════════

async def example_bfs() -> None:
    """Breadth-first crawl — explores level by level."""
    from agentcrawl import CrawlEngine, BFSCrawler, CrawlerConfig

    print("\n[1] BFS Crawl")
    print("-" * 40)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        cache=True,
    )

    crawler = BFSCrawler(
        max_depth=2,
        max_pages=5,
        max_concurrent=3,
    )

    async with CrawlEngine.default() as engine:
        start = time.perf_counter()
        job = await engine.crawl(
            "https://example.com",
            strategy=crawler,
            config=config,
        )
        elapsed = (time.perf_counter() - start) * 1000

        print(f"  Strategy: BFS")
        print(f"  Pages: {job.total_pages} ({job.successful_pages} ok, {job.failed_pages} fail)")
        print(f"  Words: {job.total_words}")
        print(f"  Tokens: {job.total_tokens}")
        print(f"  Time: {elapsed:.0f}ms")

        for page in job.pages:
            status = "✓" if page.success else "✗"
            print(f"    {status} {page.url} ({page.word_count} words)")


# ══════════════════════════════════════════════════════════════
# Example 2: DFS Crawl (Depth-First)
# ══════════════════════════════════════════════════════════════

async def example_dfs() -> None:
    """Depth-first crawl — explores deep branches first."""
    from agentcrawl import CrawlEngine, DFSCrawler, CrawlerConfig

    print("\n[2] DFS Crawl")
    print("-" * 40)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
    )

    crawler = DFSCrawler(
        max_depth=3,
        max_pages=5,
        push_order="score",
    )

    async with CrawlEngine.default() as engine:
        job = await engine.crawl(
            "https://example.com",
            strategy=crawler,
            config=config,
        )

        print(f"  Strategy: DFS")
        print(f"  Pages: {job.total_pages}")
        print(f"  Words: {job.total_words}")

        for page in job.pages:
            status = "✓" if page.success else "✗"
            print(f"    {status} {page.url}")


# ══════════════════════════════════════════════════════════════
# Example 3: BestFirst Crawl (Priority-Based)
# ══════════════════════════════════════════════════════════════

async def example_best_first() -> None:
    """Best-first crawl — explores highest-scored URLs first."""
    from agentcrawl import CrawlEngine, BestFirstCrawler, CrawlerConfig

    print("\n[3] BestFirst Crawl")
    print("-" * 40)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
    )

    crawler = BestFirstCrawler(
        max_pages=5,
        score_threshold=0.2,
        decay_factor=0.05,
    )

    async with CrawlEngine.default() as engine:
        job = await engine.crawl(
            "https://example.com",
            strategy=crawler,
            config=config,
        )

        print(f"  Strategy: BestFirst")
        print(f"  Pages: {job.total_pages}")
        print(f"  Words: {job.total_words}")

        for page in job.pages:
            status = "✓" if page.success else "✗"
            print(f"    {status} {page.url}")


# ══════════════════════════════════════════════════════════════
# Example 4: Adaptive Crawl (Pattern-Learning)
# ══════════════════════════════════════════════════════════════

async def example_adaptive() -> None:
    """Adaptive crawl — learns site patterns and adapts."""
    from agentcrawl import CrawlEngine, AdaptiveCrawler, CrawlerConfig

    print("\n[4] Adaptive Crawl")
    print("-" * 40)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
    )

    crawler = AdaptiveCrawler(
        max_pages=5,
        max_depth=3,
        similarity_threshold=0.85,
        learn_from_pages=3,
    )

    async with CrawlEngine.default() as engine:
        job = await engine.crawl(
            "https://example.com",
            strategy=crawler,
            config=config,
        )

        print(f"  Strategy: Adaptive")
        print(f"  Pages: {job.total_pages}")
        print(f"  Words: {job.total_words}")

        for page in job.pages:
            status = "✓" if page.success else "✗"
            print(f"    {status} {page.url}")


# ══════════════════════════════════════════════════════════════
# Example 5: Crawl with URL Filtering
# ══════════════════════════════════════════════════════════════

async def example_url_filter() -> None:
    """Crawl with URL include/exclude patterns."""
    from agentcrawl import CrawlEngine, BFSCrawler, CrawlerConfig
    from agentcrawl.crawling import URLFilter

    print("\n[5] Crawl with URL Filter")
    print("-" * 40)

    url_filter = URLFilter(
        include_patterns=["/*"],
        exclude_patterns=["*.pdf", "*.zip", "*.png", "*.jpg"],
        same_domain=True,
        max_depth=3,
    )

    crawler = BFSCrawler(
        max_depth=2,
        max_pages=5,
        url_filter=url_filter,
    )

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
    )

    async with CrawlEngine.default() as engine:
        job = await engine.crawl(
            "https://example.com",
            strategy=crawler,
            config=config,
        )

        print(f"  Filter: same_domain=True, exclude=[*.pdf, *.zip, *.png, *.jpg]")
        print(f"  Pages: {job.total_pages}")

        for page in job.pages:
            print(f"    ✓ {page.url}")


# ══════════════════════════════════════════════════════════════
# Example 6: Crawl with Content Processing
# ══════════════════════════════════════════════════════════════

async def example_crawl_with_processing() -> None:
    """Crawl with content filtering and chunking."""
    from agentcrawl import CrawlEngine, BFSCrawler, CrawlerConfig

    print("\n[6] Crawl with Content Processing")
    print("-" * 40)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        content_filter="pruning",
        chunker="topic",
        chunk_max_size=500,
        chunk_overlap=100,
        include_metadata=True,
    )

    crawler = BFSCrawler(max_depth=1, max_pages=3)

    async with CrawlEngine.default() as engine:
        job = await engine.crawl(
            "https://example.com",
            strategy=crawler,
            config=config,
        )

        print(f"  Pages: {job.total_pages}")
        print(f"  Total chunks: {sum(len(p.chunks) for p in job.pages)}")

        for page in job.pages:
            if page.success:
                print(f"\n  Page: {page.url}")
                print(f"    Words: {page.word_count}")
                print(f"    Chunks: {len(page.chunks)}")
                for chunk in page.chunks[:2]:
                    heading = chunk.get("heading", "N/A")
                    tokens = chunk.get("token_count", 0)
                    print(f"      [{heading}] {tokens} tokens")


# ══════════════════════════════════════════════════════════════
# Example 7: Domain Mapping (URL Discovery)
# ══════════════════════════════════════════════════════════════

async def example_domain_map() -> None:
    """Discover all URLs without scraping content."""
    from agentcrawl import DomainMapper

    print("\n[7] Domain Mapping")
    print("-" * 40)

    mapper = DomainMapper(
        max_urls=50,
        use_sitemap=True,
        use_robots=True,
        use_link_crawl=True,
    )

    start = time.perf_counter()
    urls = await mapper.discover("https://example.com")
    elapsed = (time.perf_counter() - start) * 1000

    print(f"  Discovered {len(urls)} URLs in {elapsed:.0f}ms")

    for url in urls[:10]:
        print(f"    • {url}")

    if len(urls) > 10:
        print(f"    ... and {len(urls) - 10} more")


# ══════════════════════════════════════════════════════════════
# Example 8: Sitemap Parsing
# ══════════════════════════════════════════════════════════════

async def example_sitemap() -> None:
    """Parse sitemap.xml for URL discovery."""
    from agentcrawl import SitemapParser

    print("\n[8] Sitemap Parsing")
    print("-" * 40)

    parser = SitemapParser(max_urls=100)

    # Try to discover and parse sitemaps
    result = await parser.discover_and_parse("https://example.com")

    print(f"  Sitemaps found: {result.total_sitemaps}")
    print(f"  Total URLs: {result.total_urls}")

    if result.entries:
        print(f"\n  Sample entries:")
        for entry in result.entries[:5]:
            print(f"    • {entry.url}")
            if entry.lastmod:
                print(f"      lastmod: {entry.lastmod}")
    else:
        print("  No sitemap found (this is normal for example.com)")


# ══════════════════════════════════════════════════════════════
# Example 9: Map via Engine
# ══════════════════════════════════════════════════════════════

async def example_engine_map() -> None:
    """Use engine.map() for URL discovery."""
    from agentcrawl import CrawlEngine

    print("\n[9] Engine Map")
    print("-" * 40)

    async with CrawlEngine.default() as engine:
        urls = await engine.map("https://example.com", max_urls=20)

        print(f"  Discovered {len(urls)} URLs")
        for url in urls[:10]:
            print(f"    • {url}")


# ══════════════════════════════════════════════════════════════
# Example 10: Crawl Job Result Analysis
# ══════════════════════════════════════════════════════════════

async def example_result_analysis() -> None:
    """Analyze crawl job results in detail."""
    from agentcrawl import CrawlEngine, BFSCrawler, CrawlerConfig

    print("\n[10] Crawl Result Analysis")
    print("-" * 40)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        include_metadata=True,
    )

    crawler = BFSCrawler(max_depth=1, max_pages=3)

    async with CrawlEngine.default() as engine:
        job = await engine.crawl(
            "https://example.com",
            strategy=crawler,
            config=config,
        )

        # Job-level stats
        print(f"  Job ID: {job.job_id}")
        print(f"  Start URL: {job.start_url}")
        print(f"  Strategy: {job.strategy}")
        print(f"  Status: {job.status}")
        print(f"  Total pages: {job.total_pages}")
        print(f"  Successful: {job.successful_pages}")
        print(f"  Failed: {job.failed_pages}")
        print(f"  Total words: {job.total_words}")
        print(f"  Total tokens: {job.total_tokens}")
        print(f"  Duration: {job.duration_ms:.0f}ms")

        # Per-page analysis
        print(f"\n  Per-page breakdown:")
        for page in job.pages:
            title = page.metadata.get("title", "N/A")
            print(f"    {page.url}")
            print(f"      Title: {title}")
            print(f"      Words: {page.word_count} | Tokens: {page.token_count}")
            print(f"      Time: {page.response_time_ms:.0f}ms | Cached: {page.cached}")


# ══════════════════════════════════════════════════════════════
# Example 11: Compare Strategies
# ══════════════════════════════════════════════════════════════

async def example_compare_strategies() -> None:
    """Compare different crawl strategies on the same site."""
    from agentcrawl import (
        CrawlEngine,
        BFSCrawler,
        DFSCrawler,
        BestFirstCrawler,
        CrawlerConfig,
    )

    print("\n[11] Strategy Comparison")
    print("-" * 40)

    url = "https://example.com"
    max_pages = 3

    strategies = {
        "BFS": BFSCrawler(max_depth=2, max_pages=max_pages),
        "DFS": DFSCrawler(max_depth=3, max_pages=max_pages),
        "BestFirst": BestFirstCrawler(max_pages=max_pages),
    }

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        cache=True,
    )

    async with CrawlEngine.default() as engine:
        print(f"  URL: {url}")
        print(f"  Max pages: {max_pages}\n")

        header = f"  {'Strategy':<12} {'Pages':>6} {'Words':>8} {'Time':>10}"
        print(header)
        print(f"  {'-' * 40}")

        for name, strategy in strategies.items():
            start = time.perf_counter()
            job = await engine.crawl(url, strategy=strategy, config=config)
            elapsed = (time.perf_counter() - start) * 1000

            print(
                f"  {name:<12} {job.total_pages:>6} "
                f"{job.total_words:>8} {elapsed:>9.0f}ms"
            )


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

async def main() -> None:
    """Run all examples."""
    print("=" * 50)
    print("  AgentCrawl — Deep Crawl Examples")
    print("=" * 50)

    await example_bfs()
    await example_dfs()
    await example_best_first()
    await example_adaptive()
    await example_url_filter()
    await example_crawl_with_processing()
    await example_domain_map()
    await example_sitemap()
    await example_engine_map()
    await example_result_analysis()
    await example_compare_strategies()

    print("\n" + "=" * 50)
    print("  All examples completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())