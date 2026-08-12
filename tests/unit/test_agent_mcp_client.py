"""Tests for agentcrawl.agent.mcp_client (Set C migrated client).

These tests verify the MCP SDK 2.0.0 client migration:

* Construction & transport wiring
* Connection lifecycle (connect, disconnect, cleanup)
* Tool discovery (tools/list → exactly 6 canonical tools)
* Tool execution (tools/call for every canonical tool)
* Negative cases (unknown tool, invalid args, errors, timeouts)
* Compatibility (no legacy SSE/WebSocket/JSON-RPC, no web_screenshot)
* Server interoperability (client → Streamable HTTP → real MCP server)

No live external websites are used — the server-side handlers are mocked
for unit tests and a local uvicorn server is used for integration tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agentcrawl.agent.mcp_client import (
    CANONICAL_TOOL_ORDER,
    TOOL_NAMES,
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPServerInfo,
    MCPTimeoutError,
    MCPToolError,
    MCPToolInfo,
    MCPToolResult,
    TransportType,
    _content_to_dict,
    _extract_error_text,
    _result_to_dict,
    create_http_client,
    create_sse_client,
    create_stdio_client,
    create_websocket_client,
)

# ─────────────────────────────────────────────────────────────
# Canonical tool names
# ─────────────────────────────────────────────────────────────

EXPECTED_CANONICAL_NAMES = [
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


# ─────────────────────────────────────────────────────────────
# Mock session helper for connect() tests (Set H: negotiate_auto)
# ─────────────────────────────────────────────────────────────

_MODERN_PROTOCOL_VERSION = "2026-07-28"


def _make_mock_session(protocol_version: str = _MODERN_PROTOCOL_VERSION):
    """Build a MagicMock that mimics a ClientSession after ``negotiate_auto``.

    After ``negotiate_auto(session)`` the SDK session has:
      * ``protocol_version`` — the negotiated era (default ``2026-07-28``)
      * ``server_info`` — ServerInfo or None
      * ``server_capabilities`` — dict or ServerCapabilities
      * ``_discover_result`` / ``_initialize_result`` — internal slots
    """
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    # negotiate_auto() is called as ``negotiate_auto(session)``; the function
    # inspects session._discover_result / _initialize_result and calls adopt().
    # In production negotiate_auto sends a server/discover probe and then
    # calls session.adopt().  We mock it to set up the session as if adopt()
    # succeeded with the modern era.
    mock_server_info = MagicMock()
    mock_server_info.name = "agentcrawl"
    mock_server_info.version = "1.0.0"

    # Configure the session properties that connect() reads after negotiate_auto.
    type(mock_session).protocol_version = _MODERN_PROTOCOL_VERSION
    mock_session.server_info = mock_server_info
    mock_session.server_capabilities = {}
    mock_session._discover_result = MagicMock()
    mock_session._initialize_result = None

    # Patch negotiate_auto to be an AsyncMock that does nothing (the session
    # is already preset as if adopt() ran successfully).
    async def _fake_negotiate_auto(session):
        # Simulate the adopt() side-effects that negotiate_auto performs.
        pass

    return mock_session, _fake_negotiate_auto


# ══════════════════════════════════════════════════════════════
# TransportType
# ══════════════════════════════════════════════════════════════


class TestTransportType:
    """Tests for TransportType enum."""

    def test_http(self):
        assert TransportType.HTTP.value == "http"

    def test_stdio(self):
        assert TransportType.STDIO.value == "stdio"

    def test_no_sse_or_websocket(self):
        """SSE and WebSocket must not be separate transports."""
        for removed in ("SSE", "WEBSOCKET"):
            assert not hasattr(TransportType, removed), f"TransportType.{removed} still exists"

    def test_legacy_sse_alias_maps_to_http(self):
        """``sse`` is accepted as a backward-compat alias for Streamable HTTP."""
        assert TransportType("sse") == TransportType.HTTP

    def test_legacy_websocket_alias_maps_to_http(self):
        assert TransportType("websocket") == TransportType.HTTP

    def test_streamable_http_alias(self):
        assert TransportType("streamable_http") == TransportType.HTTP

    def test_invalid_transport(self):
        with pytest.raises(ValueError):
            TransportType("invalid")


# ══════════════════════════════════════════════════════════════
# Exception hierarchy
# ══════════════════════════════════════════════════════════════


class TestExceptions:
    """Tests for MCP exception hierarchy."""

    def test_mcp_error_basic(self):
        err = MCPError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.code is None
        assert err.data is None

    def test_mcp_error_with_code(self):
        err = MCPError("Bad request", code=-32600, data={"detail": "x"})
        assert err.code == -32600
        assert err.data == {"detail": "x"}

    def test_mcp_error_is_exception(self):
        assert isinstance(MCPError("test"), Exception)

    def test_connection_error_is_mcp_error(self):
        assert isinstance(MCPConnectionError("fail"), MCPError)

    def test_tool_error_is_mcp_error(self):
        assert isinstance(MCPToolError("fail"), MCPError)

    def test_timeout_error_is_mcp_error(self):
        assert isinstance(MCPTimeoutError("fail"), MCPError)


# ══════════════════════════════════════════════════════════════
# Canonical contract
# ══════════════════════════════════════════════════════════════


class TestCanonicalContract:
    """Verify the client exposes exactly the canonical six-tool contract."""

    def test_canonical_tool_order(self):
        assert CANONICAL_TOOL_ORDER == EXPECTED_CANONICAL_NAMES

    def test_tool_names_alias(self):
        assert TOOL_NAMES == EXPECTED_CANONICAL_NAMES

    def test_no_legacy_names_in_contract(self):
        for legacy in LEGACY_NAMES:
            assert legacy not in CANONICAL_TOOL_ORDER, f"{legacy} should not be in canonical order"
            assert legacy not in TOOL_NAMES

    def test_no_web_screenshot(self):
        assert "web_screenshot" not in CANONICAL_TOOL_ORDER
        assert "web_screenshot" not in TOOL_NAMES

    def test_six_tools(self):
        assert len(CANONICAL_TOOL_ORDER) == 6


# ══════════════════════════════════════════════════════════════
# No legacy internals
# ══════════════════════════════════════════════════════════════


class TestNoLegacyInternals:
    """Verify legacy custom transport/JSON-RPC code has been removed."""

    def test_no_json_rpc_class(self):
        """``_JsonRpc`` must not exist on the active client path."""
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_JsonRpc"), "_JsonRpc still exists"

    def test_no_sse_transport_class(self):
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_SSETransport"), "_SSETransport still exists"

    def test_no_websocket_transport_class(self):
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_WebSocketTransport"), "_WebSocketTransport still exists"

    def test_no_stdio_transport_class(self):
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_StdioTransport"), "_StdioTransport still exists"

    def test_no_base_transport_class(self):
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "_BaseTransport"), "_BaseTransport still exists"

    def test_no_hardcoded_protocol_version(self):
        """No active client code should hardcode the 2024-11-05 protocol version."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        # The string "2024-11-05" must not appear as a protocol version
        # assignment in the active code.
        assert "2024-11-05" not in src, "Hardcoded protocol version 2024-11-05 found"


