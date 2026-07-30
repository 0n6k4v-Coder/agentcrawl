"""
AgentCrawl — Test Configuration & Fixtures
==============================================

Shared pytest fixtures and configuration for the AgentCrawl
test suite.

Fixtures:
    - Event loop (async tests)
    - CrawlEngine (mock and real)
    - CrawlerConfig presets
    - Sample HTML/Markdown content
    - Mock HTTP responses
    - Settings overrides
    - Temporary directories
    - Cache manager

Usage:
    # In test files, fixtures are auto-discovered:
    async def test_scrape(engine, sample_html):
        result = await engine.scrape("https://example.com")
        assert result.success

Markers:
    @pytest.mark.slow       — Slow tests (skip with -m "not slow")
    @pytest.mark.integration — Integration tests (require network)
    @pytest.mark.e2e        — End-to-end tests
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

# Add project root to sys.path for server/ imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# ══════════════════════════════════════════════════════════════
# Pytest Configuration
# ══════════════════════════════════════════════════════════════


def pytest_configure(config: Any) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests requiring network access")
    config.addinivalue_line("markers", "e2e: marks end-to-end tests")
    config.addinivalue_line("markers", "llm: marks tests requiring LLM API keys")


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """Skip integration/e2e tests unless explicitly requested."""
    skip_integration = pytest.mark.skip(reason="Need --run-integration flag")
    skip_e2e = pytest.mark.skip(reason="Need --run-e2e flag")

    run_integration = config.getoption("--run-integration", default=False)
    run_e2e = config.getoption("--run-e2e", default=False)

    for item in items:
        if "integration" in item.keywords and not run_integration:
            item.add_marker(skip_integration)
        if "e2e" in item.keywords and not run_e2e:
            item.add_marker(skip_e2e)


def pytest_addoption(parser: Any) -> None:
    """Add custom CLI options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (require network)",
    )
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run end-to-end tests",
    )


# ══════════════════════════════════════════════════════════════
# Event Loop
# ══════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ══════════════════════════════════════════════════════════════
# Settings
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def settings() -> Any:
    """Create test Settings with safe defaults."""
    from agentcrawl.config.settings import Settings

    return Settings(
        log_level="WARNING",
        headless=True,
        stealth=False,
        cache_backend="memory",
        cache_ttl=60,
        api_key="",
    )


@pytest.fixture
def settings_no_cache() -> Any:
    """Settings with caching disabled."""
    from agentcrawl.config.settings import Settings

    return Settings(
        log_level="WARNING",
        headless=True,
        cache_backend="none",
    )


# ══════════════════════════════════════════════════════════════
# CrawlerConfig
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def default_config() -> Any:
    """Default CrawlerConfig for tests."""
    from agentcrawl.config.crawler_config import CrawlerConfig

    return CrawlerConfig(
        output_format="markdown",
        include_links=True,
        include_metadata=True,
        only_main_content=True,
        cache=False,
        timeout=15,
    )


@pytest.fixture
def markdown_config() -> Any:
    """CrawlerConfig for Markdown output."""
    from agentcrawl.config.crawler_config import CrawlerConfig

    return CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        cache=False,
    )


@pytest.fixture
def chunked_config() -> Any:
    """CrawlerConfig with chunking enabled."""
    from agentcrawl.config.crawler_config import CrawlerConfig

    return CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        chunker="topic",
        chunk_max_size=500,
        chunk_overlap=100,
        cache=False,
    )


@pytest.fixture
def filtered_config() -> Any:
    """CrawlerConfig with content filtering."""
    from agentcrawl.config.crawler_config import CrawlerConfig

    return CrawlerConfig(
        output_format="markdown",
        only_main_content=True,
        content_filter="pruning",
        cache=False,
    )


# ══════════════════════════════════════════════════════════════
# Engine
# ══════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def engine(settings: Any) -> AsyncGenerator[Any, None]:
    """
    Create a real CrawlEngine for testing.

    Starts the engine and shuts it down after the test.
    """
    from agentcrawl.core.engine import CrawlEngine

    engine = CrawlEngine.from_settings(settings)
    await engine.startup()

    yield engine

    await engine.shutdown()


