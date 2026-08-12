"""AgentCrawl — MCP Tools (Canonical Server Tool Contract)
========================================================

This module is the **single authoritative source** for the AgentCrawl MCP
server tool contract.  It defines, in exactly one place:

* the canonical MCP tool names
* the machine-readable JSON Schema input schema for each tool
* the human-readable description
* the handler association (a coroutine that performs the work)

Design rules enforced here (Set B architectural requirement):

* There is no duplicate ``TOOLS`` list, no separate ``TOOL_HANDLERS`` dict, and
  no second ``ToolRegistry``.  :data:`TOOL_DEFINITIONS` is the canonical
  contract and :func:`get_tool` is the only dispatch table.
* Handlers raise :class:`ToolError` on controlled failure so that the MCP
  server can map the failure to a correct ``isError`` result rather than
  embedding ``{"error": ...}`` inside successful ``TextContent``.
* Handlers return raw Python objects (dict / list / str).  Serialization to
  JSON text is the server layer's responsibility, keeping handlers pure.
* Handlers receive the server-owned shared ``CrawlEngine`` as a second
  argument (G1) so the engine is created once per server lifetime and its
  memory cache persists across calls (G3).  Handlers do not instantiate a
  fresh ``CrawlEngine`` per invocation — the engine and its browser/cache
  lifecycle are owned by the MCP server lifespan (G4).

Canonical tool names (established here, documented in REQ-B03):

    scrape_webpage, search_web, crawl_website,
    discover_urls, extract_data, batch_scrape

Usage in :mod:`server.mcp.server`:

    from server.mcp.tools import TOOL_DEFINITIONS, ToolError, get_tool, _serialize

    tool_names = [t.name for t in TOOL_DEFINITIONS]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("agentcrawl.mcp.tools")


# ══════════════════════════════════════════════════════════════
# Error contract
# ══════════════════════════════════════════════════════════════


class ToolError(Exception):
    """Raised by a tool handler to signal a controlled, client-visible error.

    The MCP server layer catches this and returns a ``CallToolResult`` with
    ``isError=True`` and the message surfaced via an ``ErrorData`` result,
    rather than leaking a stack trace.
    """

    def __init__(self, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data = data or {}


# ══════════════════════════════════════════════════════════════
# Tool Definition
# ══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ToolDefinition:
    """Canonical MCP tool contract.

    Attributes:
        name: Stable MCP tool name.
        description: Human-readable description surfaced in ``tools/list``.
        input_schema: JSON Schema (dict) accepted as ``inputSchema``.
        handler: Coroutine ``handler(arguments: dict, engine) -> Any`` producing the
            tool's return value (a plain Python object serialized by the
            server layer).  ``engine`` is the shared CrawlEngine owned by the
            MCP server lifespan.
        category: Internal grouping label (not exposed over MCP).
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], Any], Awaitable[Any]]
    category: str = "general"
    _handler_name: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_handler_name", self.handler.__name__)


