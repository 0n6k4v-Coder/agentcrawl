"""
AgentCrawl — Search Layer
============================

Web search integration with multiple provider support.
Search the web and optionally scrape result pages for full content.

Modules:
    engine    — SearchEngine + provider base classes
    google    — Google search (Custom Search API, SerpAPI, scraping)
    scraper   — Direct SERP scraping (Google, Bing, DuckDuckGo)
    searxng   — SearXNG metasearch provider

Providers:
    DuckDuckGo    — No API key required (default)
    Google        — Custom Search API, SerpAPI, or scraping
    Bing          — Direct scraping
    Brave         — Brave Search API
    Tavily        — AI-optimized search API
    Exa           — Neural/semantic search API
    SearXNG       — Self-hosted metasearch (no API key)

Quick Start:
    from agentcrawl.search import SearchEngine

    # Default (DuckDuckGo, no API key)
    engine = SearchEngine()
    results = await engine.search("python tutorial")

    # With provider
    engine = SearchEngine(provider="tavily", api_key="...")
    results = await engine.search("machine learning")

    # Search and scrape
    results = await engine.search_and_scrape(
        query="python web scraping",
        crawl_engine=crawl_engine,
    )

    # Google via Custom Search API
    from agentcrawl.search import GoogleSearchProvider
    provider = GoogleSearchProvider(api_key="...", cx="...")
    results = await provider.search("asyncio tutorial")

    # SearXNG (self-hosted)
    from agentcrawl.search import SearXNGProvider
    provider = SearXNGProvider(base_url="http://localhost:8888")
    results = await provider.search("open source")

    # Direct SERP scraping
    from agentcrawl.search import SearchScraper
    scraper = SearchScraper(engine="bing")
    results = await scraper.search("web scraping")
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# Engine & Providers
# ──────────────────────────────────────────────────────────────
from agentcrawl.search.engine import (
    PROVIDERS,
    BraveProvider,
    DuckDuckGoProvider,
    ExaProvider,
    SearchEngine,
    SearchProvider,
    SearchResponse,
    SearchResult,
    TavilyProvider,
)

# ──────────────────────────────────────────────────────────────
# Google
# ──────────────────────────────────────────────────────────────
from agentcrawl.search.google import GoogleSearchProvider

# ──────────────────────────────────────────────────────────────
# Scraper
# ──────────────────────────────────────────────────────────────
from agentcrawl.search.scraper import SearchScraper

# ──────────────────────────────────────────────────────────────
# SearXNG
# ──────────────────────────────────────────────────────────────
from agentcrawl.search.searxng import SearXNGProvider

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Engine
    "SearchEngine",
    "SearchProvider",
    "SearchResult",
    "SearchResponse",
    "PROVIDERS",
    # Providers
    "DuckDuckGoProvider",
    "GoogleSearchProvider",
    "BraveProvider",
    "TavilyProvider",
    "ExaProvider",
    "SearXNGProvider",
    # Scraper
    "SearchScraper",
]