@pytest.fixture
def mock_engine() -> Any:
    """
    Create a mock CrawlEngine.

    Useful for unit tests that don't need a real browser.
    """
    engine = MagicMock()
    engine.is_started = True

    # Mock scrape
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.url = "https://example.com"
    mock_result.status_code = 200
    mock_result.markdown = "# Example\n\nTest content"
    mock_result.html = "<h1>Example</h1><p>Test content</p>"
    mock_result.text = "Example Test content"
    mock_result.word_count = 3
    mock_result.token_count = 5
    mock_result.response_time_ms = 100.0
    mock_result.cached = False
    mock_result.error = None
    mock_result.metadata = {"title": "Example"}
    mock_result.links = {"all": [], "internal": [], "external": []}
    mock_result.citations = []
    mock_result.chunks = []
    mock_result.extracted_data = None
    mock_result.screenshot = ""
    mock_result.request_id = "req_test"

    engine.scrape = AsyncMock(return_value=mock_result)
    engine.batch_scrape = AsyncMock(return_value=[mock_result])
    engine.startup = AsyncMock()
    engine.shutdown = AsyncMock()

    return engine


# ══════════════════════════════════════════════════════════════
# Sample Content
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def sample_html() -> str:
    """Sample HTML page for testing."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Example Domain</title>
    <meta name="description" content="An example web page for testing.">
    <meta property="og:title" content="Example Domain">
    <meta property="og:description" content="An example web page.">
</head>
<body>
    <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/contact">Contact</a>
    </nav>
    <main>
        <h1>Example Domain</h1>
        <p>This domain is for use in illustrative examples in documents.
        You may use this domain in literature without prior coordination
        or asking for permission.</p>
        <h2>More Information</h2>
        <p>For more information, visit
        <a href="https://www.iana.org/domains/example">IANA</a>.</p>
        <ul>
            <li>Item one</li>
            <li>Item two</li>
            <li>Item three</li>
        </ul>
    </main>
    <footer>
        <p>&copy; 2025 Example Corp</p>
    </footer>
</body>
</html>"""


@pytest.fixture
def sample_html_complex() -> str:
    """Complex HTML with tables, code blocks, and nested elements."""
    return """<!DOCTYPE html>
<html>
<head><title>Complex Page</title></head>
<body>
    <article>
        <h1>Python Guide</h1>
        <p>Python is a programming language.</p>
        <h2>Features</h2>
        <table>
            <thead>
                <tr><th>Feature</th><th>Description</th></tr>
            </thead>
            <tbody>
                <tr><td>Dynamic</td><td>Dynamic typing</td></tr>
                <tr><td>Interpreted</td><td>No compilation needed</td></tr>
            </tbody>
        </table>
        <h2>Code Example</h2>
        <pre><code>def hello():
    print("Hello, World!")
</code></pre>
        <h2>Links</h2>
        <a href="https://python.org">Python.org</a>
        <a href="https://docs.python.org">Docs</a>
        <a href="/internal">Internal Page</a>
    </article>
</body>
</html>"""


@pytest.fixture
def sample_markdown() -> str:
    """Sample Markdown content for testing."""
    return """# Example Domain

This domain is for use in illustrative examples in documents.
You may use this domain in literature without prior coordination
or asking for permission.

## More Information

For more information, visit [IANA](https://www.iana.org/domains/example).

- Item one
- Item two
- Item three

## Conclusion

This is a simple example page used for testing purposes.
"""


@pytest.fixture
def sample_markdown_long() -> str:
    """Long Markdown content for chunking tests."""
    sections = []
    for i in range(10):
        sections.append(f"## Section {i + 1}\n")
        sections.append(
            f"This is section {i + 1} with enough content to make "
            f"it meaningful for testing chunking algorithms. "
            f"It contains multiple sentences that should be properly "
            f"split across chunks when the chunk size is small enough. "
            f"Additional padding text ensures we have sufficient content "
            f"for meaningful tests of the chunking system.\n"
        )
    return "\n".join(sections)


