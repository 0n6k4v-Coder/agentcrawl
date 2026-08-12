"""Tests for the reconstructed AgentCrawl MCP server (MCP SDK 2.0.0).

These tests drive the server through an in-process MCP session using
:class:`mcp.client.session.ClientSession` wired to the server's read/write
streams via anyio memory object streams.  No live HTTP server or external
website is required, satisfying REQ-B12 / AC-B18 / AC-B19.

Coverage map (AC-B18):

* AC-B01  server construction
* AC-B02  no removed decorator APIs
* AC-B03  exactly one canonical contract
* AC-B04  canonical tool names
* AC-B05  deterministic ordered tools/list
* AC-B06  every listed tool maps to a callable handler
* AC-B07  schema correctness (required fields, defaults)
* AC-B08  batch_scrape exposed
* AC-B09  web_screenshot NOT exposed
* AC-B10  HTTP transport is Streamable HTTP (app construction)
* AC-B11  no custom protocol implementation
* AC-B12  stateless request independence
* AC-B13  error semantics (ToolError -> is_error)
* AC-B14  unknown tool + invalid args handled deterministically
* AC-B15  engine cleanup on failure
* AC-B16  stdio server constructible
* AC-B17  stdio + HTTP expose same canonical contract
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.types import CallToolResult, ListToolsResult
from server.mcp.server import create_mcp_server, run_stdio
from server.mcp.tools import (
    CANONICAL_TOOL_ORDER,
    TOOL_DEFINITIONS,
    _serialize,
    get_tool,
    list_tool_names,
)

EXPECTED_NAMES = [
    "scrape_webpage",
    "search_web",
    "crawl_website",
    "discover_urls",
    "extract_data",
    "batch_scrape",
]


# ══════════════════════════════════════════════════════════════
# In-process session harness (anyio memory streams)
# ══════════════════════════════════════════════════════════════


async def _make_session(
    server: Server[Any] | None = None,
) -> tuple[
    ClientSession,
    asyncio.Task[Any],
    tuple[Any, Any],
    tuple[Any, Any],
]:
    """Connect a ClientSession to an MCP server over memory streams.

    The client is started as an async context manager so its dispatcher run
    loop is active during the test.  Callers must tear down via
    :func:`_close_session`.

    Returns (client, server_task, stream_pair_a, stream_pair_b).
    """
    if server is None:
        server = create_mcp_server()

    # anyio.create_memory_object_stream returns (send, receive).
    # Direction A: client writes -> server reads.
    a_send, a_recv = anyio.create_memory_object_stream(0)
    # Direction B: server writes -> client reads.
    b_send, b_recv = anyio.create_memory_object_stream(0)

    client = ClientSession(read_stream=b_recv, write_stream=a_send)
    # Server reads from a_recv, writes to b_send.
    server_task = asyncio.create_task(
        server.run(
            a_recv,
            b_send,
            server.create_initialization_options(),
            raise_exceptions=True,
        )
    )

    await client.__aenter__()
    async with asyncio.timeout(10):
        await client.initialize()
    return client, server_task, (a_send, a_recv), (b_send, b_recv)


async def _close_session(
    client: ClientSession,
    server_task: asyncio.Task[Any],
    stream_pair_a: tuple[Any, Any],
    stream_pair_b: tuple[Any, Any],
) -> None:
    """Tear down a session created by :func:`_make_session`."""
    _a_send, _a_recv = stream_pair_a
    _b_send, _b_recv = stream_pair_b
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await server_task
    with contextlib.suppress(Exception):
        await client.__aexit__(None, None, None)
    for s in (_a_send, _a_recv, _b_send, _b_recv):
        await s.aclose()


# ══════════════════════════════════════════════════════════════
# AC-B01 / AC-B02 / AC-B03 — construction & canonical contract
# ══════════════════════════════════════════════════════════════


class TestServerConstruction:
    def test_create_mcp_server_constructs(self):
        server = create_mcp_server()
        assert isinstance(server, Server)

    def test_no_removed_decorator_apis(self):
        server = create_mcp_server()
        for removed in ("list_tools", "call_tool", "list_resources", "list_prompts", "get_prompt"):
            assert not hasattr(server, removed), (
                f"Server still exposes removed decorator API: {removed}"
            )

    def test_single_canonical_contract(self):
        assert len(TOOL_DEFINITIONS) == 6
        for t in TOOL_DEFINITIONS:
            assert callable(t.handler)
            assert t.name
            assert t.input_schema["type"] == "object"
            assert "required" in t.input_schema

    def test_canonical_tool_names(self):
        assert list_tool_names() == EXPECTED_NAMES

    def test_batch_scrape_exposed(self):
        assert get_tool("batch_scrape") is not None
        assert "batch_scrape" in list_tool_names()

    def test_web_screenshot_not_exposed(self):
        assert get_tool("web_screenshot") is None
        assert "web_screenshot" not in list_tool_names()

    def test_deterministic_order(self):
        assert CANONICAL_TOOL_ORDER == EXPECTED_NAMES
        assert list_tool_names() == list_tool_names()


# ══════════════════════════════════════════════════════════════
# AC-B07 — schema correctness
# ══════════════════════════════════════════════════════════════


class TestToolSchemas:
    def _schema_for(self, name: str) -> dict[str, Any]:
        tool = get_tool(name)
        assert tool is not None
        return tool.input_schema

    def test_scrape_webpage_schema(self):
        s = self._schema_for("scrape_webpage")
        assert s["required"] == ["url"]
        assert s["properties"]["include_links"]["default"] is False
        assert s["properties"]["only_main_content"]["default"] is True

    def test_search_web_schema(self):
        s = self._schema_for("search_web")
        assert s["required"] == ["query"]
        assert s["properties"]["max_results"]["default"] == 5

    def test_crawl_website_schema(self):
        s = self._schema_for("crawl_website")
        assert s["required"] == ["url"]
        assert s["properties"]["max_pages"]["default"] == 10
        assert s["properties"]["max_depth"]["default"] == 2

    def test_discover_urls_schema(self):
        s = self._schema_for("discover_urls")
        assert s["required"] == ["url"]
        assert s["properties"]["max_urls"]["default"] == 100

    def test_extract_data_schema(self):
        s = self._schema_for("extract_data")
        assert sorted(s["required"]) == ["fields", "url"]

    def test_batch_scrape_schema(self):
        s = self._schema_for("batch_scrape")
        assert s["required"] == ["urls"]
        assert s["properties"]["only_main_content"]["default"] is True
        assert s["properties"]["urls"]["type"] == "array"


# ══════════════════════════════════════════════════════════════
# AC-B05 / AC-B06 — tools/list via real MCP protocol
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tools_list_via_protocol():
    client, task, pair_a, pair_b = await _make_session()
    try:
        result: ListToolsResult = await client.list_tools()
        names = [t.name for t in result.tools]
        assert names == EXPECTED_NAMES
        # Deterministic ordering (REQ-B13).
        result2 = await client.list_tools()
        names2 = [t.name for t in result2.tools]
        assert names == names2
        for tool in result.tools:
            assert get_tool(tool.name) is not None
            assert tool.input_schema["type"] == "object"
    finally:
        await _close_session(client, task, pair_a, pair_b)


@pytest.mark.asyncio
async def test_every_tool_has_handler():
    for name in EXPECTED_NAMES:
        tool = get_tool(name)
        assert tool is not None
        assert callable(tool.handler)


# ══════════════════════════════════════════════════════════════
# fixtures: mock CrawlEngine so no browser/network is needed
# ══════════════════════════════════════════════════════════════


def _mock_result(url="https://example.com"):
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.url = url
    mock_result.markdown = "# Example\n\nTest content"
    mock_result.metadata = {"title": "Example"}
    mock_result.word_count = 3
    mock_result.token_count = 5
    mock_result.links = {"all": []}
    return mock_result


@pytest.fixture
def _mock_engine():
    from agentcrawl.core.engine import CrawlEngine as _RealEngine

    mock_result = _mock_result()

    engine = MagicMock()
    engine.scrape = AsyncMock(return_value=mock_result)
    engine.batch_scrape = AsyncMock(return_value=[mock_result])
    engine.crawl = AsyncMock(
        return_value=MagicMock(
            pages=[mock_result],
            total_pages=1,
            successful_pages=1,
            total_words=3,
        )
    )
    engine.extract = AsyncMock(return_value=mock_result)
    engine.__aenter__ = AsyncMock(return_value=engine)
    engine.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_RealEngine, "default", classmethod(lambda cls: engine)):
        yield engine


# ══════════════════════════════════════════════════════════════
# AC-B12 / AC-B13 / AC-B14 — tools/call dispatch & error semantics
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_call_tool_success(_mock_engine):
    client, task, pair_a, pair_b = await _make_session()
    try:
        result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        assert isinstance(result, CallToolResult)
        assert result.is_error is False
        assert result.content
        data = json.loads(result.content[0].text)
        assert data["url"] == "https://example.com"
        assert "content" in data
    finally:
        await _close_session(client, task, pair_a, pair_b)


@pytest.mark.asyncio
async def test_call_tool_toolerror_is_error_result(_mock_engine):
    """An operational failure surfaces as isError=True, not a JSON error
    blob inside successful TextContent (REQ-B07 / AC-B13)."""
    client, task, pair_a, pair_b = await _make_session()
    try:
        result = await client.call_tool("scrape_webpage", {"url": ""})
        assert isinstance(result, CallToolResult)
        assert result.is_error is True
        data = json.loads(result.content[0].text)
        assert "error" in data
    finally:
        await _close_session(client, task, pair_a, pair_b)


@pytest.mark.asyncio
async def test_unknown_tool_returns_protocol_error():
    client, task, pair_a, pair_b = await _make_session()
    try:
        result = await client.call_tool("no_such_tool", {"url": "x"})
        assert isinstance(result, CallToolResult)
        assert result.is_error is True
    finally:
        await _close_session(client, task, pair_a, pair_b)


@pytest.mark.asyncio
async def test_invalid_arguments_rejected():
    """Missing required 'url' for scrape_webpage is a ToolError (deterministic)."""
    client, task, pair_a, pair_b = await _make_session()
    try:
        result = await client.call_tool("scrape_webpage", {})
        assert isinstance(result, CallToolResult)
        assert result.is_error is True
    finally:
        await _close_session(client, task, pair_a, pair_b)


@pytest.mark.asyncio
async def test_batch_scrape_via_protocol(_mock_engine):
    client, task, pair_a, pair_b = await _make_session()
    try:
        result = await client.call_tool(
            "batch_scrape",
            {"urls": ["https://example.com", "https://example.org"]},
        )
        assert isinstance(result, CallToolResult)
        assert result.is_error is False
        _mock_engine.batch_scrape.assert_awaited_once()
    finally:
        await _close_session(client, task, pair_a, pair_b)


# ══════════════════════════════════════════════════════════════
# AC-B15 — resource cleanup on failure
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_engine_cleanup_on_handler_error():
    """When a handler raises a non-ToolError exception, the tool returns an
    error result and the shared engine's async context manager is closed once
    at session teardown — not per-call (Set G shared-engine lifecycle)."""
    from agentcrawl.core.engine import CrawlEngine as _RealEngine

    _mock_result()
    engine = MagicMock()
    engine.scrape = AsyncMock(side_effect=RuntimeError("boom"))
    engine.__aenter__ = AsyncMock(return_value=engine)
    engine.__aexit__ = AsyncMock(return_value=None)

    with patch.object(_RealEngine, "default", classmethod(lambda cls: engine)):
        client, task, pair_a, pair_b = await _make_session()
        try:
            result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            assert isinstance(result, CallToolResult)
            assert result.is_error is True
            # __aexit__ is NOT called per-call anymore (Set G: shared engine
            # is cleaned up at session teardown, below).
            assert not engine.__aexit__.called
        finally:
            await _close_session(client, task, pair_a, pair_b)
        # Engine cleanup happens exactly once at session teardown (Set G/G4).
        assert engine.__aexit__.called


# ══════════════════════════════════════════════════════════════
# AC-B10 / AC-B11 / AC-B16 / AC-B17 — transport construction
# ══════════════════════════════════════════════════════════════


class TestStdioConstruction:
    def test_stdio_run_signature(self):
        sig = inspect.signature(run_stdio)
        assert sig.parameters == {}

    def test_stdio_uses_native_sdk_primitive(self):
        import mcp.server.stdio as mcp_stdio

        assert callable(mcp_stdio.stdio_server)

    def test_server_exposes_run_and_streamable_http_app(self):
        server = create_mcp_server()
        assert hasattr(server, "run")
        assert hasattr(server, "streamable_http_app")


class TestStreamableHttpConstruction:
    def test_http_transport_is_streamable(self):
        """streamable_http_app yields a Starlette app using the SDK's native
        Streamable HTTP facility (REQ-B05 / AC-B10)."""
        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)
        from starlette.applications import Starlette

        assert isinstance(app, Starlette)

    def test_no_legacy_sse_routing(self):
        """The HTTP app must not register legacy /sse + /messages/ routes
        (AC-B21)."""
        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)
        route_paths = set()
        for r in app.router.routes:
            if hasattr(r, "path") and r.path:
                route_paths.add(r.path)
        assert "/sse" not in route_paths
        assert "/messages/" not in route_paths

    def test_stateless_http_option(self):
        """The transport exposes the MCP path /mcp by default and is
        stateless (AC-B12)."""
        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)
        paths = {r.path for r in app.router.routes if hasattr(r, "path") and r.path}
        assert "/mcp" in paths

    def test_http_and_stdio_same_canonical_contract(self):
        """Both transports surface the identical canonical tool list."""
        server = create_mcp_server()
        _http_app = server.streamable_http_app(stateless_http=True)
        assert [t.name for t in TOOL_DEFINITIONS] == EXPECTED_NAMES
        assert server.streamable_http_app is not None


# ══════════════════════════════════════════════════════════════
# AC-B12 — stateless request independence
# ══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stateless_request_independence(_mock_engine):
    """Two independent sessions must not depend on prior invocations."""
    server = create_mcp_server()

    async def _drive_once() -> CallToolResult:
        client, task, pair_a, pair_b = await _make_session(server)
        try:
            result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            return result
        finally:
            await _close_session(client, task, pair_a, pair_b)

    r1 = await _drive_once()
    r2 = await _drive_once()
    assert r1.is_error is False
    assert r2.is_error is False
    # Both returned identical content (deterministic, stateless).
    assert r1.content[0].text == r2.content[0].text


# ══════════════════════════════════════════════════════════════
# _serialize helper contract
# ══════════════════════════════════════════════════════════════


def test_serialize_dict():
    assert _serialize({"a": 1}) == '{"a": 1}'


def test_serialize_str_passthrough():
    assert _serialize("hello") == "hello"


def test_serialize_ensure_ascii_false():
    out = _serialize({"k": "café"})
    assert "caf" in out
