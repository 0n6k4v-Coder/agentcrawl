# Quick Start

Get up and running with AgentCrawl in 5 minutes.

---

## Prerequisites

- Python 3.10 or higher
- pip or uv package manager

---

## Step 1: Install

```bash
pip install agentcrawl
playwright install chromium
```

Verify:

```bash
python -c "import agentcrawl; print(agentcrawl.__version__)"
# → 1.0.0
```

---

## Step 2: Your First Scrape

Create `scrape.py`:

```python
import asyncio
from agentcrawl import CrawlEngine

async def main():
    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")

        print(f"Status: {result.status_code}")
        print(f"Words: {result.word_count}")
        print(f"Time: {result.response_time_ms:.0f}ms")
        print()
        print(result.markdown)

asyncio.run(main())
```

Run it:

```bash
python scrape.py
```

Expected output:

```
Status: 200
Words: 125
Time: 2340ms

# Example Domain

This domain is for use in illustrative examples in documents.
You may use this domain in literature without prior coordination
or asking for permission.

[More information...](https://www.iana.org/domains/example)
```

---

## Step 3: Configure Output

```python
from agentcrawl import CrawlEngine, CrawlerConfig

config = CrawlerConfig(
    output_format="markdown",
    include_links=True,
    include_metadata=True,
    only_main_content=True,
)

async with CrawlEngine.default() as engine:
    result = await engine.scrape("https://news.ycombinator.com", config)

    # Markdown content
    print(result.markdown[:500])

    # Metadata
    print(f"\nTitle: {result.metadata.get('title')}")

    # Links
    print(f"\nLinks: {len(result.links.get('all', []))}")
```

---

## Step 4: Crawl a Website

```python
from agentcrawl import CrawlEngine, BFSCrawler

async with CrawlEngine.default() as engine:
    job = await engine.crawl(
        "https://docs.python.org/3/tutorial/",
        strategy=BFSCrawler(max_depth=2, max_pages=10),
    )

    print(f"Crawled {job.total_pages} pages in {job.duration_ms:.0f}ms")
    print(f"Total words: {job.total_words}")

    for page in job.pages[:3]:
        print(f"\n--- {page.url} ---")
        print(page.markdown[:200])
```

---

## Step 5: Extract Structured Data

```python
from agentcrawl import CrawlEngine, JsonCssExtractor

schema = {
    "name": "HN Story",
    "baseSelector": "tr.athing",
    "fields": [
        {"name": "title", "selector": "span.titleline > a", "type": "text"},
        {"name": "url", "selector": "span.titleline > a", "type": "attribute", "attribute": "href"},
        {"name": "rank", "selector": "span.rank", "type": "text"},
    ],
}

async with CrawlEngine.default() as engine:
    result = await engine.scrape("https://news.ycombinator.com")

    extractor = JsonCssExtractor(schema=schema)
    extraction = await extractor.extract(html=result.html)

    for story in extraction.data[:5]:
        print(f"{story['rank']} {story['title']}")
        print(f"   {story['url']}")
```

---

## Step 6: Search the Web

```python
from agentcrawl import SearchEngine

engine = SearchEngine(provider="duckduckgo")
results = await engine.search("python asyncio tutorial", max_results=5)

for r in results:
    print(f"• {r['title']}")
    print(f"  {r['url']}")
```

---

## Step 7: RAG-Ready Chunks

```python
from agentcrawl import CrawlEngine, CrawlerConfig

config = CrawlerConfig(
    content_filter="pruning",
    chunker="topic",
    chunk_max_size=1000,
    chunk_overlap=200,
)

async with CrawlEngine.default() as engine:
    result = await engine.scrape("https://docs.python.org/3/tutorial/controlflow.html", config)

    for chunk in result.chunks:
        print(f"[{chunk['heading']}] {chunk['token_count']} tokens")
        print(chunk["text"][:150])
        print("---")
```

---

## Step 8: REST API Server

Start the server:

```bash
agentcrawl serve --port 8000
```

Scrape via HTTP:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "output_format": "markdown"}'
```

Response:

```json
{
  "url": "https://example.com",
  "success": true,
  "status_code": 200,
  "markdown": "# Example Domain\n\n...",
  "metadata": {"title": "Example Domain"},
  "word_count": 125,
  "response_time_ms": 2340
}
```

---

## One-Liner

```python
import agentcrawl; result = await agentcrawl.scrape("https://example.com"); print(result.markdown)
```

---

## Next Steps

| Topic | Guide |
|-------|-------|
| Full package usage | [Package Mode Guide](package_mode.md) |
| All API options | [API Reference](api_reference.md) |
| Internal design | [Architecture](architecture.md) |
| Configuration | [Configuration Guide](configuration.md) |
| Production setup | [Deployment Guide](deployment.md) |

---

## Common Issues

### Playwright browsers not found

```bash
playwright install chromium
```

### Permission denied on Linux

```bash
playwright install-deps chromium
```

### Timeout errors

Increase the timeout in `CrawlerConfig`:

```python
config = CrawlerConfig(timeout=60)  # 60 seconds
```

### Import errors

Make sure you installed with the right extras:

```bash
pip install "agentcrawl[all]"
```

---

*AgentCrawl v1.0.0 — Quick Start*