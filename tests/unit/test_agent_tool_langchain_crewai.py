"""Extended tests for agentcrawl.agent.tool with mocked langchain/crewai imports.

Since langchain and crewai are not installed in the test environment,
these tests inject mock modules into sys.modules via a module-scoped
fixture, allowing coverage of the try/except ImportError branches.

The fixture saves and restores sys.modules state so this module does
NOT pollute other test files (e.g. test_agent_tool.py::TestOptionalImports).
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Module-level placeholders — overwritten by the mock_langchain_crewai
# fixture before any test runs.  Declared here so linters (F821) see them
# as defined and so type-checkers don't complain.
AgentCrawlCrawlTool = None
AgentCrawlSearchTool = None
AgentCrawlTool = None
AgentCrawlToolkit = None
CrewAICrawlTool = None
CrewAISearchTool = None
create_toolkit = None
get_crewai_tools = None
get_langchain_tools = None


# ══════════════════════════════════════════════════════════════
# Mock helpers
# ══════════════════════════════════════════════════════════════


def _make_mock_base_tool():
    """Create a BaseTool-like class that accepts class-level annotations."""

    class BaseTool:
        """Mock BaseTool that mimics langchain/crewai BaseTool interface."""

        name: str = ""
        description: str = ""
        args_schema: object = None
        return_direct: bool = False

        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    return BaseTool


# ══════════════════════════════════════════════════════════════
# Test isolation fixture: save/restore sys.modules
# ══════════════════════════════════════════════════════════════

_SYMBOLS = [
    "AgentCrawlCrawlTool",
    "AgentCrawlSearchTool",
    "AgentCrawlTool",
    "AgentCrawlToolkit",
    "CrewAICrawlTool",
    "CrewAISearchTool",
    "create_toolkit",
    "get_crewai_tools",
    "get_langchain_tools",
]

_KEYS_TO_MOCK = [
    "langchain",
    "langchain.tools",
    "crewai",
    "crewai.tools",
]


@pytest.fixture(scope="module", autouse=True)
def mock_langchain_crewai():
    """Mock langchain and crewai modules for this test module only.

    Saves sys.modules state before and restores after to prevent
    pollution of other test files (e.g. test_agent_tool.py::TestOptionalImports).
    """
    # Save original state
    saved_modules: dict[str, object] = {}
    for key in _KEYS_TO_MOCK:
        if key in sys.modules:
            saved_modules[key] = sys.modules[key]

    # Create mock modules with real mock objects (not bare MagicMock,
    # because the source uses them as base classes)
    mock_base_tool = _make_mock_base_tool()

    mock_langchain_tools = MagicMock()
    mock_langchain_tools.BaseTool = mock_base_tool

    mock_langchain = MagicMock()
    mock_langchain.tools = mock_langchain_tools

    mock_crewai_tools = MagicMock()
    mock_crewai_tools.BaseTool = mock_base_tool

    mock_crewai = MagicMock()
    mock_crewai.tools = mock_crewai_tools

    # Inject mocks into sys.modules
    sys.modules["langchain"] = mock_langchain
    sys.modules["langchain.tools"] = mock_langchain_tools
    sys.modules["crewai"] = mock_crewai
    sys.modules["crewai.tools"] = mock_crewai_tools

    # Force fresh import of agentcrawl.agent.tool with mocked modules
    sys.modules.pop("agentcrawl.agent.tool", None)

    # Import the module under test and inject symbols into THIS module's
    # global namespace so test classes can reference them.
    import agentcrawl.agent.tool as _tool_module

    g = globals()
    for _name in _SYMBOLS:
        g[_name] = getattr(_tool_module, _name)

    yield

    # ── Cleanup ──────────────────────────────────────────────
    # Restore original sys.modules state
    for key in _KEYS_TO_MOCK:
        if key in saved_modules:
            sys.modules[key] = saved_modules[key]
        else:
            sys.modules.pop(key, None)

    # Force reimport of agentcrawl.agent.tool without mocks so that
    # subsequent test files see the real (un-mocked) module.
    sys.modules.pop("agentcrawl.agent.tool", None)

    # Remove injected names from globals
    for _name in _SYMBOLS:
        g.pop(_name, None)


# ══════════════════════════════════════════════════════════════
# LangChain Tool Tests
# ══════════════════════════════════════════════════════════════


class TestLangChainTool:
    """Tests for AgentCrawlTool (LangChain)."""

    def test_tool_attributes(self) -> None:
        tool = AgentCrawlTool()
        assert tool.name == "web_scraper"
        assert tool.return_direct is False
        assert tool.args_schema is not None

    def test_tool_with_custom_toolkit(self) -> None:
        toolkit = AgentCrawlToolkit(return_format="json")
        tool = AgentCrawlTool(toolkit=toolkit)
        assert tool._get_toolkit() is toolkit

    def test_tool_lazy_toolkit(self) -> None:
        tool = AgentCrawlTool()
        tk = tool._get_toolkit()
        assert tk._return_format == "text"

    @pytest.mark.asyncio
    async def test_arun_success(self) -> None:
        tool = AgentCrawlTool()
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
            result = await tool._arun("https://example.com")

        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_arun_error(self) -> None:
        tool = AgentCrawlTool()
        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(side_effect=Exception("Scrape failed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("https://example.com")

        assert "Scrape failed" in result

    @pytest.mark.asyncio
    async def test_arun_engine_error(self) -> None:
        """Test _arun when engine raises an exception."""
        tool = AgentCrawlTool()
        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(side_effect=RuntimeError("Engine crashed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("https://example.com")

        assert "Engine crashed" in result


class TestLangChainSearchTool:
    """Tests for AgentCrawlSearchTool (LangChain)."""

    def test_tool_attributes(self) -> None:
        tool = AgentCrawlSearchTool()
        assert tool.name == "web_search"

    def test_tool_with_custom_toolkit(self) -> None:
        toolkit = AgentCrawlToolkit(return_format="json")
        tool = AgentCrawlSearchTool(toolkit=toolkit)
        assert tool._get_toolkit() is toolkit

    def test_tool_lazy_toolkit(self) -> None:
        tool = AgentCrawlSearchTool()
        tk = tool._get_toolkit()
        assert tk._return_format == "text"

    @pytest.mark.asyncio
    async def test_arun_success(self) -> None:
        tool = AgentCrawlSearchTool()
        mock_result = MagicMock()
        mock_result.title = "Result 1"
        mock_result.url = "https://example.com"
        mock_result.snippet = "A snippet"
        mock_result.markdown = "# Content"

        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("test query")

        assert "Result 1" in result
        assert "https://example.com" in result

    @pytest.mark.asyncio
    async def test_arun_error(self) -> None:
        tool = AgentCrawlSearchTool()
        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(side_effect=Exception("Search failed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("test query")

        assert "Search failed" in result

    @pytest.mark.asyncio
    async def test_arun_no_results(self) -> None:
        """Test _arun when search returns empty results."""
        toolkit = AgentCrawlToolkit(return_format="dict")
        tool = AgentCrawlSearchTool(toolkit=toolkit)
        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("test query")

        assert "No results found" in result

    @pytest.mark.asyncio
    async def test_arun_result_no_content(self) -> None:
        """Test _arun when result has no content."""
        toolkit = AgentCrawlToolkit(return_format="dict")
        tool = AgentCrawlSearchTool(toolkit=toolkit)
        mock_result = MagicMock(spec=["title", "url", "snippet"])
        mock_result.title = "Result 1"
        mock_result.url = "https://example.com"
        mock_result.snippet = "A snippet"
        # No markdown attribute — hasattr(r, "markdown") will be False

        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("test query")

        assert "Result 1" in result
        assert "Content" not in result

    @pytest.mark.asyncio
    async def test_arun_engine_error(self) -> None:
        """Test _arun when engine raises an exception."""
        tool = AgentCrawlSearchTool()
        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(side_effect=RuntimeError("Engine crashed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("test query")

        assert "Engine crashed" in result


class TestLangChainCrawlTool:
    """Tests for AgentCrawlCrawlTool (LangChain)."""

    def test_tool_attributes(self) -> None:
        tool = AgentCrawlCrawlTool()
        assert tool.name == "web_crawler"

    def test_tool_with_custom_toolkit(self) -> None:
        toolkit = AgentCrawlToolkit(return_format="json")
        tool = AgentCrawlCrawlTool(toolkit=toolkit)
        assert tool._get_toolkit() is toolkit

    def test_tool_lazy_toolkit(self) -> None:
        tool = AgentCrawlCrawlTool()
        tk = tool._get_toolkit()
        assert tk._return_format == "text"

    @pytest.mark.asyncio
    async def test_arun_success(self) -> None:
        toolkit = AgentCrawlToolkit(return_format="dict")
        tool = AgentCrawlCrawlTool(toolkit=toolkit)
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page1"
        mock_page.markdown = "# Page 1 content here"
        mock_page.to_json.return_value = '{"url": "..."}'
        mock_page.status_code = 200

        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(return_value=[mock_page])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("https://example.com")

        assert "Crawled" in result
        assert "page1" in result

    @pytest.mark.asyncio
    async def test_arun_error(self) -> None:
        tool = AgentCrawlCrawlTool()
        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(side_effect=Exception("Crawl failed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("https://example.com")

        assert "Crawl failed" in result

    @pytest.mark.asyncio
    async def test_arun_many_pages(self) -> None:
        """Test _arun with many pages (limit to 20)."""
        toolkit = AgentCrawlToolkit(return_format="dict")
        tool = AgentCrawlCrawlTool(toolkit=toolkit)
        pages = []
        for i in range(25):
            page = MagicMock()
            page.url = f"https://example.com/page{i}"
            page.markdown = f"# Page {i}"
            page.to_json.return_value = "{}"
            page.status_code = 200
            pages.append(page)

        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(return_value=pages)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("https://example.com")

        assert "25 pages" in result

    @pytest.mark.asyncio
    async def test_arun_engine_error(self) -> None:
        """Test _arun when engine raises an exception."""
        tool = AgentCrawlCrawlTool()
        mock_engine = MagicMock()
        mock_engine.crawl = AsyncMock(side_effect=RuntimeError("Engine crashed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun("https://example.com")

        assert "Engine crashed" in result


class TestGetLangChainTools:
    """Tests for get_langchain_tools factory."""

    def test_get_langchain_tools_default(self) -> None:
        tools = get_langchain_tools()
        assert len(tools) == 3
        assert isinstance(tools[0], AgentCrawlTool)
        assert isinstance(tools[1], AgentCrawlSearchTool)
        assert isinstance(tools[2], AgentCrawlCrawlTool)

    def test_get_langchain_tools_custom_toolkit(self) -> None:
        toolkit = AgentCrawlToolkit()
        tools = get_langchain_tools(toolkit=toolkit)
        assert len(tools) == 3
        for t in tools:
            assert t._get_toolkit() is toolkit


# ══════════════════════════════════════════════════════════════
# CrewAI Tool Tests
# ══════════════════════════════════════════════════════════════


class TestCrewAICrawlTool:
    """Tests for CrewAICrawlTool (CrewAI)."""

    def test_tool_attributes(self) -> None:
        tool = CrewAICrawlTool()
        assert tool.name == "Web Scraper"

    def test_tool_with_custom_toolkit(self) -> None:
        toolkit = AgentCrawlToolkit(return_format="json")
        tool = CrewAICrawlTool(toolkit=toolkit)
        assert tool._get_toolkit() is toolkit

    def test_tool_lazy_toolkit(self) -> None:
        tool = CrewAICrawlTool()
        tk = tool._get_toolkit()
        assert tk._return_format == "text"

    @pytest.mark.asyncio
    async def test_arun_success(self) -> None:
        tool = CrewAICrawlTool()
        mock_result = MagicMock()
        mock_result.url = "https://example.com"
        mock_result.markdown = "# Hello"

        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(return_value=mock_result)

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(url="https://example.com")

        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_arun_error(self) -> None:
        tool = CrewAICrawlTool()
        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(side_effect=Exception("CrewAI scrape failed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(url="https://example.com")

        assert "CrewAI scrape failed" in result

    @pytest.mark.asyncio
    async def test_arun_engine_error(self) -> None:
        """Test _arun when engine raises an exception."""
        tool = CrewAICrawlTool()
        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock(side_effect=RuntimeError("Engine crashed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(url="https://example.com")

        assert "Engine crashed" in result


class TestCrewAISearchTool:
    """Tests for CrewAISearchTool (CrewAI)."""

    def test_tool_attributes(self) -> None:
        tool = CrewAISearchTool()
        assert tool.name == "Web Search"

    def test_tool_with_custom_toolkit(self) -> None:
        toolkit = AgentCrawlToolkit(return_format="json")
        tool = CrewAISearchTool(toolkit=toolkit)
        assert tool._get_toolkit() is toolkit

    def test_tool_lazy_toolkit(self) -> None:
        tool = CrewAISearchTool()
        tk = tool._get_toolkit()
        assert tk._return_format == "text"

    @pytest.mark.asyncio
    async def test_arun_success(self) -> None:
        toolkit = AgentCrawlToolkit(return_format="dict")
        tool = CrewAISearchTool(toolkit=toolkit)
        mock_result = MagicMock()
        mock_result.title = "Result 1"
        mock_result.url = "https://example.com"
        mock_result.snippet = "A snippet"
        mock_result.markdown = "Some content here"

        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(query="test query")

        assert "Result 1" in result
        assert "https://example.com" in result
        assert "Some content" in result

    @pytest.mark.asyncio
    async def test_arun_error(self) -> None:
        tool = CrewAISearchTool()
        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(side_effect=Exception("CrewAI search failed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(query="test query")

        assert "CrewAI search failed" in result

    @pytest.mark.asyncio
    async def test_arun_no_results(self) -> None:
        """Test _arun when search returns empty results."""
        toolkit = AgentCrawlToolkit(return_format="dict")
        tool = CrewAISearchTool(toolkit=toolkit)
        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(query="test query")

        assert "No results found" in result

    @pytest.mark.asyncio
    async def test_arun_result_no_content(self) -> None:
        """Test _arun when result has no content."""
        toolkit = AgentCrawlToolkit(return_format="dict")
        tool = CrewAISearchTool(toolkit=toolkit)
        mock_result = MagicMock(spec=["title", "url", "content"])
        mock_result.title = "Result 1"
        mock_result.url = "https://example.com"
        mock_result.content = None

        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(return_value=[mock_result])

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(query="test query")

        assert "Result 1" in result

    @pytest.mark.asyncio
    async def test_arun_engine_error(self) -> None:
        """Test _arun when engine raises an exception."""
        tool = CrewAISearchTool()
        mock_engine = MagicMock()
        mock_engine.search = AsyncMock(side_effect=RuntimeError("Engine crashed"))

        with patch("agentcrawl.agent.tool._engine_manager") as mock_mgr:
            mock_mgr.get_engine = AsyncMock(return_value=mock_engine)
            result = await tool._arun(query="test query")

        assert "Engine crashed" in result


class TestGetCrewAITools:
    """Tests for get_crewai_tools factory."""

    def test_get_crewai_tools_default(self) -> None:
        tools = get_crewai_tools()
        assert len(tools) == 2
        assert isinstance(tools[0], CrewAICrawlTool)
        assert isinstance(tools[1], CrewAISearchTool)

    def test_get_crewai_tools_custom_toolkit(self) -> None:
        toolkit = AgentCrawlToolkit()
        tools = get_crewai_tools(toolkit=toolkit)
        assert len(tools) == 2


# ══════════════════════════════════════════════════════════════
# create_toolkit with langchain/crewai
# ══════════════════════════════════════════════════════════════


class TestCreateToolkitWithMockedImports:
    """Tests for create_toolkit that now work with mocked langchain/crewai."""

    def test_create_langchain(self) -> None:
        tools = create_toolkit("langchain")
        assert len(tools) == 3
        assert isinstance(tools[0], AgentCrawlTool)

    def test_create_crewai(self) -> None:
        tools = create_toolkit("crewai")
        assert len(tools) == 2
        assert isinstance(tools[0], CrewAICrawlTool)
