# Package Mode Guide

Use AgentCrawl as a Python library in your applications, AI agents, and RAG pipelines.

---

## Table of Contents

- [Installation](#installation)
- [Basic Usage](#basic-usage)
- [Scraping](#scraping)
- [Crawling](#crawling)
- [Structured Extraction](#structured-extraction)
- [Web Search](#web-search)
- [URL Discovery](#url-discovery)
- [Content Processing](#content-processing)
- [Session Management](#session-management)
- [Batch Operations](#batch-operations)
- [Configuration](#configuration)
- [Error Handling](#error-handling)
- [Integration Patterns](#integration-patterns)
- [Performance Tips](#performance-tips)

---

## Installation

```bash
# Core installation
pip install agentcrawl

# With LLM extraction
pip install "agentcrawl[llm]"

# With Redis cache/queue
pip install "agentcrawl[redis]"

# Full installation
pip install "agentcrawl[all]"

# Install Playwright browsers (required)
playwright install chromium
```

### Verify Installation

```python
import agentcrawl
print(agentcrawl.__version__)  # 1.0.0

# Quick test
import asyncio

async def test():
    result = await agentcrawl.scrape("https://example.com")
    print(result.markdown[:200])

asyncio.run(test())
```

---

## Basic Usage

### Engine Lifecycle

The `CrawlEngine` manages browser, cache, and processing resources. Use it as a context manager for automatic cleanup:

```python
from agentcrawl import CrawlEngine, CrawlerConfig

async with CrawlEngine.default() as engine:
    # Engine is started — browser is running
    result = await engine.scrape("https://example.com")
    print(result.markdown)
# Engine is shut down — browser is closed
```

Or manage the lifecycle manually:

```python
engine = CrawlEngine.default()
await engine.startup()

try:
    result = await engine.scrape("https://example.com")
finally:
    await engine.shutdown()
```

### Convenience Functions

For one-off operations, use the top-level convenience functions:

```python
import agentcrawl

# Scrape a single page
result = await agentcrawl.scrape("https://example.com")

# Crawl a website
job = await agentcrawl.crawl("https://docs.example.com")

# Search the web
results = await agentcrawl.search("python tutorial")

# Discover URLs
urls = await agentcrawl.map_site("https://example.com")
```

> **Note:** Convenience functions create and destroy an engine per call. For repeated operations, use `CrawlEngine` directly.

---

## Scraping

### Basic Scrape

```python
from agentcrawl import CrawlEngine, CrawlerConfig

async with CrawlEngine.default() as engine:
    result = await engine.scrape("https://example.com")

    print(result.success)         # True
    print(result.status_code)     # 200
    print(result.markdown)        # Clean Markdown
    print(result.metadata)        # {title, description, ...}
    print(result.word_count)      # 150
    print(result.token_count)     # ~200
    print(result.response_time_ms) # 1234.5
```

### With Configuration

```python
config = CrawlerConfig(
    output_format="markdown",
    include_links=True,
    include_metadata=True,
    include_screenshot=False,
    only_main_content=True,
    selectors=["article", ".content"],
    exclude_selectors=["nav", "footer", ".sidebar"],
    content_filter="pruning",
    chunker="topic",
    chunk_max_size=1000,
    chunk_overlap=200,
    include_citations=True,
    cache=True,
    cache_ttl=3600,
    timeout=30,
)

result = await engine.scrape("https://example.com", config)
```

### Page Actions

Execute browser actions before content extraction:

```python
config = CrawlerConfig(
    actions=[
        # Click a cookie consent button
        {"type": "click", "selector": "#accept-cookies"},

        # Type into a search box
        {"type": "type", "selector": "#search", "text": "python tutorial"},

        # Press Enter
        {"type": "press", "selector": "#search", "key": "Enter"},

        # Scroll down 3 viewport heights
        {"type": "scroll", "direction": "down", "amount": 3},

        # Wait for content to load
        {"type": "wait", "selector": "#results"},

        # Wait 2 seconds
        {"type": "wait", "milliseconds": 2000},

        # Take a screenshot
        {"type": "screenshot"},
    ],
)

result = await engine.scrape("https://example.com/search", config)
```

### Accessing Result Fields

```python
result = await engine.scrape("https://example.com", config)

# Main content
print(result.markdown)        # Clean Markdown
print(result.html)            # Cleaned HTML
print(result.text)            # Plain text

# Metadata
print(result.metadata["title"])
print(result.metadata["description"])
print(result.metadata.get("og_image"))

# Links
for link in result.links["internal"]:
    print(f"{link['text']}: {link['url']}")

# Chunks (for RAG)
for chunk in result.chunks:
    print(f"[{chunk['heading']}] {chunk['token_count']} tokens")
    print(chunk["text"][:200])

# Citations
for citation in result.citations:
    print(f"[{citation['number']}] {citation['url']}")

# Screenshot (base64)
if result.screenshot:
    import base64
    with open("screenshot.png", "wb") as f:
        f.write(base64.b64decode(result.screenshot))
```

---

## Crawling

### Strategy Selection

```python
from agentcrawl import (
    CrawlEngine,
    BFSCrawler,
    DFSCrawler,
    BestFirstCrawler,
    AdaptiveCrawler,
)

async with CrawlEngine.default() as engine:

    # BFS — good for documentation sites (wide, shallow)
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=BFSCrawler(max_depth=3, max_pages=100),
    )

    # DFS — good for deep hierarchies
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=DFSCrawler(max_depth=5, max_pages=50),
    )

    # BestFirst — good for finding relevant pages quickly
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=BestFirstCrawler(max_pages=50, score_threshold=0.3),
    )

    # Adaptive — good for unknown site structures
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=AdaptiveCrawler(max_pages=100),
    )
```

### Accessing Crawl Results

```python
job = await engine.crawl("https://docs.example.com", strategy=crawler)

print(job.job_id)             # "job_a1b2c3d4"
print(job.total_pages)        # 42
print(job.successful_pages)   # 40
print(job.failed_pages)       # 2
print(job.total_words)        # 15000
print(job.total_tokens)       # ~20000
print(job.duration_ms)        # 45000.0

for page in job.pages:
    print(f"{page.url}: {page.word_count} words")
    print(page.markdown[:200])
```

### URL Filtering

```python
from agentcrawl.crawling import URLFilter

url_filter = URLFilter(
    include_patterns=["/docs/*", "/api/*"],
    exclude_patterns=["/blog/*", "*.pdf"],
    same_domain=True,
    max_depth=5,
)

crawler = BFSCrawler(
    max_depth=3,
    max_pages=100,
    url_filter=url_filter,
)
```

---

## Structured Extraction

### LLM Extraction

```python
from agentcrawl import CrawlEngine, LLMExtractor, LLMConfig
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float
    description: str
    features: list[str]

async with CrawlEngine.default() as engine:
    # Method 1: Via engine.extract()
    result = await engine.extract(
        "https://shop.example.com/product/1",
        schema=Product,
        method="llm",
    )
    product = result.extracted_data
    print(f"{product.name}: ${product.price}")

    # Method 2: Via extractor directly
    extractor = LLMExtractor(
        schema=Product,
        llm_config=LLMConfig(provider="openai/gpt-4o-mini"),
        max_content_tokens=8000,
    )

    # First scrape, then extract
    scrape_result = await engine.scrape("https://shop.example.com/product/1")
    extraction = await extractor.extract(
        html=scrape_result.html,
        markdown=scrape_result.markdown,
    )
    print(extraction.data)  # Product instance
```

### CSS Selector Extraction

```python
from agentcrawl import JsonCssExtractor

schema = {
    "name": "Product Listing",
    "baseSelector": "div.product-card",
    "fields": [
        {"name": "title", "selector": "h2.title", "type": "text"},
        {"name": "price", "selector": "span.price", "type": "text"},
        {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
        {"name": "image", "selector": "img", "type": "attribute", "attribute": "src"},
        {
            "name": "reviews",
            "selector": "div.review",
            "type": "list",
            "fields": [
                {"name": "author", "selector": "span.author", "type": "text"},
                {"name": "rating", "selector": "span.stars", "type": "text"},
                {"name": "text", "selector": "p.review-text", "type": "text"},
            ],
        },
    ],
}

extractor = JsonCssExtractor(schema=schema)
result = await extractor.extract(html=html_content)

for product in result.data:
    print(f"{product['title']}: {product['price']}")
```

### Schema Builder

```python
from agentcrawl import SchemaBuilder

schema = (
    SchemaBuilder("Product", method="css")
    .base_selector("div.product-card")
    .text_field("title", selector="h2.title")
    .text_field("price", selector="span.price")
    .link_field("url", selector="a")
    .image_field("image", selector="img")
    .list_field("reviews", selector="div.review", fields=[
        {"name": "author", "selector": "span.author", "type": "text"},
        {"name": "rating", "selector": "span.stars", "type": "text"},
    ])
    .build()
)
```

### Extraction via CrawlerConfig

```python
from agentcrawl import CrawlerConfig, LLMExtractor

config = CrawlerConfig(
    extraction=LLMExtractor(schema=Product),
)

result = await engine.scrape("https://shop.example.com/product/1", config)
print(result.extracted_data)  # Product instance
```

---

## Web Search

```python
from agentcrawl import SearchEngine

# DuckDuckGo (no API key)
engine = SearchEngine(provider="duckduckgo")
results = await engine.search("python asyncio tutorial", max_results=10)

for r in results:
    print(f"{r['title']}: {r['url']}")
    print(f"  {r['snippet']}")

# Tavily (AI-optimized)
engine = SearchEngine(provider="tavily", api_key="tvly-...")
results = await engine.search("machine learning frameworks")

# Search and scrape
from agentcrawl import CrawlEngine

async with CrawlEngine.default() as crawl_engine:
    search_engine = SearchEngine(provider="duckduckgo")
    results = await search_engine.search_and_scrape(
        "python web scraping",
        max_results=5,
        crawl_engine=crawl_engine,
    )
    for result in results:
        print(f"{result.url}: {result.word_count} words")
```

---

## URL Discovery

```python
from agentcrawl import DomainMapper, SitemapParser

# Discover all URLs (sitemap + robots + link crawl)
mapper = DomainMapper(
    max_urls=500,
    use_sitemap=True,
    use_robots=True,
    use_link_crawl=True,
)
urls = await mapper.discover("https://docs.example.com")
print(f"Found {len(urls)} URLs")

# Parse sitemap directly
parser = SitemapParser(max_urls=10000)
result = await parser.discover_and_parse("https://example.com")
print(f"Found {result.total_urls} URLs in {result.total_sitemaps} sitemaps")

# Analyze URL patterns
patterns = mapper.analyze_patterns(urls)
for p in patterns:
    print(f"{p.template}: {p.count} URLs")
```

---

## Content Processing

### Content Filtering

```python
from agentcrawl.content import PruningContentFilter, BM25ContentFilter

# Remove low-density content (nav, footer, boilerplate)
filter = PruningContentFilter(threshold=0.4)
result = filter.apply(markdown)
print(result.filtered_text)

# Filter by query relevance (for RAG)
filter = BM25ContentFilter(query="machine learning", threshold=1.0)
result = filter.apply(markdown)
```

### Chunking

```python
from agentcrawl.content import TopicChunker, SentenceChunker, create_chunker

# Topic-aware chunking (splits at headings)
chunker = TopicChunker(max_chunk_size=1000, overlap=200)
result = chunker.chunk(markdown, metadata={"url": url, "title": title})

for chunk in result.chunks:
    print(f"Chunk {chunk.index}: [{chunk.heading}] {chunk.token_count} tokens")

# Sentence-based chunking
chunker = SentenceChunker(max_chunk_size=500, overlap=50)

# Factory
chunker = create_chunker("topic", max_chunk_size=1000)
```

### Citations

```python
from agentcrawl.content import CitationExtractor

extractor = CitationExtractor(deduplicate=True)
result = extractor.extract(markdown)

print(result.citation_count)
print(result.format_bibliography("markdown"))
print(result.format_bibliography("apa"))
```

### HTML to Markdown

```python
from agentcrawl.content import html_to_markdown, HTMLParser

# Simple conversion
markdown = html_to_markdown(html_content)

# Advanced parsing
parser = HTMLParser(html_content, base_url="https://example.com")
main_content = parser.get_main_content()
metadata = parser.get_metadata()
links = parser.get_links()
headings = parser.get_headings()
```

---

## Session Management

Maintain state across multiple requests (cookies, authentication):

```python
from agentcrawl import CrawlEngine, CrawlSession

async with CrawlEngine.default() as engine:
    async with CrawlSession(engine, ttl=3600) as session:
        # Login
        await session.goto("https://app.example.com/login")
        await session.execute_actions([
            {"type": "type", "selector": "#email", "text": "user@example.com"},
            {"type": "type", "selector": "#password", "text": "secret"},
            {"type": "click", "selector": "#login-btn"},
            {"type": "wait", "selector": "#dashboard"},
        ])

        # Navigate — cookies are preserved
        result = await session.scrape("https://app.example.com/dashboard")
        print(result.markdown)

        # Another page — still authenticated
        result = await session.scrape("https://app.example.com/settings")

        # Session info
        print(session.page_count)     # 3
        print(session.urls_visited)   # [login, dashboard, settings]
        print(session.session_id)     # "sess_a1b2c3d4e5f6g7h8"
```

---

## Batch Operations

```python
from agentcrawl import CrawlEngine, CrawlerConfig

urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3",
]

async with CrawlEngine.default() as engine:
    results = await engine.batch_scrape(
        urls,
        config=CrawlerConfig(output_format="markdown"),
        max_concurrent=5,
    )

    for result in results:
        if result.success:
            print(f"{result.url}: {result.word_count} words")
        else:
            print(f"{result.url}: FAILED — {result.error}")
```

---

## Configuration

### Global Settings

```python
from agentcrawl import Settings, CrawlEngine

settings = Settings(
    # Browser
    browser_type="chromium",
    headless=True,
    stealth=True,
    user_agent="CustomBot/1.0",
    viewport_width=1920,
    viewport_height=1080,

    # Cache
    cache_backend="redis",
    redis_url="redis://localhost:6379",
    cache_ttl=3600,

    # LLM
    llm_provider="openai/gpt-4o-mini",
    openai_api_key="sk-...",

    # Logging
    log_level="INFO",
)

engine = CrawlEngine.from_settings(settings)
```

### Environment Variables

```bash
# .env
AGENTCRAWL_BROWSER_TYPE=chromium
AGENTCRAWL_HEADLESS=true
AGENTCRAWL_STEALTH=true
AGENTCRAWL_CACHE_BACKEND=memory
AGENTCRAWL_CACHE_TTL=3600
AGENTCRAWL_LOG_LEVEL=INFO
AGENTCRAWL_LLM_PROVIDER=openai/gpt-4o-mini
OPENAI_API_KEY=sk-...
ENCRYPTION_KEY=your-32-byte-key
```

### Per-Request Config

```python
from agentcrawl import CrawlerConfig

config = CrawlerConfig(
    output_format="markdown",
    include_links=True,
    include_metadata=True,
    only_main_content=True,
    content_filter="pruning",
    chunker="topic",
    cache=True,
    timeout=30,
)

result = await engine.scrape(url, config)
```

---

## Error Handling

```python
from agentcrawl import CrawlEngine, CrawlerConfig

async with CrawlEngine.default() as engine:
    result = await engine.scrape("https://nonexistent.example.com")

    if not result.success:
        print(f"Error: {result.error}")
        print(f"Status: {result.status_code}")
    else:
        print(result.markdown)

# Batch with error handling
results = await engine.batch_scrape(urls)

successful = [r for r in results if r.success]
failed = [r for r in results if not r.success]

print(f"Success: {len(successful)}, Failed: {len(failed)}")
for r in failed:
    print(f"  {r.url}: {r.error}")
```

---

## Integration Patterns

### RAG Pipeline

```python
from agentcrawl import CrawlEngine, CrawlerConfig

config = CrawlerConfig(
    output_format="markdown",
    content_filter="pruning",
    chunker="topic",
    chunk_max_size=1000,
    chunk_overlap=200,
    include_metadata=True,
)

async with CrawlEngine.default() as engine:
    result = await engine.scrape("https://docs.example.com/guide", config)

    # Feed chunks to vector store
    for chunk in result.chunks:
        vector_store.add(
            text=chunk["text"],
            metadata={
                "url": result.url,
                "title": result.metadata.get("title", ""),
                "heading": chunk.get("heading", ""),
                "chunk_index": chunk["index"],
            },
        )
```

### LangChain Integration

```python
from langchain.document_loaders.base import BaseLoader
from langchain.schema import Document
from agentcrawl import CrawlEngine, CrawlerConfig

class AgentCrawlLoader(BaseLoader):
    def __init__(self, url: str, config: CrawlerConfig | None = None):
        self.url = url
        self.config = config or CrawlerConfig(
            content_filter="pruning",
            chunker="topic",
        )

    def load(self) -> list[Document]:
        import asyncio
        return asyncio.run(self._load())

    async def _load(self) -> list[Document]:
        async with CrawlEngine.default() as engine:
            result = await engine.scrape(self.url, self.config)

            docs = []
            for chunk in result.chunks:
                docs.append(Document(
                    page_content=chunk["text"],
                    metadata={
                        "source": result.url,
                        "title": result.metadata.get("title", ""),
                        "heading": chunk.get("heading", ""),
                    },
                ))
            return docs

# Usage
loader = AgentCrawlLoader("https://docs.example.com")
docs = loader.load()
```

### LlamaIndex Integration

```python
from llama_index.core import Document
from agentcrawl import CrawlEngine, CrawlerConfig

async def load_documents(urls: list[str]) -> list[Document]:
    config = CrawlerConfig(
        content_filter="pruning",
        chunker="topic",
    )

    async with CrawlEngine.default() as engine:
        results = await engine.batch_scrape(urls, config)

        documents = []
        for result in results:
            if result.success:
                for chunk in result.chunks:
                    documents.append(Document(
                        text=chunk["text"],
                        metadata={
                            "url": result.url,
                            "title": result.metadata.get("title", ""),
                        },
                    ))
        return documents
```

### AI Agent Tool

```python
# Define as a tool for AI agents
tools = [
    {
        "name": "scrape_webpage",
        "description": "Scrape a webpage and return clean Markdown content",
        "parameters": {
            "url": {"type": "string", "description": "URL to scrape"},
        },
    },
    {
        "name": "search_web",
        "description": "Search the web and return results",
        "parameters": {
            "query": {"type": "string", "description": "Search query"},
        },
    },
]

async def handle_tool(name: str, params: dict):
    if name == "scrape_webpage":
        result = await agentcrawl.scrape(params["url"])
        return result.markdown

    if name == "search_web":
        results = await agentcrawl.search(params["query"])
        return results
```

---

## Performance Tips

### 1. Reuse the Engine

```python
# ❌ Bad — creates/destroys engine per call
for url in urls:
    result = await agentcrawl.scrape(url)

# ✅ Good — reuse engine
async with CrawlEngine.default() as engine:
    for url in urls:
        result = await engine.scrape(url)
```

### 2. Use Batch Operations

```python
# ❌ Sequential
for url in urls:
    result = await engine.scrape(url)

# ✅ Concurrent
results = await engine.batch_scrape(urls, max_concurrent=10)
```

### 3. Enable Caching

```python
config = CrawlerConfig(cache=True, cache_ttl=3600)
# Second scrape of same URL returns cached result (~1ms vs ~3s)
```

### 4. Skip Unnecessary Processing

```python
# If you only need text, skip links/metadata/screenshots
config = CrawlerConfig(
    include_links=False,
    include_metadata=False,
    include_screenshot=False,
    include_citations=False,
    chunker="none",
)
```

### 5. Use CSS Extraction Over LLM

```python
# ❌ Slow + expensive
extractor = LLMExtractor(schema=Product)

# ✅ Fast + free (if HTML structure is known)
extractor = JsonCssExtractor(schema=css_schema)
```

### 6. Limit Crawl Scope

```python
# Use URL filters to avoid crawling irrelevant pages
from agentcrawl.crawling import URLFilter

url_filter = URLFilter(
    include_patterns=["/docs/*"],
    exclude_patterns=["/blog/*", "*.pdf"],
)
crawler = BFSCrawler(max_depth=3, max_pages=50, url_filter=url_filter)
```

---

*AgentCrawl v1.0.0 — Package Mode Guide*