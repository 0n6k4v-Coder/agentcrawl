"""
AgentCrawl — MCP Tools
==========================

Tool definitions and handlers for the AgentCrawl MCP server.

Each tool is defined with:
    - name: Unique tool identifier
    - description: What the tool does
    - input_schema: JSON Schema for parameters
    - handler: Async function that executes the tool

Usage:
    from server.mcp.tools import ToolRegistry

    registry = ToolRegistry()

    # Get all tool definitions
    tools = registry.get_definitions()

    # Execute a tool
    result = await registry.execute("scrape_webpage", {"url": "https://example.com"})
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger("agentcrawl.mcp.tools")


# ══════════════════════════════════════════════════════════════
# Tool Definition
# ══════════════════════════════════════════════════════════════


@dataclass
class ToolDefinition:
    """
    MCP tool definition.

    Attributes:
        name: Unique tool name.
        description: Human-readable description.
        input_schema: JSON Schema for input parameters.
        handler: Async handler function.
        category: Tool category for grouping.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Coroutine[Any, Any, str]]
    category: str = "general"

    def to_mcp_dict(self) -> dict[str, Any]:
        """Convert to MCP tool dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# ══════════════════════════════════════════════════════════════
# Tool Registry
# ══════════════════════════════════════════════════════════════


class ToolRegistry:
    """
    Registry of MCP tools.

    Manages tool definitions and dispatches execution.

    Example:
        >>> registry = ToolRegistry()
        >>> tools = registry.get_definitions()
        >>> result = await registry.execute("scrape_webpage", {"url": "..."})
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._register_defaults()

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug("Registered MCP tool: %s", tool.name)

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in MCP format."""
        return [tool.to_mcp_dict() for tool in self._tools.values()]

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """
        Execute a tool by name.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            JSON string result.
        """
        tool = self._tools.get(name)

        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            result = await tool.handler(arguments)
            return result
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e, exc_info=True)
            return json.dumps({"error": str(e), "tool": name})

    def _register_defaults(self) -> None:
        """Register all default tools."""
        self.register(
            ToolDefinition(
                name="scrape_webpage",
                description=(
                    "Scrape a webpage and return its content as clean Markdown. "
                    "Removes navigation, ads, and boilerplate. "
                    "Use this to read the content of a specific URL."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to scrape",
                        },
                        "include_links": {
                            "type": "boolean",
                            "description": "Include extracted links",
                            "default": False,
                        },
                        "only_main_content": {
                            "type": "boolean",
                            "description": "Extract only main content",
                            "default": True,
                        },
                    },
                    "required": ["url"],
                },
                handler=handle_scrape_webpage,
                category="scraping",
            )
        )

        self.register(
            ToolDefinition(
                name="search_web",
                description=(
                    "Search the web and return results with titles, URLs, and snippets. "
                    "Use this to find relevant pages before scraping them."
                ),
                input_schema={
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
                handler=handle_search_web,
                category="search",
            )
        )

        self.register(
            ToolDefinition(
                name="crawl_website",
                description=(
                    "Crawl a website starting from a URL and return content from "
                    "multiple pages. Use for documentation sites or multi-page resources."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The starting URL",
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Maximum pages to crawl",
                            "default": 10,
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum link depth",
                            "default": 2,
                        },
                    },
                    "required": ["url"],
                },
                handler=handle_crawl_website,
                category="crawling",
            )
        )

        self.register(
            ToolDefinition(
                name="discover_urls",
                description=(
                    "Discover all URLs on a website without scraping content. "
                    "Uses sitemap.xml, robots.txt, and link crawling."
                ),
                input_schema={
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
                handler=handle_discover_urls,
                category="discovery",
            )
        )

        self.register(
            ToolDefinition(
                name="extract_data",
                description=(
                    "Extract structured data from a webpage. "
                    "Specify fields to extract as comma-separated names. "
                    "Returns structured JSON."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to extract from",
                        },
                        "fields": {
                            "type": "string",
                            "description": "Comma-separated field names (e.g., 'title,price,description')",
                        },
                    },
                    "required": ["url", "fields"],
                },
                handler=handle_extract_data,
                category="extraction",
            )
        )

        self.register(
            ToolDefinition(
                name="batch_scrape",
                description=(
                    "Scrape multiple URLs at once and return all results. "
                    "More efficient than calling scrape_webpage multiple times."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of URLs to scrape",
                        },
                        "only_main_content": {
                            "type": "boolean",
                            "description": "Extract only main content",
                            "default": True,
                        },
                    },
                    "required": ["urls"],
                },
                handler=handle_batch_scrape,
                category="scraping",
            )
        )


# ══════════════════════════════════════════════════════════════
# Tool Handlers
# ══════════════════════════════════════════════════════════════


async def handle_scrape_webpage(args: dict[str, Any]) -> str:
    """
    Scrape a single webpage.

    Args:
        args: Tool arguments (url, include_links, only_main_content).

    Returns:
        JSON string with page content.
    """
    from agentcrawl import CrawlEngine, CrawlerConfig

    url = args.get("url", "")
    if not url:
        return _error("URL is required")

    config = CrawlerConfig(
        output_format="markdown",
        include_links=args.get("include_links", False),
        include_metadata=True,
        only_main_content=args.get("only_main_content", True),
        cache=True,
        cache_ttl=3600,
    )

    try:
        async with CrawlEngine.default() as engine:
            result = await engine.scrape(url, config)

            if not result.success:
                return _error(result.error or "Scrape failed", url=url)

            response: dict[str, Any] = {
                "url": result.url,
                "title": result.metadata.get("title", ""),
                "content": result.markdown,
                "word_count": result.word_count,
                "token_count": result.token_count,
            }

            if args.get("include_links") and result.links:
                response["links"] = result.links.get("all", [])[:20]

            return _json(response)

    except Exception as e:
        return _error(str(e))


async def handle_search_web(args: dict[str, Any]) -> str:
    """
    Search the web.

    Args:
        args: Tool arguments (query, max_results).

    Returns:
        JSON string with search results.
    """
    from agentcrawl import SearchEngine

    query = args.get("query", "")
    if not query:
        return _error("Query is required")

    max_results = args.get("max_results", 5)

    try:
        engine = SearchEngine(provider="duckduckgo")
        results = await engine.search(query, max_results=max_results)

        return _json({"query": query, "results": results})

    except Exception as e:
        return _error(str(e))


async def handle_crawl_website(args: dict[str, Any]) -> str:
    """
    Crawl a website.

    Args:
        args: Tool arguments (url, max_pages, max_depth).

    Returns:
        JSON string with crawled pages.
    """
    from agentcrawl import BFSCrawler, CrawlEngine, CrawlerConfig

    url = args.get("url", "")
    if not url:
        return _error("URL is required")

    max_pages = min(args.get("max_pages", 10), 50)
    max_depth = min(args.get("max_depth", 2), 5)

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
                    pages.append(
                        {
                            "url": page.url,
                            "title": page.metadata.get("title", ""),
                            "content": content,
                            "word_count": page.word_count,
                        }
                    )

            return _json(
                {
                    "start_url": url,
                    "total_pages": job.total_pages,
                    "successful_pages": job.successful_pages,
                    "total_words": job.total_words,
                    "pages": pages,
                }
            )

    except Exception as e:
        return _error(str(e))


async def handle_discover_urls(args: dict[str, Any]) -> str:
    """
    Discover URLs on a website.

    Args:
        args: Tool arguments (url, max_urls).

    Returns:
        JSON string with discovered URLs.
    """
    from agentcrawl import DomainMapper

    url = args.get("url", "")
    if not url:
        return _error("URL is required")

    max_urls = min(args.get("max_urls", 100), 1000)

    try:
        mapper = DomainMapper(max_urls=max_urls)
        urls = await mapper.discover(url)

        return _json(
            {
                "url": url,
                "total_urls": len(urls),
                "urls": urls[:max_urls],
            }
        )

    except Exception as e:
        return _error(str(e))


async def handle_extract_data(args: dict[str, Any]) -> str:
    """
    Extract structured data from a webpage.

    Args:
        args: Tool arguments (url, fields).

    Returns:
        JSON string with extracted data.
    """
    from pydantic import create_model

    from agentcrawl import CrawlEngine

    url = args.get("url", "")
    fields_str = args.get("fields", "")

    if not url:
        return _error("URL is required")

    if not fields_str:
        return _error("Fields are required")

    field_names = [f.strip() for f in fields_str.split(",") if f.strip()]

    if not field_names:
        return _error("No valid fields specified")

    try:
        field_definitions = dict.fromkeys(field_names, (str, ""))
        dynamic_model = create_model("ExtractedData", **field_definitions)

        async with CrawlEngine.default() as engine:
            result = await engine.extract(
                url,
                schema=dynamic_model,
                method="llm",
            )

            if not result.success:
                return _error(result.error or "Extraction failed", url=url)

            if result.extracted_data:
                if hasattr(result.extracted_data, "model_dump"):
                    data = result.extracted_data.model_dump()
                else:
                    data = result.extracted_data
                return _json(data)

            return _error("No data extracted", url=url)

    except Exception as e:
        return _error(str(e))


async def handle_batch_scrape(args: dict[str, Any]) -> str:
    """
    Scrape multiple URLs.

    Args:
        args: Tool arguments (urls, only_main_content).

    Returns:
        JSON string with all results.
    """
    from agentcrawl import CrawlEngine, CrawlerConfig

    urls = args.get("urls", [])
    if not urls:
        return _error("URLs list is required")

    if len(urls) > 20:
        return _error("Maximum 20 URLs per batch")

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=args.get("only_main_content", True),
        cache=True,
    )

    try:
        async with CrawlEngine.default() as engine:
            results = await engine.batch_scrape(urls, config, max_concurrent=5)

            pages = []
            for result in results:
                page: dict[str, Any] = {
                    "url": result.url,
                    "success": result.success,
                }
                if result.success:
                    content = result.markdown
                    if len(content) > 2000:
                        content = content[:2000] + "\n\n[... truncated]"
                    page["title"] = result.metadata.get("title", "")
                    page["content"] = content
                    page["word_count"] = result.word_count
                else:
                    page["error"] = result.error

                pages.append(page)

            successful = sum(1 for r in results if r.success)

            return _json(
                {
                    "total": len(results),
                    "successful": successful,
                    "failed": len(results) - successful,
                    "pages": pages,
                }
            )

    except Exception as e:
        return _error(str(e))


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════


def _json(data: Any) -> str:
    """Serialize to JSON string."""
    return json.dumps(data, ensure_ascii=False, default=str)


def _error(message: str, **extra: Any) -> str:
    """Create an error JSON string."""
    return json.dumps({"error": message, **extra}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# Global Registry
# ══════════════════════════════════════════════════════════════

_global_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """
    Get the global tool registry.

    Returns:
        ToolRegistry instance with all default tools.
    """
    global _global_registry

    if _global_registry is None:
        _global_registry = ToolRegistry()

    return _global_registry
