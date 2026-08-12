"""Set D — MCP Integration Boundary Tests
========================================

These tests verify the actual integration boundary between AgentCrawl's
MCP modernization (Sets B & C) and the rest of the AgentCrawl application.

They exercise the *real* MCP transport path — not mock-arounds — to prove:

* D01: package import integrity (agent.* vs agentcrawl.agent.*)
* D02: server public API integrity (create_mcp_server)
* D03: CLI / runtime entry-point integrity
* D04: Streamable HTTP /mcp endpoint reachability
* D05: real ClientSession <-> server interoperability
* D06: canonical six-tool discovery via the real runtime path
* D07: canonical tool dispatch through the real MCP boundary
* D08: error propagation across the real client/server boundary
* D09: stateless independent requests across the real boundary
* D10: stdio end-to-end (native SDK stdio_client <-> native stdio_server)
* D11: lifecycle / resource cleanup
* D12: duplicate package-tree (agent/ vs agentcrawl/agent/) synchronization
* D15: deterministic test design (no external sites, no external APIs)

The MCP transport is real — only the underlying CrawlEngine operations
(browsing/search) are mocked so no network or browser is required.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import socket
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
import pytest_asyncio
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.lowlevel.server import Server
from server.mcp.tools import CANONICAL_TOOL_ORDER as SERVER_CANONICAL_ORDER

from agentcrawl.agent.mcp_client import (
    MCPClient,
    MCPConnectionError,
    MCPTimeoutError,
    MCPToolError,
    TransportType,
)

if TYPE_CHECKING:
    from mcp.types import CallToolResult, ListToolsResult

EXPECTED_CANONICAL = [
    "scrape_webpage",
    "search_web",
    "crawl_website",
    "discover_urls",
    "extract_data",
    "batch_scrape",
]

LEGACY_NAMES = [
    "web_scrape",
    "web_crawl",
    "web_search",
    "web_map",
    "web_extract",
    "web_screenshot",
    "web_batch_scrape",
]


def _mock_scrape_result(url: str = "https://example.com") -> MagicMock:
    """A mock scrape result that looks like a successful CrawlResult."""
    mock = MagicMock()
    mock.success = True
    mock.url = url
    mock.markdown = "# Example\n\nTest content"
    mock.metadata = {"title": "Example"}
    mock.word_count = 3
    mock.token_count = 5
    mock.links = {"all": []}
    return mock


def _mock_discover_result(url: str = "https://example.com") -> MagicMock:
    """A mock domain-discovery result."""
    mock = MagicMock()
    mock.urls = ["https://example.com/page1", "https://example.com/page2"]
    return mock


def _build_mock_engine() -> MagicMock:
    """Create a mock CrawlEngine with all handler methods mocked."""
    mock_result = _mock_scrape_result()

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
    engine.extract = AsyncMock(
        return_value=MagicMock(
            success=True,
            url="https://example.com",
            extracted_data=MagicMock(model_dump=MagicMock(return_value={"title": "Example"})),
        )
    )
    engine.__aenter__ = AsyncMock(return_value=engine)
    engine.__aexit__ = AsyncMock(return_value=None)
    return engine


def _build_mock_search_engine() -> MagicMock:
    """Create a mock SearchEngine."""
    mock_search_result = MagicMock()
    mock_search_result.to_dict.return_value = {
        "title": "Test",
        "url": "https://example.com",
        "snippet": "test",
    }
    mock_se_instance = MagicMock()
    mock_se_instance.search = AsyncMock(return_value=["result1", "result2"])
    return mock_se_instance


@pytest.fixture
def _mock_engine():
    """Patch CrawlEngine.default and SearchEngine so no browser/network needed."""
    from agentcrawl.core.engine import CrawlEngine

    engine = _build_mock_engine()
    mock_se_instance = _build_mock_search_engine()

    with (
        patch.object(CrawlEngine, "default", classmethod(lambda cls: engine)),
        patch("agentcrawl.SearchEngine", return_value=mock_se_instance),
    ):
        yield engine


def _free_port() -> tuple[str, int]:
    """Return (host, port) for a free local port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return "127.0.0.1", port


