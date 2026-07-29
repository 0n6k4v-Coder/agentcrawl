"""
AgentCrawl — MCP Server
===========================

Model Context Protocol (MCP) server that exposes AgentCrawl
tools to AI agents and LLM applications.

MCP is an open protocol for connecting AI assistants to
external tools and data sources. This server provides
web scraping, crawling, search, and extraction tools.

Prerequisites:
    pip install mcp agentcrawl

Usage:
    # Start MCP server (stdio transport)
    python -m agentcrawl.server.mcp.server

    # Start with SSE transport
    python -m agentcrawl.server.mcp.server --transport sse --port 8080

    # Configure in Claude Desktop (claude_desktop_config.json):
    {
        "mcpServers": {
            "agentcrawl": {
                "command": "python",
                "args": ["-m", "agentcrawl.server.mcp.server"]
            }
        }
    }

Tools:
    scrape_webpage   — Scrape a URL and return Markdown
    search_web       — Search the web
    crawl_website    — Crawl multiple pages
    discover_urls    — Discover URLs on a site
    extract_data     — Extract structured data
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

logger = logging.getLogger("agentcrawl.mcp")


# ══════════════════════════════════════════════════════════════
# Tool Definitions
# ══════════════════════════════════════════════════════════════

TOOLS: list[dict[str, Any]] = [
    {
        "name": "scrape_webpage",
        "description": (
            "Scrape a webpage and return its content as clean Markdown. "
            "Removes navigation, ads, and boilerplate. "
            "Use this to read the content of a specific URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to scrape",
                },
                "include_links": {
                    "type": "boolean",
                    "description": "Whether to include extracted links",
                    "default": False,
                },
                "only_main_content": {
                    "type": "boolean",
                    "description": "Extract only main content (skip nav, footer)",
                    "default": True,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_web",
        "description": (
            "Search the web and return results with titles, URLs, and snippets. "
            "Use this to find relevant pages before scraping them."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "crawl_website",
        "description": (
            "Crawl a website starting from a URL and return content from "
            "multiple pages. Use this to gather information from documentation "
            "sites or multi-page resources."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The starting URL to crawl",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum number of pages to crawl",
                    "default": 10,
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum link depth to follow",
                    "default": 2,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "discover_urls",
        "description": (
            "Discover all URLs on a website without scraping content. "
            "Uses sitemap.xml, robots.txt, and link crawling. "
            "Use this to understand a site's structure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The website URL",
                },
                "max_urls": {
                    "type": "integer",
                    "description": "Maximum URLs to discover",
                    "default": 100,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "extract_data",
        "description": (
            "Extract structured data from a webpage using CSS selectors. "
            "Define fields with selectors to extract specific data. "
            "Returns structured JSON."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to extract from",
                },
                "fields": {
                    "type": "string",
                    "description": (
                        "Comma-separated field names to extract. "
                        "Example: 'title,price,description'"
                    ),
                },
            },
            "required": ["url", "fields"],
        },
    },
]


# ══════════════════════════════════════════════════════════════
# Tool Handlers
# ══════════════════════════════════════════════════════════════

async def handle_scrape_webpage(args: dict[str, Any]) -> str:
    """Handle scrape_webpage tool call."""
    from agentcrawl import CrawlEngine, CrawlerConfig

    url = args.get("url", "")
    include_links = args.get("include_links", False)
    only_main_content = args.get("only_main_content", True)

    if not url:
        return json.dumps({"error": "URL is required"})

    config = CrawlerConfig(
        output_format="markdown",
        include_links=include_links,
        include_metadata=True,
        only_main_content=only_main_content,
        cache=True,
        cache_ttl=3600,
    )

    try:
        async with CrawlEngine.default() as engine:
            result = await engine.scrape(url, config)

            if not result.success:
                return json.dumps({"error": result.error, "url": url})

            response: dict[str, Any] = {
                "url": result.url,
                "title": result.metadata.get("title", ""),
                "content": result.markdown,
                "word_count": result.word_count,
            }

            if include_links and result.links:
                response["links"] = result.links.get("all", [])[:20]

            return json.dumps(response, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)})


async def handle_search_web(args: dict[str, Any]) -> str:
    """Handle search_web tool call."""
    from agentcrawl import SearchEngine

    query = args.get("query", "")
    max_results = args.get("max_results", 5)

    if not query:
        return json.dumps({"error": "Query is required"})

    try:
        engine = SearchEngine(provider="duckduckgo")
        results = await engine.search(query, max_results=max_results)

        return json.dumps(
            {"query": query, "results": results},
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps({"error": str(e)})


async def handle_crawl_website(args: dict[str, Any]) -> str:
    """Handle crawl_website tool call."""
    from agentcrawl import BFSCrawler, CrawlEngine, CrawlerConfig

    url = args.get("url", "")
    max_pages = args.get("max_pages", 10)
    max_depth = args.get("max_depth", 2)

    if not url:
        return json.dumps({"error": "URL is required"})

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        cache=True,
    )

    try:
        async with CrawlEngine.default() as engine:
            job = await engine.crawl(
                url,
                strategy=BFSCrawler(max_depth=max_depth, max_pages=max_pages),
                config=config,
            )

            pages = []
            for page in job.pages:
                if page.success:
                    content = page.markdown
                    if len(content) > 2000:
                        content = content[:2000] + "\n\n[... truncated]"
                    pages.append({
                        "url": page.url,
                        "title": page.metadata.get("title", ""),
                        "content": content,
                        "word_count": page.word_count,
                    })

            return json.dumps(
                {
                    "start_url": url,
                    "total_pages": job.total_pages,
                    "successful_pages": job.successful_pages,
                    "pages": pages,
                },
                ensure_ascii=False,
            )

    except Exception as e:
        return json.dumps({"error": str(e)})


async def handle_discover_urls(args: dict[str, Any]) -> str:
    """Handle discover_urls tool call."""
    from agentcrawl import DomainMapper

    url = args.get("url", "")
    max_urls = args.get("max_urls", 100)

    if not url:
        return json.dumps({"error": "URL is required"})

    try:
        mapper = DomainMapper(max_urls=max_urls)
        urls = await mapper.discover(url)

        return json.dumps(
            {"url": url, "total_urls": len(urls), "urls": urls},
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps({"error": str(e)})


async def handle_extract_data(args: dict[str, Any]) -> str:
    """Handle extract_data tool call."""
    from pydantic import create_model

    from agentcrawl import CrawlEngine

    url = args.get("url", "")
    fields_str = args.get("fields", "")

    if not url:
        return json.dumps({"error": "URL is required"})

    if not fields_str:
        return json.dumps({"error": "Fields are required"})

    field_names = [f.strip() for f in fields_str.split(",") if f.strip()]

    if not field_names:
        return json.dumps({"error": "No valid fields specified"})

    try:
        # Build dynamic model
        field_definitions = dict.fromkeys(field_names, (str, ""))
        DynamicModel = create_model("ExtractedData", **field_definitions)

        async with CrawlEngine.default() as engine:
            result = await engine.extract(
                url,
                schema=DynamicModel,
                method="llm",
            )

            if not result.success:
                return json.dumps({"error": result.error, "url": url})

            if result.extracted_data:
                if hasattr(result.extracted_data, "model_dump"):
                    data = result.extracted_data.model_dump()
                else:
                    data = result.extracted_data
                return json.dumps(data, ensure_ascii=False)

            return json.dumps({"error": "No data extracted", "url": url})

    except Exception as e:
        return json.dumps({"error": str(e)})


# Tool handler registry
TOOL_HANDLERS: dict[str, Any] = {
    "scrape_webpage": handle_scrape_webpage,
    "search_web": handle_search_web,
    "crawl_website": handle_crawl_website,
    "discover_urls": handle_discover_urls,
    "extract_data": handle_extract_data,
}


# ══════════════════════════════════════════════════════════════
# MCP Server
# ══════════════════════════════════════════════════════════════

def create_mcp_server() -> Any:
    """
    Create and configure the MCP server.

    Returns:
        MCP Server instance.
    """
    try:
        import mcp.types as types
        from mcp.server import Server
        from mcp.server.models import InitializationOptions
    except ImportError:
        print(
            "MCP library not installed. Install with: pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    server = Server("agentcrawl")

    # ── List Tools ────────────────────────────────────────────

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        """Return available tools."""
        tools = []
        for tool_def in TOOLS:
            tools.append(types.Tool(
                name=tool_def["name"],
                description=tool_def["description"],
                inputSchema=tool_def["inputSchema"],
            ))
        return tools

    # ── Call Tool ─────────────────────────────────────────────

    @server.call_tool()
    async def call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> list[types.TextContent]:
        """Execute a tool call."""
        handler = TOOL_HANDLERS.get(name)

        if handler is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"}),
            )]

        try:
            result = await handler(arguments)
            return [types.TextContent(type="text", text=result)]
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e, exc_info=True)
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": str(e)}),
            )]

    # ── List Resources (optional) ─────────────────────────────

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        """Return available resources."""
        return []

    # ── List Prompts (optional) ───────────────────────────────

    @server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        """Return available prompts."""
        return [
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

    @server.get_prompt()
    async def get_prompt(
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> types.GetPromptResult:
        """Return a prompt."""
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

    return server


# ══════════════════════════════════════════════════════════════
# Transports
# ══════════════════════════════════════════════════════════════

async def run_stdio() -> None:
    """Run MCP server with stdio transport."""
    from mcp.server.stdio import stdio_server

    server = create_mcp_server()

    logger.info("Starting AgentCrawl MCP server (stdio)...")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def run_sse(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run MCP server with SSE transport."""
    try:
        import uvicorn
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
    except ImportError:
        print(
            "SSE transport requires: pip install uvicorn starlette",
            file=sys.stderr,
        )
        sys.exit(1)

    server = create_mcp_server()
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Any) -> Any:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages/", endpoint=sse.handle_post_message, methods=["POST"]),
        ],
    )

    logger.info("Starting AgentCrawl MCP server (SSE) on %s:%d...", host, port)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="AgentCrawl MCP Server",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="SSE host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="SSE port (default: 8080)",
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

    if args.transport == "sse":
        asyncio.run(run_sse(args.host, args.port))
    else:
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
