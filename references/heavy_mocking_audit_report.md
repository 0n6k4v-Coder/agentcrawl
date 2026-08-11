# Heavy Mocking Audit Report (Issue 10)

## Summary

- **Files with >20 mock usages:** 9
- **Total mock usages across all test files:** 851
- **External dependency mocks (acceptable):** ~19 targeted patches (primarily Playwright/asyncio)
- **Internal component mocks (questionable):** ~832 lines using bare `MagicMock()`/`AsyncMock()` as test doubles for internal classes
- **Bare MagicMock/AsyncMock (not targeted patches):** ~672 — these serve as return values/config objects for the targeted patches, not independent internal mocks

## File Analysis

### tests/unit/test_agent_tool.py (164 mock lines)
- **External dependency mocks:** 0 targeted patches to external deps
- **Internal component mocks:** 32 targeted patches + 73 bare mocks = 105 mock lines (164 total counting all MagicMock/AsyncMock/patch occurrences)
  - `agentcrawl.agent.tool._engine_manager`: 30 patches — mocking the engine manager singleton
  - `agentcrawl.config.settings.Settings`: 1 patch
  - `agentcrawl.core.engine.CrawlEngine`: 1 patch
  - Remaining 61: bare `MagicMock()`/`AsyncMock()` used as return values for mocked engine methods (engine startup, scrape results, page content, etc.)
- **Classification:** QUESTIONABLE
- **Recommendation:** The 30 patches on `_engine_manager` and bare mocks that mock `engine.scrape()`, `engine.crawl()`, etc. are mocking the internal CrawlEngine orchestrator. This creates tight coupling between tests and internal implementation. Since CrawlEngine wraps Playwright (external), the mocks serve as a substitute for browser I/O. This is acceptable for unit tests but consider adding integration tests that exercise the real engine with a headless browser.

### tests/unit/test_agent_mcp_client.py (123 mock lines)
- **External dependency mocks:** 1 (`asyncio.sleep`)
- **Internal component mocks:** 1 targeted patch + 121 bare mocks
  - `agentcrawl.agent.mcp_client._JsonRpc.request`: 1 patch
  - Bare mocks create fake MCP protocol messages, transport objects, and JSON-RPC responses
- **Classification:** MIXED
- **Recommendation:** The single targeted patch mocks internal JSON-RPC transport, but the bare mocks primarily simulate protocol-level interactions (message serialization, connection lifecycle). Since MCP transport is a network protocol, this is acceptable as unit-level simulation. Consider adding a fixture that generates realistic MCP message structures to reduce mock duplication.

### tests/unit/test_core_pipeline.py (113 mock lines)
- **External dependency mocks:** 0 targeted patches to external deps
- **Internal component mocks:** 3 targeted patches + 87 bare mocks
  - `agentcrawl.content.chunker.create_chunker_from_config`: 2 patches
  - `agentcrawl.content.citation.CitationExtractor`: 1 patch
  - Bare mocks simulate pipeline stages: cache reads/writes, extracted content, chunk lists, citation maps
- **Classification:** MIXED
- **Recommendation:** The targeted patches mock content processing internals. However, the pipeline stages are designed to be pluggable, so mocking at the stage boundary is appropriate. The bare mocks mostly simulate data flowing through the pipeline (strings, dicts, lists) rather than mocking internal state. This is acceptable.

### tests/unit/test_core_session.py (103 mock lines)
- **External dependency mocks:** 0 targeted patches to external deps
- **Internal component mocks:** 2 targeted patches + 70 bare mocks (51 non-self + 20 self-referencing)
  - `agentcrawl.browser.actions.PageActions`: 2 patches
  - Bare mocks simulate session state objects, page visit records, cookie data
- **Classification:** MIXED
- **Recommendation:** Tests access `._make_session`, `._context`, `._state`, `._started` (private attributes) extensively. Since CrawlSession is a data model, testing its internal state transitions is legitimate. The PageActions mock is for the browser layer (external). Acceptable.

### tests/unit/test_agent_tool_langchain_crewai.py (94 mock lines)
- **External dependency mocks:** 0 targeted patches to external deps (langchain/crewai are mocked via sys.modules injection, not via `patch()`)
- **Internal component mocks:** 20 targeted patches + 30 bare mocks
  - `agentcrawl.agent.tool._engine_manager`: 20 patches (same pattern as test_agent_tool.py)
  - Bare mocks for `_arun`, `_get_toolkit`, toolkit execution results
- **Classification:** QUESTIONABLE
- **Recommendation:** Same `_engine_manager` mocking pattern as test_agent_tool.py. The 20 `._engine_manager` patches tightly couple tests to the internal engine manager singleton. The `._arun` and `._get_toolkit` accesses are testing private methods of the LangChain/CrewAI tool wrappers. Consider testing through public `_run` method instead.