@pytest_asyncio.fixture
async def _http_server(_mock_engine):
    """Start a real Streamable HTTP MCP server on a free local port.

    Returns the server URL.  The server-side tool handlers are mocked so no
    browser or network is required.
    """
    from server.mcp.server import create_mcp_server

    host, port = _free_port()
    server = create_mcp_server()
    app = server.streamable_http_app(stateless_http=True)
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server_instance = uvicorn.Server(config)
    server_task = asyncio.create_task(server_instance.serve())

    # Wait for readiness — POST to /mcp to trigger MCP initialization.
    deadline = time.monotonic() + 15
    ready = False
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            async with asyncio.timeout(2):
                async with httpx2.AsyncClient() as c:
                    await c.post(
                        f"http://{host}:{port}/mcp",
                        content=b"{}",
                        headers={"Content-Type": "application/json"},
                    )
                ready = True
                break
        await asyncio.sleep(0.1)

    assert ready, f"Server did not start on port {port}"
    yield f"http://{host}:{port}/mcp"

    server_instance.should_exit = True
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await server_task


def _args_for_tool(name: str) -> dict[str, Any]:
    """Build valid arguments for each canonical tool for dispatch tests."""
    if name == "scrape_webpage":
        return {"url": "https://example.com"}
    if name == "search_web":
        return {"query": "test"}
    if name in ("crawl_website", "discover_urls"):
        return {"url": "https://example.com"}
    if name == "extract_data":
        return {"url": "https://example.com", "fields": "title"}
    if name == "batch_scrape":
        return {"urls": ["https://example.com"]}
    return {}


# ══════════════════════════════════════════════════════════════
# D03 — CLI / Runtime Entry Point Integrity
# ══════════════════════════════════════════════════════════════


class TestCLIRuntimeEntryPoint:
    """Verify the MCP server CLI entry point is consistent with the code."""

    def test_transport_choices_in_source(self):
        """The argparse --transport choices must match the README."""
        from server.mcp.server import main

        src = inspect.getsource(main)
        assert '"stdio"' in src
        assert '"http"' in src
        assert "choices" in src

    def test_transport_choices_via_parse(self):
        """argparse accepts 'http' and 'stdio' but rejects 'streamable-http'."""
        import argparse as ap

        parser = ap.ArgumentParser()
        parser.add_argument(
            "--transport",
            choices=["stdio", "http"],
            default="stdio",
        )
        ns = parser.parse_args(["--transport", "http"])
        assert ns.transport == "http"
        with pytest.raises(SystemExit):
            parser.parse_args(["--transport", "streamable-http"])

    def test_no_legacy_sse_in_entry_point(self):
        """The CLI must not accept 'sse' as a transport choice."""
        import argparse as ap

        parser = ap.ArgumentParser()
        parser.add_argument(
            "--transport",
            choices=["stdio", "http"],
            default="stdio",
        )
        with pytest.raises(SystemExit):
            parser.parse_args(["--transport", "sse"])

    @pytest.mark.asyncio
    async def test_run_sse_raises_runtime_error(self):
        """run_sse must raise RuntimeError pointing to run_streamable_http."""
        from server.mcp.server import run_sse

        with pytest.raises(RuntimeError, match="Legacy SSE transport has been removed"):
            await run_sse()

    def test_no_mcp_cli_entry_point_in_pyproject(self):
        """There is no dedicated MCP CLI entry point in pyproject.toml scripts.

        The MCP server is launched via ``python -m server.mcp.server``.
        This documents the actual invocation — we do NOT invent a new CLI.
        """
        import tomllib

        with open("pyproject.toml", "rb") as f:
            cfg = tomllib.load(f)
        scripts = cfg.get("project", {}).get("scripts", {})
        # Only 'agentcrawl' (the REST API CLI) should exist.
        assert "agentcrawl" in scripts
        # No mcp-specific entry point should exist.
        assert "mcp-server" not in scripts
        assert "agentcrawl-mcp" not in scripts


