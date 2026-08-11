# Private Attribute Access Audit Report (Issue 11)

## Summary

- **Total private attribute accesses across all test files:** 718
- **Files with >10 instances:** 13
- **Files with >50 instances:** 6
- **Files with >100 instances:** 2 (test_agent_mcp_client.py, test_core_session.py)

## High-Risk Files (>50 instances)

### tests/unit/test_agent_mcp_client.py (185 instances)
Top accessed attributes:
- `_connected`: 46 — testing MCP client connection lifecycle state
- `_transport`: 43 — testing internal JSON-RPC transport layer
- `_pending`: 24 — testing pending request tracking (request/response correlation)
- `_handle_message`: 10 — testing internal message handler dispatch
- `_notification_handlers`: 8 — testing notification handler registration

**Recommendation:** The `_connected` and `_transport` accesses test internal connection state that has no public accessor. Consider adding public properties (e.g., `is_connected: bool`) or state enums to expose connection status. The `_pending` and `_handle_message` accesses are testing internal protocol mechanics — these could be verified through public method behavior (sending requests, matching responses) rather than inspecting internal pending-tracking dicts.

### tests/unit/test_core_session.py (136 instances)
Top accessed attributes:
- `_make_session`: 46 — testing internal session factory method
- `_context`: 31 — testing internal crawl context (session-scoped state)
- `_state`: 21 — testing session state (enum/flag inspection)
- `_started`: 16 — testing session lifecycle flag
- `_restore_state`: 4 — testing state restoration

**Recommendation:** `_started` and `_state` could be exposed as read-only public properties (`session.is_started`, `session.state`) since tests need to verify lifecycle state. `_context` is a context object that tests need to inspect for verifying crawl behavior — consider adding a public `context` property. `_make_session` is a factory method that tests call to create sessions — consider making it a public static/class method or providing a public factory function.

### tests/unit/test_agent_tool.py (90 instances)
Top accessed attributes:
- `_engine_manager`: 30 — testing internal engine manager singleton access
- `_tool_registry`: 8 — testing internal tool registration dictionary
- `_engine`: 7 — testing internal engine reference
- `_format_result`: 6 — testing internal result formatting
- `_handle_extract`: 5 — testing internal extraction dispatch

**Recommendation:** `_engine_manager` accesses are the highest concern — 30 instances of reaching into the module-level singleton. Tests verify that `create_toolkit` and tool classes correctly delegate to the engine manager. Consider adding a public `get_engine()` accessor or making the engine manager injectable via constructor for testability. `_tool_registry` and `_format_result` are testing internal tool metadata — these could be exposed via public methods like `list_registered_tools()`.

### tests/unit/test_agent_tool_langchain_crewai.py (56 instances)
Top accessed attributes:
- `_engine_manager`: 20 — same pattern as test_agent_tool.py
- `_arun`: 20 — testing internal async run methods of LangChain/CrewAI tool wrappers
- `_get_toolkit`: 11 — testing internal toolkit lazy-initialization
- `_return_format`: 5 — testing internal output format setting

**Recommendation:** `_arun` and `_get_toolkit` are LangChain/CrewAI framework-required method names (prefixed with `_` by the framework convention). These cannot be renamed. The `_engine_manager` pattern is the same concern as in test_agent_tool.py. `_return_format` could be exposed as a public property.

### tests/unit/test_browser_actions.py (51 instances)
Top accessed attributes:
- `_page`: 23 — testing internal Playwright Page reference
- `_current_frame`: 19 — testing internal frame tracking
- `_get_handler`: 4 — testing internal action handler dispatch
- `_stop_on_error`: 2 — testing error handling flag
- `__new__`: 1 — dunder method access

**Recommendation:** `_page` and `_current_frame` are testing internal Playwright page/frame state. Since PageActions wraps external Playwright objects, these accesses are testing how the wrapper manages Playwright's state. Consider adding public properties `page` and `current_frame` for test inspection. `_get_handler` is an internal dispatch method — tests could verify it through public `execute()` calls instead.

### tests/unit/test_core_engine.py (28 instances)
Top accessed attributes:
- `_is_started`: 17 — testing engine lifecycle state
- `_cache_manager`: 5 — testing internal cache manager reference
- `_build_cache_key`: 3 — testing internal cache key generation
- `__dataclass_fields__`: 2 — testing dataclass field introspection
- `_ensure_started`: 1 — testing internal startup guard

**Recommendation:** `_is_started` (17 accesses) is the highest concern. Consider adding a public `is_started` property. `_cache_manager` could be exposed via a public `cache_manager` property if tests need to verify cache behavior. `_build_cache_key` is an internal utility — tests could verify caching behavior through public API instead.

## Other Files (<=28 instances)

