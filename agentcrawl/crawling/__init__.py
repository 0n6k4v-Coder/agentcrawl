"""
AgentCrawl — Crawling Strategies Layer
=========================================

Crawling strategies for discovering and fetching web pages at scale.
Provides BFS, DFS, BestFirst, Adaptive, and SinglePage crawlers with
URL filtering, scoring, sitemap parsing, and domain mapping.

Strategies:
    BFSCrawler        — Breadth-first (level-by-level) exploration
    DFSCrawler        — Depth-first (deep branch) exploration
    BestFirstCrawler  — Priority-based (highest score first) exploration
    AdaptiveCrawler   — Pattern-learning intelligent exploration
    SinglePageCrawler — Single page fetch (no link following)

Utilities:
    URLFilter         — URL include/exclude filtering
    URLScorer         — URL relevance scoring
    DomainMapper      — Full-site URL discovery (sitemap + robots + crawl)
    SitemapParser     — Comprehensive sitemap.xml parsing

Quick Start:
    from agentcrawl.crawling import BFSCrawler, DFSCrawler, BestFirstCrawler

    # BFS crawl
    crawler = BFSCrawler(max_depth=3, max_pages=100)
    urls = await crawler.discover("https://docs.example.com", engine)

    # DFS crawl
    crawler = DFSCrawler(max_depth=5, max_pages=50)
    urls = await crawler.discover("https://docs.example.com", engine)

    # Best-first crawl
    crawler = BestFirstCrawler(max_pages=50, score_threshold=0.3)
    urls = await crawler.discover("https://docs.example.com", engine)

    # Adaptive crawl
    from agentcrawl.crawling import AdaptiveCrawler
    crawler = AdaptiveCrawler(max_pages=100, similarity_threshold=0.85)
    urls = await crawler.discover("https://docs.example.com", engine)

    # Domain mapping
    from agentcrawl.crawling import DomainMapper
    mapper = DomainMapper(max_urls=500)
    urls = await mapper.discover("https://example.com")

    # Sitemap parsing
    from agentcrawl.crawling import SitemapParser
    parser = SitemapParser()
    entries = await parser.parse("https://example.com/sitemap.xml")

    # URL filtering and scoring
    from agentcrawl.crawling import URLFilter, URLScorer
    url_filter = URLFilter(include_patterns=["/docs/*"])
    scorer = URLScorer()
"""

from __future__ import annotations

from agentcrawl.crawling.adaptive import (
    AdaptiveCrawler,
    AdaptiveStats,
    ContentSimilarityTracker,
    URLPatternAnalyzer,
)

# ──────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────
from agentcrawl.crawling.base import (
    CrawlConfig,
    CrawlProgress,
    CrawlStrategy,
    DiscoveredURL,
    URLFilter,
    URLScorer,
)
from agentcrawl.crawling.best_first import BestFirstCrawler

# ──────────────────────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────────────────────
from agentcrawl.crawling.bfs import BFSCrawler
from agentcrawl.crawling.dfs import DFSCrawler

# ──────────────────────────────────────────────────────────────
# Discovery
# ──────────────────────────────────────────────────────────────
from agentcrawl.crawling.domain_mapper import (
    DomainMapper,
    MapResult,
    URLPatternInfo,
)
from agentcrawl.crawling.single import SinglePageCrawler
from agentcrawl.crawling.sitemap_parser import (
    SitemapEntry,
    SitemapInfo,
    SitemapParser,
    SitemapParseResult,
)

# ──────────────────────────────────────────────────────────────
# Filtering & Scoring (Extended)
# ──────────────────────────────────────────────────────────────
from agentcrawl.crawling.url_filter import (
    AdvancedURLFilter,
    FilterPreset,
    RobotsTxtParser,
    URLNormalizer,
    URLValidator,
)
from agentcrawl.crawling.url_scorer import (
    AdvancedURLScorer,
    ScoreBreakdown,
    ScoringPreset,
    ScoringWeights,
)

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    "AdaptiveCrawler",
    "AdaptiveStats",
    # Filtering & Scoring
    "AdvancedURLFilter",
    "AdvancedURLScorer",
    # Strategies
    "BFSCrawler",
    "BestFirstCrawler",
    "ContentSimilarityTracker",
    "CrawlConfig",
    "CrawlProgress",
    # Base
    "CrawlStrategy",
    "DFSCrawler",
    "DiscoveredURL",
    # Discovery
    "DomainMapper",
    "FilterPreset",
    "MapResult",
    "RobotsTxtParser",
    "ScoreBreakdown",
    "ScoringPreset",
    "ScoringWeights",
    "SinglePageCrawler",
    "SitemapEntry",
    "SitemapInfo",
    "SitemapParseResult",
    "SitemapParser",
    "URLFilter",
    "URLNormalizer",
    "URLPatternAnalyzer",
    "URLPatternInfo",
    "URLScorer",
    "URLValidator",
]