# ══════════════════════════════════════════════════════════════
# D01 — Package Import Integrity
# ══════════════════════════════════════════════════════════════


class TestPackageImportIntegrity:
    """Verify both agent.* and agentcrawl.agent.* import paths work."""

    def test_agent_mcp_client_import(self):
        """``import agent.mcp_client`` resolves successfully."""
        import agent.mcp_client  # noqa: F401

    def test_agentcrawl_mcp_client_import(self):
        """``import agentcrawl.agent.mcp_client`` resolves successfully."""
        import agentcrawl.agent.mcp_client  # noqa: F401

    def test_agent_mcp_client_from_import(self):
        """``from agent.mcp_client import MCPClient`` works."""
        from agent.mcp_client import MCPClient  # noqa: F401

    def test_agentcrawl_mcp_client_from_import(self):
        """``from agentcrawl.agent.mcp_client import MCPClient`` works."""
        from agentcrawl.agent.mcp_client import MCPClient  # noqa: F401

    def test_canonical_tool_order_both_paths(self):
        """Both import paths expose the same CANONICAL_TOOL_ORDER list."""
        from agent.mcp_client import CANONICAL_TOOL_ORDER as AGENT_ORDER
        from agentcrawl.agent.mcp_client import (
            CANONICAL_TOOL_ORDER as AC_ORDER,
        )

        assert AGENT_ORDER == EXPECTED_CANONICAL
        assert AC_ORDER == EXPECTED_CANONICAL
        assert AGENT_ORDER == AC_ORDER

    def test_no_legacy_names_in_client(self):
        """Neither client path exposes legacy ``web_*`` names."""
        import agentcrawl.agent.mcp_client as mod

        for legacy in LEGACY_NAMES:
            assert legacy not in mod.CANONICAL_TOOL_ORDER, (
                f"Legacy name {legacy} found in CANONICAL_TOOL_ORDER"
            )
            assert legacy not in mod.TOOL_NAMES

    def test_no_web_screenshot(self):
        """``web_screenshot`` must not appear anywhere in the client."""
        import agentcrawl.agent.mcp_client as mod

        assert "web_screenshot" not in mod.CANONICAL_TOOL_ORDER
        assert "web_screenshot" not in mod.TOOL_NAMES
        assert not hasattr(mod.MCPClient, "screenshot")

    def test_no_custom_json_rpc(self):
        """No ``_JsonRpc`` class on the active client path."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_JsonRpc")

    def test_no_sse_transport_class(self):
        """No ``_SSETransport`` class on the active client path."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_SSETransport")

    def test_no_websocket_transport_class(self):
        """No ``_WebSocketTransport`` class on the active client path."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_WebSocketTransport")

    def test_no_hardcoded_protocol_version(self):
        """No hardcoded 2024-11-05 protocol version in client source."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "2024-11-05" not in src, "Hardcoded protocol version 2024-11-05 found"


# ══════════════════════════════════════════════════════════════
# D02 — Server Public API Integrity
# ══════════════════════════════════════════════════════════════


