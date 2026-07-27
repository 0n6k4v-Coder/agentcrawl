# API Reference

Complete API documentation for AgentCrawl v1.0.0.

---

## Table of Contents

- [Core Engine](#core-engine)
- [Configuration](#configuration)
- [Crawl Result](#crawl-result)
- [Crawling Strategies](#crawling-strategies)
- [Extraction Strategies](#extraction-strategies)
- [Content Processing](#content-processing)
- [Search](#search)
- [Cache](#cache)
- [Hooks](#hooks)
- [Output Formatters](#output-formatters)
- [REST API](#rest-api)
- [Utilities](#utilities)

---

## Core Engine

### `CrawlEngine`

The central orchestrator for all crawl operations.

```python
from agentcrawl import CrawlEngine, CrawlerConfig, Settings
```

#### Constructor

```python
CrawlEngine(
    browser_config: BrowserConfig | None = None,
    settings: Settings | None = None,
)
```

#### Factory Methods

| Method | Description |
|--------|-------------|
| `CrawlEngine.from_settings(settings)` | Create from global Settings |
| `CrawlEngine.from_browser_config(config)` | Create from BrowserConfig |
| `CrawlEngine.default()` | Create with default settings |

#### Lifecycle

| Method | Description |
|--------|-------------|
| `await engine.startup()` | Initialize browser, cache, and tools |
| `await engine.shutdown()` | Release all resources |
| `async with engine:` | Context manager (auto startup/shutdown) |

#### Operations

##### `scrape(url, config=None) → CrawlResult`

Scrape a single page.

```python
result = await engine.scrape(
    "https://example.com",
    config=CrawlerConfig(output_format="markdown"),
)
```

##### `crawl(url, strategy=None, config=None) → CrawlJobResult`

Crawl a website with a strategy.

```python
from agentcrawl import BFSCrawler

result = await engine.crawl(
    "https://docs.example.com",
    strategy=BFSCrawler(max_depth=3, max_pages=50),
)
```

##### `search(query, max_results=5, scrape=True, config=None) → list[CrawlResult]`

Search the web and optionally scrape results.

```python
results = await engine.search("python tutorial", max_results=5)
```

##### `map(url, max_urls=500, use_sitemap=True) → list[str]`

Discover all URLs on a website.

```python
urls = await engine.map("https://example.com", max_urls=1000)
```

##### `batch_scrape(urls, config=None, max_concurrent=5) → list[CrawlResult]`

Scrape multiple URLs concurrently.

```python
results = await engine.batch_scrape(
    ["https://a.com", "https://b.com"],
    max_concurrent=10,
)
```

##### `extract(url, schema=None, method="llm", config=None) → CrawlResult`

Extract structured data from a URL.

```python
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float

result = await engine.extract(
    "https://shop.example.com/product/1",
    schema=Product,
    method="llm",
)
print(result.extracted_data)
```

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `engine.is_started` | `bool` | Whether engine is initialized |
| `engine.stats` | `EngineStats` | Cumulative statistics |
| `engine.settings` | `Settings` | Global settings |

---

## Configuration

### `Settings`

Global application settings.

```python
from agentcrawl import Settings

settings = Settings(
    # Server
    host="0.0.0.0",
    port=8000,
    workers=4,
    # Browser
    browser_type="chromium",
    headless=True,
    stealth=True,
    # Cache
    cache_backend="memory",
    cache_ttl=3600,
    # LLM
    llm_provider="openai/gpt-4o-mini",
    openai_api_key="sk-...",
    # Logging
    log_level="INFO",
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"0.0.0.0"` | Server host |
| `port` | `int` | `8000` | Server port |
| `workers` | `int` | `4` | Worker processes |
| `browser_type` | `str` | `"chromium"` | Browser engine |
| `headless` | `bool` | `True` | Headless mode |
| `stealth` | `bool` | `True` | Anti-detection |
| `cache_backend` | `str` | `"memory"` | Cache backend |
| `cache_ttl` | `int` | `3600` | Cache TTL (seconds) |
| `llm_provider` | `str` | `"openai/gpt-4o-mini"` | LLM provider |
| `log_level` | `str` | `"INFO"` | Log level |

### `CrawlerConfig`

Per-request crawl configuration.

```python
from agentcrawl import CrawlerConfig

config = CrawlerConfig(
    output_format="markdown",
    include_links=True,
    include_metadata=True,
    include_screenshot=False,
    only_main_content=True,
    selectors=["article", ".content"],
    exclude_selectors=["nav", "footer"],
    actions=[
        {"type": "click", "selector": "#accept-cookies"},
        {"type": "scroll", "direction": "down", "amount": 3},
        {"type": "wait", "milliseconds": 1000},
    ],
    content_filter="pruning",
    chunker="topic",
    chunk_max_size=1000,
    chunk_overlap=200,
    cache=True,
    cache_ttl=3600,
    timeout=30,
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `output_format` | `str` | `"markdown"` | Output: markdown, json, html, text |
| `include_links` | `bool` | `True` | Extract links |
| `include_metadata` | `bool` | `True` | Extract metadata |
| `include_screenshot` | `bool` | `False` | Capture screenshot |
| `include_citations` | `bool` | `False` | Extract citations |
| `only_main_content` | `bool` | `True` | Skip nav/footer/sidebar |
| `selectors` | `list[str]` | `[]` | CSS selectors to target |
| `exclude_selectors` | `list[str]` | `[]` | CSS selectors to exclude |
| `actions` | `list[dict]` | `[]` | Page actions before extraction |
| `content_filter` | `str` | `"none"` | Filter: none, bm25, pruning |
| `content_filter_query` | `str` | `""` | Query for BM25 filter |
| `chunker` | `str` | `"none"` | Chunker: none, fixed, sentence, regex, topic |
| `chunk_max_size` | `int` | `1000` | Max chunk size (tokens) |
| `chunk_overlap` | `int` | `200` | Chunk overlap (tokens) |
| `extraction` | `ExtractionStrategy` | `None` | Extraction strategy |
| `cache` | `bool` | `True` | Enable caching |
| `cache_ttl` | `int` | `3600` | Cache TTL override |
| `timeout` | `int` | `30` | Page timeout (seconds) |

---

## Crawl Result

### `CrawlResult`

Result of a single page scrape.

| Field | Type | Description |
|-------|------|-------------|
| `url` | `str` | Scraped URL |
| `success` | `bool` | Whether scrape succeeded |
| `status_code` | `int` | HTTP status code |
| `markdown` | `str` | Clean Markdown content |
| `html` | `str` | Cleaned HTML |
| `raw_html` | `str` | Original raw HTML |
| `json` | `dict` | Structured JSON output |
| `text` | `str` | Plain text content |
| `metadata` | `dict` | Page metadata (title, description, og:tags) |
| `links` | `dict` | Extracted links (internal, external, all) |
| `citations` | `list[dict]` | Extracted citations |
| `chunks` | `list[dict]` | Content chunks |
| `extracted_data` | `Any` | Structured extraction result |
| `screenshot` | `str` | Base64 screenshot |
| `error` | `str \| None` | Error message |
| `response_time_ms` | `float` | Response time |
| `word_count` | `int` | Word count |
| `token_count` | `int` | Estimated token count |
| `cached` | `bool` | Whether from cache |
| `request_id` | `str` | Unique request ID |

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `result.to_dict()` | `dict` | Serialize to dictionary |
| `result.to_json()` | `str` | Serialize to JSON string |

### `CrawlJobResult`

Result of a multi-page crawl job.

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `str` | Unique job ID |
| `start_url` | `str` | Starting URL |
| `pages` | `list[CrawlResult]` | All page results |
| `total_pages` | `int` | Total pages crawled |
| `successful_pages` | `int` | Successful pages |
| `failed_pages` | `int` | Failed pages |
| `total_words` | `int` | Total word count |
| `total_tokens` | `int` | Total token count |
| `duration_ms` | `float` | Total duration |
| `strategy` | `str` | Strategy used |
| `status` | `str` | Job status |

---

## Crawling Strategies

### `BFSCrawler`

Breadth-first search — explores level by level.

```python
from agentcrawl import BFSCrawler

crawler = BFSCrawler(
    max_depth=3,
    max_pages=100,
    max_concurrent=5,
    sort_by_score=False,
)
urls = await crawler.discover("https://docs.example.com", engine)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_depth` | `int` | `3` | Maximum link depth |
| `max_pages` | `int` | `50` | Maximum pages |
| `max_concurrent` | `int` | `5` | Concurrent fetches |
| `process_per_level` | `bool` | `True` | Process one level at a time |
| `sort_by_score` | `bool` | `False` | Sort URLs by score within level |

### `DFSCrawler`

Depth-first search — explores deep branches first.

```python
from agentcrawl import DFSCrawler

crawler = DFSCrawler(
    max_depth=5,
    max_pages=100,
    push_order="score",
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_depth` | `int` | `3` | Maximum depth |
| `max_pages` | `int` | `50` | Maximum pages |
| `max_backtracks` | `int` | `0` | Max backtracks (0=unlimited) |
| `push_order` | `str` | `"score"` | Push order: first, last, score |
| `prioritize_deep` | `bool` | `True` | Bonus for deeper links |

### `BestFirstCrawler`

Priority-based — explores highest-scored URL first.

```python
from agentcrawl import BestFirstCrawler

crawler = BestFirstCrawler(
    max_pages=50,
    score_threshold=0.3,
    decay_factor=0.05,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_pages` | `int` | `50` | Maximum pages |
| `score_threshold` | `float` | `0.0` | Minimum score to enqueue |
| `decay_factor` | `float` | `0.05` | Score decay per depth |
| `diversity_bonus` | `float` | `0.05` | Bonus for new URL patterns |

### `AdaptiveCrawler`

Pattern-learning — adapts to site structure.

```python
from agentcrawl import AdaptiveCrawler

crawler = AdaptiveCrawler(
    max_pages=100,
    max_depth=4,
    similarity_threshold=0.85,
    learn_from_pages=5,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_pages` | `int` | `100` | Maximum pages |
| `max_depth` | `int` | `4` | Maximum depth |
| `learn_from_pages` | `int` | `5` | Pages to learn patterns from |
| `similarity_threshold` | `float` | `0.85` | Content dedup threshold |
| `min_pattern_score` | `float` | `0.2` | Minimum pattern score |

### `SinglePageCrawler`

Single page — no link following.

```python
from agentcrawl import SinglePageCrawler

crawler = SinglePageCrawler(
    actions=[{"type": "click", "selector": "#btn"}],
    wait_for_selector="#content",
)
```

### `DomainMapper`

Full-site URL discovery without scraping.

```python
from agentcrawl import DomainMapper

mapper = DomainMapper(
    max_urls=500,
    use_sitemap=True,
    use_robots=True,
    use_link_crawl=True,
)
urls = await mapper.discover("https://example.com")
```

### `SitemapParser`

Comprehensive sitemap.xml parsing.

```python
from agentcrawl import SitemapParser

parser = SitemapParser(max_urls=10000)
entries = await parser.parse("https://example.com/sitemap.xml")
result = await parser.discover_and_parse("https://example.com")
```

---

## Extraction Strategies

### `LLMExtractor`

LLM-powered structured extraction.

```python
from agentcrawl import LLMExtractor
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float
    description: str

extractor = LLMExtractor(
    schema=Product,
    llm_config=LLMConfig(provider="openai/gpt-4o-mini"),
    max_content_tokens=8000,
)
result = await extractor.extract(html=html, markdown=md)
print(result.data)  # Product instance
```

### `JsonCssExtractor`

CSS selector-based extraction.

```python
from agentcrawl import JsonCssExtractor

schema = {
    "name": "Product",
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
            ],
        },
    ],
}

extractor = JsonCssExtractor(schema=schema)
result = await extractor.extract(html=html)
```

**Field Types:** `text`, `html`, `attribute`, `list`, `nested`, `regex`

### `JsonXPathExtractor`

XPath expression-based extraction.

```python
from agentcrawl import JsonXPathExtractor

schema = {
    "name": "Product",
    "baseXPath": "//div[@class='product']",
    "fields": [
        {"name": "title", "xpath": ".//h2", "type": "text"},
        {"name": "price", "xpath": ".//span[contains(@class,'price')]", "type": "text"},
    ],
}
```

### `CosineExtractor`

Similarity-based clustering extraction.

```python
from agentcrawl import CosineExtractor

extractor = CosineExtractor(
    threshold=0.7,
    min_cluster_size=3,
)
result = await extractor.extract(html=html)
```

### `RegexExtractor`

Regex pattern extraction.

```python
from agentcrawl import RegexExtractor

schema = {
    "name": "Contact",
    "fields": [
        {"name": "email", "pattern": r"[\w.+-]+@[\w-]+\.[\w.]+", "type": "first"},
        {"name": "phones", "pattern": r"\+?[\d\s\-]{10,}", "type": "all"},
    ],
}
extractor = RegexExtractor(schema=schema)
```

### `FitMarkdownExtractor`

LLM-optimized Markdown extraction.

```python
from agentcrawl import FitMarkdownExtractor

extractor = FitMarkdownExtractor(
    include_links=True,
    remove_boilerplate=True,
    max_length=10000,
)
result = await extractor.extract(html=html)
```

### `TableExtractor`

HTML table extraction.

```python
from agentcrawl import TableExtractor

extractor = TableExtractor(
    output_format="json",
    infer_types=True,
)
result = await extractor.extract(html=html)
```

### `SchemaBuilder`

Fluent schema construction.

```python
from agentcrawl import SchemaBuilder

schema = (
    SchemaBuilder("Product")
    .base_selector("div.product")
    .field("title", selector="h2", type="text")
    .field("price", selector=".price", type="text")
    .link_field("url", selector="a")
    .image_field("image", selector="img")
    .build()
)
```

### `create_extractor(method, schema, **kwargs)`

Factory function.

```python
from agentcrawl import create_extractor

extractor = create_extractor("llm", schema=Product)
extractor = create_extractor("css", schema=css_schema)
extractor = create_extractor("xpath", schema=xpath_schema)
```

---

## Content Processing

### Content Filters

#### `PruningContentFilter`

```python
from agentcrawl.content import PruningContentFilter

filter = PruningContentFilter(threshold=0.4)
result = filter.apply(markdown)
print(result.filtered_text)
```

#### `BM25ContentFilter`

```python
from agentcrawl.content import BM25ContentFilter

filter = BM25ContentFilter(query="machine learning", threshold=1.0)
result = filter.apply(markdown)
```

### Chunkers

#### `TopicChunker`

```python
from agentcrawl.content import TopicChunker

chunker = TopicChunker(max_chunk_size=1000, overlap=200)
result = chunker.chunk(markdown, metadata={"url": url})
for chunk in result.chunks:
    print(f"[{chunk.heading}] {chunk.token_count} tokens")
```

#### `SentenceChunker`

```python
from agentcrawl.content import SentenceChunker

chunker = SentenceChunker(max_chunk_size=500, overlap=50)
```

#### `create_chunker(strategy, **kwargs)`

```python
from agentcrawl.content import create_chunker

chunker = create_chunker("topic", max_chunk_size=1000)
chunker = create_chunker("sentence", max_chunk_size=500)
```

### Citations

```python
from agentcrawl.content import CitationExtractor

extractor = CitationExtractor(deduplicate=True)
result = extractor.extract(markdown)
print(result.format_bibliography("markdown"))
```

### HTML Processing

```python
from agentcrawl.content import HTMLParser, HTMLToMarkdown, html_to_markdown

# Parse
parser = HTMLParser(html, base_url="https://example.com")
content = parser.get_main_content()
meta = parser.get_metadata()
links = parser.get_links()

# Convert
markdown = html_to_markdown(html)
```

---

## Search

### `SearchEngine`

```python
from agentcrawl import SearchEngine

# DuckDuckGo (no API key)
engine = SearchEngine(provider="duckduckgo")
results = await engine.search("python tutorial")

# Tavily
engine = SearchEngine(provider="tavily", api_key="tvly-...")
results = await engine.search("machine learning")

# Search and scrape
results = await engine.search_and_scrape(
    "python web scraping",
    crawl_engine=crawl_engine,
)
```

**Providers:** `duckduckgo`, `tavily`, `brave`, `exa`, `google`, `searxng`

### `SearchResult`

| Field | Type | Description |
|-------|------|-------------|
| `url` | `str` | Result URL |
| `title` | `str` | Page title |
| `snippet` | `str` | Text snippet |
| `position` | `int` | Result position |
| `domain` | `str` | Extracted domain |
| `score` | `float` | Relevance score |

---

## Cache

### `CacheManager`

```python
from agentcrawl import CacheManager
from agentcrawl.config import CacheConfig

cache = CacheManager(config=CacheConfig(backend="memory", ttl=3600))
await cache.start()

await cache.set("key", {"data": "value"}, ttl=3600)
value = await cache.get("key")
await cache.delete("key")
await cache.clear()

stats = cache.get_stats()
```

**Backends:** `memory`, `redis`, `disk`, `none`

---

## Hooks

### `HookExecutor`

```python
from agentcrawl import HookExecutor, HookEvent, HookContext

executor = HookExecutor()

@executor.on(HookEvent.PRE_SCRAPE)
async def log_url(ctx: HookContext):
    print(f"Scraping: {ctx.url}")

@executor.on(HookEvent.POST_SCRAPE, priority=10)
async def add_timestamp(ctx: HookContext):
    ctx.data["scraped_at"] = time.time()

@executor.on(HookEvent.ON_ERROR)
async def handle_error(ctx: HookContext):
    logger.error(f"Error: {ctx.error}")

ctx = HookContext(url="https://example.com")
await executor.execute(HookEvent.PRE_SCRAPE, ctx)
```

**Events:** `pre_scrape`, `post_scrape`, `pre_extract`, `post_extract`, `pre_filter`, `post_filter`, `pre_chunk`, `post_chunk`, `on_error`, `on_complete`, `pre_crawl`, `post_crawl`

### `HookRegistry`

```python
from agentcrawl import HookRegistry, hook

@hook(event="pre_scrape", group="logging", priority=10)
async def my_hook(ctx):
    print(f"Scraping: {ctx.url}")

registry = HookRegistry.global_registry()
registry.register_builtins()
registry.disable_group("analytics")
```

---

## Output Formatters

### `JsonOutputFormatter`

```python
from agentcrawl import JsonOutputFormatter

formatter = JsonOutputFormatter(
    pretty=True,
    fields=["url", "markdown", "metadata"],
    flatten=False,
)
json_str = formatter.format(result)
formatter.save(result, "output.json")
```

### `MarkdownOutputFormatter`

```python
from agentcrawl import MarkdownOutputFormatter

formatter = MarkdownOutputFormatter(
    include_front_matter=True,
    include_citations=True,
    include_links=True,
)
md = formatter.format(result)
formatter.save(result, "output.md")
```

### `HtmlOutputFormatter`

```python
from agentcrawl import HtmlOutputFormatter

formatter = HtmlOutputFormatter(sanitize=True, include_styles=True)
html = formatter.format(result)
pdf_bytes = await formatter.to_pdf(result)
```

### `ScreenshotHandler`

```python
from agentcrawl import ScreenshotHandler

handler = ScreenshotHandler()
handler.save(result, "screenshot.png")
info = handler.get_info(result.screenshot)
diff = handler.compare(screenshot_a, screenshot_b)
```

---

## REST API

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/scrape` | Scrape a single page |
| `POST` | `/crawl` | Start a crawl job |
| `GET` | `/crawl/{job_id}` | Get crawl job status |
| `DELETE` | `/crawl/{job_id}` | Cancel a crawl job |
| `POST` | `/map` | Discover URLs |
| `POST` | `/search` | Web search |
| `POST` | `/extract` | Structured extraction |
| `POST` | `/batch/scrape` | Batch scrape |
| `GET` | `/health` | Health check |
| `GET` | `/` | API info |

### `POST /scrape`

**Request:**
```json
{
    "url": "https://example.com",
    "output_format": "markdown",
    "include_links": true,
    "include_metadata": true,
    "only_main_content": true,
    "actions": [
        {"type": "click", "selector": "#accept"}
    ],
    "content_filter": "pruning",
    "chunker": "topic",
    "cache": true
}
```

**Response:**
```json
{
    "url": "https://example.com",
    "success": true,
    "status_code": 200,
    "markdown": "# Example Domain\n\n...",
    "metadata": {"title": "Example", "description": "..."},
    "links": {"internal": [...], "external": [...]},
    "word_count": 150,
    "token_count": 200,
    "response_time_ms": 1234.5,
    "cached": false
}
```

### `POST /crawl`

**Request:**
```json
{
    "url": "https://docs.example.com",
    "strategy": "bfs",
    "max_depth": 3,
    "max_pages": 50,
    "output_format": "markdown"
}
```

**Response:**
```json
{
    "job_id": "job_a1b2c3d4",
    "status": "queued"
}
```

### `POST /search`

**Request:**
```json
{
    "query": "python tutorial",
    "max_results": 5,
    "scrape_results": false
}
```

### `GET /health`

**Response:**
```json
{
    "status": "healthy",
    "version": "1.0.0",
    "uptime_seconds": 3600,
    "browser_connected": true,
    "cache_backend": "memory",
    "active_pages": 2,
    "total_scrapes": 150
}
```

---

## Utilities

### Crypto

```python
from agentcrawl.utils import (
    encrypt_api_key, decrypt_api_key,
    hash_sha256, hmac_sign,
    generate_token, generate_api_key,
    CryptoManager,
)
```

### Text

```python
from agentcrawl.utils import (
    clean_text, count_words, count_sentences,
    estimate_tokens, truncate, slugify,
    detect_language, text_similarity,
    extract_keywords, analyze_text,
)
```

### URL

```python
from agentcrawl.utils import (
    normalize_url, is_valid_url,
    get_domain, get_base_domain,
    join_url, url_matches_pattern,
    filter_urls, deduplicate_urls,
)
```

### HTML

```python
from agentcrawl.utils import (
    strip_tags, extract_text, clean_html,
    sanitize_html, decode_entities,
    extract_links, extract_meta_tags,
)
```

### Retry

```python
from agentcrawl.utils import retry, RetryConfig, CircuitBreaker, RateLimiter

@retry(max_retries=3, delay=1.0)
async def fetch(): ...

breaker = CircuitBreaker(failure_threshold=5)
limiter = RateLimiter(max_calls=10, window_seconds=60)
```

### Logging

```python
from agentcrawl.utils import setup_logging, get_logger, LoggingContext

setup_logging(level="INFO", json_format=False)
logger = get_logger(__name__)

with LoggingContext(request_id="req_123"):
    logger.info("Processing")
```

---

## Convenience Functions

```python
import agentcrawl

# Scrape
result = await agentcrawl.scrape("https://example.com")

# Crawl
job = await agentcrawl.crawl("https://docs.example.com")

# Search
results = await agentcrawl.search("python tutorial")

# Map
urls = await agentcrawl.map_site("https://example.com")
```

---

*AgentCrawl v1.0.0 — Apache-2.0 License*