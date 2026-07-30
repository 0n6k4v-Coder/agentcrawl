"""
AgentCrawl — AI Agent Tool Wrappers
=====================================

Provides ready-to-use tool wrappers for popular AI agent frameworks:
  - LangChain (BaseTool / StructuredTool)
  - CrewAI (BaseTool)
  - OpenAI Function Calling (handler)
  - Generic (any custom agent harness)

All wrappers share the same core CrawlEngine, ensuring consistent
behavior across Package Mode, Server Mode, and Agent Mode.

Usage:
    # LangChain
    from agentcrawl.agent.tool import AgentCrawlTool
    tools = [AgentCrawlTool()]

    # CrewAI
    from agentcrawl.agent.tool import CrewAICrawlTool
    tools = [CrewAICrawlTool()]

    # OpenAI Function Calling
    from agentcrawl.agent.tool import OpenAIFunctionHandler
    handler = OpenAIFunctionHandler()
    result = await handler.handle_tool_call("web_scrape", {"url": "..."})

    # Generic
    from agentcrawl.agent.tool import AgentCrawlToolkit
    toolkit = AgentCrawlToolkit()
    result = await toolkit.execute("web_scrape", url="https://example.com")
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("agentcrawl.agent")


# ══════════════════════════════════════════════════════════════
# Pydantic Input Schemas (for LangChain / CrewAI)
# ══════════════════════════════════════════════════════════════

class WebScrapeInput(BaseModel):
    """Input schema for web_scrape tool."""
    url: str = Field(description="The full URL of the web page to scrape.")
    output_format: str = Field(
        default="markdown",
        description="Output format: 'markdown', 'json', or 'html'.",
    )
    include_links: bool = Field(
        default=True,
        description="Whether to include extracted links in the response.",
    )
    include_metadata: bool = Field(
        default=True,
        description="Whether to include page metadata (title, description, og:tags).",
    )
    stealth: bool = Field(
        default=True,
        description="Enable stealth mode to bypass anti-bot detection.",
    )
    timeout: int = Field(
        default=30,
        description="Page load timeout in seconds.",
    )


class WebCrawlInput(BaseModel):
    """Input schema for web_crawl tool."""
    url: str = Field(description="The starting URL to crawl from.")
    strategy: str = Field(
        default="bfs",
        description="Crawling strategy: 'bfs', 'dfs', or 'best_first'.",
    )
    max_depth: int = Field(default=3, description="Maximum link depth.")
    max_pages: int = Field(default=50, description="Maximum pages to crawl.")
    output_format: str = Field(
        default="markdown",
        description="Output format: 'markdown', 'json', or 'html'.",
    )
    same_domain_only: bool = Field(
        default=True,
        description="Only crawl pages on the same domain.",
    )


class WebSearchInput(BaseModel):
    """Input schema for web_search tool."""
    query: str = Field(description="The search query string.")
    max_results: int = Field(default=5, description="Maximum search results.")
    scrape_results: bool = Field(
        default=True,
        description="Whether to scrape full content of each result.",
    )
    output_format: str = Field(
        default="markdown",
        description="Output format for scraped content.",
    )


class WebMapInput(BaseModel):
    """Input schema for web_map tool."""
    url: str = Field(description="The website URL to map.")
    max_urls: int = Field(default=500, description="Maximum URLs to discover.")
    use_sitemap: bool = Field(default=True, description="Parse sitemap.xml.")
    use_robots: bool = Field(default=True, description="Parse robots.txt.")


class WebExtractInput(BaseModel):
    """Input schema for web_extract tool."""
    model_config = ConfigDict(protected_namespaces=())

    url: str = Field(description="The URL to extract data from.")
    schema_json: str = Field(
        description=(
            "JSON schema describing the data to extract. "
            'Example: {"type": "object", "properties": {"name": {"type": "string"}}}'
        ),
    )
    method: str = Field(
        default="llm",
        description="Extraction method: 'llm', 'css', or 'xpath'.",
    )
    prompt: str = Field(
        default="",
        description="Optional custom prompt to guide LLM extraction.",
    )


class WebScreenshotInput(BaseModel):
    """Input schema for web_screenshot tool."""
    url: str = Field(description="The URL to screenshot.")
    full_page: bool = Field(default=True, description="Capture full page or viewport.")
    format: str = Field(default="png", description="Image format: 'png' or 'jpeg'.")


class WebBatchScrapeInput(BaseModel):
    """Input schema for web_batch_scrape tool."""
    urls: str = Field(
        description="Comma-separated list of URLs to scrape.",
    )
    output_format: str = Field(
        default="markdown",
        description="Output format: 'markdown', 'json', or 'html'.",
    )
    max_concurrent: int = Field(default=5, description="Max concurrent scrapes.")


# ══════════════════════════════════════════════════════════════
# Core Engine Manager (Shared Singleton)
# ══════════════════════════════════════════════════════════════

class _EngineManager:
    """
    Manages the shared CrawlEngine instance for agent tools.

    Lazily initializes the engine on first use and provides
    a clean shutdown mechanism.
    """

    def __init__(self) -> None:
        self._engine: Any = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def get_engine(self) -> Any:
        """Get or create the shared CrawlEngine instance."""
        if self._engine is not None:
            return self._engine

        async with self._lock:
            if self._engine is not None:
                return self._engine

            from agentcrawl.config.settings import Settings
            from agentcrawl.core.engine import CrawlEngine

            settings = Settings()
            self._engine = CrawlEngine.from_settings(settings)
            await self._engine.startup()
            self._initialized = True
            logger.info("AgentCrawl engine initialized for agent tools")
            return self._engine

    async def shutdown(self) -> None:
        """Shut down the engine and release resources."""
        if self._engine is not None:
            await self._engine.shutdown()
            self._engine = None
            self._initialized = False
            logger.info("AgentCrawl engine shut down")

    @property
    def is_initialized(self) -> bool:
        return self._initialized


# Global engine manager (shared across all tool instances)
_engine_manager = _EngineManager()


# ══════════════════════════════════════════════════════════════
# Generic Toolkit (Framework-Agnostic)
# ══════════════════════════════════════════════════════════════

class AgentCrawlToolkit:
    """
    Framework-agnostic toolkit for AI agent integration.

    Provides a unified interface to all AgentCrawl tools that can be
    used with any custom agent harness.

    Example:
        >>> toolkit = AgentCrawlToolkit()
        >>> result = await toolkit.execute("web_scrape", url="https://example.com")
        >>> print(result["content"])

        >>> # List available tools
        >>> tools = toolkit.list_tools()

        >>> # Get OpenAI-compatible schema
        >>> schema = toolkit.get_openai_schema()

        >>> # Cleanup
        >>> await toolkit.close()
    """

    def __init__(
        self,
        max_content_length: int = 50_000,
        return_format: str = "dict",
    ):
        """
        Args:
            max_content_length: Maximum content length to return (chars).
                                Longer content is truncated with a notice.
            return_format: Return format — 'dict', 'json', or 'text'.
        """
        self._max_content_length = max_content_length
        self._return_format = return_format
        self._tool_registry: dict[str, dict[str, Any]] = self._build_registry()

    def _build_registry(self) -> dict[str, dict[str, Any]]:
        """Build the internal tool registry."""
        return {
            "web_scrape": {
                "description": "Scrape a single web page and return clean Markdown, JSON, or HTML.",
                "handler": self._handle_scrape,
                "input_schema": WebScrapeInput,
            },
            "web_crawl": {
                "description": "Crawl an entire website starting from a URL.",
                "handler": self._handle_crawl,
                "input_schema": WebCrawlInput,
            },
            "web_search": {
                "description": "Search the web and optionally scrape results.",
                "handler": self._handle_search,
                "input_schema": WebSearchInput,
            },
            "web_map": {
                "description": "Discover all URLs on a website without scraping content.",
                "handler": self._handle_map,
                "input_schema": WebMapInput,
            },
            "web_extract": {
                "description": "Extract structured data from a web page using LLM or CSS/XPath.",
                "handler": self._handle_extract,
                "input_schema": WebExtractInput,
            },
            "web_screenshot": {
                "description": "Capture a screenshot of a web page.",
                "handler": self._handle_screenshot,
                "input_schema": WebScreenshotInput,
            },
            "web_batch_scrape": {
                "description": "Scrape multiple URLs in a single call.",
                "handler": self._handle_batch_scrape,
                "input_schema": WebBatchScrapeInput,
            },
        }

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, str]]:
        """List all available tools with descriptions."""
        return [
            {"name": name, "description": info["description"]}
            for name, info in self._tool_registry.items()
        ]

    def get_tool_names(self) -> list[str]:
        """Get list of available tool names."""
        return list(self._tool_registry.keys())

    def get_openai_schema(self, tools: list[str] | None = None) -> list[dict[str, Any]]:
        """Get OpenAI function calling schema for all or selected tools."""
        from agentcrawl.agent.function_schema import get_openai_tools_schema
        return get_openai_tools_schema(tools)

    def get_anthropic_schema(self, tools: list[str] | None = None) -> list[dict[str, Any]]:
        """Get Anthropic tool use schema for all or selected tools."""
        from agentcrawl.agent.function_schema import get_anthropic_tools_schema
        return get_anthropic_tools_schema(tools)

    async def execute(self, tool_name: str, **kwargs: Any) -> Any:
        """
        Execute a tool by name with keyword arguments.

        Args:
            tool_name: Name of the tool (e.g., 'web_scrape').
            **kwargs: Tool arguments.

        Returns:
            Result in the configured return_format.

        Raises:
            ValueError: If tool_name is unknown.
            Exception: If tool execution fails.
        """
        if tool_name not in self._tool_registry:
            available = ", ".join(sorted(self._tool_registry.keys()))
            raise ValueError(
                f"Unknown tool: '{tool_name}'. Available: {available}"
            )

        handler = self._tool_registry[tool_name]["handler"]

        try:
            result = await handler(**kwargs)
        except Exception as e:
            logger.error("Tool '%s' failed: %s", tool_name, e)
            result = {
                "success": False,
                "error": str(e),
                "tool": tool_name,
            }

        return self._format_result(result)

    async def execute_json(self, tool_name: str, arguments_json: str) -> Any:
        """
        Execute a tool with a JSON string of arguments.

        Useful for handling LLM function call outputs directly.

        Args:
            tool_name: Name of the tool.
            arguments_json: JSON string of arguments.

        Returns:
            Formatted result.
        """
        try:
            kwargs = json.loads(arguments_json)
        except json.JSONDecodeError as e:
            return self._format_result({
                "success": False,
                "error": f"Invalid JSON arguments: {e}",
                "tool": tool_name,
            })

        return await self.execute(tool_name, **kwargs)

    async def close(self) -> None:
        """Shut down the engine and release all resources."""
        await _engine_manager.shutdown()

    async def __aenter__(self) -> AgentCrawlToolkit:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ──────────────────────────────────────────────────────────
    # Tool Handlers
    # ──────────────────────────────────────────────────────────

    async def _handle_scrape(
        self,
        url: str,
        output_format: str = "markdown",
        include_links: bool = True,
        include_metadata: bool = True,
        stealth: bool = True,
        timeout: int = 30,
        **kwargs: Any,
    ) -> dict[str, Any]:
        engine = await _engine_manager.get_engine()

        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            output_format=output_format,
            include_links=include_links,
            include_metadata=include_metadata,
            timeout=timeout,
        )

        result = await engine.scrape(url=url, config=config)

        output: dict[str, Any] = {
            "success": True,
            "url": result.url,
            "content": self._truncate(result.markdown if output_format == "markdown" else result.to_json()),
            "format": output_format,
        }

        if include_metadata and hasattr(result, "metadata"):
            output["metadata"] = result.metadata

        if include_links and hasattr(result, "links"):
            output["links"] = result.links

        return output

    async def _handle_crawl(
        self,
        url: str,
        strategy: str = "bfs",
        max_depth: int = 3,
        max_pages: int = 50,
        output_format: str = "markdown",
        same_domain_only: bool = True,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        engine = await _engine_manager.get_engine()

        from agentcrawl.config.crawler_config import CrawlerConfig
        from agentcrawl.crawling import BestFirstCrawler, BFSCrawler, DFSCrawler, URLFilter

        strategy_map = {
            "bfs": BFSCrawler,
            "dfs": DFSCrawler,
            "best_first": BestFirstCrawler,
        }

        crawler_cls = strategy_map.get(strategy, BFSCrawler)
        url_filter = URLFilter(
            include_patterns=include_patterns or [],
            exclude_patterns=exclude_patterns or [],
        ) if (include_patterns or exclude_patterns) else None

        crawler_strategy = crawler_cls(
            max_depth=max_depth,
            max_pages=max_pages,
            url_filter=url_filter,
        )

        config = CrawlerConfig(output_format=output_format)
        results = await engine.crawl(url=url, strategy=crawler_strategy, config=config)

        pages = []
        for page in results:
            pages.append({
                "url": page.url,
                "content": self._truncate(
                    page.markdown if output_format == "markdown" else page.to_json()
                ),
                "status": getattr(page, "status_code", 200),
            })

        return {
            "success": True,
            "start_url": url,
            "strategy": strategy,
            "pages_crawled": len(pages),
            "pages": pages,
        }

    async def _handle_search(
        self,
        query: str,
        max_results: int = 5,
        scrape_results: bool = True,
        output_format: str = "markdown",
        search_engine: str = "google",
        **kwargs: Any,
    ) -> dict[str, Any]:
        engine = await _engine_manager.get_engine()

        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(output_format=output_format)
        results = await engine.search(
            query=query,
            max_results=max_results,
            scrape=scrape_results,
            config=config,
        )

        items = []
        for r in results:
            item: dict[str, Any] = {
                "title": r.title,
                "url": r.url,
                "snippet": getattr(r, "snippet", ""),
            }
            if scrape_results and hasattr(r, "markdown"):
                item["content"] = self._truncate(r.markdown)
            items.append(item)

        return {
            "success": True,
            "query": query,
            "results_count": len(items),
            "results": items,
        }

    async def _handle_map(
        self,
        url: str,
        max_urls: int = 500,
        use_sitemap: bool = True,
        use_robots: bool = True,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        engine = await _engine_manager.get_engine()

        urls = await engine.map(
            url=url,
            max_urls=max_urls,
            use_sitemap=use_sitemap,
            use_robots=use_robots,
        )

        return {
            "success": True,
            "url": url,
            "urls_found": len(urls),
            "urls": urls[:max_urls],
        }

    async def _handle_extract(
        self,
        url: str,
        schema_json: str = "{}",
        method: str = "llm",
        prompt: str = "",
        css_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        engine = await _engine_manager.get_engine()

        from agentcrawl.config.crawler_config import CrawlerConfig

        try:
            schema = json.loads(schema_json) if isinstance(schema_json, str) else schema_json
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid schema JSON: {e}",
            }

        if method == "css" and css_schema:
            from agentcrawl.extraction import JsonCssExtractor
            extraction = JsonCssExtractor(schema=css_schema)
        elif method == "xpath":
            from agentcrawl.extraction import JsonXPathExtractor
            extraction = JsonXPathExtractor(schema=schema)
        else:
            from agentcrawl.config.llm_config import LLMConfig
            from agentcrawl.extraction import LLMExtractor
            extraction = LLMExtractor(
                schema=schema,
                llm_config=LLMConfig(),
                prompt=prompt or None,
            )

        config = CrawlerConfig(extraction=extraction)
        result = await engine.scrape(url=url, config=config)

        return {
            "success": True,
            "url": url,
            "method": method,
            "extracted_data": result.extracted_data,
        }

    async def _handle_screenshot(
        self,
        url: str,
        full_page: bool = True,
        format_: str = "png",
        quality: int = 80,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        **kwargs: Any,
    ) -> dict[str, Any]:
        engine = await _engine_manager.get_engine()

        from agentcrawl.config.crawler_config import CrawlerConfig

        config = CrawlerConfig(
            screenshot=True,
            screenshot_full_page=full_page,
            screenshot_format=format_,
            screenshot_quality=quality,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )

        result = await engine.scrape(url=url, config=config)

        return {
            "success": True,
            "url": url,
            "screenshot_base64": getattr(result, "screenshot", ""),
            "format": format,
            "full_page": full_page,
        }

    async def _handle_batch_scrape(
        self,
        urls: str | list[str] = "",
        output_format: str = "markdown",
        max_concurrent: int = 5,
        stealth: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        engine = await _engine_manager.get_engine()

        from agentcrawl.config.crawler_config import CrawlerConfig

        # Parse URLs
        if isinstance(urls, str):
            url_list = [u.strip() for u in urls.split(",") if u.strip()]
        else:
            url_list = urls

        if not url_list:
            return {"success": False, "error": "No URLs provided."}

        config = CrawlerConfig(output_format=output_format)
        results = await engine.batch_scrape(
            urls=url_list,
            config=config,
            max_concurrent=max_concurrent,
        )

        pages = []
        for r in results:
            pages.append({
                "url": r.url,
                "success": r.success if hasattr(r, "success") else True,
                "content": self._truncate(
                    r.markdown if output_format == "markdown" else r.to_json()
                ),
            })

        return {
            "success": True,
            "total_urls": len(url_list),
            "successful": sum(1 for p in pages if p["success"]),
            "failed": sum(1 for p in pages if not p["success"]),
            "pages": pages,
        }

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _truncate(self, content: str) -> str:
        """Truncate content to max length with a notice."""
        if len(content) <= self._max_content_length:
            return content
        truncated = content[: self._max_content_length]
        truncated += f"\n\n[... content truncated at {self._max_content_length} chars. Total: {len(content)} chars]"
        return truncated

    def _format_result(self, result: dict[str, Any]) -> Any:
        """Format result according to return_format setting."""
        if self._return_format == "json":
            return json.dumps(result, ensure_ascii=False, default=str)
        elif self._return_format == "text":
            if result.get("success") is False:
                return f"Error: {result.get('error', 'Unknown error')}"
            return result.get("content", json.dumps(result, ensure_ascii=False, default=str))
        return result


# ══════════════════════════════════════════════════════════════
# LangChain Tool
# ══════════════════════════════════════════════════════════════

try:
    from langchain.tools import BaseTool

    class AgentCrawlTool(BaseTool):
        """
        LangChain tool for web scraping via AgentCrawl.

        Scrapes a web page and returns clean Markdown content optimized for LLMs.

        Example:
            >>> from agentcrawl.agent.tool import AgentCrawlTool
            >>> tool = AgentCrawlTool()
            >>> result = tool.invoke({"url": "https://example.com"})
            >>> print(result)
        """

        name: str = "web_scraper"
        description: str = (
            "Scrape a web page and return its content as clean Markdown. "
            "Use this tool when you need to read the content of a specific URL. "
            "Input should be a URL string or a JSON object with 'url' and optional "
            "'output_format' (markdown/json/html), 'include_links' (bool), "
            "'include_metadata' (bool), and 'stealth' (bool) fields."
        )
        args_schema: type[BaseModel] = WebScrapeInput
        toolkit: AgentCrawlToolkit | None = None
        return_direct: bool = False

        def _get_toolkit(self) -> AgentCrawlToolkit:
            if self.toolkit is None:
                self.toolkit = AgentCrawlToolkit(return_format="text")
            return self.toolkit

        def _run(
            self,
            url: str,
            output_format: str = "markdown",
            include_links: bool = True,
            include_metadata: bool = True,
            stealth: bool = True,
            timeout: int = 30,
        ) -> str:
            """Synchronous execution (runs async in event loop)."""
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = pool.submit(
                            asyncio.run,
                            self._arun(url, output_format, include_links, include_metadata, stealth, timeout),
                        ).result()
                    return result
                else:
                    return asyncio.run(
                        self._arun(url, output_format, include_links, include_metadata, stealth, timeout)
                    )
            except RuntimeError:
                return asyncio.run(
                    self._arun(url, output_format, include_links, include_metadata, stealth, timeout)
                )

        async def _arun(
            self,
            url: str,
            output_format: str = "markdown",
            include_links: bool = True,
            include_metadata: bool = True,
            stealth: bool = True,
            timeout: int = 30,
        ) -> str:
            """Async execution."""
            toolkit = self._get_toolkit()
            result = await toolkit.execute(
                "web_scrape",
                url=url,
                output_format=output_format,
                include_links=include_links,
                include_metadata=include_metadata,
                stealth=stealth,
                timeout=timeout,
            )
            if isinstance(result, dict):
                if result.get("success") is False:
                    return f"Error scraping {url}: {result.get('error', 'Unknown error')}"
                return result.get("content", str(result))
            return str(result)

    class AgentCrawlSearchTool(BaseTool):
        """LangChain tool for web search via AgentCrawl."""

        name: str = "web_search"
        description: str = (
            "Search the web for information and optionally scrape the results. "
            "Use this when you need to find information across the web. "
            "Input should be a search query string."
        )
        args_schema: type[BaseModel] = WebSearchInput
        toolkit: AgentCrawlToolkit | None = None

        def _get_toolkit(self) -> AgentCrawlToolkit:
            if self.toolkit is None:
                self.toolkit = AgentCrawlToolkit(return_format="text")
            return self.toolkit

        def _run(self, query: str, max_results: int = 5, scrape_results: bool = True) -> str:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        return pool.submit(
                            asyncio.run,
                            self._arun(query, max_results, scrape_results),
                        ).result()
                return asyncio.run(self._arun(query, max_results, scrape_results))
            except RuntimeError:
                return asyncio.run(self._arun(query, max_results, scrape_results))

        async def _arun(self, query: str, max_results: int = 5, scrape_results: bool = True) -> str:
            toolkit = self._get_toolkit()
            result = await toolkit.execute(
                "web_search",
                query=query,
                max_results=max_results,
                scrape_results=scrape_results,
            )
            if isinstance(result, dict):
                if result.get("success") is False:
                    return f"Search error: {result.get('error', 'Unknown error')}"
                items = result.get("results", [])
                parts = []
                for item in items:
                    parts.append(f"## {item.get('title', 'Untitled')}\nURL: {item.get('url', '')}")
                    if item.get("content"):
                        parts.append(item["content"][:1000])
                return "\n\n".join(parts) if parts else "No results found."
            return str(result)

    class AgentCrawlCrawlTool(BaseTool):
        """LangChain tool for website crawling via AgentCrawl."""

        name: str = "web_crawler"
        description: str = (
            "Crawl an entire website starting from a URL. Discovers and scrapes "
            "multiple pages. Use this when you need content from multiple pages of a site. "
            "Input should be a starting URL."
        )
        args_schema: type[BaseModel] = WebCrawlInput
        toolkit: AgentCrawlToolkit | None = None

        def _get_toolkit(self) -> AgentCrawlToolkit:
            if self.toolkit is None:
                self.toolkit = AgentCrawlToolkit(return_format="text")
            return self.toolkit

        def _run(self, url: str, max_depth: int = 3, max_pages: int = 50) -> str:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        return pool.submit(
                            asyncio.run,
                            self._arun(url, max_depth, max_pages),
                        ).result()
                return asyncio.run(self._arun(url, max_depth, max_pages))
            except RuntimeError:
                return asyncio.run(self._arun(url, max_depth, max_pages))

        async def _arun(self, url: str, max_depth: int = 3, max_pages: int = 50) -> str:
            toolkit = self._get_toolkit()
            result = await toolkit.execute(
                "web_crawl",
                url=url,
                max_depth=max_depth,
                max_pages=max_pages,
            )
            if isinstance(result, dict):
                if result.get("success") is False:
                    return f"Crawl error: {result.get('error', 'Unknown error')}"
                pages = result.get("pages", [])
                parts = [f"Crawled {len(pages)} pages from {url}:"]
                for page in pages[:20]:
                    parts.append(f"\n### {page.get('url', '')}\n{page.get('content', '')[:500]}")
                return "\n".join(parts)
            return str(result)

    def get_langchain_tools(
        toolkit: AgentCrawlToolkit | None = None,
    ) -> list[BaseTool]:
        """
        Get all AgentCrawl tools as LangChain BaseTool instances.

        Args:
            toolkit: Optional shared toolkit instance.

        Returns:
            List of LangChain tools.

        Example:
            >>> from agentcrawl.agent.tool import get_langchain_tools
            >>> tools = get_langchain_tools()
            >>> agent = initialize_agent(tools=tools, llm=llm, ...)
        """
        tk = toolkit or AgentCrawlToolkit(return_format="text")
        return [
            AgentCrawlTool(toolkit=tk),
            AgentCrawlSearchTool(toolkit=tk),
            AgentCrawlCrawlTool(toolkit=tk),
        ]

except ImportError:
    # LangChain not installed — provide stubs
    AgentCrawlTool = None  # type: ignore[assignment,misc]
    AgentCrawlSearchTool = None  # type: ignore[assignment,misc]
    AgentCrawlCrawlTool = None  # type: ignore[assignment,misc]

    def get_langchain_tools(toolkit: Any = None) -> list[Any]:  # type: ignore[misc]
        raise ImportError(
            "LangChain is required. Install with: pip install langchain langchain-openai"
        )


# ══════════════════════════════════════════════════════════════
# CrewAI Tool
# ══════════════════════════════════════════════════════════════

try:
    from crewai.tools import BaseTool as CrewAIBaseTool

    class CrewAICrawlTool(CrewAIBaseTool):
        """
        CrewAI tool for web scraping via AgentCrawl.

        Example:
            >>> from agentcrawl.agent.tool import CrewAICrawlTool
            >>> tool = CrewAICrawlTool()
            >>> # Use in CrewAI agent definition
        """

        name: str = "Web Scraper"
        description: str = (
            "Scrape a web page and return clean Markdown content. "
            "Input: a JSON string with 'url' (required) and optional "
            "'output_format', 'include_links', 'stealth' fields."
        )
        toolkit: AgentCrawlToolkit | None = None

        def _get_toolkit(self) -> AgentCrawlToolkit:
            if self.toolkit is None:
                self.toolkit = AgentCrawlToolkit(return_format="text")
            return self.toolkit

        def _run(self, **kwargs: Any) -> str:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        return pool.submit(
                            asyncio.run,
                            self._arun(**kwargs),
                        ).result()
                return asyncio.run(self._arun(**kwargs))
            except RuntimeError:
                return asyncio.run(self._arun(**kwargs))

        async def _arun(self, **kwargs: Any) -> str:
            toolkit = self._get_toolkit()
            result = await toolkit.execute("web_scrape", **kwargs)
            if isinstance(result, dict):
                if result.get("success") is False:
                    return f"Error: {result.get('error', 'Unknown error')}"
                return result.get("content", str(result))
            return str(result)

    class CrewAISearchTool(CrewAIBaseTool):
        """CrewAI tool for web search via AgentCrawl."""

        name: str = "Web Search"
        description: str = (
            "Search the web for information. "
            "Input: a JSON string with 'query' (required) and optional 'max_results'."
        )
        toolkit: AgentCrawlToolkit | None = None

        def _get_toolkit(self) -> AgentCrawlToolkit:
            if self.toolkit is None:
                self.toolkit = AgentCrawlToolkit(return_format="text")
            return self.toolkit

        def _run(self, **kwargs: Any) -> str:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        return pool.submit(asyncio.run, self._arun(**kwargs)).result()
                return asyncio.run(self._arun(**kwargs))
            except RuntimeError:
                return asyncio.run(self._arun(**kwargs))

        async def _arun(self, **kwargs: Any) -> str:
            toolkit = self._get_toolkit()
            result = await toolkit.execute("web_search", **kwargs)
            if isinstance(result, dict):
                if result.get("success") is False:
                    return f"Error: {result.get('error', 'Unknown error')}"
                items = result.get("results", [])
                parts = []
                for item in items:
                    parts.append(f"- {item.get('title', '')}: {item.get('url', '')}")
                    if item.get("content"):
                        parts.append(f"  {item['content'][:300]}")
                return "\n".join(parts) if parts else "No results found."
            return str(result)

    def get_crewai_tools(
        toolkit: AgentCrawlToolkit | None = None,
    ) -> list[CrewAIBaseTool]:
        """
        Get all AgentCrawl tools as CrewAI BaseTool instances.

        Args:
            toolkit: Optional shared toolkit instance.

        Returns:
            List of CrewAI tools.
        """
        tk = toolkit or AgentCrawlToolkit(return_format="text")
        return [
            CrewAICrawlTool(toolkit=tk),
            CrewAISearchTool(toolkit=tk),
        ]

except ImportError:
    CrewAICrawlTool = None  # type: ignore[assignment,misc]
    CrewAISearchTool = None  # type: ignore[assignment,misc]

    def get_crewai_tools(toolkit: Any = None) -> list[Any]:  # type: ignore[misc]
        raise ImportError(
            "CrewAI is required. Install with: pip install crewai"
        )


# ══════════════════════════════════════════════════════════════
# OpenAI Function Calling Handler
# ══════════════════════════════════════════════════════════════

class OpenAIFunctionHandler:
    """
    Handler for OpenAI function calling / tool use responses.

    Parses tool_calls from OpenAI API responses and executes them
    using the AgentCrawl toolkit.

    Example:
        >>> handler = OpenAIFunctionHandler()
        >>>
        >>> response = client.chat.completions.create(
        ...     model="gpt-4o",
        ...     messages=[...],
        ...     tools=handler.get_tools_schema(),
        ...     tool_choice="auto",
        ... )
        >>>
        >>> if response.choices[0].message.tool_calls:
        ...     results = await handler.handle_response(response.choices[0].message)
        ...     for result in results:
        ...         print(result)
    """

    def __init__(
        self,
        toolkit: AgentCrawlToolkit | None = None,
        max_content_length: int = 50_000,
    ):
        self._toolkit = toolkit or AgentCrawlToolkit(
            return_format="json",
            max_content_length=max_content_length,
        )

    def get_tools_schema(self, tools: list[str] | None = None) -> list[dict[str, Any]]:
        """Get OpenAI-compatible tools schema."""
        return self._toolkit.get_openai_schema(tools)

    async def handle_tool_call(
        self,
        function_name: str,
        arguments: str | dict[str, Any],
    ) -> str:
        """
        Handle a single tool call.

        Args:
            function_name: Name of the function to call.
            arguments: JSON string or dict of arguments.

        Returns:
            JSON string result suitable for OpenAI tool message.
        """
        if isinstance(arguments, str):
            result = await self._toolkit.execute_json(function_name, arguments)
        else:
            result = await self._toolkit.execute(function_name, **arguments)

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    async def handle_response(
        self,
        message: Any,
    ) -> list[dict[str, Any]]:
        """
        Handle all tool_calls in an OpenAI response message.

        Args:
            message: OpenAI ChatCompletionMessage with tool_calls.

        Returns:
            List of tool message dicts ready to append to messages list.

        Example:
            >>> results = await handler.handle_response(response.choices[0].message)
            >>> messages.append(response.choices[0].message)
            >>> messages.extend(results)
        """
        tool_messages = []

        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return tool_messages

        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            arguments = tool_call.function.arguments

            try:
                result = await self.handle_tool_call(function_name, arguments)
            except Exception as e:
                result = json.dumps({
                    "success": False,
                    "error": str(e),
                    "tool": function_name,
                })

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        return tool_messages

    async def run_agent_loop(
        self,
        client: Any,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o",
        max_iterations: int = 10,
        **kwargs: Any,
    ) -> str:
        """
        Run a complete agent loop with tool calling until the model
        produces a final text response.

        Args:
            client: OpenAI client instance.
            messages: Initial messages list.
            model: Model to use.
            max_iterations: Maximum tool call iterations.
            **kwargs: Additional arguments for chat.completions.create.

        Returns:
            Final text response from the model.
        """
        tools = self.get_tools_schema()
        current_messages = list(messages)

        for _ in range(max_iterations):
            response = client.chat.completions.create(
                model=model,
                messages=current_messages,
                tools=tools,
                tool_choice="auto",
                **kwargs,
            )

            choice = response.choices[0]

            # No tool calls — final response
            if not choice.message.tool_calls:
                return choice.message.content or ""

            # Append assistant message with tool calls
            current_messages.append(choice.message)

            # Execute tool calls and append results
            tool_results = await self.handle_response(choice.message)
            current_messages.extend(tool_results)

        return "[Agent loop reached maximum iterations without final response]"

    async def close(self) -> None:
        """Shut down the underlying toolkit."""
        await self._toolkit.close()


# ══════════════════════════════════════════════════════════════
# Convenience Factory
# ══════════════════════════════════════════════════════════════

def create_toolkit(
    framework: str = "generic",
    **kwargs: Any,
) -> Any:
    """
    Factory function to create the appropriate tool wrapper.

    Args:
        framework: Target framework — 'langchain', 'crewai', 'openai', 'generic'.
        **kwargs: Additional arguments passed to the toolkit/tool constructor.

    Returns:
        Framework-specific tool instance(s).

    Example:
        >>> # LangChain
        >>> tools = create_toolkit("langchain")
        >>>
        >>> # CrewAI
        >>> tools = create_toolkit("crewai")
        >>>
        >>> # OpenAI
        >>> handler = create_toolkit("openai")
        >>>
        >>> # Generic
        >>> toolkit = create_toolkit("generic")
    """
    if framework == "langchain":
        return get_langchain_tools(**kwargs)
    elif framework == "crewai":
        return get_crewai_tools(**kwargs)
    elif framework == "openai":
        return OpenAIFunctionHandler(**kwargs)
    elif framework == "generic":
        return AgentCrawlToolkit(**kwargs)
    else:
        raise ValueError(
            f"Unknown framework: '{framework}'. "
            f"Available: langchain, crewai, openai, generic"
        )