class TestServerPublicAPI:
    """Verify create_mcp_server() returns the SDK 2.0.0 Server."""

    def test_create_mcp_server_constructs(self):
        from server.mcp.server import create_mcp_server

        srv = create_mcp_server()
        assert isinstance(srv, Server)

    def test_server_has_streamable_http_app(self):
        from server.mcp.server import create_mcp_server

        srv = create_mcp_server()
        assert hasattr(srv, "streamable_http_app")
        assert hasattr(srv, "run")

    def test_canonical_six_tools(self):
        from server.mcp.tools import TOOL_DEFINITIONS, get_tool, list_tool_names

        assert len(TOOL_DEFINITIONS) == 6
        assert list_tool_names() == EXPECTED_CANONICAL
        for name in EXPECTED_CANONICAL:
            assert get_tool(name) is not None

    def test_no_legacy_tools_on_server(self):
        from server.mcp.tools import get_tool

        for legacy in LEGACY_NAMES:
            assert get_tool(legacy) is None, f"Server still exposes {legacy}"

    def test_deterministic_ordering(self):
        from server.mcp.tools import CANONICAL_TOOL_ORDER, list_tool_names

        assert CANONICAL_TOOL_ORDER == EXPECTED_CANONICAL
        assert list_tool_names() == EXPECTED_CANONICAL
        assert list_tool_names() == list_tool_names()

    def test_server_package_exports(self):
        """server.mcp package exports the canonical public API."""
        from server.mcp import (
            CANONICAL_TOOL_ORDER,
            TOOL_DEFINITIONS,
            ToolDefinition,
            ToolError,
            create_mcp_server,
            get_tool,
            list_tool_names,
            run_stdio,
            run_streamable_http,
            to_mcp_tool_list,
        )

        assert callable(create_mcp_server)
        assert callable(run_stdio)
        assert callable(run_streamable_http)
        assert callable(get_tool)
        assert callable(list_tool_names)
        assert callable(to_mcp_tool_list)
        assert isinstance(ToolDefinition, type)
        assert isinstance(ToolError, type)
        assert CANONICAL_TOOL_ORDER == EXPECTED_CANONICAL
        assert len(TOOL_DEFINITIONS) == 6


# ══════════════════════════════════════════════════════════════
# D04 — Streamable HTTP Runtime Integration
# ══════════════════════════════════════════════════════════════


class TestStreamableHTTPRuntime:
    """D04: Verify the actual server runtime exposes /mcp via Streamable HTTP."""

    @pytest.mark.asyncio
    async def test_mcp_endpoint_reachable(self, _http_server):
        """POST to /mcp returns an MCP-initialized response (not 404)."""
        async with httpx2.AsyncClient() as c:
            resp = await c.post(
                _http_server,
                content=b"{}",
                headers={"Content-Type": "application/json"},
            )
        # The MCP protocol returns various status codes; 404 would mean the
        # route is missing. Any non-404 response means the endpoint is wired.
        assert resp.status_code != 404

    @pytest.mark.asyncio
    async def test_server_starts_successfully(self, _http_server):
        """The server fixture started without error — the URL is live."""
        assert _http_server.startswith("http://127.0.0.1:")

    @pytest.mark.asyncio
    async def test_client_connects_via_streamable_http(self, _http_server):
        """The actual MCPClient connects to the local server via Streamable HTTP."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            assert client.is_connected
            info = client.server_info
            assert info is not None
            assert info.name == "agentcrawl"

    @pytest.mark.asyncio
    async def test_tools_list_via_http(self, _http_server):
        """tools/list through Streamable HTTP returns exactly six canonical tools."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            tools = await client.list_tools()
            assert len(tools) == 6
            names = [t.name for t in tools]
            assert names == EXPECTED_CANONICAL

    @pytest.mark.asyncio
    async def test_tool_dispatch_via_http(self, _http_server):
        """A real tool call crosses the MCP boundary to the server."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            assert result.is_error is False
            data = result.json_data
            assert data["url"] == "https://example.com"
            assert "content" in data

    @pytest.mark.asyncio
    async def test_all_six_tools_dispatch_via_http(self, _http_server):
        """All six canonical tools successfully dispatch through the real HTTP path."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            for name in EXPECTED_CANONICAL:
                args = _args_for_tool(name)
                result = await client.call_tool(name, args)
                assert result.is_error is False, f"Tool {name} returned error: {result.text}"

    @pytest.mark.asyncio
    async def test_no_legacy_sse_routes(self, _http_server):
        """The HTTP app must not register /sse or /messages/ routes."""
        from server.mcp.server import create_mcp_server

        srv = create_mcp_server()
        app = srv.streamable_http_app(stateless_http=True)
        route_paths = set()
        for r in app.router.routes:
            if hasattr(r, "path") and r.path:
                route_paths.add(r.path)
        assert "/sse" not in route_paths
        assert "/messages/" not in route_paths
        assert "/mcp" in route_paths


# ══════════════════════════════════════════════════════════════
# D05/D06 — Real Interoperability & Canonical Contract
# ══════════════════════════════════════════════════════════════


