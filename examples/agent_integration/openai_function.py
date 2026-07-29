"""
AgentCrawl × OpenAI Function Calling Integration
====================================================

OpenAI function calling (tools) powered by AgentCrawl for web
scraping, searching, and structured extraction within GPT agents.

Prerequisites:
    pip install agentcrawl openai

Features:
    - OpenAI tools/function definitions
    - Agent loop with automatic tool execution
    - Parallel function calls
    - Structured outputs with Pydantic
    - Assistant API integration
    - Streaming support

Usage:
    from examples.agent_integration.openai_function import (
        AgentCrawlTools,
        run_agent,
    )

    # Create tools
    tools = AgentCrawlTools()

    # Run an agent with tool calling
    response = await run_agent(
        messages=[{"role": "user", "content": "Research Python 3.13 features"}],
        tools=tools,
    )
    print(response)

    # Use with OpenAI client directly
    import openai
    client = openai.AsyncOpenAI()

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Scrape https://example.com"}],
        tools=tools.openai_tools(),
    )
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    import openai
except ImportError:
    raise ImportError(
        "openai is required. Install with: pip install openai"
    )


# ══════════════════════════════════════════════════════════════
# Tool Definitions
# ══════════════════════════════════════════════════════════════

SCRAPE_FUNCTION: dict[str, Any] = {
    "name": "scrape_webpage",
    "description": (
        "Scrape a webpage and return its content as clean Markdown. "
        "Removes navigation, ads, and boilerplate. "
        "Use this to read the content of a specific URL."
    ),
    "parameters": {
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
        },
        "required": ["url"],
    },
}

SEARCH_FUNCTION: dict[str, Any] = {
    "name": "search_web",
    "description": (
        "Search the web and return results with titles, URLs, and snippets. "
        "Use this to find relevant pages before scraping them."
    ),
    "parameters": {
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
}

CRAWL_FUNCTION: dict[str, Any] = {
    "name": "crawl_website",
    "description": (
        "Crawl a website starting from a URL and return content from "
        "multiple pages. Use this to gather information from documentation "
        "sites or multi-page resources."
    ),
    "parameters": {
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
        },
        "required": ["url"],
    },
}

EXTRACT_FUNCTION: dict[str, Any] = {
    "name": "extract_data",
    "description": (
        "Extract structured data from a webpage. Specify the fields "
        "to extract as a JSON schema. Returns structured JSON data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to extract data from",
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
}


# ══════════════════════════════════════════════════════════════
# Tool Executor
# ══════════════════════════════════════════════════════════════

class AgentCrawlTools:
    """
    Manages AgentCrawl tools for OpenAI function calling.

    Provides tool definitions and execution handlers for use
    with the OpenAI Chat Completions API.

    Example:
        >>> tools = AgentCrawlTools()
        >>>
        >>> # Get OpenAI tool definitions
        >>> openai_tools = tools.openai_tools()
        >>>
        >>> # Execute a tool call
        >>> result = await tools.execute("scrape_webpage", {"url": "https://example.com"})
    """

    def __init__(self, include_crawl: bool = True, include_extract: bool = True):
        self._include_crawl = include_crawl
        self._include_extract = include_extract

    def openai_tools(self) -> list[dict[str, Any]]:
        """
        Get OpenAI-compatible tool definitions.

        Returns:
            List of tool definitions for the OpenAI API.
        """
        tools = [
            {"type": "function", "function": SCRAPE_FUNCTION},
            {"type": "function", "function": SEARCH_FUNCTION},
        ]

        if self._include_crawl:
            tools.append({"type": "function", "function": CRAWL_FUNCTION})

        if self._include_extract:
            tools.append({"type": "function", "function": EXTRACT_FUNCTION})

        return tools

    async def execute(
        self,
        function_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """
        Execute a tool function.

        Args:
            function_name: Name of the function to execute.
            arguments: Function arguments.

        Returns:
            Result string.
        """
        handlers = {
            "scrape_webpage": self._scrape,
            "search_web": self._search,
            "crawl_website": self._crawl,
            "extract_data": self._extract,
        }

        handler = handlers.get(function_name)
        if handler is None:
            return json.dumps({"error": f"Unknown function: {function_name}"})

        try:
            result = await handler(**arguments)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _scrape(
        self,
        url: str,
        include_links: bool = False,
    ) -> str:
        """Scrape a webpage."""
        from agentcrawl import CrawlEngine, CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            include_links=include_links,
            include_metadata=True,
            only_main_content=True,
            cache=True,
            cache_ttl=3600,
        )

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

    async def _search(
        self,
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search the web."""
        from agentcrawl import SearchEngine

        engine = SearchEngine(provider="duckduckgo")
        results = await engine.search(query, max_results=max_results)

        return json.dumps(
            {"query": query, "results": results},
            ensure_ascii=False,
        )

    async def _crawl(
        self,
        url: str,
        max_pages: int = 10,
    ) -> str:
        """Crawl a website."""
        from agentcrawl import BFSCrawler, CrawlEngine, CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            only_main_content=True,
            cache=True,
        )

        async with CrawlEngine.default() as engine:
            job = await engine.crawl(
                url,
                strategy=BFSCrawler(max_depth=2, max_pages=max_pages),
                config=config,
            )

            pages = []
            for page in job.pages:
                if page.success:
                    pages.append({
                        "url": page.url,
                        "title": page.metadata.get("title", ""),
                        "content": page.markdown[:2000],
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

    async def _extract(
        self,
        url: str,
        fields: str,
    ) -> str:
        """Extract structured data."""
        from agentcrawl import CrawlEngine

        field_names = [f.strip() for f in fields.split(",") if f.strip()]

        # Build dynamic schema
        from pydantic import create_model

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


# ══════════════════════════════════════════════════════════════
# Agent Loop
# ══════════════════════════════════════════════════════════════

async def run_agent(
    messages: list[dict[str, str]],
    tools: AgentCrawlTools | None = None,
    model: str = "gpt-4o",
    max_iterations: int = 10,
    temperature: float = 0.0,
    verbose: bool = True,
) -> str:
    """
    Run an agent loop with OpenAI function calling.

    Automatically executes tool calls and feeds results back
    until the model produces a final response.

    Args:
        messages: Initial messages.
        tools: AgentCrawlTools instance.
        model: OpenAI model name.
        max_iterations: Maximum tool call iterations.
        temperature: Sampling temperature.
        verbose: Print tool call info.

    Returns:
        Final assistant response text.

    Example:
        >>> response = await run_agent(
        ...     messages=[{"role": "user", "content": "What's on example.com?"}],
        ... )
        >>> print(response)
    """
    if tools is None:
        tools = AgentCrawlTools()

    client = openai.AsyncOpenAI()
    openai_tools = tools.openai_tools()

    # Working copy of messages
    working_messages = list(messages)

    for iteration in range(max_iterations):
        if verbose:
            print(f"\n[Iteration {iteration + 1}]")

        # Call OpenAI
        response = await client.chat.completions.create(
            model=model,
            messages=working_messages,
            tools=openai_tools,
            temperature=temperature,
        )

        message = response.choices[0].message

        # Check if model wants to call tools
        if message.tool_calls:
            # Add assistant message with tool calls
            working_messages.append(message.model_dump())

            # Execute tool calls (potentially in parallel)
            if verbose:
                print(f"  Tool calls: {len(message.tool_calls)}")

            # Execute all tool calls
            tasks = []
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                if verbose:
                    print(f"  → {fn_name}({json.dumps(fn_args)[:100]})")

                tasks.append(tools.execute(fn_name, fn_args))

            # Run in parallel
            results = await asyncio.gather(*tasks)

            # Add tool results to messages
            for tool_call, result in zip(message.tool_calls, results):
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

                if verbose:
                    print(f"  ← {result[:150]}...")

        else:
            # No tool calls — final response
            final_content = message.content or ""
            if verbose:
                print("\n[Final Response]")

            return final_content

    return "Max iterations reached without final response."


# ══════════════════════════════════════════════════════════════
# Structured Output
# ══════════════════════════════════════════════════════════════

async def scrape_structured(
    url: str,
    schema: dict[str, Any],
    model: str = "gpt-4o",
) -> dict[str, Any]:
    """
    Scrape a URL and extract data matching a JSON schema.

    Uses OpenAI's structured outputs for guaranteed schema compliance.

    Args:
        url: URL to scrape.
        schema: JSON Schema for the output.
        model: OpenAI model.

    Returns:
        Extracted data matching the schema.

    Example:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {
        ...         "title": {"type": "string"},
        ...         "summary": {"type": "string"},
        ...         "key_points": {"type": "array", "items": {"type": "string"}},
        ...     },
        ...     "required": ["title", "summary"],
        ... }
        >>> data = await scrape_structured("https://example.com", schema)
    """
    from agentcrawl import CrawlEngine, CrawlerConfig

    # Step 1: Scrape
    config = CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
    )

    async with CrawlEngine.default() as engine:
        result = await engine.scrape(url, config)

    if not result.success:
        raise ValueError(f"Failed to scrape {url}: {result.error}")

    # Step 2: Extract with structured output
    client = openai.AsyncOpenAI()

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract structured data from the web page content. "
                    "Return ONLY valid JSON matching the schema."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Schema\n```json\n{json.dumps(schema)}\n```\n\n"
                    f"## Content\n{result.markdown[:8000]}"
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "extracted_data",
                "strict": True,
                "schema": schema,
            },
        },
        temperature=0.0,
    )

    content = response.choices[0].message.content
    return json.loads(content)