# Helper to build a JSON-Schema object-typed input schema concisely.
def _schema(
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ══════════════════════════════════════════════════════════════
# Tool handlers
#
# Each handler is a coroutine:  handler(arguments: dict[str, Any], engine: Any) -> Any
#
# * The ``engine`` is the server-owned shared CrawlEngine (G1).  Handlers
#   do *not* create their own engine via ``CrawlEngine.default()``.
# * Returns a plain Python object (dict / list / str) on success.
# * Raises :class:`ToolError` for controlled, client-visible failures.
# * The MCP server lifespan owns the engine/browser/cache lifecycle and
#   performs graceful shutdown (G4).  Concurrency is bounded by a
#   server-level semaphore applied around the engine operation (G2).
# ══════════════════════════════════════════════════════════════


async def _handle_scrape_webpage(args: dict[str, Any], engine: Any) -> dict[str, Any]:
    """Scrape a single webpage -> Markdown JSON.

    Uses the server-owned shared ``engine`` (G1/G3) — no per-call engine
    creation.  Concurrency is bounded by the server-level semaphore (G2).
    """
    from agentcrawl import CrawlerConfig

    url = args.get("url", "")
    if not url:
        raise ToolError("url is required")

    include_links = bool(args.get("include_links", False))
    only_main_content = bool(args.get("only_main_content", True))

    config = CrawlerConfig(
        output_format="markdown",
        include_links=include_links,
        include_metadata=True,
        only_main_content=only_main_content,
        cache=True,
        cache_ttl=3600,
    )

    result = await engine.scrape(url, config)

    if not result.success:
        raise ToolError(result.error or "scrape failed", data={"url": url})

    response: dict[str, Any] = {
        "url": result.url,
        "title": result.metadata.get("title", ""),
        "content": result.markdown,
        "word_count": result.word_count,
    }
    if include_links and result.links:
        response["links"] = result.links.get("all", [])[:20]
    return response


async def _handle_search_web(args: dict[str, Any], engine: Any) -> dict[str, Any]:
    """Search the web via DuckDuckGo.

    ``engine`` is accepted for signature uniformity (G1); search uses the
    standalone :class:`SearchEngine` and does not consume a CrawlEngine.
    """
    from agentcrawl import SearchEngine

    query = args.get("query", "")
    if not query:
        raise ToolError("query is required")

    max_results = int(args.get("max_results", 5))

    search_engine = SearchEngine(provider="duckduckgo")
    results = await search_engine.search(query, max_results=max_results)

    return {"query": query, "results": results}


async def _handle_crawl_website(args: dict[str, Any], engine: Any) -> dict[str, Any]:
    """Crawl a website with a BFS strategy.

    Uses the server-owned shared ``engine`` (G1/G3).
    """
    from agentcrawl import BFSCrawler, CrawlerConfig

    url = args.get("url", "")
    if not url:
        raise ToolError("url is required")

    max_pages = min(int(args.get("max_pages", 10)), 50)
    max_depth = min(int(args.get("max_depth", 2)), 5)

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        cache=True,
    )

    job = await engine.crawl(
        url,
        strategy=BFSCrawler(max_depth=max_depth, max_pages=max_pages),
        config=config,
    )

    pages = []
    for page in job.pages:
        if page.success:
            content = page.markdown or ""
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

    return {
        "start_url": url,
        "total_pages": job.total_pages,
        "successful_pages": job.successful_pages,
        "total_words": job.total_words,
        "pages": pages,
    }


async def _handle_discover_urls(args: dict[str, Any], engine: Any) -> dict[str, Any]:
    """Discover URLs on a domain via sitemap/robots/link crawling.

    ``engine`` is accepted for signature uniformity (G1); discovery uses
    :class:`DomainMapper` directly.
    """
    from agentcrawl import DomainMapper

    url = args.get("url", "")
    if not url:
        raise ToolError("url is required")

    max_urls = min(int(args.get("max_urls", 100)), 1000)

    mapper = DomainMapper(max_urls=max_urls)
    urls = await mapper.discover(url)

    return {"url": url, "total_urls": len(urls), "urls": urls[:max_urls]}


async def _handle_extract_data(args: dict[str, Any], engine: Any) -> dict[str, Any]:
    """Extract structured fields from a page via LLM extraction.

    Uses the server-owned shared ``engine`` (G1/G3).
    """
    from pydantic import create_model

    from agentcrawl import CrawlerConfig

    url = args.get("url", "")
    fields_str = args.get("fields", "")
    if not url:
        raise ToolError("url is required")
    if not fields_str:
        raise ToolError("fields is required")

    field_names = [f.strip() for f in fields_str.split(",") if f.strip()]
    if not field_names:
        raise ToolError("No valid fields specified")

    # Build a dynamic Pydantic model describing the fields to extract.
    # Each field is a string with an empty default.
    field_definitions = dict.fromkeys(field_names, (str, ""))
    dynamic_model = create_model("ExtractedData", **field_definitions)

    config = CrawlerConfig(extraction="llm")

    result = await engine.extract(
        url,
        schema=dynamic_model,
        config=config,
    )

    if not result.success:
        raise ToolError(result.error or "extraction failed", data={"url": url})

    if result.extracted_data:
        if hasattr(result.extracted_data, "model_dump"):
            return result.extracted_data.model_dump()
        return result.extracted_data  # type: ignore[return-value]

    raise ToolError("No data extracted", data={"url": url})


async def _handle_batch_scrape(args: dict[str, Any], engine: Any) -> dict[str, Any]:
    """Scrape multiple URLs concurrently.

    Uses the server-owned shared ``engine`` (G1/G3).  The MCP-level
    concurrency semaphore (G2) further bounds execution at the server level.
    """
    from agentcrawl import CrawlerConfig

    urls = args.get("urls", [])
    if not urls:
        raise ToolError("urls is required")
    if not isinstance(urls, list):
        raise ToolError("urls must be a list of strings")
    if len(urls) > 20:
        raise ToolError("Maximum 20 URLs per batch")

    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=bool(args.get("only_main_content", True)),
        cache=True,
    )

    results = await engine.batch_scrape(urls, config, max_concurrent=5)

    pages = []
    for result in results:
        page: dict[str, Any] = {
            "url": result.url,
            "success": result.success,
        }
        if result.success:
            content = result.markdown or ""
            if len(content) > 2000:
                content = content[:2000] + "\n\n[... truncated]"
            page["title"] = result.metadata.get("title", "")
            page["content"] = content
            page["word_count"] = result.word_count
        else:
            page["error"] = result.error
        pages.append(page)

    successful = sum(1 for r in results if r.success)
    return {
        "total": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "pages": pages,
    }


