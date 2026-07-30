"""
AgentCrawl — Search API Integration Tests
=============================================

Integration tests for the search REST API endpoint.

Tests:
    - POST /search (basic search)
    - Provider selection
    - Result limits
    - Validation errors
    - Scrape results option
    - Response structure
    - Error handling

Run:
    pytest tests/integration/test_search_api.py -v
    pytest tests/integration/test_search_api.py -v --run-integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def app() -> AsyncGenerator[Any, None]:
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
# POST /search — Basic
# ══════════════════════════════════════════════════════════════

class TestSearchBasic:
    """Tests for basic search operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_basic(self, client: AsyncClient) -> None:
        """Basic search returns results."""
        response = await client.post("/search", json={
            "query": "python programming",
        })

        assert response.status_code == 200
        data = response.json()

        assert data["query"] == "python programming"
        assert "results" in data
        assert data["total_results"] >= 0
        assert "provider" in data
        assert "duration_ms" in data

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_returns_results(self, client: AsyncClient) -> None:
        """Search returns structured results."""
        response = await client.post("/search", json={
            "query": "python asyncio tutorial",
            "max_results": 3,
        })

        data = response.json()
        assert data["total_results"] >= 1

        for result in data["results"]:
            assert "url" in result
            assert "title" in result
            assert "snippet" in result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_result_has_url(self, client: AsyncClient) -> None:
        """Each result has a valid URL."""
        response = await client.post("/search", json={
            "query": "python docs",
            "max_results": 3,
        })

        data = response.json()
        for result in data["results"]:
            url = result.get("url", "")
            assert url.startswith("http"), f"Invalid URL: {url}"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_default_provider(self, client: AsyncClient) -> None:
        """Default provider is duckduckgo."""
        response = await client.post("/search", json={
            "query": "test query",
        })

        data = response.json()
        assert data["provider"] == "duckduckgo"


# ══════════════════════════════════════════════════════════════
# POST /search — Max Results
# ══════════════════════════════════════════════════════════════

