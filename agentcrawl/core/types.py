"""
AgentCrawl — Core Type Definitions
======================================

Shared type definitions, protocols, enums, and type aliases used
across all AgentCrawl modules. Provides a single import point for
common types.

Usage:
    from agentcrawl.core.types import (
        URL,
        HtmlString,
        MarkdownString,
        JsonDict,
        CrawlResult,
        CrawlJobResult,
        PipelineContext,
        PageVisit,
        SessionState,
        OutputFormat,
        CrawlStrategy,
        ExtractionMethod,
        is_crawl_result,
        is_pipeline_context,
    )
"""

from __future__ import annotations

from enum import Enum
from typing import (
    Any,
    Callable,
    Coroutine,
    Protocol,
    TypeAlias,
    TypeGuard,
    TypedDict,
    runtime_checkable,
)


# ══════════════════════════════════════════════════════════════
# Type Aliases
# ══════════════════════════════════════════════════════════════

# Basic types
URL: TypeAlias = str
HtmlString: TypeAlias = str
MarkdownString: TypeAlias = str
JsonString: TypeAlias = str
CssSelector: TypeAlias = str
XPathExpression: TypeAlias = str
Base64String: TypeAlias = str
SessionId: TypeAlias = str
JobId: TypeAlias = str
RequestId: TypeAlias = str

# Composite types
JsonDict: TypeAlias = dict[str, Any]
JsonList: TypeAlias = list[Any]
JsonValue: TypeAlias = str | int | float | bool | None | JsonDict | JsonList
Headers: TypeAlias = dict[str, str]
Cookies: TypeAlias = list[dict[str, Any]]
Metadata: TypeAlias = dict[str, Any]
LinkList: TypeAlias = list[dict[str, Any]]
ChunkList: TypeAlias = list[dict[str, Any]]
CitationList: TypeAlias = list[dict[str, Any]]

# Callback types
AsyncCallback: TypeAlias = Callable[..., Coroutine[Any, Any, None]]
SyncCallback: TypeAlias = Callable[..., None]
ErrorHandler: TypeAlias = Callable[[Exception], Coroutine[Any, Any, bool]]
ProgressCallback: TypeAlias = Callable[[int, int, str], None]  # (current, total, message)


# ══════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════

class OutputFormat(str, Enum):
    """Supported output formats for scraped content."""
    MARKDOWN = "markdown"
    JSON = "json"
    HTML = "html"
    TEXT = "text"


class CrawlStrategy(str, Enum):
    """Available crawling strategies."""
    BFS = "bfs"
    DFS = "dfs"
    BEST_FIRST = "best_first"
    ADAPTIVE = "adaptive"


class ExtractionMethod(str, Enum):
    """Available extraction methods."""
    LLM = "llm"
    CSS = "css"
    XPATH = "xpath"
    COSINE = "cosine"
    REGEX = "regex"


class ContentFilterType(str, Enum):
    """Available content filter types."""
    NONE = "none"
    BM25 = "bm25"
    PRUNING = "pruning"
    ADVANCED_PRUNING = "advanced_pruning"


class ChunkerType(str, Enum):
    """Available chunker types."""
    NONE = "none"
    FIXED = "fixed"
    SENTENCE = "sentence"
    REGEX = "regex"
    TOPIC = "topic"
    MARKDOWN = "markdown"


class JobStatus(str, Enum):
    """Status of an async crawl job."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BrowserType(str, Enum):
    """Supported browser engines."""
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class CacheBackendType(str, Enum):
    """Available cache backends."""
    MEMORY = "memory"
    REDIS = "redis"
    DISK = "disk"
    NONE = "none"


class QueueBackendType(str, Enum):
    """Available queue backends."""
    MEMORY = "memory"
    REDIS = "redis"


class ProxyRotationStrategy(str, Enum):
    """Proxy rotation strategies."""
    NONE = "none"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"


class LogLevel(str, Enum):
    """Logging levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ══════════════════════════════════════════════════════════════
# TypedDicts (for API responses and structured data)
# ══════════════════════════════════════════════════════════════

class ScrapeRequestDict(TypedDict, total=False):
    """Typed dictionary for scrape API requests."""
    url: str
    output_format: str
    include_links: bool
    include_metadata: bool
    include_screenshot: bool
    only_main_content: bool
    selectors: list[str]
    exclude_selectors: list[str]
    actions: list[dict[str, Any]]
    wait_for_selector: str
    timeout: int
    cache: bool
    cache_ttl: int
    content_filter: str
    content_filter_query: str
    chunker: str
    chunk_max_size: int
    chunk_overlap: int


