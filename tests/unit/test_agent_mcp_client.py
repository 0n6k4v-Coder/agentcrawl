"""Tests for agentcrawl.agent.mcp_client module."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcrawl.agent.mcp_client import (
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPTimeoutError,
    MCPToolError,
    MCPToolInfo,
    MCPToolResult,
    MCPServerInfo,
    TransportType,
    _JsonRpc,
    create_sse_client,
    create_stdio_client,
    create_websocket_client,
)


# ═══ TransportType ═══

class TestTransportType:
    """Tests for TransportType enum."""

    def test_sse(self):
        assert TransportType.SSE.value == "sse"

    def test_websocket(self):
        assert TransportType.WEBSOCKET.value == "websocket"

    def test_stdio(self):
        assert TransportType.STDIO.value == "stdio"

    def test_from_string_sse(self):
        assert TransportType("sse") == TransportType.SSE

    def test_from_string_websocket(self):
        assert TransportType("websocket") == TransportType.WEBSOCKET

    def test_from_string_stdio(self):
        assert TransportType("stdio") == TransportType.STDIO

    def test_invalid_transport(self):
        with pytest.raises(ValueError):
            TransportType("invalid")


# ═══ MCPError ═══

class TestMCPError:
    """Tests for MCPError exception."""

    def test_basic(self):
        err = MCPError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.code is None
        assert err.data is None

    def test_with_code(self):
        err = MCPError("Bad request", code=-32600, data={"detail": "x"})
        assert err.code == -32600
        assert err.data == {"detail": "x"}

    def test_is_exception(self):
        err = MCPError("test")
        assert isinstance(err, Exception)

    def test_connection_error_is_mcp_error(self):
        err = MCPConnectionError("Connection failed")
        assert isinstance(err, MCPError)

    def test_tool_error_is_mcp_error(self):
        err = MCPToolError("Tool error")
        assert isinstance(err, MCPError)

    def test_timeout_error_is_mcp_error(self):
        err = MCPTimeoutError("Timed out")
        assert isinstance(err, MCPError)


# ═══ MCPToolInfo ═══

class TestMCPToolInfo:
    """Tests for MCPToolInfo dataclass."""

    def test_from_dict_basic(self):
        data = {"name": "web_scrape", "description": "Scrape a URL", "inputSchema": {"type": "object"}}
        info = MCPToolInfo.from_dict(data)
        assert info.name == "web_scrape"
        assert info.description == "Scrape a URL"
        assert info.input_schema == {"type": "object"}

    def test_from_dict_input_schema_fallback(self):
        data = {"name": "web_crawl", "input_schema": {"type": "object"}}
        info = MCPToolInfo.from_dict(data)
        assert info.input_schema == {"type": "object"}

    def test_from_dict_defaults(self):
        info = MCPToolInfo.from_dict({})
        assert info.name == ""
        assert info.description == ""
        assert info.input_schema == {}


# ═══ MCPToolResult ═══

class TestMCPToolResultText:
    """Tests for MCPToolResult.text property."""

    def test_text_simple(self):
        result = MCPToolResult(content=[{"type": "text", "text": "Hello"}])
        assert result.text == "Hello"

    def test_text_multiple_parts(self):
        result = MCPToolResult(content=[
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": " World"},
        ])
        assert result.text == "Hello\n World"

    def test_text_image(self):
        result = MCPToolResult(content=[
            {"type": "image", "mimeType": "image/png"},
        ])
        assert result.text == "[image: image/png]"

    def test_text_image_no_mime(self):
        result = MCPToolResult(content=[{"type": "image"}])
        assert result.text == "[image: unknown]"

    def test_text_resource(self):
        result = MCPToolResult(content=[
            {"type": "resource", "uri": "file:///test.txt"},
        ])
        assert result.text == "[resource: file:///test.txt]"

    def test_text_resource_no_uri(self):
        result = MCPToolResult(content=[{"type": "resource"}])
        assert result.text == "[resource: unknown]"

    def test_text_mixed(self):
        result = MCPToolResult(content=[
            {"type": "text", "text": "Hello"},
            {"type": "image", "mimeType": "image/jpeg"},
            {"type": "resource", "uri": "file:///test.txt"},
        ])
        assert "Hello" in result.text
        assert "[image: image/jpeg]" in result.text
        assert "[resource: file:///test.txt]" in result.text

    def test_text_empty(self):
        result = MCPToolResult(content=[])
        assert result.text == ""

    def test_text_unknown_type(self):
        result = MCPToolResult(content=[{"type": "unknown"}])
        assert result.text == ""


class TestMCPToolResultJson:
    """Tests for MCPToolResult.json_data property."""

    def test_json_valid(self):
        result = MCPToolResult(content=[{"type": "text", "text": '{"key": "value"}'}])
        assert result.json_data == {"key": "value"}

    def test_json_invalid(self):
        result = MCPToolResult(content=[{"type": "text", "text": "not json"}])
        assert result.json_data == "not json"

    def test_json_no_text(self):
        result = MCPToolResult(content=[{"type": "image", "mimeType": "image/png"}])
        assert result.json_data == "[image: image/png]"

    def test_json_empty_content(self):
        result = MCPToolResult(content=[])
        assert result.json_data == ""


class TestMCPToolResultFromDict:
    """Tests for MCPToolResult.from_dict."""

    def test_from_dict_basic(self):
        data = {"content": [{"type": "text", "text": "Hello"}], "isError": False}
        result = MCPToolResult.from_dict(data)
        assert len(result.content) == 1
        assert result.is_error is False
        assert result.raw == data

    def test_from_dict_error(self):
        data = {"content": [], "isError": True}
        result = MCPToolResult.from_dict(data)
        assert result.is_error is True

    def test_from_dict_defaults(self):
        result = MCPToolResult.from_dict({})
        assert result.content == []
        assert result.is_error is False


# ═══ MCPServerInfo ═══

class TestMCPServerInfo:
    """Tests for MCPServerInfo dataclass."""

    def test_from_dict_basic(self):
        data = {
            "serverInfo": {"name": "test-server", "version": "1.0.0"},
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
        }
        info = MCPServerInfo.from_dict(data)
        assert info.name == "test-server"
        assert info.version == "1.0.0"
        assert info.protocol_version == "2024-11-05"
        assert info.capabilities == {"tools": {}}

    def test_from_dict_defaults(self):
        info = MCPServerInfo.from_dict({})
        assert info.name == ""
        assert info.version == ""
        assert info.protocol_version == ""
        assert info.capabilities == {}

    def test_from_dict_no_server_info(self):
        data = {"protocolVersion": "1.0"}
        info = MCPServerInfo.from_dict(data)
        assert info.name == ""
        assert info.version == ""
        assert info.protocol_version == "1.0"


# ═══ _JsonRpc ═══

class TestJsonRpc:
    """Tests for _JsonRpc message builder."""

    def test_request_with_params(self):
        msg = _JsonRpc.request("tools/call", {"name": "web_scrape"})
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "tools/call"
        assert msg["params"] == {"name": "web_scrape"}
        assert "id" in msg

    def test_request_without_params(self):
        msg = _JsonRpc.request("initialize")
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "initialize"
        assert msg["params"] == {}

    def test_notification_with_params(self):
        msg = _JsonRpc.notification("notifications/initialized", {"key": "val"})
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "notifications/initialized"
        assert msg["params"] == {"key": "val"}
        assert "id" not in msg

    def test_notification_without_params(self):
        msg = _JsonRpc.notification("ping")
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "ping"
        assert msg["params"] == {}
        assert "id" not in msg

    def test_response(self):
        result = {"tools": []}
        msg = _JsonRpc.response("req-123", result)
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == "req-123"
        assert msg["result"] == result

    def test_error_response_with_data(self):
        msg = _JsonRpc.error_response("req-123", -32601, "Method not found", {"detail": "x"})
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == "req-123"
        assert msg["error"]["code"] == -32601
        assert msg["error"]["message"] == "Method not found"
        assert msg["error"]["data"] == {"detail": "x"}

    def test_error_response_no_data(self):
        msg = _JsonRpc.error_response("req-456", -32600, "Invalid")
        assert msg["error"]["code"] == -32600
        assert msg["error"]["message"] == "Invalid"
        assert "data" not in msg["error"]


# ═══ MCPClient Init ═══

class TestMCPClientInit:
    """Tests for MCPClient.__init__."""

    def test_defaults(self):
        client = MCPClient()
        assert client._transport_type == TransportType.SSE
        assert client._url == "http://localhost:8000/mcp/sse"
        assert client._timeout == 60.0
        assert client._api_key is None
        assert client._connected is False
        assert client.is_connected is False

    def test_sse_transport(self):
        client = MCPClient(transport="sse", url="http://localhost:9000/sse")
        assert client._transport_type == TransportType.SSE
        assert client._url == "http://localhost:9000/sse"

    def test_websocket_transport(self):
        client = MCPClient(transport="websocket", url="ws://localhost:9000/ws")
        assert client._transport_type == TransportType.WEBSOCKET

    def test_stdio_transport(self):
        client = MCPClient(transport="stdio", command="agentcrawl", args=["mcp", "serve"])
        assert client._transport_type == TransportType.STDIO
        assert client._command == "agentcrawl"
        assert client._args == ["mcp", "serve"]

    def test_api_key_sets_auth_header(self):
        client = MCPClient(api_key="secret123")
        assert client._headers["Authorization"] == "Bearer secret123"

    def test_custom_headers(self):
        client = MCPClient(headers={"X-Custom": "value"})
        assert client._headers["X-Custom"] == "value"

    def test_custom_timeout(self):
        client = MCPClient(timeout=120.0)
        assert client._timeout == 120.0

    def test_args_defaults_to_empty(self):
        client = MCPClient(transport="stdio", command="agentcrawl")
        assert client._args == []

    def test_invalid_transport(self):
        with pytest.raises(ValueError, match="not a valid TransportType"):
            MCPClient(transport="invalid")

    def test_create_transport_sse(self):
        client = MCPClient(transport="sse")
        transport = client._create_transport()
        assert transport.__class__.__name__ == "_SSETransport"

    def test_create_transport_websocket(self):
        client = MCPClient(transport="websocket")
        transport = client._create_transport()
        assert transport.__class__.__name__ == "_WebSocketTransport"

    def test_create_transport_stdio(self):
        client = MCPClient(transport="stdio")
        transport = client._create_transport()
        assert transport.__class__.__name__ == "_StdioTransport"

    def test_server_info_none_before_connect(self):
        client = MCPClient()
        assert client.server_info is None

    def test_repr_disconnected(self):
        client = MCPClient(transport="sse", url="http://localhost:9000/sse")
        assert "disconnected" in repr(client)
        assert "sse" in repr(client)

    def test_repr_connected(self):
        client = MCPClient(transport="sse", url="http://localhost:9000/sse")
        client._connected = True
        client._transport = MagicMock()
        client._transport.is_connected = True
        assert "connected" in repr(client)

    def test_is_connected_transport_down(self):
        client = MCPClient()
        client._connected = True
        client._transport = MagicMock()
        client._transport.is_connected = False
        assert client.is_connected is False

    def test_is_connected_both_true(self):
        client = MCPClient()
        client._connected = True
        client._transport = MagicMock()
        client._transport.is_connected = True
        assert client.is_connected is True


# ═══ MCPClient.connect ═══

class TestMCPClientConnect:
    """Tests for MCPClient.connect."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        client = MCPClient(transport="sse")
        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        mock_transport.is_connected = True
        client._transport = mock_transport

        init_response = {
            "serverInfo": {"name": "test-server", "version": "1.0.0"},
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
        }
        mock_transport.send = AsyncMock()
        mock_transport.receive = AsyncMock(return_value=[])
        # Mock _request to return the init response
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=init_response):
            with patch.object(client, "_notify", new_callable=AsyncMock):
                with patch.object(client, "_listen", new_callable=AsyncMock):
                    result = await client.connect()

        assert client._connected is True
        assert client._server_info.name == "test-server"
        assert client._server_info.version == "1.0.0"
        assert client._server_info.protocol_version == "2024-11-05"
        assert client._server_info.capabilities == {"tools": {}}

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        client = MCPClient(transport="sse")
        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock(side_effect=MCPConnectionError("Connection refused"))
        client._transport = mock_transport

        with pytest.raises(MCPConnectionError, match="Connection refused"):
            await client.connect()

        assert client._connected is False


