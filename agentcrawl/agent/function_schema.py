"""
AgentCrawl — Function Schema Generator
=======================================

Generates tool/function schemas for AI agent integrations:
  - OpenAI Function Calling
  - Anthropic Tool Use
  - LangChain Tool
  - CrewAI Tool
  - Generic JSON Schema

Usage:
    from agentcrawl.agent.function_schema import (
        get_openai_tools_schema,
        get_anthropic_tools_schema,
        get_langchain_tools,
        get_crewai_tools,
        get_all_schemas,
    )

    # OpenAI
    tools = get_openai_tools_schema()

    # Anthropic
    tools = get_anthropic_tools_schema()

    # All formats
    schemas = get_all_schemas()
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# ══════════════════════════════════════════════════════════════
# Core Tool Definitions (Source of Truth)
# ══════════════════════════════════════════════════════════════

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "web_scrape",
        "description": (
            "Scrape a single web page and return its content as clean Markdown, "
            "structured JSON, or cleaned HTML. Use this when you need to read "
            "the content of a specific URL. Supports JavaScript-rendered pages, "
            "stealth mode for anti-bot protection, and optional page interactions "
            "(click, scroll, type) before extraction."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full URL of the web page to scrape (e.g., https://example.com/article).",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["markdown", "json", "html"],
                    "description": (
                        "Output format. 'markdown' returns clean LLM-ready Markdown. "
                        "'json' returns structured JSON with metadata. "
                        "'html' returns cleaned HTML."
                    ),
                    "default": "markdown",
                },
                "include_links": {
                    "type": "boolean",
                    "description": "Whether to include extracted links (internal and external) in the response.",
                    "default": True,
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Whether to include page metadata (title, description, og:tags, etc.).",
                    "default": True,
                },
                "include_screenshot": {
                    "type": "boolean",
                    "description": "Whether to capture a full-page screenshot (returned as base64).",
                    "default": False,
                },
                "stealth": {
                    "type": "boolean",
                    "description": "Enable stealth mode to bypass anti-bot detection.",
                    "default": True,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Page load timeout in seconds.",
                    "default": 30,
                },
                "actions": {
                    "type": "array",
                    "description": (
                        "Optional list of page interactions to perform before scraping. "
                        "Each action is an object with 'type' (click, scroll, type, wait, press, screenshot) "
                        "and relevant parameters."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["click", "scroll", "type", "wait", "press", "screenshot"],
                            },
                            "selector": {
                                "type": "string",
                                "description": "CSS selector for the target element.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text to type (for 'type' action).",
                            },
                            "direction": {
                                "type": "string",
                                "enum": ["up", "down"],
                                "description": "Scroll direction (for 'scroll' action).",
                            },
                            "amount": {
                                "type": "integer",
                                "description": "Number of scrolls or pixels.",
                            },
                            "milliseconds": {
                                "type": "integer",
                                "description": "Wait duration in milliseconds (for 'wait' action).",
                            },
                            "key": {
                                "type": "string",
                                "description": "Key to press (for 'press' action, e.g., 'Enter', 'Tab').",
                            },
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_crawl",
        "description": (
            "Crawl an entire website starting from a given URL. Discovers and scrapes "
            "multiple pages following links. Supports BFS (breadth-first), DFS (depth-first), "
            "and BestFirst crawling strategies. Use this when you need to collect content "
            "from multiple pages of a website. Returns a list of scraped pages."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The starting URL to crawl from (e.g., https://docs.example.com).",
                },
                "strategy": {
                    "type": "string",
                    "enum": ["bfs", "dfs", "best_first"],
                    "description": (
                        "Crawling strategy. 'bfs' explores level by level (default). "
                        "'dfs' goes deep first. 'best_first' prioritizes by relevance score."
                    ),
                    "default": "bfs",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum link depth from the starting URL.",
                    "default": 3,
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum number of pages to crawl.",
                    "default": 50,
                },
                "output_format": {
                    "type": "string",
                    "enum": ["markdown", "json", "html"],
                    "description": "Output format for each scraped page.",
                    "default": "markdown",
                },
                "include_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "URL patterns to include (glob patterns). "
                        "Example: ['/docs/*', '/api/*']. Empty means include all."
                    ),
                    "default": [],
                },
                "exclude_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "URL patterns to exclude (glob patterns). "
                        "Example: ['/blog/*', '*.pdf', '/admin/*']."
                    ),
                    "default": [],
                },
                "same_domain_only": {
                    "type": "boolean",
                    "description": "Only crawl pages on the same domain as the starting URL.",
                    "default": True,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for a query and optionally scrape the top results. "
            "Returns search results with titles, URLs, snippets, and optionally "
            "the full scraped content of each result page. Use this when you need "
            "to find information across the web."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to return.",
                    "default": 5,
                },
                "scrape_results": {
                    "type": "boolean",
                    "description": (
                        "Whether to scrape the full content of each search result page. "
                        "If false, only titles, URLs, and snippets are returned."
                    ),
                    "default": True,
                },
                "output_format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Output format for scraped content.",
                    "default": "markdown",
                },
                "search_engine": {
                    "type": "string",
                    "enum": ["google", "duckduckgo", "searxng"],
                    "description": "Search engine to use.",
                    "default": "google",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_map",
        "description": (
            "Discover and list all URLs on a website without scraping their content. "
            "Uses sitemap.xml, robots.txt, and link crawling to build a complete URL map. "
            "Use this when you need to understand a website's structure or find specific pages "
            "before scraping them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The website URL to map (e.g., https://example.com).",
                },
                "max_urls": {
                    "type": "integer",
                    "description": "Maximum number of URLs to discover.",
                    "default": 500,
                },
                "include_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL patterns to include (glob patterns).",
                    "default": [],
                },
                "exclude_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL patterns to exclude (glob patterns).",
                    "default": [],
                },
                "use_sitemap": {
                    "type": "boolean",
                    "description": "Whether to parse sitemap.xml for URL discovery.",
                    "default": True,
                },
                "use_robots": {
                    "type": "boolean",
                    "description": "Whether to parse robots.txt for URL discovery.",
                    "default": True,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_extract",
        "description": (
            "Extract structured data from a web page using LLM-powered or rule-based extraction. "
            "Provide a JSON schema describing the data you want, and the tool will extract it. "
            "Use this when you need specific fields (e.g., product name, price, reviews) "
            "rather than the full page content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to extract data from.",
                },
                "schema": {
                    "type": "object",
                    "description": (
                        "JSON schema describing the data to extract. "
                        "Example: {\"type\": \"object\", \"properties\": {\"name\": {\"type\": \"string\"}, "
                        "\"price\": {\"type\": \"number\"}}}."
                    ),
                },
                "method": {
                    "type": "string",
                    "enum": ["llm", "css", "xpath"],
                    "description": (
                        "Extraction method. 'llm' uses an LLM to understand and extract data (most flexible). "
                        "'css' uses CSS selectors (fastest, no LLM cost). "
                        "'xpath' uses XPath expressions."
                    ),
                    "default": "llm",
                },
                "css_schema": {
                    "type": "object",
                    "description": (
                        "CSS extraction schema (required if method='css'). "
                        "Format: {\"baseSelector\": \"...\", \"fields\": [{\"name\": \"...\", \"selector\": \"...\", \"type\": \"text|html|attribute|list\"}]}."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Optional custom prompt to guide LLM extraction. "
                        "Example: 'Extract all product listings with name, price, and rating'."
                    ),
                },
            },
            "required": ["url", "schema"],
        },
    },
    {
        "name": "web_screenshot",
        "description": (
            "Capture a screenshot of a web page. Returns the image as a base64-encoded string. "
            "Supports full-page or viewport-only captures. Use this when you need a visual "
            "representation of a web page."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to screenshot.",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "Capture the entire scrollable page (true) or just the viewport (false).",
                    "default": True,
                },
                "format": {
                    "type": "string",
                    "enum": ["png", "jpeg"],
                    "description": "Image format.",
                    "default": "png",
                },
                "quality": {
                    "type": "integer",
                    "description": "JPEG quality (1-100). Only used when format='jpeg'.",
                    "default": 80,
                },
                "viewport_width": {
                    "type": "integer",
                    "description": "Viewport width in pixels.",
                    "default": 1280,
                },
                "viewport_height": {
                    "type": "integer",
                    "description": "Viewport height in pixels.",
                    "default": 720,
                },
                "wait_for_selector": {
                    "type": "string",
                    "description": "Optional CSS selector to wait for before taking the screenshot.",
                },
                "wait_milliseconds": {
                    "type": "integer",
                    "description": "Optional milliseconds to wait before taking the screenshot.",
                    "default": 0,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_batch_scrape",
        "description": (
            "Scrape multiple URLs in a single call. More efficient than calling web_scrape "
            "repeatedly. Returns a list of results, one per URL. Use this when you have "
            "a known list of URLs to scrape."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of URLs to scrape.",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["markdown", "json", "html"],
                    "description": "Output format for each page.",
                    "default": "markdown",
                },
                "max_concurrent": {
                    "type": "integer",
                    "description": "Maximum number of concurrent scrapes.",
                    "default": 5,
                },
                "stealth": {
                    "type": "boolean",
                    "description": "Enable stealth mode for all scrapes.",
                    "default": True,
                },
            },
            "required": ["urls"],
        },
    },
]


# ══════════════════════════════════════════════════════════════
# OpenAI Function Calling Format
# ══════════════════════════════════════════════════════════════

def get_openai_tools_schema(
    tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate OpenAI-compatible function calling tool definitions.

    Args:
        tools: Optional list of tool names to include.
               If None, all tools are included.

    Returns:
        List of tool definitions in OpenAI format.

    Example:
        >>> tools = get_openai_tools_schema()
        >>> response = client.chat.completions.create(
        ...     model="gpt-4o",
        ...     messages=[...],
        ...     tools=tools,
        ...     tool_choice="auto",
        ... )
    """
    defs = _filter_tools(tools)
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in defs
    ]