class ScrapeResponseDict(TypedDict, total=False):
    """Typed dictionary for scrape API responses."""
    url: str
    success: bool
    status_code: int
    markdown: str
    html: str
    text: str
    json: dict[str, Any]
    metadata: dict[str, Any]
    links: dict[str, list[dict[str, Any]]]
    citations: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    extracted_data: Any
    screenshot: str
    error: str
    response_time_ms: float
    word_count: int
    token_count: int
    cached: bool
    request_id: str


class CrawlRequestDict(TypedDict, total=False):
    """Typed dictionary for crawl API requests."""
    url: str
    strategy: str
    max_depth: int
    max_pages: int
    output_format: str
    include_patterns: list[str]
    exclude_patterns: list[str]
    same_domain_only: bool
    webhook_url: str


class CrawlJobResponseDict(TypedDict, total=False):
    """Typed dictionary for crawl job responses."""
    job_id: str
    status: str
    start_url: str
    total_pages: int
    successful_pages: int
    failed_pages: int
    total_words: int
    total_tokens: int
    duration_ms: float
    pages: list[dict[str, Any]]


class SearchRequestDict(TypedDict, total=False):
    """Typed dictionary for search API requests."""
    query: str
    max_results: int
    scrape_results: bool
    output_format: str
    search_engine: str


class MapRequestDict(TypedDict, total=False):
    """Typed dictionary for map API requests."""
    url: str
    max_urls: int
    use_sitemap: bool
    use_robots: bool
    include_patterns: list[str]
    exclude_patterns: list[str]


class ExtractRequestDict(TypedDict, total=False):
    """Typed dictionary for extract API requests."""
    url: str
    schema: dict[str, Any]
    method: str
    prompt: str


class HealthResponseDict(TypedDict, total=False):
    """Typed dictionary for health check responses."""
    status: str
    version: str
    uptime_seconds: float
    browser_connected: bool
    cache_backend: str
    queue_backend: str
    active_pages: int
    total_scrapes: int


class ErrorResponseDict(TypedDict, total=False):
    """Typed dictionary for error responses."""
    error: str
    detail: str
    status_code: int
    request_id: str


# ══════════════════════════════════════════════════════════════
# Protocols (Structural Typing)
# ══════════════════════════════════════════════════════════════

@runtime_checkable
class Scrapable(Protocol):
    """Protocol for objects that can scrape a URL."""

    async def scrape(
        self,
        url: str,
        config: Any = None,
    ) -> Any: ...


@runtime_checkable
class Crawlable(Protocol):
    """Protocol for objects that can crawl a website."""

    async def crawl(
        self,
        url: str,
        strategy: Any = None,
        config: Any = None,
    ) -> Any: ...


@runtime_checkable
class Searchable(Protocol):
    """Protocol for objects that can search the web."""

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> Any: ...


@runtime_checkable
class Cacheable(Protocol):
    """Protocol for cache backends."""

    async def get(self, key: str, default: Any = None) -> Any: ...
    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool: ...
    async def delete(self, key: str) -> bool: ...
    async def exists(self, key: str) -> bool: ...
    async def clear(self) -> bool: ...


@runtime_checkable
class Filterable(Protocol):
    """Protocol for content filters."""

    def apply(self, text: str, **kwargs: Any) -> Any: ...


@runtime_checkable
class Chunkable(Protocol):
    """Protocol for content chunkers."""

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> Any: ...


@runtime_checkable
class Extractable(Protocol):
    """Protocol for extraction strategies."""

    async def extract(
        self,
        html: str = "",
        markdown: str = "",
        url: str = "",
    ) -> Any: ...


