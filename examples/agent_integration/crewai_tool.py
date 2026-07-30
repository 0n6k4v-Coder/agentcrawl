"""
AgentCrawl x CrewAI Integration
==================================

CrewAI tools powered by AgentCrawl for web scraping, searching,
and structured data extraction within AI agent crews.

Prerequisites:
    pip install agentcrawl crewai

Usage:
    from examples.agent_integration.crewai_tool import (
        AgentCrawlScrapeTool,
        AgentCrawlSearchTool,
        AgentCrawlCrawlTool,
        AgentCrawlExtractTool,
    )

    # Create tools
    scrape_tool = AgentCrawlScrapeTool()
    search_tool = AgentCrawlSearchTool()

    # Use in a CrewAI agent
    from crewai import Agent, Task, Crew

    researcher = Agent(
        role="Web Researcher",
        goal="Find and extract information from the web",
        backstory="Expert at finding and extracting web content",
        tools=[scrape_tool, search_tool],
    )

    task = Task(
        description="Research the latest Python 3.13 features",
        expected_output="A summary of new features",
        agent=researcher,
    )

    crew = Crew(agents=[researcher], tasks=[task])
    result = crew.kickoff()
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    from crewai.tools import BaseTool
except ImportError as err:
    raise ImportError(
        "crewai is required for this integration. "
        "Install with: pip install crewai"
    ) from err

from pydantic import BaseModel, Field

# ══════════════════════════════════════════════════════════════
# Input Schemas
# ══════════════════════════════════════════════════════════════

class ScrapeInput(BaseModel):
    """Input schema for the scrape tool."""
    url: str = Field(..., description="The URL to scrape")
    include_links: bool = Field(
        default=False,
        description="Whether to include extracted links",
    )
    only_main_content: bool = Field(
        default=True,
        description="Whether to extract only main content (skip nav, footer)",
    )


class SearchInput(BaseModel):
    """Input schema for the search tool."""
    query: str = Field(..., description="The search query")
    max_results: int = Field(
        default=5,
        description="Maximum number of results to return",
    )


class CrawlInput(BaseModel):
    """Input schema for the crawl tool."""
    url: str = Field(..., description="The starting URL to crawl")
    max_pages: int = Field(
        default=10,
        description="Maximum number of pages to crawl",
    )
    max_depth: int = Field(
        default=2,
        description="Maximum link depth to follow",
    )


class ExtractInput(BaseModel):
    """Input schema for the extract tool."""
    url: str = Field(..., description="The URL to extract data from")
    fields: str = Field(
        ...,
        description=(
            "Comma-separated list of fields to extract. "
            "Example: 'title,price,description'"
        ),
    )


# ══════════════════════════════════════════════════════════════
# Tools
# ══════════════════════════════════════════════════════════════

class AgentCrawlScrapeTool(BaseTool):
    """
    CrewAI tool for scraping a single webpage.

    Converts any webpage into clean, LLM-ready Markdown content.
    Removes navigation, ads, and boilerplate. Extracts metadata
    and optionally includes links.

    Args:
        url: The URL to scrape.
        include_links: Whether to include extracted links.
        only_main_content: Whether to extract only main content.

    Returns:
        Clean Markdown content of the page.
    """

    name: str = "agentcrawl_scrape"
    description: str = (
        "Scrape a webpage and return its content as clean Markdown. "
        "Removes navigation, ads, and boilerplate. "
        "Use this to read the content of a specific URL."
    )
    args_schema: type[BaseModel] = ScrapeInput

    def _run(
        self,
        url: str,
        include_links: bool = False,
        only_main_content: bool = True,
    ) -> str:
        """Execute the scrape tool."""
        return asyncio.run(self._async_run(url, include_links, only_main_content))

    async def _async_run(
        self,
        url: str,
        include_links: bool = False,
        only_main_content: bool = True,
    ) -> str:
        from agentcrawl import CrawlEngine, CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            include_links=include_links,
            include_metadata=True,
            only_main_content=only_main_content,
            cache=True,
            cache_ttl=3600,
            timeout=30,
        )

        try:
            async with CrawlEngine.default() as engine:
                result = await engine.scrape(url, config)

                if not result.success:
                    return f"Error: Failed to scrape {url} — {result.error}"

                # Build response
                parts: list[str] = []

                # Metadata
                title = result.metadata.get("title", "")
                if title:
                    parts.append(f"# {title}\n")

                # Main content
                parts.append(result.markdown)

                # Links (if requested)
                if include_links and result.links:
                    all_links = result.links.get("all", [])
                    if all_links:
                        parts.append("\n\n## Links\n")
                        for link in all_links[:20]:
                            text = link.get("text", link.get("url", ""))
                            href = link.get("url", "")
                            parts.append(f"- [{text}]({href})")

                return "\n".join(parts)

        except Exception as e:
            return f"Error: {e}"


class AgentCrawlSearchTool(BaseTool):
    """
    CrewAI tool for web search.

    Searches the web using DuckDuckGo (no API key required)
    and returns structured results with titles, URLs, and snippets.

    Args:
        query: The search query.
        max_results: Maximum number of results.

    Returns:
        Formatted search results.
    """

    name: str = "agentcrawl_search"
    description: str = (
        "Search the web and return results with titles, URLs, and snippets. "
        "Use this to find relevant pages before scraping them."
    )
    args_schema: type[BaseModel] = SearchInput

    def _run(self, query: str, max_results: int = 5) -> str:
        """Execute the search tool."""
        return asyncio.run(self._async_run(query, max_results))

    async def _async_run(self, query: str, max_results: int = 5) -> str:
        from agentcrawl import SearchEngine

        try:
            engine = SearchEngine(provider="duckduckgo")
            results = await engine.search(query, max_results=max_results)

            if not results:
                return f"No results found for: {query}"

            parts: list[str] = [f"Search results for: \"{query}\"\n"]

            for i, r in enumerate(results, 1):
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                snippet = r.get("snippet", "")

                parts.append(f"{i}. **{title}**")
                parts.append(f"   URL: {url}")
                if snippet:
                    parts.append(f"   {snippet}")
                parts.append("")

            return "\n".join(parts)

        except Exception as e:
            return f"Error: {e}"


class AgentCrawlCrawlTool(BaseTool):
    """
    CrewAI tool for crawling a website.

    Crawls multiple pages from a starting URL using breadth-first
    search. Returns combined Markdown content from all pages.

    Args:
        url: The starting URL.
        max_pages: Maximum pages to crawl.
        max_depth: Maximum link depth.

    Returns:
        Combined content from all crawled pages.
    """

    name: str = "agentcrawl_crawl"
    description: str = (
        "Crawl a website starting from a URL and return content from "
        "multiple pages. Use this to gather information from an entire "
        "website or documentation section."
    )
    args_schema: type[BaseModel] = CrawlInput

    def _run(
        self,
        url: str,
        max_pages: int = 10,
        max_depth: int = 2,
    ) -> str:
        """Execute the crawl tool."""
        return asyncio.run(self._async_run(url, max_pages, max_depth))

    async def _async_run(
        self,
        url: str,
        max_pages: int = 10,
        max_depth: int = 2,
    ) -> str:
        from agentcrawl import BFSCrawler, CrawlEngine, CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            only_main_content=True,
            cache=True,
            cache_ttl=3600,
        )

        try:
            async with CrawlEngine.default() as engine:
                job = await engine.crawl(
                    url,
                    strategy=BFSCrawler(
                        max_depth=max_depth,
                        max_pages=max_pages,
                    ),
                    config=config,
                )

                if job.total_pages == 0:
                    return f"No pages crawled from {url}"

                parts: list[str] = [
                    f"Crawled {job.successful_pages} pages from {url}\n"
                ]

                for page in job.pages:
                    if page.success and page.markdown:
                        title = page.metadata.get("title", page.url)
                        parts.append(f"\n---\n## {title}\n")
                        parts.append(f"URL: {page.url}\n")
                        # Truncate long pages
                        content = page.markdown
                        if len(content) > 3000:
                            content = content[:3000] + "\n\n[... truncated]"
                        parts.append(content)

                return "\n".join(parts)

        except Exception as e:
            return f"Error: {e}"


class AgentCrawlExtractTool(BaseTool):
    """
    CrewAI tool for structured data extraction.

    Extracts specific fields from a webpage using CSS selectors
    or LLM-powered extraction.

    Args:
        url: The URL to extract from.
        fields: Comma-separated field names to extract.

    Returns:
        Extracted data as JSON.
    """

    name: str = "agentcrawl_extract"
    description: str = (
        "Extract structured data from a webpage. Specify the fields "
        "you want to extract (e.g., 'title,price,description'). "
        "Returns the extracted data as JSON."
    )
    args_schema: type[BaseModel] = ExtractInput

    def _run(self, url: str, fields: str) -> str:
        """Execute the extract tool."""
        return asyncio.run(self._async_run(url, fields))

    async def _async_run(self, url: str, fields: str) -> str:
        from agentcrawl import CrawlEngine, CrawlerConfig

        try:
            # Parse field names
            field_names = [f.strip() for f in fields.split(",") if f.strip()]

            if not field_names:
                return "Error: No fields specified"

            # Build a dynamic Pydantic model
            from pydantic import create_model

            field_definitions: dict[str, Any] = dict.fromkeys(field_names, (str, ""))
            dynamic_model = create_model("ExtractedData", **field_definitions)

            # Scrape and extract
            config = CrawlerConfig(
                output_format="markdown",
                only_main_content=True,
            )

            async with CrawlEngine.default() as engine:
                result = await engine.extract(
                    url,
                    schema=dynamic_model,
                    method="llm",
                    config=config,
                )

                if not result.success:
                    return f"Error: Failed to extract from {url} — {result.error}"

                if result.extracted_data:
                    if hasattr(result.extracted_data, "model_dump"):
                        data = result.extracted_data.model_dump()
                    elif isinstance(result.extracted_data, dict):
                        data = result.extracted_data
                    else:
                        data = {"data": str(result.extracted_data)}

                    return json.dumps(data, indent=2, ensure_ascii=False)

                return "No data extracted"

        except Exception as e:
            return f"Error: {e}"


# ══════════════════════════════════════════════════════════════
# Convenience: All Tools
# ══════════════════════════════════════════════════════════════

def get_all_tools() -> list[BaseTool]:
    """
    Get all AgentCrawl CrewAI tools.

    Returns:
        List of tool instances.

    Example:
        >>> tools = get_all_tools()
        >>> agent = Agent(role="Researcher", tools=tools)
    """
    return [
        AgentCrawlScrapeTool(),
        AgentCrawlSearchTool(),
        AgentCrawlCrawlTool(),
        AgentCrawlExtractTool(),
    ]


# ══════════════════════════════════════════════════════════════
# Example: Full Crew
# ══════════════════════════════════════════════════════════════

def create_research_crew(topic: str) -> Any:
    """
    Create a CrewAI crew for web research using AgentCrawl tools.

    Args:
        topic: Research topic.

    Returns:
        Crew instance.

    Example:
        >>> crew = create_research_crew("Python 3.13 new features")
        >>> result = crew.kickoff()
        >>> print(result)
    """
    from crewai import Agent, Crew, Process, Task

    # Tools
    scrape_tool = AgentCrawlScrapeTool()
    search_tool = AgentCrawlSearchTool()
    crawl_tool = AgentCrawlCrawlTool()

    # Agents
    researcher = Agent(
        role="Web Researcher",
        goal=f"Find comprehensive information about: {topic}",
        backstory=(
            "You are an expert web researcher. You use search to find "
            "relevant pages, then scrape them to extract detailed content. "
            "You always verify information from multiple sources."
        ),
        tools=[search_tool, scrape_tool],
        verbose=True,
    )

    analyst = Agent(
        role="Content Analyst",
        goal=f"Analyze and summarize findings about: {topic}",
        backstory=(
            "You are a skilled analyst who synthesizes information from "
            "multiple sources into clear, actionable summaries. You identify "
            "key insights and present them in a structured format."
        ),
        tools=[scrape_tool, crawl_tool],
        verbose=True,
    )

    # Tasks
    research_task = Task(
        description=(
            f"Search the web for information about: {topic}\n"
            f"Find at least 3-5 relevant sources.\n"
            f"Scrape the most relevant pages for detailed content.\n"
            f"Compile your findings with source URLs."
        ),
        expected_output=(
            "A detailed research report with findings from multiple "
            "sources, including URLs and key quotes."
        ),
        agent=researcher,
    )

    analysis_task = Task(
        description=(
            f"Analyze the research findings about: {topic}\n"
            f"Identify the most important insights.\n"
            f"Create a structured summary with key takeaways.\n"
            f"Include recommendations if applicable."
        ),
        expected_output=(
            "A structured analysis with key insights, summary, "
            "and actionable recommendations."
        ),
        agent=analyst,
        context=[research_task],
    )

    # Crew
    crew = Crew(
        agents=[researcher, analyst],
        tasks=[research_task, analysis_task],
        process=Process.sequential,
        verbose=True,
    )

    return crew


# ══════════════════════════════════════════════════════════════
# Main (Example Usage)
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("AgentCrawl x CrewAI Integration Example")
    print("=" * 50)

    # Example 1: Use tools directly
    print("\n[1] Testing scrape tool...")
    scrape_tool = AgentCrawlScrapeTool()
    result = scrape_tool._run(url="https://example.com")
    print(result[:500])

    print("\n[2] Testing search tool...")
    search_tool = AgentCrawlSearchTool()
    result = search_tool._run(query="python asyncio tutorial", max_results=3)
    print(result[:500])

    # Example 2: Create a research crew
    if "--crew" in sys.argv:
        topic = " ".join(sys.argv[sys.argv.index("--crew") + 1:]) or "Python 3.13"
        print(f"\n[3] Creating research crew for: {topic}")
        crew = create_research_crew(topic)
        result = crew.kickoff()
        print(f"\nResult:\n{result}")