# ══════════════════════════════════════════════════════════════
# MCPClient construction
# ══════════════════════════════════════════════════════════════


class TestMCPClientConstruction:
    """Tests for MCPClient.__init__."""

    def test_defaults(self):
        client = MCPClient()
        assert client._transport_type == TransportType.HTTP
        assert client._url == "http://localhost:8080/mcp"
        assert client._timeout == 60.0
        assert client._api_key is None
        assert client.is_connected is False
        assert client.server_info is None

    def test_http_transport_url(self):
        client = MCPClient(transport="http", url="http://localhost:9000/mcp")
        assert client._transport_type == TransportType.HTTP
        assert client._url == "http://localhost:9000/mcp"

    def test_stdio_transport(self):
        client = MCPClient(transport="stdio", command="python", args=["-m", "server.mcp.server"])
        assert client._transport_type == TransportType.STDIO
        assert client._command == "python"
        assert client._args == ["-m", "server.mcp.server"]

    def test_legacy_sse_alias(self):
        client = MCPClient(transport="sse", url="http://localhost:9000/mcp")
        assert client._transport_type == TransportType.HTTP

    def test_legacy_websocket_alias(self):
        client = MCPClient(transport="websocket", url="ws://localhost:9000/ws")
        assert client._transport_type == TransportType.HTTP

    def test_api_key_sets_auth_header(self):
        client = MCPClient(api_key="secret123")
        assert client._headers["Authorization"] == "Bearer secret123"

    def test_custom_headers(self):
        client = MCPClient(headers={"X-Custom": "value"})
        assert client._headers["X-Custom"] == "value"

    def test_custom_timeout(self):
        client = MCPClient(timeout=120.0)
        assert client._timeout == 120.0

    def test_args_defaults(self):
        client = MCPClient(transport="stdio", command="python")
        assert client._args == ["-m", "server.mcp.server"]

    def test_no_screenshot_method(self):
        """The ``screenshot`` convenience method must not exist."""
        assert not hasattr(MCPClient, "screenshot")

    def test_no_map_site_method(self):
        """The legacy ``map_site`` method is replaced by ``discover``."""
        assert not hasattr(MCPClient, "map_site")

    def test_repr_disconnected(self):
        client = MCPClient(transport="http", url="http://localhost:9000/mcp")
        assert "disconnected" in repr(client)
        assert "http" in repr(client)

    def test_repr_connected(self):
        client = MCPClient(transport="http", url="http://localhost:9000/mcp")
        client._connected = True
        client._session = MagicMock()
        assert "connected" in repr(client)

    def test_is_connected_transport_down(self):
        client = MCPClient()
        client._connected = True
        client._session = None
        assert client.is_connected is False

    def test_is_connected_both_true(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()
        assert client.is_connected is True

    def test_server_info_none_before_connect(self):
        client = MCPClient()
        assert client.server_info is None


# ══════════════════════════════════════════════════════════════
# Content / result helpers
# ══════════════════════════════════════════════════════════════


class TestContentHelpers:
    """Tests for _content_to_dict, _extract_error_text, _result_to_dict."""

    def test_content_to_dict_from_dict(self):
        d = {"type": "text", "text": "hello"}
        assert _content_to_dict(d) == d

    def test_content_to_dict_from_object(self):
        class FakeContent:
            type = "text"

            def model_dump(self):
                return {"text": "hello"}

            # model_dump does not include "type"

        content = FakeContent()
        result = _content_to_dict(content)
        assert result["type"] == "text"
        assert result["text"] == "hello"

    def test_content_to_dict_fallback(self):
        result = _content_to_dict("plain string")
        assert result == {"type": "text", "text": "plain string"}

    def test_extract_error_text_finds_text(self):
        result = MagicMock()
        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {"type": "text", "text": "tool failed"}
        result.content = [content]
        assert _extract_error_text(result) == "tool failed"

    def test_extract_error_text_defaults(self):
        result = MagicMock()
        result.content = []
        assert _extract_error_text(result) == "Unknown tool error"

    def test_result_to_dict_with_model_dump(self):
        class FakeResult:
            def model_dump(self):
                return {"is_error": False, "content": []}

        result = _result_to_dict(FakeResult())
        assert result["is_error"] is False
        assert result["isError"] is False

    def test_result_to_dict_no_model_dump(self):
        obj = MagicMock()
        del obj.model_dump
        obj.__dict__ = {"custom": "data"}
        result = _result_to_dict(obj)
        assert result == {"custom": "data"}


# ══════════════════════════════════════════════════════════════
# MCPClient lifecycle (mocked SDK session)
# ══════════════════════════════════════════════════════════════


class TestMCPClientConnect:
    """Tests for MCPClient.connect / disconnect with mocked SDK session."""

    @pytest.mark.asyncio
    async def test_connect_http(self):
        """Client connects via Streamable HTTP using negotiate_auto (modern era)."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")

        mock_session, fake_negotiate = _make_mock_session()

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=fake_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            info = await client.connect()

        assert client.is_connected is True
        assert info.name == "agentcrawl"
        assert info.version == "1.0.0"
        assert info.protocol_version == _MODERN_PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_connect_stdio(self):
        """Client connects via stdio using negotiate_auto (modern era)."""
        client = MCPClient(transport="stdio", command="python", args=["-m", "server.mcp.server"])

        mock_session, fake_negotiate = _make_mock_session()

        with (
            patch("agentcrawl.agent.mcp_client.stdio_client") as mock_sc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=fake_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_sc.return_value = mock_cm

            info = await client.connect()

        assert client.is_connected is True
        assert info.name == "agentcrawl"

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Connection failure is wrapped in MCPConnectionError."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")

        with (
            patch(
                "agentcrawl.agent.mcp_client.streamable_http_client", side_effect=OSError("refused")
            ),
            pytest.raises(MCPConnectionError, match="refused"),
        ):
            await client.connect()

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Connection timeout raises MCPTimeoutError."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp", timeout=0.001)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.protocol_version = ""
        mock_session.server_info = MagicMock()
        mock_session.server_info.name = "agentcrawl"
        mock_session.server_info.version = "1.0.0"
        mock_session.server_capabilities = {}
        mock_session._discover_result = None
        mock_session._initialize_result = None

        async def slow_negotiate(session):
            await asyncio.sleep(10)

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", side_effect=slow_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            with pytest.raises(MCPTimeoutError, match="timed out"):
                await client.connect()

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_disconnect_cleans_resources(self):
        """Disconnect tears down session, transport, and caches."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")
        client._connected = True
        session_mock = MagicMock()
        session_mock.__aexit__ = AsyncMock(return_value=None)
        client._session = session_mock
        transport_cm = MagicMock()
        transport_cm.__aexit__ = AsyncMock(return_value=None)
        client._transport_cm = transport_cm
        client._server_info = MCPServerInfo(name="test", version="1.0")
        client._tools_cache = [MCPToolInfo(name="test", description="d", input_schema={})]

        await client.disconnect()

        assert client.is_connected is False
        assert client._session is None
        assert client._transport_cm is None
        assert client._tools_cache is None
        assert client._server_info is None
        session_mock.__aexit__.assert_awaited_once()
        transport_cm.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """``async with`` connects and disconnects cleanly."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")

        mock_session, fake_negotiate = _make_mock_session()

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=fake_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            async with client:
                assert client.is_connected is True

        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self):
        """Disconnect on an already-disconnected client is a no-op."""
        client = MCPClient()
        client._connected = False
        client._session = None
        client._transport_cm = None
        # Should not raise
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_internal_cancellation_translated(self):
        """A CancelledError from the MCP SDK's anyio task-group (e.g. when
        the Streamable HTTP transport fails with a connection refused) must
        be translated to MCPConnectionError, not propagated as
        asyncio.CancelledError.
        """
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")

        mock_session, _fake_negotiate = _make_mock_session()

        async def _fake_negotiate_auto(session):
            # Simulate the anyio cancel-scope cancellation that the SDK
            # raises when the transport fails.
            raise asyncio.CancelledError("Cancelled via cancel scope 0xdeadbeef")

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=_fake_negotiate_auto),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            with pytest.raises(MCPConnectionError, match="Failed to connect"):
                await client.connect()

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_connect_external_cancel_not_swallowed(self):
        """External task cancellation must propagate as CancelledError,
        not be converted to MCPConnectionError.

        GIVEN connect() is blocked after mocks are patched
        WHEN the caller invokes task.cancel() (empty reason)
        THEN connect() must propagate CancelledError
        AND must not convert it to MCPConnectionError.
        AND cleanup must leave the client disconnected (is_connected=False,
        _session=None).
        """
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")
        mock_session, _fake_negotiate = _make_mock_session()

        async def _slow_negotiate(session):
            await asyncio.sleep(10)

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=_slow_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            task = asyncio.current_task()
            assert task is not None
            task.cancel()
            try:
                await client.connect()
            except asyncio.CancelledError:
                pass  # expected
            else:
                pytest.fail("Expected CancelledError from external cancellation")

        # Cleanup must still leave the client in a clean, disconnected state.
        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_connect_external_cancel_with_message_not_swallowed(self):
        """External task cancellation WITH a reason must propagate as
        CancelledError, not be converted to MCPConnectionError.

        Python permits ``task.cancel("reason")`` which produces a
        ``CancelledError`` carrying a non-empty message.  This is still
        EXTERNAL cancellation and must reach the caller unmodified.

        This guards against the previous ``not str(err)`` heuristic that
        misclassified any non-empty-message CancelledError as internal.
        """
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")
        mock_session, _fake_negotiate = _make_mock_session()

        async def _slow_negotiate(session):
            await asyncio.sleep(10)

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=_slow_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            task = asyncio.current_task()
            assert task is not None
            task.cancel("connection torn down by caller")
            try:
                await client.connect()
            except asyncio.CancelledError:
                pass  # expected — external cancellation must propagate
            else:
                pytest.fail("Expected CancelledError from external cancellation with reason")

        # Cleanup must still leave the client in a clean, disconnected state.
        assert client.is_connected is False
        assert client._session is None


# ══════════════════════════════════════════════════════════════
# Set H — Protocol negotiation & architecture tests
# ══════════════════════════════════════════════════════════════


class TestSetHProtocolNegotiation:
    """H2 — Verify the client uses negotiate_auto (mode='auto') for the
    modern MCP 2.0.0 protocol path, not a direct initialize() call."""

    @pytest.mark.asyncio
    async def test_connect_uses_negotiate_auto(self):
        """connect() must call negotiate_auto, not session.initialize()."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")
        mock_session, _ = _make_mock_session()

        negotiate_called = []

        async def tracking_negotiate(session):
            negotiate_called.append(session)

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", side_effect=tracking_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            await client.connect()

        assert len(negotiate_called) == 1, "negotiate_auto must be called exactly once"
        assert negotiate_called[0] is mock_session

    @pytest.mark.asyncio
    async def test_connect_does_not_call_initialize_directly(self):
        """The client must NOT call session.initialize() — that is the legacy
        handshake path that locks to 2025-11-25."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")
        mock_session, fake_negotiate = _make_mock_session()

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=fake_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            await client.connect()

        # initialize must NOT be called — it's the legacy 2025-11-25 path.
        assert not getattr(mock_session.initialize, "called", False), (
            "session.initialize() must not be called; use negotiate_auto"
        )

    @pytest.mark.asyncio
    async def test_connect_reports_modern_protocol_version(self):
        """After connect, protocol_version must be 2026-07-28 (modern era)."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")
        mock_session, fake_negotiate = _make_mock_session()

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=fake_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            await client.connect()

        assert client.protocol_version == _MODERN_PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_protocol_version_none_before_connect(self):
        """protocol_version is None before connect."""
        client = MCPClient()
        assert client.protocol_version is None

    @pytest.mark.asyncio
    async def test_protocol_version_none_after_disconnect(self):
        """protocol_version is None after disconnect."""
        client = MCPClient()
        mock_session, fake_negotiate = _make_mock_session()

        with (
            patch("agentcrawl.agent.mcp_client.streamable_http_client") as mock_shc,
            patch("agentcrawl.agent.mcp_client.ClientSession", return_value=mock_session),
            patch("agentcrawl.agent.mcp_client.negotiate_auto", new=fake_negotiate),
        ):
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_shc.return_value = mock_cm

            await client.connect()
            assert client.protocol_version == _MODERN_PROTOCOL_VERSION
            await client.disconnect()
            assert client.protocol_version is None

    def test_no_direct_initialize_call_in_source(self):
        """The active client source must not call self._session.initialize()."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "self._session.initialize()" not in src, (
            "Client must use negotiate_auto, not session.initialize()"
        )
        assert "negotiate_auto" in src


class TestSetHProtocolNegotiationInterop:
    """H2 — Integration test: connect to a real server and verify the
    negotiated protocol version is the modern 2026-07-28 era."""

    @pytest.mark.asyncio
    async def test_interop_negotiates_modern_protocol(
        self,
        _mcp_server,
        _mock_crawl_engine,
    ):
        """Client → Streamable HTTP → real server; protocol_version must be
        2026-07-28 after auto-negotiation."""
        server_url = _mcp_server
        async with MCPClient(transport="http", url=server_url) as client:
            assert client.protocol_version == _MODERN_PROTOCOL_VERSION
            assert client.is_connected is True


# ══════════════════════════════════════════════════════════════
# MCPClient.list_tools (mocked session)
# ══════════════════════════════════════════════════════════════


class TestListTools:
    """Tests for list_tools."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_canonical(self):
        """list_tools returns the six canonical tools from the server."""
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        tools = []
        for name in EXPECTED_CANONICAL_NAMES:
            t = MagicMock()
            t.name = name
            t.description = f"desc for {name}"
            t.input_schema = {"type": "object", "properties": {}, "required": []}
            tools.append(t)

        result = MagicMock()
        result.tools = tools
        client._session.list_tools = AsyncMock(return_value=result)

        listed = await client.list_tools()
        assert len(listed) == 6
        assert [t.name for t in listed] == EXPECTED_CANONICAL_NAMES

    @pytest.mark.asyncio
    async def test_list_tools_caches(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        t = MagicMock()
        t.name = "scrape_webpage"
        t.description = "desc"
        t.input_schema = {"type": "object"}
        result = MagicMock()
        result.tools = [t]
        client._session.list_tools = AsyncMock(return_value=result)

        first = await client.list_tools()
        second = await client.list_tools()
        assert first is second  # cached
        client._session.list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_tools_not_connected(self):
        client = MCPClient()
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await client.list_tools()

    @pytest.mark.asyncio
    async def test_list_tools_empty(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.tools = []
        client._session.list_tools = AsyncMock(return_value=result)

        listed = await client.list_tools()
        assert listed == []

    def test_get_tool_names_empty(self):
        client = MCPClient()
        assert client.get_tool_names() == []

    def test_get_tool_names_cached(self):
        client = MCPClient()
        client._tools_cache = [
            MCPToolInfo(name="scrape_webpage", description="d", input_schema={}),
            MCPToolInfo(name="search_web", description="d", input_schema={}),
        ]
        assert client.get_tool_names() == ["scrape_webpage", "search_web"]


# ══════════════════════════════════════════════════════════════
# MCPClient.call_tool (mocked session)
# ══════════════════════════════════════════════════════════════


class TestCallTool:
    """Tests for call_tool."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        client = MCPClient(timeout=30.0)
        client._connected = True
        client._session = MagicMock()

        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {"type": "text", "text": "Hello"}

        result = MagicMock()
        result.is_error = False
        result.content = [content]
        result.model_dump.return_value = {
            "is_error": False,
            "content": [{"type": "text", "text": "Hello"}],
        }
        client._session.call_tool = AsyncMock(return_value=result)

        tool_result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        assert isinstance(tool_result, MCPToolResult)
        assert tool_result.text == "Hello"
        assert tool_result.is_error is False

    @pytest.mark.asyncio
    async def test_call_tool_error(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {"type": "text", "text": "Tool failed"}

        result = MagicMock()
        result.is_error = True
        result.content = [content]
        client._session.call_tool = AsyncMock(return_value=result)

        with pytest.raises(MCPToolError, match="returned error"):
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

    @pytest.mark.asyncio
    async def test_call_tool_timeout(self):
        client = MCPClient(timeout=0.001)
        client._connected = True
        client._session = MagicMock()

        async def hanging(name, arguments):
            await asyncio.sleep(10)

        client._session.call_tool = hanging

        with pytest.raises(MCPTimeoutError, match="timed out"):
            await client.call_tool("scrape_webpage", {"url": "x"})

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self):
        client = MCPClient()
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await client.call_tool("scrape_webpage", {"url": "x"})

    @pytest.mark.asyncio
    async def test_call_tool_empty_arguments(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {"type": "text", "text": "OK"}

        result = MagicMock()
        result.is_error = False
        result.content = [content]
        client._session.call_tool = AsyncMock(return_value=result)

        tool_result = await client.call_tool("discover_urls", None)
        assert tool_result.text == "OK"

    @pytest.mark.asyncio
    async def test_call_tool_no_args(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {"type": "text", "text": "OK"}

        result = MagicMock()
        result.is_error = False
        result.content = [content]
        client._session.call_tool = AsyncMock(return_value=result)

        tool_result = await client.call_tool("search_web", {"query": "test"})
        # Verify arguments are passed correctly
        client._session.call_tool.assert_awaited_once_with("search_web", {"query": "test"})
        assert tool_result.text == "OK"


# ══════════════════════════════════════════════════════════════
# Convenience methods
# ══════════════════════════════════════════════════════════════


class TestConvenienceMethods:
    """Tests that convenience methods map to canonical tool names."""

    @pytest.mark.asyncio
    async def test_scrape_calls_scrape_webpage(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {"type": "text", "text": "content"}
        result = MagicMock()
        result.is_error = False
        result.content = [content]
        client._session.call_tool = AsyncMock(return_value=result)

        await client.scrape("https://example.com", include_links=True)
        client._session.call_tool.assert_awaited_once_with(
            "scrape_webpage",
            {"url": "https://example.com", "include_links": True, "only_main_content": True},
        )

    @pytest.mark.asyncio
    async def test_crawl_calls_crawl_website(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.is_error = False
        result.content = []
        client._session.call_tool = AsyncMock(return_value=result)

        await client.crawl("https://example.com", max_pages=5, max_depth=3)
        client._session.call_tool.assert_awaited_once_with(
            "crawl_website",
            {"url": "https://example.com", "max_pages": 5, "max_depth": 3},
        )

    @pytest.mark.asyncio
    async def test_search_calls_search_web(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.is_error = False
        result.content = []
        client._session.call_tool = AsyncMock(return_value=result)

        await client.search("python asyncio", max_results=10)
        client._session.call_tool.assert_awaited_once_with(
            "search_web",
            {"query": "python asyncio", "max_results": 10},
        )

    @pytest.mark.asyncio
    async def test_discover_calls_discover_urls(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.is_error = False
        result.content = []
        client._session.call_tool = AsyncMock(return_value=result)

        await client.discover("https://example.com", max_urls=200)
        client._session.call_tool.assert_awaited_once_with(
            "discover_urls",
            {"url": "https://example.com", "max_urls": 200},
        )

    @pytest.mark.asyncio
    async def test_extract_calls_extract_data(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.is_error = False
        result.content = []
        client._session.call_tool = AsyncMock(return_value=result)

        await client.extract("https://example.com", "title,price")
        client._session.call_tool.assert_awaited_once_with(
            "extract_data",
            {"url": "https://example.com", "fields": "title,price"},
        )

    @pytest.mark.asyncio
    async def test_batch_scrape_calls_batch_scrape(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.is_error = False
        result.content = []
        client._session.call_tool = AsyncMock(return_value=result)

        await client.batch_scrape(["https://a.com", "https://b.com"], only_main_content=False)
        client._session.call_tool.assert_awaited_once_with(
            "batch_scrape",
            {"urls": ["https://a.com", "https://b.com"], "only_main_content": False},
        )


# ══════════════════════════════════════════════════════════════
# Resource & Prompt operations
# ══════════════════════════════════════════════════════════════


class TestResourcePromptOps:
    """Tests for resource and prompt operations."""

    @pytest.mark.asyncio
    async def test_list_resources(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        r = MagicMock()
        r.model_dump.return_value = {"uri": "file:///test"}
        result = MagicMock()
        result.resources = [r]
        client._session.list_resources = AsyncMock(return_value=result)

        listed = await client.list_resources()
        assert len(listed) == 1
        assert listed[0]["uri"] == "file:///test"

    @pytest.mark.asyncio
    async def test_list_resources_not_connected(self):
        client = MCPClient()
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await client.list_resources()

    @pytest.mark.asyncio
    async def test_read_resource(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.model_dump.return_value = {"content": "data"}
        client._session.read_resource = AsyncMock(return_value=result)

        data = await client.read_resource("file:///test.txt")
        assert data["content"] == "data"

    @pytest.mark.asyncio
    async def test_list_prompts(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        p = MagicMock()
        p.model_dump.return_value = {"name": "test"}
        result = MagicMock()
        result.prompts = [p]
        client._session.list_prompts = AsyncMock(return_value=result)

        prompts = await client.list_prompts()
        assert len(prompts) == 1
        assert prompts[0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_get_prompt(self):
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        result = MagicMock()
        result.model_dump.return_value = {"description": "..."}
        client._session.get_prompt = AsyncMock(return_value=result)

        data = await client.get_prompt("my_prompt", {"arg": "val"})
        assert data["description"] == "..."

    @pytest.mark.asyncio
    async def test_resource_ops_not_connected(self):
        client = MCPClient()
        with pytest.raises(MCPConnectionError):
            await client.read_resource("file:///x")
        with pytest.raises(MCPConnectionError):
            await client.list_prompts()
        with pytest.raises(MCPConnectionError):
            await client.get_prompt("x")


# ══════════════════════════════════════════════════════════════
# Negative cases
# ══════════════════════════════════════════════════════════════


class TestNegativeCases:
    """Negative-case tests for call_tool."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Calling a tool that doesn't exist raises MCPToolError."""
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        # The SDK's ClientSession.call_tool will raise for unknown tools.
        # On the server side, unknown tools return is_error=True.  The client
        # should surface this as an MCPToolError.

        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {
            "type": "text",
            "text": '{"error": "Tool not found: no_such_tool"}',
        }

        result = MagicMock()
        result.is_error = True
        result.content = [content]
        client._session.call_tool = AsyncMock(return_value=result)

        with pytest.raises(MCPToolError):
            await client.call_tool("no_such_tool", {"url": "x"})

    @pytest.mark.asyncio
    async def test_invalid_arguments(self):
        """Invalid arguments surface as MCPToolError (server-side validation)."""
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        content = MagicMock()
        content.type = "text"
        content.model_dump.return_value = {
            "type": "text",
            "text": '{"error": "url is required"}',
        }

        result = MagicMock()
        result.is_error = True
        result.content = [content]
        client._session.call_tool = AsyncMock(return_value=result)

        with pytest.raises(MCPToolError, match="url is required"):
            await client.call_tool("scrape_webpage", {})

    @pytest.mark.asyncio
    async def test_disconnect_during_pending_operation(self):
        """Disconnecting during a pending operation doesn't hang."""
        client = MCPClient(timeout=5.0)
        client._connected = True
        client._session = MagicMock()

        async def hanging():
            await asyncio.sleep(100)

        client._session.call_tool = hanging
        client._session.__aexit__ = AsyncMock(return_value=None)
        client._transport_cm = MagicMock()
        client._transport_cm.__aexit__ = AsyncMock(return_value=None)

        call_task = asyncio.create_task(client.call_tool("scrape_webpage", {"url": "x"}))
        # Give the call a moment to start, then disconnect
        await asyncio.sleep(0.05)
        await client.disconnect()

        with pytest.raises((MCPTimeoutError, MCPConnectionError, asyncio.TimeoutError, Exception)):
            await call_task

    @pytest.mark.asyncio
    async def test_connection_error_propagated(self):
        """A connection error during call_tool propagates as MCPConnectionError."""
        client = MCPClient()
        client._connected = True
        client._session = MagicMock()

        client._session.call_tool = AsyncMock(side_effect=ConnectionError("Connection reset"))

        with pytest.raises(MCPError):
            await client.call_tool("scrape_webpage", {"url": "x"})


# ══════════════════════════════════════════════════════════════
# Factory functions
# ══════════════════════════════════════════════════════


class TestFactoryFunctions:
    """Tests for factory helpers."""

    def test_create_http_client(self):
        client = create_http_client(url="http://localhost:9000/mcp")
        assert client._transport_type == TransportType.HTTP
        assert client._url == "http://localhost:9000/mcp"

    def test_create_http_client_with_api_key(self):
        client = create_http_client(api_key="secret")
        assert client._headers["Authorization"] == "Bearer secret"

    def test_create_http_client_defaults(self):
        client = create_http_client()
        assert client._url == "http://localhost:8080/mcp"
        assert client._timeout == 60.0

    def test_create_sse_client_deprecated(self):
        """``create_sse_client`` maps to Streamable HTTP."""
        client = create_sse_client(url="http://localhost:9000/mcp")
        assert client._transport_type == TransportType.HTTP

    def test_create_stdio_client(self):
        client = create_stdio_client(command="python", args=["-m", "server.mcp.server"])
        assert client._transport_type == TransportType.STDIO
        assert client._command == "python"
        assert client._args == ["-m", "server.mcp.server"]

    def test_create_stdio_client_defaults(self):
        client = create_stdio_client()
        assert client._command == "python"
        assert client._args == ["-m", "server.mcp.server"]

    def test_create_websocket_client_deprecated(self):
        """``create_websocket_client`` returns an HTTP client (deprecated)."""
        client = create_websocket_client(url="ws://localhost:9000/ws")
        assert client._transport_type == TransportType.HTTP


# ══════════════════════════════════════════════════════════════
# MCPToolInfo / MCPToolResult / MCPServerInfo wrappers
# ══════════════════════════════════════════════════════════════


class TestMCPToolInfo:
    def test_from_dict(self):
        info = MCPToolInfo.from_dict(
            {"name": "scrape_webpage", "description": "Scrape", "inputSchema": {"type": "object"}}
        )
        assert info.name == "scrape_webpage"
        assert info.description == "Scrape"
        assert info.input_schema == {"type": "object"}

    def test_from_dict_defaults(self):
        info = MCPToolInfo.from_dict({})
        assert info.name == ""
        assert info.description == ""
        assert info.input_schema == {}

    def test_from_mcp_tool(self):
        tool = MagicMock()
        tool.name = "test_tool"
        tool.description = "A test"
        tool.input_schema = {"type": "object"}
        info = MCPToolInfo.from_mcp_tool(tool)
        assert info.name == "test_tool"
        assert info.description == "A test"
        assert info.input_schema == {"type": "object"}


class TestMCPToolResultText:
    def test_text_simple(self):
        result = MCPToolResult(content=[{"type": "text", "text": "Hello"}])
        assert result.text == "Hello"

    def test_text_multiple_parts(self):
        result = MCPToolResult(
            content=[
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": " World"},
            ]
        )
        assert result.text == "Hello\n World"

    def test_text_image(self):
        result = MCPToolResult(content=[{"type": "image", "mimeType": "image/png"}])
        assert result.text == "[image: image/png]"

    def test_text_resource(self):
        result = MCPToolResult(content=[{"type": "resource", "uri": "file:///test.txt"}])
        assert result.text == "[resource: file:///test.txt]"

    def test_text_empty(self):
        result = MCPToolResult(content=[])
        assert result.text == ""

    def test_json_valid(self):
        result = MCPToolResult(content=[{"type": "text", "text": '{"key": "value"}'}])
        assert result.json_data == {"key": "value"}

    def test_json_invalid(self):
        result = MCPToolResult(content=[{"type": "text", "text": "not json"}])
        assert result.json_data == "not json"


class TestMCPServerInfo:
    def test_from_dict(self):
        info = MCPServerInfo.from_dict(
            {
                "serverInfo": {"name": "test-server", "version": "1.0.0"},
                "protocolVersion": _MODERN_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
            }
        )
        assert info.name == "test-server"
        assert info.version == "1.0.0"
        assert info.protocol_version == _MODERN_PROTOCOL_VERSION
        assert info.capabilities == {"tools": {}}

    def test_from_dict_defaults(self):
        info = MCPServerInfo.from_dict({})
        assert info.name == ""
        assert info.version == ""
        assert info.protocol_version == ""
        assert info.capabilities == {}


# ══════════════════════════════════════════════════════════════
# Server interoperability tests
#
# These tests start a real MCP server (Set B Streamable HTTP) on a local
# port and connect the migrated MCPClient to it.  No external websites are
# used — the server-side tool handlers are patched to return mock data.
# ══════════════════════════════════════════════════════════════

# Canonical names imported for interop test assertions.
from server.mcp.tools import CANONICAL_TOOL_ORDER as SERVER_CANONICAL_ORDER  # noqa: E402
from server.mcp.tools import get_tool  # noqa: E402


@pytest.fixture
def _mock_crawl_engine():
    """Patch CrawlEngine.default to return a mock engine that doesn't
    touch any browser or network."""
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
        )
    )
    engine.extract = AsyncMock(
        return_value=MagicMock(
            success=True,
            extracted_data=MagicMock(model_dump=MagicMock(return_value={"title": "Example"})),
        )
    )
    engine.__aenter__ = AsyncMock(return_value=engine)
    engine.__aexit__ = AsyncMock(return_value=None)

    # Also mock SearchEngine for search_web.
    mock_search_result = MagicMock()
    mock_search_result.to_dict.return_value = {
        "title": "Test",
        "url": "https://example.com",
        "snippet": "test",
    }

    with (
        patch("agentcrawl.core.engine.CrawlEngine.default", classmethod(lambda cls: engine)),
        patch("agentcrawl.SearchEngine") as mock_se_class,
    ):
        mock_se_instance = MagicMock()
        mock_se_instance.search = AsyncMock(return_value=["result1", "result2"])
        mock_se_class.return_value = mock_se_instance
        yield engine