def get_openai_functions_schema(
    tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate legacy OpenAI functions schema (deprecated but still supported).

    Args:
        tools: Optional list of tool names to include.

    Returns:
        List of function definitions in legacy OpenAI format.
    """
    defs = _filter_tools(tools)
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        }
        for t in defs
    ]


# ══════════════════════════════════════════════════════════════
# Anthropic Tool Use Format
# ══════════════════════════════════════════════════════════════

def get_anthropic_tools_schema(
    tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate Anthropic-compatible tool use definitions.

    Args:
        tools: Optional list of tool names to include.

    Returns:
        List of tool definitions in Anthropic format.

    Example:
        >>> tools = get_anthropic_tools_schema()
        >>> response = client.messages.create(
        ...     model="claude-sonnet-4-20250514",
        ...     messages=[...],
        ...     tools=tools,
        ... )
    """
    defs = _filter_tools(tools)
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in defs
    ]


# ══════════════════════════════════════════════════════════════
# LangChain Tool Format
# ══════════════════════════════════════════════════════════════

def get_langchain_tools(
    tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate LangChain-compatible tool definitions.

    Args:
        tools: Optional list of tool names to include.

    Returns:
        List of tool definitions in LangChain StructuredTool format.

    Example:
        >>> from langchain.tools import StructuredTool
        >>> tool_defs = get_langchain_tools()
        >>> # Use with AgentCrawlTool wrapper for actual execution
    """
    defs = _filter_tools(tools)
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "args_schema": _to_langchain_args_schema(t["parameters"]),
            "metadata": {
                "tool_type": "agentcrawl",
                "requires_browser": True,
            },
        }
        for t in defs
    ]


def _to_langchain_args_schema(parameters: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON Schema parameters to LangChain args_schema format."""
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    schema_fields: dict[str, Any] = {}
    for name, prop in properties.items():
        field_info: dict[str, Any] = {
            "type": prop.get("type", "string"),
            "description": prop.get("description", ""),
        }
        if "enum" in prop:
            field_info["enum"] = prop["enum"]
        if "default" in prop:
            field_info["default"] = prop["default"]
        if "items" in prop:
            field_info["items"] = prop["items"]
        field_info["required"] = name in required
        schema_fields[name] = field_info

    return {
        "type": "object",
        "properties": schema_fields,
        "required": required,
    }


# ══════════════════════════════════════════════════════════════
# CrewAI Tool Format
# ══════════════════════════════════════════════════════════════

def get_crewai_tools(
    tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate CrewAI-compatible tool definitions.

    Args:
        tools: Optional list of tool names to include.

    Returns:
        List of tool definitions in CrewAI format.
    """
    defs = _filter_tools(tools)
    return [
        {
            "name": _to_class_name(t["name"]),
            "description": t["description"],
            "parameters": t["parameters"],
            "method": t["name"],
        }
        for t in defs
    ]


# ══════════════════════════════════════════════════════════════
# MCP (Model Context Protocol) Tool Format
# ══════════════════════════════════════════════════════════════

def get_mcp_tools_schema(
    tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate MCP-compatible tool definitions.

    Args:
        tools: Optional list of tool names to include.

    Returns:
        List of tool definitions in MCP format.
    """
    defs = _filter_tools(tools)
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["parameters"],
        }
        for t in defs
    ]


