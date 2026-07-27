# AgentCrawl Documentation

**Web Crawling & Scraping Framework for AI Agents**

Convert any website into clean, LLM-ready Markdown or structured JSON. Built for AI agents, RAG pipelines, and production scraping workloads.

---

## Getting Started

### Installation

```bash
# Core (browser automation + content processing)
pip install agentcrawl

# With LLM extraction support
pip install "agentcrawl[llm]"

# With Redis cache/queue
pip install "agentcrawl[redis]"

# Full installation
pip install "agentcrawl[all]"

# Install Playwright browsers
playwright install chromium
```

### Quick Start

```python
from agentcrawl import CrawlEngine, CrawlerConfig

async with CrawlEngine.default() as engine:
    # Scrape a single page
    result = await engine.scrape(
        "https://example.com",
        config=CrawlerConfig(output_format="markdown"),
    )
    print(result.markdown)

    # Deep crawl a website
    from agentcrawl import BFSCrawler
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=BFSCrawler(max_depth=3, max_pages=50),
    )
    print(f"Crawled {job.total_pages} pages")

    # Search the web
    results = await engine.search("python tutorial", max_results=5)

    # Discover all URLs
    urls = await engine.map("https://example.com")
```

### Structured Extraction

```python
from agentcrawl import CrawlEngine, LLMExtractor
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float
    description: str

async with CrawlEngine.default() as engine:
    result = await engine.extract(
        "https://shop.example.com/product/1",
        schema=Product,
        method="llm",
    )
    print(result.extracted_data)  # Product instance
```

---

## Documentation

### Guides

| Document | Description |
|----------|-------------|
| [API Reference](api_reference.md) | Complete API documentation for all classes and functions |
| [Architecture](architecture.md) | Internal architecture, data flow, and design decisions |
| [Configuration](configuration.md) | Settings, environment variables, and per-request config |
| [Deployment](deployment.md) | Docker, Docker Compose, Kubernetes, and production setup |

### Core Concepts

