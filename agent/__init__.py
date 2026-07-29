"""
AgentCrawl — AI Agent Integration Layer
=========================================

Provides ready-to-use tool wrappers and schemas for integrating
AgentCrawl with popular AI agent frameworks.

Supported Frameworks:
    - LangChain (BaseTool / StructuredTool)
    - CrewAI (BaseTool)
    - OpenAI Function Calling / Tool Use
    - Anthropic Tool Use
    - MCP (Model Context Protocol)
    - Generic (any custom agent harness)

Quick Start:
    # Generic toolkit (no framework dependency)
    from agentcrawl.agent import AgentCrawlToolkit

    async with AgentCrawlToolkit() as toolkit:
        result = await toolkit.execute("web_scrape", url="https://example.com")
        print(result["content"])

    # LangChain
    from agentcrawl.agent import get_langchain_tools
    tools = get_langchain_tools()

    # CrewAI
    from agentcrawl.agent import get_crewai_tools
    tools = get_crewai_tools()

    # OpenAI Function Calling
    from agentcrawl.agent import OpenAIFunctionHandler
    handler = OpenAIFunctionHandler()

    # MCP Client
    from agentcrawl.agent import MCPClient
    async with MCPClient(url="http://localhost:8000/mcp/sse") as client:
        result = await client.scrape("https://example.com")

    # Function Schemas
    from agentcrawl.agent import get_openai_tools_schema, get_anthropic_tools_schema
    openai_tools = get_openai_tools_schema()
    anthropic_tools = get_anthropic_tools_schema()

    # Factory
    from agentcrawl.agent import create_toolkit
    tools = create_toolkit("langchain")   # or "crewai", "openai", "generic"
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("agentcrawl.agent")

# ──────────────────────────────────────────────────────────────
# Core (always available — no external framework required)
# ──────────────────────────────────────────────────────────────

from agentcrawl.agent.function_schema import (
    TOOL_DEFINITIONS,
    export_schemas_json,
    get_all_schemas,
    get_anthropic_tools_schema,
    get_crewai_tools,
    get_langchain_tools,
    get_mcp_tools_schema,
    get_openai_functions_schema,
    get_openai_tools_schema,
    get_tool_definition,
    get_tool_names,
)
from agentcrawl.agent.mcp_client import (
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPServerInfo,
    MCPTimeoutError,
    MCPToolError,
    MCPToolInfo,
    MCPToolResult,
    TransportType,
    create_sse_client,
    create_stdio_client,
    create_websocket_client,
)
from agentcrawl.agent.tool import (
    AgentCrawlToolkit,
    OpenAIFunctionHandler,
    create_toolkit,
)

# ──────────────────────────────────────────────────────────────
# Framework-Specific (conditional imports)
# ──────────────────────────────────────────────────────────────

# LangChain tools
try:
    from agentcrawl.agent.tool import (
        AgentCrawlCrawlTool,
        AgentCrawlSearchTool,
        AgentCrawlTool,
    )
    _HAS_LANGCHAIN = True
except ImportError:
    AgentCrawlTool = None  # type: ignore[assignment,misc]
    AgentCrawlSearchTool = None  # type: ignore[assignment,misc]
    AgentCrawlCrawlTool = None  # type: ignore[assignment,misc]
    _HAS_LANGCHAIN = False

# CrewAI tools
try:
    from agentcrawl.agent.tool import (
        CrewAICrawlTool,
        CrewAISearchTool,
    )
    _HAS_CREWAI = True
except ImportError:
    CrewAICrawlTool = None  # type: ignore[assignment,misc]
    CrewAISearchTool = None  # type: ignore[assignment,misc]
    _HAS_CREWAI = False


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Core toolkit
    "AgentCrawlToolkit",
    "OpenAIFunctionHandler",
    "create_toolkit",
    # Function schemas
    "TOOL_DEFINITIONS",
    "get_all_schemas",
    "get_anthropic_tools_schema",
    "get_crewai_tools",
    "get_langchain_tools",
    "get_mcp_tools_schema",
    "get_openai_functions_schema",
    "get_openai_tools_schema",
    "get_tool_definition",
    "get_tool_names",
    "export_schemas_json",
    # MCP client
    "MCPClient",
    "MCPConnectionError",
    "MCPError",
    "MCPTimeoutError",
    "MCPToolError",
    "MCPToolInfo",
    "MCPToolResult",
    "MCPServerInfo",
    "TransportType",
    "create_sse_client",
    "create_stdio_client",
    "create_websocket_client",
    # LangChain (may be None if not installed)
    "AgentCrawlTool",
    "AgentCrawlSearchTool",
    "AgentCrawlCrawlTool",
    # CrewAI (may be None if not installed)
    "CrewAICrawlTool",
    "CrewAISearchTool",
    # Feature detection
    "has_langchain",
    "has_crewai",
    "get_available_frameworks",
]


# ──────────────────────────────────────────────────────────────
# Feature Detection Helpers
# ──────────────────────────────────────────────────────────────

def has_langchain() -> bool:
    """Check if LangChain is installed and AgentCrawl tools are available."""
    return _HAS_LANGCHAIN


def has_crewai() -> bool:
    """Check if CrewAI is installed and AgentCrawl tools are available."""
    return _HAS_CREWAI


def get_available_frameworks() -> list[str]:
    """
    Get a list of AI agent frameworks currently available.

    Returns:
        List of framework names that can be used with create_toolkit().

    Example:
        >>> frameworks = get_available_frameworks()
        >>> print(frameworks)
        ['generic', 'openai', 'langchain', 'crewai']
    """
    frameworks = ["generic", "openai"]
    if _HAS_LANGCHAIN:
        frameworks.append("langchain")
    if _HAS_CREWAI:
        frameworks.append("crewai")
    return frameworks
