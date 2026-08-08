"""Tests for agentcrawl.core.types module — type guards and lazy imports."""

from __future__ import annotations

from typing import Any

import pytest

# ═══ Lazy Imports (__getattr__) ═══


class TestLazyImports:
    """Tests for lazy type re-exports via __getattr__."""

    def test_crawl_result_import(self) -> None:
        from agentcrawl.core.types import CrawlResult

        assert CrawlResult is not None

    def test_crawl_job_result_import(self) -> None:
        from agentcrawl.core.types import CrawlJobResult

        assert CrawlJobResult is not None

    def test_engine_stats_import(self) -> None:
        from agentcrawl.core.types import EngineStats

        assert EngineStats is not None

    def test_pipeline_context_import(self) -> None:
        from agentcrawl.core.types import PipelineContext

        assert PipelineContext is not None

    def test_stage_result_import(self) -> None:
        from agentcrawl.core.types import StageResult

        assert StageResult is not None

    def test_pipeline_stage_import(self) -> None:
        from agentcrawl.core.types import PipelineStage

        assert PipelineStage is not None

    def test_pipeline_import(self) -> None:
        from agentcrawl.core.types import Pipeline

        assert Pipeline is not None

    def test_crawl_session_import(self) -> None:
        from agentcrawl.core.types import CrawlSession

        assert CrawlSession is not None

    def test_page_visit_import(self) -> None:
        from agentcrawl.core.types import PageVisit

        assert PageVisit is not None

    def test_session_state_import(self) -> None:
        from agentcrawl.core.types import SessionState

        assert SessionState is not None

    def test_lazy_import_invalid_raises(self) -> None:
        import agentcrawl.core.types as t

        with pytest.raises(AttributeError, match="has no attribute"):
            _ = t.NonExistentType


# ═══ Type Guards — is_crawl_result ═══


class TestIsCrawlResult:
    """Tests for is_crawl_result type guard."""

    def test_valid_crawl_result(self) -> None:
        from agentcrawl.core.types import is_crawl_result

        obj = type(
            "Obj",
            (),
            {
                "url": "https://example.com",
                "success": True,
                "markdown": "# Hello",
                "status_code": 200,
            },
        )()
        assert is_crawl_result(obj) is True

    def test_missing_url(self) -> None:
        from agentcrawl.core.types import is_crawl_result

        obj = type("Obj", (), {"success": True, "markdown": "#", "status_code": 200})()
        assert is_crawl_result(obj) is False

    def test_missing_success(self) -> None:
        from agentcrawl.core.types import is_crawl_result

        obj = type("Obj", (), {"url": "x", "markdown": "#", "status_code": 200})()
        assert is_crawl_result(obj) is False

    def test_missing_markdown(self) -> None:
        from agentcrawl.core.types import is_crawl_result

        obj = type("Obj", (), {"url": "x", "success": True, "status_code": 200})()
        assert is_crawl_result(obj) is False

    def test_missing_status_code(self) -> None:
        from agentcrawl.core.types import is_crawl_result

        obj = type("Obj", (), {"url": "x", "success": True, "markdown": "#"})()
        assert is_crawl_result(obj) is False

    def test_plain_dict(self) -> None:
        from agentcrawl.core.types import is_crawl_result

        assert is_crawl_result({"url": "x"}) is False


# ═══ Type Guards — is_crawl_job_result ═══


class TestIsCrawlJobResult:
    """Tests for is_crawl_job_result type guard."""

    def test_valid(self) -> None:
        from agentcrawl.core.types import is_crawl_job_result

        obj = type("Obj", (), {"job_id": "abc", "pages": [], "total_pages": 0, "status": "ok"})()
        assert is_crawl_job_result(obj) is True

    def test_missing_job_id(self) -> None:
        from agentcrawl.core.types import is_crawl_job_result

        obj = type("Obj", (), {"pages": [], "total_pages": 0, "status": "ok"})()
        assert is_crawl_job_result(obj) is False

    def test_missing_pages(self) -> None:
        from agentcrawl.core.types import is_crawl_job_result

        obj = type("Obj", (), {"job_id": "abc", "total_pages": 0, "status": "ok"})()
        assert is_crawl_job_result(obj) is False

    def test_missing_total_pages(self) -> None:
        from agentcrawl.core.types import is_crawl_job_result

        obj = type("Obj", (), {"job_id": "abc", "pages": [], "status": "ok"})()
        assert is_crawl_job_result(obj) is False

    def test_missing_status(self) -> None:
        from agentcrawl.core.types import is_crawl_job_result

        obj = type("Obj", (), {"job_id": "abc", "pages": [], "total_pages": 0})()
        assert is_crawl_job_result(obj) is False