@pytest_asyncio.fixture
async def _mcp_server(_mock_crawl_engine):
    """Start a Streamable HTTP MCP server in a background task and yield the URL.

    Depends on ``_mock_crawl_engine`` so that the mock-patched
    ``CrawlEngine.default`` is active during server startup (the shared-engine
    lifespan, Set G) and graceful shutdown — preventing a real browser launch.
    """
    import socket

    import uvicorn
    from server.mcp.server import create_mcp_server

    # Find a free port to avoid collisions between test runs.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = create_mcp_server()
    app = server.streamable_http_app(stateless_http=True)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server_instance = uvicorn.Server(config)

    # Run server in a background task.
    server_task = asyncio.create_task(server_instance.serve())

    # Wait for the server to be ready (POST — GET triggers an SSE stream).
    import time

    deadline = time.monotonic() + 15
    ready = False
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            import httpx2

            async with asyncio.timeout(2):
                async with httpx2.AsyncClient() as c:
                    await c.post(
                        f"http://127.0.0.1:{port}/mcp",
                        content=b"{}",
                        headers={"Content-Type": "application/json"},
                    )
            ready = True
            break
        await asyncio.sleep(0.1)

    assert ready, f"Server did not start on port {port}"

    url = f"http://127.0.0.1:{port}/mcp"
    yield url

    # Shutdown: signal shutdown and await the serve task.
    server_instance.should_exit = True
    server_task.cancel()
    # Guard against a stuck lifespan finally-block hanging teardown.
    with contextlib.suppress(asyncio.CancelledError, Exception, asyncio.TimeoutError):
        await asyncio.wait_for(server_task, timeout=5)


