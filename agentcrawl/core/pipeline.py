"""
AgentCrawl — Processing Pipeline
====================================

Composable, stage-based processing pipeline for web content.
Each stage transforms a shared PipelineContext, allowing flexible
composition of fetch → parse → extract → filter → chunk → output.

Architecture:
    PipelineContext (shared state)
        │
        ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │  Fetch  │──▶│  Parse   │──▶│ Convert │──▶│  Filter  │──▶ ...
    │  Stage  │    │  Stage  │    │  Stage  │    │  Stage  │
    └─────────┘    └─────────┘    └─────────┘    └─────────┘

Usage:
    from agentcrawl.core.pipeline import (
        Pipeline,
        PipelineContext,
        FetchStage,
        ParseStage,
        ConvertStage,
        FilterStage,
        ChunkStage,
        CitationStage,
    )

    # Build a custom pipeline
    pipeline = (
        Pipeline.builder()
        .add(FetchStage())
        .add(ParseStage())
        .add(ConvertStage())
        .add(FilterStage())
        .add(ChunkStage())
        .add(CitationStage())
        .build()
    )

    # Execute
    context = PipelineContext(url="https://example.com", config=config)
    result = await pipeline.execute(context)
    print(context.markdown)

    # Or use pre-built pipelines
    pipeline = Pipeline.scrape_pipeline()
    pipeline = Pipeline.rag_pipeline()
    pipeline = Pipeline.extract_pipeline()
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("agentcrawl.core.pipeline")


# ══════════════════════════════════════════════════════════════
# Pipeline Context
# ══════════════════════════════════════════════════════════════

class StageStatus(str, Enum):
    """Status of a pipeline stage execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class StageResult:
    """Result of a single stage execution."""
    stage_name: str
    status: StageStatus = StageStatus.PENDING
    duration_ms: float = 0.0
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_name,
            "status": self.status.value,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
        }


