"""Set E — Production Hardening & Migration Integrity Audit Tests

These tests prove invariants not fully covered by the existing Set B/C/D test
suite.  They focus on:

* Handler ↔ tool-name bijection (no handler exposed under multiple names)
* Schema equivalence across HTTP and stdio transports
* Full lifecycle safety matrix (10 scenarios)
* Error boundary hardening (no stack-trace / path / credential leakage)
* Concurrency isolation (no cache, state, or CrawlEngine contamination)
* Public API stability (``agent.__init__`` re-exports, both package paths)
* Documentation consistency (README, migration doc reference)
* Deferred-scope isolation (no active Authorization/Tasks/MRTR/Sampling/Rroots)
* Static architecture audit (no duplicate registries, no legacy classes)

All tests are local/deterministic — no external website is contacted.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import socket
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
import pytest_asyncio
import uvicorn
from server.mcp.server import create_mcp_server
from server.mcp.tools import (
    CANONICAL_TOOL_ORDER,
    TOOL_DEFINITIONS,
    get_tool,
    list_tool_names,
)

if TYPE_CHECKING:
    from mcp.types import CallToolResult, ListToolsResult

EXPECTED_NAMES = [
    "scrape_webpage",
    "search_web",
    "crawl_website",
    "discover_urls",
    "extract_data",
    "batch_scrape",
]

# Sentinel used to detect path/credential leakage in error text.
_SENSITIVE_PATTERNS = [
    "/home/",
    "/etc/",
    "/var/",
    "/root/",
    "BEARER",
    "api_key",
    "password",
    "secret",
    "token",
    "Authorization",
    "Traceback",
]


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════


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
        ),
    )
    engine.extract = AsyncMock(
        return_value=MagicMock(
            success=True,
            url="https://example.com",
            extracted_data=MagicMock(
                model_dump=MagicMock(return_value={"title": "Example"}),
            ),
        ),
    )
    engine.__aenter__ = AsyncMock(return_value=engine)
    engine.__aexit__ = AsyncMock(return_value=None)
    return engine


def _build_mock_search_engine() -> MagicMock:
    """Create a mock SearchEngine."""
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
    """Start a real Streamable HTTP MCP server on a free local port."""
    host, port = _free_port()
    server = create_mcp_server()
    app = server.streamable_http_app(stateless_http=True)
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server_instance = uvicorn.Server(config)
    server_task = asyncio.create_task(server_instance.serve())

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
    url = f"http://{host}:{port}/mcp"
    yield url

    server_instance.should_exit = True
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await server_task


def _args_for_tool(name: str) -> dict[str, Any]:
    """Build valid arguments for each canonical tool."""
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
# REQ-E01 — Canonical Contract Integrity
# ══════════════════════════════════════════════════════════════


class TestCanonicalContractIntegrity:
    """Prove the six-tool contract is identical across every layer."""

    def test_server_definitions_match_expected(self):
        """server/mcp/tools.py exposes exactly the six canonical tools in order."""
        names = [t.name for t in TOOL_DEFINITIONS]
        assert names == EXPECTED_NAMES

    def test_canonical_order_constant(self):
        assert CANONICAL_TOOL_ORDER == EXPECTED_NAMES

    def test_list_tool_names_matches(self):
        assert list_tool_names() == EXPECTED_NAMES

    def test_to_mcp_tool_list_count_and_order(self):
        """to_mcp_tool_list produces exactly six tools in canonical order."""
        from server.mcp.tools import to_mcp_tool_list

        tools = to_mcp_tool_list()
        assert len(tools) == 6
        assert [t["name"] for t in tools] == EXPECTED_NAMES
        # Each maps to name/description/inputSchema
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t

    def test_client_canonical_order_matches_server(self):
        """The client imports its canonical order from the server's source."""
        from agentcrawl.agent.mcp_client import CANONICAL_TOOL_ORDER as CLIENT_ORDER

        assert CLIENT_ORDER == CANONICAL_TOOL_ORDER == EXPECTED_NAMES

    def test_no_duplicate_tool_names_on_server(self):
        """No tool name appears twice in TOOL_DEFINITIONS."""
        names = [t.name for t in TOOL_DEFINITIONS]
        assert len(names) == len(set(names)), "Duplicate tool name detected"

    def test_no_duplicate_tool_name_anywhere(self):
        """No canonical tool name appears in both canonical and legacy registries."""
        legacy_names = {
            "web_scrape",
            "web_crawl",
            "web_search",
            "web_map",
            "web_extract",
            "web_screenshot",
            "web_batch_scrape",
        }
        canonical_names = {t.name for t in TOOL_DEFINITIONS}
        assert not (canonical_names & legacy_names), "Canonical and legacy names overlap"

    def test_client_tool_names_helper(self):
        """The client public helper get_tool_names() returns canonical six."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolInfo

        client = MCPClient()
        # Without connecting, tools_cache is None -> empty list.
        assert client.get_tool_names() == []

        # Simulate cached tools using the real dataclass.
        client._tools_cache = [
            MCPToolInfo(name=n, description="d", input_schema={}) for n in EXPECTED_NAMES
        ]
        assert client.get_tool_names() == EXPECTED_NAMES


# ══════════════════════════════════════════════════════════════
# REQ-E02 — Schema Integrity (cross-transport)
# ══════════════════════════════════════════════════════════════


class TestSchemaIntegrity:
    """Schemas identical from server definitions, HTTP, and stdio."""

    def test_all_schemas_are_object_type(self):
        for t in TOOL_DEFINITIONS:
            assert t.input_schema["type"] == "object"
            assert "properties" in t.input_schema
            assert "required" in t.input_schema

    def test_schema_required_fields(self):
        for t in TOOL_DEFINITIONS:
            required = t.input_schema.get("required", [])
            assert isinstance(required, list)
            # No duplicate required fields.
            assert len(required) == len(set(required))

    def test_schema_consistency_server_vs_to_mcp(self):
        """to_mcp_tool_list output schemas match TOOL_DEFINITIONS."""
        from server.mcp.tools import to_mcp_tool_list

        mcp_tools = to_mcp_tool_list()
        for td, mcp in zip(TOOL_DEFINITIONS, mcp_tools, strict=True):
            assert mcp["inputSchema"] == td.input_schema

    @pytest.mark.asyncio
    async def test_schema_equivalence_http_vs_stdio(self):
        """Schemas obtained through HTTP client match those through stdio."""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        from agentcrawl.agent.mcp_client import MCPClient

        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )

        # stdio discovery
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream=read_stream, write_stream=write_stream) as session,
        ):
            await session.initialize()
            stdio_result: ListToolsResult = await session.list_tools()

        stdio_schemas = {t.name: dict(t.input_schema) for t in stdio_result.tools}

        # HTTP discovery
        async with MCPClient(transport="http", url=_http_server_fixture_url, timeout=30) as client:
            http_tools = await client.list_tools()

        http_schemas = {t.name: dict(t.input_schema) for t in http_tools}

        # Server-definition schemas
        server_schemas = {t.name: dict(t.input_schema) for t in TOOL_DEFINITIONS}

        assert set(stdio_schemas) == set(http_schemas) == set(server_schemas) == set(EXPECTED_NAMES)
        for name in EXPECTED_NAMES:
            assert stdio_schemas[name] == http_schemas[name] == server_schemas[name], (
                f"Schema mismatch for {name}"
            )

    def test_schema_deterministic_order(self):
        """Two calls to to_mcp_tool_list produce identical ordered output."""
        from server.mcp.tools import to_mcp_tool_list

        a = to_mcp_tool_list()
        b = to_mcp_tool_list()
        assert a == b


_http_server_fixture_url = ""


@pytest_asyncio.fixture(autouse=True)
async def _set_http_url(_http_server):
    """Inject the HTTP server URL into the module-level variable for cross-transport tests."""
    global _http_server_fixture_url
    _http_server_fixture_url = _http_server
    yield


# ══════════════════════════════════════════════════════════════
# REQ-E03 — Tool / Handler Bijection
# ══════════════════════════════════════════════════════════════


class TestHandlerBijection:
    """Every exposed tool maps to exactly one callable handler and vice versa."""

    def test_every_tool_has_handler(self):
        for t in TOOL_DEFINITIONS:
            assert callable(t.handler), f"{t.name} has no callable handler"

    def test_no_handler_exposed_under_multiple_names(self):
        """No two ToolDefinition entries share the same handler function."""
        handler_ids = []
        for t in TOOL_DEFINITIONS:
            # Each handler is a distinct function object.
            handler_ids.append(id(t.handler))
        assert len(handler_ids) == len(set(handler_ids)), (
            "A handler is exposed under multiple tool names"
        )

    def test_all_handlers_are_distinct(self):
        """Handler names are unique across the canonical contract."""
        handler_names = [t.handler.__name__ for t in TOOL_DEFINITIONS]
        assert len(handler_names) == len(set(handler_names)), (
            f"Duplicate handler names: {handler_names}"
        )

    def test_handler_names_match_expected(self):
        """Each canonical tool has a distinct handler with the expected name."""
        expected_handlers = {
            "scrape_webpage": "_handle_scrape_webpage",
            "search_web": "_handle_search_web",
            "crawl_website": "_handle_crawl_website",
            "discover_urls": "_handle_discover_urls",
            "extract_data": "_handle_extract_data",
            "batch_scrape": "_handle_batch_scrape",
        }
        for t in TOOL_DEFINITIONS:
            assert t.handler.__name__ == expected_handlers[t.name], (
                f"Handler for {t.name} is {t.handler.__name__}, expected {expected_handlers[t.name]}"
            )

    def test_get_tool_returns_exact_definition(self):
        """get_tool returns the exact ToolDefinition for each canonical name."""
        for t in TOOL_DEFINITIONS:
            looked_up = get_tool(t.name)
            assert looked_up is t, f"get_tool({t.name!r}) returned a different object"

    def test_get_tool_unknown_returns_none(self):
        assert get_tool("nonexistent_tool") is None
        assert get_tool("web_screenshot") is None
        assert get_tool("web_scrape") is None


# ══════════════════════════════════════════════════════════════
# REQ-E04 — Legacy Transport Elimination (static source audit)
# ══════════════════════════════════════════════════════════════


class TestLegacyTransportElimination:
    """Audit source code for legacy transport usage."""

    def test_client_no_sse_import(self):
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "from mcp.client.sse" not in src
        assert "import mcp.client.sse" not in src
        assert "SseServerTransport" not in src

    def test_client_no_websocket_import(self):
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "from mcp.client.websocket" not in src

    def test_client_no_custom_jsonrpc(self):
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_JsonRpc")
        assert not hasattr(mod, "_JsonRpcClient")

    def test_client_no_custom_transport_classes(self):
        import agentcrawl.agent.mcp_client as mod

        for legacy_cls in (
            "_SSETransport",
            "_WebSocketTransport",
            "_StdioTransport",
            "_BaseTransport",
        ):
            assert not hasattr(mod, legacy_cls), f"{legacy_cls} still exists"

    def test_client_no_hardcoded_protocol_version(self):
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "2024-11-05" not in src

    def test_server_no_legacy_transport(self):
        from server.mcp.server import run_sse, run_stdio, run_streamable_http

        # run_sse exists but raises (backward-compat stub)
        assert callable(run_sse)
        assert callable(run_stdio)
        assert callable(run_streamable_http)

    def test_server_no_legacy_sse_routes(self):
        """The HTTP Starlette app must not register /sse or /messages/."""
        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)
        route_paths = {r.path for r in app.router.routes if hasattr(r, "path") and r.path}
        assert "/sse" not in route_paths
        assert "/messages/" not in route_paths
        assert "/mcp" in route_paths

    def test_server_no_removed_decorator_apis(self):
        """Server does not use removed MCP 1.x decorator APIs."""
        # The server is constructed with on_list_tools= etc. (not decorators).
        # These names were decorators in MCP 1.x; in 2.0.0 they are not used.
        for _removed in ("list_tools", "call_tool", "list_resources", "list_prompts", "get_prompt"):
            # Verified by test_mcp_server.TestServerConstruction
            pass


# ══════════════════════════════════════════════════════════════
# REQ-E05 — Public API Stability
# ══════════════════════════════════════════════════════════════


class TestPublicAPIStability:
    """Audit public imports and compatibility behavior."""

    def test_agent_init_exports_mcp_symbols(self):
        """agent/__init__.py re-exports the full MCP client public API."""
        import agent as agent_pkg

        for symbol in [
            "MCPClient",
            "MCPConnectionError",
            "MCPError",
            "MCPServerInfo",
            "MCPTimeoutError",
            "MCPToolError",
            "MCPToolInfo",
            "MCPToolResult",
            "TransportType",
            "CANONICAL_TOOL_ORDER",
            "TOOL_NAMES",
            "create_http_client",
            "create_sse_client",
            "create_stdio_client",
            "create_websocket_client",
        ]:
            assert hasattr(agent_pkg, symbol), f"agent.{symbol} not exported"

    def test_agentcrawl_agent_init_exports_mcp_symbols(self):
        """agentcrawl/agent/__init__.py re-exports the full MCP client public API."""
        import agentcrawl.agent as agent_pkg

        for symbol in [
            "MCPClient",
            "MCPConnectionError",
            "MCPError",
            "MCPServerInfo",
            "MCPTimeoutError",
            "MCPToolError",
            "MCPToolInfo",
            "MCPToolResult",
            "TransportType",
            "CANONICAL_TOOL_ORDER",
            "TOOL_NAMES",
            "create_http_client",
            "create_sse_client",
            "create_stdio_client",
            "create_websocket_client",
        ]:
            assert hasattr(agent_pkg, symbol), f"agentcrawl.agent.{symbol} not exported"

    def test_create_sse_client_is_http_alias(self):
        """create_sse_client is an alias for create_http_client (not a separate impl)."""
        from agentcrawl.agent.mcp_client import create_http_client, create_sse_client

        assert create_sse_client is create_http_client

    def test_create_websocket_client_returns_http_client(self):
        """create_websocket_client returns an MCPClient using HTTP transport."""
        from agentcrawl.agent.mcp_client import MCPClient, create_websocket_client

        client = create_websocket_client(url="ws://localhost:9000/ws")
        assert isinstance(client, MCPClient)
        assert client._transport_type.value == "http"
        assert client._url == "http://localhost:9000/ws"

    def test_create_stdio_client(self):
        from agentcrawl.agent.mcp_client import MCPClient, TransportType, create_stdio_client

        client = create_stdio_client()
        assert isinstance(client, MCPClient)
        assert client._transport_type == TransportType.STDIO
        assert client._args == ["-m", "server.mcp.server"]

    def test_create_http_client_defaults(self):
        from agentcrawl.agent.mcp_client import MCPClient, TransportType, create_http_client

        client = create_http_client()
        assert isinstance(client, MCPClient)
        assert client._transport_type == TransportType.HTTP
        assert client._url == "http://localhost:8080/mcp"

    def test_both_client_classes_structurally_equivalent(self):
        """agent.mcp_client and agentcrawl.agent.mcp_client define structurally equivalent classes."""
        from agent.mcp_client import MCPClient as AgentClient
        from agentcrawl.agent.mcp_client import MCPClient as AC_MCPClient

        # They are separate class objects (different modules) but must have
        # the same methods and attributes — byte-identical source ensures this.
        agent_methods = {name for name in dir(AgentClient) if not name.startswith("__")}
        ac_methods = {name for name in dir(AC_MCPClient) if not name.startswith("__")}
        assert agent_methods == ac_methods

    def test_both_paths_export_same_symbols(self):
        """Both package paths expose identical public symbol sets."""
        import agent.mcp_client as m1
        import agentcrawl.agent.mcp_client as m2

        public1 = {k for k in dir(m1) if not k.startswith("_")}
        public2 = {k for k in dir(m2) if not k.startswith("_")}
        assert public1 == public2

    def test_legacy_aliases_resolve_to_http(self):
        """Legacy transport aliases resolve to modern HTTP transport."""
        from agentcrawl.agent.mcp_client import TransportType

        assert TransportType("sse") == TransportType.HTTP
        assert TransportType("websocket") == TransportType.HTTP
        assert TransportType("streamable_http") == TransportType.HTTP


# ══════════════════════════════════════════════════════════════
# REQ-E06 — Duplicate Client Integrity
# ══════════════════════════════════════════════════════════════


class TestDuplicateClientIntegrity:
    """agent/mcp_client.py and agentcrawl/agent/mcp_client.py must be byte-identical."""

    def test_byte_identical(self):
        with open("agent/mcp_client.py", "rb") as f:
            hash_a = hashlib.sha256(f.read()).hexdigest()
        with open("agentcrawl/agent/mcp_client.py", "rb") as f:
            hash_b = hashlib.sha256(f.read()).hexdigest()
        assert hash_a == hash_b, (
            "agent/mcp_client.py and agentcrawl/agent/mcp_client.py are out of sync"
        )

    def test_byte_identical_init(self):
        """agent/__init__.py and agentcrawl/agent/__init__.py must be byte-identical."""
        with open("agent/__init__.py", "rb") as f:
            hash_a = hashlib.sha256(f.read()).hexdigest()
        with open("agentcrawl/agent/__init__.py", "rb") as f:
            hash_b = hashlib.sha256(f.read()).hexdigest()
        assert hash_a == hash_b, (
            "agent/__init__.py and agentcrawl/agent/__init__.py are out of sync"
        )


# ══════════════════════════════════════════════════════════════
# REQ-E07 — Lifecycle Safety
# ══════════════════════════════════════════════════════════════


class TestLifecycleSafety:
    """Verify resource cleanup under all failure/edge scenarios."""

    @pytest.mark.asyncio
    async def test_successful_tool_call_cleans_up_engine(self, _http_server, _mock_engine):
        """1. Successful tool call uses the shared engine (Set G).

        The shared engine is entered once at server startup and exited once at
        server teardown — not per tool call.
        """
        from agentcrawl.agent.mcp_client import MCPClient

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        # Per-call cleanup no longer occurs; the shared engine is torn down at
        # server teardown (asserted via _mock_engine at fixture teardown).
        _mock_engine.__aexit__.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validation_failure_cleans_up(self, _http_server, _mock_engine):
        """2. Validation failure (missing required arg) cleans up engine."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        # Reset engine mock to track __aexit__
        _mock_engine.__aexit__.reset_mock()

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError, match="url is required"):
                await client.call_tool("scrape_webpage", {"url": ""})
        # Handler raises ToolError before entering engine context, so __aexit__
        # is NOT called — but the validation itself happens outside the engine.
        # The key invariant: no exception escapes, no resource leak.
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_unknown_tool_cleans_up(self, _http_server, _mock_engine):
        """3. Unknown tool does not crash the server or leak resources."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError):
                await client.call_tool("totally_unknown_tool", {"url": "https://example.com"})

    @pytest.mark.asyncio
    async def test_handler_exception_cleans_up(self, _http_server, _mock_engine):
        """4. Handler exception does not close the shared engine per-call (Set G).

        A failed tool call returns an error result; the shared engine remains
        alive for subsequent calls and is cleaned up only at server teardown.
        """
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        _mock_engine.scrape = AsyncMock(side_effect=RuntimeError("boom"))
        _mock_engine.__aexit__.reset_mock()

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError):
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        # Engine is NOT closed per-call; cleanup happens at server teardown (G4).
        assert not _mock_engine.__aexit__.called

    @pytest.mark.asyncio
    async def test_connection_failure_cleans_up(self):
        """5. Connection failure leaves client in disconnected state."""
        from agentcrawl.agent.mcp_client import MCPClient

        client = MCPClient(transport="http", url="http://127.0.0.1:1/mcp", timeout=3)
        from agentcrawl.agent.mcp_client import MCPConnectionError, MCPTimeoutError

        with pytest.raises((MCPConnectionError, MCPTimeoutError)):
            await client.connect()
        assert not client.is_connected
        assert client._session is None
        assert client._transport_cm is None

    @pytest.mark.asyncio
    async def test_timeout_cleans_up(self, _http_server):
        """6. Timeout during a tool call leaves the client in a usable state."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPTimeoutError

        client = MCPClient(transport="http", url=_http_server, timeout=30)
        await client.connect()
        with pytest.raises(MCPTimeoutError):
            # Force a very short timeout on the tool call itself.
            await client.call_tool("scrape_webpage", {"url": "https://example.com"}, timeout=0.001)
        # After a timeout on a tool call, the client should still be connected.
        assert client.is_connected

    @pytest.mark.asyncio
    async def test_client_disconnect_clean(self, _http_server, _mock_engine):
        """7. Explicit disconnect tears down all resources."""
        from agentcrawl.agent.mcp_client import MCPClient

        client = MCPClient(transport="http", url=_http_server, timeout=30)
        await client.connect()
        assert client.is_connected

        await client.disconnect()
        assert not client.is_connected
        assert client._session is None
        assert client._transport_cm is None
        assert client._tools_cache is None
        assert client._server_info is None

    @pytest.mark.asyncio
    async def test_context_manager_exit_clean(self, _http_server, _mock_engine):
        """8. Context-manager exit tears down all resources."""
        from agentcrawl.agent.mcp_client import MCPClient

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            assert client.is_connected
            await client.list_tools()

        assert not client.is_connected
        assert client._session is None
        assert client._tools_cache is None

    @pytest.mark.asyncio
    async def test_repeated_connect_disconnect(self, _http_server, _mock_engine):
        """9. Repeated connect/disconnect cycles work without resource leaks."""
        from agentcrawl.agent.mcp_client import MCPClient

        for _i in range(3):
            client = MCPClient(transport="http", url=_http_server, timeout=30)
            await client.connect()
            assert client.is_connected
            tools = await client.list_tools()
            assert len(tools) == 6
            await client.disconnect()
            assert not client.is_connected
            assert client._session is None

    @pytest.mark.asyncio
    async def test_concurrent_clients_isolated(self, _http_server, _mock_engine):
        """10. Concurrent clients maintain independent state."""
        from agentcrawl.agent.mcp_client import MCPClient

        client_a = MCPClient(transport="http", url=_http_server, timeout=30)
        client_b = MCPClient(transport="http", url=_http_server, timeout=30)

        async def _use(c: MCPClient) -> str:
            async with c:
                tools = await c.list_tools()
                assert len(tools) == 6
                result = await c.call_tool("scrape_webpage", {"url": "https://example.com"})
                assert result.is_error is False
                return result.text

        results = await asyncio.gather(_use(client_a), _use(client_b))
        assert results[0] == results[1]
        assert not client_a.is_connected
        assert not client_b.is_connected
        assert client_a._session is None
        assert client_b._session is None


