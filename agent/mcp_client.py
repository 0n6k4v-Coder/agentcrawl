"""
AgentCrawl — MCP (Model Context Protocol) Client
==================================================

Connects AI Agents to an AgentCrawl MCP server via SSE, WebSocket, or stdio.

Usage:
    # SSE transport (remote server)
    async with MCPClient(transport="sse", url="http://localhost:8000/mcp/sse") as client:
        result = await client.call_tool("web_scrape", {"url": "https://example.com"})
        print(result)

    # WebSocket transport
    async with MCPClient(transport="websocket", url="ws://localhost:8000/mcp/ws") as client:
        tools = await client.list_tools()
        result = await client.call_tool("web_search", {"query": "Python asyncio"})

    # stdio transport (local process)
    async with MCPClient(transport="stdio", command="agentcrawl", args=["mcp", "serve"]) as client:
        result = await client.call_tool("web_map", {"url": "https://example.com"})

    # Manual lifecycle
    client = MCPClient(transport="sse", url="http://localhost:8000/mcp/sse")
    await client.connect()
    result = await client.call_tool("web_scrape", {"url": "https://example.com"})
    await client.disconnect()
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger("agentcrawl.mcp")


# ══════════════════════════════════════════════════════════════
# Types & Enums
# ══════════════════════════════════════════════════════════════

class TransportType(str, Enum):
    """Supported MCP transport types."""
    SSE = "sse"
    WEBSOCKET = "websocket"
    STDIO = "stdio"


class MCPError(Exception):
    """Base exception for MCP client errors."""

    def __init__(self, message: str, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class MCPConnectionError(MCPError):
    """Raised when connection to MCP server fails."""
    pass


class MCPToolError(MCPError):
    """Raised when a tool call returns an error."""
    pass


class MCPTimeoutError(MCPError):
    """Raised when a request times out."""
    pass


@dataclass
class MCPToolInfo:
    """Metadata about an available MCP tool."""
    name: str
    description: str
    input_schema: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPToolInfo:
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            input_schema=data.get("inputSchema", data.get("input_schema", {})),
        )


@dataclass
class MCPToolResult:
    """Result from an MCP tool call."""
    content: list[dict[str, Any]]
    is_error: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Extract concatenated text content from the result."""
        parts = []
        for item in self.content:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif item.get("type") == "image":
                parts.append(f"[image: {item.get('mimeType', 'unknown')}]")
            elif item.get("type") == "resource":
                parts.append(f"[resource: {item.get('uri', 'unknown')}]")
        return "\n".join(parts)

    @property
    def json_data(self) -> Any:
        """Try to parse the text content as JSON."""
        text = self.text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPToolResult:
        return cls(
            content=data.get("content", []),
            is_error=data.get("isError", False),
            raw=data,
        )


@dataclass
class MCPServerInfo:
    """Information about the connected MCP server."""
    name: str = ""
    version: str = ""
    protocol_version: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPServerInfo:
        server_info = data.get("serverInfo", {})
        return cls(
            name=server_info.get("name", ""),
            version=server_info.get("version", ""),
            protocol_version=data.get("protocolVersion", ""),
            capabilities=data.get("capabilities", {}),
        )


# ══════════════════════════════════════════════════════════════
# JSON-RPC Message Builder
# ══════════════════════════════════════════════════════════════

class _JsonRpc:
    """Helper for building JSON-RPC 2.0 messages."""

    @staticmethod
    def request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

    @staticmethod
    def notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

    @staticmethod
    def response(id: str, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": id,
            "result": result,
        }

    @staticmethod
    def error_response(id: str, code: int, message: str, data: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": id,
            "error": error,
        }


# ══════════════════════════════════════════════════════════════
# Transport Implementations
# ══════════════════════════════════════════════════════════════

class _BaseTransport:
    """Abstract base for MCP transports."""

    async def connect(self) -> None:
        raise NotImplementedError

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError
        yield  # pragma: no cover

    @property
    def is_connected(self) -> bool:
        raise NotImplementedError


