"""
AgentCrawl — RAG Chunking Examples
======================================

Examples of content chunking for RAG (Retrieval-Augmented Generation)
pipelines using AgentCrawl's chunking and filtering system.

Prerequisites:
    pip install agentcrawl
    playwright install chromium

Run:
    python examples/package_mode/rag_chunking.py
"""

from __future__ import annotations

import asyncio
import json
import time


# Sample content for demonstrations
SAMPLE_MARKDOWN = """\
# Python Asyncio Guide

## Introduction

Asyncio is a Python library for writing concurrent code using the
async/await syntax. It is used as a foundation for multiple Python
asynchronous frameworks used for high-performance network and web-servers,
database connection libraries, distributed task queues, and more.

## Coroutines

A coroutine is a specialized function that can pause its execution
and yield control back to the event loop. Coroutines are declared
using the async def syntax.

```python
async def fetch_data():
    await asyncio.sleep(1)
    return {"data": "result"}
```

## Tasks

Tasks are used to schedule coroutines concurrently. When a coroutine
is wrapped in a Task, it is scheduled to run on the event loop.

```python
async def main():
    task = asyncio.create_task(fetch_data())
    result = await task
    print(result)
```

## Event Loop

The event loop is the core of asyncio. It runs async tasks and
callbacks, performs network IO operations, and runs subprocesses.

## Gather

The asyncio.gather() function runs multiple coroutines concurrently
and waits for all of them to complete.

```python
async def main():
    results = await asyncio.gather(
        fetch_data(),
        fetch_data(),
        fetch_data(),
    )
    print(results)
```

## Semaphores

Semaphores limit the number of concurrent operations. They are
useful for rate limiting API calls or database connections.

## Conclusion

Asyncio provides powerful primitives for concurrent programming
in Python. Understanding coroutines, tasks, and the event loop
is essential for building high-performance applications.
"""


# ══════════════════════════════════════════════════════════════
# Example 1: Topic Chunking
# ══════════════════════════════════════════════════════════════

async def example_topic_chunking() -> None:
    """Split content by headings (topic-aware)."""
    from agentcrawl.content import TopicChunker

    print("\n[1] Topic Chunking")
    print("-" * 45)

    chunker = TopicChunker(
        max_chunk_size=300,
        overlap=50,
    )

    result = chunker.chunk(
        SAMPLE_MARKDOWN,
        metadata={"url": "https://docs.python.org/asyncio", "title": "Asyncio Guide"},
    )

    print(f"  Total chunks: {result.total_chunks}")
    print(f"  Total tokens: {result.total_tokens}")
    print(f"  Strategy: {result.strategy}")

    for chunk in result.chunks:
        print(f"\n  Chunk {chunk.index}: [{chunk.heading}]")
        print(f"    Tokens: {chunk.token_count} | Words: {chunk.word_count}")
        print(f"    Has code: {chunk.has_code_block}")
        print(f"    Metadata: {list(chunk.metadata.keys())}")
        print(f"    Preview: {chunk.text[:100]}...")


# ══════════════════════════════════════════════════════════════
# Example 2: Sentence Chunking
# ══════════════════════════════════════════════════════════════

async def example_sentence_chunking() -> None:
    """Split content by sentences."""
    from agentcrawl.content import SentenceChunker

    print("\n[2] Sentence Chunking")
    print("-" * 45)

    chunker = SentenceChunker(
        max_chunk_size=200,
        overlap=30,
    )

    result = chunker.chunk(SAMPLE_MARKDOWN)

    print(f"  Total chunks: {result.total_chunks}")
    print(f"  Total tokens: {result.total_tokens}")

    for chunk in result.chunks[:5]:
        print(f"\n  Chunk {chunk.index}: {chunk.token_count} tokens")
        print(f"    Preview: {chunk.text[:120]}...")


# ══════════════════════════════════════════════════════════════
# Example 3: Fixed-Size Chunking
# ══════════════════════════════════════════════════════════════