# ═══ MCPClient.disconnect ═══

class TestMCPClientDisconnect:
    """Tests for MCPClient.disconnect."""

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self):
        client = MCPClient()
        mock_transport = MagicMock()
        mock_transport.disconnect = AsyncMock()
        client._transport = mock_transport
        await client.disconnect()
        mock_transport.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_cancels_listener(self):
        client = MCPClient()
        client._connected = True
        client._listener_task = asyncio.create_task(asyncio.sleep(10))
        client._server_info = MagicMock()
        client._tools_cache = [MagicMock()]
        mock_transport = MagicMock()
        mock_transport.disconnect = AsyncMock()
        client._transport = mock_transport

        await client.disconnect()
        assert client._connected is False
        assert client._tools_cache is None
        assert client._server_info is None

    @pytest.mark.asyncio
    async def test_disconnect_cancels_pending(self):
        client = MCPClient()
        client._connected = True
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        client._pending = {"req-1": future}
        mock_transport = MagicMock()
        mock_transport.disconnect = AsyncMock()
        client._transport = mock_transport

        await client.disconnect()
        future.cancel()
        assert len(client._pending) == 0


# ═══ MCPClient async context ═══

class TestMCPClientContext:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_async_with(self):
        client = MCPClient(transport="sse")
        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        mock_transport.disconnect = AsyncMock()
        mock_transport.is_connected = True
        client._transport = mock_transport

        init_response = {"serverInfo": {"name": "test", "version": "1.0"}}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=init_response):
            with patch.object(client, "_notify", new_callable=AsyncMock):
                with patch.object(client, "_listen", new_callable=AsyncMock):
                    async with client:
                        assert client._connected is True

        assert client._connected is False


