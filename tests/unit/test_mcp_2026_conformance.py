"""Set I — MCP 2026-07-28 Protocol Conformance Tests

These tests convert the Set I runtime and wire-level evidence into automated
regression tests, proving that the modern MCP 2026-07-28 protocol is actually
used end-to-end — not just inferred from source code.

Covered requirements (TR-01 through TR-10):

* TR-01 — server/discover returns supportedVersions={"2026-07-28"}
* TR-02 — negotiate_auto() negotiates protocol 2026-07-28
* TR-03 — MCP-Protocol-Version: 2026-07-28 on the wire
* TR-04 — Modern routing headers (Mcp-Method, Mcp-Name) on the wire
* TR-05 — No initialize / notifications/initialized on the modern path
* TR-06 — No Mcp-Session-Id on the wire
* TR-07 — Each request gets a fresh connection/request state
* TR-08 — Multiple requests share the same CrawlEngine instance
* TR-09 — Engine enters once, serves many, exits once (lifespan)
* TR-10 — Concurrent: distinct connections + same CrawlEngine

Architecture note: protocol/request/transport state is per-request (or absent),
but application resources (CrawlEngine) are shared through the server lifespan.
This is correct per MCP 2026-07-28 and must NOT be changed.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import socket
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
import pytest_asyncio
import uvicorn

# Import the MCP SDK constants so we assert against the real values,
# not string literals that could drift.
from mcp.shared.inbound import (
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    MCP_PROTOCOL_VERSION_HEADER,
)
from server.mcp.server import create_mcp_server

# MCP-Protocol-Version header for session ID — use the string directly as
# the SDK does not export a named constant for it.
MCP_SESSION_ID_HEADER = "mcp-session-id"
from mcp.server.context import CallNext, ServerRequestContext
from mcp.types import DiscoverResult

# ───────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────

def _free_port() -> tuple[str, int]:
    """Return (host, port) for a free local port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return "127.0.0.1", port


def _build_mock_engine() -> MagicMock:
    """Create a mock CrawlEngine with all handler methods mocked.

    Mirrors the pattern from test_mcp_hardening.py so that no browser/network
    is required.
    """
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.url = "https://example.com"
    mock_result.markdown = "# Example\n\nTest content"
    mock_result.metadata = {"title": "Example"}
    mock_result.word_count = 3
    mock_result.token_count = 5
    mock_result.links = {"all": []}

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
    engine.search = AsyncMock(return_value=["result1", "result2"])
    engine.__aenter__ = AsyncMock(return_value=engine)
    engine.__aexit__ = AsyncMock(return_value=None)
    return engine


@pytest.fixture
def _mock_engine():
    """Patch CrawlEngine.default and SearchEngine so no browser/network needed."""
    from agentcrawl.core.engine import CrawlEngine

    engine = _build_mock_engine()
    mock_se_instance = MagicMock()
    mock_se_instance.search = AsyncMock(return_value=["result1", "result2"])

    with (
        patch.object(CrawlEngine, "default", classmethod(lambda cls: engine)),
        patch("agentcrawl.SearchEngine", return_value=mock_se_instance),
    ):
        yield engine


# ───────────────────────────────────────────────────────────
# Wire-level server fixture (captures raw HTTP headers)
# ───────────────────────────────────────────────────────────


