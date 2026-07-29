"""
AgentCrawl × LangChain Integration
======================================

LangChain tools, document loaders, and RAG components powered
by AgentCrawl for web scraping and content extraction.

Prerequisites:
    pip install agentcrawl langchain langchain-community langchain-openai

Components:
    - AgentCrawlLoader      — LangChain DocumentLoader
    - AgentCrawlScrapeTool  — LangChain Tool for scraping
    - AgentCrawlSearchTool  — LangChain Tool for web search
    - AgentCrawlCrawlTool   — LangChain Tool for crawling
    - RAG pipeline example
    - Agent executor example

Usage:
    # Document Loader
    from examples.agent_integration.langchain_tool import AgentCrawlLoader

    loader = AgentCrawlLoader(
        urls=["https://docs.example.com/guide"],
        chunk=True,
        chunk_size=1000,
    )
    docs = loader.load()

    # Tools
    from examples.agent_integration.langchain_tool import (
        AgentCrawlScrapeTool,
        AgentCrawlSearchTool,
        get_all_tools,
    )

    tools = get_all_tools()

    # RAG Pipeline
    from examples.agent_integration.langchain_tool import build_rag_chain

    chain = build_rag_chain(urls=["https://docs.example.com"])
    answer = chain.invoke("How do I get started?")
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

try:
    from langchain_core.documents import Document
    from langchain_core.tools import BaseTool
except ImportError:
    raise ImportError(
        "langchain-core is required. "
        "Install with: pip install langchain-core"
    )

from pydantic import BaseModel, Field

# ══════════════════════════════════════════════════════════════
# Document Loader
# ══════════════════════════════════════════════════════════════

class AgentCrawlLoader:
    """
    LangChain DocumentLoader powered by AgentCrawl.

    Loads web pages as LangChain Documents with optional chunking,
    content filtering, and metadata extraction.

    Args:
        urls: Single URL or list of URLs to load.
        chunk: Whether to chunk the content.
        chunk_size: Maximum chunk size in tokens.
        chunk_overlap: Overlap between chunks in tokens.
        content_filter: Content filter type ('none', 'pruning', 'bm25').
        filter_query: Query for BM25 filter.
        include_metadata: Whether to include page metadata.
        only_main_content: Whether to extract only main content.
        max_concurrent: Maximum concurrent scrapes.

    Example:
        >>> loader = AgentCrawlLoader(
        ...     urls=["https://docs.example.com/guide"],
        ...     chunk=True,
        ...     chunk_size=1000,
        ... )
        >>> docs = loader.load()
        >>> print(f"Loaded {len(docs)} documents")
        >>> print(docs[0].page_content[:200])
    """

    def __init__(
        self,
        urls: str | list[str],
        chunk: bool = True,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        content_filter: str = "pruning",
        filter_query: str = "",
        include_metadata: bool = True,
        only_main_content: bool = True,
        max_concurrent: int = 5,
    ):
        if isinstance(urls, str):
            urls = [urls]

        self._urls = urls
        self._chunk = chunk
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._content_filter = content_filter
        self._filter_query = filter_query
        self._include_metadata = include_metadata
        self._only_main_content = only_main_content
        self._max_concurrent = max_concurrent

    def load(self) -> list[Document]:
        """
        Load documents synchronously.

        Returns:
            List of LangChain Document objects.
        """
        return asyncio.run(self._async_load())

    def lazy_load(self) -> Iterator[Document]:
        """
        Load documents lazily (one at a time).

        Yields:
            LangChain Document objects.
        """
        docs = self.load()
        yield from docs

    async def _async_load(self) -> list[Document]:
        """Async implementation of document loading."""
        from agentcrawl import CrawlEngine, CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            include_metadata=self._include_metadata,
            only_main_content=self._only_main_content,
            content_filter=self._content_filter,
            content_filter_query=self._filter_query,
            chunker="topic" if self._chunk else "none",
            chunk_max_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
            cache=True,
            cache_ttl=3600,
        )

        documents: list[Document] = []

        async with CrawlEngine.default() as engine:
            results = await engine.batch_scrape(
                self._urls,
                config=config,
                max_concurrent=self._max_concurrent,
            )

            for result in results:
                if not result.success:
                    continue

                # Build metadata
                metadata: dict[str, Any] = {
                    "source": result.url,
                }

                if self._include_metadata and result.metadata:
                    metadata["title"] = result.metadata.get("title", "")
                    metadata["description"] = result.metadata.get("description", "")

                # Add chunks as documents
                if self._chunk and result.chunks:
                    for chunk in result.chunks:
                        chunk_metadata = {
                            **metadata,
                            "chunk_index": chunk.get("index", 0),
                            "heading": chunk.get("heading", ""),
                            "token_count": chunk.get("token_count", 0),
                        }
                        documents.append(Document(
                            page_content=chunk.get("text", ""),
                            metadata=chunk_metadata,
                        ))
                else:
                    # Single document per page
                    metadata["word_count"] = result.word_count
                    metadata["token_count"] = result.token_count
                    documents.append(Document(
                        page_content=result.markdown,
                        metadata=metadata,
                    ))

        return documents

    def load_and_split(
        self,
        text_splitter: Any = None,
    ) -> list[Document]:
        """
        Load and split documents using a LangChain text splitter.

        Args:
            text_splitter: LangChain TextSplitter instance.

        Returns:
            List of split Document objects.
        """
        docs = self.load()

        if text_splitter is None:
            return docs

        return text_splitter.split_documents(docs)


# ══════════════════════════════════════════════════════════════
# Tool Input Schemas
# ══════════════════════════════════════════════════════════════

class ScrapeInput(BaseModel):
    """Input for the scrape tool."""
    url: str = Field(description="The URL to scrape")


class SearchInput(BaseModel):
    """Input for the search tool."""
    query: str = Field(description="The search query")
    max_results: int = Field(default=5, description="Maximum results")


class CrawlInput(BaseModel):
    """Input for the crawl tool."""
    url: str = Field(description="The starting URL")
    max_pages: int = Field(default=10, description="Maximum pages")


# ══════════════════════════════════════════════════════════════
# LangChain Tools
# ══════════════════════════════════════════════════════════════

class AgentCrawlScrapeTool(BaseTool):
    """
    LangChain tool for scraping a webpage.

    Converts any URL into clean Markdown content suitable for
    LLM consumption.
    """

    name: str = "agentcrawl_scrape"
    description: str = (
        "Scrape a webpage and return its content as clean Markdown. "
        "Input should be a URL string. Removes navigation, ads, "
        "and boilerplate content."
    )
    args_schema: type[BaseModel] = ScrapeInput

    def _run(self, url: str) -> str:
        """Synchronous execution."""
        return asyncio.run(self._arun(url))

    async def _arun(self, url: str) -> str:
        """Async execution."""
        from agentcrawl import CrawlEngine, CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            include_metadata=True,
            only_main_content=True,
            cache=True,
            cache_ttl=3600,
        )

        try:
            async with CrawlEngine.default() as engine:
                result = await engine.scrape(url, config)

                if not result.success:
                    return f"Error: {result.error}"

                title = result.metadata.get("title", "")
                content = result.markdown

                if title:
                    return f"# {title}\n\n{content}"
                return content

        except Exception as e:
            return f"Error scraping {url}: {e}"


class AgentCrawlSearchTool(BaseTool):
    """
    LangChain tool for web search.

    Searches the web and returns results with titles, URLs,
    and snippets.
    """

    name: str = "agentcrawl_search"
    description: str = (
        "Search the web for information. Input should be a search "
        "query string. Returns titles, URLs, and snippets."
    )
    args_schema: type[BaseModel] = SearchInput

    def _run(self, query: str, max_results: int = 5) -> str:
        """Synchronous execution."""
        return asyncio.run(self._arun(query, max_results))

    async def _arun(self, query: str, max_results: int = 5) -> str:
        """Async execution."""
        from agentcrawl import SearchEngine

        try:
            engine = SearchEngine(provider="duckduckgo")
            results = await engine.search(query, max_results=max_results)

            if not results:
                return f"No results found for: {query}"

            lines: list[str] = []
            for i, r in enumerate(results, 1):
                lines.append(
                    f"{i}. {r.get('title', 'Untitled')}\n"
                    f"   URL: {r.get('url', '')}\n"
                    f"   {r.get('snippet', '')}"
                )

            return "\n\n".join(lines)

        except Exception as e:
            return f"Error searching: {e}"


class AgentCrawlCrawlTool(BaseTool):
    """
    LangChain tool for crawling a website.

    Crawls multiple pages from a starting URL and returns
    combined content.
    """

    name: str = "agentcrawl_crawl"
    description: str = (
        "Crawl a website starting from a URL. Input should be a URL. "
        "Returns content from multiple pages. Use for gathering "
        "information from documentation sites."
    )
    args_schema: type[BaseModel] = CrawlInput

    def _run(self, url: str, max_pages: int = 10) -> str:
        """Synchronous execution."""
        return asyncio.run(self._arun(url, max_pages))

    async def _arun(self, url: str, max_pages: int = 10) -> str:
        """Async execution."""
        from agentcrawl import BFSCrawler, CrawlEngine, CrawlerConfig

        config = CrawlerConfig(
            output_format="markdown",
            only_main_content=True,
            cache=True,
        )

        try:
            async with CrawlEngine.default() as engine:
                job = await engine.crawl(
                    url,
                    strategy=BFSCrawler(max_depth=2, max_pages=max_pages),
                    config=config,
                )

                if job.total_pages == 0:
                    return f"No pages crawled from {url}"

                parts: list[str] = [
                    f"Crawled {job.successful_pages} pages from {url}\n"
                ]

                for page in job.pages[:max_pages]:
                    if page.success and page.markdown:
                        title = page.metadata.get("title", page.url)
                        content = page.markdown[:2000]
                        parts.append(f"\n## {title}\nURL: {page.url}\n\n{content}")

                return "\n".join(parts)

        except Exception as e:
            return f"Error crawling {url}: {e}"


# ══════════════════════════════════════════════════════════════
# Convenience Functions
# ══════════════════════════════════════════════════════════════

def get_all_tools() -> list[BaseTool]:
    """
    Get all AgentCrawl LangChain tools.

    Returns:
        List of tool instances.

    Example:
        >>> tools = get_all_tools()
        >>> agent = create_react_agent(llm, tools, prompt)
    """
    return [
        AgentCrawlScrapeTool(),
        AgentCrawlSearchTool(),
        AgentCrawlCrawlTool(),
    ]


# ══════════════════════════════════════════════════════════════
# RAG Pipeline
# ══════════════════════════════════════════════════════════════

def build_rag_chain(
    urls: str | list[str],
    llm: Any = None,
    embedding_model: Any = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> Any:
    """
    Build a RAG chain using AgentCrawl for document loading.

    Args:
        urls: URLs to load as knowledge base.
        llm: LangChain LLM instance (default: ChatOpenAI).
        embedding_model: Embedding model (default: OpenAIEmbeddings).
        chunk_size: Chunk size in tokens.
        chunk_overlap: Chunk overlap in tokens.

    Returns:
        LangChain chain that answers questions from the loaded docs.

    Example:
        >>> chain = build_rag_chain(
        ...     urls=["https://docs.example.com/guide"],
        ... )
        >>> answer = chain.invoke("How do I get started?")
        >>> print(answer)
    """
    try:
        from langchain.chains import RetrievalQA
        from langchain_community.vectorstores import FAISS
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    except ImportError:
        raise ImportError(
            "langchain, langchain-community, langchain-openai, and faiss "
            "are required. Install with: "
            "pip install langchain langchain-community langchain-openai faiss-cpu"
        )

    # Default LLM and embeddings
    if llm is None:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    if embedding_model is None:
        embedding_model = OpenAIEmbeddings()

    # Load documents
    loader = AgentCrawlLoader(
        urls=urls,
        chunk=True,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        content_filter="pruning",
    )

    docs = loader.load()

    if not docs:
        raise ValueError("No documents loaded from the provided URLs")

    # Create vector store
    vectorstore = FAISS.from_documents(docs, embedding_model)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

    # Build chain
    chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
    )

    return chain


# ══════════════════════════════════════════════════════════════
# Agent Executor
# ══════════════════════════════════════════════════════════════

def create_web_agent(
    llm: Any = None,
    verbose: bool = True,
) -> Any:
    """
    Create a LangChain agent with AgentCrawl web tools.

    Args:
        llm: LangChain LLM instance.
        verbose: Whether to print agent steps.

    Returns:
        AgentExecutor instance.

    Example:
        >>> agent = create_web_agent()
        >>> result = agent.invoke({
        ...     "input": "Research the latest Python 3.13 features"
        ... })
        >>> print(result["output"])
    """
    try:
        from langchain.agents import AgentExecutor, create_react_agent
        from langchain_core.prompts import PromptTemplate
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "langchain and langchain-openai are required. "
            "Install with: pip install langchain langchain-openai"
        )

    if llm is None:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    tools = get_all_tools()

    # ReAct prompt
    prompt = PromptTemplate.from_template(
        """Answer the following questions using the available tools.

