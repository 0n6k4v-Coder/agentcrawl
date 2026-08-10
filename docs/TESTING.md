# Testing Guidelines

This document describes testing practices for AgentCrawl, distilled from the
lessons learned during the Phase 3–4 audit and refactor cycles.

## Table of Contents

1. [Overview](#overview)
2. [Test Organization](#test-organization)
3. [Mocking Guidelines](#mocking-guidelines)
4. [Test Isolation](#test-isolation)
5. [Shared Fixtures](#shared-fixtures)
6. [Pytest Markers](#pytest-markers)
7. [Coverage Requirements](#coverage-requirements)
8. [Examples](#examples)

## Overview

AgentCrawl uses **pytest** for all unit and integration tests.

- **Test counts:** 2266+ unit tests, 112+ integration tests
- **Coverage:** ~56% (target 80%, growing)
- **CI:** All tests must pass on GitHub Actions (`.github/workflows/ci.yml`)

### Running Tests

```bash
# All unit tests (fast, no browser)
make test

# With coverage
pytest tests/unit/ --cov=agentcrawl --cov-report=html

# Specific module
pytest tests/unit/test_agent_tool.py -v

# Integration tests (requires Playwright + network)
pytest tests/integration/ --run-integration

# Full CI simulation (Docker required)
make pre-push
```

## Test Organization

```
tests/
├── unit/              # Unit tests (no external deps)
│   ├── conftest.py    # Shared fixtures (mock_engine_manager, etc.)
│   ├── test_agent_*.py
│   ├── test_core_*.py
│   ├── test_browser_*.py
│   └── ...
├── integration/       # Integration tests (browser, network)
└── conftest.py        # Root fixtures (mock_engine, real engine)
```

The `tests/unit/conftest.py` holds fixtures shared across unit test modules
(e.g. `mock_engine_manager`). The root `tests/conftest.py` holds broader
fixtures like `mock_engine` and a real `CrawlEngine` lifecycle fixture.

See [Development Workflow](README.md#development-workflow) in the README for
local setup and pre-commit configuration.

## Mocking Guidelines

### External Dependencies (ACCEPTABLE)

Mock external dependencies that are hard to control or spin up in a unit test:

- **Playwright/Browser**: Mock `Page`, `Browser`, `Frame` objects
- **LLM APIs**: Mock OpenAI / Anthropic / LLM clients
- **MCP/Network**: Mock the transport layer
- **File system**: Use the `tmp_path` fixture

**Example — BrowserPool (from `tests/unit/test_browser_pool.py`):**

```python
def test_pool_initialization(self):
    with patch("agentcrawl.browser.pool.async_playwright") as mock_pw:
        mock_browser = AsyncMock()
        mock_pw.return_value.__aenter__.return_value.chromium.launch.return_value = mock_browser

        pool = BrowserPool(size=2)
        await pool.initialize()

        assert pool.size == 2
```

### Internal Components (QUESTIONABLE)

Avoid mocking internal components when possible:

- Use real classes with test data
- Test through the public API
- Use dependency injection

**Acceptable when:**

- Testing orchestration logic (the class under test isn't the real subject)
- Simulating error conditions on a dependency
- External dependencies cascade into the internal component

### The shared fixture pattern

Prefer a single shared fixture over per-test `patch()` calls. The canonical
example is `mock_engine_manager` in `tests/unit/conftest.py`:

```python
@pytest.fixture
def mock_engine_manager():
    """Shared fixture for mocking the engine manager singleton."""
    with patch("agentcrawl.agent.tool._engine_manager") as mock_manager:
        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock()
        mock_engine.crawl = AsyncMock()
        mock_engine.search = AsyncMock()
        mock_engine.batch_scrape = AsyncMock()
        mock_engine.map = AsyncMock()
        mock_engine.startup = AsyncMock()
        mock_manager.get_engine = AsyncMock(return_value=mock_engine)
        mock_manager.shutdown = AsyncMock()
        yield mock_manager
```

Tests then read the pre-wired engine via `mock_engine_manager.get_engine.return_value`
and only override the return values they care about.

## Test Isolation

### sys.modules Manipulation

When testing optional dependencies (langchain, crewai), use a save/restore
pattern so mocks don't leak across modules:

```python
@pytest.fixture(scope="module", autouse=True)
def mock_langchain_crewai():
    """Mock langchain/crewai with proper isolation."""
    saved = {}
    keys = ["langchain", "langchain.tools", "crewai", "crewai.tools"]
    for key in keys:
        if key in sys.modules:
            saved[key] = sys.modules[key]

    sys.modules["langchain"] = MagicMock()
    sys.modules["crewai"] = MagicMock()
    # Force reimport of the module under test
    sys.modules.pop("agentcrawl.agent.tool", None)

    yield

    # Restore original module state
    for key in keys:
        if key in saved:
            sys.modules[key] = saved[key]
        elif key in sys.modules:
            del sys.modules[key]

    sys.modules.pop("agentcrawl.agent.tool", None)
```

### Fixture scope

- **`function` (default):** Use for per-test state. Always prefer this unless
  isolation is proven safe.
- **`module`:** Use for expensive, immutable setup shared across a module.
- **`session`:** Use sparingly; shared state across the whole session risks
  cross-test contamination.

## Shared Fixtures

Prefer shared fixtures in `conftest.py` over duplicate per-test mocking:

```python
# Good: shared fixture
def test_tool_execute(mock_engine_manager):
    mock_engine = mock_engine_manager.get_engine.return_value
    mock_engine.scrape.return_value = {"url": "https://x.com", "markdown": "..."}
    result = tool.execute(...)
    assert result is not None

# Bad: duplicate mocking
def test_tool_execute():
    with patch("agentcrawl.agent.tool._engine_manager") as m:
        m.get_engine.return_value.scrape.return_value = {"url": "https://x.com"}
        ...
```

The shared fixture keeps the mock surface consistent and makes refactoring
the patch target a one-line change.

## Pytest Markers

```python
@pytest.mark.asyncio                              # Async tests
async def test_async_function(): ...

@pytest.mark.skipif(os.getenv("CI") == "true",   # Flaky in CI
                    reason="Flaky in CI")
def test_flaky_network(): ...

@pytest.mark.integration                          # Integration tests
def test_real_browser(): ...
```

Run marker-scoped subsets:

```bash
pytest tests/unit/ -m "not integration"
pytest tests/integration/ -m integration --run-integration
```

## Coverage Requirements

- **Target:** 80% (current: ~56%)
- **New code:** Must come with tests
- **Coverage check:** Local only (not enforced in CI yet)

```bash
# Check coverage (missing lines highlighted)
pytest tests/unit/ --cov=agentcrawl --cov-report=term-missing

# Generate HTML report
pytest tests/unit/ --cov=agentcrawl --cov-report=html
open htmlcov/index.html
```

Coverage gaps discovered during the Phase 4 audit are tracked in
`references/heavy_mocking_audit_report.md` and
`references/private_attribute_access_audit_report.md`.

## Examples

### Testing Private State (Use Public Properties)

This was a core fix in commit `c0bd095` — tests used to read private
`_is_started`; they now use the public `is_started` property
(`agentcrawl/core/engine.py:402`):

```python
# Good: use the public read-only property
assert engine.is_started is True

# Bad: accessing a private attribute directly
assert engine._is_started is True  # removed in c0bd095
```

The `CrawlEngine` exposes `is_started` as a `@property` specifically so tests
and consumers never touch `_is_started`:

```python
@property
def is_started(self) -> bool:
    """Return whether the engine has been started."""
    return self._is_started
```

### Testing Error Paths

```python
def test_invalid_url():
    with pytest.raises(ValueError, match="Invalid URL"):
        engine.scrape("")

def test_network_error():
    with patch.object(httpx, "get", side_effect=httpx.TimeoutException):
        result = fetcher.fetch("https://example.com")
        assert result.error is not None
```

## References

- [Pytest Documentation](https://docs.pytest.org/)
- [Python Mock Library](https://docs.python.org/3/library/unittest.mock.html)
- Our test files: `tests/unit/`, `tests/integration/`
- Audit reports: `references/heavy_mocking_audit_report.md`,
  `references/private_attribute_access_audit_report.md`
- [Code Style Guide](CODE_STYLE.md)
- [Suppression Policy](SUPPRESSION_POLICY.md)
