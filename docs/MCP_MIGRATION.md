# MCP Migration Guide

This document describes the Model Context Protocol (MCP) modernization of
AgentCrawl, the current runtime state, and the migration path from the legacy
(1.x) implementation.

## Migration Overview

AgentCrawl's MCP integration has been fully modernized to **MCP SDK 2.0.0**.

| Layer         | Legacy (pre-migration)            | Modern (current)                          |
|---------------|-----------------------------------|-------------------------------------------|
| Server SDK    | MCP 1.x `Server` + decorators     | MCP 2.0.0 `Server` with constructor callbacks |
| Transport     | SSE (`GET /sse`, `POST /messages/`) | Streamable HTTP (`POST /mcp`, `stateless_http=True`) + native stdio |
| Client        | Custom JSON-RPC / SSE / WebSocket | Official MCP 2.0.0 `ClientSession` with `streamable_http_client` and `stdio_client` |
| Routing       | `/sse`, `/messages/`              | `/mcp` (Streamable HTTP only)             |

## Old → New Transport Model

**Legacy:** The server exposed a Server-Sent Events (SSE) transport with two
routes — `GET /sse` (connection establishment) and `POST /messages/`
(request/response). The client used a custom `SseServerTransport` wrapper and
hand-rolled JSON-RPC framing.

**Modern:** The server exposes a single Streamable HTTP endpoint at `/mcp`
using the MCP SDK 2.0.0 native `Server.streamable_http_app(stateless_http=True)`
facility. The client uses `mcp.client.session.ClientSession` wired to
`mcp.client.streamable_http.streamable_http_client` (HTTP) or
`mcp.client.stdio.stdio_client` (stdio). All protocol framing, negotiation,
and session management is delegated to the official SDK — no custom JSON-RPC.

## Old → New Client Architecture

The client modules (`agent/mcp_client.py` and `agentcrawl/agent/mcp_client.py`,
which are byte-identical) now import directly from the MCP SDK 2.0.0:

- `mcp.client.session.ClientSession` — native client session
- `mcp.client.stdio.stdio_client` — native stdio transport
- `mcp.client.streamable_http.streamable_http_client` — native Streamable HTTP transport

The client discovers tools at runtime through `tools/list` rather than
hardcoding a server-side tool registry. The canonical tool order is imported
from `server.mcp.tools.CANONICAL_TOOL_ORDER` (single source of truth), with a
frozen fallback list when the server package is not importable.

**Compatibility aliases (safe):**

- `create_sse_client` — alias for `create_http_client`; returns a
  Streamable HTTP client. Does NOT instantiate any legacy SSE transport.
- `create_websocket_client` — returns a Streamable HTTP client with `ws://`/`wss://`
  URLs rewritten to `http://`/`https://`. Emits a deprecation warning. Does NOT
  instantiate any legacy WebSocket transport.

## Canonical Tools

The server exposes exactly six canonical tools, defined in
`server/mcp/tools.py` as `TOOL_DEFINITIONS`. The order is deterministic:

| # | Name             | Required Args | Optional Args (with defaults)        |
|---|------------------|---------------|---------------------------------------|
| 1 | `scrape_webpage` | `url`         | `include_links` (False), `only_main_content` (True) |
| 2 | `search_web`     | `query`       | `max_results` (5)                     |
| 3 | `crawl_website`  | `url`         | `max_pages` (10), `max_depth` (2)    |
| 4 | `discover_urls`  | `url`         | `max_urls` (100)                      |
| 5 | `extract_data`   | `url`, `fields` | —                                   |
| 6 | `batch_scrape`   | `urls`        | `only_main_content` (True)           |

`web_screenshot` is **not** a supported tool and is not reintroduced.

## HTTP `/mcp` Endpoint

Launch the server with Streamable HTTP:

```bash
python -m server.mcp.server --transport http --host 127.0.0.1 --port 9000
```

The server listens on POST `/mcp` with `stateless_http=True`.

## stdio Transport

Launch the server with stdio (for agents that manage the subprocess):

```bash
python -m server.mcp.server --transport stdio
```

Connect from a client using the native SDK `stdio_client`:

```python
import asyncio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    server_params = StdioServerParameters(
        command="python3",
        args=["-m", "server.mcp.server", "--transport", "stdio"],
    )
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream=read_stream, write_stream=write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])

asyncio.run(main())
```

## Removed Legacy Transports

The following legacy transports and patterns have been **removed** and are no
longer active in any implementation code:

- `mcp.client.sse` — not imported
- `mcp.client.websocket` — not imported
- `SseServerTransport` — not instantiated
- `GET /sse` route — not registered
- `POST /messages/` route — not registered
- Custom JSON-RPC client classes (`_JsonRpc`, `_JsonRpcClient`) — removed
- Custom WebSocket transport (`_WebSocketTransport`) — removed
- Custom SSE transport (`_SSETransport`) — removed
- Hardcoded protocol version `2024-11-05` — removed

The `run_sse()` function is retained as a backward-compat stub that raises
`RuntimeError` with a migration message, so callers get a clear error rather
than a silent `AttributeError`.

## Migration Completion State

| Set | Scope                                      | Status |
|-----|--------------------------------------------|--------|
| B   | Server reconstruction (SDK 2.0.0, Streamable HTTP, stdio) | Complete |
| C   | Client migration (SDK 2.0.0 `ClientSession`)              | Complete |
| D   | Integration boundary (real transport, dispatch, errors)  | Complete |
| E   | Hardening (lifecycle, error boundary, concurrency, docs) | Complete |
| F   | Release readiness & documentation closure                | Complete |

## Deferred Functionality

The following MCP capabilities are **not yet implemented** and remain deferred:

- **Authorization** — no MCP-level OAuth2 / bearer-token validation. The
  `api_key`/`Authorization` header in the client is passed through but the
  server does not enforce it at the MCP layer.
- **MCP Tasks** — no `tasks/send`, `tasks/list`, or `tasks/get` support.
- **MRTR** (Model-Represented Tool Results) — not implemented.
- **Sampling** — no `sampling/create` support.
- **Roots** — no `roots/list` or `roots/added` support.
- **Hermes integration** — no automatic Hermes Agent MCP registration.

These features are explicitly out of scope for the current migration. Do not
rely on them being available.
