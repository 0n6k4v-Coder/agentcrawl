"""
AgentCrawl — Crawl API Integration Tests
============================================

Integration tests for the crawl REST API endpoints.

Tests:
    - POST /crawl (start job)
    - GET /crawl/{job_id} (status/results)
    - DELETE /crawl/{job_id} (cancel)
    - Strategy selection
    - URL filtering
    - Validation errors
    - Job lifecycle
    - Concurrent crawls

Run:
    pytest tests/integration/test_crawl_api.py -v
    pytest tests/integration/test_crawl_api.py -v --run-integration
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
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

    # Use TestClient which properly handles lifespan
    with TestClient(application) as client:
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
# POST /crawl — Start Job
# ══════════════════════════════════════════════════════════════

class TestStartCrawl:
    """Tests for POST /crawl."""

    @pytest.mark.asyncio
    async def test_start_crawl_basic(self, client: AsyncClient) -> None:
        """Start a basic crawl job."""
        response = await client.post("/crawl", json={
            "url": "https://example.com",
            "strategy": "bfs",
            "max_depth": 1,
            "max_pages": 2,
        })

        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        assert data["job_id"].startswith("job_")

    @pytest.mark.asyncio
    async def test_start_crawl_returns_job_id(self, client: AsyncClient) -> None:
        """Each crawl returns a unique job ID."""
        resp1 = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 1,
        })
        resp2 = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 1,
        })

        job1 = resp1.json()["job_id"]
        job2 = resp2.json()["job_id"]
        assert job1 != job2

    @pytest.mark.asyncio
    async def test_start_crawl_default_strategy(self, client: AsyncClient) -> None:
        """Default strategy is BFS."""
        response = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 1,
        })

        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_start_crawl_all_strategies(self, client: AsyncClient) -> None:
        """All strategies are accepted."""
        strategies = ["bfs", "dfs", "best_first", "adaptive"]

        for strategy in strategies:
            response = await client.post("/crawl", json={
                "url": "https://example.com",
                "strategy": strategy,
                "max_pages": 1,
            })
            assert response.status_code == 202, f"Strategy {strategy} failed"

    @pytest.mark.asyncio
    async def test_start_crawl_with_url_filters(self, client: AsyncClient) -> None:
        """Crawl with include/exclude patterns."""
        response = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 2,
            "include_patterns": ["/*"],
            "exclude_patterns": ["*.pdf", "*.zip"],
            "same_domain": True,
        })

        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_start_crawl_with_content_options(self, client: AsyncClient) -> None:
        """Crawl with content processing options."""
        response = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 1,
            "output_format": "markdown",
            "only_main_content": True,
            "content_filter": "pruning",
        })

        assert response.status_code == 202


# ══════════════════════════════════════════════════════════════
# POST /crawl — Validation
# ══════════════════════════════════════════════════════════════

class TestCrawlValidation:
    """Tests for crawl request validation."""

    @pytest.mark.asyncio
    async def test_missing_url(self, client: AsyncClient) -> None:
        """Missing URL returns 422."""
        response = await client.post("/crawl", json={
            "max_pages": 5,
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_url(self, client: AsyncClient) -> None:
        """Empty URL returns 422."""
        response = await client.post("/crawl", json={
            "url": "",
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_strategy(self, client: AsyncClient) -> None:
        """Invalid strategy returns 422."""
        response = await client.post("/crawl", json={
            "url": "https://example.com",
            "strategy": "invalid_strategy",
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_max_pages_too_high(self, client: AsyncClient) -> None:
        """max_pages above limit returns 422."""
        response = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 10000,
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_max_depth_too_high(self, client: AsyncClient) -> None:
        """max_depth above limit returns 422."""
        response = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_depth": 100,
        })

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_json(self, client: AsyncClient) -> None:
        """Invalid JSON body returns 422."""
        response = await client.post(
            "/crawl",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422


# ══════════════════════════════════════════════════════════════
# GET /crawl/{job_id} — Status
# ══════════════════════════════════════════════════════════════

class TestGetCrawlStatus:
    """Tests for GET /crawl/{job_id}."""

    @pytest.mark.asyncio
    async def test_get_status_after_start(self, client: AsyncClient) -> None:
        """Get status immediately after starting."""
        # Start job
        start_resp = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 1,
        })
        job_id = start_resp.json()["job_id"]

        # Get status
        status_resp = await client.get(f"/crawl/{job_id}")

        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("queued", "running", "completed")

    @pytest.mark.asyncio
    async def test_get_status_nonexistent_job(self, client: AsyncClient) -> None:
        """Non-existent job returns 404."""
        response = await client.get("/crawl/job_nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_status_has_progress(self, client: AsyncClient) -> None:
        """Status includes progress information."""
        start_resp = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 2,
        })
        job_id = start_resp.json()["job_id"]

        status_resp = await client.get(f"/crawl/{job_id}")
        data = status_resp.json()

        assert "progress" in data
        assert "pages_crawled" in data
        assert "elapsed_ms" in data


# ══════════════════════════════════════════════════════════════
# Job Lifecycle
# ══════════════════════════════════════════════════════════════

class TestCrawlLifecycle:
    """Tests for complete crawl job lifecycle."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_full_lifecycle(self, client: AsyncClient) -> None:
        """Test complete job lifecycle: start → poll → complete."""
        # Start
        start_resp = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_depth": 1,
            "max_pages": 2,
        })
        assert start_resp.status_code == 202
        job_id = start_resp.json()["job_id"]

        # Poll until complete
        final_data = None
        for _ in range(30):
            status_resp = await client.get(f"/crawl/{job_id}")
            data = status_resp.json()

            if data["status"] in ("completed", "failed", "cancelled"):
                final_data = data
                break

            await asyncio.sleep(1)

        assert final_data is not None, "Job did not complete in time"
        assert final_data["status"] == "completed"
        assert final_data["total_pages"] >= 1

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_completed_job_has_pages(self, client: AsyncClient) -> None:
        """Completed job includes page results."""
        start_resp = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 1,
        })
        job_id = start_resp.json()["job_id"]

        # Wait for completion
        for _ in range(30):
            resp = await client.get(f"/crawl/{job_id}")
            data = resp.json()
            if data["status"] == "completed":
                break
            await asyncio.sleep(1)

        assert data["status"] == "completed"
        assert "pages" in data
        assert len(data["pages"]) >= 1

        page = data["pages"][0]
        assert "url" in page
        assert "success" in page