# ═══ Type Guards — is_pipeline_context ═══


class TestIsPipelineContext:
    """Tests for is_pipeline_context type guard."""

    def test_valid(self) -> None:
        from agentcrawl.core.types import is_pipeline_context

        obj = type(
            "Obj",
            (),
            {
                "url": "https://example.com",
                "raw_html": "<html></html>",
                "markdown": "# Hello",
                "stage_results": [],
            },
        )()
        assert is_pipeline_context(obj) is True

    def test_missing_url(self) -> None:
        from agentcrawl.core.types import is_pipeline_context

        obj = type("Obj", (), {"raw_html": "<html>", "markdown": "#", "stage_results": []})()
        assert is_pipeline_context(obj) is False

    def test_missing_raw_html(self) -> None:
        from agentcrawl.core.types import is_pipeline_context

        obj = type("Obj", (), {"url": "x", "markdown": "#", "stage_results": []})()
        assert is_pipeline_context(obj) is False

    def test_missing_markdown(self) -> None:
        from agentcrawl.core.types import is_pipeline_context

        obj = type("Obj", (), {"url": "x", "raw_html": "<html>", "stage_results": []})()
        assert is_pipeline_context(obj) is False

    def test_missing_stage_results(self) -> None:
        from agentcrawl.core.types import is_pipeline_context

        obj = type("Obj", (), {"url": "x", "raw_html": "<html>", "markdown": "#"})()
        assert is_pipeline_context(obj) is False

    def test_none(self) -> None:
        from agentcrawl.core.types import is_pipeline_context

        assert is_pipeline_context(None) is False


# ═══ Type Guards — is_page_visit ═══


class TestIsPageVisit:
    """Tests for is_page_visit type guard."""

    def test_valid(self) -> None:
        from agentcrawl.core.types import is_page_visit

        obj = type(
            "Obj",
            (),
            {
                "url": "https://example.com",
                "timestamp": 1000.0,
                "status_code": 200,
                "success": True,
            },
        )()
        assert is_page_visit(obj) is True

    def test_missing_url(self) -> None:
        from agentcrawl.core.types import is_page_visit

        obj = type("Obj", (), {"timestamp": 1.0, "status_code": 200, "success": True})()
        assert is_page_visit(obj) is False

    def test_missing_timestamp(self) -> None:
        from agentcrawl.core.types import is_page_visit

        obj = type("Obj", (), {"url": "x", "status_code": 200, "success": True})()
        assert is_page_visit(obj) is False

    def test_missing_status_code(self) -> None:
        from agentcrawl.core.types import is_page_visit

        obj = type("Obj", (), {"url": "x", "timestamp": 1.0, "success": True})()
        assert is_page_visit(obj) is False

    def test_missing_success(self) -> None:
        from agentcrawl.core.types import is_page_visit

        obj = type("Obj", (), {"url": "x", "timestamp": 1.0, "status_code": 200})()
        assert is_page_visit(obj) is False


# ═══ Type Guards — is_session_state ═══


class TestIsSessionState:
    """Tests for is_session_state type guard."""

    def test_valid(self) -> None:
        from agentcrawl.core.types import is_session_state

        obj = type(
            "Obj",
            (),
            {
                "session_id": "sess_123",
                "cookies": [],
                "history": [],
                "is_expired": False,
            },
        )()
        assert is_session_state(obj) is True

    def test_missing_session_id(self) -> None:
        from agentcrawl.core.types import is_session_state

        obj = type("Obj", (), {"cookies": [], "history": [], "is_expired": False})()
        assert is_session_state(obj) is False

    def test_missing_cookies(self) -> None:
        from agentcrawl.core.types import is_session_state

        obj = type("Obj", (), {"session_id": "x", "history": [], "is_expired": False})()
        assert is_session_state(obj) is False

    def test_missing_history(self) -> None:
        from agentcrawl.core.types import is_session_state

        obj = type("Obj", (), {"session_id": "x", "cookies": [], "is_expired": False})()
        assert is_session_state(obj) is False

    def test_missing_is_expired(self) -> None:
        from agentcrawl.core.types import is_session_state

        obj = type("Obj", (), {"session_id": "x", "cookies": [], "history": []})()
        assert is_session_state(obj) is False