# ═══ MCPClient.list_tools ═══

class TestListTools:
    """Tests for list_tools."""

    @pytest.mark.asyncio
    async def test_list_tools_caches(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        # First call goes to _request
        tools_data = [{"name": "web_scrape", "description": "desc", "inputSchema": {}}]
        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"tools": tools_data}):
            result1 = await client.list_tools()
            assert len(result1) == 1
            assert result1[0].name == "web_scrape"

            # Second call uses cache
            result2 = await client.list_tools()
            assert result2 is result1  # cached

    @pytest.mark.asyncio
    async def test_list_tools_empty(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"tools": []}):
            result = await client.list_tools()
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_tools_no_tools_key(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}):
            result = await client.list_tools()
            assert result == []


# ═══ MCPClient.call_tool ═══

class TestCallTool:
    """Tests for call_tool."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        client = MCPClient(timeout=30.0)
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        tool_result = {"content": [{"type": "text", "text": "Hello"}], "isError": False}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=tool_result):
            result = await client.call_tool("web_scrape", {"url": "https://example.com"})

        assert isinstance(result, MCPToolResult)
        assert result.text == "Hello"
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_call_tool_error(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        tool_result = {"content": [{"type": "text", "text": "Tool failed"}], "isError": True}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=tool_result):
            with pytest.raises(MCPToolError, match="Tool 'web_scrape' returned error"):
                await client.call_tool("web_scrape", {"url": "https://example.com"})

    @pytest.mark.asyncio
    async def test_call_tool_timeout(self):
        client = MCPClient(timeout=0.001)
        client._connected = True
        client._pending = {}

        async def hanging_request(*args, **kwargs):
            # Never completes — simulates a hung server
            await asyncio.sleep(100)

        with patch.object(client, "_request", new_callable=AsyncMock, side_effect=hanging_request):
            with pytest.raises(MCPTimeoutError, match="timed out"):
                await client.call_tool("web_scrape", {"url": "https://example.com"})

    @pytest.mark.asyncio
    async def test_call_tool_default_timeout(self):
        client = MCPClient(timeout=60.0)
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        tool_result = {"content": [{"type": "text", "text": "OK"}], "isError": False}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=tool_result):
            result = await client.call_tool("web_scrape")

        assert result.text == "OK"

    @pytest.mark.asyncio
    async def test_call_tool_custom_timeout(self):
        client = MCPClient(timeout=60.0)
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        tool_result = {"content": [{"type": "text", "text": "OK"}], "isError": False}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=tool_result):
            result = await client.call_tool("web_scrape", None, timeout=120.0)

        assert result.text == "OK"

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self):
        client = MCPClient()
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await client.call_tool("web_scrape", {"url": "https://example.com"})

    @pytest.mark.asyncio
    async def test_call_tool_empty_arguments(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        tool_result = {"content": [{"type": "text", "text": "OK"}], "isError": False}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=tool_result):
            result = await client.call_tool("web_ping")

        assert result.text == "OK"


# ═══ MCPClient convenience methods ═══

class TestConvenienceMethods:
    """Tests for convenience methods (scrape, crawl, search, map_site, extract, screenshot)."""

    @pytest.mark.asyncio
    async def test_scrape(self):
        client = MCPClient()
        mock_result = MCPToolResult(content=[{"type": "text", "text": "content"}], is_error=False)
        with patch.object(client, "call_tool", new_callable=AsyncMock, return_value=mock_result) as mock_call:
            result = await client.scrape("https://example.com", output_format="json")

        mock_call.assert_called_once_with("web_scrape", {"url": "https://example.com", "output_format": "json"})
        assert result.text == "content"

    @pytest.mark.asyncio
    async def test_scrape_with_kwargs(self):
        client = MCPClient()
        mock_result = MCPToolResult(content=[{"type": "text", "text": "ok"}], is_error=False)
        with patch.object(client, "call_tool", new_callable=AsyncMock, return_value=mock_result) as mock_call:
            await client.scrape("https://example.com", output_format="html", stealth=False)

        call_args = mock_call.call_args
        assert call_args[0][0] == "web_scrape"
        assert call_args[0][1]["url"] == "https://example.com"
        assert call_args[0][1]["output_format"] == "html"
        assert call_args[0][1]["stealth"] is False

    @pytest.mark.asyncio
    async def test_crawl(self):
        client = MCPClient()
        mock_result = MagicMock()
        with patch.object(client, "call_tool", new_callable=AsyncMock, return_value=mock_result):
            await client.crawl("https://example.com", max_depth=5, max_pages=100)

    @pytest.mark.asyncio
    async def test_search(self):
        client = MCPClient()
        mock_result = MagicMock()
        with patch.object(client, "call_tool", new_callable=AsyncMock, return_value=mock_result):
            await client.search("test query", max_results=10)

    @pytest.mark.asyncio
    async def test_map_site(self):
        client = MCPClient()
        mock_result = MagicMock()
        with patch.object(client, "call_tool", new_callable=AsyncMock, return_value=mock_result):
            await client.map_site("https://example.com", max_urls=100)

    @pytest.mark.asyncio
    async def test_extract(self):
        client = MCPClient()
        mock_result = MagicMock()
        with patch.object(client, "call_tool", new_callable=AsyncMock, return_value=mock_result):
            await client.extract("https://example.com", {"type": "object"}, method="css")

    @pytest.mark.asyncio
    async def test_screenshot(self):
        client = MCPClient()
        mock_result = MagicMock()
        with patch.object(client, "call_tool", new_callable=AsyncMock, return_value=mock_result):
            await client.screenshot("https://example.com", full_page=False)


# ═══ MCPClient resource/prompt operations ═══

class TestResourcePromptOps:
    """Tests for resource and prompt operations."""

    @pytest.mark.asyncio
    async def test_list_resources(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"resources": [{"uri": "file:///test"}]}):
            result = await client.list_resources()

        assert len(result) == 1
        assert result[0]["uri"] == "file:///test"

    @pytest.mark.asyncio
    async def test_list_resources_empty(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"resources": []}):
            result = await client.list_resources()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_resources_no_key(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}):
            result = await client.list_resources()
        assert result == []

    @pytest.mark.asyncio
    async def test_read_resource(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"content": "data"}) as mock_req:
            result = await client.read_resource("file:///test.txt")

        mock_req.assert_called_once_with("resources/read", {"uri": "file:///test.txt"})
        assert result["content"] == "data"

    @pytest.mark.asyncio
    async def test_list_prompts(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"prompts": [{"name": "test"}]}):
            result = await client.list_prompts()

        assert len(result) == 1
        assert result[0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_list_prompts_empty(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}):
            result = await client.list_prompts()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_prompt(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"prompt": "..."}) as mock_req:
            result = await client.get_prompt("my_prompt", {"arg": "val"})

        mock_req.assert_called_once_with("prompts/get", {"name": "my_prompt", "arguments": {"arg": "val"}})

    @pytest.mark.asyncio
    async def test_get_prompt_defaults(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}
        client._transport = MagicMock()

        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}):
            result = await client.get_prompt("my_prompt")


# ═══ MCPClient.on_notification ═══

class TestOnNotification:
    """Tests for on_notification."""

    def test_register_handler(self):
        client = MCPClient()
        handler = AsyncMock()
        client.on_notification("notifications/tools/list_changed", handler)
        assert client._notification_handlers["notifications/tools/list_changed"] == [handler]

    def test_register_multiple_handlers_same_method(self):
        client = MCPClient()
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        client.on_notification("notifications/test", handler1)
        client.on_notification("notifications/test", handler2)
        assert len(client._notification_handlers["notifications/test"]) == 2

    def test_register_different_methods(self):
        client = MCPClient()
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        client.on_notification("notifications/a", handler1)
        client.on_notification("notifications/b", handler2)
        assert len(client._notification_handlers["notifications/a"]) == 1
        assert len(client._notification_handlers["notifications/b"]) == 1

    def test_register_no_handler_key(self):
        client = MCPClient()
        handler = AsyncMock()
        client.on_notification("notifications/new", handler)
        assert "notifications/new" in client._notification_handlers


# ═══ MCPClient._request ═══

class TestRequest:
    """Tests for _request method."""

    @pytest.mark.asyncio
    async def test_request_not_connected(self):
        client = MCPClient()
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await client._request("tools/list")

    @pytest.mark.asyncio
    async def test_request_success(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock()
        client._transport = mock_transport

        loop = asyncio.get_event_loop()

        async def mock_receive():
            # Simulate receiving the response
            await asyncio.sleep(0.01)
            return

        # We need to simulate the response arriving
        async def fake_receive():
            yield {"id": "test-id", "result": {"data": "value"}}

        mock_transport.receive = MagicMock(return_value=fake_receive())

        with patch("agentcrawl.agent.mcp_client._JsonRpc.request") as mock_req:
            mock_req.return_value = {"jsonrpc": "2.0", "id": "test-id", "method": "tools/list", "params": {}}

            # Schedule _handle_message to resolve the pending future that
            # _request creates. Since we bypass connect() (no listener task
            # is running), we must drive the response ourselves.
            response_message = {"id": "test-id", "result": {"data": "value"}}

            async def drive_response():
                await asyncio.sleep(0.01)
                await client._handle_message(response_message)

            asyncio.create_task(drive_response())
            result = await client._request("tools/list", {"key": "val"})

        assert result == {"data": "value"}
        mock_transport.send.assert_awaited_once()


# ═══ MCPClient._handle_message ═══

class TestHandleMessage:
    """Tests for _handle_message."""

    @pytest.mark.asyncio
    async def test_handle_response_success(self):
        client = MCPClient()
        client._connected = True
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        client._pending = {"req-1": future}

        message = {"id": "req-1", "result": {"data": "value"}}
        await client._handle_message(message)

        assert future.done()
        assert future.result() == {"data": "value"}
        # _handle_message resolves the future but does not remove it from
        # _pending; cleanup is the responsibility of _request's finally block.

    @pytest.mark.asyncio
    async def test_handle_response_error(self):
        client = MCPClient()
        client._connected = True
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        client._pending = {"req-2": future}

        message = {"id": "req-2", "error": {"code": -32601, "message": "Not found", "data": {"x": 1}}}
        await client._handle_message(message)

        assert future.done()
        exc = future.exception()
        assert isinstance(exc, MCPError)
        assert exc.code == -32601
        assert exc.data == {"x": 1}

    @pytest.mark.asyncio
    async def test_handle_response_no_future(self):
        client = MCPClient()
        client._connected = True
        client._pending = {}

        message = {"id": "nonexistent", "result": {}}
        # Should not raise
        await client._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_response_future_already_done(self):
        client = MCPClient()
        client._connected = True
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        future.set_result({"old": "data"})
        client._pending = {"req-3": future}

        message = {"id": "req-3", "result": {"new": "data"}}
        await client._handle_message(message)
        # Should not modify the already-done future
        assert future.result() == {"old": "data"}

    @pytest.mark.asyncio
    async def test_handle_notification(self):
        client = MCPClient()
        client._connected = True
        handler = AsyncMock()
        client._notification_handlers = {"notifications/test": [handler]}

        message = {"jsonrpc": "2.0", "method": "notifications/test", "params": {"key": "val"}}
        await client._handle_message(message)

        handler.assert_awaited_once_with({"key": "val"})

    @pytest.mark.asyncio
    async def test_handle_notification_handler_exception(self):
        client = MCPClient()
        client._connected = True

        handler = AsyncMock(side_effect=Exception("Handler failed"))
        client._notification_handlers = {"notifications/test": [handler]}

        message = {"jsonrpc": "2.0", "method": "notifications/test", "params": {}}
        # Should not raise
        await client._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_notification_no_handlers(self):
        client = MCPClient()
        client._connected = True
        client._notification_handlers = {}

        message = {"jsonrpc": "2.0", "method": "notifications/unknown", "params": {}}
        await client._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_server_request(self):
        client = MCPClient()
        client._connected = True
        client._transport = MagicMock()
        client._transport.send = AsyncMock()

        message = {"jsonrpc": "2.0", "id": "req-100", "method": "sampling/create"}
        await client._handle_message(message)

        client._transport.send.assert_awaited_once()


# ═══ MCPClient._listen ═══

class TestListen:
    """Tests for _listen method."""

    @pytest.mark.asyncio
    async def test_listen_message(self):
        client = MCPClient()
        client._connected = True

        async def mock_receive():
            yield {"id": "1", "result": {}}

        client._transport = MagicMock()
        client._transport.receive = MagicMock(return_value=mock_receive())

        async def handle_msg(msg):
            pass

        with patch.object(client, "_handle_message", side_effect=handle_msg):
            await client._listen()

    @pytest.mark.asyncio
    async def test_listen_cancelled(self):
        client = MCPClient()
        client._connected = True

        async def mock_receive():
            yield {}
            await asyncio.sleep(10)

        client._transport = MagicMock()
        client._transport.receive = MagicMock(return_value=mock_receive())

        with patch.object(client, "_handle_message", new_callable=AsyncMock):
            task = asyncio.create_task(client._listen())
            await asyncio.sleep(0.01)
            task.cancel()
            # _listen swallows CancelledError (see source: except CancelledError:
            # pass) so the task completes cleanly without re-raising.
            await task
            assert task.done()

    @pytest.mark.asyncio
    async def test_listen_connection_error(self):
        client = MCPClient()
        client._connected = True
        client._transport = MagicMock()

        async def raise_error():
            raise MCPConnectionError("Lost")

        client._transport.receive = MagicMock(return_value=raise_error())

        await client._listen()
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_listen_exception_disconnected(self):
        client = MCPClient()
        client._connected = True
        client._transport = MagicMock()

        async def raise_error():
            raise RuntimeError("Unexpected")

        client._transport.receive = MagicMock(return_value=raise_error())

        await client._listen()
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_listen_exception_not_connected(self):
        client = MCPClient()
        client._connected = False
        client._transport = MagicMock()

        async def raise_error():
            raise RuntimeError("Unexpected")

        client._transport.receive = MagicMock(return_value=raise_error())

        await client._listen()
        # Should not change _connected since it's already False


# ═══ MCPClient.reconnect ═══

class TestReconnect:
    """Tests for reconnect."""

    @pytest.mark.asyncio
    async def test_reconnect_success(self):
        client = MCPClient()
        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        mock_transport.disconnect = AsyncMock()
        mock_transport.is_connected = True
        client._transport = mock_transport

        init_response = {"serverInfo": {"name": "test", "version": "1.0"}}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=init_response):
            with patch.object(client, "_notify", new_callable=AsyncMock):
                with patch.object(client, "_listen", new_callable=AsyncMock):
                    with patch.object(client, "_create_transport", return_value=mock_transport):
                        await client.reconnect(max_retries=3, delay=0.001)

        assert client._connected is True

    @pytest.mark.asyncio
    async def test_reconnect_all_fail(self):
        client = MCPClient()

        with patch.object(client, "disconnect", new_callable=AsyncMock):
            with patch.object(client, "_create_transport") as mock_create:
                mock_transport = MagicMock()
                mock_transport.connect = AsyncMock(side_effect=MCPConnectionError("fail"))
                mock_transport.is_connected = False
                mock_create.return_value = mock_transport

                with pytest.raises(MCPConnectionError, match="Failed to reconnect"):
                    await client.reconnect(max_retries=3, delay=0.001)

    @pytest.mark.asyncio
    async def test_reconnect_retry_then_success(self):
        client = MCPClient()
        call_count = [0]

        with patch.object(client, "disconnect", new_callable=AsyncMock):
            with patch.object(client, "_create_transport") as mock_create:
                mock_transport = MagicMock()
                mock_transport.is_connected = True

                def side_effect(*args, **kwargs):
                    call_count[0] += 1
                    if call_count[0] == 1:
                        mock_transport.connect = AsyncMock(side_effect=MCPConnectionError("fail"))
                    else:
                        mock_transport.connect = AsyncMock()
                    return mock_transport

                mock_create.side_effect = side_effect

                init_response = {"serverInfo": {"name": "test", "version": "1.0"}}
                with patch.object(client, "_request", new_callable=AsyncMock, return_value=init_response):
                    with patch.object(client, "_notify", new_callable=AsyncMock):
                        with patch.object(client, "_listen", new_callable=AsyncMock):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                await client.reconnect(max_retries=3, delay=0.001)

        assert client._connected is True


# ═══ MCPClient.get_tool_names ═══

class TestGetToolNames:
    """Tests for get_tool_names."""

    def test_empty(self):
        client = MCPClient()
        assert client.get_tool_names() == []

    def test_with_cache(self):
        client = MCPClient()
        client._tools_cache = [
            MCPToolInfo(name="web_scrape", description="test", input_schema={}),
            MCPToolInfo(name="web_crawl", description="test", input_schema={}),
        ]
        names = client.get_tool_names()
        assert names == ["web_scrape", "web_crawl"]


# ═══ Factory functions ═══

class TestFactoryFunctions:
    """Tests for factory helpers."""

    def test_create_sse_client(self):
        client = create_sse_client(url="http://localhost:9000/sse")
        assert client._transport_type == TransportType.SSE
        assert client._url == "http://localhost:9000/sse"

    def test_create_sse_client_with_api_key(self):
        client = create_sse_client(api_key="secret")
        assert client._headers["Authorization"] == "Bearer secret"

    def test_create_websocket_client(self):
        client = create_websocket_client(url="ws://localhost:9000/ws")
        assert client._transport_type == TransportType.WEBSOCKET
        assert client._url == "ws://localhost:9000/ws"

    def test_create_websocket_client_with_api_key(self):
        client = create_websocket_client(api_key="secret")
        assert client._headers["Authorization"] == "Bearer secret"

    def test_create_stdio_client(self):
        client = create_stdio_client(command="agentcrawl", args=["mcp", "serve"])
        assert client._transport_type == TransportType.STDIO
        assert client._command == "agentcrawl"
        assert client._args == ["mcp", "serve"]

    def test_create_stdio_client_defaults(self):
        client = create_stdio_client()
        assert client._command == "agentcrawl"
        assert client._args == ["mcp", "serve"]
