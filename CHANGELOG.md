# Changelog

All notable changes to AgentCrawl will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-30

### Added
- **Core Engine & Architecture**: Async-first web scraping and crawling framework (`CrawlEngine`) with support for browser automation, HTTP fetching, session management, and hooks.
- **Scraping & Extraction**:
  - CSS Selector (`JsonCssExtractor`) and XPath (`JsonXPathExtractor`) structured data extraction.
  - LLM-powered extraction (`LLMExtractor`) supporting multiple providers via LiteLLM.
  - Fast HTML-to-Markdown conversion with customizable rules and noise removal.
- **Deep Crawling**: Multi-strategy crawling engine supporting BFS (`BFSCrawler`), DFS (`DFSCrawler`), Best-First (`BestFirstCrawler`), and Adaptive pattern-learning crawler.
- **Content Processing**:
  - Okapi BM25 relevance filtering (`BM25ContentFilter` / `BM25Filter`) for query-focused extraction.
  - Heuristic-based noise pruning (`PruningContentFilter`).
  - RAG-focused document chunkers (`TopicChunker`, `SentenceChunker`, `RegexChunker`, `FixedChunker`).
  - Citation reference extraction and bibliography generator.
- **Search Integration**: Multi-provider web search engine supporting DuckDuckGo, Google, SearXNG, Brave, Tavily, and Exa.
- **REST API & MCP Server**:
  - FastAPI standalone API server (`server/`).
  - Model Context Protocol (MCP) server integration for AI agent ecosystems.
- **Distributed Queue & Caching**: Multi-backend caching system (Memory, Redis, DiskCache) and job queue support.
- **CI/CD & DevOps**: GitHub Actions CI workflow for testing and linting across Python 3.10–3.13, Docker production image, and type marker (`py.typed`).
