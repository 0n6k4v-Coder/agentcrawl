"""AgentCrawl — MCP Server Package
==================================

Model Context Protocol (MCP) server for exposing AgentCrawl
tools to AI agents and LLM applications.

Modules:
    server — MCP server setup and transports
    tools  — Canonical tool contract (definitions + handlers)

Usage:
    # Start MCP server (stdio transport)
    python -m server.mcp.server

    # Start with Streamable HTTP transport
    python -m server.mcp.server --transport http --port 8080

    # Programmatic
    from server.mcp import create_mcp_server
    server = create_mcp_server()

The canonical tool contract lives in :mod:`server.mcp.tools`.
"""

from __future__ import annotations

from server.mcp.server import create_mcp_server, run_stdio, run_streamable_http
from server.mcp.tools import (
    CANONICAL_TOOL_ORDER,
    TOOL_DEFINITIONS,
    ToolDefinition,
    ToolError,
    get_tool,
    list_tool_names,
    to_mcp_tool_list,
)

__all__ = [
    "CANONICAL_TOOL_ORDER",
    "TOOL_DEFINITIONS",
    "ToolDefinition",
    "ToolError",
    "create_mcp_server",
    "get_tool",
    "list_tool_names",
    "run_stdio",
    "run_streamable_http",
    "to_mcp_tool_list",
]