# ══════════════════════════════════════════════════════════════
# DELETE /crawl/{job_id} — Cancel
# ══════════════════════════════════════════════════════════════

class TestCancelCrawl:
    """Tests for DELETE /crawl/{job_id}."""

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self, client: AsyncClient) -> None:
        """Cancel non-existent job returns 404."""
        response = await client.delete("/crawl/job_nonexistent")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_returns_status(self, client: AsyncClient) -> None:
        """Cancel returns job status."""
        start_resp = await client.post("/crawl", json={
            "url": "https://example.com",
            "max_pages": 50,
            "max_depth": 5,
        })
        job_id = start_resp.json()["job_id"]

        cancel_resp = await client.delete(f"/crawl/{job_id}")

        # May be 200 (cancelled) or 400 (already finished)
        assert cancel_resp.status_code in (200, 400)


# ══════════════════════════════════════════════════════════════
# Concurrent Crawls
# ══════════════════════════════════════════════════════════════

class TestConcurrentCrawls:
    """Tests for concurrent crawl jobs."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_jobs(self, client: AsyncClient) -> None:
        """Multiple crawl jobs can run concurrently."""
        job_ids = []

        # Start 3 jobs
        for i in range(3):
            resp = await client.post("/crawl", json={
                "url": "https://example.com",
                "max_pages": 1,
            })
            assert resp.status_code == 202
            job_ids.append(resp.json()["job_id"])

        # All should have unique IDs
        assert len(set(job_ids)) == 3

        # All should be queryable
        for job_id in job_ids:
            resp = await client.get(f"/crawl/{job_id}")
            assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════
# Strategy-Specific Tests
# ══════════════════════════════════════════════════════════════

class TestCrawlStrategies:
    """Tests for specific crawl strategies."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.parametrize("strategy", ["bfs", "dfs", "best_first", "adaptive"])
    async def test_strategy_completes(
        self,
        client: AsyncClient,
        strategy: str,
    ) -> None:
        """Each strategy completes successfully."""
        start_resp = await client.post("/crawl", json={
            "url": "https://example.com",
            "strategy": strategy,
            "max_depth": 1,
            "max_pages": 2,
        })
        assert start_resp.status_code == 202
        job_id = start_resp.json()["job_id"]

        # Wait for completion
        for _ in range(30):
            resp = await client.get(f"/crawl/{job_id}")
            data = resp.json()
            if data["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(1)

        assert data["status"] == "completed", f"Strategy {strategy} failed: {data.get('error')}"


# ══════════════════════════════════════════════════════════════
# Error Handling
# ══════════════════════════════════════════════════════════════

class TestCrawlErrors:
    """Tests for crawl error handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_crawl_invalid_url(self, client: AsyncClient) -> None:
        """Crawl with invalid URL fails gracefully."""
        start_resp = await client.post("/crawl", json={
            "url": "https://this-domain-does-not-exist-12345.com",
            "max_pages": 1,
        })

        if start_resp.status_code == 202:
            job_id = start_resp.json()["job_id"]

            # Wait for result
            for _ in range(15):
                resp = await client.get(f"/crawl/{job_id}")
                data = resp.json()
                if data["status"] in ("completed", "failed"):
                    break
                await asyncio.sleep(1)

            # Should fail or complete with 0 pages
            assert data["status"] in ("completed", "failed")

    @pytest.mark.asyncio
    async def test_crawl_method_not_allowed(self, client: AsyncClient) -> None:
        """GET /crawl (without job_id) returns 405."""
        response = await client.get("/crawl")

        # FastAPI returns 405 for wrong method
        assert response.status_code in (404, 405)
