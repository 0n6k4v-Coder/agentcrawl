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

from typing import Any

import pytest
from fastapi.testclient import TestClient

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
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

    return create_app(settings)


@pytest.fixture
def client(app: Any) -> Any:
    """Create a test client using TestClient."""
    with TestClient(app) as test_client:
        yield test_client


# ══════════════════════════════════════════════════════════════
# POST /crawl — Start Job
# ══════════════════════════════════════════════════════════════


class TestStartCrawl:
    """Tests for POST /crawl."""

    @pytest.mark.integration
    def test_start_crawl_basic(self, client: TestClient, require_playwright) -> None:
        """Start a basic crawl job."""
        response = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "strategy": "bfs",
                "max_depth": 1,
                "max_pages": 2,
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        assert data["job_id"].startswith("job_")

    @pytest.mark.integration
    def test_start_crawl_returns_job_id(self, client: TestClient, require_playwright) -> None:
        """Each crawl returns a unique job ID."""
        resp1 = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 1,
            },
        )
        resp2 = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 1,
            },
        )

        job1 = resp1.json()["job_id"]
        job2 = resp2.json()["job_id"]
        assert job1 != job2

    @pytest.mark.integration
    def test_start_crawl_default_strategy(self, client: TestClient, require_playwright) -> None:
        """Default strategy is BFS."""
        response = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 1,
            },
        )

        assert response.status_code == 202

    @pytest.mark.integration
    def test_start_crawl_all_strategies(self, client: TestClient, require_playwright) -> None:
        """All strategies are accepted."""
        strategies = ["bfs", "dfs", "best_first", "adaptive"]

        for strategy in strategies:
            response = client.post(
                "/crawl",
                json={
                    "url": "https://example.com",
                    "strategy": strategy,
                    "max_pages": 1,
                },
            )
            assert response.status_code == 202, f"Strategy {strategy} failed"

    @pytest.mark.integration
    def test_start_crawl_with_url_filters(self, client: TestClient, require_playwright) -> None:
        """Crawl with include/exclude patterns."""
        response = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 2,
                "include_patterns": ["/*"],
                "exclude_patterns": ["*.pdf", "*.zip"],
                "same_domain": True,
            },
        )

        assert response.status_code == 202

    @pytest.mark.integration
    def test_start_crawl_with_content_options(self, client: TestClient, require_playwright) -> None:
        """Crawl with content processing options."""
        response = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 1,
                "output_format": "markdown",
                "only_main_content": True,
                "content_filter": "pruning",
            },
        )

        assert response.status_code == 202


# ══════════════════════════════════════════════════════════════
# POST /crawl — Validation
# ══════════════════════════════════════════════════════════════


class TestCrawlValidation:
    """Tests for crawl request validation."""

    def test_missing_url(self, client: TestClient) -> None:
        """Missing URL returns 422."""
        response = client.post(
            "/crawl",
            json={
                "max_pages": 5,
            },
        )

        assert response.status_code == 422

    def test_empty_url(self, client: TestClient) -> None:
        """Empty URL returns 422."""
        response = client.post("/crawl", json={"url": ""})

        assert response.status_code == 422

    def test_invalid_strategy(self, client: TestClient) -> None:
        """Invalid strategy returns 422."""
        response = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "strategy": "invalid_strategy",
            },
        )

        assert response.status_code == 422

    def test_max_pages_too_high(self, client: TestClient) -> None:
        """max_pages above limit returns 422."""
        response = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 10000,
            },
        )

        assert response.status_code == 422

    def test_max_depth_too_high(self, client: TestClient) -> None:
        """max_depth above limit returns 422."""
        response = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_depth": 100,
            },
        )

        assert response.status_code == 422

    def test_invalid_json(self, client: TestClient) -> None:
        """Invalid JSON body returns 422."""
        response = client.post(
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

    def test_get_status_after_start(self, client: TestClient) -> None:
        """Get status immediately after starting."""
        # Start job
        start_resp = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 1,
            },
        )
        job_id = start_resp.json()["job_id"]

        # Get status
        status_resp = client.get(f"/crawl/{job_id}")

        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("queued", "running", "completed")

    def test_get_status_nonexistent_job(self, client: TestClient) -> None:
        """Non-existent job returns 404."""
        response = client.get("/crawl/job_nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    def test_status_has_progress(self, client: TestClient) -> None:
        """Status includes progress information."""
        start_resp = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 2,
            },
        )
        job_id = start_resp.json()["job_id"]

        status_resp = client.get(f"/crawl/{job_id}")
        data = status_resp.json()

        assert "progress" in data
        assert "pages_crawled" in data
        assert "elapsed_ms" in data


# ══════════════════════════════════════════════════════════════
# Job Lifecycle
# ══════════════════════════════════════════════════════════════