@dataclass
class PipelineContext:
    """
    Shared state passed through all pipeline stages.

    Each stage reads from and writes to this context, allowing
    data to flow through the pipeline without tight coupling
    between stages.

    Attributes:
        url: The target URL.
        config: CrawlerConfig for this request.
        raw_html: Raw HTML from the browser.
        status_code: HTTP status code.
        page: Playwright Page instance (transient, not serialized).
        metadata: Extracted page metadata.
        links: Extracted links.
        main_content_html: Cleaned main content HTML.
        main_content_text: Plain text content.
        markdown: Converted Markdown content.
        html: Cleaned HTML output.
        json: Structured JSON output.
        text: Plain text output.
        filtered_text: Text after content filtering.
        chunks: Content chunks.
        citations: Extracted citations.
        extracted_data: Structured extraction result.
        screenshot: Base64 screenshot.
        error: Error message (if pipeline failed).
        stage_results: Results from each stage.
        extra: Arbitrary extra data for custom stages.
    """
    # Input
    url: str = ""
    config: Any = None  # CrawlerConfig

    # Fetch stage
    raw_html: str = ""
    status_code: int = 0
    page: Any = None  # Transient — not serialized

    # Parse stage
    metadata: dict[str, Any] = field(default_factory=dict)
    links: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    main_content_html: str = ""
    main_content_text: str = ""
    headings: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)

    # Convert stage
    markdown: str = ""
    html: str = ""
    json: dict[str, Any] | None = None
    text: str = ""

    # Filter stage
    filtered_text: str = ""
    filter_stats: dict[str, Any] = field(default_factory=dict)

    # Chunk stage
    chunks: list[dict[str, Any]] = field(default_factory=list)
    chunk_stats: dict[str, Any] = field(default_factory=dict)

    # Citation stage
    citations: list[dict[str, Any]] = field(default_factory=dict)
    bibliography: str = ""

    # Extraction stage
    extracted_data: Any = None

    # Screenshot stage
    screenshot: str = ""

    # Pipeline state
    error: str | None = None
    stage_results: list[StageResult] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def output_content(self) -> str:
        """Get the primary output content based on config."""
        if self.config:
            fmt = str(getattr(self.config, "output_format", "markdown"))
            if fmt == "html":
                return self.html or self.main_content_html
            elif fmt == "json":
                import json as json_mod
                return json_mod.dumps(self.json or {}, ensure_ascii=False)
            elif fmt == "text":
                return self.text or self.main_content_text
        return self.markdown or self.filtered_text or self.main_content_text

    @property
    def word_count(self) -> int:
        content = self.output_content
        return len(content.split()) if content else 0

    @property
    def token_count(self) -> int:
        return max(1, len(self.output_content) // 4) if self.output_content else 0

    @property
    def total_duration_ms(self) -> float:
        return sum(sr.duration_ms for sr in self.stage_results)

    @property
    def failed_stages(self) -> list[str]:
        return [
            sr.stage_name for sr in self.stage_results
            if sr.status == StageStatus.FAILED
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "markdown": self.markdown,
            "html": self.html,
            "text": self.text,
            "metadata": self.metadata,
            "links": self.links,
            "chunks": self.chunks,
            "citations": self.citations,
            "extracted_data": self.extracted_data,
            "screenshot": self.screenshot[:100] + "..." if self.screenshot else "",
            "error": self.error,
            "word_count": self.word_count,
            "token_count": self.token_count,
            "stage_results": [sr.to_dict() for sr in self.stage_results],
            "total_duration_ms": round(self.total_duration_ms, 2),
        }


# ══════════════════════════════════════════════════════════════
# Stage ABC
# ══════════════════════════════════════════════════════════════

class PipelineStage(ABC):
    """
    Abstract base class for pipeline stages.

    Each stage performs a single transformation on the
    PipelineContext. Stages can be conditionally skipped
    based on the config.

    Subclasses must implement:
        - name: Stage identifier.
        - _execute: The actual processing logic.

    Optional overrides:
        - should_skip: Whether to skip this stage.
        - on_error: Custom error handling.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique stage name."""
        ...

    @abstractmethod
    async def _execute(self, ctx: PipelineContext) -> None:
        """
        Execute the stage logic.

        Args:
            ctx: Pipeline context to read from and write to.
        """
        ...

    def should_skip(self, ctx: PipelineContext) -> bool:
        """
        Determine whether this stage should be skipped.

        Override in subclasses for conditional execution.

        Args:
            ctx: Pipeline context.

        Returns:
            True to skip this stage.
        """
        return False

    async def on_error(self, ctx: PipelineContext, error: Exception) -> bool:
        """
        Handle an error during stage execution.

        Args:
            ctx: Pipeline context.
            error: The exception that occurred.

        Returns:
            True to continue the pipeline, False to abort.
        """
        return False

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """
        Execute the stage with timing, skip check, and error handling.

        Args:
            ctx: Pipeline context.

        Returns:
            StageResult with status and timing.
        """
        # Check skip condition
        if self.should_skip(ctx):
            logger.debug("Stage '%s' skipped", self.name)
            return StageResult(
                stage_name=self.name,
                status=StageStatus.SKIPPED,
            )

        # Execute with timing
        start = time.perf_counter()
        try:
            await self._execute(ctx)
            duration = (time.perf_counter() - start) * 1000
            logger.debug("Stage '%s' completed in %.1fms", self.name, duration)
            return StageResult(
                stage_name=self.name,
                status=StageStatus.COMPLETED,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            logger.warning("Stage '%s' failed: %s", self.name, e)

            # Let stage handle its own error
            should_continue = await self.on_error(ctx, e)

            result = StageResult(
                stage_name=self.name,
                status=StageStatus.FAILED,
                duration_ms=duration,
                error=str(e),
            )

            if not should_continue:
                ctx.error = f"Stage '{self.name}' failed: {e}"
                raise

            return result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


# ══════════════════════════════════════════════════════════════
# Built-in Stages
# ══════════════════════════════════════════════════════════════

class FetchStage(PipelineStage):
    """
    Fetch a page using the browser manager.

    Reads: ctx.url, ctx.config
    Writes: ctx.raw_html, ctx.status_code, ctx.page
    """

    def __init__(self, browser_manager: Any = None):
        self._browser_manager = browser_manager

    @property
    def name(self) -> str:
        return "fetch"

    async def _execute(self, ctx: PipelineContext) -> None:
        if self._browser_manager is None:
            raise RuntimeError("BrowserManager not provided to FetchStage")

        config = ctx.config
        timeout = getattr(config, "timeout", 30) if config else 30
        nav_timeout = getattr(config, "navigation_timeout_ms", 30_000) if config else 30_000

        # Acquire page
        page = await self._browser_manager.acquire_page(timeout=timeout)
        ctx.page = page

        try:
            # Execute actions
            actions = getattr(config, "actions", None) if config else None
            if actions:
                from agentcrawl.browser.actions import PageActions
                if isinstance(actions, list) and actions:
                    pa = PageActions(actions)
                    await pa.execute(page)

            # Navigate
            response = await page.goto(
                ctx.url,
                timeout=nav_timeout,
                wait_until="domcontentloaded",
            )

            if response:
                ctx.status_code = response.status

            # Wait for content
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass

            # Get HTML
            ctx.raw_html = await page.content()

        finally:
            await self._browser_manager.release_page(page)
            ctx.page = None

    async def on_error(self, ctx: PipelineContext, error: Exception) -> bool:
        # Release page if still held
        if ctx.page and self._browser_manager:
            try:
                await self._browser_manager.release_page(ctx.page)
            except Exception:
                pass
            ctx.page = None
        return False  # Abort pipeline on fetch failure


class ParseStage(PipelineStage):
    """
    Parse HTML and extract metadata, links, headings, and main content.

    Reads: ctx.raw_html, ctx.url, ctx.config
    Writes: ctx.metadata, ctx.links, ctx.main_content_html,
            ctx.main_content_text, ctx.headings, ctx.images, ctx.tables
    """

    @property
    def name(self) -> str:
        return "parse"

    async def _execute(self, ctx: PipelineContext) -> None:
        from agentcrawl.content.html_parser import HTMLParser

        config = ctx.config
        parser = HTMLParser(ctx.raw_html, base_url=ctx.url)

        # Metadata
        include_meta = getattr(config, "include_metadata", True) if config else True
        if include_meta:
            meta = parser.get_metadata()
            ctx.metadata = meta.to_dict()

        # Links
        include_links = getattr(config, "include_links", True) if config else True
        if include_links:
            links = parser.get_links(base_url=ctx.url)
            ctx.links = {
                "internal": [l.to_dict() for l in links["internal"]],
                "external": [l.to_dict() for l in links["external"]],
                "all": [l.to_dict() for l in links["all"]],
            }

        # Headings
        ctx.headings = [h.to_dict() for h in parser.get_headings()]

        # Main content
        selectors = getattr(config, "selectors", None) if config else None
        exclude = getattr(config, "exclude_selectors", None) if config else None
        only_main = getattr(config, "only_main_content", True) if config else True

        main = parser.get_main_content(
            include_selectors=selectors or None,
            exclude_selectors=exclude or None,
            only_main=only_main,
        )
        ctx.main_content_html = main.html
        ctx.main_content_text = main.text

    def should_skip(self, ctx: PipelineContext) -> bool:
        return not ctx.raw_html


class ConvertStage(PipelineStage):
    """
    Convert HTML to Markdown/JSON/text output.

    Reads: ctx.main_content_html, ctx.main_content_text, ctx.config
    Writes: ctx.markdown, ctx.html, ctx.json, ctx.text
    """

    @property
    def name(self) -> str:
        return "convert"

    async def _execute(self, ctx: PipelineContext) -> None:
        from agentcrawl.content.html_to_markdown import HTMLToMarkdown, MarkdownOptions

        config = ctx.config
        output_format = str(getattr(config, "output_format", "markdown")) if config else "markdown"

        converter = HTMLToMarkdown(MarkdownOptions(
            include_links=True,
            include_images=False,
        ))

        # Always produce markdown (used by filters, chunkers, citations)
        ctx.markdown = converter.convert(ctx.main_content_html)
        ctx.text = ctx.main_content_text
        ctx.html = ctx.main_content_html

        if output_format == "json":
            ctx.json = {
                "url": ctx.url,
                "content": ctx.main_content_text,
                "markdown": ctx.markdown,
                "metadata": ctx.metadata,
                "links": ctx.links,
            }


class FilterStage(PipelineStage):
    """
    Apply content filtering (BM25 or Pruning).

    Reads: ctx.markdown, ctx.config
    Writes: ctx.filtered_text, ctx.filter_stats
    """

    @property
    def name(self) -> str:
        return "filter"

    async def _execute(self, ctx: PipelineContext) -> None:
        from agentcrawl.content.content_filter import create_content_filter_from_config

        config = ctx.config
        content_filter = create_content_filter_from_config(config)

        if content_filter is None:
            ctx.filtered_text = ctx.markdown
            return

        result = content_filter.apply(ctx.markdown)
        ctx.filtered_text = result.filtered_text
        ctx.filter_stats = result.to_dict()

        # Update markdown with filtered content
        ctx.markdown = result.filtered_text

    def should_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.config:
            return True
        cf = getattr(ctx.config, "content_filter", "none")
        return cf == "none" or cf is None


class ChunkStage(PipelineStage):
    """
    Apply content chunking for RAG.

    Reads: ctx.markdown, ctx.config
    Writes: ctx.chunks, ctx.chunk_stats
    """

    @property
    def name(self) -> str:
        return "chunk"

    async def _execute(self, ctx: PipelineContext) -> None:
        from agentcrawl.content.chunker import create_chunker_from_config

        config = ctx.config
        chunker = create_chunker_from_config(config)

        if chunker is None:
            return

        result = chunker.chunk(
            ctx.markdown,
            metadata={"url": ctx.url},
        )
        ctx.chunks = [c.to_dict() for c in result.chunks]
        ctx.chunk_stats = {
            "total_chunks": result.total_chunks,
            "total_tokens": result.total_tokens,
            "avg_chunk_tokens": round(result.avg_chunk_tokens, 1),
            "strategy": result.strategy,
        }

    def should_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.config:
            return True
        ch = getattr(ctx.config, "chunker", "none")
        return ch == "none" or ch is None


class CitationStage(PipelineStage):
    """
    Extract citations from content.

    Reads: ctx.markdown, ctx.config
    Writes: ctx.citations, ctx.bibliography
    """

    @property
    def name(self) -> str:
        return "citation"

    async def _execute(self, ctx: PipelineContext) -> None:
        from agentcrawl.content.citation import CitationExtractor

        extractor = CitationExtractor(deduplicate=True, include_context=True)
        result = extractor.extract(ctx.markdown)

        ctx.citations = [c.to_dict() for c in result.citations]
        ctx.bibliography = result.format_bibliography("markdown")

    def should_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.config:
            return True
        return not getattr(ctx.config, "include_citations", False)


class ExtractionStage(PipelineStage):
    """
    Run structured data extraction (LLM, CSS, XPath).

    Reads: ctx.main_content_html, ctx.markdown, ctx.config
    Writes: ctx.extracted_data
    """

    @property
    def name(self) -> str:
        return "extraction"

    async def _execute(self, ctx: PipelineContext) -> None:
        config = ctx.config
        extraction = getattr(config, "extraction", None) if config else None

        if extraction is None:
            return

        ctx.extracted_data = await extraction.extract(
            html=ctx.main_content_html,
            markdown=ctx.markdown,
            url=ctx.url,
        )

    def should_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.config:
            return True
        return getattr(ctx.config, "extraction", None) is None


class ScreenshotStage(PipelineStage):
    """
    Capture a page screenshot.

    Reads: ctx.page (must be set by FetchStage), ctx.config
    Writes: ctx.screenshot

    Note: This stage must run BEFORE the page is released.
    In the default pipeline, screenshots are handled in FetchStage.
    This stage is for custom pipelines where the page is still available.
    """

    @property
    def name(self) -> str:
        return "screenshot"

    async def _execute(self, ctx: PipelineContext) -> None:
        if ctx.page is None:
            logger.debug("No page available for screenshot")
            return

        config = ctx.config
        screenshot_opts = getattr(config, "screenshot", None) if config else None

        full_page = True
        fmt = "png"
        if screenshot_opts:
            full_page = getattr(screenshot_opts, "full_page", True)
            fmt = getattr(screenshot_opts, "format", "png")

        screenshot_bytes = await ctx.page.screenshot(
            full_page=full_page,
            type=fmt,
        )

        import base64
        ctx.screenshot = base64.b64encode(screenshot_bytes).decode()

    def should_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.config:
            return True
        return not (
            getattr(ctx.config, "include_screenshot", False)
            or getattr(getattr(ctx.config, "screenshot", None), "enabled", False)
        )


class CacheReadStage(PipelineStage):
    """
    Check cache before fetching.

    Reads: ctx.url, ctx.config
    Writes: ctx (populates all fields from cache if hit)
    """

    def __init__(self, cache_manager: Any = None):
        self._cache = cache_manager

    @property
    def name(self) -> str:
        return "cache_read"

    async def _execute(self, ctx: PipelineContext) -> None:
        if not self._cache:
            return

        config = ctx.config
        cache_key = self._cache.key_generator.from_url(
            ctx.url,
            output_format=str(getattr(config, "output_format", "markdown")),
        )

        cached = await self._cache.get(cache_key)
        if cached:
            ctx.raw_html = cached.get("raw_html", "")
            ctx.markdown = cached.get("markdown", "")
            ctx.html = cached.get("html", "")
            ctx.text = cached.get("text", "")
            ctx.metadata = cached.get("metadata", {})
            ctx.links = cached.get("links", {})
            ctx.status_code = cached.get("status_code", 200)
            ctx.extra["cache_hit"] = True
            logger.debug("Cache hit for %s", ctx.url)

    def should_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.config:
            return True
        return not getattr(ctx.config, "cache", True)


class CacheWriteStage(PipelineStage):
    """
    Write result to cache after processing.

    Reads: ctx (all output fields)
    Writes: (cache storage)
    """

    def __init__(self, cache_manager: Any = None):
        self._cache = cache_manager

    @property
    def name(self) -> str:
        return "cache_write"

    async def _execute(self, ctx: PipelineContext) -> None:
        if not self._cache:
            return

        if ctx.extra.get("cache_hit"):
            return  # Don't re-cache a cache hit

        config = ctx.config
        cache_key = self._cache.key_generator.from_url(
            ctx.url,
            output_format=str(getattr(config, "output_format", "markdown")),
        )

        ttl = getattr(config, "cache_ttl", None) or 3600

        await self._cache.set(cache_key, ctx.to_dict(), ttl=ttl)

    def should_skip(self, ctx: PipelineContext) -> bool:
        if not ctx.config:
            return True
        if not getattr(ctx.config, "cache", True):
            return True
        return ctx.error is not None  # Don't cache errors


class NoOpStage(PipelineStage):
    """A stage that does nothing. Useful for testing or as a placeholder."""

    def __init__(self, stage_name: str = "noop"):
        self._name = stage_name

    @property
    def name(self) -> str:
        return self._name

    async def _execute(self, ctx: PipelineContext) -> None:
        pass


# ══════════════════════════════════════════════════════════════
# Pipeline
# ══════════════════════════════════════════════════════════════

class Pipeline:
    """
    Composable processing pipeline.

    Executes a sequence of PipelineStage instances against a
    PipelineContext, with timing, error handling, and skip logic.

    Args:
        stages: List of pipeline stages.
        stop_on_error: Whether to stop on first stage failure.
        name: Pipeline name for logging.

    Example:
        >>> pipeline = Pipeline([
        ...     FetchStage(browser_manager),
        ...     ParseStage(),
        ...     ConvertStage(),
        ...     FilterStage(),
        ... ])
        >>> ctx = PipelineContext(url="https://example.com", config=config)
        >>> await pipeline.execute(ctx)
        >>> print(ctx.markdown)
    """

    def __init__(
        self,
        stages: list[PipelineStage] | None = None,
        stop_on_error: bool = True,
        name: str = "pipeline",
    ):
        self._stages = stages or []
        self._stop_on_error = stop_on_error
        self._name = name

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def stages(self) -> list[PipelineStage]:
        return list(self._stages)

    @property
    def stage_names(self) -> list[str]:
        return [s.name for s in self._stages]

    @property
    def name(self) -> str:
        return self._name

    # ──────────────────────────────────────────────────────────
    # Execution
    # ──────────────────────────────────────────────────────────

    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        """
        Execute all stages against a context.

        Args:
            ctx: Pipeline context.

        Returns:
            The same context (mutated in place).
        """
        logger.debug(
            "Pipeline '%s' starting (%d stages) for %s",
            self._name,
            len(self._stages),
            ctx.url,
        )

        for stage in self._stages:
            try:
                result = await stage.execute(ctx)
                ctx.stage_results.append(result)

                if result.status == StageStatus.FAILED and self._stop_on_error:
                    logger.error(
                        "Pipeline '%s' aborted at stage '%s': %s",
                        self._name,
                        stage.name,
                        result.error,
                    )
                    break

            except Exception as e:
                ctx.stage_results.append(StageResult(
                    stage_name=stage.name,
                    status=StageStatus.FAILED,
                    error=str(e),
                ))
                if self._stop_on_error:
                    ctx.error = str(e)
                    break

        logger.debug(
            "Pipeline '%s' completed in %.1fms (%d stages)",
            self._name,
            ctx.total_duration_ms,
            len(ctx.stage_results),
        )

        return ctx

    async def execute_many(
        self,
        contexts: list[PipelineContext],
        max_concurrent: int = 5,
    ) -> list[PipelineContext]:
        """
        Execute the pipeline for multiple contexts concurrently.

        Args:
            contexts: List of pipeline contexts.
            max_concurrent: Maximum concurrent executions.

        Returns:
            List of processed contexts.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _run(ctx: PipelineContext) -> PipelineContext:
            async with semaphore:
                return await self.execute(ctx)

        tasks = [_run(ctx) for ctx in contexts]
        return list(await asyncio.gather(*tasks))

    # ──────────────────────────────────────────────────────────
    # Builder
    # ──────────────────────────────────────────────────────────

    @classmethod
    def builder(cls) -> PipelineBuilder:
        """Create a new pipeline builder."""
        return PipelineBuilder()

    def add_stage(self, stage: PipelineStage) -> Pipeline:
        """Add a stage to the pipeline (returns self for chaining)."""
        self._stages.append(stage)
        return self

    # ──────────────────────────────────────────────────────────
    # Pre-built Pipelines
    # ──────────────────────────────────────────────────────────

    @classmethod
    def scrape_pipeline(
        cls,
        browser_manager: Any,
        cache_manager: Any = None,
    ) -> Pipeline:
        """
        Standard scrape pipeline: fetch → parse → convert → filter → chunk → cite.

        Args:
            browser_manager: BrowserManager instance.
            cache_manager: Optional CacheManager instance.

        Returns:
            Pipeline instance.
        """
        stages: list[PipelineStage] = []

        if cache_manager:
            stages.append(CacheReadStage(cache_manager))

        stages.extend([
            FetchStage(browser_manager),
            ParseStage(),
            ConvertStage(),
            FilterStage(),
            ChunkStage(),
            CitationStage(),
            ExtractionStage(),
        ])

        if cache_manager:
            stages.append(CacheWriteStage(cache_manager))

        return cls(stages=stages, name="scrape")

    @classmethod
    def rag_pipeline(
        cls,
        browser_manager: Any,
        cache_manager: Any = None,
    ) -> Pipeline:
        """
        RAG-optimized pipeline: fetch → parse → convert → filter → chunk.

        Emphasizes content filtering and chunking for vector stores.
        """
        stages: list[PipelineStage] = []

        if cache_manager:
            stages.append(CacheReadStage(cache_manager))

        stages.extend([
            FetchStage(browser_manager),
            ParseStage(),
            ConvertStage(),
            FilterStage(),
            ChunkStage(),
            CitationStage(),
        ])

        if cache_manager:
            stages.append(CacheWriteStage(cache_manager))

        return cls(stages=stages, name="rag")

    @classmethod
    def extract_pipeline(
        cls,
        browser_manager: Any,
    ) -> Pipeline:
        """
        Extraction pipeline: fetch → parse → convert → extract.

        Optimized for structured data extraction.
        """
        return cls(
            stages=[
                FetchStage(browser_manager),
                ParseStage(),
                ConvertStage(),
                ExtractionStage(),
            ],
            name="extract",
        )

    @classmethod
    def minimal_pipeline(
        cls,
        browser_manager: Any,
    ) -> Pipeline:
        """Minimal pipeline: fetch → parse → convert."""
        return cls(
            stages=[
                FetchStage(browser_manager),
                ParseStage(),
                ConvertStage(),
            ],
            name="minimal",
        )

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def describe(self) -> str:
        """Get a human-readable description of the pipeline."""
        lines = [f"Pipeline '{self._name}' ({len(self._stages)} stages):"]
        for i, stage in enumerate(self._stages, 1):
            lines.append(f"  {i}. {stage.name} ({stage.__class__.__name__})")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "stages": [s.name for s in self._stages],
            "stop_on_error": self._stop_on_error,
        }

    def __repr__(self) -> str:
        return (
            f"Pipeline(name={self._name!r}, "
            f"stages={self.stage_names})"
        )

    def __len__(self) -> int:
        return len(self._stages)


# ══════════════════════════════════════════════════════════════
# Pipeline Builder
# ══════════════════════════════════════════════════════════════

class PipelineBuilder:
    """
    Fluent builder for constructing pipelines.

    Example:
        >>> pipeline = (
        ...     Pipeline.builder()
        ...     .add(FetchStage(browser_manager))
        ...     .add(ParseStage())
        ...     .add(ConvertStage())
        ...     .add(FilterStage())
        ...     .add(ChunkStage())
        ...     .stop_on_error(True)
        ...     .named("custom")
        ...     .build()
        ... )
    """

    def __init__(self) -> None:
        self._stages: list[PipelineStage] = []
        self._stop_on_error: bool = True
        self._name: str = "pipeline"

    def add(self, stage: PipelineStage) -> PipelineBuilder:
        """Add a stage to the pipeline."""
        self._stages.append(stage)
        return self

    def add_if(self, condition: bool, stage: PipelineStage) -> PipelineBuilder:
        """Conditionally add a stage."""
        if condition:
            self._stages.append(stage)
        return self

    def add_many(self, stages: list[PipelineStage]) -> PipelineBuilder:
        """Add multiple stages."""
        self._stages.extend(stages)
        return self

    def insert(self, index: int, stage: PipelineStage) -> PipelineBuilder:
        """Insert a stage at a specific position."""
        self._stages.insert(index, stage)
        return self

    def remove(self, stage_name: str) -> PipelineBuilder:
        """Remove a stage by name."""
        self._stages = [s for s in self._stages if s.name != stage_name]
        return self

    def stop_on_error(self, value: bool = True) -> PipelineBuilder:
        """Set whether to stop on first error."""
        self._stop_on_error = value
        return self

    def named(self, name: str) -> PipelineBuilder:
        """Set the pipeline name."""
        self._name = name
        return self

    def build(self) -> Pipeline:
        """Build the pipeline."""
        return Pipeline(
            stages=self._stages,
            stop_on_error=self._stop_on_error,
            name=self._name,
        )