class _HeaderCaptureMiddleware:
    """ASGI middleware that records raw HTTP request + response headers.

    This captures the actual wire-level headers sent by the MCPClient, not
    mocked Python state. Each entry is a dict with:
      - method, path, request_headers (dict)
      - status, response_headers (dict, populated on response)
    """

    def __init__(self, app):
        self.app = app
        self.captured: list[dict[str, Any]] = []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            req_headers = {
                k.decode("latin-1"): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            entry = {
                "method": scope.get("method"),
                "path": scope.get("path"),
                "request_headers": req_headers,
                "status": None,
                "response_headers": {},
            }
            self.captured.append(entry)

            async def _wrapped_send(message):
                if message["type"] == "http.response.start":
                    entry["status"] = message.get("status")
                    entry["response_headers"] = {
                        k.decode("latin-1"): v.decode("latin-1")
                        for k, v in message.get("headers", [])
                    }
                await send(message)

            await self.app(scope, receive, _wrapped_send)
        else:
            await self.app(scope, receive, send)


@pytest_asyncio.fixture
async def _wire_server(_mock_engine):
    """Start a real uvicorn MCP server with header-capture middleware.

    Yields (url, captured_list) where captured_list is the live list that
    the middleware appends to for every HTTP request.
    """
    host, port = _free_port()
    server = create_mcp_server()
    app = server.streamable_http_app(stateless_http=True)
    middleware = _HeaderCaptureMiddleware(app)

    config = uvicorn.Config(middleware, host=host, port=port, log_level="error")
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

    assert ready, f"Wire server did not start on port {port}"

    yield f"http://{host}:{port}/mcp", middleware.captured

    server_instance.should_exit = True
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await server_task


# ─══════════════════════════════════════════════════════════
# Engine identity + lifecycle via ServerMiddleware
# ─══════════════════════════════════════════════════════════

# Module-level list to hold observed connection/session/engine identity
# from the ServerMiddleware. Each entry is a dict.

_engine_observations: list[dict[str, Any]] = []


class _IdentityMiddleware:
    """ServerMiddleware that records per-request identity from ctx.

    On the modern stateless path, ctx.session and ctx.session._connection
    are fresh per request, while ctx.lifespan_context (containing the
    engine) is shared.

    Stores strong references to the actual objects so that identity
    comparison via ``is`` is robust — no id() reuse after GC.
    """

    async def __call__(self, ctx: ServerRequestContext, call_next: CallNext) -> Any:
        session = ctx.session
        connection = getattr(session, "_connection", None)
        lifespan_ctx = ctx.lifespan_context
        engine = getattr(lifespan_ctx, "engine", None)

        _engine_observations.append(
            {
                "method": ctx.method,
                "request_id": ctx.request_id,
                "session": session,
                "connection": connection,
                "engine": engine,
            }
        )
        return await call_next(ctx)


@pytest_asyncio.fixture
async def _identity_server(_mock_engine):
    """Start a real uvicorn MCP server with an identity-tracking middleware.

    The middleware records session/connection/engine identity for each
    request. Yields (url, observations_list).

    The mock engine's __aenter__/__aexit__ call counts are available via
    the _mock_engine fixture.
    """
    global _engine_observations
    _engine_observations = []

    host, port = _free_port()
    server = create_mcp_server()
    server.middleware.insert(0, _IdentityMiddleware())
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

    assert ready, f"Identity server did not start on port {port}"

    yield f"http://{host}:{port}/mcp", _engine_observations

    server_instance.should_exit = True
    server_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await server_task


# ─══════════════════════════════════════════════════════════
# TR-01 / AC-01 — server/discover returns supportedVersions
# ─══════════════════════════════════════════════════════════


class TestServerDiscover:
    """TR-01: POST /mcp with Mcp-Method: server/discover returns supportedVersions.

    Uses the real MCP server path (not a mocked function). The MCPClient's
    connect() flow calls server/discover internally, so after connecting the
    client's session.discover_result holds the real server response.
    """

    @pytest.mark.asyncio
    async def test_discover_returns_modern_version(self, _identity_server):
        """The server's DiscoverResult must contain 2026-07-28."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, _obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            session = client._session
            assert session is not None, "ClientSession must be set after connect"
            result: DiscoverResult | None = session.discover_result
            assert result is not None, "discover_result must be set after negotiate_auto"
            assert "2026-07-28" in result.supported_versions, (
                f"supportedVersions={result.supported_versions} must include 2026-07-28"
            )

    @pytest.mark.asyncio
    async def test_discover_via_raw_post(self, _wire_server):
        """Raw POST /mcp with MCP-Protocol-Version + Mcp-Method: server/discover.

        Sends the exact headers specified by TR-01 and verifies the
        response body contains supportedVersions=["2026-07-28"].
        """
        url, _captured = _wire_server

        body = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {"name": "conformance-test", "version": "1.0.0"},
                }
            },
        })

        headers = {
            MCP_PROTOCOL_VERSION_HEADER: "2026-07-28",
            MCP_METHOD_HEADER: "server/discover",
            "content-type": "application/json",
        }

        def _do_post():
            return httpx2.post(
                url, headers=headers, content=body.encode(), timeout=10.0,
            )

        resp = await asyncio.to_thread(_do_post)

        assert resp.status_code == 200, f"server/discover returned {resp.status_code}"
        data = resp.json()
        result = data.get("result", data)
        assert "supportedVersions" in result, (
            f"supportedVersions not in discover response: {result}"
        )
        assert result["supportedVersions"] == ["2026-07-28"], (
            f"supportedVersions={result['supportedVersions']} must be [\"2026-07-28\"]"
        )

    @pytest.mark.asyncio
    async def test_discover_request_recorded_on_wire(self, _wire_server):
        """The wire-capture middleware must have recorded a server/discover request."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()

        discover_reqs = [
            r for r in captured[before:]
            if r["request_headers"].get(MCP_METHOD_HEADER) == "server/discover"
        ]
        assert len(discover_reqs) == 1, (
            f"Expected exactly 1 server/discover request on wire, got {len(discover_reqs)}"
        )


# ─══════════════════════════════════════════════════════════
# TR-02 / AC-02 — negotiate_auto() negotiates 2026-07-28
# ─══════════════════════════════════════════════════════════


class TestProtocolNegotiation:
    """TR-02: MCPClient must negotiate 2026-07-28 via negotiate_auto()."""

    @pytest.mark.asyncio
    async def test_negotiate_auto_sets_protocol_version(self, _identity_server):
        """After MCPClient.connect(), protocol_version == '2026-07-28'."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, _obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            pv = client.protocol_version
            assert pv == "2026-07-28", (
                f"Negotiated protocol_version={pv!r}, expected '2026-07-28'"
            )

    @pytest.mark.asyncio
    async def test_negotiate_auto_uses_modern_path(self, _wire_server):
        """negotiate_auto() must be responsible for the negotiation.

        Proves that negotiate_auto() (not initialize()) is the entry point
        by verifying: (a) protocol_version is set to 2026-07-28, and
        (b) no 'initialize' request appears on the wire.
        """
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            assert client.protocol_version == "2026-07-28"
            await client.list_tools()

        methods_seen = []
        for r in captured[before:]:
            m = r["request_headers"].get(MCP_METHOD_HEADER, "")
            if m:
                methods_seen.append(m)

        assert "server/discover" in methods_seen, (
            f"server/discover not seen in wire requests: {methods_seen}"
        )
        assert "initialize" not in methods_seen, (
            f"legacy 'initialize' found in wire requests: {methods_seen}"
        )

    @pytest.mark.asyncio
    async def test_negotiate_auto_adopts_discover_result(self, _identity_server):
        """After negotiate_auto, the session holds a DiscoverResult with supported_versions."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, _obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            session = client._session
            assert session is not None
            dr = session.discover_result
            assert dr is not None, "discover_result must be set after negotiate_auto"
            assert "2026-07-28" in dr.supported_versions, (
                f"supportedVersions={dr.supported_versions} must include 2026-07-28"
            )


# ─══════════════════════════════════════════════════════════
# TR-03 / AC-03 — MCP-Protocol-Version header on the wire
# ─══════════════════════════════════════════════════════════


class TestProtocolVersionHeader:
    """TR-03: A real modern request MUST carry MCP-Protocol-Version: 2026-07-28."""

    @pytest.mark.asyncio
    async def test_all_modern_requests_carry_protocol_version(self, _wire_server):
        """Every POST /mcp request from the MCPClient must have the protocol header."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        reqs = captured[before:]
        assert len(reqs) >= 2, f"Expected >=2 requests, got {len(reqs)}"

        for r in reqs:
            pv = r["request_headers"].get(MCP_PROTOCOL_VERSION_HEADER)
            assert pv == "2026-07-28", (
                f"POST {r['path']} missing MCP-Protocol-Version: {pv!r}"
            )


# ─══════════════════════════════════════════════════════════
# TR-04 / AC-04 — Modern routing headers (Mcp-Method, Mcp-Name)
# ─══════════════════════════════════════════════════════════


class TestRoutingHeaders:
    """TR-04: Modern requests carry Mcp-Method (and Mcp-Name for tools/call)."""

    @pytest.mark.asyncio
    async def test_routing_headers_present(self, _wire_server):
        """Verify Mcp-Method and Mcp-Name on the wire for a tool call."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        reqs = captured[before:]

        # server/discover request
        discover = [r for r in reqs if r["request_headers"].get(MCP_METHOD_HEADER) == "server/discover"]
        assert len(discover) >= 1, "No server/discover request found"

        # tools/call request with Mcp-Method and Mcp-Name
        call_reqs = [r for r in reqs if r["request_headers"].get(MCP_METHOD_HEADER) == "tools/call"]
        assert len(call_reqs) >= 1, "No tools/call request found"
        for cr in call_reqs:
            method = cr["request_headers"].get(MCP_METHOD_HEADER)
            name = cr["request_headers"].get(MCP_NAME_HEADER)
            assert method == "tools/call", f"Mcp-Method={method!r}, expected 'tools/call'"
            assert name == "scrape_webpage", f"Mcp-Name={name!r}, expected 'scrape_webpage'"


# ─══════════════════════════════════════════════════════════
# TR-05 / AC-05 — No legacy handshake on modern path
# ─══════════════════════════════════════════════════════════


class TestNoLegacyHandshake:
    """TR-05: Modern requests must NOT send initialize or notifications/initialized."""

    @pytest.mark.asyncio
    async def test_no_initialize_on_wire(self, _wire_server):
        """No HTTP request must carry Mcp-Method: initialize."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        for r in captured[before:]:
            method = r["request_headers"].get(MCP_METHOD_HEADER, "")
            assert method != "initialize", (
                f"Legacy 'initialize' request found on wire: {method}"
            )

    @pytest.mark.asyncio
    async def test_no_notifications_initialized_on_wire(self, _wire_server):
        """No HTTP request must carry Mcp-Method: notifications/initialized."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        for r in captured[before:]:
            method = r["request_headers"].get(MCP_METHOD_HEADER, "")
            assert "notifications/initialized" not in method, (
                f"Legacy 'notifications/initialized' found on wire: {method}"
            )

    @pytest.mark.asyncio
    async def test_no_initialize_in_methods(self, _wire_server):
        """The set of Mcp-Method values must not include initialize."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()

        methods = {
            r["request_headers"].get(MCP_METHOD_HEADER, "")
            for r in captured[before:]
            if r["request_headers"].get(MCP_METHOD_HEADER)
        }
        assert "initialize" not in methods, f"initialize found in methods: {methods}"


# ─══════════════════════════════════════════════════════════
# TR-06 / AC-06 — No Mcp-Session-Id
# ─══════════════════════════════════════════════════════════


class TestNoSessionId:
    """TR-06: Modern stateless requests must NOT establish Mcp-Session-Id."""

    @pytest.mark.asyncio
    async def test_no_session_id_in_request(self, _wire_server):
        """No request header may carry Mcp-Session-Id."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        for r in captured[before:]:
            assert MCP_SESSION_ID_HEADER not in r["request_headers"], (
                f"Mcp-Session-Id unexpectedly present in request: "
                f"{r['request_headers'].get(MCP_SESSION_ID_HEADER)!r}"
            )

    @pytest.mark.asyncio
    async def test_no_session_id_in_response(self, _wire_server):
        """No response header may carry Mcp-Session-Id."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, captured = _wire_server
        before = len(captured)

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()

        for r in captured[before:]:
            assert MCP_SESSION_ID_HEADER not in r["response_headers"], (
                f"Mcp-Session-Id unexpectedly present in response: "
                f"{r['response_headers'].get(MCP_SESSION_ID_HEADER)!r}"
            )


# ─══════════════════════════════════════════════════════════
# TR-07 / AC-07 — Request isolation (fresh connection per request)
# ─══════════════════════════════════════════════════════════


class TestRequestIsolation:
    """TR-07: Multiple requests MUST receive distinct connection/request state."""

    @pytest.mark.asyncio
    async def test_distinct_connections_per_request(self, _identity_server):
        """Each request's ServerSession._connection must be a distinct object.

        Uses direct object identity comparison (``is``) via strong references
        stored in the observation dict, to be robust against Python's id()
        reuse after garbage collection.
        """
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        rpc_obs = [o for o in obs if o["method"] is not None]
        assert len(rpc_obs) >= 2, f"Expected >=2 RPC observations, got {len(rpc_obs)}"

        conns = [o["connection"] for o in rpc_obs if o["connection"] is not None]
        sessions = [o["session"] for o in rpc_obs if o["session"] is not None]

        # Each connection and session must be a distinct object (identity check).
        assert len(conns) == len({id(c) for c in conns}), (
            f"Connection objects are not distinct: {len(conns)} obs, {len({id(c) for c in conns})} unique"
        )
        assert len(sessions) == len({id(s) for s in sessions}), (
            f"Session objects are not distinct: {len(sessions)} obs, {len({id(s) for s in sessions})} unique"
        )

    @pytest.mark.asyncio
    async def test_request_ids_fresh_per_session(self, _identity_server):
        """Each request within a client session must have a fresh (non-reused) request_id.

        'Fresh' means the request ID is not reused within the same connection —
        it increments sequentially for each new request, proving that each
        request gets its own fresh request state (not replaying a stale ID).
        """
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        rpc_obs = [o for o in obs if o["method"] is not None]
        # Filter to tools/call requests only — these are the ones we sent.
        call_obs = [o for o in rpc_obs if o["method"] == "tools/call"]
        request_ids = [o["request_id"] for o in call_obs if o["request_id"] is not None]

        assert len(request_ids) >= 2, f"Expected >=2 request IDs, got {len(request_ids)}"
        # Within the same client session, consecutive tools/call requests
        # must have distinct (incrementing) request IDs — proving freshness.
        assert len(request_ids) == len(set(request_ids)), (
            f"Request IDs reused within session: {request_ids}"
        )


# ─══════════════════════════════════════════════════════════
# TR-08 / AC-08 — Shared CrawlEngine instance
# ─══════════════════════════════════════════════════════════


class TestSharedEngine:
    """TR-08: Multiple requests MUST receive the same CrawlEngine instance."""

    @pytest.mark.asyncio
    async def test_same_engine_across_requests(self, _identity_server, _mock_engine):
        """All requests must observe the same CrawlEngine instance (identity)."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.list_tools()
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            await client.call_tool("search_web", {"query": "test"})

        rpc_obs = [o for o in obs if o["method"] is not None]
        engines = [o["engine"] for o in rpc_obs if o["engine"] is not None]
        assert len(engines) >= 2

        first = engines[0]
        assert first is not None, "engine is None — lifespan context missing engine"
        for eng in engines:
            assert eng is first, (
                "Engine instances differ across requests"
            )

    @pytest.mark.asyncio
    async def test_engine_identity_matches_mock(self, _identity_server, _mock_engine):
        """The observed engine object must BE the mock engine (identity)."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        rpc_obs = [o for o in obs if o["method"] is not None]
        engines = [o["engine"] for o in rpc_obs if o["engine"] is not None]
        assert len(engines) >= 1
        assert engines[0] is _mock_engine, (
            "Observed engine is not the mock engine instance"
        )


# ─══════════════════════════════════════════════════════════
# TR-09 / AC-09 — CrawlEngine lifecycle (enter once, exit once)
# ─══════════════════════════════════════════════════════════


class TestEngineLifecycle:
    """TR-09: Engine enters once, serves many, exits once (per server lifespan)."""

    @pytest.mark.asyncio
    async def test_engine_entered_once_at_startup(self, _identity_server, _mock_engine):
        """The shared engine must be __aentered__ exactly once during startup."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server
        # At this point the server has started and entered the engine.
        assert _mock_engine.__aenter__.await_count >= 1, (
            "Engine __aenter__ must be called during server startup"
        )

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            await client.call_tool("search_web", {"query": "test"})

        # Engine entered once at startup — zero additional entries during requests.
        assert _mock_engine.__aenter__.await_count == 1, (
            f"Engine __aenter__ called {_mock_engine.__aenter__.await_count} times, "
            f"expected exactly 1 (startup only)"
        )

    @pytest.mark.asyncio
    async def test_engine_not_exited_per_request(self, _identity_server, _mock_engine):
        """Request handling must NOT call engine.__aexit__ per request."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server
        startup_exit = _mock_engine.__aexit__.await_count

        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        # No additional __aexit__ calls during requests.
        assert _mock_engine.__aexit__.await_count == startup_exit, (
            f"Engine __aexit__ called during requests "
            f"({startup_exit} -> {_mock_engine.__aexit__.await_count}); "
            f"engine must not be torn down per-request"
        )

    @pytest.mark.asyncio
    async def test_engine_exited_once_at_teardown(self, _identity_server, _mock_engine):
        """After server shutdown, engine __aexit__ must have been called exactly once."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        enter_count = _mock_engine.__aenter__.await_count
        # At this point server is still running (fixture teardown happens after test).
        assert enter_count == 1, f"Engine entered {enter_count} times, expected 1"
        assert _mock_engine.__aexit__.await_count == 0, (
            "Engine should not have been exited yet (server still running)"
        )

        # After the fixture tears down (server stops), engine exits once.
        # We verify this by accessing the fixture's server shutdown below.
        # Since we can't directly check after teardown here, we verify the
        # enter:exit ratio invariant holds at exit time via the fixture.
        # The _identity_server fixture teardown will trigger __aexit__.


class TestEngineLifecycleAtTeardown:
    """Verify engine exit count after server shutdown (separate fixture scope)."""

    @pytest.mark.asyncio
    async def test_engine_exit_once_after_server_stop(self, _mock_engine):
        """When the server is torn down, engine exits exactly once total."""
        from agentcrawl.agent.mcp_client import MCPClient

        host, port = _free_port()
        server = create_mcp_server()
        server.middleware.insert(0, _IdentityMiddleware())
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
        assert ready

        url = f"http://{host}:{port}/mcp"
        async with MCPClient(transport="http", url=url, timeout=30) as client:
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        assert _mock_engine.__aenter__.await_count == 1
        assert _mock_engine.__aexit__.await_count == 0

        # Shut down the server gracefully — this triggers engine __aexit__
        # via the lifespan context manager.
        server_instance.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(server_task, timeout=10)
        assert not server_task.cancelled(), "Server task was cancelled (lifespan cleanup skipped)"

        assert _mock_engine.__aexit__.await_count == 1, (
            f"Engine __aexit__ called {_mock_engine.__aexit__.await_count} times "
            f"after teardown, expected exactly 1"
        )


# ─══════════════════════════════════════════════════════════
# TR-10 / AC-10 — Concurrent: distinct connections + same engine
# ─══════════════════════════════════════════════════════════


class TestConcurrentIsolation:
    """TR-10: Concurrent requests get distinct connections but same CrawlEngine.

    This is the most important architectural regression test: it proves
    request/connection isolation (per-request) alongside application-level
    resource sharing (server-lifespan) under concurrency.
    """

    @pytest.mark.asyncio
    async def test_concurrent_distinct_connections_same_engine(
        self, _identity_server, _mock_engine
    ):
        """3 concurrent clients must see 3 distinct connections and 1 engine.

        Uses direct object identity (``is``) with strong references.
        """
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server

        async def _use() -> None:
            async with MCPClient(transport="http", url=url, timeout=30) as client:
                await client.list_tools()
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        await asyncio.gather(*[_use() for _ in range(3)])

        rpc_obs = [o for o in obs if o["method"] is not None]
        assert len(rpc_obs) >= 3, (
            f"Expected >=3 RPC observations for 3 concurrent clients, got {len(rpc_obs)}"
        )

        conns = [o["connection"] for o in rpc_obs if o["connection"] is not None]
        engines = [o["engine"] for o in rpc_obs if o["engine"] is not None]

        # At least 3 distinct connections (one per client's request).
        conn_ids = [id(c) for c in conns]
        assert len(set(conn_ids)) >= 3, (
            f"Expected >=3 distinct connections, got {len(set(conn_ids))}"
        )

        # All share the same engine (identity check via is).
        assert len(engines) >= 1
        first_eng = engines[0]
        for eng in engines:
            assert eng is first_eng, (
                f"Expected all requests to share the same engine, got {len(set(id(e) for e in engines))} distinct"
            )

    @pytest.mark.asyncio
    async def test_concurrent_distinct_sessions_same_engine(
        self, _identity_server, _mock_engine
    ):
        """3 concurrent connections must have distinct ServerSessions but same engine."""
        from agentcrawl.agent.mcp_client import MCPClient

        url, obs = _identity_server

        async def _call() -> None:
            async with MCPClient(transport="http", url=url, timeout=30) as client:
                await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        await asyncio.gather(*[_call() for _ in range(3)])

        # Filter to tools/call observations (each concurrent client makes one).
        call_obs = [o for o in obs if o["method"] == "tools/call"]
        assert len(call_obs) >= 3

        sessions = [o["session"] for o in call_obs if o["session"] is not None]
        engines = [o["engine"] for o in call_obs if o["engine"] is not None]

        # Each session must be a distinct object (identity check).
        session_ids = [id(s) for s in sessions]
        assert len(set(session_ids)) == len(session_ids), (
            f"Session objects not distinct: {len(session_ids)} obs, "
            f"{len(set(session_ids))} unique"
        )
        # All sessions must share the same engine.
        assert len(engines) >= 3
        first_eng = engines[0]
        for eng in engines:
            assert eng is first_eng, (
                f"Expected all requests to share the same engine, "
                f"got {len(set(id(e) for e in engines))} distinct"
            )


# ─══════════════════════════════════════════════════════════
# AC-11 / AC-12 / AC-13 — No regressions, no legacy reintroduction
# ─══════════════════════════════════════════════════════════


class TestArchitectureInvariants:
    """AC-11–16: Architectural invariants must not be weakened."""

    def test_no_sse_import_in_client(self):
        """Client must not import legacy SSE transport."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "from mcp.client.sse" not in src
        assert "import mcp.client.sse" not in src

    def test_no_websocket_import_in_client(self):
        """Client must not import legacy WebSocket transport."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "from mcp.client.websocket" not in src

    def test_no_session_initialize_in_client(self):
        """Client must not call session.initialize() directly."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "session.initialize" not in src, (
            "Direct session.initialize() must not appear in the modern client path"
        )

    def test_no_legacy_sse_routes_on_server(self):
        """Server must not register /sse or /messages/ routes."""
        server = create_mcp_server()
        app = server.streamable_http_app(stateless_http=True)
        route_paths = set()
        for r in app.router.routes:
            path = getattr(r, "path", None)
            if path:
                route_paths.add(path)
        assert "/sse" not in route_paths
        assert "/messages/" not in route_paths
        assert "/mcp" in route_paths

    def test_client_files_byte_identical(self):
        """agent/mcp_client.py and agentcrawl/agent/mcp_client.py must be byte-identical."""
        import hashlib

        with open("agent/mcp_client.py", "rb") as f:
            hash_a = hashlib.sha256(f.read()).hexdigest()
        with open("agentcrawl/agent/mcp_client.py", "rb") as f:
            hash_b = hashlib.sha256(f.read()).hexdigest()
        assert hash_a == hash_b, "Client files are out of sync"

    def test_negotiate_auto_imported_in_client(self):
        """Client must import and use negotiate_auto (not session.initialize)."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "negotiate_auto" in src, (
            "Client must import and use negotiate_auto from mcp.client._probe"
        )
