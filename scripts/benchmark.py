"""
AgentCrawl — Benchmark Suite
================================

Performance benchmarking for AgentCrawl operations.

Benchmarks:
    - Single page scrape (latency, throughput)
    - Batch scrape (concurrency scaling)
    - Crawl strategies (BFS, DFS, BestFirst)
    - Extraction methods (LLM, CSS, XPath)
    - Content processing (filter, chunk)
    - Cache performance (hit vs miss)
    - Search latency

Usage:
    # Run all benchmarks
    python scripts/benchmark.py

    # Specific benchmark
    python scripts/benchmark.py --benchmark scrape

    # Custom iterations
    python scripts/benchmark.py --iterations 20 --concurrency 5

    # Output to file
    python scripts/benchmark.py --output results.json

    # Compare strategies
    python scripts/benchmark.py --benchmark crawl --url https://docs.example.com

Requirements:
    pip install agentcrawl
    playwright install chromium
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    name: str
    iterations: int = 0
    successful: int = 0
    failed: int = 0
    times_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.times_ms) if self.times_ms else 0.0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.times_ms) if self.times_ms else 0.0

    @property
    def p95_ms(self) -> float:
        return self._percentile(95)

    @property
    def p99_ms(self) -> float:
        return self._percentile(99)

    @property
    def min_ms(self) -> float:
        return min(self.times_ms) if self.times_ms else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.times_ms) if self.times_ms else 0.0

    @property
    def std_ms(self) -> float:
        return statistics.stdev(self.times_ms) if len(self.times_ms) > 1 else 0.0

    @property
    def throughput_rps(self) -> float:
        total_s = sum(self.times_ms) / 1000.0
        return self.successful / total_s if total_s > 0 else 0.0

    def _percentile(self, p: int) -> float:
        if not self.times_ms:
            return 0.0
        sorted_times = sorted(self.times_ms)
        idx = int(len(sorted_times) * p / 100)
        idx = min(idx, len(sorted_times) - 1)
        return sorted_times[idx]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "successful": self.successful,
            "failed": self.failed,
            "avg_ms": round(self.avg_ms, 2),
            "median_ms": round(self.median_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "std_ms": round(self.std_ms, 2),
            "throughput_rps": round(self.throughput_rps, 3),
            "errors": self.errors[:5],
            "metadata": self.metadata,
        }


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results."""
    name: str = "AgentCrawl Benchmark"
    timestamp: str = ""
    results: list[BenchmarkResult] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "config": self.config,
            "results": [r.to_dict() for r in self.results],
            "summary": {
                "total_benchmarks": len(self.results),
                "total_iterations": sum(r.iterations for r in self.results),
                "total_successful": sum(r.successful for r in self.results),
                "total_failed": sum(r.failed for r in self.results),
            },
        }


# ══════════════════════════════════════════════════════════════
# Benchmark Runner
# ══════════════════════════════════════════════════════════════

