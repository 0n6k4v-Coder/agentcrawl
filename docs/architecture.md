# Architecture

This document describes the internal architecture of AgentCrawl — its layers, data flow, design decisions, and extension points.

---

## Table of Contents

- [Overview](#overview)
- [Layer Architecture](#layer-architecture)
- [Data Flow Pipeline](#data-flow-pipeline)
- [Module Map](#module-map)
- [Core Engine](#core-engine)
- [Browser Layer](#browser-layer)
- [Content Processing Layer](#content-processing-layer)
- [Extraction Layer](#extraction-layer)
- [Crawling Layer](#crawling-layer)
- [Search Layer](#search-layer)
- [Cache Layer](#cache-layer)
- [Hooks Layer](#hooks-layer)
- [Output Layer](#output-layer)
- [Configuration System](#configuration-system)
- [Server Mode](#server-mode)
- [Design Decisions](#design-decisions)
- [Extension Points](#extension-points)
- [Performance](#performance)
- [Security Model](#security-model)
- [Deployment](#deployment)

---

## Overview

AgentCrawl is built as a **layered, pipeline-based architecture** where each layer has a single responsibility and communicates through well-defined interfaces. The system is designed around two key principles:

1. **Pipeline-first**: Every operation flows through a composable pipeline of stages (fetch → parse → extract → filter → chunk → output).
2. **Strategy pattern**: All pluggable behaviors (crawling, extraction, filtering, chunking) use abstract base classes with interchangeable implementations.

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / AI Agent                          │
│                  (Package Mode or REST API)                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      Core Engine Layer                      │
│         CrawlEngine · Pipeline · Session · Types            │
└───┬─────────┬─────────┬─────────┬─────────┬─────────────────┘
    │         │         │         │         │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐
│Browser│ │Content│ │Extract│ │Crawl  │ │Search │
│ Layer │ │ Layer │ │ Layer │ │ Layer │ │ Layer │
└───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘
    │         │         │         │         │
┌───▼─────────▼─────────▼─────────▼─────────▼─────────────────┐
│                    Infrastructure Layer                     │
│           Cache · Queue · Hooks · Config · Utils            │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer Architecture

### Layer 1: Interface Layer

The entry points for users and AI agents.

| Component | File | Responsibility |
|-----------|------|----------------|
| Package API | `agentcrawl/__init__.py` | Python imports, convenience functions |
| REST API | `agentcrawl/server/` | FastAPI endpoints, middleware |
| CLI | `agentcrawl/cli/` | Command-line interface |

### Layer 2: Core Engine Layer

The orchestration layer that coordinates all subsystems.

| Component | File | Responsibility |
|-----------|------|----------------|
| `CrawlEngine` | `core/engine.py` | Main orchestrator (scrape, crawl, search, map) |
| `Pipeline` | `core/pipeline.py` | Composable stage-based processing |
| `CrawlSession` | `core/session.py` | Stateful session management |
| Types | `core/types.py` | Shared type definitions, protocols |

### Layer 3: Processing Layers

Specialized subsystems for each processing concern.

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| Browser | `browser/` | Playwright automation, stealth, proxies |
| Content | `content/` | HTML parsing, Markdown conversion, filtering, chunking |
| Extraction | `extraction/` | Structured data extraction (LLM, CSS, XPath, etc.) |
| Crawling | `crawling/` | Multi-page crawl strategies |
| Search | `search/` | Web search providers |

### Layer 4: Infrastructure Layer

Cross-cutting concerns shared by all layers.

| Component | Directory | Responsibility |
|-----------|-----------|----------------|
| Cache | `cache/` | Multi-backend caching |
| Queue | `queue/` | Job queue for async crawls |
| Hooks | `hooks/` | Event-driven pipeline extension |
| Config | `config/` | Pydantic settings management |
| Utils | `utils/` | Crypto, text, URL, HTML, logging, retry |
| Output | `output/` | Output formatters (JSON, Markdown, HTML) |

---

## Data Flow Pipeline

### Single Page Scrape

```
URL
 │
 ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Cache Check │────▶│ Browser Fetch│────▶│  HTML Parse │
│  (optional)  │     │ (Playwright) │     │  (lxml)      │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                     ┌──────────────┐     ┌──────▼───────┐
                     │  Cache Write │◀────│  Convert to  │
                     │  (optional)  │     │  Markdown    │
                     └──────────────┘     └──────┬───────┘
                                                 │
                     ┌──────────────┐     ┌──────▼───────┐
                     │  Extraction  │◀────│   Content    │
                     │  (optional)  │     │   Filter     │
                     └──────┬───────┘     └──────┬───────┘
                            │                     │
                     ┌──────▼───────┐     ┌──────▼───────┐
                     │   Chunker    │◀────│  Citations   │
                     │  (optional)  │     │  (optional)  │
                     └──────┬───────┘     └──────────────┘
                            │
                     ┌──────▼───────┐
                     │  CrawlResult │
                     └──────────────┘
```

### Pipeline Stages

The `Pipeline` class implements this flow as composable stages:

```python
Pipeline([
    CacheReadStage(cache_manager),    # Check cache
    FetchStage(browser_manager),       # Browser fetch
    ParseStage(),                      # HTML parsing
    ConvertStage(),                    # HTML → Markdown
    FilterStage(),                     # Content filtering
    ChunkStage(),                      # Chunking
    CitationStage(),                   # Citation extraction
    ExtractionStage(),                 # Structured extraction
    CacheWriteStage(cache_manager),    # Write to cache
])
```

Each stage:
- Receives a shared `PipelineContext`
- Reads input fields, writes output fields
- Can be conditionally skipped based on config
- Reports timing and errors independently

### Multi-Page Crawl

```
Start URL
    │
    ▼
┌────────────────┐
│ Crawl Strategy │  (BFS / DFS / BestFirst / Adaptive)
│  (discovery)   │
└───────┬────────┘
        │
        ▼
┌────────────────┐     ┌────────────────┐
│  URL Queue /   │────▶│  Single Page   │──▶ CrawlResult
│  Priority Heap │     │  Pipeline      │
└───────┬────────┘     └────────────────┘
        │
        ▼ (repeat until max_pages or queue empty)
┌────────────────┐
│ CrawlJobResult │
└────────────────┘
```

---

## Module Map

```
agentcrawl/
├── __init__.py              # Package root, lazy imports, convenience functions
│
├── core/                    # Layer 2: Core Engine
│   ├── engine.py            # CrawlEngine — main orchestrator
│   ├── pipeline.py          # Pipeline, PipelineStage, built-in stages
│   ├── session.py           # CrawlSession — stateful sessions
│   └── types.py             # Shared types, protocols, enums
│
├── config/                  # Configuration
│   ├── settings.py          # Settings — global Pydantic settings
│   ├── crawler_config.py    # CrawlerConfig — per-request config
│   ├── browser_config.py    # BrowserConfig — browser automation
│   ├── llm_config.py        # LLMConfig — LLM provider config
│   ├── cache_config.py      # CacheConfig — cache backend config
│   ├── queue_config.py      # QueueConfig — job queue config
│   └── proxy_config.py      # ProxyConfig — proxy settings
│
├── browser/                 # Layer 3: Browser Automation
│   ├── manager.py           # BrowserManager — context/page pooling
│   ├── stealth.py           # StealthConfig — anti-detection
│   ├── actions.py           # PageActions — click, type, scroll, etc.
│   ├── fingerprint.py       # BrowserFingerprint — fingerprint generation
│   └── config.py            # Re-exports BrowserConfig
│
├── content/                 # Layer 3: Content Processing
│   ├── html_parser.py       # HTMLParser — lxml-based parsing
│   ├── html_to_markdown.py  # HTMLToMarkdown — conversion engine
│   ├── content_filter.py    # PruningContentFilter, base classes
│   ├── bm25_filter.py       # BM25ContentFilter — BM25 scoring
│   ├── chunker.py           # TopicChunker, SentenceChunker, etc.
│   └── citation.py          # CitationExtractor — citation detection
│
├── extraction/              # Layer 3: Structured Extraction
│   ├── base.py              # ExtractionStrategy ABC, SchemaResolver
│   ├── llm.py               # LLMExtractor — LLM-powered
│   ├── json_css.py          # JsonCssExtractor — CSS selectors
│   ├── json_xpath.py        # JsonXPathExtractor — XPath
│   ├── cosine.py            # CosineExtractor — similarity clustering
│   ├── regex.py             # RegexExtractor — regex patterns
│   ├── markdown.py          # MarkdownExtractor — standard markdown
│   ├── fit_markdown.py      # FitMarkdownExtractor — LLM-optimized
│   ├── table.py             # TableExtractor — HTML tables
│   └── schema.py            # SchemaBuilder, templates, converter
│
├── crawling/                # Layer 3: Crawling Strategies
│   ├── base.py              # CrawlStrategy ABC, URLFilter, URLScorer
│   ├── bfs.py               # BFSCrawler — breadth-first
│   ├── dfs.py               # DFSCrawler — depth-first
│   ├── best_first.py        # BestFirstCrawler — priority-based
│   ├── adaptive.py          # AdaptiveCrawler — pattern-learning
│   ├── single.py            # SinglePageCrawler — single page
│   ├── domain_mapper.py     # DomainMapper — full-site URL discovery
│   ├── sitemap_parser.py    # SitemapParser — sitemap.xml parsing
│   ├── url_filter.py        # AdvancedURLFilter, RobotsTxtParser
│   └── url_scorer.py        # AdvancedURLScorer, ScoringPreset
│
├── search/                  # Layer 3: Web Search
│   ├── engine.py            # SearchEngine, provider base classes
│   ├── google.py            # GoogleSearchProvider
│   ├── scraper.py           # SearchScraper — direct SERP scraping
│   └── searxng.py           # SearXNGProvider — metasearch
│
├── cache/                   # Layer 4: Caching
│   ├── manager.py           # CacheManager — unified interface
│   ├── base.py              # CacheBackend ABC
│   ├── memory.py            # MemoryCacheBackend
│   ├── redis_backend.py     # RedisCacheBackend
│   ├── disk.py              # DiskCacheBackend
│   └── key_generator.py     # CacheKeyGenerator
│
├── queue/                   # Layer 4: Job Queue
│   ├── manager.py           # QueueManager
│   ├── base.py              # QueueBackend ABC
│   ├── memory.py            # MemoryQueueBackend
│   └── redis_backend.py     # RedisQueueBackend
│
├── hooks/                   # Layer 4: Hooks
│   ├── executor.py          # HookExecutor — execution engine
│   ├── registry.py          # HookRegistry — central management
│   └── types.py             # Hook types, protocols
│
├── output/                  # Layer 4: Output Formatters
│   ├── json.py              # JsonOutputFormatter
│   ├── markdown.py          # MarkdownOutputFormatter
│   ├── html.py              # HtmlOutputFormatter, HtmlSanitizer
│   └── screenshot.py        # ScreenshotHandler
│
├── utils/                   # Layer 4: Utilities
│   ├── crypto.py            # Encryption, hashing, tokens
│   ├── html.py              # HTML utilities
│   ├── logging.py           # Structured logging
│   ├── retry.py             # Retry, circuit breaker, rate limiter
│   ├── text.py              # Text processing
│   └── url.py               # URL utilities
│
├── server/                  # REST API Server
│   ├── app.py               # FastAPI application
│   ├── routes/              # API route handlers
│   ├── middleware.py         # Auth, rate limiting, logging
│   ├── schemas.py           # Pydantic request/response models
│   └── websocket.py         # WebSocket for real-time updates
│
└── cli/                     # CLI
    └── main.py              # Typer CLI commands
```

---

## Core Engine

### CrawlEngine

The `CrawlEngine` is the single entry point for all operations. It:

1. **Manages lifecycle** — starts/stops browser, cache, and tools
2. **Coordinates pipeline** — runs the fetch → parse → extract → output pipeline
3. **Provides operations** — `scrape()`, `crawl()`, `search()`, `map()`, `batch_scrape()`, `extract()`
4. **Tracks statistics** — cumulative metrics across all operations

```
CrawlEngine
├── BrowserManager (browser lifecycle)
├── CacheManager (cache read/write)
├── HTMLToMarkdown (content conversion)
├── CitationExtractor (citation detection)
└── EngineStats (metrics)
```

### Pipeline

The `Pipeline` class provides a composable, stage-based processing model:

- Each `PipelineStage` receives a shared `PipelineContext`
- Stages execute sequentially with timing and error handling
- Stages can be conditionally skipped via `should_skip()`
- Pre-built pipelines: `scrape_pipeline()`, `rag_pipeline()`, `extract_pipeline()`

### CrawlSession

Sessions maintain state across multiple requests:

- Dedicated browser context per session
- Cookie and localStorage persistence
- Visit history tracking
- Session serialization to disk
- TTL-based expiry

---

## Browser Layer

### BrowserManager

Manages Playwright browser instances with context pooling:

```
BrowserManager
├── Browser instance (Chromium/Firefox/WebKit)
├── Context pool (reusable browser contexts)
├── Page pool (reusable pages within contexts)
├── StealthConfig (anti-detection patches)
├── ProxyConfig (proxy rotation)
└── BrowserFingerprint (randomized fingerprints)
```

**Key design decisions:**
- Contexts are reused across requests to reduce overhead
- Pages are acquired/released via a semaphore-based pool
- Stealth patches are applied at context creation time
- Fingerprints are randomized per context

### Page Actions

Actions execute sequentially on a page before content extraction:

```
click → type → scroll → wait → screenshot → evaluate
```

Each action has a timeout and error handling. Actions can be conditional based on element visibility.

---

## Content Processing Layer

### HTML Processing Pipeline

```
Raw HTML
    │
    ▼
HTMLParser (lxml)
├── get_main_content()    → ContentBlock (cleaned HTML + text)
├── get_metadata()        → PageMetadata
├── get_links()           → {internal, external, all}
├── get_headings()        → [Heading]
└── get_tables()          → [TableData]
    │
    ▼
HTMLToMarkdown
├── Headings (h1-h6 → # through ######)
├── Paragraphs, lists, blockquotes
├── Tables (GFM format)
├── Code blocks (fenced with language)
├── Links (preserved or stripped)
└── Images (preserved or stripped)
    │
    ▼
Content Filter (optional)
├── PruningContentFilter  → Remove low-density blocks
└── BM25ContentFilter     → Score by query relevance
    │
    ▼
Chunker (optional)
├── TopicChunker      → Split by headings + token limit
├── SentenceChunker   → Split by sentences
├── RegexChunker      → Split by regex pattern
└── FixedChunker      → Fixed-size chunks
    │
    ▼
CitationExtractor (optional)
└── Detect [1], [2], etc. → Citation objects
```

---

## Extraction Layer

### Strategy Pattern

All extractors implement `ExtractionStrategy`:

```python
class ExtractionStrategy(ABC):
    async def extract(html, markdown, url) → ExtractionResult
    async def _extract(html, markdown, url) → Any  # Subclass implements
```

The base class provides:
- Schema resolution (Pydantic → JSON Schema)
- Retry logic with exponential backoff
- Timeout handling
- Output parsing (JSON from LLM responses)
- Validation against schema

### Extractor Comparison

| Extractor | Speed | Cost | Accuracy | Use Case |
|-----------|-------|------|----------|----------|
| `LLMExtractor` | Slow | $$$ | High | Any schema, unstructured |
| `JsonCssExtractor` | Fast | Free | High | Known HTML structure |
| `JsonXPathExtractor` | Fast | Free | High | Complex HTML queries |
| `CosineExtractor` | Medium | Free | Medium | Repeated item patterns |
| `RegexExtractor` | Fast | Free | Medium | Text patterns |
| `TableExtractor` | Fast | Free | High | HTML tables |

---

## Crawling Layer

### Strategy Hierarchy

```
CrawlStrategy (ABC)
├── BFSCrawler          — FIFO queue, level-by-level
├── DFSCrawler          — LIFO stack, deep-first
├── BestFirstCrawler    — Max-heap, score-based
├── AdaptiveCrawler     — Pattern learning + similarity dedup
└── SinglePageCrawler   — No recursion
```

All strategies share:
- `URLFilter` — include/exclude patterns, domain restriction
- `URLScorer` — relevance scoring for prioritization
- `CrawlConfig` — depth, page limits, concurrency
- `CrawlProgress` — real-time progress tracking

### Adaptive Crawler Algorithm

```
Phase 1: Discovery
    Fetch start URL → extract links → initial candidates

Phase 2: Pattern Learning
    Analyze URL patterns → classify (content/nav/pagination)
    Score patterns by predicted value

Phase 3: Adaptive Exploration
    Explore high-value patterns first
    Skip navigation/pagination patterns
    Content deduplication via SimHash

Phase 4: Result
    Return URLs sorted by priority score
```

---

## Search Layer

### Provider Architecture

```
SearchEngine
├── DuckDuckGoProvider  — HTML scraping (no API key)
├── GoogleSearchProvider — Custom Search API / SerpAPI / scraping
├── BraveProvider       — Brave Search API
├── TavilyProvider      — Tavily API (AI-optimized)
├── ExaProvider         — Exa API (neural search)
└── SearXNGProvider     — Self-hosted metasearch
```

All providers return `SearchResult` objects with `url`, `title`, `snippet`, `position`, `score`.

---

## Cache Layer

### Backend Architecture

```
CacheManager
├── CacheKeyGenerator   — URL → cache key (SHA-256)
├── MemoryCacheBackend  — In-process dict with TTL
├── RedisCacheBackend   — Redis with TTL
├── DiskCacheBackend    — File-based with SQLite index
└── NullCacheBackend    — No-op (disabled)
```

Cache keys are generated from:
- Normalized URL
- Output format
- Content filter settings
- Chunker settings
- Custom suffix

---

## Hooks Layer

### Event System

```
HookExecutor
├── HookEvent enum (16 events)
├── HookRegistration (callback, priority, condition, timeout)
├── HookContext (shared mutable state)
└── HookStats (execution metrics)

HookRegistry
├── Global singleton
├── Per-engine registries
├── Group management (enable/disable)
├── Auto-discovery from modules
└── Built-in hooks (logging, timing, error)
```

### Hook Execution Flow

```
Pipeline Stage
    │
    ▼
executor.execute(event, ctx)
    │
    ├── For each hook (sorted by priority):
    │   ├── Check enabled
    │   ├── Check condition(ctx)
    │   ├── Execute callback(ctx) with timeout
    │   └── Handle error (continue or abort)
    │
    ▼
Return modified ctx
```

---

## Output Layer

### Formatter Architecture

```
CrawlResult
    │
    ├── JsonOutputFormatter    → JSON / JSONL string
    ├── MarkdownOutputFormatter → Markdown with front matter
    ├── HtmlOutputFormatter    → Sanitized HTML / PDF
    └── ScreenshotHandler      → PNG / JPEG / comparison
```

---

## Configuration System

### Hierarchy

```
Environment Variables (.env)
    │
    ▼
Settings (Pydantic BaseSettings)
    │
    ├── to_browser_config() → BrowserConfig
    ├── to_cache_config()   → CacheConfig
    ├── to_queue_config()   → QueueConfig
    └── llm                 → LLMConfig
    │
    ▼
CrawlerConfig (per-request)
    ├── output_format
    ├── actions
    ├── content_filter
    ├── chunker
    ├── extraction
    └── cache settings
```

### Resolution Order

1. Per-request `CrawlerConfig` (highest priority)
2. Global `Settings`
3. Environment variables
4. Default values (lowest priority)

---

## Server Mode

### Request Flow

```
HTTP Request
    │
    ▼
FastAPI Middleware
├── Auth (API key validation)
├── Rate limiting
├── Request logging
└── CORS
    │
    ▼
Route Handler
├── Parse request (Pydantic model)
├── Build CrawlerConfig
└── Call CrawlEngine
    │
    ▼
CrawlEngine Pipeline
    │
    ▼
Response (JSON)
```

### Async Job Flow (Crawl)

```
POST /crawl
    │
    ▼
Create job → QueueManager.enqueue()
    │
    ▼
Return {job_id, status: "queued"}
    │
    ▼ (background worker)
Worker picks up job
    │
    ▼
CrawlEngine.crawl()
    │
    ▼
Update job status → completed/failed
    │
    ▼
GET /crawl/{job_id} → results
```

---

## Design Decisions

### 1. Async-First

All I/O operations are async (`asyncio`). This enables:
- Concurrent page fetches within a crawl
- Non-blocking cache operations
- Efficient batch processing
- WebSocket streaming

### 2. Lazy Imports

The root `__init__.py` uses `__getattr__` for lazy loading:
- `import agentcrawl` is fast (~50ms)
- Heavy modules (Playwright, lxml) load on first use
- Users only pay for what they use

### 3. Strategy Pattern Everywhere

All pluggable behaviors use ABCs:
- `CrawlStrategy` → BFS, DFS, BestFirst, Adaptive
- `ExtractionStrategy` → LLM, CSS, XPath, Cosine, Regex
- `CacheBackend` → Memory, Redis, Disk
- `QueueBackend` → Memory, Redis
- `PipelineStage` → Fetch, Parse, Convert, Filter, Chunk

### 4. Pipeline Context

A single mutable `PipelineContext` flows through all stages:
- Avoids copying large HTML/Markdown strings
- Stages can share data without coupling
- Easy to add new stages without changing existing ones

### 5. Configuration Cascade

Three levels of configuration:
- `Settings` — global, from environment
- `BrowserConfig` / `LLMConfig` — subsystem-specific
- `CrawlerConfig` — per-request override

### 6. No Global State

- `CrawlEngine` instances are self-contained
- `HookRegistry.global_registry()` is the only singleton
- Browser contexts are pooled per-engine, not globally

---

## Extension Points

### Adding a New Crawl Strategy

```python
from agentcrawl.crawling.base import CrawlStrategy, DiscoveredURL

class MyCrawler(CrawlStrategy):
    strategy_name = "my_strategy"

    async def _discover_urls(self, url, engine):
        # Custom discovery logic
        return [DiscoveredURL(url="...", depth=1)]
```

### Adding a New Extraction Strategy

```python
from agentcrawl.extraction.base import ExtractionStrategy

class MyExtractor(ExtractionStrategy):
    method_name = "my_method"

    async def _extract(self, html, markdown, url):
        # Custom extraction logic
        return {"field": "value"}
```

### Adding a New Pipeline Stage

```python
from agentcrawl.core.pipeline import PipelineStage, PipelineContext

class MyStage(PipelineStage):
    @property
    def name(self):
        return "my_stage"

    async def _execute(self, ctx: PipelineContext):
        # Transform ctx
        ctx.extra["my_data"] = "..."

    def should_skip(self, ctx):
        return not ctx.config.enable_my_feature
```

### Adding a New Cache Backend

```python
from agentcrawl.cache.base import CacheBackend

class MyCacheBackend(CacheBackend):
    async def get(self, key, default=None): ...
    async def set(self, key, value, ttl=None): ...
    async def delete(self, key): ...
    async def exists(self, key): ...
    async def clear(self): ...
```

### Adding a New Hook

```python
from agentcrawl.hooks import hook, HookEvent

@hook(event=HookEvent.POST_SCRAPE, group="analytics", priority=50)
async def track_metrics(ctx):
    analytics.track("scrape", url=ctx.url, duration=ctx.elapsed_ms)
```

### Adding a New Search Provider

```python
from agentcrawl.search.engine import SearchProvider, SearchResult

class MySearchProvider(SearchProvider):
    name = "my_search"

    async def search(self, query, max_results=10, **kwargs):
        # Custom search logic
        return [SearchResult(url="...", title="...", snippet="...")]
```

---

## Performance

### Browser Pooling

- Browser contexts are reused across requests (avoids ~500ms startup per context)
- Pages are pooled within contexts (avoids ~100ms per page creation)
- Semaphore limits concurrent pages to prevent memory exhaustion

### Caching Strategy

- Cache check happens before browser fetch (saves ~2-5s per cached page)
- Cache keys include config hash (different configs = different cache entries)
- TTL-based expiry prevents stale content

### Concurrency Model

```
batch_scrape(urls, max_concurrent=5)
    │
    ├── Semaphore(5)
    │   ├── scrape(url_1)
    │   ├── scrape(url_2)
    │   ├── scrape(url_3)
    │   ├── scrape(url_4)
    │   └── scrape(url_5)
    │
    └── asyncio.gather(*tasks)
```

### Memory Management

- Raw HTML is discarded after Markdown conversion
- Screenshots are stored as base64 (not in memory)
- Large crawl results are streamed via JSONL
- Browser contexts are closed after session ends

---

## Security Model

### API Key Encryption

- API keys are encrypted at rest using Fernet (AES-128-CBC + HMAC)
- Encryption key from `ENCRYPTION_KEY` environment variable
- Keys are decrypted only in memory during use

### Input Validation

- All API inputs validated via Pydantic models
- URL validation prevents SSRF (localhost, private IPs)
- HTML sanitization removes scripts and event handlers

### Rate Limiting

- Per-API-key rate limiting via middleware
- Configurable requests per minute
- 429 responses with Retry-After headers

### Proxy Support

- Outbound requests can be routed through proxies
- Proxy credentials encrypted in configuration
- Rotation strategies: round-robin, random, least-used

---

## Deployment

### Single Instance

```
┌─────────────────────────────────────┐
│           AgentCrawl Server         │
│  ┌─────────┐  ┌──────────────────┐  │
│  │ FastAPI │  │  CrawlEngine     │  │
│  │(uvicorn)│──│  (BrowserManager)│  │
│  └─────────┘  └──────────────────┘  │
│  ┌─────────┐  ┌──────────────────┐  │
│  │  Cache  │  │  Queue (memory)  │  │
│  │ (memory)│  │                  │  │
│  └─────────┘  └──────────────────┘  │
└─────────────────────────────────────┘
```

### Production (Docker Compose)

```
┌──────────┐     ┌──────────────────────────────────┐
│  Nginx   │────▶│  AgentCrawl Server (×N workers)  │
│  (proxy) │     │  ┌────────┐  ┌────────────────┐  │
└──────────┘     │  │FastAPI │  │  CrawlEngine   │  │
                 │  └────────┘  └────────────────┘  │
                 └──────────┬───────────────────────┘
                            │
                 ┌──────────▼──────────┐
                 │       Redis         │
                 │  (cache + queue)    │
                 └─────────────────────┘
```

### Kubernetes

```
┌────────────────────────────────────────────┐
│             Kubernetes Cluster             │
│                                            │
│  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Ingress    │  │  AgentCrawl Pods    │  │
│  │  (nginx)    │──│  (Deployment ×3)    │  │
│  └─────────────┘  └──────────┬──────────┘  │
│                              │             │
│  ┌─────────────┐  ┌──────────▼──────────┐  │
│  │  ConfigMap  │  │  Redis (StatefulSet)│  │
│  │  (settings) │  │  (cache + queue)    │  │
│  └─────────────┘  └─────────────────────┘  │
│                                            │
│  ┌─────────────┐                           │
│  │  Secret     │                           │
│  │  (API keys) │                           │
│  └─────────────┘                           │
└────────────────────────────────────────────┘
```

---

*AgentCrawl v1.0.0 — Architecture Document*