# ══════════════════════════════════════════════════════════════
# Generic / All Formats
# ══════════════════════════════════════════════════════════════

def get_all_schemas(
    tools: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Generate tool schemas in all supported formats.

    Args:
        tools: Optional list of tool names to include.

    Returns:
        Dictionary mapping format name to list of tool definitions.

    Example:
        >>> schemas = get_all_schemas()
        >>> schemas["openai"]      # OpenAI format
        >>> schemas["anthropic"]   # Anthropic format
        >>> schemas["langchain"]   # LangChain format
        >>> schemas["crewai"]      # CrewAI format
        >>> schemas["mcp"]         # MCP format
    """
    return {
        "openai": get_openai_tools_schema(tools),
        "openai_legacy": get_openai_functions_schema(tools),
        "anthropic": get_anthropic_tools_schema(tools),
        "langchain": get_langchain_tools(tools),
        "crewai": get_crewai_tools(tools),
        "mcp": get_mcp_tools_schema(tools),
    }


def get_tool_names() -> list[str]:
    """Return a list of all available tool names."""
    return [t["name"] for t in TOOL_DEFINITIONS]


def get_tool_definition(name: str) -> dict[str, Any] | None:
    """
    Get a single tool definition by name.

    Args:
        name: Tool name (e.g., 'web_scrape', 'web_crawl').

    Returns:
        Tool definition dict, or None if not found.
    """
    for t in TOOL_DEFINITIONS:
        if t["name"] == name:
            return t
    return None


def export_schemas_json(
    filepath: str,
    tools: list[str] | None = None,
    fmt: str = "openai",
) -> None:
    """
    Export tool schemas to a JSON file.

    Args:
        filepath: Output file path.
        tools: Optional list of tool names to include.
        fmt: Schema format ('openai', 'anthropic', 'langchain', 'crewai', 'mcp').
    """
    format_map = {
        "openai": get_openai_tools_schema,
        "openai_legacy": get_openai_functions_schema,
        "anthropic": get_anthropic_tools_schema,
        "langchain": get_langchain_tools,
        "crewai": get_crewai_tools,
        "mcp": get_mcp_tools_schema,
    }

    generator = format_map.get(fmt)
    if generator is None:
        raise ValueError(
            f"Unknown format '{fmt}'. Available: {', '.join(format_map.keys())}"
        )

    schemas = generator(tools)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(schemas, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# Internal Helpers
# ══════════════════════════════════════════════════════════════

def _filter_tools(tools: list[str] | None) -> list[dict[str, Any]]:
    """Filter tool definitions by name list."""
    if tools is None:
        return TOOL_DEFINITIONS

    available = {t["name"] for t in TOOL_DEFINITIONS}
    invalid = set(tools) - available
    if invalid:
        raise ValueError(
            f"Unknown tool(s): {', '.join(sorted(invalid))}. "
            f"Available: {', '.join(sorted(available))}"
        )

    return [t for t in TOOL_DEFINITIONS if t["name"] in tools]


def _to_class_name(snake_name: str) -> str:
    """Convert snake_case tool name to PascalCase class name."""
    return "".join(word.capitalize() for word in snake_name.split("_"))


# ══════════════════════════════════════════════════════════════
# CLI — Print schemas for debugging
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    fmt = sys.argv[1] if len(sys.argv) > 1 else "openai"
    tool_filter = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    format_map: dict[str, Callable[[Any], Any]] = {
        "openai": get_openai_tools_schema,
        "openai_legacy": get_openai_functions_schema,
        "anthropic": get_anthropic_tools_schema,
        "langchain": get_langchain_tools,
        "crewai": get_crewai_tools,
        "mcp": get_mcp_tools_schema,
        "names": lambda t: get_tool_names(),
    }

    if fmt not in format_map:
        print(f"Unknown format: {fmt}")
        print(f"Available: {', '.join(format_map.keys())}")
        sys.exit(1)

    result = format_map[fmt](tool_filter)
    print(json.dumps(result, indent=2, ensure_ascii=False))
