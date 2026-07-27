"""
AgentCrawl — Search and Scrape Examples
===========================================

Examples of web search integration and search-then-scrape
workflows using AgentCrawl.

Prerequisites:
    pip install agentcrawl
    playwright install chromium

Run:
    python examples/package_mode/search_and_scrape.py
"""

from __future__ import annotations

import asyncio
import json
import time


# ══════════════════════════════════════════════════════════════
# Example 1: Basic Search (DuckDuckGo)
# ══════════════════════════════════════════════════════════════

async def example_basic_search() -> None:
    """Basic web search with DuckDuckGo (no API key)."""
    from agentcrawl import SearchEngine

    print("\n[1] Basic Search (DuckDuckGo)")
    print("-" * 45)

    engine = SearchEngine(provider="duckduckgo")

    start = time.perf_counter()
    results = await engine.search("python asyncio tutorial", max_results=5)
    elapsed = (time.perf_counter() - start) * 1000

    print(f"  Query: \"python asyncio tutorial\"")
    print(f"  Results: {len(results)}")
    print(f"  Time: {elapsed:.0f}ms")

    for i, r in enumerate(results, 1):
        print(f"\n  {i}. {r.get('title', 'N/A')}")
        print(f"     URL: {r.get('url', '')}")
        print(f"     {r.get('snippet', '')[:100]}")


# ══════════════════════════════════════════════════════════════
# Example 2: Search with Response Object
# ══════════════════════════════════════════════════════════════

async def example_search_response() -> None:
    """Search with full SearchResponse metadata."""
    from agentcrawl import SearchEngine

    print("\n[2] Search with Response Object")
    print("-" * 45)

    engine = SearchEngine(provider="duckduckgo")

    response = await engine.search_with_response(
        "machine learning frameworks 2025",
        max_results=5,
    )

    print(f"  Query: {response.query}")
    print(f"  Provider: {response.provider}")
    print(f"  Results: {response.result_count}")
    print(f"  Duration: {response.duration_ms:.0f}ms")
    print(f"  Error: {response.error}")

    for r in response.results[:3]:
        print(f"\n  • {r.title}")
        print(f"    {r.url}")
        print(f"    Domain: {r.domain}")


# ══════════════════════════════════════════════════════════════
# Example 3: Search and Scrape
# ══════════════════════════════════════════════════════════════

async def example_search_and_scrape() -> None:
    """Search the web and scrape each result page."""
    from agentcrawl import CrawlEngine, SearchEngine

    print("\n[3] Search and Scrape")
    print("-" * 45)

    search_engine = SearchEngine(provider="duckduckgo")

    async with CrawlEngine.default() as crawl_engine:
        start = time.perf_counter()

        results = await search_engine.search_and_scrape(
            "python web scraping best practices",
            max_results=3,
            crawl_engine=crawl_engine,
        )

        elapsed = (time.perf_counter() - start) * 1000

        print(f"  Query: \"python web scraping best practices\"")
        print(f"  Scraped: {len(results)} pages")
        print(f"  Total time: {elapsed:.0f}ms")

        for result in results:
            title = result.metadata.get("search_title", result.metadata.get("title", "N/A"))
            print(f"\n  • {title}")
            print(f"    URL: {result.url}")
            print(f"    Words: {result.word_count}")
            print(f"    Preview: {result.markdown[:150]}...")


# ══════════════════════════════════════════════════════════════
# Example 4: Engine Search (Convenience)
# ══════════════════════════════════════════════════════════════

async def example_engine_search() -> None:
    """Use CrawlEngine.search() convenience method."""
    from agentcrawl import CrawlEngine

    print("\n[4] Engine Search")
    print("-" * 45)

    async with CrawlEngine.default() as engine:
        results = await engine.search(
            "docker compose tutorial",
            max_results=5,
            scrape=False,
        )

        print(f"  Results: {len(results)}")
        for r in results:
            print(f"  • {r.get('title', 'N/A')}: {r.get('url', '')}")


# ══════════════════════════════════════════════════════════════
# Example 5: Multiple Queries
# ══════════════════════════════════════════════════════════════