class _SSETransport(_BaseTransport):
    """Server-Sent Events transport for MCP."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False
        self._message_endpoint: str | None = None
        self._sse_task: asyncio.Task | None = None
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout, connect=10.0),
        )
        # Connect to SSE endpoint to get the message endpoint
        try:
            async with self._client.stream("GET", self._url) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("event: endpoint"):
                        continue
                    if line.startswith("data: "):
                        endpoint = line[6:].strip()
                        if endpoint.startswith("/"):
                            # Relative path — resolve against base URL
                            base = self._url.rsplit("/", 1)[0]
                            self._message_endpoint = f"{base}{endpoint}"
                        else:
                            self._message_endpoint = endpoint
                        break

            if not self._message_endpoint:
                # Fallback: assume POST to same URL
                self._message_endpoint = self._url

            self._connected = True
            logger.info("SSE transport connected to %s", self._url)

        except httpx.HTTPError as e:
            raise MCPConnectionError(f"Failed to connect to SSE endpoint: {e}") from e

    async def disconnect(self) -> None:
        self._connected = False
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("SSE transport disconnected")

    async def send(self, message: dict[str, Any]) -> None:
        if not self._client or not self._message_endpoint:
            raise MCPConnectionError("Not connected")
        try:
            response = await self._client.post(
                self._message_endpoint,
                json=message,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MCPError(f"Failed to send message: {e}") from e

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._incoming.get(), timeout=1.0)
                yield msg
            except asyncio.TimeoutError:
                continue

    @property
    def is_connected(self) -> bool:
        return self._connected


class _WebSocketTransport(_BaseTransport):
    """WebSocket transport for MCP."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout
        self._ws: Any = None
        self._connected = False

    async def connect(self) -> None:
        try:
            import websockets
            self._ws = await websockets.connect(
                self._url,
                additional_headers=self._headers,
                open_timeout=self._timeout,
            )
            self._connected = True
            logger.info("WebSocket transport connected to %s", self._url)
        except ImportError:
            raise MCPConnectionError(
                "websockets package required. Install with: pip install websockets"
            )
        except Exception as e:
            raise MCPConnectionError(f"Failed to connect to WebSocket: {e}") from e

    async def disconnect(self) -> None:
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket transport disconnected")

    async def send(self, message: dict[str, Any]) -> None:
        if not self._ws:
            raise MCPConnectionError("Not connected")
        try:
            await self._ws.send(json.dumps(message))
        except Exception as e:
            raise MCPError(f"Failed to send message: {e}") from e

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        if not self._ws:
            return
        try:
            async for raw in self._ws:
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message: %s", raw[:200])
        except Exception as e:
            if self._connected:
                raise MCPConnectionError(f"WebSocket receive error: {e}") from e

    @property
    def is_connected(self) -> bool:
        return self._connected