@pytest.mark.asyncio
async def test_interop_list_tools(
    _mcp_server,
    _mock_crawl_engine,
):
    """MCP Client → Streamable HTTP → Set B Server → tools/list."""
    server_url = _mcp_server
    async with MCPClient(transport="http", url=server_url) as client:
        tools = await client.list_tools()
        assert len(tools) == 6
        names = [t.name for t in tools]
        assert names == EXPECTED_CANONICAL_NAMES
        # Verify canonical ordering matches server.
        assert names == SERVER_CANONICAL_ORDER


@pytest.mark.asyncio
async def test_interop_call_tool(
    _mcp_server,
    _mock_crawl_engine,
):
    """MCP Client → Streamable HTTP → Set B Server → tools/call (scrape_webpage)."""
    server_url = _mcp_server
    async with MCPClient(transport="http", url=server_url) as client:
        result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        assert result.is_error is False
        data = result.json_data
        assert data["url"] == "https://example.com"
        assert "content" in data


@pytest.mark.asyncio
async def test_interop_all_six_tools(
    _mcp_server,
    _mock_crawl_engine,
):
    """Every canonical tool is callable through the migrated client."""
    server_url = _mcp_server
    async with MCPClient(transport="http", url=server_url) as client:
        for name in EXPECTED_CANONICAL_NAMES:
            tool = get_tool(name)
            assert tool is not None

            # Build valid arguments for each tool.
            if name == "scrape_webpage":
                args = {"url": "https://example.com"}
            elif name == "search_web":
                args = {"query": "test"}
            elif name == "crawl_website" or name == "discover_urls":
                args = {"url": "https://example.com"}
            elif name == "extract_data":
                args = {"url": "https://example.com", "fields": "title"}
            elif name == "batch_scrape":
                args = {"urls": ["https://example.com"]}
            else:
                continue

            result = await client.call_tool(name, args)
            assert result.is_error is False, f"Tool {name} returned error"
            assert result.text, f"Tool {name} returned empty content"