async def example_multiple_queries() -> None:
    """Run multiple search queries."""
    from agentcrawl import SearchEngine

    print("\n[5] Multiple Queries")
    print("-" * 45)

    engine = SearchEngine(provider="duckduckgo", rate_limit_delay=1.5)

    queries = [
        "python 3.13 new features",
        "fastapi vs flask 2025",
        "best vector databases for RAG",
    ]

    for query in queries:
        results = await engine.search(query, max_results=3)
        print(f"\n  Query: \"{query}\"")
        print(f"  Results: {len(results)}")
        for r in results[:2]:
            print(f"    • {r.get('title', 'N/A')}")


# ══════════════════════════════════════════════════════════════
# Example 6: Search → Scrape → Extract Pipeline
# ══════════════════════════════════════════════════════════════

async def example_research_pipeline() -> None:
    """Full research pipeline: search → scrape → extract."""
    from agentcrawl import CrawlEngine, SearchEngine, CrawlerConfig

    print("\n[6] Research Pipeline")
    print("-" * 45)

    search_engine = SearchEngine(provider="duckduckgo")

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        content_filter="pruning",
        chunker="topic",
        chunk_max_size=500,
    )

    # Step 1: Search
    print("  Step 1: Search")
    search_results = await search_engine.search(
        "python asyncio guide",
        max_results=3,
    )
    print(f"    Found {len(search_results)} results")

    # Step 2: Scrape
    print("\n  Step 2: Scrape")
    urls = [r.get("url", "") for r in search_results if r.get("url")]

    async with CrawlEngine.default() as engine:
        scrape_results = await engine.batch_scrape(urls[:2], config)

        for result in scrape_results:
            if result.success:
                print(f"    ✓ {result.url} ({result.word_count} words, {len(result.chunks)} chunks)")
            else:
                print(f"    ✗ {result.url} ({result.error})")

    # Step 3: Summarize
    print("\n  Step 3: Summary")
    total_words = sum(r.word_count for r in scrape_results if r.success)
    total_chunks = sum(len(r.chunks) for r in scrape_results if r.success)
    print(f"    Total words: {total_words}")
    print(f"    Total chunks: {total_chunks}")
    print(f"    Ready for RAG ingestion")


# ══════════════════════════════════════════════════════════════
# Example 7: Search with Filtering
# ══════════════════════════════════════════════════════════════

async def example_search_filtering() -> None:
    """Filter search results by domain or pattern."""
    from agentcrawl import SearchEngine

    print("\n[7] Search with Filtering")
    print("-" * 45)

    engine = SearchEngine(provider="duckduckgo")

    results = await engine.search("python documentation", max_results=10)

    # Filter by domain
    docs_only = [
        r for r in results
        if "docs.python.org" in r.get("url", "")
        or "python.org" in r.get("url", "")
    ]

    print(f"  Total results: {len(results)}")
    print(f"  python.org results: {len(docs_only)}")

    for r in docs_only:
        print(f"    • {r.get('title', 'N/A')}: {r.get('url', '')}")

    # Filter by keyword in title
    tutorial_results = [
        r for r in results
        if "tutorial" in r.get("title", "").lower()
        or "guide" in r.get("title", "").lower()
    ]

    print(f"\n  Tutorial/guide results: {len(tutorial_results)}")
    for r in tutorial_results:
        print(f"    • {r.get('title', 'N/A')}")


# ══════════════════════════════════════════════════════════════
# Example 8: Search Diagnostics
# ══════════════════════════════════════════════════════════════

async def example_diagnostics() -> None:
    """View search engine diagnostics."""
    from agentcrawl import SearchEngine

    print("\n[8] Search Diagnostics")
    print("-" * 45)

    engine = SearchEngine(provider="duckduckgo")

    # Run a few searches
    await engine.search("test query 1", max_results=3)
    await engine.search("test query 2", max_results=3)

    diag = engine.get_diagnostics()
    print(f"  Provider: {diag['provider']}")
    print(f"  Total searches: {diag['total_searches']}")
    print(f"  Total results: {diag['total_results']}")
    print(f"  Avg results/search: {diag['avg_results_per_search']}")
    print(f"  Timeout: {diag['timeout']}s")
    print(f"  Rate limit delay: {diag['rate_limit_delay']}s")


# ══════════════════════════════════════════════════════════════
# Example 9: Convenience Function
# ══════════════════════════════════════════════════════════════