class _StdioTransport(_BaseTransport):
    """stdio transport for MCP (spawns a local process)."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ):
        self._command = command
        self._args = args or []
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._connected = False

    async def connect(self) -> None:
        import os
        env = os.environ.copy()
        if self._env:
            env.update(self._env)

        try:
            self._process = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._connected = True
            logger.info(
                "stdio transport started: %s %s",
                self._command,
                " ".join(self._args),
            )
        except FileNotFoundError:
            raise MCPConnectionError(
                f"Command not found: {self._command}"
            )
        except Exception as e:
            raise MCPConnectionError(f"Failed to start process: {e}") from e

    async def disconnect(self) -> None:
        self._connected = False
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
        logger.info("stdio transport stopped")

    async def send(self, message: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise MCPConnectionError("Not connected")
        data = json.dumps(message) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        if not self._process or not self._process.stdout:
            return
        while self._connected:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=1.0,
                )
                if not line:
                    break
                try:
                    yield json.loads(line.decode().strip())
                except json.JSONDecodeError:
                    continue
            except asyncio.TimeoutError:
                continue

    @property
    def is_connected(self) -> bool:
        return self._connected


# ══════════════════════════════════════════════════════════════
# MCP Client
# ══════════════════════════════════════════════════════════════

class MCPClient:
    """
    MCP (Model Context Protocol) client for AgentCrawl.

    Supports SSE, WebSocket, and stdio transports.

    Args:
        transport: Transport type ('sse', 'websocket', 'stdio').
        url: Server URL (for SSE/WebSocket).
        command: Command to run (for stdio).
        args: Command arguments (for stdio).
        headers: Additional HTTP headers (for SSE/WebSocket).
        timeout: Request timeout in seconds.
        api_key: API key for authentication (sent as Bearer token).

    Example:
        >>> async with MCPClient(transport="sse", url="http://localhost:8000/mcp/sse") as client:
        ...     tools = await client.list_tools()
        ...     result = await client.call_tool("web_scrape", {"url": "https://example.com"})
        ...     print(result.text)
    """

    def __init__(
        self,
        transport: str | TransportType = TransportType.SSE,
        url: str = "http://localhost:8000/mcp/sse",
        command: str = "agentcrawl",
        args: list[str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
        api_key: str | None = None,
    ):
        self._transport_type = TransportType(transport)
        self._url = url
        self._command = command
        self._args = args or []
        self._timeout = timeout
        self._api_key = api_key

        # Build headers
        self._headers = headers or {}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

        # Create transport
        self._transport = self._create_transport()

        # State
        self._connected = False
        self._server_info: MCPServerInfo | None = None
        self._tools_cache: list[MCPToolInfo] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._listener_task: asyncio.Task | None = None
        self._notification_handlers: dict[str, list[Callable]] = {}

    def _create_transport(self) -> _BaseTransport:
        if self._transport_type == TransportType.SSE:
            return _SSETransport(
                url=self._url,
                headers=self._headers,
                timeout=self._timeout,
            )
        elif self._transport_type == TransportType.WEBSOCKET:
            return _WebSocketTransport(
                url=self._url,
                headers=self._headers,
                timeout=self._timeout,
            )
        elif self._transport_type == TransportType.STDIO:
            return _StdioTransport(
                command=self._command,
                args=self._args,
            )
        else:
            raise ValueError(f"Unsupported transport: {self._transport_type}")

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def connect(self) -> MCPServerInfo:
        """
        Connect to the MCP server and perform initialization handshake.

        Returns:
            Server information (name, version, capabilities).

        Raises:
            MCPConnectionError: If connection fails.
        """
        await self._transport.connect()
        self._connected = True

        # Start message listener
        self._listener_task = asyncio.create_task(self._listen())

        # Send initialize request
        init_result = await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "agentcrawl-mcp-client",
                    "version": "1.0.0",
                },
            },
        )

        self._server_info = MCPServerInfo.from_dict(init_result)

        # Send initialized notification
        await self._notify("notifications/initialized")

        logger.info(
            "Connected to MCP server: %s v%s (protocol %s)",
            self._server_info.name,
            self._server_info.version,
            self._server_info.protocol_version,
        )

        return self._server_info

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        self._connected = False

        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        # Cancel all pending requests
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

        await self._transport.disconnect()
        self._tools_cache = None
        self._server_info = None
        logger.info("Disconnected from MCP server")

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected and self._transport.is_connected

    @property
    def server_info(self) -> MCPServerInfo | None:
        """Information about the connected server."""
        return self._server_info

    # ──────────────────────────────────────────────────────────
    # Tool Operations
    # ──────────────────────────────────────────────────────────

    async def list_tools(self) -> list[MCPToolInfo]:
        """
        List all available tools on the MCP server.

        Returns:
            List of tool metadata (name, description, input schema).

        Example:
            >>> tools = await client.list_tools()
            >>> for tool in tools:
            ...     print(f"{tool.name}: {tool.description}")
        """
        if self._tools_cache is not None:
            return self._tools_cache

        result = await self._request("tools/list")
        tools_data = result.get("tools", [])
        self._tools_cache = [MCPToolInfo.from_dict(t) for t in tools_data]
        return self._tools_cache

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> MCPToolResult:
        """
        Call a tool on the MCP server.

        Args:
            name: Tool name (e.g., 'web_scrape', 'web_search').
            arguments: Tool arguments as a dictionary.
            timeout: Override default timeout for this call.

        Returns:
            MCPToolResult with content and error status.

        Raises:
            MCPToolError: If the tool returns an error.
            MCPTimeoutError: If the call times out.

        Example:
            >>> result = await client.call_tool("web_scrape", {
            ...     "url": "https://example.com",
            ...     "output_format": "markdown",
            ... })
            >>> print(result.text)
        """
        effective_timeout = timeout or self._timeout

        try:
            result = await asyncio.wait_for(
                self._request(
                    "tools/call",
                    {
                        "name": name,
                        "arguments": arguments or {},
                    },
                ),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            raise MCPTimeoutError(
                f"Tool call '{name}' timed out after {effective_timeout}s"
            )

        tool_result = MCPToolResult.from_dict(result)

        if tool_result.is_error:
            error_text = tool_result.text or "Unknown tool error"
            raise MCPToolError(f"Tool '{name}' returned error: {error_text}")

        return tool_result

    async def scrape(
        self,
        url: str,
        output_format: str = "markdown",
        **kwargs: Any,
    ) -> MCPToolResult:
        """
        Convenience method: scrape a single URL.

        Args:
            url: URL to scrape.
            output_format: Output format ('markdown', 'json', 'html').
            **kwargs: Additional arguments passed to web_scrape tool.

        Returns:
            MCPToolResult with scraped content.
        """
        args = {"url": url, "output_format": output_format, **kwargs}
        return await self.call_tool("web_scrape", args)

    async def crawl(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        **kwargs: Any,
    ) -> MCPToolResult:
        """
        Convenience method: crawl a website.

        Args:
            url: Starting URL.
            max_depth: Maximum crawl depth.
            max_pages: Maximum pages to crawl.
            **kwargs: Additional arguments passed to web_crawl tool.

        Returns:
            MCPToolResult with crawled content.
        """
        args = {
            "url": url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            **kwargs,
        }
        return await self.call_tool("web_crawl", args)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> MCPToolResult:
        """
        Convenience method: search the web.

        Args:
            query: Search query.
            max_results: Maximum results.
            **kwargs: Additional arguments passed to web_search tool.

        Returns:
            MCPToolResult with search results.
        """
        args = {"query": query, "max_results": max_results, **kwargs}
        return await self.call_tool("web_search", args)

    async def map_site(
        self,
        url: str,
        max_urls: int = 500,
        **kwargs: Any,
    ) -> MCPToolResult:
        """
        Convenience method: discover URLs on a website.

        Args:
            url: Website URL to map.
            max_urls: Maximum URLs to discover.
            **kwargs: Additional arguments passed to web_map tool.

        Returns:
            MCPToolResult with discovered URLs.
        """
        args = {"url": url, "max_urls": max_urls, **kwargs}
        return await self.call_tool("web_map", args)

    async def extract(
        self,
        url: str,
        schema: dict[str, Any],
        method: str = "llm",
        **kwargs: Any,
    ) -> MCPToolResult:
        """
        Convenience method: extract structured data from a URL.

        Args:
            url: URL to extract from.
            schema: JSON schema describing desired data.
            method: Extraction method ('llm', 'css', 'xpath').
            **kwargs: Additional arguments passed to web_extract tool.

        Returns:
            MCPToolResult with extracted data.
        """
        args = {"url": url, "schema": schema, "method": method, **kwargs}
        return await self.call_tool("web_extract", args)

    async def screenshot(
        self,
        url: str,
        full_page: bool = True,
        **kwargs: Any,
    ) -> MCPToolResult:
        """
        Convenience method: capture a screenshot.

        Args:
            url: URL to screenshot.
            full_page: Capture full page or viewport only.
            **kwargs: Additional arguments passed to web_screenshot tool.

        Returns:
            MCPToolResult with base64 image data.
        """
        args = {"url": url, "full_page": full_page, **kwargs}
        return await self.call_tool("web_screenshot", args)

    # ──────────────────────────────────────────────────────────
    # Resource & Prompt Operations (MCP standard)
    # ──────────────────────────────────────────────────────────

    async def list_resources(self) -> list[dict[str, Any]]:
        """List available resources on the MCP server."""
        result = await self._request("resources/list")
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI."""
        return await self._request("resources/read", {"uri": uri})

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List available prompts on the MCP server."""
        result = await self._request("prompts/list")
        return result.get("prompts", [])

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get a prompt by name."""
        return await self._request(
            "prompts/get",
            {"name": name, "arguments": arguments or {}},
        )

    # ──────────────────────────────────────────────────────────
    # Notifications
    # ──────────────────────────────────────────────────────────

    def on_notification(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Register a handler for server notifications.

        Args:
            method: Notification method name (e.g., 'notifications/tools/list_changed').
            handler: Async callback receiving the notification params.
        """
        if method not in self._notification_handlers:
            self._notification_handlers[method] = []
        self._notification_handlers[method].append(handler)

    # ──────────────────────────────────────────────────────────
    # Internal — JSON-RPC Communication
    # ──────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        if not self._connected:
            raise MCPConnectionError("Not connected to MCP server")

        message = _JsonRpc.request(method, params)
        request_id = message["id"]

        # Create a future for the response
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future

        try:
            await self._transport.send(message)
            result = await future
            return result
        finally:
            self._pending.pop(request_id, None)

    async def _notify(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._connected:
            raise MCPConnectionError("Not connected to MCP server")

        message = _JsonRpc.notification(method, params)
        await self._transport.send(message)

    async def _listen(self) -> None:
        """Background task: listen for incoming messages from the server."""
        try:
            async for message in self._transport.receive():
                await self._handle_message(message)
        except asyncio.CancelledError:
            pass
        except MCPConnectionError:
            if self._connected:
                logger.error("Connection lost to MCP server")
                self._connected = False
        except Exception as e:
            if self._connected:
                logger.error("Unexpected error in MCP listener: %s", e)
                self._connected = False

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Route an incoming JSON-RPC message to the appropriate handler."""
        # Response to a pending request
        if "id" in message and ("result" in message or "error" in message):
            request_id = message["id"]
            future = self._pending.get(request_id)
            if future and not future.done():
                if "error" in message:
                    error = message["error"]
                    future.set_exception(
                        MCPError(
                            error.get("message", "Unknown error"),
                            code=error.get("code"),
                            data=error.get("data"),
                        )
                    )
                else:
                    future.set_result(message.get("result", {}))
            return

        # Server notification
        if "method" in message and "id" not in message:
            method = message["method"]
            params = message.get("params", {})
            handlers = self._notification_handlers.get(method, [])
            for handler in handlers:
                try:
                    await handler(params)
                except Exception as e:
                    logger.error(
                        "Error in notification handler for %s: %s", method, e
                    )
            return

        # Server request (e.g., sampling, roots)
        if "method" in message and "id" in message:
            logger.warning(
                "Received server request '%s' — not supported by this client",
                message["method"],
            )
            # Respond with method not found
            error_response = _JsonRpc.error_response(
                message["id"],
                -32601,
                f"Method not supported: {message['method']}",
            )
            await self._transport.send(error_response)

    # ──────────────────────────────────────────────────────────
    # Reconnection
    # ──────────────────────────────────────────────────────────

    async def reconnect(self, max_retries: int = 3, delay: float = 2.0) -> None:
        """
        Attempt to reconnect to the MCP server.

        Args:
            max_retries: Maximum number of reconnection attempts.
            delay: Delay between attempts in seconds (doubles each retry).
        """
        await self.disconnect()

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("Reconnection attempt %d/%d...", attempt, max_retries)
                self._transport = self._create_transport()
                await self.connect()
                logger.info("Reconnected successfully")
                return
            except MCPConnectionError as e:
                logger.warning("Reconnection attempt %d failed: %s", attempt, e)
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2

        raise MCPConnectionError(
            f"Failed to reconnect after {max_retries} attempts"
        )

    # ──────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────

    def get_tool_names(self) -> list[str]:
        """
        Get cached tool names (call list_tools() first to populate cache).

        Returns:
            List of tool names, or empty list if not yet fetched.
        """
        if self._tools_cache is None:
            return []
        return [t.name for t in self._tools_cache]

    def __repr__(self) -> str:
        status = "connected" if self.is_connected else "disconnected"
        return (
            f"MCPClient(transport={self._transport_type.value!r}, "
            f"url={self._url!r}, status={status})"
        )


# ══════════════════════════════════════════════════════════════
# Factory Helpers
# ══════════════════════════════════════════════════════════════

def create_sse_client(
    url: str = "http://localhost:8000/mcp/sse",
    api_key: str | None = None,
    **kwargs: Any,
) -> MCPClient:
    """Create an MCP client using SSE transport."""
    return MCPClient(transport=TransportType.SSE, url=url, api_key=api_key, **kwargs)


def create_websocket_client(
    url: str = "ws://localhost:8000/mcp/ws",
    api_key: str | None = None,
    **kwargs: Any,
) -> MCPClient:
    """Create an MCP client using WebSocket transport."""
    return MCPClient(
        transport=TransportType.WEBSOCKET, url=url, api_key=api_key, **kwargs
    )


def create_stdio_client(
    command: str = "agentcrawl",
    args: list[str] | None = None,
    **kwargs: Any,
) -> MCPClient:
    """Create an MCP client using stdio transport (local process)."""
    return MCPClient(
        transport=TransportType.STDIO,
        command=command,
        args=args or ["mcp", "serve"],
        **kwargs,
    )


# ══════════════════════════════════════════════════════════════
# CLI — Quick test
# ══════════════════════════════════════════════════════════════

async def _main() -> None:
    """Quick connectivity test."""
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp/sse"
    transport = "websocket" if url.startswith("ws") else "sse"

    print(f"Connecting to {url} via {transport}...")

    async with MCPClient(transport=transport, url=url) as client:
        print(f"✓ Connected: {client.server_info}")

        tools = await client.list_tools()
        print(f"✓ Available tools ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:80]}...")

        print("\nTesting web_scrape...")
        result = await client.scrape("https://example.com")
        print(f"✓ Result ({len(result.text)} chars):")
        print(result.text[:300])


if __name__ == "__main__":
    asyncio.run(_main())