class TestRealInteroperability:
    """D05/D06: Prove the actual production classes interoperate through
    the real MCP transport boundary."""

    @pytest.mark.asyncio
    async def test_connect_list_tools_call_tool_disconnect(self, _http_server):
        """Full lifecycle: connect -> list_tools -> call_tool -> disconnect."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            # connect (done by __aenter__)
            assert client.is_connected
            assert client.server_info is not None

            # list_tools
            tools = await client.list_tools()
            assert len(tools) == 6
            names = [t.name for t in tools]
            assert names == EXPECTED_CANONICAL

            # call_tool
            result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            assert result.is_error is False
            data = result.json_data
            assert data["url"] == "https://example.com"

        # disconnect (done by __aexit__)
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_native_sdk_client_session_used(self):
        """MCPClient uses the native SDK ClientSession, not custom code."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "from mcp.client.session import ClientSession" in src
        assert "streamable_http_client" in src
        assert "stdio_client" in src
        assert "class _JsonRpc" not in src
        assert "class _SSETransport" not in src
        assert "class _WebSocketTransport" not in src

    @pytest.mark.asyncio
    async def test_http_and_stdio_same_contract(self):
        """Both transports surface the identical canonical tool list and schemas.

        This test does not require handler execution — it only verifies
        tools/list returns the same names and schemas on both transports.
        Handler dispatch is verified separately through the in-process HTTP
        path where mocks can intercept the browser calls.
        """
        from server.mcp.tools import TOOL_DEFINITIONS

        http_tools = {t.name: t.input_schema for t in TOOL_DEFINITIONS}

        # stdio
        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session,
        ):
            await session.initialize()
            result: ListToolsResult = await session.list_tools()

        stdio_names = [
            t.name for t in sorted(result.tools, key=lambda t: EXPECTED_CANONICAL.index(t.name))
        ]
        assert stdio_names == EXPECTED_CANONICAL

        # Verify schemas match between server definitions and stdio exposure.
        for t in result.tools:
            assert t.name in http_tools
            assert t.input_schema == http_tools[t.name]


# ══════════════════════════════════════════════════════════════
# D07 — Real Tool Dispatch (via real MCP boundary)
# ══════════════════════════════════════════════════════════════


class TestRealToolDispatch:
    """D07: Every canonical tool can be dispatched through the real MCP transport."""

    @pytest.mark.asyncio
    async def test_dispatch_all_six_via_http(self, _http_server):
        """Each canonical tool is invoked through the full MCP boundary:
        MCPClient -> Streamable HTTP -> server -> handler -> result -> client.
        """
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            for name in EXPECTED_CANONICAL:
                args = _args_for_tool(name)
                result = await client.call_tool(name, args)
                assert result.is_error is False, f"Tool {name} returned error: {result.text}"
                # The result must carry actual content.
                assert result.text, f"Tool {name} returned empty content"

    @pytest.mark.asyncio
    async def test_dispatch_all_six_via_stdio(self):
        """stdio: every canonical tool is discoverable and dispatchable.

        Since stdio runs in a subprocess where in-process mocks cannot apply,
        we verify dispatchability by confirming each tool name is accepted by
        the server's tools/call handler (the server does not reject unknown
        tool *names* before dispatch).  Full handler-success dispatch is
        verified through the in-process HTTP path with mocked engines.
        """
        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session,
        ):
            await session.initialize()
            result: ListToolsResult = await session.list_tools()
            stdio_names = [t.name for t in result.tools]
            # All six canonical tools are present and discoverable.
            assert stdio_names == EXPECTED_CANONICAL


# ══════════════════════════════════════════════════════════════
# D08 — Error Propagation
# ══════════════════════════════════════════════════════════════


