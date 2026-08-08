# 🕷️ AgentCrawl

**AI-Ready Web Crawler & Scraper — Use as a Python Package or a Standalone API Server.**

AgentCrawl converts any URL into clean, LLM-optimized Markdown or structured JSON. It combines the API-first design of Firecrawl with the Python-native flexibility of Crawl4AI into a single unified engine.

[![CI](https://github.com/0n6k4v-Coder/agentcrawl/actions/workflows/ci.yml/badge.svg)](https://github.com/0n6k4v-Coder/agentcrawl/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.40+-2EAD33.svg)](https://playwright.dev/)
[![Coverage](https://img.shields.io/badge/coverage-49.92%25-yellow.svg)](https://github.com/0n6k4v-Coder/agentcrawl/actions/workflows/ci.yml)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🐍 **Package Mode** | `pip install agentcrawl` — import directly in your Python code |
| 🌐 **Server Mode** | Run as a FastAPI microservice with auth, rate limiting, and job queue |
| 🎭 **Stealth Browser** | Playwright-based with anti-bot evasion and fingerprint spoofing |
| 📝 **LLM-Ready Output** | Clean Markdown, Fit Markdown, structured JSON, citations |
| 🔍 **Web Search** | Search the web and scrape results in one call |
| 🕸️ **Deep Crawling** | BFS, DFS, BestFirst, and Adaptive crawling strategies |
| 📊 **Extraction Strategies** | LLM, CSS, XPath, Cosine, Regex, BM25 — no LLM cost required |
| 🧩 **RAG Chunking** | Topic-based, regex, and sentence-level chunking for vector stores |
| 🪝 **Hooks System** | 8 hook points to customize every stage of the crawl pipeline |
| 🔐 **Auth & Rate Limiting** | API Key + JWT authentication with configurable rate limits |
| 📦 **Queue System** | In-memory (dev) or Redis (production) job queue |
| 🤖 **Agent Integration** | LangChain, CrewAI, OpenAI Function Calling, and MCP support |
| 💾 **Caching** | Memory, Redis, or disk-based caching with TTL |
| 🖥️ **Multi-Browser** | Chromium, Firefox, WebKit via Playwright |
| 🔄 **Proxy Rotation** | Built-in proxy management with authentication |
| 📸 **Screenshots** | Full-page and viewport screenshots |
| 📄 **Media Parsing** | PDF and DOCX content extraction |

---

## 🚀 Quick Start

### Installation

```bash
# Core package
pip install agentcrawl

# With all optional dependencies (LLM, Redis, search)
pip install "agentcrawl[all]"

# Install Playwright browsers
agentcrawl install-browsers
```

### Package Mode — Scrape a Page

```python
import asyncio
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig

async def main():
    async with Crawler(browser_config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.scrape(
            url="https://example.com/article",
            config=CrawlerConfig(output_format="markdown"),
        )
        print(result.markdown)

asyncio.run(main())
```

### Package Mode — Deep Crawl a Website

```python
import asyncio
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig
from agentcrawl.crawling import BFSCrawler, URLFilter

async def main():
    async with Crawler(browser_config=BrowserConfig(headless=True)) as crawler:
        results = await crawler.crawl(
            url="https://docs.example.com",
            strategy=BFSCrawler(
                max_depth=3,
                max_pages=100,
                url_filter=URLFilter(
                    include_patterns=["/docs/*"],
                    exclude_patterns=["/blog/*"],
                ),
            ),
            config=CrawlerConfig(output_format="markdown"),
        )
        for page in results:
            print(f"{page.url} → {len(page.markdown)} chars")

asyncio.run(main())
```

### Package Mode — LLM-Powered Extraction

```python
import asyncio
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig
from agentcrawl.extraction import LLMExtractor
from agentcrawl.config import LLMConfig
from pydantic import BaseModel, Field

class Product(BaseModel):
    name: str = Field(description="Product name")
    price: float = Field(description="Price in USD")
    rating: float = Field(description="Rating out of 5")

async def main():
    async with Crawler(browser_config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.scrape(
            url="https://shop.example.com/product/123",
            config=CrawlerConfig(
                extraction=LLMExtractor(
                    schema=Product,
                    llm_config=LLMConfig(provider="openai/gpt-4o-mini"),
                ),
            ),
        )
        product = result.extracted_data
        print(f"{product.name}: ${product.price} ({product.rating}⭐)")

asyncio.run(main())
```

### Package Mode — CSS Extraction (No LLM Cost)

```python
import asyncio
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig
from agentcrawl.extraction import JsonCssExtractor

schema = {
    "baseSelector": "article.post",
    "fields": [
        {"name": "title", "selector": "h1", "type": "text"},
        {"name": "author", "selector": ".author", "type": "text"},
        {"name": "date", "selector": "time", "type": "attribute", "attribute": "datetime"},
    ],
}

async def main():
    async with Crawler(browser_config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.scrape(
            url="https://blog.example.com",
            config=CrawlerConfig(extraction=JsonCssExtractor(schema=schema)),
        )
        for item in result.extracted_data:
            print(f"{item['title']} by {item['author']}")

asyncio.run(main())
```

### Package Mode — RAG Chunking

```python
import asyncio
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig
from agentcrawl.content import BM25Filter, TopicChunker

async def main():
    async with Crawler(browser_config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.scrape(
            url="https://docs.example.com/long-article",
            config=CrawlerConfig(
                output_format="markdown",
                content_filter=BM25Filter(query="machine learning", threshold=1.5),
                chunker=TopicChunker(max_chunk_size=1000, overlap=200),
            ),
        )
        for i, chunk in enumerate(result.chunks):
            print(f"Chunk {i}: {chunk.text[:80]}... (~{chunk.token_count} tokens)")

asyncio.run(main())
```

### Package Mode — Search + Scrape

```python
import asyncio
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig
from agentcrawl.search import GoogleSearch

async def main():
    async with Crawler(browser_config=BrowserConfig(headless=True)) as crawler:
        results = await crawler.search(
            query="best Python web frameworks 2026",
            search_engine=GoogleSearch(),
            max_results=5,
            config=CrawlerConfig(output_format="markdown"),
        )
        for r in results:
            print(f"🔍 {r.title}: {r.url}")

asyncio.run(main())
```

### Package Mode — Page Interaction (Actions)

```python
import asyncio
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig
from agentcrawl.browser import PageActions

async def main():
    async with Crawler(browser_config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.scrape(
            url="https://app.example.com/dashboard",
            config=CrawlerConfig(
                actions=PageActions([
                    {"type": "wait", "selector": "#dashboard-loaded"},
                    {"type": "click", "selector": "#load-more"},
                    {"type": "scroll", "direction": "down", "amount": 3},
                    {"type": "type", "selector": "#search", "text": "query"},
                    {"type": "wait", "milliseconds": 2000},
                ]),
                output_format="markdown",
            ),
        )
        print(result.markdown)

asyncio.run(main())
```

---

## 🌐 Server Mode

### Run the Server

Server code is NOT in the pip package — it runs from source:

**Option 1: Docker (recommended)**
```bash
git clone https://github.com/0n6k4v-Coder/agentcrawl.git
cd agentcrawl
docker compose up -d
```

**Option 2: Run from source**
```bash
git clone https://github.com/0n6k4v-Coder/agentcrawl.git
cd agentcrawl
pip install -e ".[server]"
python -m server --port 8000
```

**Production mode (Redis queue, JWT auth, rate limiting)**
```bash
python -m server \\
  --port 8000 \\
  --redis-url redis://localhost:6379 \\
  --api-key your-secret-key \\
  --rate-limit 100/minute
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/scrape` | Scrape a single URL |
| `POST` | `/v1/crawl` | Start an async site crawl (returns job ID) |
| `GET` | `/v1/crawl/{job_id}` | Check crawl job status |
| `POST` | `/v1/search` | Search the web and scrape results |
| `POST` | `/v1/map` | Discover all URLs on a website |
| `POST` | `/v1/batch` | Batch scrape multiple URLs |
| `POST` | `/v1/extract` | Structured data extraction |
| `POST` | `/v1/interact` | Interact with a page (click, scroll, type) |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |
| `SSE` | `/mcp/sse` | MCP (Model Context Protocol) endpoint |

### API Usage Example

```bash
# Scrape a page
curl -X POST http://localhost:8000/v1/scrape \
  -H "Authorization: Bearer your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "output_format": "markdown"}'

# Start a crawl job
curl -X POST http://localhost:8000/v1/crawl \
  -H "Authorization: Bearer your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com", "max_depth": 3, "max_pages": 50}'

# Check job status
curl http://localhost:8000/v1/crawl/{job_id} \
  -H "Authorization: Bearer your-secret-key"

# Search
curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "Python asyncio tutorial", "max_results": 5}'
```

### Python Client for Server Mode

```python
import httpx
import asyncio

async def main():
    base_url = "http://localhost:8000"
    headers = {"Authorization": "Bearer your-secret-key"}

    async with httpx.AsyncClient() as client:
        # Scrape
        resp = await client.post(
            f"{base_url}/v1/scrape",
            headers=headers,
            json={"url": "https://example.com", "output_format": "markdown"},
        )
        print(resp.json()["markdown"][:200])

        # Crawl (async job)
        resp = await client.post(
            f"{base_url}/v1/crawl",
            headers=headers,
            json={"url": "https://docs.example.com", "max_depth": 2},
        )
        job_id = resp.json()["job_id"]

        # Poll status
        resp = await client.get(f"{base_url}/v1/crawl/{job_id}", headers=headers)
        print(resp.json()["status"])

asyncio.run(main())
```

---

## 🤖 AI Agent Integration

### LangChain Tool

```python
from agentcrawl.agent import AgentCrawlTool
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI

tools = [AgentCrawlTool()]
llm = ChatOpenAI(model="gpt-4o")

agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
)

response = agent.invoke("Read https://docs.python.org/3/tutorial/ and summarize it")
```

### OpenAI Function Calling

```python
from agentcrawl.agent import get_openai_tools_schema

tools = get_openai_tools_schema()  # Returns OpenAI-compatible function definitions

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Scrape https://example.com"}],
    tools=tools,
    tool_choice="auto",
)
```

### MCP (Model Context Protocol)

```bash
# Start server with MCP enabled
python -m server --port 8000 --mcp

# Connect from Claude Code
claude mcp add --transport sse agentcrawl http://localhost:8000/mcp/sse
```

### Custom Agent Harness

```python
from agentcrawl import Crawler, BrowserConfig, CrawlerConfig

class MyAgent:
    def __init__(self):
        self.crawler = Crawler(browser_config=BrowserConfig(headless=True, stealth=True))

    async def tool_web_scrape(self, url: str) -> str:
        result = await self.crawler.scrape(url=url, config=CrawlerConfig(output_format="markdown"))
        return result.markdown

    async def tool_web_search(self, query: str) -> list:
        results = await self.crawler.search(query=query, max_results=5)
        return [{"title": r.title, "url": r.url, "content": r.markdown[:300]} for r in results]
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      USAGE LAYER                            │
│   Package Mode (Python)  │  Server Mode (FastAPI)  │  MCP   │
└──────────────────────────┼─────────────────────────┼────────┘
                           │                         │
┌──────────────────────────┴─────────────────────────┴────────┐
│                      CORE ENGINE                            │
│              (CrawlEngine — shared by all modes)            │
│                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │ Browser  │ │Extraction│ │ Content  │ │  Crawling    │    │
│  │ Layer    │ │ Layer    │ │ Layer    │ │  Layer       │    │
│  │Playwright│ │Markdown  │ │HTML Parse│ │BFS/DFS/      │    │
│  │Pool      │ │JSON/CSS  │ │BM25      │ │BestFirst/    │    │
│  │Stealth   │ │LLM/XPath │ │Pruning   │ │Adaptive/     │    │
│  │Actions   │ │Cosine    │ │Chunking  │ │Search/Map    │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                  INFRASTRUCTURE LAYER                       │
│  Config   │  Cache (Memory/Redis/Disk)  │  Queue  │  Hooks  │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
agentcrawl/
├── agentcrawl/              # Core Python package
│   ├── core/                # Engine, pipeline, session, types
│   ├── browser/             # Playwright manager, pool, stealth, actions, proxy
│   ├── extraction/          # Markdown, JSON/CSS, JSON/XPath, LLM, Cosine, Regex
│   ├── content/             # HTML parser, filters (BM25, Pruning), chunkers
│   ├── crawling/            # BFS, DFS, BestFirst, Adaptive, DomainMapper
│   ├── search/              # Google, SearXNG search engines
│   ├── config/              # Settings, CrawlerConfig, BrowserConfig, LLMConfig
│   ├── cache/               # Memory, Redis, Disk cache backends
│   ├── hooks/               # Hook registry and executor
│   ├── output/              # Markdown, JSON, HTML, Screenshot formatters
│   └── utils/               # URL, HTML, text, retry, logging utilities
├── server/                  # FastAPI server (Server Mode)
│   ├── api/v1/              # REST endpoints (scrape, crawl, search, map, batch)
│   ├── auth/                # API Key, JWT, rate limiter
│   ├── queue/               # In-memory and Redis queue backends
│   ├── schemas/             # Request/response Pydantic models
│   ├── mcp/                 # MCP server (SSE + WebSocket)
│   └── monitoring/          # Health, metrics, logging
├── agent/                   # AI Agent integration (LangChain, OpenAI FC, MCP)
├── tests/                   # Unit and integration tests
├── examples/                # Usage examples for all modes
├── docs/                    # Documentation
└── scripts/                 # Dev scripts (install browsers, benchmark)
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTCRAWL_HEADLESS` | `true` | Run browser in headless mode |
| `AGENTCRAWL_STEALTH` | `true` | Enable stealth/anti-bot mode |
| `AGENTCRAWL_BROWSER` | `chromium` | Browser: `chromium`, `firefox`, `webkit` |
| `AGENTCRAWL_PROXY_URL` | — | Proxy server URL |
| `AGENTCRAWL_CACHE_BACKEND` | `memory` | Cache: `memory`, `redis`, `disk` |
| `AGENTCRAWL_REDIS_URL` | — | Redis connection URL |
| `AGENTCRAWL_AUTH_ENABLED` | `false` | Enable API authentication (server mode) |
| `AGENTCRAWL_API_KEY` | — | API key for authentication |
| `AGENTCRAWL_JWT_SECRET` | — | JWT secret for token auth |
| `AGENTCRAWL_RATE_LIMIT` | `100/minute` | Rate limit (server mode) |
| `AGENTCRAWL_QUEUE_BACKEND` | `memory` | Queue: `memory`, `redis` |
| `AGENTCRAWL_MAX_CONCURRENT` | `5` | Max concurrent browser pages |
| `AGENTCRAWL_TIMEOUT` | `30` | Page load timeout (seconds) |
| `OPENAI_API_KEY` | — | OpenAI API key (for LLM extraction) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (for LLM extraction) |

### YAML Configuration

```yaml
# agentcrawl.yml
browser:
  headless: true
  stealth: true
  browser_type: chromium
  max_concurrent_pages: 5
  timeout: 30000

cache:
  backend: redis
  redis_url: redis://localhost:6379
  ttl: 3600

server:
  host: 0.0.0.0
  port: 8000
  auth_enabled: true
  api_key: ${AGENTCRAWL_API_KEY}
  rate_limit: "100/minute"
  queue_backend: redis

llm:
  provider: openai/gpt-4o-mini
  temperature: 0.1
```

---

## 🐳 Docker Deployment

```yaml
# docker-compose.yml
version: "3.8"

services:
  agentcrawl:
    build: .
    ports:
      - "8000:8000"
    environment:
      - AGENTCRAWL_AUTH_ENABLED=true
      - AGENTCRAWL_API_KEY=${API_KEY}
      - AGENTCRAWL_QUEUE_BACKEND=redis
      - AGENTCRAWL_REDIS_URL=redis://redis:6379
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - redis
    shm_size: "1g"
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

```bash
docker compose up -d
```

---

## 🧪 Running Tests

```bash
# Unit tests (no browser needed)
pytest tests/unit/ -v

# Integration tests (requires Playwright + network)
playwright install chromium
playwright install-deps chromium  # Linux only, needs sudo
pytest tests/integration/ -v --run-integration

# All tests
pytest tests/ -v --run-integration

# Or use Makefile
make test          # unit only
make test-all      # unit + integration
```

### CI Configuration

GitHub Actions runs tests on Python 3.11, 3.12, 3.13 with Playwright Chromium pre-installed. See `.github/workflows/ci.yml`.

---

## 📊 Performance

| Metric | AgentCrawl | Firecrawl (self-hosted) | Crawl4AI |
|--------|-----------|------------------------|----------|
| Single page scrape (P50) | ~1.2s | ~2.1s | ~1.5s |
| Single page scrape (P95) | ~2.8s | ~3.4s | ~3.1s |
| Markdown conversion | markdownify | Go service | Python html2text |
| Concurrent pages | 5 (configurable) | 1 per container | 5 (pool) |
| Memory (idle) | ~150 MB | ~400 MB (5 containers) | ~200 MB |
| Docker image size | ~600 MB | ~1.2 GB (all services) | ~800 MB |

*Disclaimer: Performance benchmarks are measured in internal controlled test environments. Actual results may vary depending on hardware specs, network bandwidth, target website responsiveness, and configuration settings.*

---

## 🛣️ Roadmap

- [x] v1.0 — Core engine, Package Mode, Server Mode, basic extraction
- [x] v1.1 — LLM extraction, deep crawling, RAG chunking
- [x] v1.2 — Search integration, MCP server, agent tools
- [ ] v1.3 — Rust-accelerated HTML-to-Markdown (PyO3)
- [ ] v1.4 — Distributed crawling (multi-worker), ClickHouse analytics
- [ ] v2.0 — Visual crawler builder, browser extension, managed cloud

---

## 🤝 Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) before submitting a PR.

```bash
# Dev setup
git clone https://github.com/0n6k4v-Coder/agentcrawl.git
cd agentcrawl
pip install -e ".[dev,all]"
agentcrawl install-browsers
```

---

## 🛠️ Development Workflow

### Setup (One-time)

```bash
# Clone repository
git clone https://github.com/0n6k4v-Coder/agentcrawl.git
cd agentcrawl

# Install dependencies + Playwright
make setup

# Install pre-commit hooks (recommended)
make pre-commit-setup
```

### Before Committing

**Option 1: Pre-commit hooks (automatic, recommended)**

If you installed pre-commit hooks, every `git commit` auto-checks:

```bash
git add agentcrawl/core.py
git commit -m "feat: add feature"
# → pre-commit auto-runs: ruff check, ruff format
# → if pass → commit success
# → if fail → fix → commit again
```

**Option 2: Manual check**

```bash
make quick-lint
# → runs ruff check + ruff format --check
# → if pass → safe to commit
```

### Before Pushing

```bash
make pre-push
# → runs gacils (local CI simulation, 30-60s)
# → if pass → safe to push

git push origin main
# → GitHub Actions CI should pass (already checked locally)
```

### IDE Setup (Recommended)

**VSCode:**

Install extensions:
- Ruff (charliermarsh.ruff)
- Python (ms-python.python)

Add to `.vscode/settings.json`:

```json
{
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.codeActionsOnSave": {
      "source.fixAll": true,
      "source.organizeImports": true
    }
  }
}
```

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

---

## 🙏 Acknowledgments

- [Firecrawl](https://github.com/firecrawl/firecrawl) — Inspiration for API-first design, search, actions, and queue architecture
- [Crawl4AI](https://github.com/unclecode/crawl4ai) — Inspiration for Python-native design, extraction strategies, deep crawling, and RAG chunking
- [Playwright](https://playwright.dev/) — Browser automation engine
- [FastAPI](https://fastapi.tiangolo.com/) — Server framework

---

## 📞 Support

- **Issues:** [GitHub Issues](https://github.com/0n6k4v-Coder/agentcrawl/issues)
- **Discussions:** [GitHub Discussions](https://github.com/0n6k4v-Coder/agentcrawl/discussions)
- **Documentation:** [docs.agentcrawl.dev](https://docs.agentcrawl.dev)

---

<p align="center">
  <sub>Built for AI Agents. Optimized for LLMs. Designed for Developers.</sub>
</p>