@pytest.mark.asyncio
async def test_interop_stateless_multiple_requests(
    _mcp_server,
    _mock_crawl_engine,
):
    """Multiple independent client sessions work against the stateless server."""
    server_url = _mcp_server
    results = []
    for _ in range(3):
        async with MCPClient(transport="http", url=server_url) as client:
            result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
            results.append(result.text)

    # Each session should produce identical results (stateless).
    assert all(r == results[0] for r in results)


@pytest.mark.asyncio
async def test_interop_unknown_tool_returns_error(
    _mcp_server,
    _mock_crawl_engine,
):
    """An unknown tool name surfaces as MCPToolError."""
    server_url = _mcp_server
    async with MCPClient(transport="http", url=server_url) as client:
        with pytest.raises(MCPToolError):
            await client.call_tool("web_scrape", {"url": "https://example.com"})


@pytest.mark.asyncio
async def test_interop_invalid_arguments(
    _mcp_server,
    _mock_crawl_engine,
):
    """Missing required arguments surface as MCPToolError."""
    server_url = _mcp_server
    async with MCPClient(transport="http", url=server_url) as client:
        with pytest.raises(MCPToolError):
            await client.call_tool("scrape_webpage", {})


@pytest.mark.asyncio
async def test_interop_connection_failure():
    """Connecting to a non-existent server raises a connection error."""
    client = MCPClient(transport="http", url="http://127.0.0.1:1/mcp", timeout=3)
    with pytest.raises((MCPConnectionError, MCPTimeoutError)):
        await client.connect()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_interop_connection_failure_call_tool():
    """call_tool without connecting raises MCPConnectionError."""
    client = MCPClient()
    with pytest.raises(MCPConnectionError, match="Not connected"):
        await client.call_tool("scrape_webpage", {"url": "https://example.com"})


