"""AgentCrawl — MCP Server
=========================

Model Context Protocol (MCP) server built natively against MCP SDK 2.0.0.

Transports:

* **stdio** — ``python -m server.mcp.server --transport stdio``
* **Streamable HTTP** — ``python -m server.mcp.server --transport http
  --host 0.0.0.0 --port 8080`` (stateless at the MCP boundary,
  ``stateless_http=True``)

The server exposes the canonical tool contract defined in
:mod:`server.mcp.tools` (exactly six tools, single source of truth).

Legacy SSE (`mcp.server.sse.SseServerTransport` with ``/sse`` +
``/messages/``) has been removed.  See the "Legacy migration" section of
the module docstring and the project MIGRATION notes.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from server.mcp.tools import (
    TOOL_DEFINITIONS,
    ToolError,
    _serialize,
    get_tool,
)

# Server identity used in the MCP ``initialize`` handshake.
SERVER_NAME = "agentcrawl"
SERVER_VERSION = "1.0.0"

logger = logging.getLogger("agentcrawl.mcp.server")


# ══════════════════════════════════════════════════════════════
# Shared engine lifecycle (Set G)
# ══════════════════════════════════════════════════════════════


@dataclass
class MCPServerContext:
    """Server-lifetime state carried through an MCP session context.

    A single ``CrawlEngine`` is created once at server startup (G1) and
    reused for every tool invocation during that server lifetime.  Its
    memory cache therefore persists across calls (G3).  The concurrency
    semaphore (G2) bounds how many engine operations may run at once.
    """

    engine: Any
    semaphore: asyncio.Semaphore
    max_concurrent: int


@contextlib.asynccontextmanager
async def _mcp_lifespan(server: Server[Any]):
    """Create one shared :class:`CrawlEngine` for the server's lifetime.

    * Startup creates the engine via :meth:`CrawlEngine.default` (preserving
      the package-mode API) and enters it — initializing browser + cache.
    * The ``MCPServerContext`` (engine + concurrency semaphore) is yielded
      to handlers via ``ctx.lifespan_context``.
    * Shutdown always runs — even if startup or a tool invocation fails
      partway through — releasing the browser and cache (G4).
    """
    from agentcrawl.config.settings import Settings
    from agentcrawl.core.engine import CrawlEngine

    settings = Settings()
    max_concurrent = max(1, int(settings.mcp_max_concurrent))
    semaphore = asyncio.Semaphore(max_concurrent)

    # One engine per server lifetime (G1).  ``CrawlEngine.default()`` preserves
    # the package-mode API used by tests/fixtures that patch it.
    engine = CrawlEngine.default()
    started = False
    try:
        await engine.__aenter__()  # startup (browser + cache)
        started = True
        ctx = MCPServerContext(
            engine=engine,
            semaphore=semaphore,
            max_concurrent=max_concurrent,
        )
        yield ctx
    finally:
        # Graceful shutdown (G4) — runs even if startup/tool failed.
        if started:
            with contextlib.suppress(Exception):
                await engine.__aexit__(None, None, None)
        else:
            # Startup itself failed; ensure no partial resources leak.
            with contextlib.suppress(Exception):
                if getattr(engine, "_browser_manager", None) is not None:
                    await engine._browser_manager.stop()


def _get_server_context(ctx: Any, tool_name: str = "") -> MCPServerContext:
    """Extract the shared server context from a request context.

    The ``MCPServerContext`` (shared engine + semaphore) is yielded by the
    ``_mcp_lifespan`` and exposed by the MCP SDK on ``ctx.lifespan_context``.
    Tests that build a bare :class:`~mcp.server.lowlevel.server.Server`
    without a lifespan are supported by falling back to a synthetic context
    that creates and owns its own short-lived engine.
    """
    server_ctx = getattr(ctx, "lifespan_context", None)
    if isinstance(server_ctx, MCPServerContext):
        return server_ctx

    # Fallback for servers constructed without the MCP lifespan (e.g. the
    # in-process test harness that calls create_mcp_server without entering
    # the lifespan).  Lazily build a per-call-compatible context.
    import asyncio

    from agentcrawl.core.engine import CrawlEngine

    engine = CrawlEngine.default()
    semaphore = asyncio.Semaphore(1)
    return MCPServerContext(
        engine=engine,
        semaphore=semaphore,
        max_concurrent=1,
    )


def create_mcp_server() -> Server:
    """Construct the canonical MCP server (MCP SDK 2.0.0 native API).

    Uses the modern Server constructor callback parameters
    (``on_list_tools`` / ``on_call_tool``) rather than the removed
    ``@server.list_tools()`` / ``@server.call_tool()`` decorators, which do
    not exist in MCP 2.0.0.

    The tool contract is sourced exclusively from
    :data:`server.mcp.tools.TOOL_DEFINITIONS` — there is no duplicate
    ``TOOLS`` list or ``TOOL_HANDLERS`` dictionary in this module.
    """

    async def list_tools(
        ctx: Any,
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        """Return the canonical, deterministically-ordered tool list."""
        tools = [
            types.Tool(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in TOOL_DEFINITIONS
        ]
        return types.ListToolsResult(tools=tools)

    async def call_tool(
        ctx: Any,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        """Dispatch a tool invocation to its canonical handler.

        Error semantics (REQ-B07):

        * Unknown tool      → ``tool not found`` ``ErrorData`` result.
        * ``ToolError``     → ``isError=True`` result with the message.
        * Other exception   → logged, ``isError=True`` with a generic
          message (no stack trace leaks to the client).
        * Success           → ``TextContent`` with JSON-serialized result,
          ``isError=False``.
        """
        name = params.name
        arguments = params.arguments or {}

        tool = get_tool(name)
        if tool is None:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=json.dumps({"error": f"Tool not found: {name}"}),
                    )
                ],
                is_error=True,
            )

        # Resolve the server-lifetime shared engine + concurrency semaphore
        # (G1/G2/G3/G4).  The engine is created once in the MCP server lifespan
        # and stored on ``ctx.lifespan_context``.
        server_ctx = _get_server_context(ctx, name)
        engine = server_ctx.engine

        try:
            # G2: bound concurrent engine operations.  The semaphore covers the
            # actual CrawlEngine operation (the handler body), not just request
            # parsing.  Waiting operations queue rather than fail.
            async with server_ctx.semaphore:
                raw = await tool.handler(arguments, engine)
        except ToolError as exc:
            logger.warning("Tool %s raised ToolError: %s", name, exc.message)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"error": exc.message, **(exc.data or {})},
                        ),
                    )
                ],
                is_error=True,
            )
        except asyncio.CancelledError:
            # Allow cancellation to propagate; the shared engine is released
            # only when the server shuts down (G4), not per-call.
            raise
        except Exception as exc:
            logger.exception("Tool %s raised unexpected exception", name)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "internal tool error",
                                "tool": name,
                                "error_type": type(exc).__name__,
                            },
                        ),
                    )
                ],
                is_error=True,
            )

        text = _serialize(raw)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            is_error=False,
        )

    async def list_resources(
        ctx: Any,
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        """No server resources are currently exposed."""
        return types.ListResourcesResult(resources=[])

    async def list_prompts(
        ctx: Any,
        params: types.PaginatedRequestParams | None,
    ) -> types.ListPromptsResult:
        """A single ``research_topic`` prompt is provided."""
        return types.ListPromptsResult(
            prompts=[
                types.Prompt(
                    name="research_topic",
                    description="Research a topic using web search and scraping",
                    arguments=[
                        types.PromptArgument(
                            name="topic",
                            description="The topic to research",
                            required=True,
                        ),
                    ],
                ),
            ]
        )

    async def get_prompt(
        ctx: Any,
        params: types.GetPromptRequestParams,
        arguments: dict[str, Any] | None = None,
    ) -> types.GetPromptResult:
        name = params.name
        if name == "research_topic":
            topic = (arguments or {}).get("topic", "unknown topic")
            return types.GetPromptResult(
                description=f"Research: {topic}",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(
                            type="text",
                            text=(
                                f"Research the following topic: {topic}\n\n"
                                "Steps:\n"
                                "1. Use search_web to find relevant sources\n"
                                "2. Use scrape_webpage to read the top results\n"
                                "3. Synthesize findings into a comprehensive summary\n"
                                "4. Include source URLs for all claims"
                            ),
                        ),
                    ),
                ],
            )
        raise ValueError(f"Unknown prompt: {name}")

    return Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
        # Server-lifetime shared CrawlEngine + concurrency semaphore (Set G).
        # The lifespan is entered once per server run (stdio) and once per
        # Starlette app lifetime (Streamable HTTP), so exactly one engine is
        # created and shut down per server lifetime.
        lifespan=_mcp_lifespan,
    )


# ══════════════════════════════════════════════════════════════
# Transports
# ══════════════════════════════════════════════════════════════


async def run_stdio() -> None:
    """Run MCP server with stdio transport (native MCP SDK 2.0.0)."""
    server = create_mcp_server()
    logger.info("Starting AgentCrawl MCP server (stdio)...")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def run_streamable_http(
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Run MCP server with Streamable HTTP transport (native MCP SDK 2.0.0).

    Uses :meth:`Server.streamable_http_app` with ``stateless_http=True`` so
    the server is stateless at the MCP protocol boundary (REQ-B06) — each HTTP
    request is independently processable.  No legacy ``SseServerTransport``
    or ``/sse`` + ``/messages/`` routes are introduced.
    """
    import uvicorn

    server = create_mcp_server()
    app = server.streamable_http_app(stateless_http=True)

    logger.info(
        "Starting AgentCrawl MCP server (Streamable HTTP) on %s:%d/mcp...",
        host,
        port,
    )
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


# Backwards-compatible alias.  The previous code exposed ``run_sse``; SSE has
# been removed in favour of Streamable HTTP (REQ-B10).  ``run_sse`` is kept
# only to surface a clear migration error rather than a silent AttributeError.
async def run_sse(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Legacy SSE transport — removed in MCP 2.0.0 modernization (Set B).

    The MCP server now uses Streamable HTTP.  Use :func:`run_streamable_http`
    instead.  See ``docs/MCP_MIGRATION.md`` for the migration path.
    """
    raise RuntimeError(
        "Legacy SSE transport has been removed (Set B). "
        "Use run_streamable_http() or --transport http instead. "
        "See docs/MCP_MIGRATION.md."
    )


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="AgentCrawl MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport type (default: stdio). 'http' = Streamable HTTP.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="HTTP port (default: 8080)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )

    if args.transport == "http":
        asyncio.run(run_streamable_http(args.host, args.port))
    else:
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