| Topic | Description |
|-------|-------------|
| [Scraping](#scraping) | Single page scraping with content processing |
| [Crawling](#crawling) | Multi-page crawling with BFS, DFS, BestFirst, Adaptive |
| [Extraction](#extraction) | Structured data extraction (LLM, CSS, XPath, Cosine) |
| [Search](#search) | Web search with multiple providers |
| [Content Processing](#content-processing) | Filtering, chunking, citations |
| [Caching](#caching) | Memory, Redis, and disk caching |
| [Hooks](#hooks) | Pipeline event system |
| [REST API](#rest-api) | Server mode with FastAPI |

---

## Scraping

Scrape a single page and get clean Markdown output:

```python
from agentcrawl import CrawlEngine, CrawlerConfig

config = CrawlerConfig(
    output_format="markdown",
    include_links=True,
    include_metadata=True,
    only_main_content=True,
    content_filter="pruning",       # Remove noise
    chunker="topic",                # Split into chunks
    chunk_max_size=1000,
    include_citations=True,         # Extract [1], [2] references
)

async with CrawlEngine.default() as engine:
    result = await engine.scrape("https://example.com", config)

    print(result.markdown)          # Clean Markdown
    print(result.metadata)          # Title, description, og:tags
    print(result.links)             # Internal/external links
    print(result.chunks)            # RAG-ready chunks
    print(result.citations)         # Extracted citations
    print(result.word_count)        # Word count
    print(result.token_count)       # Estimated tokens
```

### Page Actions

Execute actions before extraction (click cookies, scroll, wait):

```python
config = CrawlerConfig(
    actions=[
        {"type": "click", "selector": "#accept-cookies"},
        {"type": "scroll", "direction": "down", "amount": 3},
        {"type": "wait", "selector": "#content-loaded"},
        {"type": "screenshot"},
    ],
)
```

---

## Crawling

Crawl entire websites with configurable strategies:

```python
from agentcrawl import CrawlEngine, BFSCrawler, DFSCrawler, BestFirstCrawler, AdaptiveCrawler

async with CrawlEngine.default() as engine:
    # Breadth-first (level by level)
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=BFSCrawler(max_depth=3, max_pages=100),
    )

    # Depth-first (deep branches first)
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=DFSCrawler(max_depth=5, max_pages=50),
    )

    # Best-first (highest score first)
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=BestFirstCrawler(max_pages=50, score_threshold=0.3),
    )

    # Adaptive (learns site patterns)
    job = await engine.crawl(
        "https://docs.example.com",
        strategy=AdaptiveCrawler(max_pages=100, similarity_threshold=0.85),
    )

    # Access results
    for page in job.pages:
        print(f"{page.url}: {page.word_count} words")
```

### URL Discovery

Discover all URLs without scraping content:

```python
from agentcrawl import DomainMapper, SitemapParser

# Full-site URL discovery
mapper = DomainMapper(max_urls=500, use_sitemap=True)
urls = await mapper.discover("https://example.com")

# Parse sitemap.xml
parser = SitemapParser()
entries = await parser.parse("https://example.com/sitemap.xml")
```

---

## Extraction

Extract structured data using multiple strategies:

### LLM Extraction

```python
from agentcrawl import LLMExtractor, LLMConfig
from pydantic import BaseModel

class Article(BaseModel):
    title: str
    author: str
    date: str
    summary: str

extractor = LLMExtractor(
    schema=Article,
    llm_config=LLMConfig(provider="openai/gpt-4o-mini"),
)
result = await extractor.extract(markdown=content)
print(result.data)  # Article instance
```

### CSS Selector Extraction

```python
from agentcrawl import JsonCssExtractor

schema = {
    "name": "Product",
    "baseSelector": "div.product-card",
    "fields": [
        {"name": "title", "selector": "h2", "type": "text"},
        {"name": "price", "selector": ".price", "type": "text"},
        {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
    ],
}

extractor = JsonCssExtractor(schema=schema)
result = await extractor.extract(html=html)
```

### Schema Builder

```python
from agentcrawl import SchemaBuilder

schema = (
    SchemaBuilder("Product")
    .base_selector("div.product")
    .text_field("title", selector="h2")
    .text_field("price", selector=".price")
    .link_field("url")
    .image_field("image")
    .build()
)
```

---

## Search

Search the web with multiple providers:

```python
from agentcrawl import SearchEngine

# DuckDuckGo (no API key required)
engine = SearchEngine(provider="duckduckgo")
results = await engine.search("python asyncio tutorial")

# Tavily (AI-optimized)
engine = SearchEngine(provider="tavily", api_key="tvly-...")
results = await engine.search("machine learning")

# Search and scrape results
results = await engine.search_and_scrape(
    "python web scraping",
    crawl_engine=crawl_engine,
)
```

**Providers:** DuckDuckGo, Google, Bing, Brave, Tavily, Exa, SearXNG

---

## Content Processing

### Content Filtering

```python
from agentcrawl.content import PruningContentFilter, BM25ContentFilter

# Remove low-density content
filter = PruningContentFilter(threshold=0.4)
result = filter.apply(markdown)

# Filter by query relevance
filter = BM25ContentFilter(query="machine learning")
result = filter.apply(markdown)
```

### Chunking

```python
from agentcrawl.content import TopicChunker, SentenceChunker, create_chunker

# Topic-aware chunking (splits at headings)
chunker = TopicChunker(max_chunk_size=1000, overlap=200)
result = chunker.chunk(markdown)

for chunk in result.chunks:
    print(f"[{chunk.heading}] {chunk.token_count} tokens")

# Factory
chunker = create_chunker("sentence", max_chunk_size=500)
```

### Citations

```python
from agentcrawl.content import CitationExtractor

extractor = CitationExtractor(deduplicate=True)
result = extractor.extract(markdown)
print(result.format_bibliography("markdown"))
```

---

## Caching

```python
from agentcrawl import CacheManager
from agentcrawl.config import CacheConfig

# Memory cache
cache = CacheManager(config=CacheConfig(backend="memory", ttl=3600))

# Redis cache
cache = CacheManager(config=CacheConfig(
    backend="redis",
    redis_url="redis://localhost:6379",
    ttl=3600,
))

await cache.start()
await cache.set("key", data, ttl=3600)
value = await cache.get("key")
```

---

## Hooks

Extend the pipeline with event-driven hooks:

```python
from agentcrawl import HookExecutor, HookEvent, HookContext

executor = HookExecutor()

@executor.on(HookEvent.PRE_SCRAPE)
async def log_url(ctx: HookContext):
    print(f"Scraping: {ctx.url}")

@executor.on(HookEvent.POST_SCRAPE)
async def track_metrics(ctx: HookContext):
    analytics.track("scrape", url=ctx.url, ms=ctx.elapsed_ms)

@executor.on(HookEvent.ON_ERROR)
async def alert_error(ctx: HookContext):
    notify(f"Scrape failed: {ctx.url} — {ctx.error}")
```

---

## REST API

Run AgentCrawl as a standalone server:

```bash
# Start server
agentcrawl serve --port 8000

# Or with uvicorn
uvicorn agentcrawl.server.app:app --host 0.0.0.0 --port 8000
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/scrape` | Scrape a single page |
| `POST` | `/crawl` | Start a crawl job |
| `GET` | `/crawl/{job_id}` | Get crawl job status |
| `POST` | `/map` | Discover URLs |
| `POST` | `/search` | Web search |
| `POST` | `/extract` | Structured extraction |
| `POST` | `/batch/scrape` | Batch scrape |
| `GET` | `/health` | Health check |

### Example

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "output_format": "markdown"}'
```

---

## Configuration

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
ENCRYPTION_KEY=your-encryption-key
```

### Settings Object

```python
from agentcrawl import Settings

settings = Settings(
    browser_type="chromium",
    headless=True,
    stealth=True,
    cache_backend="redis",
    redis_url="redis://localhost:6379",
    log_level="INFO",
)

engine = CrawlEngine.from_settings(settings)
```

See [Configuration Guide](configuration.md) for all options.

---

## Project Structure

```
agentcrawl/
├── core/          # Engine, Pipeline, Session
├── config/        # Settings, CrawlerConfig, BrowserConfig
├── browser/       # Playwright automation, stealth, proxies
├── content/       # HTML parsing, Markdown, filtering, chunking
├── extraction/    # LLM, CSS, XPath, Cosine, Regex extraction
├── crawling/      # BFS, DFS, BestFirst, Adaptive strategies
├── search/        # Web search providers
├── cache/         # Memory, Redis, disk caching
├── queue/         # Job queue for async crawls
├── hooks/         # Pipeline event system
├── output/        # JSON, Markdown, HTML formatters
├── utils/         # Crypto, text, URL, logging, retry
├── server/        # FastAPI REST API
└── cli/           # Command-line interface
```

See [Architecture](architecture.md) for detailed design.

---

## Requirements

- Python 3.10+
- Playwright (auto-installed)
- lxml (HTML parsing)
- httpx (HTTP client)

Optional:
- litellm (LLM extraction)
- redis (Redis cache/queue)
- weasyprint (PDF output)
- Pillow (screenshot comparison)

---

## License

Apache-2.0

---

## Links

- **GitHub**: [github.com/agentcrawl/agentcrawl](https://github.com/agentcrawl/agentcrawl)
- **PyPI**: [pypi.org/project/agentcrawl](https://pypi.org/project/agentcrawl/)
- **Issues**: [GitHub Issues](https://github.com/agentcrawl/agentcrawl/issues)

---

*AgentCrawl v1.0.0*