@pytest.mark.asyncio
async def test_interop_disconnect_cleans_up(
    _mcp_server,
    _mock_crawl_engine,
):
    """Disconnect during active session cleans up resources."""
    server_url = _mcp_server
    async with MCPClient(transport="http", url=server_url) as client:
        tools = await client.list_tools()
        assert len(tools) == 6

    # After exiting the context manager, session should be None.
    assert client._session is None
    assert client._transport_cm is None


# ══════════════════════════════════════════════════════════════
# Set L — Operation-level lifecycle & failure-path regression tests
# ══════════════════════════════════════════════════════════════
#
# These tests cover the failure paths that were MISSING from the original
# implementation:
#
#   * Internal AnyIO cancel-scope cancellation during an operation
#     (transport failure mid-call) must be translated to MCPConnectionError.
#   * External caller cancellation during an operation must propagate as
#     CancelledError while still cleaning up resources.
#   * Operation failures (SDK/runtime exceptions) must trigger cleanup so
#     the client is not left in a corrupted _connected=True state.
#   * list_tools / list_resources / read_resource / list_prompts / get_prompt
#     now have the same lifecycle safety as call_tool.
#   * Repeated cleanup (idempotency) after any failure path.


_ANYIO_CANCEL_MSG = "Cancelled via cancel scope 0xdeadbeef"


