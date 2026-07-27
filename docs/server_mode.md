# Server Mode Guide

Run AgentCrawl as a standalone REST API server for language-agnostic access, microservice architectures, and AI agent tool integration.

---

## Table of Contents

- [Starting the Server](#starting-the-server)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
- [Scrape API](#scrape-api)
- [Crawl API](#crawl-api)
- [Map API](#map-api)
- [Search API](#search-api)
- [Extract API](#extract-api)
- [Batch API](#batch-api)
- [Health Check](#health-check)
- [WebSocket](#websocket)
- [Error Handling](#error-handling)
- [Rate Limiting](#rate-limiting)
- [Configuration](#configuration)
- [Docker Deployment](#docker-deployment)
- [Client Examples](#client-examples)

---

## Starting the Server

### CLI

```bash
# Default (port 8000)
agentcrawl serve

# Custom port
agentcrawl serve --port 9000

# With workers
agentcrawl serve --workers 4

# With API key auth
agentcrawl serve --api-key "your-secret-key"

# Full options
agentcrawl serve \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 2 \
  --api-key "your-secret-key" \
  --log-level info
```

### Uvicorn

```bash
uvicorn agentcrawl.server.app:app --host 0.0.0.0 --port 8000
```

### Python

```python
import uvicorn
from agentcrawl.server.app import create_app

app = create_app()
uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Verify

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 120,
  "browser_connected": true,
  "cache_backend": "memory"
}
```

---

## Authentication

### API Key

Set via CLI or environment variable:

```bash
# CLI
agentcrawl serve --api-key "your-secret-key"

# Environment
export AGENTCRAWL_API_KEY="your-secret-key"
agentcrawl serve
```

Include in requests:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Authorization: Bearer your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Or via query parameter:

```bash
curl "http://localhost:8000/health?api_key=your-secret-key"
```

### No Auth (Development)

If no API key is configured, all endpoints are open. **Do not run without auth in production.**

---

## Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/` | API info | No |
| `GET` | `/health` | Health check | No |
| `POST` | `/scrape` | Scrape a single page | Yes |
| `POST` | `/crawl` | Start a crawl job | Yes |
| `GET` | `/crawl/{job_id}` | Get crawl job status | Yes |
| `DELETE` | `/crawl/{job_id}` | Cancel a crawl job | Yes |
| `POST` | `/map` | Discover URLs | Yes |
| `POST` | `/search` | Web search | Yes |
| `POST` | `/extract` | Structured extraction | Yes |
| `POST` | `/batch/scrape` | Batch scrape | Yes |
| `WS` | `/ws/crawl/{job_id}` | Real-time crawl updates | Yes |

---

## Scrape API

### `POST /scrape`

Scrape a single page and return processed content.

**Request:**

```json
{
  "url": "https://example.com",
  "output_format": "markdown",
  "include_links": true,
  "include_metadata": true,
  "include_screenshot": false,
  "include_citations": false,
  "only_main_content": true,
  "selectors": ["article", ".content"],
  "exclude_selectors": ["nav", "footer"],
  "actions": [
    {"type": "click", "selector": "#accept-cookies"},
    {"type": "scroll", "direction": "down", "amount": 3},
    {"type": "wait", "milliseconds": 1000}
  ],
  "content_filter": "pruning",
  "content_filter_query": "",
  "chunker": "topic",
  "chunk_max_size": 1000,
  "chunk_overlap": 200,
  "cache": true,
  "cache_ttl": 3600,
  "timeout": 30
}
```

**Response (200):**

```json
{
  "url": "https://example.com",
  "success": true,
  "status_code": 200,
  "markdown": "# Example Domain\n\nThis domain is for use in...",
  "html": "<h1>Example Domain</h1><p>This domain...</p>",
  "text": "Example Domain This domain is for use in...",
  "metadata": {
    "title": "Example Domain",
    "description": "This domain is for use in illustrative examples",
    "og_title": "Example Domain",
    "og_url": "https://example.com"
  },
  "links": {
    "internal": [
      {"url": "https://example.com/page", "text": "More info"}
    ],
    "external": [
      {"url": "https://www.iana.org/domains/example", "text": "IANA"}
    ],
    "all": []
  },
  "citations": [],
  "chunks": [
    {
      "index": 0,
      "heading": "Example Domain",
      "text": "This domain is for use in...",
      "token_count": 45
    }
  ],
  "screenshot": null,
  "word_count": 125,
  "token_count": 165,
  "response_time_ms": 2340.5,
  "cached": false,
  "request_id": "req_a1b2c3d4"
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "output_format": "markdown",
    "only_main_content": true
  }'
```

---

## Crawl API

### `POST /crawl`

Start an asynchronous crawl job.

**Request:**

```json
{
  "url": "https://docs.example.com",
  "strategy": "bfs",
  "max_depth": 3,
  "max_pages": 50,
  "max_concurrent": 5,
  "output_format": "markdown",
  "include_links": true,
  "only_main_content": true,
  "content_filter": "pruning",
  "include_patterns": ["/docs/*"],
  "exclude_patterns": ["/blog/*"]
}
```

**Response (202):**

```json
{
  "job_id": "job_a1b2c3d4",
  "status": "queued",
  "message": "Crawl job queued"
}
```

### `GET /crawl/{job_id}`

Get crawl job status and results.

**Response (200) — In Progress:**

```json
{
  "job_id": "job_a1b2c3d4",
  "status": "running",
  "start_url": "https://docs.example.com",
  "strategy": "bfs",
  "pages_crawled": 15,
  "pages_failed": 1,
  "pages_pending": 34,
  "progress": 0.30,
  "elapsed_ms": 12000
}
```

**Response (200) — Completed:**

```json
{
  "job_id": "job_a1b2c3d4",
  "status": "completed",
  "start_url": "https://docs.example.com",
  "strategy": "bfs",
  "total_pages": 42,
  "successful_pages": 40,
  "failed_pages": 2,
  "total_words": 15000,
  "total_tokens": 20000,
  "duration_ms": 45000,
  "pages": [
    {
      "url": "https://docs.example.com/guide",
      "success": true,
      "markdown": "# Guide\n\n...",
      "word_count": 500
    }
  ]
}
```

### `DELETE /crawl/{job_id}`

Cancel a running crawl job.

**Response (200):**

```json
{
  "job_id": "job_a1b2c3d4",
  "status": "cancelled",
  "pages_crawled": 15
}
```

---

## Map API

### `POST /map`

Discover all URLs on a website without scraping content.

**Request:**

```json
{
  "url": "https://docs.example.com",
  "max_urls": 500,
  "use_sitemap": true,
  "use_robots": true,
  "use_link_crawl": true,
  "include_patterns": ["/docs/*"],
  "exclude_patterns": ["*.pdf"]
}
```

**Response (200):**

```json
{
  "total_urls": 245,
  "sitemap_urls": 200,
  "robots_urls": 5,
  "crawl_urls": 40,
  "sources": ["sitemap", "robots", "crawl"],
  "duration_ms": 3500,
  "urls": [
    "https://docs.example.com/guide",
    "https://docs.example.com/api",
    "https://docs.example.com/tutorial"
  ]
}
```

---

## Search API

### `POST /search`

Search the web and optionally scrape results.

**Request:**

```json
{
  "query": "python asyncio tutorial",
  "max_results": 5,
  "provider": "duckduckgo",
  "scrape_results": false
}
```

**Response (200):**

```json
{
  "query": "python asyncio tutorial",
  "results": [
    {
      "url": "https://docs.python.org/3/library/asyncio.html",
      "title": "asyncio — Asynchronous I/O",
      "snippet": "asyncio is a library to write concurrent code...",
      "position": 1,
      "domain": "docs.python.org"
    }
  ],
  "total_results": 5,
  "provider": "duckduckgo",
  "duration_ms": 1200
}
```

---

## Extract API

### `POST /extract`

Extract structured data from a URL.

**Request:**

```json
{
  "url": "https://shop.example.com/product/1",
  "method": "css",
  "schema": {
    "name": "Product",
    "baseSelector": "div.product",
    "fields": [
      {"name": "title", "selector": "h1", "type": "text"},
      {"name": "price", "selector": ".price", "type": "text"},
      {"name": "description", "selector": ".description", "type": "text"}
    ]
  }
}
```

**Response (200):**

```json
{
  "url": "https://shop.example.com/product/1",
  "success": true,
  "method": "css",
  "data": [
    {
      "title": "Wireless Headphones",
      "price": "$99.99",
      "description": "High-quality wireless headphones..."
    }
  ],
  "duration_ms": 2500
}
```

### LLM Extraction

```json
{
  "url": "https://shop.example.com/product/1",
  "method": "llm",
  "schema": {
    "type": "object",
    "properties": {
      "name": {"type": "string"},
      "price": {"type": "number"},
      "features": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["name", "price"]
  }
}
```

---

## Batch API

### `POST /batch/scrape`

Scrape multiple URLs in one request.

**Request:**

```json
{
  "urls": [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3"
  ],
  "output_format": "markdown",
  "max_concurrent": 5,
  "only_main_content": true
}
```

**Response (200):**

```json
{
  "total": 3,
  "successful": 3,
  "failed": 0,
  "results": [
    {
      "url": "https://example.com/page1",
      "success": true,
      "markdown": "# Page 1\n\n...",
      "word_count": 200
    }
  ],
  "duration_ms": 5000
}
```

---

## Health Check

### `GET /health`

No authentication required.

**Response (200):**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "browser_connected": true,
  "cache_backend": "memory",
  "active_pages": 2,
  "total_scrapes": 150,
  "total_crawls": 5,
  "memory_usage_mb": 256
}
```

### `GET /`

API information.

**Response (200):**

```json
{
  "name": "AgentCrawl",
  "version": "1.0.0",
  "description": "Web Crawling & Scraping Framework for AI Agents",
  "endpoints": [
    "POST /scrape",
    "POST /crawl",
    "GET /crawl/{job_id}",
    "POST /map",
    "POST /search",
    "POST /extract",
    "POST /batch/scrape",
    "GET /health"
  ]
}
```

---

## WebSocket

### `WS /ws/crawl/{job_id}`

Receive real-time updates for a crawl job.

**Connection:**

```javascript
const ws = new WebSocket(
  "ws://localhost:8000/ws/crawl/job_a1b2c3d4?api_key=your-key"
);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`Page crawled: ${data.url} (${data.pages_crawled}/${data.total_pages})`);
};
```

**Messages:**

```json
{"type": "progress", "pages_crawled": 5, "total_pages": 50, "current_url": "..."}
{"type": "page_complete", "url": "...", "success": true, "word_count": 500}
{"type": "page_error", "url": "...", "error": "Timeout"}
{"type": "completed", "total_pages": 42, "duration_ms": 45000}
{"type": "cancelled", "pages_crawled": 15}
```

---

## Error Handling

### Error Response Format

All errors return a consistent JSON structure:

```json
{
  "error": {
    "code": "SCRAPE_FAILED",
    "message": "Page returned status 404",
    "details": {
      "url": "https://example.com/missing",
      "status_code": 404
    },
    "request_id": "req_a1b2c3d4"
  }
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 422 | Invalid request body |
| `UNAUTHORIZED` | 401 | Missing or invalid API key |
| `RATE_LIMITED` | 429 | Too many requests |
| `SCRAPE_FAILED` | 500 | Page scrape failed |
| `TIMEOUT` | 504 | Request timed out |
| `JOB_NOT_FOUND` | 404 | Crawl job not found |
| `BROWSER_ERROR` | 500 | Browser operation failed |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## Rate Limiting

Configure via environment:

```bash
AGENTCRAWL_RATE_LIMIT=100        # Requests per minute
AGENTCRAWL_RATE_LIMIT_BURST=20   # Burst allowance
```

Response headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1705312800
```

When rate limited:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Rate limit exceeded. Retry after 30 seconds.",
    "retry_after": 30
  }
}
```

---

## Configuration

### Environment Variables

```bash
# Server
AGENTCRAWL_HOST=0.0.0.0
AGENTCRAWL_PORT=8000
AGENTCRAWL_WORKERS=4
AGENTCRAWL_API_KEY=your-secret-key

# Browser
AGENTCRAWL_BROWSER_TYPE=chromium
AGENTCRAWL_HEADLESS=true
AGENTCRAWL_STEALTH=true

# Cache
AGENTCRAWL_CACHE_BACKEND=redis
AGENTCRAWL_REDIS_URL=redis://localhost:6379
AGENTCRAWL_CACHE_TTL=3600

# LLM
AGENTCRAWL_LLM_PROVIDER=openai/gpt-4o-mini
OPENAI_API_KEY=sk-...

# Rate Limiting
AGENTCRAWL_RATE_LIMIT=100

# Logging
AGENTCRAWL_LOG_LEVEL=info
```

### Settings File

Create `agentcrawl.yaml`:

```yaml
server:
  host: 0.0.0.0
  port: 8000
  workers: 4
  api_key: your-secret-key

browser:
  type: chromium
  headless: true
  stealth: true

cache:
  backend: redis
  redis_url: redis://localhost:6379
  ttl: 3600

rate_limit:
  requests_per_minute: 100
  burst: 20

logging:
  level: info
  json_format: true
```

```bash
agentcrawl serve --config agentcrawl.yaml
```

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget gnupg2 \
    && rm -rf /var/lib/apt/lists/*

# Install AgentCrawl
RUN pip install "agentcrawl[all]"

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Create non-root user
RUN useradd -m agentcrawl
USER agentcrawl

WORKDIR /app

EXPOSE 8000

CMD ["agentcrawl", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
version: "3.8"

services:
  agentcrawl:
    build: .
    ports:
      - "8000:8000"
    environment:
      - AGENTCRAWL_API_KEY=${API_KEY}
      - AGENTCRAWL_CACHE_BACKEND=redis
      - AGENTCRAWL_REDIS_URL=redis://redis:6379
      - AGENTCRAWL_LOG_LEVEL=info
    depends_on:
      - redis
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G

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

## Client Examples

### Python (httpx)

```python
import httpx

BASE_URL = "http://localhost:8000"
API_KEY = "your-secret-key"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# Scrape
async with httpx.AsyncClient() as client:
    resp = await client.post(
        f"{BASE_URL}/scrape",
        headers=headers,
        json={"url": "https://example.com", "output_format": "markdown"},
    )
    data = resp.json()
    print(data["markdown"])
```

### JavaScript (fetch)

```javascript
const BASE_URL = "http://localhost:8000";
const API_KEY = "your-secret-key";

const response = await fetch(`${BASE_URL}/scrape`, {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    url: "https://example.com",
    output_format: "markdown",
  }),
});

const data = await response.json();
console.log(data.markdown);
```

### cURL

```bash
# Scrape
curl -X POST http://localhost:8000/scrape \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Crawl
curl -X POST http://localhost:8000/crawl \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com", "max_depth": 3}'

# Check job
curl http://localhost:8000/crawl/job_a1b2c3d4 \
  -H "Authorization: Bearer your-key"

# Search
curl -X POST http://localhost:8000/search \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "python tutorial", "max_results": 5}'

# Health
curl http://localhost:8000/health
```

### OpenAI Function Calling

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "scrape_webpage",
            "description": "Scrape a webpage and return clean Markdown content",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to scrape",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

async def handle_tool_call(name, arguments):
    if name == "scrape_webpage":
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/scrape",
                headers=headers,
                json={"url": arguments["url"]},
            )
            return resp.json()["markdown"]

    if name == "search_web":
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/search",
                headers=headers,
                json={"query": arguments["query"]},
            )
            return resp.json()["results"]
```

---

*AgentCrawl v1.0.0 — Server Mode Guide*