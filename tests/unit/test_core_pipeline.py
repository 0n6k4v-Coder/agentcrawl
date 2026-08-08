"""Tests for agentcrawl.core.pipeline module.

Covers PipelineContext, all stages, Pipeline execution, PipelineBuilder,
and pre-built pipeline factories.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

# ═══ StageStatus Enum ═══


class TestStageStatus:
    """Tests for StageStatus enum."""

    def test_values(self) -> None:
        assert StageStatus.PENDING.value == "pending"
        assert StageStatus.RUNNING.value == "running"
        assert StageStatus.COMPLETED.value == "completed"
        assert StageStatus.SKIPPED.value == "skipped"
        assert StageStatus.FAILED.value == "failed"

    def test_is_str_enum(self) -> None:
        assert isinstance(StageStatus.COMPLETED, str)
        assert StageStatus.COMPLETED == "completed"


# ═══ StageResult Tests ═══


class TestStageResult:
    """Tests for StageResult dataclass."""

    def test_defaults(self) -> None:
        result = StageResult(stage_name="test")
        assert result.stage_name == "test"
        assert result.status == StageStatus.PENDING
        assert result.duration_ms == 0.0
        assert result.error is None
        assert result.data == {}

    def test_to_dict(self) -> None:
        result = StageResult(
            stage_name="fetch",
            status=StageStatus.COMPLETED,
            duration_ms=42.5,
            error=None,
        )
        d = result.to_dict()
        assert d["stage"] == "fetch"
        assert d["status"] == "completed"
        assert d["duration_ms"] == 42.5
        assert d["error"] is None

    def test_to_dict_failed(self) -> None:
        result = StageResult(
            stage_name="parse",
            status=StageStatus.FAILED,
            duration_ms=10.0,
            error="Parse error",
        )
        d = result.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "Parse error"


# ═══ PipelineContext Tests ═══


class TestPipelineContext:
    """Tests for PipelineContext dataclass properties."""

    def test_defaults(self) -> None:
        ctx = PipelineContext(url="https://example.com")
        assert ctx.url == "https://example.com"
        assert ctx.raw_html == ""
        assert ctx.status_code == 0
        assert ctx.metadata == {}
        assert ctx.links == {}
        assert ctx.markdown == ""
        assert ctx.html == ""
        assert ctx.chunks == []
        assert ctx.citations == []
        assert ctx.error is None

    def test_output_content_markdown(self) -> None:
        ctx = PipelineContext(url="https://x", markdown="# Hello", config=None)
        assert ctx.output_content == "# Hello"

    def test_output_content_with_config_html(self) -> None:
        config = MagicMock()
        config.output_format = "html"
        ctx = PipelineContext(url="https://x", main_content_html="<p>Hello</p>", config=config)
        assert ctx.output_content == "<p>Hello</p>"

    def test_output_content_with_config_json(self) -> None:
        import json as json_mod

        config = MagicMock()
        config.output_format = "json"
        ctx = PipelineContext(
            url="https://x",
            json={"key": "value"},
            config=config,
        )
        result = ctx.output_content
        parsed = json_mod.loads(result)
        assert parsed["key"] == "value"

    def test_output_content_with_config_text(self) -> None:
        config = MagicMock()
        config.output_format = "text"
        ctx = PipelineContext(url="https://x", main_content_text="Plain text", config=config)
        assert ctx.output_content == "Plain text"

    def test_output_content_fallback(self) -> None:
        config = MagicMock()
        config.output_format = "markdown"
        ctx = PipelineContext(
            url="https://x",
            markdown="",
            filtered_text="",
            main_content_text="fallback",
            config=config,
        )
        assert ctx.output_content == "fallback"

    def test_word_count(self) -> None:
        ctx = PipelineContext(url="https://x", markdown="one two three four five")
        assert ctx.word_count == 5

    def test_word_count_empty(self) -> None:
        ctx = PipelineContext(url="https://x", markdown="")
        assert ctx.word_count == 0

    def test_token_count(self) -> None:
        ctx = PipelineContext(url="https://x", markdown="one two three four" * 10)
        assert ctx.token_count >= 1

    def test_token_count_empty(self) -> None:
        ctx = PipelineContext(url="https://x", markdown="")
        assert ctx.token_count == 0

    def test_total_duration_ms(self) -> None:
        ctx = PipelineContext(url="https://x")
        ctx.stage_results = [
            StageResult(stage_name="a", duration_ms=10.0),
            StageResult(stage_name="b", duration_ms=20.5),
        ]
        assert ctx.total_duration_ms == 30.5

    def test_failed_stages(self) -> None:
        ctx = PipelineContext(url="https://x")
        ctx.stage_results = [
            StageResult(stage_name="a", status=StageStatus.COMPLETED),
            StageResult(stage_name="b", status=StageStatus.FAILED, error="err"),
            StageResult(stage_name="c", status=StageStatus.SKIPPED),
        ]
        assert ctx.failed_stages == ["b"]

    def test_to_dict(self) -> None:
        ctx = PipelineContext(url="https://x", status_code=200)
        d = ctx.to_dict()
        assert d["url"] == "https://x"
        assert d["status_code"] == 200
        assert d["word_count"] == 0

    def test_to_dict_with_screenshot(self) -> None:
        ctx = PipelineContext(url="https://x")
        ctx.screenshot = "a" * 200
        d = ctx.to_dict()
        assert d["screenshot"].endswith("...")
        assert len(d["screenshot"]) <= 103

    def test_to_dict_without_screenshot(self) -> None:
        ctx = PipelineContext(url="https://x")
        d = ctx.to_dict()
        assert d["screenshot"] == ""


# ═══ Pipeline (base) Tests ═══


class TestPipelineStage:
    """Tests for PipelineStage base class via NoOpStage."""

    @pytest.mark.asyncio
    async def test_execute_completed(self) -> None:
        stage = NoOpStage("test_stage")
        ctx = PipelineContext(url="https://x")
        result = await stage.execute(ctx)
        assert result.status == StageStatus.COMPLETED
        assert result.stage_name == "test_stage"

    @pytest.mark.asyncio
    async def test_execute_skipped(self) -> None:
        stage = NoOpStage("test_skip")
        stage.should_skip = lambda ctx: True
        ctx = PipelineContext(url="https://x")
        result = await stage.execute(ctx)
        assert result.status == StageStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_execute_failed_continues(self) -> None:
        """Test on_error returns True so pipeline continues."""
        ctx = PipelineContext(url="https://x")

        class FailingStage(PipelineStage):
            @property
            def name(self) -> str:
                return "failing"

            async def _execute(self, ctx: PipelineContext) -> None:
                raise ValueError("Fail!")

            async def on_error(self, ctx: PipelineContext, error: Exception) -> bool:
                return True  # Continue

        stage = FailingStage()
        result = await stage.execute(ctx)
        assert result.status == StageStatus.FAILED
        assert result.error == "Fail!"

    @pytest.mark.asyncio
    async def test_execute_failed_aborts(self) -> None:
        """Test on_error returns False so pipeline aborts (raises)."""
        ctx = PipelineContext(url="https://x")

        class FailingStage(PipelineStage):
            @property
            def name(self) -> str:
                return "failing"

            async def _execute(self, ctx: PipelineContext) -> None:
                raise ValueError("Abort!")

            async def on_error(self, ctx: PipelineContext, error: Exception) -> bool:
                return False  # Abort

        stage = FailingStage()
        with pytest.raises(ValueError, match="Abort!"):
            await stage.execute(ctx)
        assert ctx.error == "Stage 'failing' failed: Abort!"

    def test_repr(self) -> None:
        stage = NoOpStage("test")
        assert repr(stage) == "NoOpStage()"


# ═══ NoOpStage Tests ═══


class TestNoOpStage:
    """Tests for NoOpStage."""

    @pytest.mark.asyncio
    async def test_execute(self) -> None:
        stage = NoOpStage("noop")
        ctx = PipelineContext(url="https://x")
        await stage._execute(ctx)
        assert ctx.error is None

    def test_custom_name(self) -> None:
        stage = NoOpStage("custom_noop")
        assert stage.name == "custom_noop"

    def test_default_name(self) -> None:
        stage = NoOpStage()
        assert stage.name == "noop"


# ═══ Pipeline Tests ═══


class TestPipeline:
    """Tests for Pipeline class."""

    def test_empty_pipeline(self) -> None:
        pipeline = Pipeline()
        assert len(pipeline) == 0
        assert pipeline.stages == []
        assert pipeline.stage_names == []

    def test_add_stage(self) -> None:
        pipeline = Pipeline()
        stage = NoOpStage("test")
        result = pipeline.add_stage(stage)
        assert result is pipeline  # Returns self for chaining
        assert len(pipeline) == 1
        assert pipeline.stage_names == ["test"]

    def test_repr(self) -> None:
        pipeline = Pipeline(stages=[NoOpStage("test")], name="mypipe")
        repr_str = repr(pipeline)
        assert "mypipe" in repr_str
        assert "test" in repr_str

    def test_to_dict(self) -> None:
        pipeline = Pipeline(
            stages=[NoOpStage("a"), NoOpStage("b")],
            stop_on_error=True,
            name="test_pipe",
        )
        d = pipeline.to_dict()
        assert d["name"] == "test_pipe"
        assert d["stages"] == ["a", "b"]
        assert d["stop_on_error"] is True

    def test_describe(self) -> None:
        pipeline = Pipeline(stages=[NoOpStage("test")], name="desc_test")
        desc = pipeline.describe()
        assert "desc_test" in desc
        assert "test" in desc

    @pytest.mark.asyncio
    async def test_execute_empty(self) -> None:
        pipeline = Pipeline()
        ctx = PipelineContext(url="https://x")
        result = await pipeline.execute(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        ctx = PipelineContext(url="https://x")
        pipeline = Pipeline(stages=[NoOpStage("test")], name="test", stop_on_error=True)
        result = await pipeline.execute(ctx)
        assert result is ctx
        assert ctx.error is None
        assert len(ctx.stage_results) == 1

    @pytest.mark.asyncio
    async def test_execute_stop_on_error(self) -> None:
        ctx = PipelineContext(url="https://x")

        class FailingStage(PipelineStage):
            @property
            def name(self) -> str:
                return "fail"

            async def _execute(self, ctx: PipelineContext) -> None:
                raise ValueError("fail!")

        pipeline = Pipeline(
            stages=[NoOpStage("ok"), FailingStage(), NoOpStage("should_not_run")],
        )
        await pipeline.execute(ctx)
        assert ctx.error == "fail!"
        assert len(ctx.stage_results) == 2  # ok + fail, not the third

    @pytest.mark.asyncio
    async def test_execute_continue_on_error(self) -> None:
        ctx = PipelineContext(url="https://x")

        class FailingStage(PipelineStage):
            @property
            def name(self) -> str:
                return "fail"

            async def _execute(self, ctx: PipelineContext) -> None:
                raise ValueError("fail!")

        pipeline = Pipeline(
            stages=[NoOpStage("ok1"), FailingStage(), NoOpStage("ok2")],
            stop_on_error=False,
        )
        await pipeline.execute(ctx)
        assert len(ctx.stage_results) == 3

    @pytest.mark.asyncio
    async def test_execute_many(self) -> None:
        pipeline = Pipeline(stages=[NoOpStage("test")])
        contexts = [
            PipelineContext(url="https://a.com"),
            PipelineContext(url="https://b.com"),
            PipelineContext(url="https://c.com"),
        ]
        results = await pipeline.execute_many(contexts, max_concurrent=2)
        assert len(results) == 3
        assert all(r is ctx for r, ctx in zip(results, contexts, strict=True))

    @pytest.mark.asyncio
    async def test_execute_many_empty(self) -> None:
        pipeline = Pipeline(stages=[NoOpStage("test")])
        results = await pipeline.execute_many([])
        assert results == []

    @pytest.mark.asyncio
    async def test_stage_failed_but_continues(self) -> None:
        """Test that a failed stage with on_error=True continues when stop_on_error=False."""
        ctx = PipelineContext(url="https://x")

        class FailingStage(PipelineStage):
            @property
            def name(self) -> str:
                return "fail"

            async def _execute(self, ctx: PipelineContext) -> None:
                raise ValueError("fail")

            async def on_error(self, ctx: PipelineContext, error: Exception) -> bool:
                return True  # Continue

        pipeline = Pipeline(stages=[FailingStage(), NoOpStage("ok")], stop_on_error=False)
        await pipeline.execute(ctx)
        # Should continue to "ok" since on_error returned True and stop_on_error=False
        assert len(ctx.stage_results) == 2


# ═══ Pre-built Pipeline Tests ═══


class TestPrebuiltPipelines:
    """Tests for Pipeline pre-built factory methods."""

    def test_scrape_pipeline(self) -> None:
        pipeline = Pipeline.scrape_pipeline(browser_manager=MagicMock())
        assert pipeline.name == "scrape"
        names = pipeline.stage_names
        assert "fetch" in names
        assert "parse" in names
        assert "convert" in names
        assert "filter" in names
        assert "chunk" in names
        assert "citation" in names
        assert "extraction" in names

    def test_scrape_pipeline_with_cache(self) -> None:
        pipeline = Pipeline.scrape_pipeline(browser_manager=MagicMock(), cache_manager=MagicMock())
        names = pipeline.stage_names
        assert "cache_read" in names
        assert "cache_write" in names

    def test_rag_pipeline(self) -> None:
        pipeline = Pipeline.rag_pipeline(browser_manager=MagicMock())
        assert pipeline.name == "rag"
        names = pipeline.stage_names
        assert "fetch" in names
        assert "filter" in names
        assert "chunk" in names
        assert "extraction" not in names

    def test_rag_pipeline_with_cache(self) -> None:
        pipeline = Pipeline.rag_pipeline(browser_manager=MagicMock(), cache_manager=MagicMock())
        assert "cache_read" in pipeline.stage_names

    def test_extract_pipeline(self) -> None:
        pipeline = Pipeline.extract_pipeline(browser_manager=MagicMock())
        assert pipeline.name == "extract"
        names = pipeline.stage_names
        assert "fetch" in names
        assert "extraction" in names
        assert "filter" not in names

    def test_minimal_pipeline(self) -> None:
        pipeline = Pipeline.minimal_pipeline(browser_manager=MagicMock())
        assert pipeline.name == "minimal"
        assert len(pipeline.stages) == 3


# ═══ PipelineBuilder Tests ═══


class TestPipelineBuilder:
    """Tests for PipelineBuilder fluent API."""

    def test_build_empty(self) -> None:
        builder = PipelineBuilder()
        pipeline = builder.build()
        assert len(pipeline) == 0

    def test_add(self) -> None:
        builder = PipelineBuilder()
        result = builder.add(NoOpStage("test"))
        assert result is builder  # Fluent interface
        pipeline = builder.build()
        assert len(pipeline) == 1

    def test_add_many(self) -> None:
        builder = PipelineBuilder()
        builder.add_many([NoOpStage("a"), NoOpStage("b")])
        pipeline = builder.build()
        assert len(pipeline) == 2

    def test_add_if_true(self) -> None:
        builder = PipelineBuilder()
        builder.add_if(True, NoOpStage("yes"))
        assert len(builder._stages) == 1

    def test_add_if_false(self) -> None:
        builder = PipelineBuilder()
        builder.add_if(False, NoOpStage("no"))
        assert len(builder._stages) == 0

    def test_insert(self) -> None:
        builder = PipelineBuilder()
        builder.add(NoOpStage("a"))
        builder.insert(0, NoOpStage("b"))
        assert builder._stages[0].name == "b"
        assert builder._stages[1].name == "a"

    def test_remove(self) -> None:
        builder = PipelineBuilder()
        builder.add(NoOpStage("a"))
        builder.add(NoOpStage("b"))
        builder.add(NoOpStage("c"))
        builder.remove("b")
        assert len(builder._stages) == 2
        assert builder._stages[0].name == "a"
        assert builder._stages[1].name == "c"

    def test_remove_nonexistent(self) -> None:
        builder = PipelineBuilder()
        builder.add(NoOpStage("a"))
        builder.remove("nonexistent")
        assert len(builder._stages) == 1

    def test_stop_on_error(self) -> None:
        builder = PipelineBuilder()
        result = builder.stop_on_error(False)
        assert result is builder
        pipeline = builder.build()
        assert pipeline._stop_on_error is False

    def test_stop_on_error_default(self) -> None:
        builder = PipelineBuilder()
        assert builder._stop_on_error is True

    def test_named(self) -> None:
        builder = PipelineBuilder()
        result = builder.named("custom_name")
        assert result is builder
        pipeline = builder.build()
        assert pipeline.name == "custom_name"

    def test_full_fluent_build(self) -> None:
        pipeline = (
            Pipeline.builder()
            .add(NoOpStage("stage1"))
            .add(NoOpStage("stage2"))
            .add_if(True, NoOpStage("conditional"))
            .stop_on_error(False)
            .named("custom_pipeline")
            .build()
        )
        assert len(pipeline) == 3
        assert pipeline.name == "custom_pipeline"
        assert pipeline._stop_on_error is False


# ═══ FetchStage Tests ═══


class TestFetchStage:
    """Tests for FetchStage."""

    @pytest.mark.asyncio
    async def test_no_browser_manager(self) -> None:
        stage = FetchStage(browser_manager=None)
        ctx = PipelineContext(url="https://example.com")
        with pytest.raises(RuntimeError, match="BrowserManager not provided"):
            await stage.execute(ctx)

    @pytest.mark.asyncio
    async def test_successful_fetch(self) -> None:
        mock_browser_manager = MagicMock()
        mock_page = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.content = AsyncMock(return_value="<html></html>")
        mock_page.wait_for_load_state = AsyncMock()
        mock_browser_manager.acquire_page = AsyncMock(return_value=mock_page)
        mock_browser_manager.release_page = AsyncMock()

        stage = FetchStage(browser_manager=mock_browser_manager)
        ctx = PipelineContext(url="https://example.com")
        result = await stage.execute(ctx)
        assert result.status == StageStatus.COMPLETED
        assert ctx.raw_html == "<html></html>"
        assert ctx.status_code == 200

    @pytest.mark.asyncio
    async def test_fetch_with_actions(self) -> None:
        mock_browser_manager = MagicMock()
        mock_page = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.content = AsyncMock(return_value="<html></html>")
        mock_browser_manager.acquire_page = AsyncMock(return_value=mock_page)
        mock_browser_manager.release_page = AsyncMock()

        config = MagicMock()
        config.actions = [{"type": "click", "selector": "#btn"}]
        config.timeout = 30
        config.navigation_timeout_ms = 30000

        stage = FetchStage(browser_manager=mock_browser_manager)
        ctx = PipelineContext(url="https://example.com", config=config)
        result = await stage.execute(ctx)
        assert result.status == StageStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_fetch_no_response(self) -> None:
        """Test fetch when page.goto returns None (no response)."""
        mock_browser_manager = MagicMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.content = AsyncMock(return_value="<html></html>")
        mock_page.wait_for_load_state = AsyncMock()
        mock_browser_manager.acquire_page = AsyncMock(return_value=mock_page)
        mock_browser_manager.release_page = AsyncMock()

        stage = FetchStage(browser_manager=mock_browser_manager)
        ctx = PipelineContext(url="https://example.com")
        await stage.execute(ctx)
        assert ctx.status_code == 0

    @pytest.mark.asyncio
    async def test_fetch_on_error_releases_page(self) -> None:
        """Test on_error releases page properly."""
        mock_browser_manager = MagicMock()
        mock_browser_manager.release_page = AsyncMock()

        stage = FetchStage(browser_manager=mock_browser_manager)
        ctx = PipelineContext(url="https://example.com")
        ctx.page = MagicMock()  # Simulate page was set
        result = await stage.on_error(ctx, ValueError("test"))
        assert result is False  # Should abort
        assert ctx.page is None

    @pytest.mark.asyncio
    async def test_fetch_on_error_no_page(self) -> None:
        """Test on_error when no page is set."""
        mock_browser_manager = MagicMock()
        stage = FetchStage(browser_manager=mock_browser_manager)
        ctx = PipelineContext(url="https://example.com")
        result = await stage.on_error(ctx, ValueError("test"))
        assert result is False


# ═══ ParseStage Tests ═══


class TestParseStage:
    """Tests for ParseStage."""

    @pytest.mark.asyncio
    async def test_parse_success(self) -> None:
        stage = ParseStage()
        ctx = PipelineContext(url="https://example.com", raw_html="<html><body>Hello</body></html>")
        await stage.execute(ctx)
        assert ctx.status_code == 0  # No error

    @pytest.mark.asyncio
    async def test_parse_with_metadata_disabled(self) -> None:
        stage = ParseStage()
        config = MagicMock()
        config.include_metadata = False
        config.include_links = True
        config.selectors = None
        config.exclude_selectors = None
        config.only_main_content = True

        ctx = PipelineContext(url="https://example.com", raw_html="<html></html>", config=config)
        result = await stage.execute(ctx)
        assert result.status == StageStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_parse_no_links(self) -> None:
        stage = ParseStage()
        config = MagicMock()
        config.include_metadata = True
        config.include_links = False
        config.selectors = None
        config.exclude_selectors = None
        config.only_main_content = True

        ctx = PipelineContext(url="https://example.com", raw_html="<html></html>", config=config)
        result = await stage.execute(ctx)
        assert result.status == StageStatus.COMPLETED

    def test_should_skip_empty_html(self) -> None:
        stage = ParseStage()
        ctx = PipelineContext(url="https://x", raw_html="")
        assert stage.should_skip(ctx) is True

    def test_should_skip_no_raw_html(self) -> None:
        stage = ParseStage()
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_not_skip_with_html(self) -> None:
        stage = ParseStage()
        ctx = PipelineContext(url="https://x", raw_html="<html></html>")
        assert stage.should_skip(ctx) is False


# ═══ ConvertStage Tests ═══


class TestConvertStage:
    """Tests for ConvertStage."""

    @pytest.mark.asyncio
    async def test_convert_markdown(self) -> None:
        stage = ConvertStage()
        ctx = PipelineContext(
            url="https://example.com",
            main_content_html="<html><body>Hello</body></html>",
            main_content_text="Hello",
        )
        await stage.execute(ctx)
        assert ctx.markdown is not None

    @pytest.mark.asyncio
    async def test_convert_json(self) -> None:
        stage = ConvertStage()
        config = MagicMock()
        config.output_format = "json"
        ctx = PipelineContext(
            url="https://example.com",
            main_content_html="<html></html>",
            main_content_text="Hello",
            metadata={"title": "Test"},
            links={"internal": [], "external": [], "all": []},
            config=config,
        )
        await stage.execute(ctx)
        assert ctx.json is not None
        assert ctx.json["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_convert_default_config(self) -> None:
        stage = ConvertStage()
        ctx = PipelineContext(
            url="https://example.com",
            main_content_html="<html></html>",
            main_content_text="Hello",
        )
        await stage.execute(ctx)
        assert ctx.markdown is not None
        assert ctx.text == "Hello"

    def test_name(self) -> None:
        stage = ConvertStage()
        assert stage.name == "convert"


# ═══ FilterStage Tests ═══


class TestFilterStage:
    """Tests for FilterStage."""

    def test_should_skip_no_config(self) -> None:
        stage = FilterStage()
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_skip_none_filter(self) -> None:
        stage = FilterStage()
        config = MagicMock()
        config.content_filter = None
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_skip_string_none(self) -> None:
        stage = FilterStage()
        config = MagicMock()
        config.content_filter = "none"
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_not_skip_with_filter(self) -> None:
        stage = FilterStage()
        config = MagicMock()
        config.content_filter = "bm25"
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    @pytest.mark.asyncio
    async def test_filter_no_content_filter(self) -> None:
        stage = FilterStage()
        ctx = PipelineContext(url="https://x", markdown="# Hello", config=MagicMock())
        with patch(
            "agentcrawl.content.content_filter.create_content_filter_from_config"
        ) as mock_create:
            mock_create.return_value = None
            await stage.execute(ctx)
            assert ctx.filtered_text == "# Hello"

    @pytest.mark.asyncio
    async def test_filter_with_content_filter(self) -> None:
        stage = FilterStage()
        config = MagicMock()
        config.content_filter = "bm25"
        ctx = PipelineContext(url="https://x", markdown="# Hello", config=config)

        mock_filter = MagicMock()
        mock_result = MagicMock()
        mock_result.filtered_text = "Filtered text"
        mock_result.to_dict.return_value = {"filter": "stats"}
        mock_filter.apply.return_value = mock_result

        with patch(
            "agentcrawl.content.content_filter.create_content_filter_from_config"
        ) as mock_create:
            mock_create.return_value = mock_filter
            await stage.execute(ctx)
            assert ctx.filtered_text == "Filtered text"
            assert ctx.markdown == "Filtered text"
            assert ctx.filter_stats == {"filter": "stats"}


# ═══ ChunkStage Tests ═══


class TestChunkStage:
    """Tests for ChunkStage."""

    def test_should_skip_no_config(self) -> None:
        stage = ChunkStage()
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_skip_none_chunker(self) -> None:
        stage = ChunkStage()
        config = MagicMock()
        config.chunker = None
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_skip_string_none(self) -> None:
        stage = ChunkStage()
        config = MagicMock()
        config.chunker = "none"
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_not_skip_with_chunker(self) -> None:
        stage = ChunkStage()
        config = MagicMock()
        config.chunker = "topic"
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    @pytest.mark.asyncio
    async def test_chunk_no_chunker(self) -> None:
        stage = ChunkStage()
        ctx = PipelineContext(url="https://x", markdown="# Hello", config=MagicMock())
        with patch("agentcrawl.content.chunker.create_chunker_from_config") as mock_create:
            mock_create.return_value = None
            await stage.execute(ctx)
            assert ctx.chunks == []

    @pytest.mark.asyncio
    async def test_chunk_with_chunker(self) -> None:
        stage = ChunkStage()
        config = MagicMock()
        config.chunker = "topic"
        ctx = PipelineContext(url="https://x", markdown="# Hello", config=config)

        mock_chunker = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.to_dict.return_value = {"text": "chunk"}
        mock_result = MagicMock()
        mock_result.chunks = [mock_chunk]
        mock_result.total_chunks = 1
        mock_result.total_tokens = 10
        mock_result.avg_chunk_tokens = 10.0
        mock_result.strategy = "topic"
        mock_chunker.chunk.return_value = mock_result

        with patch("agentcrawl.content.chunker.create_chunker_from_config") as mock_create:
            mock_create.return_value = mock_chunker
            await stage.execute(ctx)
            assert len(ctx.chunks) == 1
            assert ctx.chunk_stats["total_chunks"] == 1
            assert ctx.chunk_stats["strategy"] == "topic"


# ═══ CitationStage Tests ═══


class TestCitationStage:
    """Tests for CitationStage."""

    def test_should_skip_no_config(self) -> None:
        stage = CitationStage()
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_skip_false_config(self) -> None:
        stage = CitationStage()
        config = MagicMock()
        config.include_citations = False
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_not_skip_true_config(self) -> None:
        stage = CitationStage()
        config = MagicMock()
        config.include_citations = True
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    @pytest.mark.asyncio
    async def test_citation_execute(self) -> None:
        stage = CitationStage()
        ctx = PipelineContext(url="https://x", markdown="# Hello [1](http://ref.com)")

        mock_citation = MagicMock()
        mock_citation.to_dict.return_value = {"number": 1, "url": "http://ref.com"}
        mock_result = MagicMock()
        mock_result.citations = [mock_citation]
        mock_result.format_bibliography.return_value = "Reference 1"

        with patch("agentcrawl.content.citation.CitationExtractor") as mock_cls:
            mock_cls.return_value = MagicMock()
            mock_instance = mock_cls.return_value
            mock_instance.extract.return_value = mock_result
            await stage._execute(ctx)
            assert len(ctx.citations) == 1
            assert ctx.citations[0] == {"number": 1, "url": "http://ref.com"}
            assert ctx.bibliography == "Reference 1"


# ═══ ExtractionStage Tests ═══


class TestExtractionStage:
    """Tests for ExtractionStage."""

    def test_should_skip_no_config(self) -> None:
        stage = ExtractionStage()
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_skip_none_extraction(self) -> None:
        stage = ExtractionStage()
        config = MagicMock()
        config.extraction = None
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_not_skip_with_extraction(self) -> None:
        stage = ExtractionStage()
        config = MagicMock()
        config.extraction = MagicMock()
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    @pytest.mark.asyncio
    async def test_extraction_execute(self) -> None:
        stage = ExtractionStage()
        mock_extraction = AsyncMock()
        mock_extraction.extract = AsyncMock(return_value={"key": "value"})
        config = MagicMock()
        config.extraction = mock_extraction
        ctx = PipelineContext(
            url="https://x",
            main_content_html="<html></html>",
            markdown="# Hello",
            config=config,
        )
        await stage.execute(ctx)
        mock_extraction.extract.assert_awaited_once()
        assert ctx.extracted_data == {"key": "value"}


# ═══ ScreenshotStage Tests ═══


class TestScreenshotStage:
    """Tests for ScreenshotStage."""

    def test_should_skip_no_config(self) -> None:
        stage = ScreenshotStage()
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_skip_no_screenshot(self) -> None:
        stage = ScreenshotStage()
        config = MagicMock()
        config.include_screenshot = False
        config.screenshot = None
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_skip_with_screenshot(self) -> None:
        stage = ScreenshotStage()
        config = MagicMock()
        config.include_screenshot = True
        config.screenshot = None
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    def test_should_skip_with_screenshot_enabled_attr(self) -> None:
        stage = ScreenshotStage()
        config = MagicMock()
        config.include_screenshot = False
        config.screenshot = MagicMock(enabled=True)
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    @pytest.mark.asyncio
    async def test_screenshot_no_page(self) -> None:
        stage = ScreenshotStage()
        ctx = PipelineContext(url="https://x")
        await stage._execute(ctx)
        # Should just log and return (page is None)

    @pytest.mark.asyncio
    async def test_screenshot_with_page(self) -> None:
        import base64

        stage = ScreenshotStage()
        config = MagicMock()
        config.screenshot = None
        ctx = PipelineContext(url="https://x", config=config)
        ctx.page = MagicMock()
        ctx.page.screenshot = AsyncMock(return_value=b"fake_png_data")

        await stage._execute(ctx)
        assert ctx.screenshot == base64.b64encode(b"fake_png_data").decode()

    @pytest.mark.asyncio
    async def test_screenshot_with_options(self) -> None:
        stage = ScreenshotStage()
        config = MagicMock()
        config.screenshot = MagicMock(full_page=False, format="jpeg")
        ctx = PipelineContext(url="https://x", config=config)
        ctx.page = MagicMock()
        ctx.page.screenshot = AsyncMock(return_value=b"jpeg_data")

        await stage._execute(ctx)
        assert "jpeg" in ctx.screenshot or ctx.screenshot  # base64 encoded


# ═══ CacheReadStage Tests ═══


class TestCacheReadStage:
    """Tests for CacheReadStage."""

    def test_should_skip_no_config(self) -> None:
        stage = CacheReadStage(cache_manager=MagicMock())
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_skip_cache_false(self) -> None:
        stage = CacheReadStage(cache_manager=MagicMock())
        config = MagicMock()
        config.cache = False
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_not_skip(self) -> None:
        stage = CacheReadStage(cache_manager=MagicMock())
        config = MagicMock()
        config.cache = True
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    @pytest.mark.asyncio
    async def test_cache_read_no_cache_manager(self) -> None:
        stage = CacheReadStage(cache_manager=None)
        ctx = PipelineContext(url="https://x", config=MagicMock())
        await stage.execute(ctx)
        assert ctx.error is None

    @pytest.mark.asyncio
    async def test_cache_read_hit(self) -> None:
        mock_cache = MagicMock()
        mock_cache.key_generator.from_url = MagicMock(return_value="key123")
        mock_cache.get = AsyncMock(
            return_value={
                "raw_html": "<html></html>",
                "markdown": "# cached",
                "status_code": 200,
            }
        )
        stage = CacheReadStage(cache_manager=mock_cache)
        config = MagicMock()
        config.output_format = "markdown"
        config.cache = True
        ctx = PipelineContext(url="https://x", config=config)
        await stage.execute(ctx)
        assert ctx.raw_html == "<html></html>"
        assert ctx.markdown == "# cached"
        assert ctx.status_code == 200
        assert ctx.extra["cache_hit"] is True

    @pytest.mark.asyncio
    async def test_cache_read_no_hit(self) -> None:
        mock_cache = MagicMock()
        mock_cache.key_generator.from_url = MagicMock(return_value="key123")
        mock_cache.get = AsyncMock(return_value=None)
        stage = CacheReadStage(cache_manager=mock_cache)
        config = MagicMock()
        config.output_format = "markdown"
        config.cache = True
        ctx = PipelineContext(url="https://x", config=config)
        await stage.execute(ctx)
        assert ctx.raw_html == ""  # Not populated


# ═══ CacheWriteStage Tests ═══


class TestCacheWriteStage:
    """Tests for CacheWriteStage."""

    def test_should_skip_no_config(self) -> None:
        stage = CacheWriteStage(cache_manager=MagicMock())
        ctx = PipelineContext(url="https://x")
        assert stage.should_skip(ctx) is True

    def test_should_skip_cache_false(self) -> None:
        stage = CacheWriteStage(cache_manager=MagicMock())
        config = MagicMock()
        config.cache = False
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is True

    def test_should_skip_with_error(self) -> None:
        stage = CacheWriteStage(cache_manager=MagicMock())
        config = MagicMock()
        config.cache = True
        ctx = PipelineContext(url="https://x", config=config, error="some error")
        assert stage.should_skip(ctx) is True

    def test_should_not_skip(self) -> None:
        stage = CacheWriteStage(cache_manager=MagicMock())
        config = MagicMock()
        config.cache = True
        ctx = PipelineContext(url="https://x", config=config)
        assert stage.should_skip(ctx) is False

    @pytest.mark.asyncio
    async def test_cache_write_no_cache_manager(self) -> None:
        stage = CacheWriteStage(cache_manager=None)
        ctx = PipelineContext(url="https://x", config=MagicMock())
        await stage.execute(ctx)

    @pytest.mark.asyncio
    async def test_cache_write_cache_hit(self) -> None:
        """Test that cache hits are not re-cached."""
        mock_cache = MagicMock()
        mock_cache.key_generator.from_url = MagicMock(return_value="key")
        mock_cache.set = AsyncMock()

        stage = CacheWriteStage(cache_manager=mock_cache)
        config = MagicMock()
        config.output_format = "markdown"
        config.cache = True
        config.cache_ttl = None
        ctx = PipelineContext(url="https://x", config=config)
        ctx.extra["cache_hit"] = True

        await stage.execute(ctx)
        mock_cache.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_write_normal(self) -> None:
        """Test normal cache write."""
        mock_cache = MagicMock()
        mock_cache.key_generator.from_url = MagicMock(return_value="key")
        mock_cache.set = AsyncMock()

        stage = CacheWriteStage(cache_manager=mock_cache)
        config = MagicMock()
        config.output_format = "markdown"
        config.cache = True
        config.cache_ttl = None
        ctx = PipelineContext(url="https://x", config=config)

        await stage.execute(ctx)
        mock_cache.set.assert_awaited_once()