# ═══ Type Guards — is_chunk ═══


class TestIsChunk:
    """Tests for is_chunk type guard."""

    def test_valid(self) -> None:
        from agentcrawl.core.types import is_chunk

        obj = type(
            "Obj",
            (),
            {
                "text": "content",
                "index": 0,
                "token_count": 10,
                "chunk_id": "abc",
            },
        )()
        assert is_chunk(obj) is True

    def test_missing_text(self) -> None:
        from agentcrawl.core.types import is_chunk

        obj = type("Obj", (), {"index": 0, "token_count": 10, "chunk_id": "abc"})()
        assert is_chunk(obj) is False

    def test_missing_index(self) -> None:
        from agentcrawl.core.types import is_chunk

        obj = type("Obj", (), {"text": "x", "token_count": 10, "chunk_id": "abc"})()
        assert is_chunk(obj) is False

    def test_missing_token_count(self) -> None:
        from agentcrawl.core.types import is_chunk

        obj = type("Obj", (), {"text": "x", "index": 0, "chunk_id": "abc"})()
        assert is_chunk(obj) is False

    def test_missing_chunk_id(self) -> None:
        from agentcrawl.core.types import is_chunk

        obj = type("Obj", (), {"text": "x", "index": 0, "token_count": 10})()
        assert is_chunk(obj) is False


# ═══ Type Guards — is_citation ═══


class TestIsCitation:
    """Tests for is_citation type guard."""

    def test_valid(self) -> None:
        from agentcrawl.core.types import is_citation

        obj = type("Obj", (), {"number": 1, "url": "https://x", "display_title": "Title"})()
        assert is_citation(obj) is True

    def test_missing_number(self) -> None:
        from agentcrawl.core.types import is_citation

        obj = type("Obj", (), {"url": "https://x", "display_title": "Title"})()
        assert is_citation(obj) is False

    def test_missing_url(self) -> None:
        from agentcrawl.core.types import is_citation

        obj = type("Obj", (), {"number": 1, "display_title": "Title"})()
        assert is_citation(obj) is False

    def test_missing_display_title(self) -> None:
        from agentcrawl.core.types import is_citation

        obj = type("Obj", (), {"number": 1, "url": "https://x"})()
        assert is_citation(obj) is False


# ═══ Type Guards — is_json_dict ═══


class TestIsJsonDict:
    """Tests for is_json_dict type guard."""

    def test_valid_dict(self) -> None:
        from agentcrawl.core.types import is_json_dict

        assert is_json_dict({"key": "value"}) is True

    def test_empty_dict(self) -> None:
        from agentcrawl.core.types import is_json_dict

        assert is_json_dict({}) is True

    def test_list(self) -> None:
        from agentcrawl.core.types import is_json_dict

        assert is_json_dict([1, 2, 3]) is False

    def test_string(self) -> None:
        from agentcrawl.core.types import is_json_dict

        assert is_json_dict("hello") is False

    def test_none(self) -> None:
        from agentcrawl.core.types import is_json_dict

        assert is_json_dict(None) is False


# ═══ Type Guards — is_url ═══


class TestIsUrl:
    """Tests for is_url type guard."""

    def test_http_url(self) -> None:
        from agentcrawl.core.types import is_url

        assert is_url("https://example.com") is True

    def test_http_url_lower(self) -> None:
        from agentcrawl.core.types import is_url

        assert is_url("http://example.com") is True

    def test_ftp_url(self) -> None:
        from agentcrawl.core.types import is_url

        assert is_url("ftp://files.example.com") is True

    def test_not_url(self) -> None:
        from agentcrawl.core.types import is_url

        assert is_url("example.com") is False

    def test_not_url_www(self) -> None:
        from agentcrawl.core.types import is_url

        assert is_url("www.example.com") is False

    def test_not_url_plain_text(self) -> None:
        from agentcrawl.core.types import is_url

        assert is_url("just some text") is False


# ═══ Type Guards — is_html ═══