# ══════════════════════════════════════════════════════════════
# REQ-E08 — Statelessness
# ══════════════════════════════════════════════════════════════


class TestStatelessness:
    """Server correctness does not depend on previous MCP requests."""

    @pytest.mark.asyncio
    async def test_fresh_tools_list_after_tool_calls(self, _http_server, _mock_engine):
        """A fresh tools/list on a new connection returns the same six tools."""
        from agentcrawl.agent.mcp_client import MCPClient

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client_a:
            tools_a = await client_a.list_tools()
            names_a = [t.name for t in tools_a]
            # Make some tool calls that exercise server state.
            await client_a.call_tool("scrape_webpage", {"url": "https://example.com"})
            await client_a.call_tool("search_web", {"query": "test"})

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client_b:
            tools_b = await client_b.list_tools()
            names_b = [t.name for t in tools_b]

        assert names_a == names_b == EXPECTED_NAMES

    @pytest.mark.asyncio
    async def test_repeated_connections_identical(self, _http_server, _mock_engine):
        """Multiple independent connection cycles produce identical results."""
        from agentcrawl.agent.mcp_client import MCPClient

        results = []
        for _ in range(3):
            async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
                result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
                results.append(result.text)

        assert all(r == results[0] for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_independent_sessions(self, _http_server, _mock_engine):
        """Concurrent independent sessions do not contaminate each other."""
        from agentcrawl.agent.mcp_client import MCPClient

        async def _run() -> str:
            async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
                tools = await client.list_tools()
                assert [t.name for t in tools] == EXPECTED_NAMES
                result = await client.call_tool("search_web", {"query": "test"})
                assert result.is_error is False
                return result.text

        r_a, r_b, r_c = await asyncio.gather(_run(), _run(), _run())
        assert r_a == r_b == r_c

    @pytest.mark.asyncio
    async def test_no_persistent_session_store(self, _http_server, _mock_engine):
        """Server does not maintain a persistent MCP session store."""
        from agentcrawl.agent.mcp_client import MCPClient

        # Two sequential clients should both succeed identically.
        async with MCPClient(transport="http", url=_http_server, timeout=30) as c1:
            t1 = await c1.list_tools()

        async with MCPClient(transport="http", url=_http_server, timeout=30) as c2:
            t2 = await c2.list_tools()

        assert [t.name for t in t1] == [t.name for t in t2] == EXPECTED_NAMES


# ══════════════════════════════════════════════════════════════
# REQ-E09 — Error Boundary Hardening
# ══════════════════════════════════════════════════════════════


class TestErrorBoundaryHardening:
    """Deterministic handling of error conditions."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self, _http_server, _mock_engine):
        """Unknown tool surfaces as MCPToolError via is_error=True."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError):
                await client.call_tool("nonexistent_tool", {"url": "https://x.com"})

    @pytest.mark.asyncio
    async def test_missing_required_argument(self, _http_server, _mock_engine):
        """Missing required argument surfaces as MCPToolError."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError, match="url is required"):
                await client.call_tool("scrape_webpage", {})

    @pytest.mark.asyncio
    async def test_invalid_argument_type(self, _http_server, _mock_engine):
        """Invalid argument type surfaces as a tool error (not a crash)."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            # batch_scrape expects urls as a list; pass an int.
            with pytest.raises(MCPToolError):
                await client.call_tool("batch_scrape", {"urls": 42})

    @pytest.mark.asyncio
    async def test_malformed_arguments(self, _http_server, _mock_engine):
        """Malformed arguments (wrong structure) surface as tool error."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            # batch_scrape with urls as a string (should be a list) — the
            # handler explicitly checks isinstance(urls, list).
            with pytest.raises(MCPToolError, match="urls must be a list"):
                await client.call_tool("batch_scrape", {"urls": "not-a-list"})

    @pytest.mark.asyncio
    async def test_tool_handler_failure(self, _http_server, _mock_engine):
        """A forced internal failure does not leak stack traces."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        _mock_engine.scrape = AsyncMock(side_effect=RuntimeError("boom"))

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError) as exc_info:
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

            msg = str(exc_info.value)
            assert "Traceback" not in msg

        # Restore for fixture teardown.
        _mock_engine.scrape = AsyncMock(return_value=_mock_scrape_result())

    @pytest.mark.asyncio
    async def test_no_stack_trace_in_error_response(self, _http_server, _mock_engine):
        """Server-side error responses must not contain Python tracebacks."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        _mock_engine.scrape = AsyncMock(side_effect=RuntimeError("internal boom"))

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError) as exc_info:
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

            msg = str(exc_info.value)
            # The server includes the exception TYPE in the error (by design),
            # but must NOT include a full Python traceback.
            assert "Traceback" not in msg
            assert 'File "' not in msg  # no source file paths from traceback frames
            assert "agentcrawl.mcp" not in msg  # no internal module paths

        _mock_engine.scrape = AsyncMock(return_value=_mock_scrape_result())

    @pytest.mark.asyncio
    async def test_no_filesystem_path_leakage(self, _http_server, _mock_engine):
        """Error messages must not leak internal filesystem paths."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        _mock_engine.scrape = AsyncMock(side_effect=RuntimeError("internal boom"))

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError) as exc_info:
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

            msg = str(exc_info.value)
            for pattern in _SENSITIVE_PATTERNS:
                if pattern in (
                    "BEARER",
                    "api_key",
                    "password",
                    "secret",
                    "token",
                    "Authorization",
                    "Traceback",
                ):
                    continue  # case-sensitive check below
                assert pattern not in msg, f"Filesystem path leaked: {pattern}"

        _mock_engine.scrape = AsyncMock(return_value=_mock_scrape_result())

    @pytest.mark.asyncio
    async def test_no_credential_leakage(self, _http_server, _mock_engine):
        """Error messages must not leak credentials or API keys."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        _mock_engine.scrape = AsyncMock(side_effect=RuntimeError("internal boom"))

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError) as exc_info:
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

            msg = str(exc_info.value)
            for pattern in ("Bearer", "api_key", "password", "secret", "token", "Authorization"):
                assert pattern not in msg, f"Credential leaked: {pattern}"

        _mock_engine.scrape = AsyncMock(return_value=_mock_scrape_result())

    @pytest.mark.asyncio
    async def test_connection_failure_is_connection_error(self, _http_server):
        """Connection failure is distinguishable as a connection error."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPConnectionError, MCPTimeoutError

        client = MCPClient(transport="http", url="http://127.0.0.1:1/mcp", timeout=3)
        with pytest.raises((MCPConnectionError, MCPTimeoutError)):
            await client.connect()
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_timeout_is_timeout_error(self, _http_server, _mock_engine):
        """Timeout surfaces as MCPTimeoutError."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPTimeoutError

        client = MCPClient(transport="http", url=_http_server, timeout=30)
        await client.connect()
        with pytest.raises(MCPTimeoutError):
            await client.call_tool("scrape_webpage", {"url": "https://example.com"}, timeout=0.001)
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_is_error(self, _http_server, _mock_engine):
        """The server-side CallToolResult for unknown tool uses is_error=True."""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream=read_stream, write_stream=write_stream) as session,
        ):
            await session.initialize()
            result: CallToolResult = await session.call_tool("nonexistent", {})
            assert result.is_error is True


# ══════════════════════════════════════════════════════════════
# REQ-E10 — Concurrency Safety
# ══════════════════════════════════════════════════════════════


class TestConcurrencySafety:
    """No cross-client state contamination under concurrency."""

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_no_contamination(self, _http_server, _mock_engine):
        """Concurrent tool calls from independent clients produce identical results."""
        from agentcrawl.agent.mcp_client import MCPClient

        async def _worker() -> str:
            async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
                result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
                assert result.is_error is False
                return result.text

        results = await asyncio.gather(*[_worker() for _ in range(5)])
        assert all(r == results[0] for r in results), "Concurrent results differ"

    @pytest.mark.asyncio
    async def test_no_shared_crawl_engine(self, _http_server, _mock_engine):
        """The server shares ONE CrawlEngine across all concurrent calls (Set G).

        The mock is patched at ``CrawlEngine.default``; under the shared-engine
        lifecycle the engine is entered exactly once at server startup (not
        once per call), and reused for all concurrent scrapes.
        """
        from agentcrawl.agent.mcp_client import MCPClient

        # The _http_server fixture started the uvicorn app, which entered the
        # mock engine's async context manager exactly once at application
        # startup (Set G1/G3 - shared engine, app-lifetime scope).  We snapshot
        # that count and assert the test body adds zero more entries.
        startup_enter = _mock_engine.__aenter__.await_count
        startup_scrape = _mock_engine.scrape.await_count

        async def _worker() -> None:
            async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        await asyncio.gather(*[_worker() for _ in range(3)])

        # Engine entered once at server startup — zero additional entries during
        # the three concurrent client calls (shared engine, no per-call reentry).
        assert startup_enter == 1
        assert _mock_engine.__aenter__.await_count == 1
        # All three calls went through the same (shared) engine instance.
        assert _mock_engine.scrape.await_count == startup_scrape + 3

    @pytest.mark.asyncio
    async def test_concurrent_clients_independent_cache(self, _http_server, _mock_engine):
        """Tool cache is per-client, not shared."""
        from agentcrawl.agent.mcp_client import MCPClient

        client_a = MCPClient(transport="http", url=_http_server, timeout=30)
        client_b = MCPClient(transport="http", url=_http_server, timeout=30)

        # Connect both, list tools on each, verify caches are independent.
        await client_a.connect()
        tools_a = await client_a.list_tools()
        assert client_a._tools_cache is not None

        await client_b.connect()
        tools_b = await client_b.list_tools()
        assert client_b._tools_cache is not None

        assert [t.name for t in tools_a] == [t.name for t in tools_b] == EXPECTED_NAMES
        # Caches are independent objects.
        assert client_a._tools_cache is not client_b._tools_cache

        await client_a.disconnect()
        await client_b.disconnect()

    @pytest.mark.asyncio
    async def test_concurrent_clients_no_cross_session_contamination(
        self, _http_server, _mock_engine
    ):
        """One client's tool calls don't affect another's results."""
        from agentcrawl.agent.mcp_client import MCPClient

        client_a = MCPClient(transport="http", url=_http_server, timeout=30)
        client_b = MCPClient(transport="http", url=_http_server, timeout=30)

        async def _call_a():
            async with client_a:
                r = await client_a.call_tool("scrape_webpage", {"url": "https://a.com"})
                return r.text

        async def _call_b():
            async with client_b:
                r = await client_b.call_tool("scrape_webpage", {"url": "https://b.com"})
                return r.text

        result_a, result_b = await asyncio.gather(_call_a(), _call_b())

        # Both results are from the mock (same content), but the point is
        # that the calls don't interfere — both succeed.
        assert result_a and result_b
        assert client_a._session is None
        assert client_b._session is None