# ══════════════════════════════════════════════════════════════
# Mock HTTP
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_httpx_response(sample_html: str) -> MagicMock:
    """Mock httpx.Response object."""
    response = MagicMock()
    response.status_code = 200
    response.text = sample_html
    response.headers = {
        "content-type": "text/html; charset=utf-8",
        "content-length": str(len(sample_html)),
    }
    response.url = "https://example.com"
    response.elapsed.total_seconds.return_value = 0.5
    return response


@pytest.fixture
def mock_search_results() -> list[dict[str, Any]]:
    """Sample search results."""
    return [
        {
            "title": "Python Tutorial",
            "url": "https://docs.python.org/3/tutorial/",
            "snippet": "The Python Tutorial introduces the reader informally...",
            "position": 1,
            "domain": "docs.python.org",
        },
        {
            "title": "Python.org",
            "url": "https://www.python.org/",
            "snippet": "The official home of the Python Programming Language.",
            "position": 2,
            "domain": "python.org",
        },
        {
            "title": "Real Python",
            "url": "https://realpython.com/",
            "snippet": "Learn Python programming from basic to advanced.",
            "position": 3,
            "domain": "realpython.com",
        },
    ]


# ══════════════════════════════════════════════════════════════
# Cache
# ══════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def cache_manager() -> AsyncGenerator[Any, None]:
    """Create an in-memory cache manager."""
    from agentcrawl.cache.manager import CacheManager

    manager = CacheManager(backend="memory", default_ttl=60)
    await manager.start()

    yield manager

    await manager.stop()


# ══════════════════════════════════════════════════════════════
# Temporary Files
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test outputs."""
    output_dir = tmp_path / "agentcrawl_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.fixture
def temp_output_file(temp_dir: Path) -> Path:
    """Temporary output file path."""
    return temp_dir / "output.json"


# ══════════════════════════════════════════════════════════════
# Search
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_search_engine(mock_search_results: list[dict[str, Any]]) -> MagicMock:
    """Mock SearchEngine."""
    engine = MagicMock()
    engine.search = AsyncMock(return_value=mock_search_results)
    engine.search_with_response = AsyncMock()
    return engine


# ══════════════════════════════════════════════════════════════
# Extraction
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def css_schema() -> dict[str, Any]:
    """Sample CSS extraction schema."""
    return {
        "name": "Page Info",
        "fields": [
            {"name": "title", "selector": "h1", "type": "text"},
            {"name": "link", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "paragraphs", "selector": "p", "type": "list"},
        ],
    }


@pytest.fixture
def xpath_schema() -> dict[str, Any]:
    """Sample XPath extraction schema."""
    return {
        "name": "Page Info",
        "fields": [
            {"name": "title", "xpath": "//h1", "type": "text"},
            {"name": "links", "xpath": "//a/@href", "type": "list"},
        ],
    }


# ══════════════════════════════════════════════════════════════
# Environment
# ══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure clean environment for each test."""
    # Remove any API keys that might interfere
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AGENTCRAWL_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    # Set test mode
    monkeypatch.setenv("AGENTCRAWL_TEST_MODE", "1")


@pytest.fixture
def has_openai_key() -> bool:
    """Check if OpenAI API key is available."""
    return bool(os.environ.get("OPENAI_API_KEY"))


@pytest.fixture
def skip_without_openai(has_openai_key: bool) -> None:
    """Skip test if OpenAI API key is not available."""
    if not has_openai_key:
        pytest.skip("OPENAI_API_KEY not set")


# ══════════════════════════════════════════════════════════════
# Playwright Availability
# ══════════════════════════════════════════════════════════════

_PLAYWRIGHT_AVAILABLE: bool | None = None


def _playwright_available() -> bool:
    """Check if Playwright Chromium browser is installed."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Try to launch — will fail if browser not installed
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


def playwright_available() -> bool:
    """Cached check for Playwright Chromium availability."""
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is None:
        _PLAYWRIGHT_AVAILABLE = _playwright_available()
    return _PLAYWRIGHT_AVAILABLE


@pytest.fixture
def require_playwright() -> None:
    """Skip test if Playwright Chromium is not installed."""
    if not playwright_available():
        pytest.skip(
            "Playwright Chromium not installed. "
            "Run: playwright install chromium && playwright install-deps chromium"
        )