async def example_convenience() -> None:
    """Use the top-level search convenience function."""
    import agentcrawl

    print("\n[9] Convenience Function")
    print("-" * 45)

    results = await agentcrawl.search("python asyncio", max_results=3)

    print(f"  Results: {len(results)}")
    for r in results:
        print(f"  • {r.get('title', 'N/A')}: {r.get('url', '')}")


# ══════════════════════════════════════════════════════════════
# Example 10: Error Handling
# ══════════════════════════════════════════════════════════════

async def example_error_handling() -> None:
    """Handle search errors gracefully."""
    from agentcrawl import SearchEngine

    print("\n[10] Error Handling")
    print("-" * 45)

    # Valid provider
    engine = SearchEngine(provider="duckduckgo")
    results = await engine.search("test", max_results=3)
    print(f"  DuckDuckGo: {len(results)} results")

    # Invalid provider
    try:
        bad_engine = SearchEngine(provider="nonexistent")
    except ValueError as e:
        print(f"  Invalid provider error: {e}")

    # Empty query
    results = await engine.search("", max_results=3)
    print(f"  Empty query: {len(results)} results")


# ══════════════════════════════════════════════════════════════
# Example 11: Search Providers Comparison
# ══════════════════════════════════════════════════════════════

async def example_provider_comparison() -> None:
    """Compare available search providers."""
    from agentcrawl.search.engine import PROVIDERS

    print("\n[11] Available Providers")
    print("-" * 45)

    print(f"  Registered providers: {len(PROVIDERS)}")
    for name, cls in sorted(PROVIDERS.items()):
        requires_key = name not in ("duckduckgo",)
        print(f"    • {name:<15} ({cls.__name__}) {'[API key required]' if requires_key else '[no API key]'}")


# ══════════════════════════════════════════════════════════════
# Example 12: Research Agent Workflow
# ══════════════════════════════════════════════════════════════

async def example_research_workflow() -> None:
    """Simulate an AI agent research workflow."""
    from agentcrawl import CrawlEngine, SearchEngine, CrawlerConfig

    print("\n[12] Research Agent Workflow")
    print("-" * 45)

    topic = "Python asyncio best practices"
    print(f"  Topic: \"{topic}\"")

    search_engine = SearchEngine(provider="duckduckgo")

    # Phase 1: Initial search
    print("\n  Phase 1: Initial Search")
    results = await search_engine.search(topic, max_results=5)
    print(f"    Found {len(results)} results")

    # Phase 2: Select best sources
    print("\n  Phase 2: Select Sources")
    selected_urls = []
    for r in results[:3]:
        url = r.get("url", "")
        title = r.get("title", "")
        if url:
            selected_urls.append(url)
            print(f"    Selected: {title}")
            print(f"      {url}")

    # Phase 3: Deep scrape
    print("\n  Phase 3: Deep Scrape")
    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        content_filter="pruning",
        chunker="topic",
        chunk_max_size=800,
    )

    async with CrawlEngine.default() as engine:
        scrape_results = await engine.batch_scrape(selected_urls, config)

    # Phase 4: Compile knowledge
    print("\n  Phase 4: Compile Knowledge")
    knowledge_base: list[dict] = []

    for result in scrape_results:
        if result.success:
            for chunk in result.chunks:
                knowledge_base.append({
                    "text": chunk.get("text", ""),
                    "source": result.url,
                    "heading": chunk.get("heading", ""),
                    "tokens": chunk.get("token_count", 0),
                })

    total_tokens = sum(k["tokens"] for k in knowledge_base)
    print(f"    Knowledge chunks: {len(knowledge_base)}")
    print(f"    Total tokens: {total_tokens}")
    print(f"    Sources: {len(set(k['source'] for k in knowledge_base))}")

    # Phase 5: Ready for LLM
    print("\n  Phase 5: Ready for LLM")
    print(f"    Context window needed: ~{total_tokens} tokens")
    print(f"    Can proceed with RAG or direct LLM query")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

async def main() -> None:
    """Run all examples."""
    print("=" * 55)
    print("  AgentCrawl — Search and Scrape Examples")
    print("=" * 55)

    await example_basic_search()
    await example_search_response()
    await example_search_and_scrape()
    await example_engine_search()
    await example_multiple_queries()
    await example_research_pipeline()
    await example_search_filtering()
    await example_diagnostics()
    await example_convenience()
    await example_error_handling()
    await example_provider_comparison()
    await example_research_workflow()

    print("\n" + "=" * 55)
    print("  All examples completed!")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())