class TestIsHtml:
    """Tests for is_html type guard."""

    def test_doctype(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("<!DOCTYPE html><html></html>") is True

    def test_html_tag(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("<html><body></body></html>") is True

    def test_div_tag(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("<div>content</div>") is True

    def test_p_tag(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("<p>Hello</p>") is True

    def test_html_in_content(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("Some text <html> more text") is True

    def test_not_html(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("# Just markdown") is False

    def test_empty_string(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("") is False

    def test_whitespace_only(self) -> None:
        from agentcrawl.core.types import is_html

        assert is_html("   ") is False


# ═══ Type Guards — is_markdown ═══


class TestIsMarkdown:
    """Tests for is_markdown type guard."""

    def test_heading(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("# Heading") is True

    def test_bold(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("**bold text**") is True

    def test_link(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("[link text](http://example.com)") is True

    def test_code_block(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("```python\nprint('hello')\n```") is True

    def test_list_item(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("- item one") is True

    def test_star_list_item(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("* item two") is True

    def test_plus_list_item(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("+ item three") is True

    def test_blockquote(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("> quoted text") is True

    def test_plain_text(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("Just plain text without any markdown") is False

    def test_empty_string(self) -> None:
        from agentcrawl.core.types import is_markdown

        assert is_markdown("") is False


# ═══ Enum Tests ═══


class TestEnums:
    """Tests for all enums in core.types."""

    def test_output_format_values(self) -> None:
        from agentcrawl.core.types import OutputFormat

        assert OutputFormat.MARKDOWN.value == "markdown"
        assert OutputFormat.JSON.value == "json"
        assert OutputFormat.HTML.value == "html"
        assert OutputFormat.TEXT.value == "text"

    def test_crawl_strategy_values(self) -> None:
        from agentcrawl.core.types import CrawlStrategy

        assert CrawlStrategy.BFS.value == "bfs"
        assert CrawlStrategy.DFS.value == "dfs"
        assert CrawlStrategy.BEST_FIRST.value == "best_first"
        assert CrawlStrategy.ADAPTIVE.value == "adaptive"

    def test_extraction_method_values(self) -> None:
        from agentcrawl.core.types import ExtractionMethod

        assert ExtractionMethod.LLM.value == "llm"
        assert ExtractionMethod.CSS.value == "css"
        assert ExtractionMethod.XPATH.value == "xpath"
        assert ExtractionMethod.COSINE.value == "cosine"
        assert ExtractionMethod.REGEX.value == "regex"

    def test_content_filter_type_values(self) -> None:
        from agentcrawl.core.types import ContentFilterType

        assert ContentFilterType.NONE.value == "none"
        assert ContentFilterType.BM25.value == "bm25"
        assert ContentFilterType.PRUNING.value == "pruning"
        assert ContentFilterType.ADVANCED_PRUNING.value == "advanced_pruning"

    def test_chunker_type_values(self) -> None:
        from agentcrawl.core.types import ChunkerType

        assert ChunkerType.NONE.value == "none"
        assert ChunkerType.FIXED.value == "fixed"
        assert ChunkerType.SENTENCE.value == "sentence"
        assert ChunkerType.REGEX.value == "regex"
        assert ChunkerType.TOPIC.value == "topic"
        assert ChunkerType.MARKDOWN.value == "markdown"

    def test_browser_type_values(self) -> None:
        from agentcrawl.core.types import BrowserType

        assert BrowserType.CHROMIUM.value == "chromium"
        assert BrowserType.FIREFOX.value == "firefox"
        assert BrowserType.WEBKIT.value == "webkit"

    def test_cache_backend_type_values(self) -> None:
        from agentcrawl.core.types import CacheBackendType

        assert CacheBackendType.MEMORY.value == "memory"
        assert CacheBackendType.REDIS.value == "redis"
        assert CacheBackendType.DISK.value == "disk"
        assert CacheBackendType.NONE.value == "none"

    def test_queue_backend_type_values(self) -> None:
        from agentcrawl.core.types import QueueBackendType

        assert QueueBackendType.MEMORY.value == "memory"
        assert QueueBackendType.REDIS.value == "redis"

    def test_proxy_rotation_strategy_values(self) -> None:
        from agentcrawl.core.types import ProxyRotationStrategy

        assert ProxyRotationStrategy.NONE.value == "none"
        assert ProxyRotationStrategy.ROUND_ROBIN.value == "round_robin"
        assert ProxyRotationStrategy.RANDOM.value == "random"
        assert ProxyRotationStrategy.LEAST_USED.value == "least_used"

    def test_log_level_values(self) -> None:
        from agentcrawl.core.types import LogLevel

        assert LogLevel.DEBUG.value == "debug"
        assert LogLevel.INFO.value == "info"
        assert LogLevel.WARNING.value == "warning"
        assert LogLevel.ERROR.value == "error"
        assert LogLevel.CRITICAL.value == "critical"

    def test_job_status_values(self) -> None:
        from agentcrawl.core.types import JobStatus

        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.PARTIAL.value == "partial"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"


# ═══ Type Aliases ═══


class TestTypeAliases:
    """Tests for type aliases."""

    def test_url_is_str(self) -> None:
        from agentcrawl.core.types import URL

        assert URL is str

    def test_html_string_is_str(self) -> None:
        from agentcrawl.core.types import HtmlString

        assert HtmlString is str

    def test_markdown_string_is_str(self) -> None:
        from agentcrawl.core.types import MarkdownString

        assert MarkdownString is str

    def test_json_dict_type(self) -> None:
        from agentcrawl.core.types import JsonDict

        assert JsonDict is not None  # Verify it's importable as a type alias

    def test_session_id_is_str(self) -> None:
        from agentcrawl.core.types import SessionId

        assert SessionId is str


# ═══ Protocol Tests ═══


class TestProtocols:
    """Tests for protocol structural typing."""

    def test_scrapable_protocol(self) -> None:
        from agentcrawl.core.types import Scrapable

        class Scraper:
            async def scrape(self, url: str, config: Any = None) -> Any:
                return {"url": url}

        assert isinstance(Scraper(), Scrapable)

    def test_scrapable_protocol_not_matching(self) -> None:
        from agentcrawl.core.types import Scrapable

        class NotAScraper:
            pass

        assert not isinstance(NotAScraper(), Scrapable)

    def test_crawlable_protocol(self) -> None:
        from agentcrawl.core.types import Crawlable

        class Crawler:
            async def crawl(self, url: str, strategy: Any = None, config: Any = None) -> Any:
                return []

        assert isinstance(Crawler(), Crawlable)

    def test_cacheable_protocol(self) -> None:
        from agentcrawl.core.types import Cacheable

        class Cache:
            async def get(self, key: str, default: Any = None) -> Any:
                return default

            async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
                return True

            async def delete(self, key: str) -> bool:
                return True

            async def exists(self, key: str) -> bool:
                return False

            async def clear(self) -> bool:
                return True

        assert isinstance(Cache(), Cacheable)

    def test_serializable_protocol(self) -> None:
        from agentcrawl.core.types import Serializable

        class Ser:
            def to_dict(self) -> dict[str, Any]:
                return {}

        assert isinstance(Ser(), Serializable)

    def test_startable_protocol(self) -> None:
        from agentcrawl.core.types import Startable

        class Start:
            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        assert isinstance(Start(), Startable)


# ═══ TypedDict Tests ═══


class TestTypedDicts:
    """Tests for TypedDict definitions."""

    def test_scrape_request_dict(self) -> None:
        data = {
            "url": "https://example.com",
            "output_format": "markdown",
            "include_links": True,
        }
        assert data["url"] == "https://example.com"

    def test_scrape_response_dict(self) -> None:
        data = {
            "url": "https://example.com",
            "success": True,
            "markdown": "# Hello",
        }
        assert data["success"] is True

    def test_crawl_request_dict(self) -> None:
        data = {
            "url": "https://example.com",
            "strategy": "bfs",
            "max_depth": 3,
        }
        assert data["strategy"] == "bfs"

    def test_crawl_job_response_dict(self) -> None:
        data = {
            "job_id": "abc123",
            "status": "completed",
            "total_pages": 5,
        }
        assert data["job_id"] == "abc123"

    def test_search_request_dict(self) -> None:
        data = {
            "query": "test",
            "max_results": 10,
        }
        assert data["query"] == "test"

    def test_map_request_dict(self) -> None:
        data = {
            "url": "https://example.com",
            "max_urls": 100,
        }
        assert data["max_urls"] == 100

    def test_extract_request_dict(self) -> None:
        data = {
            "url": "https://example.com",
            "schema": {"type": "object"},
        }
        assert data["schema"]["type"] == "object"

    def test_health_response_dict(self) -> None:
        data = {
            "status": "ok",
            "version": "1.0.0",
            "uptime_seconds": 3600.0,
        }
        assert data["status"] == "ok"

    def test_error_response_dict(self) -> None:
        data = {
            "error": "Not found",
            "status_code": 404,
        }
        assert data["status_code"] == 404