### tests/unit/test_engine.py (75 mock lines)
- **External dependency mocks:** 0 targeted patches to external deps
- **Internal component mocks:** 20 targeted patches + 42 bare mocks
  - `agentcrawl.core.engine.BrowserManager`: 17 patches
  - `agentcrawl.crawling.bfs.BFSCrawler`: 1 patch
  - `agentcrawl.search.engine.SearchEngine`: 1 patch
  - `agentcrawl.extraction.base.create_extractor`: 1 patch
  - Bare mocks simulate engine results, crawl results, search results
- **Classification:** MIXED
- **Recommendation:** BrowserManager mock is acceptable (external browser dependency). However, mocking BFSCrawler, SearchEngine, and create_extractor means the engine is being tested with all its collaborators replaced — this verifies orchestration logic but not integration. This is standard unit testing practice. Acceptable.

### tests/unit/test_browser_manager.py (62 mock lines)
- **External dependency mocks:** 15 targeted patches — ALL to `playwright.*` (external dependency)
- **Internal component mocks:** 0 targeted patches + 11 bare mocks (as return values for playwright mocks)
- **Classification:** ACCEPTABLE
- **Recommendation:** This file correctly mocks only the external Playwright browser API. The bare mocks are configuration objects and return values for playwright methods. This is the ideal pattern — no internal components are mocked.

### tests/unit/test_browser_actions.py (58 mock lines)
- **External dependency mocks:** 3 targeted patches (2 `asyncio.sleep`, 1 `playwright`)
- **Internal component mocks:** 1 targeted patch + 28 bare mocks (AsyncMock)
  - `agentcrawl.browser.actions.logger`: 1 patch (internal logging)
  - Bare mocks simulate page objects, frame objects, DOM elements
- **Classification:** ACCEPTABLE
- **Recommendation:** The bare mocks simulate Playwright Page/Frame objects (external), which is correct. The single internal `logger` patch is a common and acceptable pattern. The `._page` and `._current_frame` accesses (52 instances) are testing internal state of the action executor, but since PageActions is a test double target wrapping Playwright, this coupling is necessary. Acceptable.

### tests/unit/test_core_engine.py (54 mock lines)
- **External dependency mocks:** 0 targeted patches to external deps
- **Internal component mocks:** 10 targeted patches + 15 bare mocks (73 total counting all)
  - `agentcrawl.crawling.bfs.BFSCrawler`: 4 patches
  - `agentcrawl.search.engine.SearchEngine`: 3 patches
  - `agentcrawl.extraction.base.create_extractor`: 3 patches
  - Bare mocks simulate CrawlResult, engine stats, cache operations
- **Classification:** MIXED
- **Recommendation:** Same pattern as test_engine.py — mocking internal crawlers, search engines, and extractors to test the engine orchestrator. Standard unit testing approach. The `._is_started`, `._cache_manager`, `._build_cache_key` accesses are testing internal engine state, which is necessary for verifying lifecycle management. Acceptable with note.

## Classification Summary

| Classification | File Count |
|---|---|
| ACCEPTABLE | 2 (test_browser_manager, test_browser_actions) |
| MIXED | 5 (test_core_pipeline, test_core_session, test_engine, test_core_engine, test_agent_mcp_client) |
| QUESTIONABLE | 2 (test_agent_tool, test_agent_tool_langchain_crewai) |
| N/A (mocks as test doubles, not component mocks) | — |

## Recommendations

1. **test_agent_tool.py and test_agent_tool_langchain_crewai.py (QUESTIONABLE):** The repeated 30/20 patches on `_engine_manager` create tight coupling. Consider extracting a shared fixture that sets up a mock engine manager once, reducing duplication and centralizing the mock contract. The stub test functions (`test_get_langchain_tools_raises`, `test_get_crewai_tools_raises`) now work with the module-level function approach — no change needed there.

2. **test_engine.py and test_core_engine.py (MIXED):** The pattern of mocking BFSCrawler, SearchEngine, and Extractor is standard for unit testing the engine orchestrator. No action needed — this is acceptable unit test design.

3. **test_browser_manager.py (ACCEPTABLE):** This is the gold standard — only external Playwright dependencies are mocked. No changes needed.

4. **test_browser_actions.py (ACCEPTABLE):** Bare mocks simulate Playwright Page/Frame objects correctly. The single `logger` patch is a common, acceptable pattern.

5. **test_core_session.py (MIXED):** The `._make_session`, `._context`, `._state` accesses are testing internal session state transitions. Consider adding public properties or methods for the state that tests need to verify, to reduce coupling. However, since CrawlSession is a data model with complex state lifecycle, this coupling is likely necessary.

6. **General:** No refactoring required per Issue 10 scope (audit only). The mocking patterns are standard unit testing practices. The main concern is the duplication of `_engine_manager` mocking across two files, which could be consolidated into a shared conftest.py fixture.
