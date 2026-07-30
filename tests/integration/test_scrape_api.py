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

from typing import Any

import pytest
from fastapi.testclient import TestClient

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@ pytest.fixture
def app(require_playwright) -> Any:
    """Create a test FastAPI app."""
    from server.app import create_app

    from agentcrawl.config.settings import Settings

    settings = Settings(
        log_level="WARNING",
        headless=True,
        cache_backend="memory",
        cache_ttl=60,
        auth_enabled=False,
    )

    application = create_app(settings)

    # Use TestClient which properly handles lifespan
    with TestClient(application):
        yield application


@ pytest.fixture
def client(app: Any) -> Any:
    """Create a test client using TestClient."""
    with TestClient(app) as test_client:
        yield test_client


# ══════════════════════════════════════════════════════════════
# POST /scrape — Basic
# ══════════════════════════════════════════════════════════════

class TestScrapeBasic:
    """Tests for basic scrape operations."""

    @pytest.mark.integration
    def test_scrape_example_com(self, client: TestClient, require_playwright) -> None:
        """Scrape example.com successfully."""
        response = client.post("/scrape", json={
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

    @pytest.mark.integration
    def test_scrape_returns_markdown(self, client: TestClient, require_playwright) -> None:
        """Scrape returns Markdown content."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "output_format": "markdown",
        })

        data = response.json()
        assert data["success"] is True
        assert "markdown" in data
        assert "Example Domain" in data["markdown"]

    @pytest.mark.integration
    def test_scrape_returns_metadata(self, client: TestClient, require_playwright) -> None:
        """Scrape includes page metadata."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "include_metadata": True,
        })

        data = response.json()
        assert data["success"] is True
        assert "metadata" in data
        assert "title" in data["metadata"]

    @pytest.mark.integration
    def test_scrape_returns_links(self, client: TestClient, require_playwright) -> None:
        """Scrape includes extracted links."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "include_links": True,
        })

        data = response.json()
        assert data["success"] is True
        assert "links" in data

    @pytest.mark.integration
    def test_scrape_has_request_id(self, client: TestClient, require_playwright) -> None:
        """Scrape response includes request ID."""
        response = client.post("/scrape", json={
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
    async def test_scrape_only_main_content(self, client: TestClient, require_playwright) -> None:
        """only_main_content filters navigation/footer."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "only_main_content": True,
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_content_filter(self, client: TestClient, require_playwright) -> None:
        """Content filter removes noise."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "content_filter": "pruning",
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_chunking(self, client: TestClient, require_playwright) -> None:
        """Chunking splits content into chunks."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "chunker": "topic",
            "chunk_max_size": 200,
        })

        data = response.json()
        assert data["success"] is True
        assert "chunks" in data

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_selectors(self, client: TestClient, require_playwright) -> None:
        """CSS selectors target specific content."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "selectors": ["h1", "p"],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_with_exclude_selectors(self, client: TestClient, require_playwright) -> None:
        """Exclude selectors remove elements."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "exclude_selectors": ["nav", "footer"],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scrape_no_cache(self, client: TestClient, require_playwright) -> None:
        """Scrape with cache disabled."""
        response = client.post("/scrape", json={
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

    @pytest.mark.integration
    def test_scrape_with_wait_action(self, client: TestClient, require_playwright) -> None:
        """Scrape with wait action."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "actions": [
                {"type": "wait", "milliseconds": 500},
            ],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.integration
    def test_scrape_with_scroll_action(self, client: TestClient, require_playwright) -> None:
        """Scrape with scroll action."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "actions": [
                {"type": "scroll", "direction": "down", "amount": 1},
            ],
        })

        data = response.json()
        assert data["success"] is True

    @pytest.mark.integration
    def test_scrape_with_multiple_actions(self, client: TestClient, require_playwright) -> None:
        """Scrape with multiple sequential actions."""
        response = client.post("/scrape", json={
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

    def test_missing_url(self, client: TestClient) -> None:
        """Missing URL returns 422."""
        response = client.post("/scrape", json={})

        assert response.status_code == 422

    def test_empty_url(self, client: TestClient) -> None:
        """Empty URL returns 422."""
        response = client.post("/scrape", json={"url": ""})

        assert response.status_code == 422

    def test_invalid_output_format(self, client: TestClient) -> None:
        """Invalid output_format returns 422."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "output_format": "invalid",
        })

        assert response.status_code == 422

    def test_invalid_content_filter(self, client: TestClient) -> None:
        """Invalid content_filter returns 422."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "content_filter": "invalid",
        })

        assert response.status_code == 422

    def test_invalid_chunker(self, client: TestClient) -> None:
        """Invalid chunker returns 422."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
            "chunker": "invalid",
        })

        assert response.status_code == 422

    def test_invalid_json_body(self, client: TestClient) -> None:
        """Invalid JSON returns 422."""
        response = client.post(
            "/scrape",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422

    @pytest.mark.integration
    def test_url_auto_scheme(self, client: TestClient, require_playwright) -> None:
        """URL without scheme gets https:// prepended."""
        response = client.post("/scrape", json={
            "url": "example.com",
        })

        # Should not be a validation error
        assert response.status_code in (200, 503)