class TestSearchMaxResults:
    """Tests for result limiting."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_max_results_respected(self, client: AsyncClient) -> None:
        """max_results limits the number of results."""
        response = await client.post("/search", json={
            "query": "python programming",
            "max_results": 2,
        })

        data = response.json()
        assert len(data["results"]) <= 2

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_max_results_one(self, client: AsyncClient) -> None:
        """max_results=1 returns at most 1 result."""
        response = await client.post("/search", json={
            "query": "python",
            "max_results": 1,
        })

        data = response.json()
        assert len(data["results"]) <= 1


# ══════════════════════════════════════════════════════════════
# POST /search — Providers
# ══════════════════════════════════════════════════════════════

class TestSearchProviders:
    """Tests for search provider selection."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_duckduckgo_provider(self, client: AsyncClient) -> None:
        """DuckDuckGo provider works."""
        response = await client.post("/search", json={
            "query": "python tutorial",
            "provider": "duckduckgo",
            "max_results": 3,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "duckduckgo"

    @pytest.mark.asyncio
    async def test_invalid_provider(self, client: AsyncClient) -> None:
        """Invalid provider returns 422."""
        response = await client.post("/search", json={
            "query": "test",
            "provider": "nonexistent_provider",
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_provider_without_api_key(self, client: AsyncClient) -> None:
        """Provider requiring API key fails gracefully without one."""
        response = await client.post("/search", json={
            "query": "test",
            "provider": "tavily",
        })

        # Should return 200 with error or 500
        assert response.status_code in (200, 422, 500)


# ══════════════════════════════════════════════════════════════
# POST /search — Validation
# ══════════════════════════════════════════════════════════════

class TestSearchValidation:
    """Tests for search request validation."""

    @pytest.mark.asyncio
    async def test_missing_query(self, client: AsyncClient) -> None:
        """Missing query returns 422."""
        response = await client.post("/search", json={})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_query(self, client: AsyncClient) -> None:
        """Empty query returns 422."""
        response = await client.post("/search", json={"query": ""})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_max_results_too_high(self, client: AsyncClient) -> None:
        """max_results above limit returns 422."""
        response = await client.post("/search", json={
            "query": "test",
            "max_results": 1000,
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_max_results_zero(self, client: AsyncClient) -> None:
        """max_results=0 returns 422."""
        response = await client.post("/search", json={
            "query": "test",
            "max_results": 0,
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_time_range(self, client: AsyncClient) -> None:
        """Invalid time_range returns 422."""
        response = await client.post("/search", json={
            "query": "test",
            "time_range": "invalid_range",
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_json_body(self, client: AsyncClient) -> None:
        """Invalid JSON returns 422."""
        response = await client.post(
            "/search",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422


# ══════════════════════════════════════════════════════════════
# POST /search — Options
# ══════════════════════════════════════════════════════════════

class TestSearchOptions:
    """Tests for search options."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_with_language(self, client: AsyncClient) -> None:
        """Search with language parameter."""
        response = await client.post("/search", json={
            "query": "python programming",
            "language": "en",
            "max_results": 3,
        })

        assert response.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_with_time_range(self, client: AsyncClient) -> None:
        """Search with time range filter."""
        response = await client.post("/search", json={
            "query": "python release",
            "time_range": "year",
            "max_results": 3,
        })

        assert response.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_with_scrape_results(self, client: AsyncClient) -> None:
        """Search with scrape_results=True."""
        response = await client.post("/search", json={
            "query": "python asyncio",
            "max_results": 2,
            "scrape_results": True,
        })

        assert response.status_code == 200
        data = response.json()

        # Results may have scraped content
        for result in data["results"]:
            if result.get("scrape_success") is True:
                assert "markdown" in result


# ══════════════════════════════════════════════════════════════
# POST /search — Response Structure
# ══════════════════════════════════════════════════════════════

class TestSearchResponseStructure:
    """Tests for search response structure."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_response_has_all_fields(self, client: AsyncClient) -> None:
        """Response includes all expected fields."""
        response = await client.post("/search", json={
            "query": "python",
            "max_results": 3,
        })

        data = response.json()

        assert "query" in data
        assert "results" in data
        assert "total_results" in data
        assert "provider" in data
        assert "duration_ms" in data

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_result_item_structure(self, client: AsyncClient) -> None:
        """Each result item has expected fields."""
        response = await client.post("/search", json={
            "query": "python docs",
            "max_results": 3,
        })

        data = response.json()
        if data["results"]:
            result = data["results"][0]
            assert "url" in result
            assert "title" in result
            assert "snippet" in result
            assert "position" in result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_duration_is_positive(self, client: AsyncClient) -> None:
        """Duration is a positive number."""
        response = await client.post("/search", json={
            "query": "test",
        })

        data = response.json()
        assert data["duration_ms"] >= 0


# ══════════════════════════════════════════════════════════════
# POST /search — Error Handling
# ══════════════════════════════════════════════════════════════

class TestSearchErrors:
    """Tests for search error handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_search_no_results(self, client: AsyncClient) -> None:
        """Search with obscure query returns empty results."""
        response = await client.post("/search", json={
            "query": "xyzzyplughtwistyNoSuchThing12345",
            "max_results": 5,
        })

        assert response.status_code == 200
        data = response.json()
        # May have 0 results
        assert data["total_results"] >= 0

    @pytest.mark.asyncio
    async def test_search_method_not_allowed(self, client: AsyncClient) -> None:
        """GET /search returns 405."""
        response = await client.get("/search")

        assert response.status_code in (404, 405)


# ══════════════════════════════════════════════════════════════
# Concurrent Searches
# ══════════════════════════════════════════════════════════════

class TestConcurrentSearch:
    """Tests for concurrent search operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_searches(self, client: AsyncClient) -> None:
        """Multiple concurrent searches work."""
        import asyncio

        queries = [
            "python tutorial",
            "javascript guide",
            "rust programming",
        ]

        tasks = [
            client.post("/search", json={"query": q, "max_results": 2})
            for q in queries
        ]

        responses = await asyncio.gather(*tasks)

        for resp in responses:
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
