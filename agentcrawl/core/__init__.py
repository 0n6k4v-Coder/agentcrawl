"""
AgentCrawl — Core Engine Layer
=================================

The central orchestration layer that coordinates all subsystems
(browser, content, extraction, cache) into a unified crawl pipeline.
Shared by both Package Mode and Server Mode.

Modules:
    engine    — CrawlEngine: main orchestrator (scrape, crawl, search, map)
    pipeline  — Composable stage-based processing pipeline
    session   — Stateful session management (cookies, context reuse)
    types     — Shared type definitions, protocols, and enums

Quick Start:
    from agentcrawl.core import CrawlEngine, CrawlerConfig

    async with CrawlEngine.default() as engine:
        result = await engine.scrape(
            "https://example.com",
            config=CrawlerConfig(output_format="markdown"),
        )
        print(result.markdown)

    # Custom pipeline
    from agentcrawl.core import Pipeline, FetchStage, ParseStage, ConvertStage

    pipeline = (
        Pipeline.builder()
        .add(FetchStage(browser_manager))
        .add(ParseStage())
        .add(ConvertStage())
        .build()
    )

    # Session-based crawling
    from agentcrawl.core import CrawlSession

    async with CrawlSession(engine) as session:
        await session.goto("https://app.example.com/login")
        result = await session.scrape("https://app.example.com/dashboard")
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────
from agentcrawl.core.engine import (
    CrawlEngine,
    CrawlJobResult,
    CrawlResult,
    EngineStats,
)

# ──────────────────────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────────────────────
from agentcrawl.core.pipeline import (
    CacheReadStage,
    CacheWriteStage,
    ChunkStage,
    CitationStage,
    ConvertStage,
    ExtractionStage,
    FetchStage,
    FilterStage,
    NoOpStage,
    ParseStage,
    Pipeline,
    PipelineBuilder,
    PipelineContext,
    PipelineStage,
    ScreenshotStage,
    StageResult,
    StageStatus,
)

# ──────────────────────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────────────────────
from agentcrawl.core.session import (
    CrawlSession,
    PageVisit,
    SessionState,
)

# ──────────────────────────────────────────────────────────────
# Types (enums, protocols, type guards — no circular deps)
# ──────────────────────────────────────────────────────────────
from agentcrawl.core.types import (
    URL,
    # Type aliases
    AsyncCallback,
    Base64String,
    # Enums
    BrowserType,
    # Protocols
    Cacheable,
    CacheBackendType,
    Chunkable,
    ChunkerType,
    ChunkList,
    CitationList,
    ContentFilterType,
    Cookies,
    Crawlable,
    # TypedDicts
    CrawlJobResponseDict,
    CrawlRequestDict,
    CrawlStrategy,
    CssSelector,
    ErrorHandler,
    ErrorResponseDict,
    Extractable,
    ExtractionMethod,
    ExtractRequestDict,
    Filterable,
    Headers,
    HealthResponseDict,
    HtmlString,
    JobId,
    JobStatus,
    JsonDict,
    JsonList,
    JsonString,
    JsonValue,
    LinkList,
    LogLevel,
    MapRequestDict,
    MarkdownString,
    Metadata,
    OutputFormat,
    ProgressCallback,
    ProxyRotationStrategy,
    QueueBackendType,
    RequestId,
    Scrapable,
    ScrapeRequestDict,
    ScrapeResponseDict,
    Searchable,
    SearchRequestDict,
    Serializable,
    SessionId,
    Startable,
    SyncCallback,
    XPathExpression,
    # Type guards
    is_chunk,
    is_citation,
    is_crawl_job_result,
    is_crawl_result,
    is_html,
    is_json_dict,
    is_markdown,
    is_page_visit,
    is_pipeline_context,
    is_session_state,
    is_url,
)

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Engine
    "CrawlEngine",
    "CrawlResult",
    "CrawlJobResult",
    "EngineStats",
    # Pipeline
    "Pipeline",
    "PipelineBuilder",
    "PipelineContext",
    "PipelineStage",
    "StageResult",
    "StageStatus",
    "FetchStage",
    "ParseStage",
    "ConvertStage",
    "FilterStage",
    "ChunkStage",
    "CitationStage",
    "ExtractionStage",
    "ScreenshotStage",
    "CacheReadStage",
    "CacheWriteStage",
    "NoOpStage",
    # Session
    "CrawlSession",
    "PageVisit",
    "SessionState",
    # Enums
    "OutputFormat",
    "CrawlStrategy",
    "ExtractionMethod",
    "ContentFilterType",
    "ChunkerType",
    "JobStatus",
    "BrowserType",
    "CacheBackendType",
    "QueueBackendType",
    "ProxyRotationStrategy",
    "LogLevel",
    # Protocols
    "Scrapable",
    "Crawlable",
    "Searchable",
    "Cacheable",
    "Filterable",
    "Chunkable",
    "Extractable",
    "Serializable",
    "Startable",
    # Type guards
    "is_crawl_result",
    "is_crawl_job_result",
    "is_pipeline_context",
    "is_page_visit",
    "is_session_state",
    "is_chunk",
    "is_citation",
    "is_json_dict",
    "is_url",
    "is_html",
    "is_markdown",
    # TypedDicts
    "ScrapeRequestDict",
    "ScrapeResponseDict",
    "CrawlRequestDict",
    "CrawlJobResponseDict",
    "SearchRequestDict",
    "MapRequestDict",
    "ExtractRequestDict",
    "HealthResponseDict",
    "ErrorResponseDict",
    # Type aliases
    "URL",
    "HtmlString",
    "MarkdownString",
    "JsonString",
    "CssSelector",
    "XPathExpression",
    "Base64String",
    "SessionId",
    "JobId",
    "RequestId",
    "JsonDict",
    "JsonList",
    "JsonValue",
    "Headers",
    "Cookies",
    "Metadata",
    "LinkList",
    "ChunkList",
    "CitationList",
    "AsyncCallback",
    "SyncCallback",
    "ErrorHandler",
    "ProgressCallback",
]
