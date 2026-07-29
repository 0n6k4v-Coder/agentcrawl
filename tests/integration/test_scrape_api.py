"""
AgentCrawl — Scrape API Integration Tests
=============================================

Integration tests for the scrape and batch scrape REST API endpoints.

Tests:
    - POST /scrape (single page)
    - Scrape options (links, metadata, screenshot, chunks)
    - Content filtering
    - Page actions
    - Validation errors
    - POST /batch/scrape
    - Error handling
    - Cache behavior

Run:
    pytest tests/integration/test_scrape_api.py -v
    pytest tests/integration/test_scrape_api.py -v --run-integration
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def app() -> AsyncGenerator[Any, None]:
    """Create a test FastAPI app."""
    from agentcrawl.config.settings import Settings
    from server.app import create_app

    settings = Settings(
        log_level="WARNING",
        headless=True,
        cache_backend="memory",
        cache_ttl=60,
        auth_enabled=False,
    )

    application = create_app(settings)

    yield application

@pytest_asyncio.fixture
async def client(app: Any) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=60.0,
    ) as c:
        yield c


# ══════════════════════════════════════════════════════════════
# POST /scrape — Basic
# ══════════════════════════════════════════════════════════════

class TestScrapeBasic:
    """Tests for basic scrape operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_example_com(self, client: AsyncClient) -> None:
        """Scrape example.com successfully."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
        })

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["url"] == "https://example.com"
        assert data["status_code"] == 200
        assert len(data["markdown"]) > 0
        assert data["word_count"] > 0
        assert data["response_time_ms"] > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_returns_markdown(self, client: AsyncClient) -> None:
        """Scrape returns Markdown content."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "output_format": "markdown",
        })

        data = response.json()
        assert data["success"] is True
        assert "markdown" in data
        assert "Example Domain" in data["markdown"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_returns_metadata(self, client: AsyncClient) -> None:
        """Scrape includes page metadata."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "include_metadata": True,
        })

        data = response.json()
        assert data["success"] is True
        assert "metadata" in data
        assert "title" in data["metadata"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_returns_links(self, client: AsyncClient) -> None:
        """Scrape includes extracted links."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "include_links": True,
        })

        data = response.json()
        assert data["success"] is True
        assert "links" in data

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_has_request_id(self, client: AsyncClient) -> None:
        """Scrape response includes request ID."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
        })

        data = response.json()
        assert "request_id" in data


# ══════════════════════════════════════════════════════════════
# POST /scrape — Options
# ══════════════════════════════════════════════════════════════

class TestScrapeOptions:
    """Tests for scrape configuration options."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_only_main_content(self, client: AsyncClient) -> None:
        """only_main_content filters navigation/footer."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "only_main_content": True,
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_content_filter(self, client: AsyncClient) -> None:
        """Content filter removes noise."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "content_filter": "pruning",
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_chunking(self, client: AsyncClient) -> None:
        """Chunking splits content into chunks."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "chunker": "topic",
            "chunk_max_size": 200,
        })

        data = response.json()
        assert data["success"] is True
        assert "chunks" in data

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_selectors(self, client: AsyncClient) -> None:
        """CSS selectors target specific content."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "selectors": ["h1", "p"],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_exclude_selectors(self, client: AsyncClient) -> None:
        """Exclude selectors remove elements."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "exclude_selectors": ["nav", "footer"],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_no_cache(self, client: AsyncClient) -> None:
        """Scrape with cache disabled."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "cache": False,
        })

        data = response.json()
        assert data["success"] is True
        assert data["cached"] is False


# ══════════════════════════════════════════════════════════════
# POST /scrape — Actions
# ══════════════════════════════════════════════════════════════

class TestScrapeActions:
    """Tests for scrape with page actions."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_wait_action(self, client: AsyncClient) -> None:
        """Scrape with wait action."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "actions": [
                {"type": "wait", "milliseconds": 500},
            ],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_scroll_action(self, client: AsyncClient) -> None:
        """Scrape with scroll action."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "actions": [
                {"type": "scroll", "direction": "down", "amount": 1},
            ],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_multiple_actions(self, client: AsyncClient) -> None:
        """Scrape with multiple sequential actions."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "actions": [
                {"type": "wait", "milliseconds": 200},
                {"type": "scroll", "direction": "down", "amount": 1},
                {"type": "wait", "milliseconds": 200},
            ],
        })

        data = response.json()
        assert data["success"] is True


# ══════════════════════════════════════════════════════════════
# POST /scrape — Validation
# ══════════════════════════════════════════════════════════════