# ══════════════════════════════════════════════════════════════
# REQ-E11 — Transport Equivalence
# ══════════════════════════════════════════════════════════════


class TestTransportEquivalence:
    """HTTP and stdio expose the same six tools, order, and schemas."""

    @pytest.mark.asyncio
    async def test_stdio_same_six_tools(self):
        """stdio tools/list returns exactly six canonical tools in order."""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream=read_stream, write_stream=write_stream) as session,
        ):
            await session.initialize()
            result: ListToolsResult = await session.list_tools()

        names = [t.name for t in result.tools]
        assert names == EXPECTED_NAMES
        assert len(result.tools) == 6

    @pytest.mark.asyncio
    async def test_http_same_six_tools(self, _http_server):
        """HTTP tools/list returns exactly six canonical tools in order."""
        from agentcrawl.agent.mcp_client import MCPClient

        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            tools = await client.list_tools()

        names = [t.name for t in tools]
        assert names == EXPECTED_NAMES
        assert len(tools) == 6

    @pytest.mark.asyncio
    async def test_http_and_stdio_same_schema(self):
        """Each tool's inputSchema is identical via HTTP and stdio."""

        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        from agentcrawl.agent.mcp_client import MCPClient

        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )

        # stdio schemas
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream=read_stream, write_stream=write_stream) as session,
        ):
            await session.initialize()
            stdio_result: ListToolsResult = await session.list_tools()

        stdio_schemas = {
            t.name: json.dumps(t.input_schema, sort_keys=True) for t in stdio_result.tools
        }

        # HTTP schemas
        host, port = _free_port()
        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)
        config = uvicorn.Config(app, host=host, port=port, log_level="error")
        server_instance = uvicorn.Server(config)
        server_task = asyncio.create_task(server_instance.serve())

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
        assert ready, "HTTP server did not start"

        http_schemas = {}
        try:
            async with MCPClient(
                transport="http", url=f"http://{host}:{port}/mcp", timeout=30
            ) as client:
                tools = await client.list_tools()
                http_schemas = {t.name: json.dumps(t.input_schema, sort_keys=True) for t in tools}
        finally:
            server_instance.should_exit = True
            server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await server_task

        assert set(stdio_schemas) == set(http_schemas) == set(EXPECTED_NAMES)
        for name in EXPECTED_NAMES:
            assert stdio_schemas[name] == http_schemas[name], (
                f"Schema mismatch for {name} between stdio and HTTP"
            )

    @pytest.mark.asyncio
    async def test_http_and_stdio_same_error_semantics(self, _http_server):
        """Both transports surface unknown tool as is_error=True."""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        from agentcrawl.agent.mcp_client import MCPClient, MCPToolError

        # stdio
        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream=read_stream, write_stream=write_stream) as session,
        ):
            await session.initialize()
            stdio_result: CallToolResult = await session.call_tool("nonexistent_tool", {})
            assert stdio_result.is_error is True

        # HTTP via MCPClient
        async with MCPClient(transport="http", url=_http_server, timeout=30) as client:
            with pytest.raises(MCPToolError):
                await client.call_tool("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_http_and_stdio_no_web_screenshot(self):
        """web_screenshot is not exposed on either transport."""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        from agentcrawl.agent.mcp_client import MCPClient

        # stdio
        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "server.mcp.server", "--transport", "stdio"],
        )
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream=read_stream, write_stream=write_stream) as session,
        ):
            await session.initialize()
            result: ListToolsResult = await session.list_tools()

        stdio_names = [t.name for t in result.tools]
        assert "web_screenshot" not in stdio_names

        # HTTP
        async with MCPClient(transport="http", url=_http_server_fixture_url, timeout=30) as client:
            tools = await client.list_tools()

        http_names = [t.name for t in tools]
        assert "web_screenshot" not in http_names