@runtime_checkable
class Serializable(Protocol):
    """Protocol for objects that can be serialized to dict/JSON."""

    def to_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class Startable(Protocol):
    """Protocol for objects with async lifecycle."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...


# ══════════════════════════════════════════════════════════════
# Type Guards
# ══════════════════════════════════════════════════════════════

def is_crawl_result(obj: Any) -> TypeGuard[Any]:
    """Check if an object is a CrawlResult."""
    return (
        hasattr(obj, "url")
        and hasattr(obj, "success")
        and hasattr(obj, "markdown")
        and hasattr(obj, "status_code")
    )


def is_crawl_job_result(obj: Any) -> TypeGuard[Any]:
    """Check if an object is a CrawlJobResult."""
    return (
        hasattr(obj, "job_id")
        and hasattr(obj, "pages")
        and hasattr(obj, "total_pages")
        and hasattr(obj, "status")
    )


def is_pipeline_context(obj: Any) -> TypeGuard[Any]:
    """Check if an object is a PipelineContext."""
    return (
        hasattr(obj, "url")
        and hasattr(obj, "raw_html")
        and hasattr(obj, "markdown")
        and hasattr(obj, "stage_results")
    )


def is_page_visit(obj: Any) -> TypeGuard[Any]:
    """Check if an object is a PageVisit."""
    return (
        hasattr(obj, "url")
        and hasattr(obj, "timestamp")
        and hasattr(obj, "status_code")
        and hasattr(obj, "success")
    )


def is_session_state(obj: Any) -> TypeGuard[Any]:
    """Check if an object is a SessionState."""
    return (
        hasattr(obj, "session_id")
        and hasattr(obj, "cookies")
        and hasattr(obj, "history")
        and hasattr(obj, "is_expired")
    )


def is_chunk(obj: Any) -> TypeGuard[Any]:
    """Check if an object is a Chunk."""
    return (
        hasattr(obj, "text")
        and hasattr(obj, "index")
        and hasattr(obj, "token_count")
        and hasattr(obj, "chunk_id")
    )


def is_citation(obj: Any) -> TypeGuard[Any]:
    """Check if an object is a Citation."""
    return (
        hasattr(obj, "number")
        and hasattr(obj, "url")
        and hasattr(obj, "display_title")
    )


def is_json_dict(obj: Any) -> TypeGuard[JsonDict]:
    """Check if an object is a JSON-compatible dictionary."""
    return isinstance(obj, dict)


def is_url(text: str) -> bool:
    """Check if a string looks like a URL."""
    return text.startswith(("http://", "https://", "ftp://"))


def is_html(text: str) -> bool:
    """Check if a string looks like HTML."""
    stripped = text.strip()
    return (
        stripped.startswith("<!DOCTYPE")
        or stripped.startswith("<html")
        or stripped.startswith("<div")
        or stripped.startswith("<p")
        or "<html" in stripped[:500]
    )


def is_markdown(text: str) -> bool:
    """Check if a string looks like Markdown (heuristic)."""
    import re
    md_patterns = [
        r"^#{1,6}\s",       # Headings
        r"^\*\*.+\*\*",     # Bold
        r"^\[.+\]\(.+\)",   # Links
        r"^```",            # Code blocks
        r"^\s*[-*+]\s",     # List items
        r"^>",              # Blockquotes
    ]
    for pattern in md_patterns:
        if re.search(pattern, text, re.MULTILINE):
            return True
    return False


# ══════════════════════════════════════════════════════════════
# Re-exports from core modules
# ══════════════════════════════════════════════════════════════

# These are imported lazily to avoid circular dependencies.
# Use direct imports from the source modules for type checking.

def __getattr__(name: str) -> Any:
    """Lazy import for core types to avoid circular dependencies."""
    if name == "CrawlResult":
        from agentcrawl.core.engine import CrawlResult
        return CrawlResult
    if name == "CrawlJobResult":
        from agentcrawl.core.engine import CrawlJobResult
        return CrawlJobResult
    if name == "EngineStats":
        from agentcrawl.core.engine import EngineStats
        return EngineStats
    if name == "PipelineContext":
        from agentcrawl.core.pipeline import PipelineContext
        return PipelineContext
    if name == "StageResult":
        from agentcrawl.core.pipeline import StageResult
        return StageResult
    if name == "PipelineStage":
        from agentcrawl.core.pipeline import PipelineStage
        return PipelineStage
    if name == "Pipeline":
        from agentcrawl.core.pipeline import Pipeline
        return Pipeline
    if name == "CrawlSession":
        from agentcrawl.core.session import CrawlSession
        return CrawlSession
    if name == "PageVisit":
        from agentcrawl.core.session import PageVisit
        return PageVisit
    if name == "SessionState":
        from agentcrawl.core.session import SessionState
        return SessionState
    raise AttributeError(f"module 'agentcrawl.core.types' has no attribute {name!r}")


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

__all__ = [
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
    # Lazy re-exports (via __getattr__)
    "CrawlResult",
    "CrawlJobResult",
    "EngineStats",
    "PipelineContext",
    "StageResult",
    "PipelineStage",
    "Pipeline",
    "CrawlSession",
    "PageVisit",
    "SessionState",
]