# ══════════════════════════════════════════════════════════════
# Canonical tool definitions (single source of truth)
#
# Order is significant — it defines the deterministic ``tools/list`` ordering
# required by REQ-B13.  Handlers are defined above so the references resolve.
# ══════════════════════════════════════════════════════════════

TOOL_DEFINITIONS: list[ToolDefinition] = [
    ToolDefinition(
        name="scrape_webpage",
        description=(
            "Scrape a single webpage and return its content as clean Markdown. "
            "Removes navigation, ads, and boilerplate. "
            "Use this to read the content of a specific URL."
        ),
        input_schema=_schema(
            {
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
            ["url"],
        ),
        handler=_handle_scrape_webpage,
        category="scraping",
    ),
    ToolDefinition(
        name="search_web",
        description=(
            "Search the web and return results with titles, URLs, and snippets. "
            "Use this to find relevant pages before scraping them."
        ),
        input_schema=_schema(
            {
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
            ["query"],
        ),
        handler=_handle_search_web,
        category="search",
    ),
    ToolDefinition(
        name="crawl_website",
        description=(
            "Crawl a website starting from a URL and return content from "
            "multiple pages. Use this to gather information from documentation "
            "sites or multi-page resources."
        ),
        input_schema=_schema(
            {
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
            ["url"],
        ),
        handler=_handle_crawl_website,
        category="crawling",
    ),
    ToolDefinition(
        name="discover_urls",
        description=(
            "Discover all URLs on a website without scraping content. "
            "Uses sitemap.xml, robots.txt, and link crawling. "
            "Use this to understand a site's structure."
        ),
        input_schema=_schema(
            {
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
            ["url"],
        ),
        handler=_handle_discover_urls,
        category="discovery",
    ),
    ToolDefinition(
        name="extract_data",
        description=(
            "Extract structured data from a webpage using CSS selectors. "
            "Define fields with selectors to extract specific data. "
            "Returns structured JSON."
        ),
        input_schema=_schema(
            {
                "url": {
                    "type": "string",
                    "description": "The URL to extract from",
                },
                "fields": {
                    "type": "string",
                    "description": (
                        "Comma-separated field names to extract. Example: 'title,price,description'"
                    ),
                },
            },
            ["url", "fields"],
        ),
        handler=_handle_extract_data,
        category="extraction",
    ),
    ToolDefinition(
        name="batch_scrape",
        description=(
            "Scrape multiple URLs at once and return all results. "
            "More efficient than calling scrape_webpage multiple times."
        ),
        input_schema=_schema(
            {
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
            ["urls"],
        ),
        handler=_handle_batch_scrape,
        category="scraping",
    ),
]

# Deterministic ordering is guaranteed by the explicit list order above.
CANONICAL_TOOL_ORDER: list[str] = [t.name for t in TOOL_DEFINITIONS]


# ══════════════════════════════════════════════════════════════
# Dispatch helpers (single source of truth for tools/list & tools/call)
# ══════════════════════════════════════════════════════════════


def get_tool(name: str) -> ToolDefinition | None:
    """Look up a canonical tool definition by name.

    Returns ``None`` for unknown tools so callers can distinguish
    "unknown tool" from a handler error.
    """
    for tool in TOOL_DEFINITIONS:
        if tool.name == name:
            return tool
    return None


def list_tool_names() -> list[str]:
    """Return canonical tool names in deterministic order."""
    return list(CANONICAL_TOOL_ORDER)


def _to_mcp_tool(tool: ToolDefinition) -> dict[str, Any]:
    """Render a :class:`ToolDefinition` as an MCP ``Tool`` dict."""
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
    }


def to_mcp_tool_list() -> list[dict[str, Any]]:
    """Render every canonical tool as an MCP ``Tool`` dict (ordered)."""
    return [_to_mcp_tool(t) for t in TOOL_DEFINITIONS]


def _serialize(result: Any) -> str:
    """Serialize a handler return value to a JSON text string.

    The server layer wraps this in ``TextContent``; failures are routed
    through :class:`ToolError` and mapped to ``isError`` results instead.
    """
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


__all__ = [
    "CANONICAL_TOOL_ORDER",
    "TOOL_DEFINITIONS",
    "ToolDefinition",
    "ToolError",
    "_serialize",
    "get_tool",
    "list_tool_names",
    "to_mcp_tool_list",
]
