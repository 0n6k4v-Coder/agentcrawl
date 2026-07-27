"""
AgentCrawl — Crawl API Routes
=================================

Handles asynchronous crawl job management via the REST API.

Endpoints:
    POST   /crawl           — Start a crawl job
    GET    /crawl/{job_id}  — Get crawl job status/results
    DELETE /crawl/{job_id}  — Cancel a crawl job

Usage:
    Registered automatically by server/app.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("agentcrawl.server.crawl")


# ══════════════════════════════════════════════════════════════
# Job Management
# ══════════════════════════════════════════════════════════════

class JobStatus(str, Enum):
    """Crawl job status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CrawlJob:
    """
    Internal crawl job record.

    Attributes:
        job_id: Unique job identifier.
        status: Current job status.
        start_url: Starting URL.
        strategy: Crawl strategy name.
        config: Crawl configuration.
        created_at: Creation timestamp.
        started_at: Start timestamp.
        completed_at: Completion timestamp.
        pages_crawled: Number of pages crawled so far.
        pages_failed: Number of failed pages.
        total_pages: Total pages in final result.
        total_words: Total words in final result.
        total_tokens: Total tokens in final result.
        duration_ms: Total duration.
        result: Final CrawlJobResult (serialized).
        error: Error message (if failed).
        task: Background asyncio task.
    """
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    start_url: str = ""
    strategy: str = "bfs"
    config: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    pages_crawled: int = 0
    pages_failed: int = 0
    total_pages: int = 0
    total_words: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def progress(self) -> float:
        """Progress ratio (0.0 to 1.0)."""
        if self.total_pages > 0:
            return self.pages_crawled / self.total_pages
        return 0.0

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds."""
        if self.started_at == 0:
            return 0.0
        end = self.completed_at if self.completed_at > 0 else time.time()
        return (end - self.started_at) * 1000

    def to_status_dict(self) -> dict[str, Any]:
        """Serialize to status dictionary (no full results)."""
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "start_url": self.start_url,
            "strategy": self.strategy,
            "pages_crawled": self.pages_crawled,
            "pages_failed": self.pages_failed,
            "total_pages": self.total_pages,
            "progress": round(self.progress, 3),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "created_at": self.created_at,
        }

    def to_result_dict(self) -> dict[str, Any]:
        """Serialize to full result dictionary."""
        data = self.to_status_dict()
        data.update({
            "total_words": self.total_words,
            "total_tokens": self.total_tokens,
            "duration_ms": round(self.duration_ms, 1),
            "error": self.error,
        })

        if self.result:
            data["pages"] = self.result.get("pages", [])

        return data


# In-memory job store
_jobs: dict[str, CrawlJob] = {}


def _get_job(job_id: str) -> CrawlJob | None:
    """Get a job by ID."""
    return _jobs.get(job_id)


def _create_job(
    start_url: str,
    strategy: str,
    config: dict[str, Any],
) -> CrawlJob:
    """Create and register a new job."""
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    job = CrawlJob(
        job_id=job_id,
        start_url=start_url,
        strategy=strategy,
        config=config,
    )
    _jobs[job_id] = job

    # Cleanup old jobs (keep last 100)
    if len(_jobs) > 100:
        sorted_jobs = sorted(_jobs.values(), key=lambda j: j.created_at)
        for old_job in sorted_jobs[:len(_jobs) - 100]:
            if old_job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                del _jobs[old_job.job_id]

    return job


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class CrawlRequest(BaseModel):
    """Request body for POST /crawl."""

    url: str = Field(..., description="Starting URL to crawl")
    strategy: str = Field(
        default="bfs",
        description="Crawl strategy: bfs, dfs, best_first, adaptive",
    )
    max_depth: int = Field(default=3, ge=1, le=10, description="Maximum link depth")
    max_pages: int = Field(default=50, ge=1, le=500, description="Maximum pages to crawl")
    max_concurrent: int = Field(default=5, ge=1, le=20, description="Concurrent fetches")
    output_format: str = Field(default="markdown", description="Output format")
    include_links: bool = Field(default=True, description="Include links")
    only_main_content: bool = Field(default=True, description="Only main content")
    content_filter: str = Field(default="none", description="Content filter")
    include_patterns: list[str] = Field(default_factory=list, description="URL include patterns")
    exclude_patterns: list[str] = Field(default_factory=list, description="URL exclude patterns")
    same_domain: bool = Field(default=True, description="Restrict to same domain")


# ══════════════════════════════════════════════════════════════
# Handlers
# ══════════════════════════════════════════════════════════════

async def handle_start_crawl(
    engine: Any,
    body: dict[str, Any],
) -> JSONResponse:
    """
    Handle POST /crawl — start an async crawl job.

    Args:
        engine: CrawlEngine instance.
        body: Request body.

    Returns:
        202 with job_id.
    """
    # Validate
    try:
        request = CrawlRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": str(e)}},
        )

    if engine is None or not engine.is_started:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "SERVICE_UNAVAILABLE", "message": "Engine not started"}},
        )

    # Create job
    job = _create_job(
        start_url=request.url,
        strategy=request.strategy,
        config=body,
    )

    # Start background task
    job.task = asyncio.create_task(
        _run_crawl_job(engine, job, request)
    )

    logger.info(
        "Crawl job started: %s (%s, max_depth=%d, max_pages=%d)",
        job.job_id,
        request.strategy,
        request.max_depth,
        request.max_pages,
    )

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.job_id,
            "status": job.status.value,
            "message": "Crawl job queued",
        },
    )


async def handle_get_crawl(job_id: str) -> JSONResponse:
    """
    Handle GET /crawl/{job_id} — get job status/results.

    Args:
        job_id: Job identifier.

    Returns:
        Job status or full results.
    """
    job = _get_job(job_id)

    if job is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "JOB_NOT_FOUND", "message": f"Job not found: {job_id}"}},
        )

    # Return status for in-progress jobs, full results for completed
    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        return JSONResponse(status_code=200, content=job.to_status_dict())
    else:
        return JSONResponse(status_code=200, content=job.to_result_dict())


async def handle_cancel_crawl(job_id: str) -> JSONResponse:
    """
    Handle DELETE /crawl/{job_id} — cancel a job.

    Args:
        job_id: Job identifier.

    Returns:
        Cancellation result.
    """
    job = _get_job(job_id)

    if job is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "JOB_NOT_FOUND", "message": f"Job not found: {job_id}"}},
        )

    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "JOB_ALREADY_FINISHED",
                    "message": f"Job already {job.status.value}",
                }
            },
        )

    # Cancel the task
    if job.task and not job.task.done():
        job.task.cancel()

    job.status = JobStatus.CANCELLED
    job.completed_at = time.time()

    logger.info("Crawl job cancelled: %s (pages_crawled=%d)", job_id, job.pages_crawled)

    return JSONResponse(
        status_code=200,
        content={
            "job_id": job_id,
            "status": "cancelled",
            "pages_crawled": job.pages_crawled,
        },
    )


# ══════════════════════════════════════════════════════════════
# Background Job Runner
# ══════════════════════════════════════════════════════════════

async def _run_crawl_job(
    engine: Any,
    job: CrawlJob,
    request: CrawlRequest,
) -> None:
    """
    Execute a crawl job in the background.

    Args:
        engine: CrawlEngine instance.
        job: CrawlJob record.
        request: Validated request.
    """
    from agentcrawl.config.crawler_config import CrawlerConfig
    from agentcrawl.crawling.bfs import BFSCrawler
    from agentcrawl.crawling.dfs import DFSCrawler
    from agentcrawl.crawling.best_first import BestFirstCrawler
    from agentcrawl.crawling.adaptive import AdaptiveCrawler
    from agentcrawl.crawling.url_filter import URLFilter

    job.status = JobStatus.RUNNING
    job.started_at = time.time()

    try:
        # Build strategy
        strategies = {
            "bfs": BFSCrawler,
            "dfs": DFSCrawler,
            "best_first": BestFirstCrawler,
            "adaptive": AdaptiveCrawler,
        }

        strategy_cls = strategies.get(request.strategy, BFSCrawler)

        strategy_kwargs: dict[str, Any] = {
            "max_depth": request.max_depth,
            "max_pages": request.max_pages,
        }

        if hasattr(strategy_cls, "max_concurrent"):
            strategy_kwargs["max_concurrent"] = request.max_concurrent

        # URL filter
        if request.include_patterns or request.exclude_patterns or request.same_domain:
            url_filter = URLFilter(
                include_patterns=request.include_patterns,
                exclude_patterns=request.exclude_patterns,
                same_domain=request.same_domain,
            )
            strategy_kwargs["url_filter"] = url_filter

        strategy = strategy_cls(**strategy_kwargs)

        # Build config
        config = CrawlerConfig(
            output_format=request.output_format,
            include_links=request.include_links,
            only_main_content=request.only_main_content,
            content_filter=request.content_filter,
            cache=True,
        )

        # Execute crawl
        result = await engine.crawl(
            request.url,
            strategy=strategy,
            config=config,
        )

        # Update job
        job.status = JobStatus.COMPLETED
        job.completed_at = time.time()
        job.duration_ms = (job.completed_at - job.started_at) * 1000
        job.total_pages = result.total_pages
        job.pages_crawled = result.successful_pages
        job.pages_failed = result.failed_pages
        job.total_words = result.total_words
        job.total_tokens = result.total_tokens

        # Serialize pages (limit content size)
        pages = []
        for page in result.pages:
            page_data: dict[str, Any] = {
                "url": page.url,
                "success": page.success,
                "status_code": page.status_code,
                "word_count": page.word_count,
                "token_count": page.token_count,
                "response_time_ms": round(page.response_time_ms, 2),
                "error": page.error,
            }

            if page.success:
                # Truncate content for API response
                md = page.markdown
                if len(md) > 5000:
                    md = md[:5000] + "\n\n[... truncated]"
                page_data["markdown"] = md
                page_data["metadata"] = page.metadata

            pages.append(page_data)

        job.result = {"pages": pages}

        logger.info(
            "Crawl job completed: %s (%d pages, %d words, %.0fms)",
            job.job_id,
            result.total_pages,
            result.total_words,
            job.duration_ms,
        )

    except asyncio.CancelledError:
        job.status = JobStatus.CANCELLED
        job.completed_at = time.time()
        logger.info("Crawl job cancelled: %s", job.job_id)

    except Exception as e:
        job.status = JobStatus.FAILED
        job.completed_at = time.time()
        job.duration_ms = (job.completed_at - job.started_at) * 1000
        job.error = str(e)
        logger.error("Crawl job failed: %s — %s", job.job_id, e, exc_info=True)