### tests/unit/test_output_html.py (44 instances)
Top accessed: `_build_meta_tags` (9), `_markdown_to_html` (5), `_render_template` (4), `_escape_html` (3), `_allow_images` (2)
**Recommendation:** These are output formatting internals. The `_markdown_to_html` and `_escape_html` methods are utility functions that tests need to verify directly. Consider making these public or adding integration-level tests that verify HTML output through the public API.

### tests/unit/test_output_json.py (32 instances)
Top accessed: `_remove_empty` (5), `_flatten_dict` (5), `_default_serializer` (5), `_serialize` (3), `_serializers` (2)
**Recommendation:** JSON serialization internals. Tests verify edge cases of individual serializers. Acceptable for unit testing granular serialization logic.

### tests/unit/test_output_screenshot.py (28 instances)
Top accessed: `_get_dimensions` (7), `_detect_format` (6), `_url_to_slug` (6), `_get_jpeg_dimensions` (3), `_default_format` (2)
**Recommendation:** Screenshot utility methods. Tests verify format detection and dimension parsing. These are internal utilities — consider testing through the public `screenshot()` method with assertions on output file properties.

### tests/unit/test_core_pipeline.py (16 instances)
Top accessed: `_stages` (8), `_execute` (5), `_stop_on_error` (3)
**Recommendation:** `_stages` and `_execute` test pipeline internals. Since the pipeline is designed as a composable pattern, testing internal stage execution is legitimate. `_stop_on_error` could be exposed via a public property.

### tests/unit/test_engine.py (12 instances)
Top accessed: `_is_started` (5), `_browser_manager` (4), `_settings` (2), `__all__` (1)
**Recommendation:** `_is_started` access — same as test_core_engine.py. Consider adding `is_started` public property. `_browser_manager` could be exposed via public property.

### tests/unit/test_crawling.py (12 instances)
Top accessed: `_parse_xml` (3), `_sitemaps` (3), `_max_urls` (2), `_scorer` (1), `_rules` (1)
**Recommendation:** BFS crawler internals. `_parse_xml`, `_sitemaps`, `_max_urls` could be exposed as public read-only properties for test verification.

### tests/unit/test_utils_logging.py (28 instances, 24 are `self._`)
Top accessed: `_make_record` (24), `_use_colors` (2), `__enter__` (1), `__exit__` (1)
**Recommendation:** `self._make_record` is a test helper method (self-referential), not production code private access. Acceptable.

## Summary Statistics

| Metric | Count |
|---|---|
| Total private attribute accesses | 718 |
| Files with >10 instances | 13 |
| Files with >50 instances | 6 |
| Files with >100 instances | 2 |
| Distinct `_engine_manager` accesses (test_agent_tool + test_agent_tool_langchain_crewai) | 50 |
| Distinct `_is_started` accesses (test_core_engine + test_engine) | 22 |
| Framework-required `_arun` accesses (test_agent_tool_langchain_crewai) | 20 |

## Classification

- **Framework-required (cannot rename):** `_arun` (LangChain), `_run` (LangChain/CrewAI) — 20 instances. These are mandated by the framework's BaseTool interface.
- **State inspection (could be public properties):** `_is_started`, `_connected`, `_state`, `_started`, `_return_format` — 102 instances. High-value candidates for public read-only properties.
- **Internal dispatch (testable via public API):** `_engine_manager`, `_get_handler`, `_format_result`, `_handle_extract`, `_handle_message` — 68 instances. These could be tested through public method behavior.
- **Data model internals (legitimate test coupling):** `_context`, `_tool_registry`, `_cache_manager`, `_make_session` — 92 instances. Testing these directly is necessary for verifying data model behavior.
- **Utility methods (testable via public API):** `_build_cache_key`, `_parse_xml`, `_remove_empty`, `_flatten_dict`, `_detect_format`, `_get_dimensions` — 30 instances. Could be tested through public output verification.

## Recommendations

1. **Priority: Add public read-only properties** for state inspection: `is_started` (CrawlEngine, SessionManager), `is_connected` (MCPClient), `state` (CrawlSession), `return_format` (AgentCrawlToolkit). This would eliminate ~102 private accesses.

2. **Priority: Reduce `_engine_manager` coupling** (50 accesses across 2 files): Extract a shared pytest fixture in conftest.py that provides a pre-configured mock engine manager. Or add a public `get_engine_manager()` accessor to the module.

3. **Framework-required names** (`_arun`, `_run`): No action possible — these are mandated by the LangChain/CrewAI BaseTool interface contract. Acceptable.

4. **Internal dispatch testing:** Where tests access `_engine_manager`, `_get_handler`, `_format_result` to verify internal behavior, consider refactoring tests to assert on observable public method outputs instead. This would reduce ~68 accesses.

5. **Utility method testing:** For `_build_cache_key`, `_parse_xml`, `_remove_empty` etc., consider testing through public API methods and asserting on results/format rather than inspecting intermediate utility outputs.

6. **No action needed:** Framework-required methods, data model internal state, and test helper methods (`self._make_record`). These are acceptable test coupling patterns.