class BenchmarkRunner:
    """Runs benchmarks and collects results."""

    def __init__(
        self,
        url: str = "https://example.com",
        iterations: int = 10,
        concurrency: int = 1,
        warmup: int = 2,
        verbose: bool = True,
    ):
        self._url = url
        self._iterations = iterations
        self._concurrency = concurrency
        self._warmup = warmup
        self._verbose = verbose
        self._suite = BenchmarkSuite(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            config={
                "url": url,
                "iterations": iterations,
                "concurrency": concurrency,
                "warmup": warmup,
            },
        )

    @property
    def suite(self) -> BenchmarkSuite:
        return self._suite

    def _log(self, msg: str) -> None:
        if self._verbose:
            print(f"  {msg}")

    def _print_result(self, result: BenchmarkResult) -> None:
        if not self._verbose:
            return

        status = "✓" if result.failed == 0 else "✗"
        print(f"\n{status} {result.name}")
        print(f"    Iterations: {result.iterations} ({result.successful} ok, {result.failed} fail)")
        print(f"    Avg: {result.avg_ms:.1f}ms | Median: {result.median_ms:.1f}ms")
        print(f"    P95: {result.p95_ms:.1f}ms | P99: {result.p99_ms:.1f}ms")
        print(f"    Min: {result.min_ms:.1f}ms | Max: {result.max_ms:.1f}ms")
        print(f"    Std: {result.std_ms:.1f}ms | Throughput: {result.throughput_rps:.2f} req/s")

        if result.errors:
            print(f"    Errors: {result.errors[0]}")

    # ──────────────────────────────────────────────────────────
    # Benchmark: Single Scrape
    # ──────────────────────────────────────────────────────────

    async def bench_scrape(self) -> BenchmarkResult:
        """Benchmark single page scrape latency."""
        from agentcrawl import CrawlEngine, CrawlerConfig

        result = BenchmarkResult(name="scrape_single")
        config = CrawlerConfig(
            output_format="markdown",
            include_links=True,
            include_metadata=True,
            only_main_content=True,
            cache=False,
        )

        async with CrawlEngine.default() as engine:
            # Warmup
            self._log(f"Warming up ({self._warmup} iterations)...")
            for _ in range(self._warmup):
                try:
                    await engine.scrape(self._url, config)
                except Exception:
                    pass

            # Benchmark
            self._log(f"Running {self._iterations} iterations...")
            for i in range(self._iterations):
                start = time.perf_counter()
                try:
                    res = await engine.scrape(self._url, config)
                    elapsed = (time.perf_counter() - start) * 1000
                    result.times_ms.append(elapsed)
                    result.iterations += 1
                    if res.success:
                        result.successful += 1
                    else:
                        result.failed += 1
                        result.errors.append(f"iter {i}: {res.error}")
                except Exception as e:
                    elapsed = (time.perf_counter() - start) * 1000
                    result.times_ms.append(elapsed)
                    result.iterations += 1
                    result.failed += 1
                    result.errors.append(f"iter {i}: {e}")

        result.metadata["url"] = self._url
        self._suite.results.append(result)
        self._print_result(result)
        return result

    # ──────────────────────────────────────────────────────────
    # Benchmark: Batch Scrape
    # ──────────────────────────────────────────────────────────

    async def bench_batch_scrape(self) -> BenchmarkResult:
        """Benchmark batch scrape with concurrency."""
        from agentcrawl import CrawlEngine, CrawlerConfig

        urls = [self._url] * self._iterations
        result = BenchmarkResult(name=f"batch_scrape_x{self._concurrency}")

        config = CrawlerConfig(
            output_format="markdown",
            only_main_content=True,
            cache=False,
        )

        async with CrawlEngine.default() as engine:
            start = time.perf_counter()
            try:
                results = await engine.batch_scrape(
                    urls,
                    config=config,
                    max_concurrent=self._concurrency,
                )
                elapsed = (time.perf_counter() - start) * 1000

                result.iterations = len(results)
                result.successful = sum(1 for r in results if r.success)
                result.failed = sum(1 for r in results if not r.success)
                result.times_ms = [r.response_time_ms for r in results]
                result.metadata["total_time_ms"] = round(elapsed, 2)
                result.metadata["concurrency"] = self._concurrency

            except Exception as e:
                result.failed = self._iterations
                result.errors.append(str(e))

        self._suite.results.append(result)
        self._print_result(result)
        return result

    # ──────────────────────────────────────────────────────────
    # Benchmark: Crawl Strategies
    # ──────────────────────────────────────────────────────────

    async def bench_crawl(self) -> list[BenchmarkResult]:
        """Benchmark different crawl strategies."""
        from agentcrawl import CrawlEngine, BFSCrawler, DFSCrawler, BestFirstCrawler

        strategies = {
            "bfs": BFSCrawler(max_depth=2, max_pages=10),
            "dfs": DFSCrawler(max_depth=3, max_pages=10),
            "best_first": BestFirstCrawler(max_pages=10),
        }

        results: list[BenchmarkResult] = []

        async with CrawlEngine.default() as engine:
            for name, strategy in strategies.items():
                result = BenchmarkResult(name=f"crawl_{name}")
                self._log(f"Benchmarking crawl strategy: {name}")

                start = time.perf_counter()
                try:
                    job = await engine.crawl(self._url, strategy=strategy)
                    elapsed = (time.perf_counter() - start) * 1000

                    result.iterations = 1
                    result.successful = 1
                    result.times_ms = [elapsed]
                    result.metadata["pages_crawled"] = job.total_pages
                    result.metadata["pages_failed"] = job.failed_pages
                    result.metadata["total_words"] = job.total_words

                except Exception as e:
                    elapsed = (time.perf_counter() - start) * 1000
                    result.iterations = 1
                    result.failed = 1
                    result.times_ms = [elapsed]
                    result.errors.append(str(e))

                self._suite.results.append(result)
                self._print_result(result)
                results.append(result)

        return results

    # ──────────────────────────────────────────────────────────
    # Benchmark: Content Processing
    # ──────────────────────────────────────────────────────────

    async def bench_content_processing(self) -> list[BenchmarkResult]:
        """Benchmark content filtering and chunking."""
        from agentcrawl import CrawlEngine, CrawlerConfig

        results: list[BenchmarkResult] = []

        # First, get content
        async with CrawlEngine.default() as engine:
            scrape_result = await engine.scrape(self._url)
            markdown = scrape_result.markdown

        if not markdown:
            return results

        # Benchmark: Pruning filter
        result = BenchmarkResult(name="filter_pruning")
        from agentcrawl.content import PruningContentFilter

        pf = PruningContentFilter(threshold=0.4)
        for _ in range(self._iterations):
            start = time.perf_counter()
            pf.apply(markdown)
            elapsed = (time.perf_counter() - start) * 1000
            result.times_ms.append(elapsed)
            result.iterations += 1
            result.successful += 1

        self._suite.results.append(result)
        self._print_result(result)
        results.append(result)

        # Benchmark: Topic chunker
        result = BenchmarkResult(name="chunk_topic")
        from agentcrawl.content import TopicChunker

        chunker = TopicChunker(max_chunk_size=1000, overlap=200)
        for _ in range(self._iterations):
            start = time.perf_counter()
            chunker.chunk(markdown)
            elapsed = (time.perf_counter() - start) * 1000
            result.times_ms.append(elapsed)
            result.iterations += 1
            result.successful += 1

        self._suite.results.append(result)
        self._print_result(result)
        results.append(result)

        # Benchmark: Sentence chunker
        result = BenchmarkResult(name="chunk_sentence")
        from agentcrawl.content import SentenceChunker

        chunker = SentenceChunker(max_chunk_size=500, overlap=50)
        for _ in range(self._iterations):
            start = time.perf_counter()
            chunker.chunk(markdown)
            elapsed = (time.perf_counter() - start) * 1000
            result.times_ms.append(elapsed)
            result.iterations += 1
            result.successful += 1

        self._suite.results.append(result)
        self._print_result(result)
        results.append(result)

        return results

    # ──────────────────────────────────────────────────────────
    # Benchmark: Cache
    # ──────────────────────────────────────────────────────────

    async def bench_cache(self) -> list[BenchmarkResult]:
        """Benchmark cache hit vs miss performance."""
        from agentcrawl import CrawlEngine, CrawlerConfig

        results: list[BenchmarkResult] = []

        # Cache miss
        result_miss = BenchmarkResult(name="cache_miss")
        config_no_cache = CrawlerConfig(cache=False, output_format="markdown")

        async with CrawlEngine.default() as engine:
            for _ in range(min(self._iterations, 5)):
                start = time.perf_counter()
                try:
                    await engine.scrape(self._url, config_no_cache)
                    elapsed = (time.perf_counter() - start) * 1000
                    result_miss.times_ms.append(elapsed)
                    result_miss.iterations += 1
                    result_miss.successful += 1
                except Exception as e:
                    result_miss.failed += 1
                    result_miss.errors.append(str(e))

        self._suite.results.append(result_miss)
        self._print_result(result_miss)
        results.append(result_miss)

        # Cache hit
        result_hit = BenchmarkResult(name="cache_hit")
        config_cache = CrawlerConfig(cache=True, cache_ttl=3600, output_format="markdown")

        async with CrawlEngine.default() as engine:
            # Prime cache
            try:
                await engine.scrape(self._url, config_cache)
            except Exception:
                pass

            for _ in range(self._iterations):
                start = time.perf_counter()
                try:
                    res = await engine.scrape(self._url, config_cache)
                    elapsed = (time.perf_counter() - start) * 1000
                    result_hit.times_ms.append(elapsed)
                    result_hit.iterations += 1
                    if res.cached:
                        result_hit.successful += 1
                    else:
                        result_hit.successful += 1
                except Exception as e:
                    result_hit.failed += 1
                    result_hit.errors.append(str(e))

        result_hit.metadata["note"] = "After cache prime"
        self._suite.results.append(result_hit)
        self._print_result(result_hit)
        results.append(result_hit)

        return results

    # ──────────────────────────────────────────────────────────
    # Benchmark: Search
    # ──────────────────────────────────────────────────────────

    async def bench_search(self) -> BenchmarkResult:
        """Benchmark web search latency."""
        from agentcrawl import SearchEngine

        result = BenchmarkResult(name="search_duckduckgo")
        engine = SearchEngine(provider="duckduckgo")

        queries = [
            "python tutorial",
            "machine learning",
            "web scraping",
            "asyncio guide",
            "docker compose",
        ]

        for i in range(min(self._iterations, len(queries))):
            query = queries[i % len(queries)]
            start = time.perf_counter()
            try:
                results = await engine.search(query, max_results=5)
                elapsed = (time.perf_counter() - start) * 1000
                result.times_ms.append(elapsed)
                result.iterations += 1
                result.successful += 1
                result.metadata[f"query_{i}"] = {
                    "query": query,
                    "results": len(results),
                }
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                result.times_ms.append(elapsed)
                result.iterations += 1
                result.failed += 1
                result.errors.append(str(e))

        self._suite.results.append(result)
        self._print_result(result)
        return result

    # ──────────────────────────────────────────────────────────
    # Benchmark: Extraction
    # ──────────────────────────────────────────────────────────

    async def bench_extraction(self) -> list[BenchmarkResult]:
        """Benchmark CSS and XPath extraction."""
        from agentcrawl import CrawlEngine, JsonCssExtractor, JsonXPathExtractor

        results: list[BenchmarkResult] = []

        # Get HTML first
        async with CrawlEngine.default() as engine:
            scrape_result = await engine.scrape(self._url)
            html = scrape_result.html

        if not html:
            return results

        # CSS extraction
        css_schema = {
            "name": "Links",
            "fields": [
                {"name": "title", "selector": "h1, h2, h3", "type": "text"},
                {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
            ],
        }

        result_css = BenchmarkResult(name="extraction_css")
        extractor_css = JsonCssExtractor(schema=css_schema)

        for _ in range(self._iterations):
            start = time.perf_counter()
            try:
                await extractor_css.extract(html=html)
                elapsed = (time.perf_counter() - start) * 1000
                result_css.times_ms.append(elapsed)
                result_css.iterations += 1
                result_css.successful += 1
            except Exception as e:
                result_css.failed += 1
                result_css.errors.append(str(e))

        self._suite.results.append(result_css)
        self._print_result(result_css)
        results.append(result_css)

        # XPath extraction
        xpath_schema = {
            "name": "Links",
            "fields": [
                {"name": "title", "xpath": "//h1 | //h2 | //h3", "type": "text"},
                {"name": "url", "xpath": "//a", "type": "attribute", "attribute": "href"},
            ],
        }

        result_xpath = BenchmarkResult(name="extraction_xpath")
        extractor_xpath = JsonXPathExtractor(schema=xpath_schema)

        for _ in range(self._iterations):
            start = time.perf_counter()
            try:
                await extractor_xpath.extract(html=html)
                elapsed = (time.perf_counter() - start) * 1000
                result_xpath.times_ms.append(elapsed)
                result_xpath.iterations += 1
                result_xpath.successful += 1
            except Exception as e:
                result_xpath.failed += 1
                result_xpath.errors.append(str(e))

        self._suite.results.append(result_xpath)
        self._print_result(result_xpath)
        results.append(result_xpath)

        return results

    # ──────────────────────────────────────────────────────────
    # Run All
    # ──────────────────────────────────────────────────────────

    async def run_all(self) -> BenchmarkSuite:
        """Run all benchmarks."""
        print("\n" + "=" * 60)
        print("  AgentCrawl Benchmark Suite")
        print(f"  URL: {self._url}")
        print(f"  Iterations: {self._iterations} | Concurrency: {self._concurrency}")
        print("=" * 60)

        print("\n[1/7] Single Scrape")
        await self.bench_scrape()

        print("\n[2/7] Batch Scrape")
        await self.bench_batch_scrape()

        print("\n[3/7] Crawl Strategies")
        await self.bench_crawl()

        print("\n[4/7] Content Processing")
        await self.bench_content_processing()

        print("\n[5/7] Cache Performance")
        await self.bench_cache()

        print("\n[6/7] Search")
        await self.bench_search()

        print("\n[7/7] Extraction")
        await self.bench_extraction()

        return self._suite


# ══════════════════════════════════════════════════════════════
# Report
# ══════════════════════════════════════════════════════════════

def print_summary_table(suite: BenchmarkSuite) -> None:
    """Print a formatted summary table."""
    print("\n" + "=" * 90)
    print("  BENCHMARK SUMMARY")
    print("=" * 90)

    header = f"{'Benchmark':<30} {'Avg':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'Min':>8} {'Max':>8} {'OK/Fail':>8}"
    print(header)
    print("-" * 90)

    for r in suite.results:
        ok_fail = f"{r.successful}/{r.failed}"
        print(
            f"{r.name:<30} "
            f"{r.avg_ms:>7.1f} "
            f"{r.median_ms:>7.1f} "
            f"{r.p95_ms:>7.1f} "
            f"{r.p99_ms:>7.1f} "
            f"{r.min_ms:>7.1f} "
            f"{r.max_ms:>7.1f} "
            f"{ok_fail:>8}"
        )

    print("-" * 90)

    total_ok = sum(r.successful for r in suite.results)
    total_fail = sum(r.failed for r in suite.results)
    print(f"{'TOTAL':<30} {'':>8} {'':>8} {'':>8} {'':>8} {'':>8} {'':>8} {total_ok}/{total_fail:>5}")
    print("=" * 90)


def save_report(suite: BenchmarkSuite, filepath: str) -> None:
    """Save benchmark results to a JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(suite.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to: {filepath}")


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AgentCrawl Benchmark Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/benchmark.py
  python scripts/benchmark.py --benchmark scrape --iterations 20
  python scripts/benchmark.py --benchmark crawl --url https://docs.example.com
  python scripts/benchmark.py --output results.json
        """,
    )

    parser.add_argument(
        "--url",
        default="https://example.com",
        help="Target URL for benchmarks (default: https://example.com)",
    )
    parser.add_argument(
        "--benchmark",
        choices=["all", "scrape", "batch", "crawl", "content", "cache", "search", "extraction"],
        default="all",
        help="Which benchmark to run (default: all)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of iterations per benchmark (default: 10)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Concurrency level for batch benchmarks (default: 3)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="Warmup iterations (default: 2)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output",
    )

    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    runner = BenchmarkRunner(
        url=args.url,
        iterations=args.iterations,
        concurrency=args.concurrency,
        warmup=args.warmup,
        verbose=not args.quiet,
    )

    if args.benchmark == "all":
        suite = await runner.run_all()
    else:
        print(f"\nRunning benchmark: {args.benchmark}")
        print(f"URL: {args.url} | Iterations: {args.iterations}")
        print("-" * 60)

        if args.benchmark == "scrape":
            await runner.bench_scrape()
        elif args.benchmark == "batch":
            await runner.bench_batch_scrape()
        elif args.benchmark == "crawl":
            await runner.bench_crawl()
        elif args.benchmark == "content":
            await runner.bench_content_processing()
        elif args.benchmark == "cache":
            await runner.bench_cache()
        elif args.benchmark == "search":
            await runner.bench_search()
        elif args.benchmark == "extraction":
            await runner.bench_extraction()

        suite = runner.suite

    # Print summary
    print_summary_table(suite)

    # Save report
    if args.output:
        save_report(suite, args.output)


if __name__ == "__main__":
    asyncio.run(main())