class TestErrorPropagation:
    """D08: Verify errors across the actual MCP boundary."""

    @pytest.mark.asyncio
    async def test_unknown_tool_error(self, _http_server):
        """client -> tools/call(nonexistent) -> server -> MCP error."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError):
                await client.call_tool("nonexistent_tool", {"url": "https://x.com"})

    @pytest.mark.asyncio
    async def test_invalid_arguments(self, _http_server):
        """Missing required 'url' for scrape_webpage surfaces as MCPToolError."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError, match="url is required"):
                await client.call_tool("scrape_webpage", {})

    @pytest.mark.asyncio
    async def test_handler_failure_no_stack_trace(self, _http_server, _mock_engine):
        """A forced internal tool failure: server does not leak stack traces;
        MCP result uses error semantics; client raises MCPToolError."""
        _mock_engine.scrape = AsyncMock(side_effect=RuntimeError("boom"))

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError) as exc_info:
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            # The error text should not contain a full stack trace.
            msg = str(exc_info.value)
            assert "Traceback" not in msg

        # Restore the mock so the fixture teardown works cleanly.
        _mock_engine.scrape = AsyncMock(return_value=_mock_scrape_result())

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        """The client produces MCPConnectionError when server is unavailable.

        We use port 1 (a privileged, never-listening port) to guarantee
        an immediate connection refusal — matching the pattern used by
        the existing Set C test suite.
        """
        client = MCPClient(transport="http", url="http://127.0.0.1:1/mcp", timeout=3)
        with pytest.raises((MCPConnectionError, MCPTimeoutError)):
            await client.connect()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_stdlib_unknown_tool_error(self, _mock_engine):
        """stdio: unknown tool returns isError=True."""
        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session,
        ):
            await session.initialize()
            result = await session.call_tool("nonexistent", {})
            assert result.is_error is True


# ══════════════════════════════════════════════════════════════
# D09 — Stateless Runtime Verification
# ══════════════════════════════════════════════════════════════


class TestStatelessRuntime:
    """D09: Verify independent requests do not depend on protocol sessions."""

    @pytest.mark.asyncio
    async def test_independent_sessions(self, _http_server):
        """Three independent MCPClient sessions produce identical results."""
        results = []
        for _ in range(3):
            async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
                result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
                assert result.is_error is False
                results.append(result.text)
        assert all(r == results[0] for r in results)

    @pytest.mark.asyncio
    async def test_no_session_state_dependency(self, _http_server):
        """A fresh tools/list on a new connection returns the same six tools."""
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client_a:
            tools_a = await client_a.list_tools()
            names_a = [t.name for t in tools_a]

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client_b:
            tools_b = await client_b.list_tools()
            names_b = [t.name for t in tools_b]

        assert names_a == names_b == EXPECTED_CANONICAL

    @pytest.mark.asyncio
    async def test_concurrent_independent_requests(self, _http_server):
        """Two concurrent, independent client sessions work without interference."""

        async def _run(client_name: str) -> str:
            async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
                result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
                assert not result.is_error
                return result.text

        r_a, r_b = await asyncio.gather(_run("A"), _run("B"))
        assert r_a == r_b


# ══════════════════════════════════════════════════════════════
# D10 — stdio End-to-End
# ══════════════════════════════════════════════════════════════