# ══════════════════════════════════════════════════════════════
# Assistant API Integration
# ══════════════════════════════════════════════════════════════

async def create_assistant_with_tools(
    name: str = "Web Research Agent",
    instructions: str | None = None,
    model: str = "gpt-4o",
) -> Any:
    """
    Create an OpenAI Assistant with AgentCrawl tools.

    Note: This uses the Assistants API with function tools.
    Tool execution must be handled by your application.

    Args:
        name: Assistant name.
        instructions: System instructions.
        model: Model name.

    Returns:
        OpenAI Assistant object.

    Example:
        >>> assistant = await create_assistant_with_tools()
        >>> thread = await client.beta.threads.create()
        >>> # ... add messages and run ...
    """
    if instructions is None:
        instructions = (
            "You are a web research assistant. Use the available tools "
            "to search the web, scrape pages, and extract information. "
            "Always cite your sources with URLs."
        )

    tools = AgentCrawlTools()

    client = openai.AsyncOpenAI()

    assistant = await client.beta.assistants.create(
        name=name,
        instructions=instructions,
        model=model,
        tools=tools.openai_tools(),
    )

    return assistant


async def run_assistant_thread(
    assistant_id: str,
    user_message: str,
    tools: AgentCrawlTools | None = None,
    max_iterations: int = 10,
) -> str:
    """
    Run a conversation thread with an Assistant.

    Handles the tool call loop automatically.

    Args:
        assistant_id: Assistant ID.
        user_message: User message.
        tools: AgentCrawlTools instance.
        max_iterations: Maximum iterations.

    Returns:
        Final assistant response.
    """
    if tools is None:
        tools = AgentCrawlTools()

    client = openai.AsyncOpenAI()

    # Create thread
    thread = await client.beta.threads.create()

    # Add user message
    await client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=user_message,
    )

    # Run assistant
    run = await client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id,
    )

    # Tool call loop
    for _ in range(max_iterations):
        # Wait for run to complete
        while run.status in ("queued", "in_progress"):
            await asyncio.sleep(1)
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )

        if run.status == "requires_action":
            # Execute tool calls
            tool_outputs = []
            for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                result = await tools.execute(fn_name, fn_args)

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": result,
                })

            # Submit tool outputs
            run = await client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread.id,
                run_id=run.id,
                tool_outputs=tool_outputs,
            )

        elif run.status == "completed":
            # Get final messages
            messages = await client.beta.threads.messages.list(
                thread_id=thread.id,
            )

            for msg in messages.data:
                if msg.role == "assistant":
                    return msg.content[0].text.value

            return ""

        else:
            return f"Run ended with status: {run.status}"

    return "Max iterations reached"


