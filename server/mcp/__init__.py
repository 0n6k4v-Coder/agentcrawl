"""
AgentCrawl — MCP Server Package
===================================

Model Context Protocol (MCP) server for exposing AgentCrawl
tools to AI agents and LLM applications.

Modules:
    server — MCP server setup and transports
    tools  — Tool definitions and handlers

Usage:
    # Start MCP server
    python -m agentcrawl.server.mcp.server

    # Programmatic
    from server.mcp import create_mcp_server, ToolRegistry

    server = create_mcp_server()
    registry = ToolRegistry()
"""

from __future__ import annotations

from server.mcp.server import create_mcp_server
from server.mcp.tools import ToolDefinition, ToolRegistry, get_tool_registry

__all__ = [
    "ToolDefinition",
    "ToolRegistry",
    "create_mcp_server",
    "get_tool_registry",
]