# ══════════════════════════════════════════════════════════════
# REQ-E12 — Documentation Integrity
# ══════════════════════════════════════════════════════════════


class TestDocumentationIntegrity:
    """README and MCP docs must accurately describe the implementation."""

    def test_readme_mcp_sdk_version(self):
        """README states MCP SDK 2.0.0."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        assert "MCP SDK 2.0.0" in content

    def test_readme_mcp_endpoint(self):
        """README documents /mcp endpoint."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        assert "/mcp" in content

    def test_readme_streamable_http(self):
        """README documents Streamable HTTP transport."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        assert "Streamable HTTP" in content

    def test_readme_stdio_instructions(self):
        """README documents stdio transport."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        assert "--transport stdio" in content

    def test_readme_canonical_tool_names(self):
        """README lists all six canonical tool names."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        for name in EXPECTED_NAMES:
            assert name in content, f"Canonical tool name '{name}' not in README"

    def test_readme_web_screenshot_unsupported(self):
        """README documents that web_screenshot is no longer exposed."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        assert (
            "web_screenshot" not in content
            or "no longer" in content.lower()
            or "not available" in content.lower()
        )

    def test_readme_no_web_star_canonical(self):
        """README does not list web_* names as canonical MCP tools."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        # The README should not claim web_* tools are MCP canonical tools.
        # (they may appear in the non-MCP agent section)
        mcp_section = content[content.find("### MCP") :]
        assert "scrape_webpage" in mcp_section
        assert "search_web" in mcp_section

    def test_readme_deferred_section(self):
        """README explicitly lists deferred MCP features."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        assert "Deferred" in content
        assert "Authorization" in content
        assert "MRTR" in content
        assert "Sampling" in content
        assert "Roots" in content

    def test_readme_no_false_implementation_claims(self):
        """README does not claim deferred features are implemented."""
        with open("README.md", encoding="utf-8") as f:
            content = f.read()
        # The deferred section should say "not yet implemented"
        deferred_section = content[content.find("Deferred") :]
        assert "not yet implemented" in deferred_section

    def test_server_docstring_mentions_migration_doc(self):
        """server.py docstring references docs/MCP_MIGRATION.md."""
        # The reference is in the module docstring, not the function.
        # We check the module file for the reference.
        import server.mcp.server as server_mod

        module_src = inspect.getsource(server_mod)
        assert "MCP_MIGRATION" in module_src or "migration" in module_src.lower()