# ══════════════════════════════════════════════════════════════
# Examples
# ══════════════════════════════════════════════════════════════

async def example_basic_agent() -> None:
    """Example: Basic agent with tool calling."""
    print("AgentCrawl × OpenAI Function Calling — Basic Agent")
    print("=" * 55)

    response = await run_agent(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful research assistant. Use the web tools "
                    "to find information and answer questions. Always provide "
                    "source URLs."
                ),
            },
            {
                "role": "user",
                "content": "What are the main features of Python's asyncio? "
                           "Search for it and check the official docs.",
            },
        ],
        verbose=True,
    )

    print(f"\n{'=' * 55}")
    print(f"Response:\n{response}")


async def example_structured_extraction() -> None:
    """Example: Structured data extraction."""
    print("\nAgentCrawl × OpenAI — Structured Extraction")
    print("=" * 55)

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "links_count": {"type": "integer"},
        },
        "required": ["title", "description"],
        "additionalProperties": False,
    }

    data = await scrape_structured("https://example.com", schema)
    print(f"Extracted: {json.dumps(data, indent=2)}")


async def example_parallel_tools() -> None:
    """Example: Parallel tool execution."""
    print("\nAgentCrawl × OpenAI — Parallel Tool Calls")
    print("=" * 55)

    tools = AgentCrawlTools()

    # Simulate parallel tool calls
    tasks = [
        tools.execute("scrape_webpage", {"url": "https://example.com"}),
        tools.execute("search_web", {"query": "python tutorial", "max_results": 3}),
    ]

    results = await asyncio.gather(*tasks)

    for i, result in enumerate(results):
        print(f"\nTool {i + 1} result: {result[:200]}...")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if "--structured" in sys.argv:
        asyncio.run(example_structured_extraction())
    elif "--parallel" in sys.argv:
        asyncio.run(example_parallel_tools())
    else:
        asyncio.run(example_basic_agent())