You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought: {agent_scratchpad}"""
    )

    agent = create_react_agent(llm, tools, prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=verbose,
        handle_parsing_errors=True,
        max_iterations=10,
    )


# ══════════════════════════════════════════════════════════════
# Example: Full RAG Pipeline
# ══════════════════════════════════════════════════════════════

def example_rag_pipeline() -> None:
    """
    Example: Build a RAG pipeline with AgentCrawl.

    Loads documentation, chunks it, embeds it, and answers questions.
    """
    print("AgentCrawl × LangChain RAG Pipeline Example")
    print("=" * 50)

    # Step 1: Load documents
    print("\n[1] Loading documents...")
    loader = AgentCrawlLoader(
        urls=["https://docs.python.org/3/tutorial/controlflow.html"],
        chunk=True,
        chunk_size=1000,
        chunk_overlap=200,
        content_filter="pruning",
    )
    docs = loader.load()
    print(f"    Loaded {len(docs)} chunks")

    if docs:
        print(f"    First chunk: {docs[0].page_content[:100]}...")
        print(f"    Metadata: {docs[0].metadata}")

    # Step 2: Build RAG chain (requires OpenAI API key)
    print("\n[2] Building RAG chain...")
    try:
        chain = build_rag_chain(
            urls=["https://docs.python.org/3/tutorial/controlflow.html"],
            chunk_size=1000,
        )

        # Step 3: Ask questions
        print("\n[3] Asking questions...")
        questions = [
            "What are Python's control flow statements?",
            "How do for loops work in Python?",
            "What is the difference between break and continue?",
        ]

        for q in questions:
            print(f"\n    Q: {q}")
            result = chain.invoke({"query": q})
            answer = result.get("result", "")
            print(f"    A: {answer[:200]}...")

    except Exception as e:
        print(f"    Skipped (requires OpenAI API key): {e}")


# ══════════════════════════════════════════════════════════════
# Example: Agent with Tools
# ══════════════════════════════════════════════════════════════

def example_agent() -> None:
    """
    Example: Create a web research agent with AgentCrawl tools.
    """
    print("\nAgentCrawl × LangChain Agent Example")
    print("=" * 50)

    try:
        agent = create_web_agent(verbose=True)

        result = agent.invoke({
            "input": "What are the main features of Python's asyncio library? "
                     "Search for it and scrape the official documentation."
        })

        print(f"\nFinal Answer:\n{result['output']}")

    except Exception as e:
        print(f"Skipped (requires OpenAI API key): {e}")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if "--rag" in sys.argv:
        example_rag_pipeline()
    elif "--agent" in sys.argv:
        example_agent()
    else:
        # Default: test the document loader
        print("AgentCrawl × LangChain Document Loader Test")
        print("=" * 50)

        loader = AgentCrawlLoader(
            urls=["https://example.com"],
            chunk=False,
        )
        docs = loader.load()

        for doc in docs:
            print(f"\nSource: {doc.metadata.get('source', 'unknown')}")
            print(f"Content: {doc.page_content[:300]}...")
            print(f"Metadata: {doc.metadata}")
