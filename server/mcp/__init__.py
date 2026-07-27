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
    from agentcrawl.server.mcp import create_mcp_server, ToolRegistry

    server = create_mcp_server()
    registry = ToolRegistry()
"""

from __future__ import annotations

from agentcrawl.server.mcp.server import create_mcp_server
from agentcrawl.server.mcp.tools import ToolDefinition, ToolRegistry, get_tool_registry

__all__ = [
    "create_mcp_server",
    "ToolRegistry",
    "ToolDefinition",
    "get_tool_registry",
]