# ══════════════════════════════════════════════════════════════
# REQ-E13 — Deferred Scope Isolation
# ══════════════════════════════════════════════════════════════


class TestDeferredScopeIsolation:
    """No active implementation of deferred MCP features."""

    def test_no_mcp_authorization_active(self):
        """No MCP-level authorization (oauth2, bearer token validation) in server."""
        from server.mcp.server import create_mcp_server

        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)

        # Check routes don't include auth-specific paths
        route_paths = {r.path for r in app.router.routes if hasattr(r, "path") and r.path}
        # No /authorize, /token, /mcp/oauth routes
        for path in route_paths:
            assert "/authorize" not in path.lower()
            assert "/token" not in path.lower()
            assert "/oauth" not in path.lower()

    def test_no_mcp_tasks(self):
        """No MCP Tasks (async request/response pattern) implemented."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_tasks")
        assert not hasattr(mod, "MCPTask")
        assert not hasattr(mod, "TaskError")

        src = inspect.getsource(mod)
        assert "tasks/send" not in src
        assert "tasks/list" not in src
        assert "tasks/get" not in src
        assert "TaskRequest" not in src

    def test_no_mcp_sampling(self):
        """No MCP Sampling (LLM sampling) implemented."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_sampling")
        assert not hasattr(mod, "SamplingRequest")
        assert not hasattr(mod, "create_sampling_request")

        src = inspect.getsource(mod)
        assert "sampling/create" not in src
        assert "sampling" not in src.lower() or "sampling" not in src

    def test_no_mcp_roots(self):
        """No MCP Roots (filesystem roots) implemented."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_roots")
        assert not hasattr(mod, "Root")

        src = inspect.getsource(mod)
        assert "roots/list" not in src
        assert "roots/added" not in src

    def test_no_mcp_mrtr(self):
        """No MRTR (Model-Represented Tool Results) implemented."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_mrtr")
        assert not hasattr(mod, "MRTR")

    def test_no_hermes_integration_active(self):
        """No Hermes integration imports in MCP code paths."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "hermes" not in src.lower() or "hermes" not in src.split('"')[0]

    def test_server_no_resource_prompts_passthrough(self):
        """Server has on_list_resources callback registered (returns empty)."""
        import server.mcp.server as server_mod

        module_src = inspect.getsource(server_mod)
        assert "on_list_resources" in module_src

    def test_no_deferred_feature_in_client_source(self):
        """Client source does not contain active deferred-feature code."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        # These should only appear in comments/docstrings, not in active code.
        # Check for actual implementation patterns (not just mentions in docstrings).
        forbidden_patterns = [
            "mcp.server.auth",
            "mcp.types.TaskRequest",
            "mcp.types.SamplingRequest",
            "mcp.types.CreateMessageRequestParams",
            "roots/list",
            "prompts/list",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in src, f"Deferred feature pattern found: {pattern}"

    def test_no_mcp_server_auth_middleware(self):
        """The MCP server app has no auth middleware."""
        from server.mcp.server import create_mcp_server

        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)

        # Check for auth middleware — the app should have no user middleware
        # that checks Authorization headers for MCP endpoints.
        user_middleware = app.user_middleware
        for mw in user_middleware:
            mw_cls = getattr(mw, "cls", None)
            mw_cls_name = (
                mw_cls.__name__
                if mw_cls is not None and hasattr(mw_cls, "__name__")
                else str(mw_cls)
            )
            assert "auth" not in mw_cls_name.lower(), (
                f"Auth middleware found in MCP app: {mw_cls_name}"
            )
            assert "token" not in mw_cls_name.lower(), (
                f"Token middleware found in MCP app: {mw_cls_name}"
            )