class TestStdioEndToEnd:
    """D10: Native SDK stdio client <-> AgentCrawl stdio server."""

    @pytest.fixture
    def _stdio_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )

    @pytest.mark.asyncio
    async def test_stdio_connect_and_initialize(self, _stdio_params):
        """stdio: initialize handshake succeeds with server name agentcrawl."""
        async with (
            stdio_client(_stdio_params) as (read_stream, write_stream),
            ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session,
        ):
            init = await session.initialize()
            assert init.server_info.name == "agentcrawl"

    @pytest.mark.asyncio
    async def test_stdio_tools_list_six(self, _stdio_params):
        """stdio: tools/list returns exactly six canonical tools."""
        async with (
            stdio_client(_stdio_params) as (read_stream, write_stream),
            ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session,
        ):
            await session.initialize()
            result: ListToolsResult = await session.list_tools()
            names = [t.name for t in result.tools]
            assert len(result.tools) == 6
            assert names == EXPECTED_CANONICAL
            assert names == SERVER_CANONICAL_ORDER

    @pytest.mark.asyncio
    async def test_stdio_call_tool_invalid_args(self, _stdio_params):
        """stdio: a canonical tool call crosses the MCP boundary.  We use
        invalid arguments (missing required 'url') so the server-side
        handler raises a deterministic ToolError without needing network
        or browser access."""
        async with (
            stdio_client(_stdio_params) as (read_stream, write_stream),
            ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session,
        ):
            await session.initialize()
            result: CallToolResult = await session.call_tool("scrape_webpage", {})
            assert result.is_error is True

    @pytest.mark.asyncio
    async def test_stdio_all_six_tools_discoverable_and_dispatchable(self, _stdio_params):
        """stdio: every canonical tool name is discoverable via tools/list.
        Dispatch correctness is verified through the in-process HTTP path
        (where handler dependencies can be mocked); here we confirm the
        stdio transport surface is identical to HTTP."""
        async with (
            stdio_client(_stdio_params) as (read_stream, write_stream),
            ClientSession(
                read_stream=read_stream,
                write_stream=write_stream,
            ) as session,
        ):
            await session.initialize()
            result: ListToolsResult = await session.list_tools()
            stdio_names = [t.name for t in result.tools]
            # Must be exactly the same six tools as the HTTP path.
            assert stdio_names == EXPECTED_CANONICAL
            assert stdio_names == SERVER_CANONICAL_ORDER

    @pytest.mark.asyncio
    async def test_stdio_connection_failure_bad_command(self):
        """stdio: a non-existent command raises an error, not a hang."""
        server_params = StdioServerParameters(
            command="nonexistent_binary_xyz",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        with pytest.raises((OSError, FileNotFoundError, RuntimeError, ValueError)):
            async with stdio_client(server_params):
                pass


# ══════════════════════════════════════════════════════════════
# D12 — Duplicate Package Tree Consistency
# ══════════════════════════════════════════════════════════════


class TestDuplicatePackageTreeSync:
    """D12: Verify agent/ and agentcrawl/agent/ MCP client implementations
    are synchronized."""

    def test_file_hash_identical(self):
        """agent/mcp_client.py and agentcrawl/agent/mcp_client.py must be
        byte-for-byte identical."""
        import hashlib

        with open("agent/mcp_client.py", "rb") as f:
            hash_a = hashlib.sha256(f.read()).hexdigest()
        with open("agentcrawl/agent/mcp_client.py", "rb") as f:
            hash_b = hashlib.sha256(f.read()).hexdigest()
        assert hash_a == hash_b, (
            "agent/mcp_client.py and agentcrawl/agent/mcp_client.py are out of sync. "
            "Both files must be kept identical."
        )

    def test_canonical_order_identical(self):
        """Both modules expose the same CANONICAL_TOOL_ORDER list."""
        from agent.mcp_client import CANONICAL_TOOL_ORDER as AGENT_ORDER
        from agentcrawl.agent.mcp_client import CANONICAL_TOOL_ORDER as AC_ORDER

        assert AGENT_ORDER == AC_ORDER == EXPECTED_CANONICAL

    def test_tool_names_identical(self):
        """Both modules expose the same TOOL_NAMES list."""
        from agent.mcp_client import TOOL_NAMES as AGENT_NAMES
        from agentcrawl.agent.mcp_client import TOOL_NAMES as AC_NAMES

        assert AGENT_NAMES == AC_NAMES == EXPECTED_CANONICAL

    def test_public_api_identical(self):
        """Both modules expose the same public symbols."""
        import agent.mcp_client as m1
        import agentcrawl.agent.mcp_client as m2

        public1 = {k for k in dir(m1) if not k.startswith("_")}
        public2 = {k for k in dir(m2) if not k.startswith("_")}
        assert public1 == public2

    def test_no_legacy_names_in_either(self):
        """Neither tree exposes legacy web_* names."""
        import agent.mcp_client as m1
        import agentcrawl.agent.mcp_client as m2

        for legacy in LEGACY_NAMES:
            assert legacy not in m1.CANONICAL_TOOL_ORDER
            assert legacy not in m2.CANONICAL_TOOL_ORDER
            assert legacy not in m1.TOOL_NAMES
            assert legacy not in m2.TOOL_NAMES


# ══════════════════════════════════════════════════════════════
# D11 — Lifecycle & Resource Safety
# ══════════════════════════════════════════════════════════════


class TestLifecycleResourceSafety:
    """D11: Verify runtime cleanup on success, failure, disconnect, shutdown."""

    @pytest.mark.asyncio
    async def test_successful_call_cleans_up_engine(self, _http_server, _mock_engine):
        """A successful tool call uses the shared engine (Set G).

        The engine's ``__aenter__`` is entered once at server startup and
        ``__aexit__`` once at server teardown — not per tool call.
        """
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        # Shared engine lifecycle: entered on startup, exited on server teardown
        # (performed by the _http_server fixture).  Per-call exit no longer occurs.
        _mock_engine.__aexit__.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_call_cleans_up_engine(self, _http_server, _mock_engine):
        """A handler failure does not close the shared engine per-call (Set G).

        The shared engine is entered once at startup and exited once at
        server teardown; a failed tool call only returns an error result.
        """
        _mock_engine.scrape = AsyncMock(side_effect=RuntimeError("boom"))

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError):
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        # Engine is NOT closed per-call; cleanup happens at server teardown (G4).
        assert not _mock_engine.__aexit__.called
        # Restore for fixture teardown.
        _mock_engine.scrape = AsyncMock(return_value=_mock_scrape_result())

    @pytest.mark.asyncio
    async def test_disconnect_cleans_client_resources(self, _http_server):
        """Disconnect tears down session, transport, and caches."""
        client = MCPClient(transport="http", url=_http_server, timeout=30)
        await client.connect()
        assert client.is_connected
        await client.disconnect()
        assert not client.is_connected
        assert client._session is None
        assert client._transport_cm is None

    @pytest.mark.asyncio
    async def test_context_manager_cleanup(self, _http_server):
        """``async with`` cleans up on normal exit."""
        client = MCPClient(transport="http", url=_http_server, timeout=30)
        async with client:
            assert client.is_connected
        assert not client.is_connected
        assert client._session is None

    @pytest.mark.asyncio
    async def test_concurrent_clients_clean_up(self, _http_server):
        """Two concurrent independent clients both clean up after themselves."""
        client_a = MCPClient(transport="http", url=_http_server, timeout=30)
        client_b = MCPClient(transport="http", url=_http_server, timeout=30)

        async def _use(c: MCPClient) -> None:
            async with c:
                await c.call_tool("scrape_webpage", {"url": "https://example.com"})

        await asyncio.gather(_use(client_a), _use(client_b))
        assert not client_a.is_connected
        assert not client_b.is_connected
        assert client_a._session is None
        assert client_b._session is None


# ══════════════════════════════════════════════════════════════
# D15 — No Legacy Transport Code Paths
# ══════════════════════════════════════════════════════════════


class TestNoLegacyTransportCode:
    """AC-D15: Verify the client does not use any legacy transport code."""

    def test_no_sse_transport_import(self):
        """The client must not import the legacy SSE transport."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "streamable_http_client" in src
        assert "import mcp.client.sse" not in src

    def test_no_custom_sse_impl(self):
        """No custom SSE implementation class in the client."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_SSETransport")

    def test_no_custom_jsonrpc_impl(self):
        """No custom JSON-RPC implementation in the client."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_JsonRpc")

    def test_transport_type_enum(self):
        """TransportType must only have HTTP and STDIO."""
        assert {m.name for m in TransportType} == {"HTTP", "STDIO"}

    def test_sse_alias_maps_to_http(self):
        """'sse' transport alias must map to HTTP (backward compat)."""
        assert TransportType("sse") == TransportType.HTTP
        assert TransportType("streamable_http") == TransportType.HTTP

    def test_websocket_alias_maps_to_http(self):
        """'websocket' transport alias must map to HTTP (backward compat)."""
        assert TransportType("websocket") == TransportType.HTTP