async def example_fixed_chunking() -> None:
    """Split content into fixed-size chunks."""
    from agentcrawl.content import FixedChunker

    print("\n[3] Fixed-Size Chunking")
    print("-" * 45)

    chunker = FixedChunker(
        max_chunk_size=200,
        overlap=50,
    )

    result = chunker.chunk(SAMPLE_MARKDOWN)

    print(f"  Total chunks: {result.total_chunks}")
    print(f"  Total tokens: {result.total_tokens}")
    print(f"  Avg tokens/chunk: {result.avg_tokens_per_chunk:.0f}")

    for chunk in result.chunks[:4]:
        print(f"\n  Chunk {chunk.index}: {chunk.token_count} tokens")
        print(f"    Preview: {chunk.text[:100]}...")


# ══════════════════════════════════════════════════════════════
# Example 4: Regex Chunking
# ══════════════════════════════════════════════════════════════

async def example_regex_chunking() -> None:
    """Split content by regex pattern."""
    from agentcrawl.content import RegexChunker

    print("\n[4] Regex Chunking")
    print("-" * 45)

    # Split by code blocks
    chunker = RegexChunker(
        pattern=r"```[\s\S]*?```",
        max_chunk_size=500,
    )

    result = chunker.chunk(SAMPLE_MARKDOWN)

    print(f"  Total chunks: {result.total_chunks}")
    print(f"  Pattern: code blocks")

    for chunk in result.chunks[:4]:
        has_code = "```" in chunk.text
        print(f"\n  Chunk {chunk.index}: {chunk.token_count} tokens | has_code={has_code}")
        print(f"    Preview: {chunk.text[:100]}...")


# ══════════════════════════════════════════════════════════════
# Example 5: Content Filtering + Chunking
# ══════════════════════════════════════════════════════════════

async def example_filter_and_chunk() -> None:
    """Filter noise before chunking."""
    from agentcrawl.content import PruningContentFilter, TopicChunker

    print("\n[5] Filter + Chunk Pipeline")
    print("-" * 45)

    # Add noise to sample
    noisy_content = SAMPLE_MARKDOWN + """

---

## Related Articles

- [10 Python Tips](/blog/python-tips)
- [Web Scraping Guide](/blog/web-scraping)
- [Docker Tutorial](/blog/docker)

## Newsletter

Subscribe to our newsletter for weekly updates!
Enter your email: [___________] [Subscribe]

## Footer

© 2025 Example Corp. All rights reserved.
Terms of Service | Privacy Policy | Cookie Policy
"""

    # Step 1: Filter
    print("  Step 1: Content Filtering")
    content_filter = PruningContentFilter(threshold=0.3)
    filter_result = content_filter.apply(noisy_content)

    print(f"    Original: {len(noisy_content)} chars")
    print(f"    Filtered: {len(filter_result.filtered_text)} chars")
    print(f"    Removed: {len(noisy_content) - len(filter_result.filtered_text)} chars")

    # Step 2: Chunk
    print("\n  Step 2: Chunking")
    chunker = TopicChunker(max_chunk_size=300, overlap=50)
    chunk_result = chunker.chunk(filter_result.filtered_text)

    print(f"    Chunks: {chunk_result.total_chunks}")
    print(f"    Tokens: {chunk_result.total_tokens}")

    for chunk in chunk_result.chunks:
        print(f"    [{chunk.heading}] {chunk.token_count} tokens")


# ══════════════════════════════════════════════════════════════
# Example 6: BM25 Query Filtering
# ══════════════════════════════════════════════════════════════

