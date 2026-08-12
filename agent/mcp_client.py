"""AgentCrawl — MCP (Model Context Protocol) Client
==================================================

Connects AI agents to an AgentCrawl MCP server using the **official MCP SDK
2.0.0** client primitives.  The legacy custom SSE / WebSocket / JSON-RPC
machinery has been removed (Set C migration); this module now delegates
transport, protocol framing, and negotiation to the MCP SDK.

Transports:

* **Streamable HTTP** — connects to the ``/mcp`` endpoint exposed by
  :mod:`server.mcp.server`.  This is the modern MCP network transport.
* **stdio** — spawns a local MCP server subprocess (the Set B server in
  stdio mode).

Tool contract:

The client recognises the **canonical** six-tool contract defined in
:mod:`server.mcp.tools`:

    scrape_webpage, search_web, crawl_website,
    discover_urls, extract_data, batch_scrape

There are no legacy ``web_*`` names and no ``web_screenshot`` — the client
mirrors the server's single source of truth.

Usage::

    # Streamable HTTP transport (modern MCP network transport)
    async with MCPClient(transport="http", url="http://localhost:9000/mcp") as client:
        result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        print(result.text)

    # stdio transport (local subprocess)
    async with MCPClient(transport="stdio", command="python", args=["-m", "server.mcp.server"]) as client:
        tools = await client.list_tools()
        result = await client.call_tool("search_web", {"query": "Python asyncio"})

    # Convenience wrappers
    result = await client.scrape("https://example.com")
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from mcp.client._probe import negotiate_auto
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

if TYPE_CHECKING:
    from mcp.types import InitializeResult, Tool

logger = logging.getLogger("agentcrawl.mcp")

# AnyIO cancel-scope cancellation message prefix.  When the MCP SDK's anyio
# task-group/cancel-scope tears down a failed Streamable HTTP transport it
# surfaces an ``asyncio.CancelledError`` whose message begins with this exact
# prefix (e.g. ``"Cancelled via cancel scope 0xabc123"``).  This is an INTERNAL
# transport failure, not a caller-requested cancellation, and must be translated
# to ``MCPConnectionError``.
#
# Python permits ``task.cancel()`` AND ``task.cancel("reason")`` — both are
# EXTERNAL cancellations that must propagate as ``asyncio.CancelledError``.
# Relying on message emptiness (``not str(err)``) wrongly classifies a
# non-empty external reason string as internal.  Instead we positively identify
# the internal AnyIO cancellation using the same prefix AnyIO exposes via its
# own ``is_anyio_cancellation`` helper (anyio/_backends/_asyncio.py).  This
# mirrors AnyIO's public logic without importing private backend modules.
_ANYIO_CANCEL_SCOPE_PREFIX = "Cancelled via cancel scope "


def _is_internal_cancellation(err: BaseException) -> bool:
    """Return True if *err* is an internal AnyIO cancel-scope cancellation.

    Internal cancellations originate from the MCP SDK's AnyIO task-group /
    cancel-scope teardown (e.g. when a Streamable HTTP transport is refused or
    torn down mid-operation).  AnyIO raises a ``CancelledError`` whose message
    begins with ``_ANYIO_CANCEL_SCOPE_PREFIX``.

    External cancellations — ``task.cancel()`` and ``task.cancel("reason")`` —
    are NOT internal.  They carry an arbitrary user-supplied message (or an
    empty one) and must propagate to the caller as ``CancelledError``.

    This positively matches the prefix AnyIO exposes via its own
    ``is_anyio_cancellation`` predicate, mirroring AnyIO's logic without
    importing private backend modules.
    """
    return isinstance(err, asyncio.CancelledError) and str(err).startswith(
        _ANYIO_CANCEL_SCOPE_PREFIX
    )


# ───────────────────────────────────────────────────────────
# Canonical tool names — imported from the server's single
# source of truth so the client and server can never diverge.
# ───────────────────────────────────────────────────────────

try:
    from server.mcp.tools import CANONICAL_TOOL_ORDER as _CANONICAL_TOOL_ORDER
except ImportError:
    # Fallback when the server package is not importable (e.g. the client is
    # used standalone against a remote server).  The canonical names are
    # frozen here and must match ``server.mcp.tools``.
    _CANONICAL_TOOL_ORDER = [
        "scrape_webpage",
        "search_web",
        "crawl_website",
        "discover_urls",
        "extract_data",
        "batch_scrape",
    ]

#: Deterministic, canonical ordering of MCP tool names.
CANONICAL_TOOL_ORDER: list[str] = list(_CANONICAL_TOOL_ORDER)

#: Deprecated alias for backward compatibility.
TOOL_NAMES: list[str] = list(_CANONICAL_TOOL_ORDER)


# ══════════════════════════════════════════════════════════════
# TransportType
# ══════════════════════════════════════════════════════════════


class TransportType(str, Enum):
    """Supported MCP transport types."""

    HTTP = "http"
    STDIO = "stdio"

    @classmethod
    def _missing_(cls, value: object) -> TransportType | None:
        """Allow legacy aliases to resolve to the modern transport.

        ``sse`` and ``websocket`` are accepted but mapped to the modern
        Streamable HTTP transport, since the legacy transports have been
        removed.  ``websocket`` is accepted purely for backward-compat with
        old constructor calls.
        """
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in ("http", "streamable_http", "streamable-http", "sse"):
                return cls.HTTP
            if lowered == "websocket":
                return cls.HTTP
        return None


# ══════════════════════════════════════════════════════════════
# Exceptions
# ══════════════════════════════════════════════════════════════


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


# ══════════════════════════════════════════════════════════════
# Public data wrappers (kept for backward compatibility)
# ══════════════════════════════════════════════════════════════


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

    @classmethod
    def from_mcp_tool(cls, tool: Tool) -> MCPToolInfo:
        """Build from an MCP SDK ``Tool`` object (``tools/list`` result)."""
        return cls(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.input_schema or {},
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
    def from_initialize_result(cls, result: InitializeResult) -> MCPServerInfo:
        """Build from an MCP SDK ``InitializeResult``."""
        caps = result.capabilities
        if caps and hasattr(caps, "model_dump"):
            caps = caps.model_dump()
        return cls(
            name=result.server_info.name if result.server_info else "",
            version=result.server_info.version if result.server_info else "",
            protocol_version=result.protocol_version,
            capabilities=dict(caps or {}),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPServerInfo:
        server_info = data.get("serverInfo", {})
        return cls(
            name=server_info.get("name", ""),
            version=server_info.get("version", ""),
            protocol_version=data.get("protocolVersion", ""),
            capabilities=data.get("capabilities", {}),
        )


def _result_to_dict(result: Any) -> dict[str, Any]:
    """Convert an SDK result object (``CallToolResult``, ``ListToolsResult``,
    etc.) to a plain dict for the legacy ``from_dict``-style wrappers."""
    if hasattr(result, "model_dump"):
        dumped = result.model_dump()
        # Normalize is_error -> isError for CallToolResult compatibility.
        if "is_error" in dumped and "isError" not in dumped:
            dumped["isError"] = dumped["is_error"]
        return dumped
    return dict(getattr(result, "__dict__", {}))


# ══════════════════════════════════════════════════════════════
# MCP Client
# ══════════════════════════════════════════════════════════════


class MCPClient:
    """MCP (Model Context Protocol) client for AgentCrawl.

    Uses the official MCP SDK 2.0.0 client primitives for all transport
    and protocol behaviour.  Supports Streamable HTTP (``/mcp`` endpoint)
    and stdio transports.

    Args:
        transport: Transport type — ``"http"`` (Streamable HTTP, default)
            or ``"stdio"``.  Legacy aliases ``\"sse\"`` and ``"websocket\"`
            are accepted and mapped to ``http``.
        url: Server URL for Streamable HTTP (default ``http://localhost:8080/mcp``).
        command: Command to run for stdio transport.
        args: Command arguments for stdio transport.
        headers: Additional HTTP headers for Streamable HTTP.
        timeout: Request timeout in seconds.
        api_key: API key sent as a Bearer token.

    Example::

        >>> async with MCPClient(transport="http", url="http://localhost:9000/mcp") as client:
        ...     tools = await client.list_tools()
        ...     result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        ...     print(result.text)
    """

    def __init__(
        self,
        transport: str | TransportType = TransportType.HTTP,
        url: str = "http://localhost:8080/mcp",
        command: str = "python",
        args: list[str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
        api_key: str | None = None,
    ):
        self._transport_type = TransportType(transport)
        self._url = url
        self._command = command
        self._args = args or ["-m", "server.mcp.server"]
        self._timeout = timeout
        self._api_key = api_key

        # Build headers
        self._headers: dict[str, str] = headers or {}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

        # State
        self._connected = False
        self._server_info: MCPServerInfo | None = None
        self._tools_cache: list[MCPToolInfo] | None = None
        self._session: ClientSession | None = None
        self._transport_cm: Any = None  # transport async context manager

    # ─────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────

    async def connect(self) -> MCPServerInfo:
        """Connect to the MCP server and perform protocol negotiation.

        Protocol negotiation follows the MCP 2.0.0 ``mode='auto'`` policy:
        a ``server/discover`` probe is sent at the newest modern protocol
        version (``2026-07-28``).  If the server advertises modern versions
        the client adopts the negotiated era directly; otherwise it falls
        back to the legacy ``initialize`` handshake.  The negotiated
        protocol version is discoverable via :attr:`protocol_version`.

        Returns:
            Server information (name, version, capabilities, protocol version).

        Raises:
            MCPConnectionError: If connection or negotiation fails.
        """
        try:
            if self._transport_type == TransportType.STDIO:
                server_params = StdioServerParameters(
                    command=self._command,
                    args=self._args,
                )
                cm = stdio_client(server_params)
            else:
                # Streamable HTTP — build an httpx2 client with auth headers.
                import httpx2

                http_client = httpx2.AsyncClient(
                    headers=self._headers or None,
                    timeout=httpx2.Timeout(self._timeout, connect=10.0),
                )
                cm = streamable_http_client(self._url, http_client=http_client)

            self._transport_cm = cm
            read_stream, write_stream = await cm.__aenter__()

            self._session = ClientSession(read_stream=read_stream, write_stream=write_stream)
            await self._session.__aenter__()

            # Use the MCP SDK's approved auto-negotiation: probes
            # server/discover at the modern era (2026-07-28) and falls back
            # to the legacy initialize handshake only for legacy-only servers.
            async with asyncio.timeout(self._timeout):
                await negotiate_auto(self._session)

            # Build server info from the negotiated session state.
            negotiated = self._session.protocol_version
            caps = self._session.server_capabilities
            if caps is not None and hasattr(caps, "model_dump"):
                caps = caps.model_dump()
            if self._session._discover_result is not None:
                si = self._session.server_info
                self._server_info = MCPServerInfo(
                    name=si.name if si else "",
                    version=si.version if si else "",
                    protocol_version=negotiated or "",
                    capabilities=dict(caps or {}),
                )
            elif self._session._initialize_result is not None:
                init_result = self._session._initialize_result
                self._server_info = MCPServerInfo.from_initialize_result(init_result)
            else:
                self._server_info = MCPServerInfo(protocol_version=negotiated or "")
            self._connected = True
            self._tools_cache = None

            logger.info(
                "Connected to MCP server: %s v%s (protocol %s)",
                self._server_info.name,
                self._server_info.version,
                self._server_info.protocol_version,
            )
            return self._server_info

        except asyncio.TimeoutError as err:
            await self._cleanup()
            raise MCPTimeoutError(f"Connection timed out after {self._timeout}s") from err
        except asyncio.CancelledError as err:
            # Distinguish EXTERNAL caller cancellation from INTERNAL AnyIO/MCP
            # cancellation (transport teardown).  Python permits both
            # ``task.cancel()`` and ``task.cancel("reason")`` — BOTH are
            # external cancellations that MUST propagate as
            # ``asyncio.CancelledError`` so the caller's cooperative-cancellation
            # semantics are preserved.  Relying on message emptiness
            # (``not str(err)``) is unsafe because ``task.cancel("reason")``
            # carries a non-empty message yet is still external.
            #
            # Internal cancellation originates from the MCP SDK's AnyIO
            # task-group / cancel-scope teardown (e.g. a refused Streamable HTTP
            # connection).  AnyIO raises a ``CancelledError`` whose message
            # begins with ``_ANYIO_CANCEL_SCOPE_PREFIX`` ("Cancelled via cancel
            # scope <id>").  We positively identify that prefix — mirroring
            # AnyIO's own public ``is_anyio_cancellation`` predicate — and only
            # then translate it to ``MCPConnectionError``.
            #
            # Python 3.11+: ``asyncio.timeout()`` already converts a
            # timeout-fired cancellation to ``TimeoutError`` (handled above), so
            # any ``CancelledError`` reaching here is either an external caller
            # cancellation or an internal transport-failure cancellation.
            if _is_internal_cancellation(err):
                # Internal AnyIO cancel-scope cancellation from transport
                # failure → translate to an application-level connection error.
                # Consume the cancel count so asyncio does not re-raise it
                # after we translate the error.
                task = asyncio.current_task()
                if task is not None:
                    _uncancel = getattr(task, "uncancel", None)
                    if _uncancel is not None:
                        _uncancel()
                await self._cleanup()
                raise MCPConnectionError(f"Failed to connect to MCP server: {err}") from err
            # External cancellation (task.cancel() / task.cancel("reason")):
            # re-raise so the caller observes CancelledError.  Cleanup runs but
            # must NOT swallow the original exception.
            await self._cleanup()
            raise
        except MCPError:
            await self._cleanup()
            raise
        except Exception as err:
            await self._cleanup()
            raise MCPConnectionError(f"Failed to connect to MCP server: {err}") from err

    async def disconnect(self) -> None:
        """Disconnect from the MCP server and clean up all resources."""
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Tear down session, transport, and caches."""
        self._connected = False

        # Close the ClientSession (cancels its task group).
        if self._session is not None:
            # Suppress BaseException (not just Exception) because the MCP
            # SDK's anyio TaskGroup.__aexit__ can raise CancelledError or
            # ExceptionGroup during teardown — these must not mask the
            # original connection error that triggered cleanup.
            with contextlib.suppress(BaseException):
                await self._session.__aexit__(None, None, None)
            self._session = None

        # Exit the transport context manager (closes streams / process).
        if self._transport_cm is not None:
            # Same rationale: the StreamableHTTPTransport's task-group exit
            # can surface CancelledError/ExceptionGroup on a failed connection.
            with contextlib.suppress(BaseException):
                await self._transport_cm.__aexit__(None, None, None)
            self._transport_cm = None

        self._tools_cache = None
        self._server_info = None
        logger.info("Disconnected from MCP server")

    async def _safe_cleanup(self) -> None:
        """Call ``_cleanup()`` without masking an in-flight exception.

        ``_cleanup()`` already suppresses ``BaseException`` from the SDK
        teardowns, so this wrapper exists purely for readability at call
        sites and to guarantee idempotency — calling it multiple times (or
        after a partial failure) is always safe.
        """
        await self._cleanup()

    async def _execute_session_op(
        self,
        op_name: str,
        coro: Any,
        timeout: float | None = None,
    ) -> Any:
        """Execute an MCP session operation with full lifecycle safety.

        Wraps *coro* (a bound ``self._session.<method>`` call) with:

        * timeout enforcement (via ``asyncio.timeout``) → ``MCPTimeoutError``
          (session is preserved; only the operation was slow)
        * internal AnyIO cancel-scope cancellation → ``MCPConnectionError``
          + cleanup (transport failure mid-operation)
        * external caller cancellation → clean up + re-raise (no resource leak)
        * SDK/runtime exceptions → ``MCPConnectionError`` + cleanup (session
          is broken)

        On transport-level or external-cancellation failures the client is
        cleaned up so that no stale session or transport remains in a
        corrupted state (AC-04, AC-05, AC-06, AC-07).  A pure timeout does
        NOT tear down the session — the connection may still be usable.

        Args:
            op_name: Human-readable operation name for error messages.
            coro: The coroutine to execute (e.g. ``self._session.list_tools()``).
            timeout: Optional per-call timeout override; defaults to
                ``self._timeout``.
        """
        effective_timeout = timeout if timeout is not None else self._timeout
        try:
            async with asyncio.timeout(effective_timeout):
                return await coro
        except asyncio.TimeoutError as err:
            # A timeout means the operation was slow, not that the transport
            # is broken.  The session remains usable for subsequent calls.
            raise MCPTimeoutError(f"{op_name} timed out after {effective_timeout}s") from err
        except asyncio.CancelledError as err:
            if _is_internal_cancellation(err):
                task = asyncio.current_task()
                if task is not None:
                    _uncancel = getattr(task, "uncancel", None)
                    if _uncancel is not None:
                        _uncancel()
                await self._safe_cleanup()
                raise MCPConnectionError(f"Error in {op_name}: {err}") from err
            await self._safe_cleanup()
            raise
        except Exception as err:
            await self._safe_cleanup()
            raise MCPConnectionError(f"Error in {op_name}: {err}") from err

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected and self._session is not None

    @property
    def server_info(self) -> MCPServerInfo | None:
        """Information about the connected server."""
        return self._server_info

    @property
    def protocol_version(self) -> str | None:
        """The negotiated MCP protocol version (e.g. ``2026-07-28``).

        Returns ``None`` until :meth:`connect` completes the negotiation.
        After a successful ``mode='auto'`` negotiation the value reflects
        the era agreed with the server (modern ``2026-07-28`` for an
        MCP 2.0.0 server, or a legacy version for older peers).
        """
        if self._session is not None:
            return self._session.protocol_version
        return None

    # ─────────────────────────────────────────────────────────
    # Tool Operations
    # ─────────────────────────────────────────────────────────

    async def list_tools(self) -> list[MCPToolInfo]:
        """List all available tools on the MCP server.

        Returns:
            List of tool metadata (name, description, input schema).

        Raises:
            MCPConnectionError: If not connected or the session operation fails.
            MCPTimeoutError: If the operation times out.
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError("Not connected to MCP server")

        if self._tools_cache is not None:
            return self._tools_cache

        result = await self._execute_session_op("list_tools", self._session.list_tools())
        self._tools_cache = [MCPToolInfo.from_mcp_tool(t) for t in result.tools]
        return self._tools_cache

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> MCPToolResult:
        """Call a tool on the MCP server.

        Args:
            name: Tool name (e.g., ``scrape_webpage``).
            arguments: Tool arguments as a dictionary.
            timeout: Override default timeout for this call.

        Returns:
            MCPToolResult with content and error status.

        Raises:
            MCPToolError: If the tool returns an error.
            MCPTimeoutError: If the call times out.
            MCPConnectionError: If not connected.
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError("Not connected to MCP server")

        effective_timeout = timeout if timeout is not None else self._timeout

        result = await self._execute_session_op(
            f"call_tool:{name}",
            self._session.call_tool(name, arguments or {}),
            timeout=effective_timeout,
        )

        # The SDK returns a CallToolResult.  If the tool raised a server-side
        # error it is signalled via ``is_error`` + an ``ErrorData`` content
        # block.  An unknown-tool or invalid-param failure may surface as a
        # raw ``MCPError`` from the dispatcher — catch that.
        if result.is_error:
            error_text = _extract_error_text(result)
            raise MCPToolError(f"Tool '{name}' returned error: {error_text}")

        return MCPToolResult(
            content=[_content_to_dict(c) for c in result.content],
            is_error=False,
            raw=_result_to_dict(result),
        )

    # ─────────────────────────────────────────────────────────
    # Convenience Methods — mapped to canonical tool names
    # ─────────────────────────────────────────────────────────

    async def scrape(
        self,
        url: str,
        include_links: bool = False,
        only_main_content: bool = True,
        **kwargs: Any,
    ) -> MCPToolResult:
        """Convenience method: scrape a single URL (``scrape_webpage``)."""
        args: dict[str, Any] = {
            "url": url,
            "include_links": include_links,
            "only_main_content": only_main_content,
        }
        args.update(kwargs)
        return await self.call_tool("scrape_webpage", args)

    async def crawl(
        self,
        url: str,
        max_pages: int = 10,
        max_depth: int = 2,
        **kwargs: Any,
    ) -> MCPToolResult:
        """Convenience method: crawl a website (``crawl_website``)."""
        args: dict[str, Any] = {
            "url": url,
            "max_pages": max_pages,
            "max_depth": max_depth,
        }
        args.update(kwargs)
        return await self.call_tool("crawl_website", args)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> MCPToolResult:
        """Convenience method: search the web (``search_web``)."""
        args: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
        }
        args.update(kwargs)
        return await self.call_tool("search_web", args)

    async def discover(
        self,
        url: str,
        max_urls: int = 100,
        **kwargs: Any,
    ) -> MCPToolResult:
        """Convenience method: discover URLs on a site (``discover_urls``)."""
        args: dict[str, Any] = {"url": url, "max_urls": max_urls}
        args.update(kwargs)
        return await self.call_tool("discover_urls", args)

    async def extract(
        self,
        url: str,
        fields: str,
        **kwargs: Any,
    ) -> MCPToolResult:
        """Convenience method: extract structured data (``extract_data``).

        Args:
            url: The URL to extract from.
            fields: Comma-separated field names to extract
                (e.g. ``"title,price,description"``).
            **kwargs: Additional arguments forwarded to the tool.
        """
        args: dict[str, Any] = {"url": url, "fields": fields}
        args.update(kwargs)
        return await self.call_tool("extract_data", args)

    async def batch_scrape(
        self,
        urls: list[str],
        only_main_content: bool = True,
        **kwargs: Any,
    ) -> MCPToolResult:
        """Convenience method: scrape multiple URLs at once (``batch_scrape``)."""
        args: dict[str, Any] = {
            "urls": urls,
            "only_main_content": only_main_content,
        }
        args.update(kwargs)
        return await self.call_tool("batch_scrape", args)

    # ─────────────────────────────────────────────────────────
    # Resource & Prompt Operations (MCP standard)
    # ─────────────────────────────────────────────────────────

    async def list_resources(self) -> list[dict[str, Any]]:
        """List available resources on the MCP server.

        Raises:
            MCPConnectionError: If not connected or the session operation fails.
            MCPTimeoutError: If the operation times out.
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError("Not connected to MCP server")
        result = await self._execute_session_op("list_resources", self._session.list_resources())
        return [r.model_dump() for r in result.resources]

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI.

        Raises:
            MCPConnectionError: If not connected or the session operation fails.
            MCPTimeoutError: If the operation times out.
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError("Not connected to MCP server")
        result = await self._execute_session_op("read_resource", self._session.read_resource(uri))
        return result.model_dump()

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List available prompts on the MCP server.

        Raises:
            MCPConnectionError: If not connected or the session operation fails.
            MCPTimeoutError: If the operation times out.
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError("Not connected to MCP server")
        result = await self._execute_session_op("list_prompts", self._session.list_prompts())
        return [p.model_dump() for p in result.prompts]

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get a prompt by name.

        Raises:
            MCPConnectionError: If not connected or the session operation fails.
            MCPTimeoutError: If the operation times out.
        """
        if not self._connected or self._session is None:
            raise MCPConnectionError("Not connected to MCP server")
        result = await self._execute_session_op(
            "get_prompt", self._session.get_prompt(name, arguments or {})
        )
        return result.model_dump()

    # ─────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────

    def get_tool_names(self) -> list[str]:
        """Get cached tool names (call ``list_tools()`` first to populate).

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
# Content helpers
# ══════════════════════════════════════════════════════════════


def _content_to_dict(content: Any) -> dict[str, Any]:
    """Convert an MCP SDK content item (TextContent, ImageContent, etc.) to a
    plain dict compatible with the legacy ``MCPToolResult.content`` shape."""
    if isinstance(content, dict):
        return content
    if hasattr(content, "model_dump"):
        d = content.model_dump()
        # Ensure "type" key exists for the text property logic.
        if "type" not in d and hasattr(content, "type"):
            d["type"] = content.type
        return d
    return {"type": "text", "text": str(content)}


def _extract_error_text(result: Any) -> str:
    """Pull a human-readable error message from an error ``CallToolResult``."""
    for c in result.content:
        d = _content_to_dict(c)
        if d.get("type") == "text":
            return d.get("text", "")
    return "Unknown tool error"


# ══════════════════════════════════════════════════════════════
# Factory Helpers
# ══════════════════════════════════════════════════════════════


def create_http_client(
    url: str = "http://localhost:8080/mcp",
    api_key: str | None = None,
    **kwargs: Any,
) -> MCPClient:
    """Create an MCP client using Streamable HTTP transport.

    This is the modern MCP network transport.  The client connects to the
    server's ``/mcp`` Streamable HTTP endpoint.
    """
    return MCPClient(transport=TransportType.HTTP, url=url, api_key=api_key, **kwargs)


def create_stdio_client(
    command: str = "python",
    args: list[str] | None = None,
    **kwargs: Any,
) -> MCPClient:
    """Create an MCP client using stdio transport (local process).

    Args:
        command: Command to run (default ``python``).
        args: Command arguments (default ``[\"-m\", \"server.mcp.server\"]``).
    """
    return MCPClient(
        transport=TransportType.STDIO,
        command=command,
        args=args or ["-m", "server.mcp.server"],
        **kwargs,
    )


# Backwards-compatible aliases for legacy factory names.
# ``create_sse_client`` now maps to Streamable HTTP (the modern transport).
create_sse_client = create_http_client


def create_websocket_client(
    url: str = "ws://localhost:8000/mcp",
    api_key: str | None = None,
    **kwargs: Any,
) -> MCPClient:
    """Deprecated: WebSocket transport is no longer supported.

    Returns a Streamable HTTP client instead, since the legacy WebSocket
    transport has been removed.  Use :func:`create_http_client` directly.
    """
    logger.warning(
        "create_websocket_client is deprecated; returning an HTTP client. "
        "The WebSocket transport has been removed in favor of Streamable HTTP."
    )
    return create_http_client(
        url.replace("ws://", "http://").replace("wss://", "https://"),
        api_key,
        **kwargs,
    )


# ══════════════════════════════════════════════════════════════
# CLI — Quick test
# ══════════════════════════════════════════════════════════════


async def _main() -> None:
    """Quick connectivity test."""
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080/mcp"

    print(f"Connecting to {url} via Streamable HTTP...")
    async with MCPClient(transport="http", url=url) as client:
        print(f"✓ Connected: {client.server_info}")

        tools = await client.list_tools()
        print(f"✓ Available tools ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:80]}...")

        print("\nTesting scrape_webpage...")
        result = await client.scrape("https://example.com")
        print(f"✓ Result ({len(result.text)} chars):")
        print(result.text[:300])


if __name__ == "__main__":
    asyncio.run(_main())