# ══════════════════════════════════════════════════════════════
# POST /scrape — Error Handling
# ══════════════════════════════════════════════════════════════

class TestScrapeErrors:
    """Tests for scrape error handling."""

    @pytest.mark.integration
    def test_scrape_nonexistent_domain(self, client: TestClient, require_playwright) -> None:
        """Scrape non-existent domain returns error."""
        response = client.post("/scrape", json={
            "url": "https://this-domain-does-not-exist-12345.com",
            "timeout": 10,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] is not None

    @pytest.mark.integration
    def test_scrape_404_page(self, client: TestClient, require_playwright) -> None:
        """Scrape 404 page returns appropriate status."""
        response = client.post("/scrape", json={
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

    @pytest.mark.integration
    def test_cache_hit(self, client: TestClient, require_playwright) -> None:
        """Second scrape of same URL is cached."""
        url = "https://example.com"

        # First scrape
        resp1 = client.post("/scrape", json={
            "url": url,
            "cache": True,
        })
        data1 = resp1.json()
        assert data1["success"] is True
        assert data1["cached"] is False

        # Second scrape (should be cached)
        resp2 = client.post("/scrape", json={
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

    @pytest.mark.integration
    def test_batch_scrape_basic(self, client: TestClient, require_playwright) -> None:
        """Batch scrape multiple URLs."""
        response = client.post("/batch/scrape", json={
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

    @pytest.mark.integration
    def test_batch_scrape_result_structure(self, client: TestClient, require_playwright) -> None:
        """Batch results have correct structure."""
        response = client.post("/batch/scrape", json={
            "urls": ["https://example.com"],
        })

        data = response.json()
        result = data["results"][0]

        assert "url" in result
        assert "success" in result
        assert "word_count" in result

    @pytest.mark.integration
    def test_batch_scrape_with_options(self, client: TestClient, require_playwright) -> None:
        """Batch scrape with configuration options."""
        response = client.post("/batch/scrape", json={
            "urls": ["https://example.com"],
            "output_format": "markdown",
            "only_main_content": True,
            "max_concurrent": 2,
        })

        assert response.status_code == 200

    def test_batch_scrape_empty_urls(self, client: TestClient) -> None:
        """Empty URLs list returns 422."""
        response = client.post("/batch/scrape", json={
            "urls": [],
        })

        assert response.status_code == 422

    def test_batch_scrape_too_many_urls(self, client: TestClient) -> None:
        """Too many URLs returns 422."""
        response = client.post("/batch/scrape", json={
            "urls": [f"https://example.com/{i}" for i in range(200)],
        })

        assert response.status_code == 422

    @pytest.mark.integration
    def test_batch_scrape_mixed_success(self, client: TestClient, require_playwright) -> None:
        """Batch with valid and invalid URLs."""
        response = client.post("/batch/scrape", json={
            "urls": [
                "https://example.com",
                "https://this-domain-does-not-exist-12345.com",
            ],
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

    @pytest.mark.integration
    def test_response_time_header(self, client: TestClient) -> None:
        """Response includes X-Response-Time header."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
        })

        assert "x-response-time" in response.headers

    def test_content_type_json(self, client: TestClient) -> None:
        """Response Content-Type is application/json."""
        response = client.post("/scrape", json={
            "url": "https://example.com",
        })

        assert "application/json" in response.headers.get("content-type", "")