class TestSetLSessionOpFailurePaths:
    """Set L — regression tests for operation-level failure paths (F4-F8)."""

    def _connected_client(self) -> MCPClient:
        """Build a client in the connected state with a mock session."""
        client = MCPClient(transport="http", url="http://localhost:8080/mcp")
        client._connected = True
        session = MagicMock()
        session.__aexit__ = AsyncMock(return_value=None)
        client._session = session
        transport_cm = MagicMock()
        transport_cm.__aexit__ = AsyncMock(return_value=None)
        client._transport_cm = transport_cm
        return client

    # ── F4: Transport failure during operation ──────────────────

    @pytest.mark.asyncio
    async def test_call_tool_sdk_exception_triggers_cleanup(self):
        """An SDK/runtime exception during call_tool must clean up the session
        and transport, leaving the client disconnected."""
        client = self._connected_client()
        client._session.call_tool = AsyncMock(side_effect=ConnectionError("connection reset"))

        with pytest.raises(MCPConnectionError, match="connection reset"):
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        assert client.is_connected is False
        assert client._session is None
        assert client._transport_cm is None

    @pytest.mark.asyncio
    async def test_list_tools_sdk_exception_triggers_cleanup(self):
        """An exception during list_tools must clean up resources."""
        client = self._connected_client()
        client._session.list_tools = AsyncMock(side_effect=ConnectionError("transport closed"))

        with pytest.raises(MCPConnectionError):
            await client.list_tools()

        assert client.is_connected is False
        assert client._session is None
        assert client._tools_cache is None

    @pytest.mark.asyncio
    async def test_list_resources_sdk_exception_triggers_cleanup(self):
        """An exception during list_resources must clean up resources."""
        client = self._connected_client()
        client._session.list_resources = AsyncMock(side_effect=ConnectionError("broken pipe"))

        with pytest.raises(MCPConnectionError):
            await client.list_resources()

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_read_resource_sdk_exception_triggers_cleanup(self):
        """An exception during read_resource must clean up resources."""
        client = self._connected_client()
        client._session.read_resource = AsyncMock(side_effect=ConnectionError("broken pipe"))

        with pytest.raises(MCPConnectionError):
            await client.read_resource("file:///test.txt")

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_list_prompts_sdk_exception_triggers_cleanup(self):
        """An exception during list_prompts must clean up resources."""
        client = self._connected_client()
        client._session.list_prompts = AsyncMock(side_effect=ConnectionError("broken pipe"))

        with pytest.raises(MCPConnectionError):
            await client.list_prompts()

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_get_prompt_sdk_exception_triggers_cleanup(self):
        """An exception during get_prompt must clean up resources."""
        client = self._connected_client()
        client._session.get_prompt = AsyncMock(side_effect=ConnectionError("broken pipe"))

        with pytest.raises(MCPConnectionError):
            await client.get_prompt("test_prompt")

        assert client.is_connected is False
        assert client._session is None

    # ── F5: Cancellation during operation ───────────────────────

    @pytest.mark.asyncio
    async def test_call_tool_internal_cancel_translated(self):
        """Internal AnyIO cancel-scope cancellation during call_tool must be
        translated to MCPConnectionError (not propagated as CancelledError)."""
        client = self._connected_client()
        client._session.call_tool = AsyncMock(side_effect=asyncio.CancelledError(_ANYIO_CANCEL_MSG))

        with pytest.raises(MCPConnectionError, match="Error in call_tool"):
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_call_tool_external_cancel_propagates_with_cleanup(self):
        """External task cancellation during call_tool must propagate as
        CancelledError AND clean up resources (no leak)."""
        client = self._connected_client()

        async def _hanging_call(name, arguments):
            await asyncio.sleep(100)

        client._session.call_tool = _hanging_call

        call_task = asyncio.create_task(client.call_tool("scrape_webpage", {"url": "x"}))
        await asyncio.sleep(0.05)
        call_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await call_task

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_list_tools_external_cancel_propagates_with_cleanup(self):
        """External cancellation during list_tools must propagate AND clean up."""
        client = self._connected_client()

        async def _hanging_list():
            await asyncio.sleep(100)

        client._session.list_tools = _hanging_list

        call_task = asyncio.create_task(client.list_tools())
        await asyncio.sleep(0.05)
        call_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await call_task

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_list_tools_internal_cancel_translated(self):
        """Internal AnyIO cancel during list_tools → MCPConnectionError."""
        client = self._connected_client()
        client._session.list_tools = AsyncMock(
            side_effect=asyncio.CancelledError(_ANYIO_CANCEL_MSG)
        )

        with pytest.raises(MCPConnectionError):
            await client.list_tools()

        assert client.is_connected is False
        assert client._session is None

    # ── F3: Timeout during operation (no cleanup — session preserved) ─

    @pytest.mark.asyncio
    async def test_call_tool_timeout_preserves_connection(self):
        """A tool-call timeout does NOT tear down the session (the transport
        is still usable for subsequent calls)."""
        client = self._connected_client()
        client._session.call_tool = AsyncMock(return_value=MagicMock())

        # Use the helper to make call_tool raise a timeout
        with (
            patch.object(
                client,
                "_execute_session_op",
                side_effect=MCPTimeoutError("call_tool: timed out after 0.001s"),
            ),
            pytest.raises(MCPTimeoutError),
        ):
            await client.call_tool("scrape_webpage", {"url": "x"}, timeout=0.001)

        # Session is preserved after timeout
        assert client._session is not None
        assert client._connected is True

    # ── F6/F7/F8: Idempotency & cleanup after partial/failed states ─

    @pytest.mark.asyncio
    async def test_cleanup_idempotent_after_call_tool_failure(self):
        """Calling disconnect() after a failed call_tool must be safe (AC-07:
        repeated cleanup must not raise)."""
        client = self._connected_client()
        client._session.call_tool = AsyncMock(side_effect=ConnectionError("dead"))

        with pytest.raises(MCPConnectionError):
            await client.call_tool("scrape_webpage", {"url": "x"})

        # First cleanup (already happened during the failure)
        assert client._session is None

        # Second cleanup (explicit disconnect) must not raise
        await client.disconnect()
        await client.disconnect()  # triple — still safe

    @pytest.mark.asyncio
    async def test_cleanup_idempotent_when_never_connected(self):
        """Cleanup on a never-connected client is a safe no-op."""
        client = MCPClient()

        await client._cleanup()
        await client._cleanup()
        await client._safe_cleanup()

        assert client.is_connected is False
        assert client._session is None
        assert client._transport_cm is None
        assert client._server_info is None

    @pytest.mark.asyncio
    async def test_cleanup_idempotent_after_connect_failure(self):
        """Cleanup is safe after a connection failure."""
        client = MCPClient(transport="http", url="http://127.0.0.1:1/mcp", timeout=2)

        with pytest.raises((MCPConnectionError, MCPTimeoutError)):
            await client.connect()

        # Session and transport should already be None from connect()'s cleanup.
        assert client._session is None
        assert client._transport_cm is None

        # Calling disconnect again must not raise (F7: repeated cleanup).
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_call_tool_then_disconnect_after_failure(self):
        """After a failed tool call, the client can still be safely shut down."""
        client = self._connected_client()
        client._session.call_tool = AsyncMock(side_effect=RuntimeError("kaboom"))

        with pytest.raises(MCPConnectionError):
            await client.call_tool("scrape_webpage", {"url": "x"})

        # Client should be fully disconnected after the failure.
        assert not client.is_connected

        # disconnect() must be a no-op (already cleaned up, no double-exit).
        await client.disconnect()
        assert not client.is_connected

    # ── F4: CancelledError not masked by MCPError re-raise ────────

    @pytest.mark.asyncio
    async def test_call_tool_does_not_swallow_cancelled_error_as_connection_error(self):
        """External CancelledError (no AnyIO prefix) must NOT be converted to
        MCPConnectionError — it must propagate as CancelledError."""
        client = self._connected_client()

        async def _hanging(name, arguments):
            await asyncio.sleep(100)

        client._session.call_tool = _hanging

        call_task = asyncio.create_task(client.call_tool("scrape_webpage", {"url": "x"}))
        await asyncio.sleep(0.05)
        # External cancel with a non-AnyIO prefix message
        call_task.cancel("external teardown reason")

        with pytest.raises(asyncio.CancelledError):
            await call_task

        assert client.is_connected is False
        assert client._session is None


