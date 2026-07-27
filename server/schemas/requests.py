"""
AgentCrawl — Request Schemas
================================

Pydantic models for all REST API request bodies.

Each schema includes:
    - Field validation (types, ranges, patterns)
    - Default values
    - Descriptions for OpenAPI docs
    - Example values

Usage:
    from agentcrawl.server.schemas.requests import (
        ScrapeRequest,
        CrawlRequest,
        SearchRequest,
    )

    # Validate request body
    request = ScrapeRequest(**body)
    print(request.url)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════════════════════
# Scrape
# ══════════════════════════════════════════════════════════════

class ScrapeRequest(BaseModel):
    """
    Request body for POST /scrape.

    Scrapes a single page and returns processed content.

    Example:
        {
            "url": "https://example.com",
            "output_format": "markdown",
            "include_links": true,
            "only_main_content": true
        }
    """

    url: str = Field(
        ...,
        description="URL to scrape",
        min_length=1,
        examples=["https://example.com"],
    )
    output_format: str = Field(
        default="markdown",
        description="Output format: markdown, json, html, text",
        examples=["markdown"],
    )
    include_links: bool = Field(
        default=True,
        description="Include extracted links",
    )
    include_metadata: bool = Field(
        default=True,
        description="Include page metadata (title, description, og:tags)",
    )
    include_screenshot: bool = Field(
        default=False,
        description="Capture a page screenshot (base64 PNG)",
    )
    include_citations: bool = Field(
        default=False,
        description="Extract citation references [1], [2], etc.",
    )
    only_main_content: bool = Field(
        default=True,
        description="Extract only main content (skip nav, footer, sidebar)",
    )
    selectors: list[str] = Field(
        default_factory=list,
        description="CSS selectors to target specific content",
        examples=[["article", ".content"]],
    )
    exclude_selectors: list[str] = Field(
        default_factory=list,
        description="CSS selectors to exclude from extraction",
        examples=[["nav", "footer", ".ads"]],
    )
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Browser actions to execute before extraction",
        examples=[[
            {"type": "click", "selector": "#accept-cookies"},
            {"type": "scroll", "direction": "down", "amount": 3},
        ]],
    )
    content_filter: str = Field(
        default="none",
        description="Content filter: none, pruning, bm25",
    )
    content_filter_query: str = Field(
        default="",
        description="Query for BM25 content filter",
    )
    chunker: str = Field(
        default="none",
        description="Chunker: none, fixed, sentence, topic, regex",
    )
    chunk_max_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Maximum chunk size in tokens",
    )
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        le=2000,
        description="Chunk overlap in tokens",
    )
    cache: bool = Field(
        default=True,
        description="Enable response caching",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=0,
        le=86400,
        description="Cache TTL in seconds",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Page load timeout in seconds",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Custom HTTP headers",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v

    @field_validator("output_format")
    @classmethod
    def validate_output_format(cls, v: str) -> str:
        allowed = {"markdown", "json", "html", "text"}
        if v not in allowed:
            raise ValueError(f"output_format must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("content_filter")
    @classmethod
    def validate_content_filter(cls, v: str) -> str:
        allowed = {"none", "pruning", "bm25"}
        if v not in allowed:
            raise ValueError(f"content_filter must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("chunker")
    @classmethod
    def validate_chunker(cls, v: str) -> str:
        allowed = {"none", "fixed", "sentence", "topic", "regex"}
        if v not in allowed:
            raise ValueError(f"chunker must be one of: {', '.join(sorted(allowed))}")
        return v


# ══════════════════════════════════════════════════════════════
# Crawl
# ══════════════════════════════════════════════════════════════

class CrawlRequest(BaseModel):
    """
    Request body for POST /crawl.

    Starts an asynchronous crawl job.

    Example:
        {
            "url": "https://docs.example.com",
            "strategy": "bfs",
            "max_depth": 3,
            "max_pages": 50
        }
    """

    url: str = Field(
        ...,
        description="Starting URL to crawl",
        min_length=1,
    )
    strategy: str = Field(
        default="bfs",
        description="Crawl strategy: bfs, dfs, best_first, adaptive",
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum link depth to follow",
    )
    max_pages: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum pages to crawl",
    )
    max_concurrent: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Concurrent page fetches",
    )
    output_format: str = Field(
        default="markdown",
        description="Output format",
    )
    include_links: bool = Field(
        default=True,
        description="Include links in output",
    )
    only_main_content: bool = Field(
        default=True,
        description="Only main content",
    )
    content_filter: str = Field(
        default="none",
        description="Content filter: none, pruning, bm25",
    )
    include_patterns: list[str] = Field(
        default_factory=list,
        description="URL include patterns (glob)",
        examples=[["/docs/*"]],
    )
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="URL exclude patterns (glob)",
        examples=[["/blog/*", "*.pdf"]],
    )
    same_domain: bool = Field(
        default=True,
        description="Restrict crawl to same domain",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        allowed = {"bfs", "dfs", "best_first", "adaptive"}
        if v not in allowed:
            raise ValueError(f"strategy must be one of: {', '.join(sorted(allowed))}")
        return v


# ══════════════════════════════════════════════════════════════
# Map
# ══════════════════════════════════════════════════════════════

class MapRequest(BaseModel):
    """
    Request body for POST /map.

    Discovers URLs on a website.

    Example:
        {
            "url": "https://docs.example.com",
            "max_urls": 500,
            "use_sitemap": true
        }
    """

    url: str = Field(
        ...,
        description="Website URL to discover URLs from",
        min_length=1,
    )
    max_urls: int = Field(
        default=500,
        ge=1,
        le=10000,
        description="Maximum URLs to discover",
    )
    use_sitemap: bool = Field(
        default=True,
        description="Parse sitemap.xml for URLs",
    )
    use_robots: bool = Field(
        default=True,
        description="Parse robots.txt for URLs",
    )
    use_link_crawl: bool = Field(
        default=True,
        description="Crawl links to discover more URLs",
    )
    include_patterns: list[str] = Field(
        default_factory=list,
        description="URL include patterns",
    )
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="URL exclude patterns",
    )
    same_domain: bool = Field(
        default=True,
        description="Restrict to same domain",
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum crawl depth for link discovery",
    )
    timeout: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Overall timeout in seconds",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v


# ══════════════════════════════════════════════════════════════
# Search
# ══════════════════════════════════════════════════════════════

class SearchRequest(BaseModel):
    """
    Request body for POST /search.

    Searches the web.

    Example:
        {
            "query": "python asyncio tutorial",
            "max_results": 5,
            "provider": "duckduckgo"
        }
    """

    query: str = Field(
        ...,
        description="Search query string",
        min_length=1,
        max_length=500,
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of results",
    )
    provider: str = Field(
        default="duckduckgo",
        description="Search provider: duckduckgo, tavily, brave, exa, searxng",
    )
    api_key: str = Field(
        default="",
        description="Provider API key (if required)",
    )
    scrape_results: bool = Field(
        default=False,
        description="Scrape each result page for full content",
    )
    include_answer: bool = Field(
        default=False,
        description="Include direct answer (provider-dependent)",
    )
    language: str = Field(
        default="en",
        description="Search language code",
    )
    time_range: str = Field(
        default="",
        description="Time range filter: day, week, month, year",
    )
    safe_search: bool = Field(
        default=False,
        description="Enable safe search",
    )

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"duckduckgo", "tavily", "brave", "exa", "searxng", "google"}
        if v not in allowed:
            raise ValueError(f"provider must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("time_range")
    @classmethod
    def validate_time_range(cls, v: str) -> str:
        if v and v not in {"day", "week", "month", "year"}:
            raise ValueError("time_range must be one of: day, week, month, year")
        return v


# ══════════════════════════════════════════════════════════════
# Extract
# ══════════════════════════════════════════════════════════════

class ExtractRequest(BaseModel):
    """
    Request body for POST /extract.

    Extracts structured data from a URL.

    Example:
        {
            "url": "https://shop.example.com/product/1",
            "method": "css",
            "schema": {
                "name": "Product",
                "fields": [
                    {"name": "title", "selector": "h1", "type": "text"},
                    {"name": "price", "selector": ".price", "type": "text"}
                ]
            }
        }
    """

    url: str = Field(
        ...,
        description="URL to extract data from",
        min_length=1,
    )
    method: str = Field(
        default="css",
        description="Extraction method: css, xpath, llm, regex",
    )
    schema_def: dict[str, Any] = Field(
        default_factory=dict,
        alias="schema",
        description="Extraction schema (format depends on method)",
    )
    fields: str = Field(
        default="",
        description="Comma-separated field names (for LLM dynamic schema)",
        examples=["title,price,description"],
    )
    instructions: str = Field(
        default="",
        description="Additional instructions (for LLM method)",
    )
    output_format: str = Field(
        default="markdown",
        description="Page output format before extraction",
    )
    only_main_content: bool = Field(
        default=True,
        description="Extract only main content",
    )
    cache: bool = Field(
        default=True,
        description="Enable page caching",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Page timeout in seconds",
    )

    model_config = {"populate_by_name": True}

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        allowed = {"css", "xpath", "llm", "regex"}
        if v not in allowed:
            raise ValueError(f"method must be one of: {', '.join(sorted(allowed))}")
        return v


# ══════════════════════════════════════════════════════════════
# Batch
# ══════════════════════════════════════════════════════════════

class BatchScrapeRequest(BaseModel):
    """
    Request body for POST /batch/scrape.

    Scrapes multiple URLs concurrently.

    Example:
        {
            "urls": ["https://example.com/1", "https://example.com/2"],
            "max_concurrent": 5
        }
    """

    urls: list[str] = Field(
        ...,
        description="List of URLs to scrape",
        min_length=1,
        max_length=100,
    )
    output_format: str = Field(
        default="markdown",
        description="Output format",
    )
    include_links: bool = Field(
        default=True,
        description="Include links",
    )
    include_metadata: bool = Field(
        default=True,
        description="Include metadata",
    )
    only_main_content: bool = Field(
        default=True,
        description="Only main content",
    )
    content_filter: str = Field(
        default="none",
        description="Content filter",
    )
    chunker: str = Field(
        default="none",
        description="Chunker",
    )
    chunk_max_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Max chunk size",
    )
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        le=2000,
        description="Chunk overlap",
    )
    max_concurrent: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum concurrent scrapes",
    )
    cache: bool = Field(
        default=True,
        description="Enable caching",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Per-page timeout in seconds",
    )

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v: list[str]) -> list[str]:
        validated = []
        for url in v:
            url = url.strip()
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            validated.append(url)
        return validated


# ══════════════════════════════════════════════════════════════
# Interact
# ══════════════════════════════════════════════════════════════

class ActionStep(BaseModel):
    """A single browser action."""

    type: str = Field(
        ...,
        description="Action type: click, type, press, scroll, wait, screenshot, evaluate, navigate, select, hover",
    )
    selector: str = Field(default="", description="CSS selector")
    text: str = Field(default="", description="Text to type")
    key: str = Field(default="", description="Key to press")
    direction: str = Field(default="down", description="Scroll direction: up, down")
    amount: int = Field(default=1, description="Scroll amount")
    milliseconds: int = Field(default=0, description="Wait duration in ms")
    url: str = Field(default="", description="URL to navigate to")
    script: str = Field(default="", description="JavaScript to evaluate")
    value: str = Field(default="", description="Value to select")
    timeout: int = Field(default=5000, description="Action timeout in ms")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {
            "click", "type", "press", "scroll", "wait",
            "screenshot", "evaluate", "navigate", "select", "hover",
        }
        if v not in allowed:
            raise ValueError(f"action type must be one of: {', '.join(sorted(allowed))}")
        return v


class InteractRequest(BaseModel):
    """
    Request body for POST /interact.

    Executes browser actions on a page.

    Example:
        {
            "url": "https://example.com",
            "actions": [
                {"type": "click", "selector": "#accept"},
                {"type": "screenshot"}
            ]
        }
    """

    url: str = Field(default="", description="URL to navigate to first")
    session_id: str = Field(default="", description="Existing session ID")
    actions: list[ActionStep] = Field(
        default_factory=list,
        description="Actions to execute",
    )
    screenshot: bool = Field(default=False, description="Capture screenshot")
    full_page: bool = Field(default=False, description="Full page screenshot")
    get_content: bool = Field(default=False, description="Return page content")
    get_html: bool = Field(default=False, description="Return page HTML")
    timeout: int = Field(default=30, ge=5, le=120, description="Timeout in seconds")


class SessionCreateRequest(BaseModel):
    """
    Request body for POST /interact/session.

    Creates an interactive browser session.
    """

    url: str = Field(default="", description="Initial URL")
    user_agent: str = Field(default="", description="Custom User-Agent")
    viewport_width: int = Field(default=1280, ge=320, le=3840, description="Viewport width")
    viewport_height: int = Field(default=720, ge=240, le=2160, description="Viewport height")