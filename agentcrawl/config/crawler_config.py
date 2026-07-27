"""
AgentCrawl — Crawler Run Configuration
=========================================

Per-request configuration for scrape, crawl, search, and extract
operations. Controls output format, content processing, extraction
strategies, page actions, caching, and request-level overrides.

This is the primary configuration object passed to every crawl
operation in both Package Mode and Server Mode.

Usage:
    from agentcrawl.config.crawler_config import CrawlerConfig

    # Simple
    config = CrawlerConfig(output_format="markdown")

    # Full configuration
    config = CrawlerConfig(
        output_format="markdown",
        include_links=True,
        include_metadata=True,
        include_screenshot=False,
        cache=True,
        cache_ttl=600,
        timeout=30,
        wait_for_selector="#content-loaded",
        actions=[
            {"type": "click", "selector": "#accept-cookies"},
            {"type": "scroll", "direction": "down", "amount": 3},
        ],
        content_filter="bm25",
        content_filter_query="machine learning",
        chunker="topic",
        chunk_max_size=1000,
        chunk_overlap=200,
    )

    # With extraction strategy
    from agentcrawl.extraction import LLMExtractor
    config = CrawlerConfig(extraction=LLMExtractor(schema=MyModel))

    # From dictionary (API request)
    config = CrawlerConfig.from_dict(request.json())
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ══════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════

class OutputFormat(str, Enum):
    """Supported output formats."""
    MARKDOWN = "markdown"
    JSON = "json"
    HTML = "html"
    TEXT = "text"


class ContentFilterType(str, Enum):
    """Available content filter types."""
    NONE = "none"
    BM25 = "bm25"
    PRUNING = "pruning"


class ChunkerType(str, Enum):
    """Available chunker types."""
    NONE = "none"
    TOPIC = "topic"
    REGEX = "regex"
    SENTENCE = "sentence"
    FIXED = "fixed"


class WaitStrategy(str, Enum):
    """Page wait strategies before content extraction."""
    LOAD = "load"
    DOM_CONTENT_LOADED = "domcontentloaded"
    NETWORK_IDLE = "networkidle"
    SELECTOR = "selector"
    TIMEOUT = "timeout"
    FUNCTION = "function"


# ══════════════════════════════════════════════════════════════
# Screenshot Options
# ══════════════════════════════════════════════════════════════

@dataclass
class ScreenshotOptions:
    """
    Screenshot capture options.

    Attributes:
        enabled: Whether to capture a screenshot.
        full_page: Capture the entire scrollable page.
        format: Image format ('png' or 'jpeg').
        quality: JPEG quality (1-100).
        selector: Capture a specific element only.
        viewport_width: Override viewport width.
        viewport_height: Override viewport height.
        wait_before_ms: Milliseconds to wait before capture.
    """
    enabled: bool = False
    full_page: bool = True
    format: str = "png"
    quality: int = 80
    selector: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    wait_before_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "full_page": self.full_page,
            "format": self.format,
            "quality": self.quality,
            "selector": self.selector,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "wait_before_ms": self.wait_before_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScreenshotOptions:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
# Wait Options
# ══════════════════════════════════════════════════════════════

@dataclass
class WaitOptions:
    """
    Wait conditions before content extraction.

    Attributes:
        strategy: Wait strategy type.
        selector: CSS selector to wait for (for SELECTOR strategy).
        timeout_ms: Maximum wait time in milliseconds.
        milliseconds: Fixed wait duration (for TIMEOUT strategy).
        expression: JavaScript expression (for FUNCTION strategy).
        load_state: Load state to wait for (for LOAD strategy).
    """
    strategy: WaitStrategy = WaitStrategy.LOAD
    selector: str | None = None
    timeout_ms: int = 30_000
    milliseconds: int = 0
    expression: str | None = None
    load_state: str = "load"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "selector": self.selector,
            "timeout_ms": self.timeout_ms,
            "milliseconds": self.milliseconds,
            "expression": self.expression,
            "load_state": self.load_state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaitOptions:
        strategy = data.get("strategy", "load")
        if isinstance(strategy, str):
            try:
                strategy = WaitStrategy(strategy)
            except ValueError:
                strategy = WaitStrategy.LOAD
        return cls(
            strategy=strategy,
            selector=data.get("selector"),
            timeout_ms=data.get("timeout_ms", 30_000),
            milliseconds=data.get("milliseconds", 0),
            expression=data.get("expression"),
            load_state=data.get("load_state", "load"),
        )


# ══════════════════════════════════════════════════════════════
# Main Crawler Configuration
# ══════════════════════════════════════════════════════════════

@dataclass
class CrawlerConfig:
    """
    Per-request configuration for crawl operations.

    Controls every aspect of a scrape/crawl/search/extract request,
    from output format and content processing to extraction strategies,
    page actions, and caching.

    Attributes:
        output_format: Output format ('markdown', 'json', 'html', 'text').
        include_links: Include extracted links in the result.
        include_metadata: Include page metadata (title, description, og:tags).
        include_screenshot: Capture a page screenshot.
        screenshot: Detailed screenshot options.
        include_raw_html: Include the raw HTML in the result.
        include_citations: Include numbered citation references.
        only_main_content: Extract only the main content (skip nav, footer, etc.).
        selectors: CSS selectors to target specific content.
        exclude_selectors: CSS selectors to exclude from extraction.
        xpath: XPath expression for targeted extraction.
        extraction: Extraction strategy instance (LLM, CSS, XPath, etc.).
        actions: Page actions to perform before extraction.
        wait: Wait conditions before extraction.
        content_filter: Content filter type ('none', 'bm25', 'pruning').
        content_filter_query: Query for BM25 relevance scoring.
        content_filter_threshold: Minimum relevance score threshold.
        chunker: Chunker type ('none', 'topic', 'regex', 'sentence', 'fixed').
        chunk_max_size: Maximum chunk size in characters.
        chunk_overlap: Overlap between chunks in characters.
        chunk_pattern: Regex pattern for regex chunker.
        cache: Whether to use caching for this request.
        cache_ttl: Cache TTL override in seconds.
        timeout: Request timeout in seconds.
        headers: Additional HTTP headers for this request.
        user_agent: Override User-Agent for this request.
        proxy_url: Override proxy for this request.
        follow_redirects: Whether to follow HTTP redirects.
        max_redirects: Maximum number of redirects to follow.
        accept_status_codes: HTTP status codes to accept (default: [200]).
        process_pdf: Whether to process PDF content.
        process_docx: Whether to process DOCX content.
        remove_overlay_elements: Remove popups, modals, cookie banners.
        simulate_user: Simulate human-like behavior (random delays, mouse moves).
        magic: Enable automatic content optimization (best-effort).
        word_count_threshold: Minimum word count for content blocks.
        page_timeout_ms: Page-level timeout in milliseconds.
        navigation_timeout_ms: Navigation timeout in milliseconds.
        extra: Arbitrary extra parameters for extensibility.
    """

    # ── Output ────────────────────────────────────────────────
    output_format: OutputFormat | str = OutputFormat.MARKDOWN
    include_links: bool = True
    include_metadata: bool = True
    include_screenshot: bool = False
    screenshot: ScreenshotOptions = field(default_factory=ScreenshotOptions)
    include_raw_html: bool = False
    include_citations: bool = False
    only_main_content: bool = True

    # ── Targeting ─────────────────────────────────────────────
    selectors: list[str] = field(default_factory=list)
    exclude_selectors: list[str] = field(default_factory=list)
    xpath: str | None = None

    # ── Extraction ────────────────────────────────────────────
    extraction: Any = None  # ExtractionStrategy instance

    # ── Actions & Wait ────────────────────────────────────────
    actions: list[dict[str, Any]] | Any = field(default_factory=list)
    wait: WaitOptions = field(default_factory=WaitOptions)

    # ── Content Processing ────────────────────────────────────
    content_filter: ContentFilterType | str = ContentFilterType.NONE
    content_filter_query: str | None = None
    content_filter_threshold: float = 1.0
    chunker: ChunkerType | str = ChunkerType.NONE
    chunk_max_size: int = 1000
    chunk_overlap: int = 200
    chunk_pattern: str | None = None

    # ── Caching ───────────────────────────────────────────────
    cache: bool = True
    cache_ttl: int | None = None

    # ── Timeouts ──────────────────────────────────────────────
    timeout: int = 30
    page_timeout_ms: int = 30_000
    navigation_timeout_ms: int = 30_000

    # ── Request Overrides ─────────────────────────────────────
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str | None = None
    proxy_url: str | None = None
    follow_redirects: bool = True
    max_redirects: int = 10
    accept_status_codes: list[int] = field(default_factory=lambda: [200])

    # ── Media Processing ──────────────────────────────────────
    process_pdf: bool = True
    process_docx: bool = False

    # ── Content Cleanup ───────────────────────────────────────
    remove_overlay_elements: bool = True
    simulate_user: bool = False
    magic: bool = False
    word_count_threshold: int = 10

    # ── Extensibility ─────────────────────────────────────────
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalize enums
        if isinstance(self.output_format, str):
            try:
                self.output_format = OutputFormat(self.output_format)
            except ValueError:
                self.output_format = OutputFormat.MARKDOWN

        if isinstance(self.content_filter, str):
            try:
                self.content_filter = ContentFilterType(self.content_filter)
            except ValueError:
                self.content_filter = ContentFilterType.NONE

        if isinstance(self.chunker, str):
            try:
                self.chunker = ChunkerType(self.chunker)
            except ValueError:
                self.chunker = ChunkerType.NONE

        # Sync screenshot flag
        if self.include_screenshot and not self.screenshot.enabled:
            self.screenshot.enabled = True

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self, exclude_none: bool = True) -> dict[str, Any]:
        """
        Convert to a plain dictionary (JSON-serializable).

        Args:
            exclude_none: Whether to exclude None values.

        Returns:
            Configuration dictionary.
        """
        result: dict[str, Any] = {
            "output_format": self.output_format.value if isinstance(self.output_format, OutputFormat) else self.output_format,
            "include_links": self.include_links,
            "include_metadata": self.include_metadata,
            "include_screenshot": self.include_screenshot,
            "screenshot": self.screenshot.to_dict(),
            "include_raw_html": self.include_raw_html,
            "include_citations": self.include_citations,
            "only_main_content": self.only_main_content,
            "selectors": self.selectors,
            "exclude_selectors": self.exclude_selectors,
            "xpath": self.xpath,
            "actions": self.actions if isinstance(self.actions, list) else [],
            "wait": self.wait.to_dict(),
            "content_filter": self.content_filter.value if isinstance(self.content_filter, ContentFilterType) else self.content_filter,
            "content_filter_query": self.content_filter_query,
            "content_filter_threshold": self.content_filter_threshold,
            "chunker": self.chunker.value if isinstance(self.chunker, ChunkerType) else self.chunker,
            "chunk_max_size": self.chunk_max_size,
            "chunk_overlap": self.chunk_overlap,
            "chunk_pattern": self.chunk_pattern,
            "cache": self.cache,
            "cache_ttl": self.cache_ttl,
            "timeout": self.timeout,
            "page_timeout_ms": self.page_timeout_ms,
            "navigation_timeout_ms": self.navigation_timeout_ms,
            "headers": self.headers,
            "user_agent": self.user_agent,
            "proxy_url": self.proxy_url,
            "follow_redirects": self.follow_redirects,
            "max_redirects": self.max_redirects,
            "accept_status_codes": self.accept_status_codes,
            "process_pdf": self.process_pdf,
            "process_docx": self.process_docx,
            "remove_overlay_elements": self.remove_overlay_elements,
            "simulate_user": self.simulate_user,
            "magic": self.magic,
            "word_count_threshold": self.word_count_threshold,
            "extra": self.extra,
        }

        # Exclude extraction strategy (not serializable)
        if self.extraction is not None:
            result["extraction"] = type(self.extraction).__name__

        if exclude_none:
            result = {k: v for k, v in result.items() if v is not None}

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrawlerConfig:
        """
        Create a CrawlerConfig from a dictionary.

        Handles nested objects (screenshot, wait) and enum normalization.

        Args:
            data: Configuration dictionary (e.g., from API request).

        Returns:
            CrawlerConfig instance.
        """
        # Handle screenshot
        screenshot = data.get("screenshot")
        if isinstance(screenshot, dict):
            screenshot = ScreenshotOptions.from_dict(screenshot)
        elif isinstance(screenshot, bool):
            screenshot = ScreenshotOptions(enabled=screenshot)
        else:
            screenshot = ScreenshotOptions()

        # Handle wait
        wait = data.get("wait")
        if isinstance(wait, dict):
            wait = WaitOptions.from_dict(wait)
        elif isinstance(wait, str):
            # Simple selector shorthand
            wait = WaitOptions(strategy=WaitStrategy.SELECTOR, selector=wait)
        elif isinstance(wait, int):
            # Simple timeout shorthand (ms)
            wait = WaitOptions(strategy=WaitStrategy.TIMEOUT, milliseconds=wait)
        else:
            wait = WaitOptions()

        # Handle actions
        actions = data.get("actions", [])
        if isinstance(actions, str):
            try:
                actions = json.loads(actions)
            except json.JSONDecodeError:
                actions = []

        # Filter to known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}

        return cls(
            screenshot=screenshot,
            wait=wait,
            actions=actions,
            **{k: v for k, v in filtered.items() if k not in ("screenshot", "wait", "actions")},
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> CrawlerConfig:
        """Create from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ──────────────────────────────────────────────────────────
    # Cache Key Generation
    # ──────────────────────────────────────────────────────────

    def cache_key_suffix(self) -> str:
        """
        Generate a hash suffix representing the configuration
        parameters that affect the output.

        Used by CacheManager to differentiate cached results
        for the same URL with different configs.

        Returns:
            Short hash string.
        """
        # Only include fields that affect output
        relevant = {
            "output_format": str(self.output_format),
            "include_links": self.include_links,
            "include_metadata": self.include_metadata,
            "only_main_content": self.only_main_content,
            "selectors": self.selectors,
            "exclude_selectors": self.exclude_selectors,
            "xpath": self.xpath,
            "content_filter": str(self.content_filter),
            "content_filter_query": self.content_filter_query,
            "chunker": str(self.chunker),
            "chunk_max_size": self.chunk_max_size,
            "chunk_overlap": self.chunk_overlap,
            "remove_overlay_elements": self.remove_overlay_elements,
            "word_count_threshold": self.word_count_threshold,
        }

        if self.extraction is not None:
            relevant["extraction"] = type(self.extraction).__name__

        raw = json.dumps(relevant, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ──────────────────────────────────────────────────────────
    # Merge / Override
    # ──────────────────────────────────────────────────────────

    def merge(self, overrides: dict[str, Any]) -> CrawlerConfig:
        """
        Create a new config with overridden values.

        Args:
            overrides: Dictionary of field names to new values.

        Returns:
            New CrawlerConfig with merged values.
        """
        current = self.to_dict(exclude_none=False)
        current.update(overrides)
        # Preserve extraction strategy object
        if self.extraction is not None and "extraction" not in overrides:
            current["extraction"] = self.extraction
        return CrawlerConfig.from_dict(current)

    def with_output_format(self, fmt: str | OutputFormat) -> CrawlerConfig:
        """Return a copy with a different output format."""
        return self.merge({"output_format": fmt})

    def with_cache(self, enabled: bool, ttl: int | None = None) -> CrawlerConfig:
        """Return a copy with cache settings changed."""
        return self.merge({"cache": enabled, "cache_ttl": ttl})

    def with_timeout(self, seconds: int) -> CrawlerConfig:
        """Return a copy with a different timeout."""
        return self.merge({
            "timeout": seconds,
            "page_timeout_ms": seconds * 1000,
            "navigation_timeout_ms": seconds * 1000,
        })

    def with_selectors(
        self,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> CrawlerConfig:
        """Return a copy with CSS selectors changed."""
        return self.merge({
            "selectors": include or self.selectors,
            "exclude_selectors": exclude or self.exclude_selectors,
        })

    def with_actions(self, actions: list[dict[str, Any]]) -> CrawlerConfig:
        """Return a copy with page actions changed."""
        return self.merge({"actions": actions})

    def with_content_filter(
        self,
        filter_type: str | ContentFilterType,
        query: str | None = None,
        threshold: float | None = None,
    ) -> CrawlerConfig:
        """Return a copy with content filter changed."""
        return self.merge({
            "content_filter": filter_type,
            "content_filter_query": query or self.content_filter_query,
            "content_filter_threshold": threshold or self.content_filter_threshold,
        })

    def with_chunker(
        self,
        chunker_type: str | ChunkerType,
        max_size: int | None = None,
        overlap: int | None = None,
    ) -> CrawlerConfig:
        """Return a copy with chunker changed."""
        return self.merge({
            "chunker": chunker_type,
            "chunk_max_size": max_size or self.chunk_max_size,
            "chunk_overlap": overlap or self.chunk_overlap,
        })

    # ──────────────────────────────────────────────────────────
    # Presets
    # ──────────────────────────────────────────────────────────

    @classmethod
    def default(cls) -> CrawlerConfig:
        """Default configuration (markdown, cached, main content only)."""
        return cls()

    @classmethod
    def llm_ready(cls) -> CrawlerConfig:
        """Optimized for LLM consumption (clean markdown, no noise)."""
        return cls(
            output_format=OutputFormat.MARKDOWN,
            only_main_content=True,
            remove_overlay_elements=True,
            include_links=True,
            include_metadata=True,
            include_citations=True,
            word_count_threshold=20,
        )

    @classmethod
    def rag_ready(cls, query: str = "", chunk_size: int = 1000) -> CrawlerConfig:
        """Optimized for RAG pipelines (filtered, chunked)."""
        return cls(
            output_format=OutputFormat.MARKDOWN,
            only_main_content=True,
            remove_overlay_elements=True,
            content_filter=ContentFilterType.BM25 if query else ContentFilterType.PRUNING,
            content_filter_query=query or None,
            chunker=ChunkerType.TOPIC,
            chunk_max_size=chunk_size,
            chunk_overlap=200,
            include_citations=True,
        )

    @classmethod
    def full_archive(cls) -> CrawlerConfig:
        """Capture everything (HTML, screenshot, links, metadata)."""
        return cls(
            output_format=OutputFormat.MARKDOWN,
            include_links=True,
            include_metadata=True,
            include_screenshot=True,
            include_raw_html=True,
            only_main_content=False,
            remove_overlay_elements=False,
            cache=False,
        )

    @classmethod
    def fast_scrape(cls) -> CrawlerConfig:
        """Fastest possible scrape (minimal processing)."""
        return cls(
            output_format=OutputFormat.MARKDOWN,
            only_main_content=True,
            include_links=False,
            include_metadata=False,
            include_screenshot=False,
            remove_overlay_elements=False,
            cache=True,
        )

    @classmethod
    def structured_data(cls) -> CrawlerConfig:
        """Optimized for structured data extraction."""
        return cls(
            output_format=OutputFormat.JSON,
            include_links=False,
            include_metadata=True,
            only_main_content=False,
        )

    # ──────────────────────────────────────────────────────────
    # Validation
    # ──────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        Validate the configuration and return a list of warnings.

        Returns:
            List of warning messages (empty if valid).
        """
        warnings: list[str] = []

        if self.timeout < 5:
            warnings.append("Timeout < 5s may cause premature failures")

        if self.chunk_max_size < 100:
            warnings.append("chunk_max_size < 100 may produce very small chunks")

        if self.chunk_overlap >= self.chunk_max_size:
            warnings.append("chunk_overlap >= chunk_max_size will cause infinite loops")

        if (
            self.content_filter == ContentFilterType.BM25
            and not self.content_filter_query
        ):
            warnings.append("BM25 filter requires content_filter_query")

        if self.include_screenshot and self.output_format == OutputFormat.JSON:
            warnings.append("Screenshot with JSON output — screenshot will be base64 in JSON")

        if self.selectors and self.xpath:
            warnings.append("Both selectors and xpath set — selectors take priority")

        return warnings

    # ──────────────────────────────────────────────────────────
    # Representation
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        fmt = self.output_format.value if isinstance(self.output_format, OutputFormat) else self.output_format
        parts = [f"format={fmt}"]

        if self.selectors:
            parts.append(f"selectors={self.selectors}")
        if self.extraction:
            parts.append(f"extraction={type(self.extraction).__name__}")
        if self.actions:
            parts.append(f"actions={len(self.actions)}")
        if self.content_filter != ContentFilterType.NONE:
            parts.append(f"filter={self.content_filter}")
        if self.chunker != ChunkerType.NONE:
            parts.append(f"chunker={self.chunker}")
        if not self.cache:
            parts.append("no_cache")

        return f"CrawlerConfig({', '.join(parts)})"