class TestSetLTransportCoverage:
    """Set L — AC-08: verify lifecycle safety for both stdio and HTTP transports.

    Uses the real local server fixture for HTTP and the mocked-session pattern
    for stdio to avoid spawning subprocesses.
    """

    @pytest.mark.asyncio
    async def test_http_transport_failure_cleans_up(self, _mcp_server):
        """HTTP transport: when the server is killed mid-operation, the
        client is cleaned up (session + transport torn down)."""
        client = MCPClient(transport="http", url=_mcp_server, timeout=30)
        await client.connect()
        assert client.is_connected

        # Simulate a transport failure during a tool call by making the
        # session call raise a raw connection error.
        client._session.call_tool = AsyncMock(
            side_effect=ConnectionError("connection reset by peer")
        )

        with pytest.raises(MCPConnectionError, match="connection reset"):
            await client.call_tool("scrape_webpage", {"url": "https://example.com"})

        assert client.is_connected is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_stdio_call_tool_failure_cleans_up(self):
        """stdio transport: a tool call failure cleans up the client."""
        client = MCPClient(transport="stdio", command="python", args=["-m", "server.mcp.server"])
        client._connected = True
        session_mock = MagicMock()
        session_mock.__aexit__ = AsyncMock(return_value=None)
        client._session = session_mock
        transport_cm = MagicMock()
        transport_cm.__aexit__ = AsyncMock(return_value=None)
        client._transport_cm = transport_cm

        client._session.call_tool = AsyncMock(side_effect=ConnectionError("stdio pipe broke"))

        with pytest.raises(MCPConnectionError):
            await client.call_tool("scrape_webpage", {"url": "x"})

        assert client.is_connected is False
        assert client._session is None