class TestCrawlLifecycle:
    """Tests for complete crawl job lifecycle."""

    @pytest.mark.integration
    def test_full_lifecycle(self, client: TestClient, require_playwright) -> None:
        """Test complete job lifecycle: start -> poll -> complete."""
        # Start
        start_resp = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_depth": 1,
                "max_pages": 2,
            },
        )
        assert start_resp.status_code == 202
        job_id = start_resp.json()["job_id"]

        # Poll until complete
        final_data = None
        for _ in range(30):
            status_resp = client.get(f"/crawl/{job_id}")
            data = status_resp.json()

            if data["status"] in ("completed", "failed", "cancelled"):
                final_data = data
                break

            import time

            time.sleep(1)

        assert final_data is not None, "Job did not complete in time"
        assert final_data["status"] == "completed"
        assert final_data["total_pages"] >= 1

    @pytest.mark.integration
    def test_completed_job_has_pages(self, client: TestClient, require_playwright) -> None:
        """Completed job includes page results."""
        start_resp = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 1,
            },
        )
        job_id = start_resp.json()["job_id"]

        # Wait for completion
        for _ in range(30):
            resp = client.get(f"/crawl/{job_id}")
            data = resp.json()
            if data["status"] == "completed":
                break
            import time

            time.sleep(1)

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

    def test_cancel_nonexistent_job(self, client: TestClient) -> None:
        """Cancel non-existent job returns 404."""
        response = client.delete("/crawl/job_nonexistent")

        assert response.status_code == 404

    def test_cancel_returns_status(self, client: TestClient) -> None:
        """Cancel returns job status."""
        start_resp = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "max_pages": 50,
                "max_depth": 5,
            },
        )
        job_id = start_resp.json()["job_id"]

        cancel_resp = client.delete(f"/crawl/{job_id}")

        # May be 200 (cancelled) or 400 (already finished)
        assert cancel_resp.status_code in (200, 400)


# ══════════════════════════════════════════════════════════════
# Concurrent Crawls
# ══════════════════════════════════════════════════════════════


class TestConcurrentCrawls:
    """Tests for concurrent crawl jobs."""

    def test_multiple_concurrent_jobs(self, client: TestClient) -> None:
        """Multiple crawl jobs can run concurrently."""
        job_ids = []

        # Start 3 jobs
        for _i in range(3):
            resp = client.post(
                "/crawl",
                json={
                    "url": "https://example.com",
                    "max_pages": 1,
                },
            )
            assert resp.status_code == 202
            job_ids.append(resp.json()["job_id"])

        # All should have unique IDs
        assert len(set(job_ids)) == 3

        # All should be queryable
        for job_id in job_ids:
            resp = client.get(f"/crawl/{job_id}")
            assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════
# Strategy-Specific Tests
# ══════════════════════════════════════════════════════════════


class TestCrawlStrategies:
    """Tests for specific crawl strategies."""

    @pytest.mark.integration
    @pytest.mark.parametrize("strategy", ["bfs", "dfs", "best_first", "adaptive"])
    def test_strategy_completes(
        self,
        client: TestClient,
        strategy: str,
        require_playwright,
    ) -> None:
        """Each strategy completes successfully."""
        start_resp = client.post(
            "/crawl",
            json={
                "url": "https://example.com",
                "strategy": strategy,
                "max_depth": 1,
                "max_pages": 2,
            },
        )
        assert start_resp.status_code == 202
        job_id = start_resp.json()["job_id"]

        # Wait for completion
        for _ in range(30):
            resp = client.get(f"/crawl/{job_id}")
            data = resp.json()
            if data["status"] in ("completed", "failed"):
                break
            import time

            time.sleep(1)

        assert data["status"] == "completed", f"Strategy {strategy} failed: {data.get('error')}"


# ══════════════════════════════════════════════════════════════
# Error Handling
# ══════════════════════════════════════════════════════════════


class TestCrawlErrors:
    """Tests for crawl error handling."""

    @pytest.mark.integration
    def test_crawl_invalid_url(self, client: TestClient, require_playwright) -> None:
        """Crawl with invalid URL fails gracefully."""
        start_resp = client.post(
            "/crawl",
            json={
                "url": "https://this-domain-does-not-exist-12345.com",
                "max_pages": 1,
            },
        )

        if start_resp.status_code == 202:
            job_id = start_resp.json()["job_id"]

            # Wait for result
            for _ in range(15):
                resp = client.get(f"/crawl/{job_id}")
                data = resp.json()
                if data["status"] in ("completed", "failed"):
                    break
                import time

                time.sleep(1)

            # Should fail or complete with 0 pages
            assert data["status"] in ("completed", "failed")

    def test_crawl_method_not_allowed(self, client: TestClient) -> None:
        """GET /crawl (without job_id) returns 405."""
        response = client.get("/crawl")

        # FastAPI returns 405 for wrong method
        assert response.status_code in (404, 405)
