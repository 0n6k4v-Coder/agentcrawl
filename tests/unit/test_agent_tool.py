"""Tests for agentcrawl.agent.tool module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcrawl.agent.tool import (
    AgentCrawlToolkit,
    OpenAIFunctionHandler,
    WebBatchScrapeInput,
    WebCrawlInput,
    WebExtractInput,
    WebMapInput,
    WebScrapeInput,
    WebScreenshotInput,
    WebSearchInput,
    create_toolkit,
)

# ─── Input Schema Tests ───────────────────────────────────────


class TestInputSchemas:
    """Tests for Pydantic input schemas."""

    def test_web_scrape_input_defaults(self):
        schema = WebScrapeInput(url="https://example.com")
        assert schema.url == "https://example.com"
        assert schema.output_format == "markdown"
        assert schema.include_links is True
        assert schema.include_metadata is True
        assert schema.stealth is True
        assert schema.timeout == 30

    def test_web_scrape_input_required(self):
        with pytest.raises(ValueError):
            WebScrapeInput()

    def test_web_crawl_input_defaults(self):
        schema = WebCrawlInput(url="https://example.com")
        assert schema.strategy == "bfs"
        assert schema.max_depth == 3
        assert schema.max_pages == 50
        assert schema.output_format == "markdown"
        assert schema.same_domain_only is True

    def test_web_crawl_input_required(self):
        with pytest.raises(ValueError):
            WebCrawlInput()

    def test_web_search_input_defaults(self):
        schema = WebSearchInput(query="test")
        assert schema.max_results == 5
        assert schema.scrape_results is True
        assert schema.output_format == "markdown"

    def test_web_search_input_required(self):
        with pytest.raises(ValueError):
            WebSearchInput()

    def test_web_map_input_defaults(self):
        schema = WebMapInput(url="https://example.com")
        assert schema.max_urls == 500
        assert schema.use_sitemap is True
        assert schema.use_robots is True

    def test_web_map_input_required(self):
        with pytest.raises(ValueError):
            WebMapInput()

    def test_web_extract_input_defaults(self):
        schema = WebExtractInput(url="https://example.com", extraction_schema_json="{}")
        assert schema.method == "llm"
        assert schema.prompt == ""

    def test_web_extract_input_required(self):
        with pytest.raises(ValueError):
            WebExtractInput()

    def test_web_screenshot_input_defaults(self):
        schema = WebScreenshotInput(url="https://example.com")
        assert schema.full_page is True
        assert schema.format == "png"

    def test_web_screenshot_input_required(self):
        with pytest.raises(ValueError):
            WebScreenshotInput()

    def test_web_batch_scrape_input_defaults(self):
        schema = WebBatchScrapeInput(urls="https://example.com,https://test.com")
        assert schema.output_format == "markdown"
        assert schema.max_concurrent == 5

    def test_web_batch_scrape_input_required(self):
        with pytest.raises(ValueError):
            WebBatchScrapeInput()


# ─── AgentCrawlToolkit ───────────────────────────────────────


class TestAgentCrawlToolkitInit:
    """Tests for AgentCrawlToolkit initialization."""

    def test_defaults(self):
        toolkit = AgentCrawlToolkit()
        assert toolkit._max_content_length == 50000
        assert toolkit._return_format == "dict"

    def test_custom_max_content_length(self):
        toolkit = AgentCrawlToolkit(max_content_length=100)
        assert toolkit._max_content_length == 100

    def test_custom_return_format_dict(self):
        toolkit = AgentCrawlToolkit(return_format="dict")
        assert toolkit._return_format == "dict"

    def test_custom_return_format_json(self):
        toolkit = AgentCrawlToolkit(return_format="json")
        assert toolkit._return_format == "json"

    def test_custom_return_format_text(self):
        toolkit = AgentCrawlToolkit(return_format="text")
        assert toolkit._return_format == "text"

    def test_registry_built(self):
        toolkit = AgentCrawlToolkit()
        assert "web_scrape" in toolkit._tool_registry
        assert "web_crawl" in toolkit._tool_registry
        assert "web_search" in toolkit._tool_registry
        assert "web_map" in toolkit._tool_registry
        assert "web_extract" in toolkit._tool_registry
        assert "web_screenshot" in toolkit._tool_registry
        assert "web_batch_scrape" in toolkit._tool_registry

    def test_registry_has_handlers_and_schemas(self):
        toolkit = AgentCrawlToolkit()
        for _name, info in toolkit._tool_registry.items():
            assert "handler" in info
            assert "input_schema" in info
            assert "description" in info


# ─── AgentCrawlToolkit Public API ───────────────────────────


class TestToolkitPublicAPI:
    """Tests for AgentCrawlToolkit public methods."""

    def test_list_tools(self):
        toolkit = AgentCrawlToolkit()
        tools = toolkit.list_tools()
        assert len(tools) == 7
        names = [t["name"] for t in tools]
        assert "web_scrape" in names
        assert "web_crawl" in names

    def test_get_tool_names(self):
        toolkit = AgentCrawlToolkit()
        names = toolkit.get_tool_names()
        assert len(names) == 7
        assert "web_scrape" in names

    def test_get_openai_schema(self):
        toolkit = AgentCrawlToolkit()
        schema = toolkit.get_openai_schema()
        assert len(schema) == 7
        assert schema[0]["type"] == "function"

    def test_get_openai_schema_filtered(self):
        toolkit = AgentCrawlToolkit()
        schema = toolkit.get_openai_schema(["web_scrape"])
        assert len(schema) == 1
        assert schema[0]["function"]["name"] == "web_scrape"

    def test_get_anthropic_schema(self):
        toolkit = AgentCrawlToolkit()
        schema = toolkit.get_anthropic_schema()
        assert len(schema) == 7
        assert "input_schema" in schema[0]

    def test_get_anthropic_schema_filtered(self):
        toolkit = AgentCrawlToolkit()
        schema = toolkit.get_anthropic_schema(["web_crawl"])
        assert len(schema) == 1
        assert schema[0]["name"] == "web_crawl"


# ─── AgentCrawlToolkit.execute ──────────────────────────────


class TestEngineManager:
    """Tests for _EngineManager private class."""

    @pytest.mark.asyncio
    async def test_get_engine_already_initialized(self):
        from agentcrawl.agent.tool import _EngineManager

        mgr = _EngineManager()
        mgr._engine = MagicMock()
        result = await mgr.get_engine()
        assert result is mgr._engine

    @pytest.mark.asyncio
    async def test_get_engine_creates_new(self):
        from agentcrawl.agent.tool import _EngineManager

        mgr = _EngineManager()
        mock_engine = MagicMock()
        mock_engine.startup = AsyncMock()

        with (
            patch("agentcrawl.config.settings.Settings"),
            patch("agentcrawl.core.engine.CrawlEngine") as mock_engine_cls,
        ):
            mock_engine_cls.from_settings.return_value = mock_engine
            result = await mgr.get_engine()

        assert result is mock_engine
        assert mgr.is_initialized is True

    @pytest.mark.asyncio
    async def test_shutdown_not_initialized(self):
        from agentcrawl.agent.tool import _EngineManager

        mgr = _EngineManager()
        await mgr.shutdown()
        # Should not raise, should just do nothing

    @pytest.mark.asyncio
    async def test_shutdown_after_init(self):
        from agentcrawl.agent.tool import _EngineManager

        mgr = _EngineManager()
        mgr._engine = MagicMock()
        mgr._engine.shutdown = AsyncMock()
        mgr._initialized = True

        await mgr.shutdown()

        assert mgr._engine is None
        assert mgr.is_initialized is False

    def test_is_initialized_false(self):
        from agentcrawl.agent.tool import _EngineManager

        mgr = _EngineManager()
        assert mgr.is_initialized is False

    @pytest.mark.asyncio
    async def test_get_engine_double_lock(self):
        """Test double-checked locking in get_engine."""
        from agentcrawl.agent.tool import _EngineManager

        mgr = _EngineManager()
        mgr._engine = MagicMock()  # Already set

        # Should return early without acquiring lock
        result = await mgr.get_engine()
        assert result is mgr._engine


class TestToolkitExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        toolkit = AgentCrawlToolkit()
        with pytest.raises(ValueError, match="Unknown tool"):
            await toolkit.execute("nonexistent")

    @pytest.mark.asyncio
    async def test_execute_returns_dict_on_error(self):
        toolkit = AgentCrawlToolkit()
        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(side_effect=Exception("Scrape failed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit.execute("web_scrape", url="https://example.com")

        assert result["success"] is False
        assert result["error"] == "Scrape failed"
        assert result["tool"] == "web_scrape"

    @pytest.mark.asyncio
    async def test_execute_format_result_json(self):
        toolkit = AgentCrawlToolkit(return_format="json")
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.metadata = {}
        mock_result.links = {}
        mock_result.to_json.return_value = '{"url": "..."}'

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit.execute("web_scrape", url="https://example.com")

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["url"] == "https://example.com"


# ─── AgentCrawlToolkit.execute_json ────────────────────────


class TestExecuteJson:
    """Tests for execute_json method."""

    @pytest.mark.asyncio
    async def test_execute_json_valid(self):
        toolkit = AgentCrawlToolkit(return_format="json")
        mock_engine = AsyncMock()
        mock_engine.scrape.return_value = MagicMock(
            url="https://example.com",
            markdown="# Hello",
            metadata={},
            links={},
            to_json=lambda: '{"url": "..."}',
        )

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit.execute_json("web_scrape", '{"url": "https://example.com"}')

        parsed = json.loads(result)
        assert parsed["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_execute_json_invalid(self):
        toolkit = AgentCrawlToolkit()
        result = await toolkit.execute_json("web_scrape", "{invalid json}")

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]


# ─── AgentCrawlToolkit.close ─────────────────────────────────


class TestToolkitClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        toolkit = AgentCrawlToolkit()
        mock_mgr = MagicMock()
        mock_mgr.shutdown = AsyncMock()
        with patch("agentcrawl.agent.tool._engine_manager", mock_mgr):
            await toolkit.close()
            mock_mgr.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        AgentCrawlToolkit()
        mock_mgr = MagicMock()
        mock_mgr.shutdown = AsyncMock()
        with patch("agentcrawl.agent.tool._engine_manager", mock_mgr):
            async with AgentCrawlToolkit():
                pass
            mock_mgr.shutdown.assert_awaited_once()


# ─── _format_result ─────────────────────────────────────────


class TestFormatResult:
    """Tests for _format_result method."""

    def test_format_dict(self):
        toolkit = AgentCrawlToolkit(return_format="dict")
        result = {"success": True, "content": "test"}
        assert toolkit._format_result(result) == result

    def test_format_json(self):
        toolkit = AgentCrawlToolkit(return_format="json")
        result = {"success": True, "content": "test"}
        formatted = toolkit._format_result(result)
        parsed = json.loads(formatted)
        assert parsed["success"] is True

    def test_format_text_success(self):
        toolkit = AgentCrawlToolkit(return_format="text")
        result = {"success": True, "content": "Hello World"}
        formatted = toolkit._format_result(result)
        assert formatted == "Hello World"

    def test_format_text_error(self):
        toolkit = AgentCrawlToolkit(return_format="text")
        result = {"success": False, "error": "Something went wrong"}
        formatted = toolkit._format_result(result)
        assert "Error" in formatted
        assert "Something went wrong" in formatted

    def test_format_text_error_no_message(self):
        toolkit = AgentCrawlToolkit(return_format="text")
        result = {"success": False}  # No "error" key
        formatted = toolkit._format_result(result)
        assert "Unknown error" in formatted

    def test_format_text_no_content(self):
        toolkit = AgentCrawlToolkit(return_format="text")
        result = {"success": True}
        formatted = toolkit._format_result(result)
        # When no "content" key, returns json.dumps(result)
        assert json.loads(formatted)["success"] is True


# ─── _truncate ───────────────────────────────────────────────


class TestTruncate:
    """Tests for _truncate method."""

    def test_short_content(self):
        toolkit = AgentCrawlToolkit(max_content_length=100)
        assert toolkit._truncate("short") == "short"

    def test_exact_length(self):
        toolkit = AgentCrawlToolkit(max_content_length=5)
        assert toolkit._truncate("12345") == "12345"

    def test_truncated_content(self):
        toolkit = AgentCrawlToolkit(max_content_length=5)
        result = toolkit._truncate("123456789")
        assert result.startswith("12345")
        assert "truncated" in result
        assert "9" in result  # total length

    def test_truncate_with_special_chars(self):
        toolkit = AgentCrawlToolkit(max_content_length=5)
        result = toolkit._truncate("Hello World!")
        assert "truncated" in result


# ─── _handle_scrape ─────────────────────────────────────────


class TestHandleScrape:
    """Tests for _handle_scrape."""

    @pytest.mark.asyncio
    async def test_scrape_success(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.metadata = {"title": "Test"}
        mock_result.links = {"internal": []}
        mock_result.to_json.return_value = '{"url": "..."}'

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_scrape(url="https://example.com")

        assert result["success"] is True
        assert result["url"] == "https://example.com"
        assert "# Hello" in result["content"]
        assert result["format"] == "markdown"

    @pytest.mark.asyncio
    async def test_scrape_json_format(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.metadata = {}
        mock_result.links = {}
        mock_result.to_json.return_value = '{"url": "https://example.com"}'

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_scrape(url="https://example.com", output_format="json")

        assert result["success"] is True
        assert result["format"] == "json"

    @pytest.mark.asyncio
    async def test_scrape_no_metadata(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock(spec=["url", "markdown", "to_json"])
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.to_json.return_value = '{"url": "..."}'

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_scrape(
                url="https://example.com", include_metadata=False, include_links=False
            )

        assert result["success"] is True
        assert "metadata" not in result
        assert "links" not in result


# ─── _handle_crawl ──────────────────────────────────────────


class TestHandleCrawl:
    """Tests for _handle_crawl."""

    @pytest.mark.asyncio
    async def test_crawl_bfs(self):
        toolkit = AgentCrawlToolkit()
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page1"
        mock_page.markdown = "# Page 1"
        mock_page.to_json.return_value = '{"url": "..."}'
        mock_page.status_code = 200

        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(return_value=[mock_page])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_crawl(url="https://example.com")

        assert result["success"] is True
        assert result["pages_crawled"] == 1
        assert result["strategy"] == "bfs"
        assert len(result["pages"]) == 1

    @pytest.mark.asyncio
    async def test_crawl_dfs(self):
        toolkit = AgentCrawlToolkit()
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page1"
        mock_page.markdown = "# Page"
        mock_page.to_json.return_value = "{}"
        mock_page.status_code = 200

        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(return_value=[mock_page])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_crawl(url="https://example.com", strategy="dfs")

        assert result["strategy"] == "dfs"

    @pytest.mark.asyncio
    async def test_crawl_best_first(self):
        toolkit = AgentCrawlToolkit()
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page1"
        mock_page.markdown = "# Page"
        mock_page.to_json.return_value = "{}"
        mock_page.status_code = 200

        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(return_value=[mock_page])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_crawl(url="https://example.com", strategy="best_first")

        assert result["strategy"] == "best_first"

    @pytest.mark.asyncio
    async def test_crawl_with_patterns(self):
        toolkit = AgentCrawlToolkit()
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page1"
        mock_page.markdown = "# Page"
        mock_page.to_json.return_value = "{}"
        mock_page.status_code = 200

        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(return_value=[mock_page])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_crawl(
                url="https://example.com",
                include_patterns=["/docs/*"],
                exclude_patterns=["/admin/*"],
            )

        assert result["pages_crawled"] == 1


# ─── _handle_search ──────────────────────────────────────────


class TestHandleSearch:
    """Tests for _handle_search."""

    @pytest.mark.asyncio
    async def test_search_success(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.title = "Result 1"
        mock_result.url = "https://example.com"
        mock_result.snippet = "A snippet"
        mock_result.markdown = "# Content"

        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_search(query="test query")

        assert result["success"] is True
        assert result["query"] == "test query"
        assert result["results_count"] == 1
        assert result["results"][0]["title"] == "Result 1"

    @pytest.mark.asyncio
    async def test_search_no_scrape(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.title = "Result 1"
        mock_result.url = "https://example.com"
        mock_result.snippet = "A snippet"
        # No markdown attribute when scrape_results=False
        del mock_result.markdown  # will cause AttributeError when checking
        # Actually let's set it differently
        mock_result.markdown = None
        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_search(query="test", scrape_results=False)

        assert result["results_count"] == 1
        assert "content" not in result["results"][0]


# ─── _handle_map ───────────────────────────────────────────


class TestHandleMap:
    """Tests for _handle_map."""

    @pytest.mark.asyncio
    async def test_map_success(self):
        toolkit = AgentCrawlToolkit()
        mock_engine = MagicMock()
        mock_engine.map = AsyncMock(
            return_value=[
                "https://example.com/page1",
                "https://example.com/page2",
            ]
        )

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_map(url="https://example.com")

        assert result["success"] is True
        assert result["urls_found"] == 2
        assert len(result["urls"]) == 2

    @pytest.mark.asyncio
    async def test_map_max_urls_limit(self):
        toolkit = AgentCrawlToolkit()
        mock_engine = MagicMock()
        mock_engine.map = AsyncMock(
            return_value=[f"https://example.com/page{i}" for i in range(100)]
        )

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_map(url="https://example.com", max_urls=50)

        assert len(result["urls"]) == 50


# ─── _handle_extract ───────────────────────────────────────


class TestHandleExtract:
    """Tests for _handle_extract."""

    @pytest.mark.asyncio
    async def test_extract_css(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.extracted_data = {"key": "value"}

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_extract(
                url="https://example.com",
                extraction_schema_json='{"type": "object"}',
                method="css",
                css_schema={"baseSelector": "div", "fields": []},
            )

        assert result["success"] is True
        assert result["method"] == "css"
        assert result["extracted_data"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_extract_llm(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.extracted_data = {"name": "test"}

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_extract(
                url="https://example.com",
                extraction_schema_json='{"type": "object"}',
                method="llm",
            )

        assert result["success"] is True
        assert result["method"] == "llm"

    @pytest.mark.asyncio
    async def test_extract_xpath(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.extracted_data = {"key": "value"}

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_extract(
                url="https://example.com",
                extraction_schema_json='{"type": "object"}',
                method="xpath",
            )

        assert result["success"] is True
        assert result["method"] == "xpath"

    @pytest.mark.asyncio
    async def test_extract_invalid_json(self):
        toolkit = AgentCrawlToolkit()
        result = await toolkit._handle_extract(
            url="https://example.com",
            extraction_schema_json="{invalid json",
        )

        assert result["success"] is False
        assert "Invalid schema JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_extract_with_schema_json_fallback(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.extracted_data = {"name": "test"}

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_extract(
                url="https://example.com",
                schema_json='{"type": "object"}',
                method="llm",
            )

        assert result["success"] is True


# ─── _handle_screenshot ──────────────────────────────────────


class TestHandleScreenshot:
    """Tests for _handle_screenshot."""

    @pytest.mark.asyncio
    async def test_screenshot_success(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.screenshot = "base64_data"

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_screenshot(url="https://example.com")

        assert result["success"] is True
        assert result["url"] == "https://example.com"
        assert result["screenshot_base64"] == "base64_data"


# ─── _handle_batch_scrape ───────────────────────────────────


class TestHandleBatchScrape:
    """Tests for _handle_batch_scrape."""

    @pytest.mark.asyncio
    async def test_batch_scrape_string_urls(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.url = "https://a.com"
        mock_result.markdown = "# A"
        mock_result.success = True
        mock_result.to_json.return_value = "{}"

        mock_engine = MagicMock()
        mock_engine.batch_scrape = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_batch_scrape(urls="https://a.com,https://b.com")

        assert result["success"] is True
        assert result["total_urls"] == 2
        assert result["successful"] == 1
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_batch_scrape_list_urls(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.url = "https://a.com"
        mock_result.markdown = "# A"
        mock_result.success = True
        mock_result.to_json.return_value = "{}"

        mock_engine = MagicMock()
        mock_engine.batch_scrape = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_batch_scrape(urls=["https://a.com"])

        assert result["total_urls"] == 1

    @pytest.mark.asyncio
    async def test_batch_scrape_empty_urls(self):
        toolkit = AgentCrawlToolkit()
        result = await toolkit._handle_batch_scrape(urls="")

        assert result["success"] is False
        assert result["error"] == "No URLs provided."

    @pytest.mark.asyncio
    async def test_batch_scrape_failed_page(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock()
        mock_result.url = "https://a.com"
        mock_result.markdown = ""
        mock_result.success = False
        mock_result.to_json.return_value = "{}"

        mock_engine = MagicMock()
        mock_engine.batch_scrape = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_batch_scrape(urls="https://a.com")

        assert result["successful"] == 0
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_batch_scrape_no_success_attr(self):
        toolkit = AgentCrawlToolkit()
        mock_result = MagicMock(spec=["url", "markdown", "to_json"])
        mock_result.url = "https://a.com"
        mock_result.markdown = "# A"
        mock_result.to_json.return_value = "{}"

        mock_engine = MagicMock()
        mock_engine.batch_scrape = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await toolkit._handle_batch_scrape(urls="https://a.com")

        assert result["successful"] == 1


# ─── OpenAIFunctionHandler ───────────────────────────────────


class TestOpenAIFunctionHandler:
    """Tests for OpenAIFunctionHandler."""

    def test_init_defaults(self):
        handler = OpenAIFunctionHandler()
        assert handler._toolkit is not None

    def test_init_custom_toolkit(self):
        toolkit = AgentCrawlToolkit()
        handler = OpenAIFunctionHandler(toolkit=toolkit)
        assert handler._toolkit is toolkit

    def test_init_custom_max_content(self):
        handler = OpenAIFunctionHandler(max_content_length=1000)
        assert handler._toolkit._max_content_length == 1000

    def test_get_tools_schema(self):
        handler = OpenAIFunctionHandler()
        schema = handler.get_tools_schema()
        assert len(schema) == 7
        assert schema[0]["type"] == "function"

    def test_get_tools_schema_filtered(self):
        handler = OpenAIFunctionHandler()
        schema = handler.get_tools_schema(["web_scrape"])
        assert len(schema) == 1
        assert schema[0]["function"]["name"] == "web_scrape"

    @pytest.mark.asyncio
    async def test_handle_tool_call_with_json_string(self):
        handler = OpenAIFunctionHandler(toolkit=AgentCrawlToolkit(return_format="dict"))
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.metadata = {}
        mock_result.links = {}
        mock_result.to_json.return_value = '{"url": "..."}'

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await handler.handle_tool_call("web_scrape", '{"url": "https://example.com"}')

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_handle_tool_call_with_dict(self):
        handler = OpenAIFunctionHandler(toolkit=AgentCrawlToolkit(return_format="dict"))
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.metadata = {}
        mock_result.links = {}
        mock_result.to_json.return_value = '{"url": "..."}'

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await handler.handle_tool_call("web_scrape", {"url": "https://example.com"})

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_handle_tool_call_returns_str(self):
        handler = OpenAIFunctionHandler(toolkit=AgentCrawlToolkit(return_format="json"))
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.metadata = {}
        mock_result.links = {}
        mock_result.to_json.return_value = '{"url": "..."}'

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await handler.handle_tool_call("web_scrape", '{"url": "https://example.com"}')

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_handle_response_no_tool_calls(self):
        handler = OpenAIFunctionHandler()
        message = MagicMock()
        message.tool_calls = None
        result = await handler.handle_response(message)
        assert result == []

    @pytest.mark.asyncio
    async def test_handle_response_with_tool_calls(self):
        handler = OpenAIFunctionHandler()
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"
        mock_result.metadata = {}
        mock_result.links = {}
        mock_result.to_json.return_value = '{"url": "..."}'

        mock_engine = AsyncMock()
        mock_engine.scrape.return_value = mock_result

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "web_scrape"
        tool_call.function.arguments = '{"url": "https://example.com"}'

        message = MagicMock()
        message.tool_calls = [tool_call]

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            results = await handler.handle_response(message)

        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == "call_1"
        assert "content" in results[0]

    @pytest.mark.asyncio
    async def test_handle_tool_call_exception(self):
        handler = OpenAIFunctionHandler(toolkit=AgentCrawlToolkit(return_format="dict"))
        with (
            patch.object(handler._toolkit, "execute_json", side_effect=Exception("Tool error")),
            pytest.raises(Exception, match="Tool error"),
        ):
            await handler.handle_tool_call("web_scrape", '{"url": "https://example.com"}')


# ─── OpenAIFunctionHandler.run_agent_loop ────────────────────


class TestRunAgentLoop:
    """Tests for run_agent_loop method."""

    @pytest.mark.asyncio
    async def test_agent_loop_final_response(self):
        handler = OpenAIFunctionHandler()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Final answer"
        mock_response.choices[0].message.tool_calls = None
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(handler, "get_tools_schema", return_value=[]):
            result = await handler.run_agent_loop(mock_client, [{"role": "user", "content": "Hi"}])

        assert result == "Final answer"

    @pytest.mark.asyncio
    async def test_agent_loop_max_iterations(self):
        handler = OpenAIFunctionHandler()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.choices[0].message.tool_calls = [MagicMock()]  # Always tool calls
        mock_response.choices[0].message.tool_calls[0].id = "call_1"
        mock_response.choices[0].message.tool_calls[0].function.name = "web_scrape"
        mock_response.choices[0].message.tool_calls[
            0
        ].function.arguments = '{"url": "https://example.com"}'
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(
            handler,
            "handle_response",
            return_value=[{"role": "tool", "content": "{}", "tool_call_id": "call_1"}],
        ):
            result = await handler.run_agent_loop(
                mock_client, [{"role": "user", "content": "Hi"}], max_iterations=2
            )

        assert "maximum iterations" in result

    @pytest.mark.asyncio
    async def test_agent_loop_no_content(self):
        handler = OpenAIFunctionHandler()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.choices[0].message.tool_calls = None
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(handler, "get_tools_schema", return_value=[]):
            result = await handler.run_agent_loop(mock_client, [{"role": "user", "content": "Hi"}])

        assert result == ""

    @pytest.mark.asyncio
    async def test_close(self):
        handler = OpenAIFunctionHandler()
        mock_mgr = MagicMock()
        mock_mgr.shutdown = AsyncMock()
        with patch("agentcrawl.agent.tool._engine_manager", mock_mgr):
            await handler.close()
            mock_mgr.shutdown.assert_awaited_once()


# ─── LangChain / CrewAI Stubs ─────────────────────────────────


class TestOptionalImports:
    """Tests for optional langchain/crewai imports (stubs when not installed)."""

    def test_langchain_not_installed(self):
        # Since langchain is not installed in this environment
        import agentcrawl.agent.tool as tool_module

        assert tool_module.AgentCrawlTool is None

    def test_crewai_not_installed(self):
        import agentcrawl.agent.tool as tool_module

        assert tool_module.CrewAICrawlTool is None

    def test_get_langchain_tools_raises(self):
        from agentcrawl.agent.tool import get_langchain_tools as get_lc

        with pytest.raises(ImportError, match="LangChain"):
            get_lc()

    def test_get_crewai_tools_raises(self):
        from agentcrawl.agent.tool import get_crewai_tools as get_ca

        with pytest.raises(ImportError, match="CrewAI"):
            get_ca()


# ─── create_toolkit ──────────────────────────────────────────


class TestCreateToolkit:
    """Tests for create_toolkit factory function."""

    def test_create_langchain(self):
        with pytest.raises(ImportError):
            create_toolkit("langchain")

    def test_create_crewai(self):
        with pytest.raises(ImportError):
            create_toolkit("crewai")

    def test_create_openai(self):
        handler = create_toolkit("openai")
        assert isinstance(handler, OpenAIFunctionHandler)

    def test_create_generic(self):
        toolkit = create_toolkit("generic")
        assert isinstance(toolkit, AgentCrawlToolkit)

    def test_create_generic_with_kwargs(self):
        toolkit = create_toolkit("generic", max_content_length=1000)
        assert toolkit._max_content_length == 1000

    def test_create_invalid_framework(self):
        with pytest.raises(ValueError, match="Unknown framework"):
            create_toolkit("invalid")