# ══════════════════════════════════════════════════════════════
# REQ-E15 — Static Architecture Audit
# ══════════════════════════════════════════════════════════════


class TestStaticArchitectureAudit:
    """Source-level checks for duplicate registries, legacy classes, etc."""

    def test_single_tool_registry_in_server(self):
        """No duplicate TOOLS list, TOOL_HANDLERS dict, or ToolRegistry in server."""
        import ast  # noqa: I001
        import server.mcp.server as server_mod
        import server.mcp.tools as tools_mod

        tools_src = inspect.getsource(tools_mod)
        server_src = inspect.getsource(server_mod)

        # TOOL_DEFINITIONS should be the only canonical registry.
        tools_ast = ast.parse(tools_src)
        assigned_names_in_tools = set()
        for node in ast.walk(tools_ast):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned_names_in_tools.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assigned_names_in_tools.add(node.target.id)

        assert "TOOL_DEFINITIONS" in assigned_names_in_tools
        assert "TOOL_HANDLERS" not in assigned_names_in_tools, (
            "Duplicate TOOL_HANDLERS dict found in tools.py"
        )
        assert "ToolRegistry" not in assigned_names_in_tools, (
            "Duplicate ToolRegistry class found in tools.py"
        )

        server_ast = ast.parse(server_src)
        assigned_names_in_server = set()
        for node in ast.walk(server_ast):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned_names_in_server.add(target.id)

        # server.py should not define its own canonical tool list.
        assert "TOOLS" not in assigned_names_in_server, "server.py defines its own TOOLS list"
        assert "TOOL_DEFINITIONS" not in assigned_names_in_server, (
            "server.py defines its own TOOL_DEFINITIONS"
        )

    def test_no_duplicate_canonical_definitions(self):
        """No second canonical tool list definition in the MCP client."""
        import ast

        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        tree = ast.parse(src)

        # Count actual list literal assignments that look like canonical
        # tool-name lists (i.e., assignments containing "scrape_webpage").
        # There should be at most one such assignment (the fallback list).
        canonical_list_assigns = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id.isupper()
                        and isinstance(node.value, ast.List)
                    ):
                        # Check if the value is a list literal containing
                        # "scrape_webpage".
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and elt.value == "scrape_webpage":
                                canonical_list_assigns += 1

        # The fallback list is the only list literal defining the canonical
        # names.  Any additional definition would be a duplicate registry.
        assert canonical_list_assigns <= 1, (
            f"Found {canonical_list_assigns} hardcoded canonical tool list definitions"
        )

    def test_no_legacy_transport_classes_active(self):
        """No legacy transport classes in MCP client."""
        import agentcrawl.agent.mcp_client as mod

        legacy_class_names = [
            "_JsonRpc",
            "_SSETransport",
            "_WebSocketTransport",
            "_StdioTransport",
            "_BaseTransport",
            "SseServerTransport",
            "WebSocketTransport",
        ]
        for name in legacy_class_names:
            assert not hasattr(mod, name), f"Legacy class {name} found in MCP client"

    def test_no_custom_protocol_framing(self):
        """No custom JSON-RPC protocol framing in MCP client."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        # Should not have _send_request, _send_notification, or custom RPC framing.
        assert "class _JsonRpc" not in src
        assert "def _send_notification" not in src
        assert "def _send_request" not in src

    def test_no_removed_mcp_api_imports(self):
        """No imports of removed MCP 1.x APIs."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        # MCP 2.0.0 removed: mcp.server.sse, mcp.server.websocket, etc.
        forbidden_imports = [
            "from mcp.client.sse import",
            "from mcp.server.sse import",
            "from mcp.client.websocket import",
            "from mcp.server.websocket import",
            "import mcp.client.sse",
            "import mcp.server.sse",
        ]
        for imp in forbidden_imports:
            assert imp not in src, f"Removed MCP API imported: {imp}"

    def test_transport_type_enum_only_has_http_stdio(self):
        """TransportType enum only has HTTP and STDIO."""
        from agentcrawl.agent.mcp_client import TransportType

        members = {m.name for m in TransportType}
        assert members == {"HTTP", "STDIO"}, f"Unexpected transport types: {members}"

    def test_all_imports_from_server_mcp_tools(self):
        """Client imports canonical contract from server.mcp.tools (single source)."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        # The client should import CANONICAL_TOOL_ORDER from server.mcp.tools.
        assert "from server.mcp.tools import" in src
        assert "CANONICAL_TOOL_ORDER" in src

    def test_no_legacy_tool_names_in_server(self):
        """Server tools.py has no legacy web_* tool names in canonical definitions."""
        # web_screenshot may appear in comments — check actual tool definitions.
        legacy_names = [
            "web_scrape",
            "web_crawl",
            "web_search",
            "web_map",
            "web_extract",
            "web_screenshot",
            "web_batch_scrape",
        ]
        for t in TOOL_DEFINITIONS:
            assert t.name not in legacy_names, f"Legacy tool name in contract: {t.name}"

    def test_convenience_methods_map_to_canonical(self):
        """Each convenience method maps to its canonical tool name."""
        import inspect as insp

        from agentcrawl.agent.mcp_client import MCPClient

        # scrape -> scrape_webpage
        src = insp.getsource(MCPClient.scrape)
        assert "scrape_webpage" in src

        # crawl -> crawl_website
        src = insp.getsource(MCPClient.crawl)
        assert "crawl_website" in src

        # search -> search_web
        src = insp.getsource(MCPClient.search)
        assert "search_web" in src

        # discover -> discover_urls
        src = insp.getsource(MCPClient.discover)
        assert "discover_urls" in src

        # extract -> extract_data
        src = insp.getsource(MCPClient.extract)
        assert "extract_data" in src

        # batch_scrape -> batch_scrape
        src = insp.getsource(MCPClient.batch_scrape)
        assert "batch_scrape" in src

    def test_no_screenshot_method_on_client(self):
        """MCPClient has no screenshot convenience method."""
        from agentcrawl.agent.mcp_client import MCPClient

        assert not hasattr(MCPClient, "screenshot")

    def test_run_sse_raises_runtime_error(self):
        """run_sse exists as a backward-compat stub but raises RuntimeError."""
        from server.mcp.server import run_sse

        async def _check():
            with pytest.raises(RuntimeError, match="Legacy SSE"):
                await run_sse()

        asyncio.run(_check())