class TestScrapeValidation:
    """Tests for scrape request validation."""

    @pytest.mark.asyncio
    async def test_missing_url(self, client: AsyncClient) -> None:
        """Missing URL returns 422."""
        response = await client.post("/scrape", json={})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_url(self, client: AsyncClient) -> None:
        """Empty URL returns 422."""
        response = await client.post("/scrape", json={"url": ""})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_output_format(self, client: AsyncClient) -> None:
        """Invalid output_format returns 422."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "output_format": "invalid",
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_content_filter(self, client: AsyncClient) -> None:
        """Invalid content_filter returns 422."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "content_filter": "invalid",
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_chunker(self, client: AsyncClient) -> None:
        """Invalid chunker returns 422."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
            "chunker": "invalid",
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_json_body(self, client: AsyncClient) -> None:
        """Invalid JSON returns 422."""
        response = await client.post(
            "/scrape",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_url_auto_scheme(self, client: AsyncClient) -> None:
        """URL without scheme gets https:// prepended."""
        response = await client.post("/scrape", json={
            "url": "example.com",
        })

        # Should not be a validation error
        assert response.status_code in (200, 503)


# ══════════════════════════════════════════════════════════════
# POST /scrape — Error Handling
# ══════════════════════════════════════════════════════════════

class TestScrapeErrors:
    """Tests for scrape error handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_nonexistent_domain(self, client: AsyncClient) -> None:
        """Scrape non-existent domain returns error."""
        response = await client.post("/scrape", json={
            "url": "https://this-domain-does-not-exist-12345.com",
            "timeout": 10,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] is not None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_404_page(self, client: AsyncClient) -> None:
        """Scrape 404 page returns appropriate status."""
        response = await client.post("/scrape", json={
            "url": "https://httpbin.org/status/404",
            "timeout": 15,
        })

        assert response.status_code == 200
        data = response.json()
        # May succeed with 404 status or fail
        assert data["status_code"] in (404, 0) or data["success"] is False


# ══════════════════════════════════════════════════════════════
# POST /scrape — Cache
# ══════════════════════════════════════════════════════════════

class TestScrapeCache:
    """Tests for scrape caching."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cache_hit(self, client: AsyncClient) -> None:
        """Second scrape of same URL is cached."""
        url = "https://example.com"

        # First scrape
        resp1 = await client.post("/scrape", json={
            "url": url,
            "cache": True,
        })
        data1 = resp1.json()
        assert data1["success"] is True
        assert data1["cached"] is False

        # Second scrape (should be cached)
        resp2 = await client.post("/scrape", json={
            "url": url,
            "cache": True,
        })
        data2 = resp2.json()
        assert data2["success"] is True
        assert data2["cached"] is True


# ══════════════════════════════════════════════════════════════
# POST /batch/scrape
# ══════════════════════════════════════════════════════════════

class TestBatchScrape:
    """Tests for batch scrape endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_batch_scrape_basic(self, client: AsyncClient) -> None:
        """Batch scrape multiple URLs."""
        response = await client.post("/batch/scrape", json={
            "urls": [
                "https://example.com",
                "https://www.iana.org/domains/example",
            ],
        })

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 2
        assert data["successful"] >= 1
        assert "results" in data
        assert len(data["results"]) == 2

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_batch_scrape_result_structure(self, client: AsyncClient) -> None:
        """Batch results have correct structure."""
        response = await client.post("/batch/scrape", json={
            "urls": ["https://example.com"],
        })

        data = response.json()
        result = data["results"][0]

        assert "url" in result
        assert "success" in result
        assert "word_count" in result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_batch_scrape_with_options(self, client: AsyncClient) -> None:
        """Batch scrape with configuration options."""
        response = await client.post("/batch/scrape", json={
            "urls": ["https://example.com"],
            "output_format": "markdown",
            "only_main_content": True,
            "max_concurrent": 2,
        })

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_batch_scrape_empty_urls(self, client: AsyncClient) -> None:
        """Empty URLs list returns 422."""
        response = await client.post("/batch/scrape", json={
            "urls": [],
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_batch_scrape_too_many_urls(self, client: AsyncClient) -> None:
        """Too many URLs returns 422."""
        response = await client.post("/batch/scrape", json={
            "urls": [f"https://example.com/{i}" for i in range(200)],
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_batch_scrape_mixed_success(self, client: AsyncClient) -> None:
        """Batch with valid and invalid URLs."""
        response = await client.post("/batch/scrape", json={
            "urls": [
                "https://example.com",
                "https://this-domain-does-not-exist-12345.com",
            ],
            "timeout": 10,
        })

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 2
        assert data["successful"] >= 1
        assert data["failed"] >= 0

        # Check individual results
        for result in data["results"]:
            assert "url" in result
            assert "success" in result


# ══════════════════════════════════════════════════════════════
# Response Headers
# ══════════════════════════════════════════════════════════════

class TestResponseHeaders:
    """Tests for response headers."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_response_time_header(self, client: AsyncClient) -> None:
        """Response includes X-Response-Time header."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
        })

        assert "x-response-time" in response.headers

    @pytest.mark.asyncio
    async def test_content_type_json(self, client: AsyncClient) -> None:
        """Response Content-Type is application/json."""
        response = await client.post("/scrape", json={
            "url": "https://example.com",
        })

        assert "application/json" in response.headers.get("content-type", "")