async def example_bm25_filter() -> None:
    """Filter content by query relevance using BM25."""
    from agentcrawl.content import BM25ContentFilter

    print("\n[6] BM25 Query Filtering")
    print("-" * 45)

    queries = [
        "asyncio coroutines",
        "event loop tasks",
        "semaphores rate limiting",
    ]

    for query in queries:
        bm25_filter = BM25ContentFilter(query=query, threshold=0.5)
        result = bm25_filter.apply(SAMPLE_MARKDOWN)

        print(f"\n  Query: \"{query}\"")
        print(f"    Original: {len(SAMPLE_MARKDOWN)} chars")
        print(f"    Filtered: {len(result.filtered_text)} chars")
        print(f"    Preview: {result.filtered_text[:150]}...")


# ══════════════════════════════════════════════════════════════
# Example 7: Chunking via CrawlerConfig
# ══════════════════════════════════════════════════════════════

async def example_config_chunking() -> None:
    """Use chunking through CrawlerConfig."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[7] Chunking via CrawlerConfig")
    print("-" * 45)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        content_filter="pruning",
        chunker="topic",
        chunk_max_size=500,
        chunk_overlap=100,
        include_metadata=True,
    )

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com", config)

        print(f"  URL: {result.url}")
        print(f"  Chunks: {len(result.chunks)}")
        print(f"  Total tokens: {result.token_count}")

        for chunk in result.chunks:
            heading = chunk.get("heading", "N/A")
            tokens = chunk.get("token_count", 0)
            text_preview = chunk.get("text", "")[:80]
            print(f"\n  [{heading}] {tokens} tokens")
            print(f"    {text_preview}...")


# ══════════════════════════════════════════════════════════════
# Example 8: Chunk Metadata for Vector Store
# ══════════════════════════════════════════════════════════════

async def example_chunk_metadata() -> None:
    """Prepare chunks with rich metadata for vector store ingestion."""
    from agentcrawl.content import TopicChunker

    print("\n[8] Chunk Metadata for Vector Store")
    print("-" * 45)

    chunker = TopicChunker(max_chunk_size=300, overlap=50)

    result = chunker.chunk(
        SAMPLE_MARKDOWN,
        metadata={
            "url": "https://docs.python.org/3/library/asyncio.html",
            "title": "Asyncio Guide",
            "author": "Python Docs",
            "scraped_at": "2025-01-15T10:00:00Z",
        },
    )

    # Prepare for vector store
    documents_for_vector_store = []
    for chunk in result.chunks:
        doc = {
            "text": chunk.text,
            "metadata": {
                **chunk.metadata,
                "chunk_index": chunk.index,
                "heading": chunk.heading,
                "token_count": chunk.token_count,
                "has_code": chunk.has_code_block,
                "chunk_id": f"{chunk.metadata.get('url', '')}#chunk-{chunk.index}",
            },
        }
        documents_for_vector_store.append(doc)

    print(f"  Prepared {len(documents_for_vector_store)} documents for vector store")

    for doc in documents_for_vector_store[:3]:
        print(f"\n  Document:")
        print(f"    chunk_id: {doc['metadata']['chunk_id']}")
        print(f"    heading: {doc['metadata']['heading']}")
        print(f"    tokens: {doc['metadata']['token_count']}")
        print(f"    text: {doc['text'][:80]}...")


# ══════════════════════════════════════════════════════════════
# Example 9: Compare Chunking Strategies
# ══════════════════════════════════════════════════════════════

async def example_compare_strategies() -> None:
    """Compare different chunking strategies."""
    from agentcrawl.content import (
        TopicChunker,
        SentenceChunker,
        FixedChunker,
        RegexChunker,
    )

    print("\n[9] Strategy Comparison")
    print("-" * 45)

    strategies = {
        "Topic (300)": TopicChunker(max_chunk_size=300, overlap=50),
        "Sentence (200)": SentenceChunker(max_chunk_size=200, overlap=30),
        "Fixed (200)": FixedChunker(max_chunk_size=200, overlap=50),
        "Regex (code)": RegexChunker(pattern=r"```[\s\S]*?```", max_chunk_size=500),
    }

    header = f"  {'Strategy':<20} {'Chunks':>7} {'Tokens':>8} {'Avg/Chunk':>10} {'Time':>8}"
    print(header)
    print(f"  {'-' * 55}")

    for name, chunker in strategies.items():
        start = time.perf_counter()
        result = chunker.chunk(SAMPLE_MARKDOWN)
        elapsed = (time.perf_counter() - start) * 1000

        avg = result.avg_tokens_per_chunk
        print(
            f"  {name:<20} {result.total_chunks:>7} "
            f"{result.total_tokens:>8} {avg:>9.0f} {elapsed:>7.2f}ms"
        )


# ══════════════════════════════════════════════════════════════
# Example 10: Full RAG Pipeline
# ══════════════════════════════════════════════════════════════

async def example_full_rag_pipeline() -> None:
    """Complete RAG pipeline: scrape → filter → chunk → prepare."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    print("\n[10] Full RAG Pipeline")
    print("-" * 45)

    urls = ["https://example.com"]

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        content_filter="pruning",
        chunker="topic",
        chunk_max_size=500,
        chunk_overlap=100,
        include_metadata=True,
        cache=True,
    )

    async with CrawlEngine.default() as engine:
        start = time.perf_counter()
        results = await engine.batch_scrape(urls, config)
        elapsed = (time.perf_counter() - start) * 1000

    # Collect all chunks
    all_chunks: list[dict] = []
    for result in results:
        if result.success:
            for chunk in result.chunks:
                all_chunks.append({
                    "text": chunk.get("text", ""),
                    "metadata": {
                        "source": result.url,
                        "title": result.metadata.get("title", ""),
                        "heading": chunk.get("heading", ""),
                        "chunk_index": chunk.get("index", 0),
                        "token_count": chunk.get("token_count", 0),
                    },
                })

    print(f"  URLs processed: {len(results)}")
    print(f"  Total chunks: {len(all_chunks)}")
    print(f"  Total tokens: {sum(c['metadata']['token_count'] for c in all_chunks)}")
    print(f"  Pipeline time: {elapsed:.0f}ms")

    print(f"\n  Ready for vector store ingestion:")
    for chunk in all_chunks[:3]:
        print(f"    [{chunk['metadata']['heading']}] {chunk['metadata']['token_count']} tokens")
        print(f"      {chunk['text'][:80]}...")

    # Conceptual: feed to vector store
    print(f"\n  # Next step: embed and store")
    print(f"  # embeddings = embedding_model.embed([c['text'] for c in all_chunks])")
    print(f"  # vector_store.add(embeddings, all_chunks)")


# ══════════════════════════════════════════════════════════════
# Example 11: Factory Function
# ══════════════════════════════════════════════════════════════

async def example_factory() -> None:
    """Create chunkers with the factory function."""
    from agentcrawl.content import create_chunker

    print("\n[11] Chunker Factory")
    print("-" * 45)

    strategies = ["fixed", "sentence", "topic", "regex"]

    for strategy in strategies:
        kwargs = {"max_chunk_size": 300}
        if strategy == "regex":
            kwargs["pattern"] = r"\n## "

        chunker = create_chunker(strategy, **kwargs)
        result = chunker.chunk(SAMPLE_MARKDOWN)

        print(f"  {strategy:<10} → {result.total_chunks} chunks, {result.total_tokens} tokens")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

async def main() -> None:
    """Run all examples."""
    print("=" * 55)
    print("  AgentCrawl — RAG Chunking Examples")
    print("=" * 55)

    await example_topic_chunking()
    await example_sentence_chunking()
    await example_fixed_chunking()
    await example_regex_chunking()
    await example_filter_and_chunk()
    await example_bm25_filter()
    await example_config_chunking()
    await example_chunk_metadata()
    await example_compare_strategies()
    await example_full_rag_pipeline()
    await example_factory()

    print("\n" + "=" * 55)
    print("  All examples completed!")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())