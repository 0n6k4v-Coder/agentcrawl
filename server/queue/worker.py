"""
AgentCrawl — Queue Worker
=============================

Background workers that process jobs from the queue.

Features:
    - Configurable worker pool size
    - Job type routing (crawl, scrape, batch)
    - Graceful shutdown with drain
    - Error handling with automatic retry
    - Progress reporting via callbacks
    - Webhook dispatch on completion
    - Metrics recording
    - Health tracking

Usage:
    from server.queue.worker import WorkerPool

    pool = WorkerPool(
        backend=queue_backend,
        engine=crawl_engine,
        num_workers=3,
    )

    await pool.start()
    # ... jobs are processed automatically ...
    await pool.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("agentcrawl.server.queue.worker")


# ══════════════════════════════════════════════════════════════
# Worker State
# ══════════════════════════════════════════════════════════════

class WorkerState(str, Enum):
    """Worker lifecycle state."""
    IDLE = "idle"
    RUNNING = "running"
    PROCESSING = "processing"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class WorkerInfo:
    """
    Worker status information.

    Attributes:
        worker_id: Unique worker identifier.
        state: Current worker state.
        current_job: Currently processing job ID.
        jobs_processed: Total jobs processed.
        jobs_failed: Total jobs failed.
        started_at: Worker start timestamp.
        last_active: Last activity timestamp.
        uptime_seconds: Worker uptime.
    """
    worker_id: str
    state: WorkerState = WorkerState.IDLE
    current_job: str = ""
    jobs_processed: int = 0
    jobs_failed: int = 0
    started_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "state": self.state.value,
            "current_job": self.current_job,
            "jobs_processed": self.jobs_processed,
            "jobs_failed": self.jobs_failed,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


# ══════════════════════════════════════════════════════════════
# Job Handler Type
# ══════════════════════════════════════════════════════════════

# Handler signature: (engine, item) → result dict
JobHandler = Callable[
    [Any, Any],
    Coroutine[Any, Any, dict[str, Any]],
]


# ══════════════════════════════════════════════════════════════
# Single Worker
# ══════════════════════════════════════════════════════════════

class QueueWorker:
    """
    A single queue worker that processes jobs.

    Continuously polls the queue for items and processes them
    using the appropriate handler based on job type.

    Args:
        worker_id: Unique worker identifier.
        backend: Queue backend.
        engine: CrawlEngine instance.
        handlers: Job type → handler mapping.
        poll_interval: Seconds between queue polls when empty.
        on_complete: Callback on job completion.
        on_error: Callback on job error.
    """

    def __init__(
        self,
        worker_id: str,
        backend: Any,
        engine: Any,
        handlers: dict[str, JobHandler] | None = None,
        poll_interval: float = 1.0,
        on_complete: Callable[[str, dict[str, Any]], Coroutine] | None = None,
        on_error: Callable[[str, str], Coroutine] | None = None,
    ):
        self._worker_id = worker_id
        self._backend = backend
        self._engine = engine
        self._handlers = handlers or {}
        self._poll_interval = poll_interval
        self._on_complete = on_complete
        self._on_error = on_error

        self._info = WorkerInfo(worker_id=worker_id)
        self._task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

    @property
    def info(self) -> WorkerInfo:
        return self._info

    async def start(self) -> None:
        """Start the worker loop."""
        if self._task and not self._task.done():
            return

        self._shutdown_event.clear()
        self._info.state = WorkerState.RUNNING
        self._info.started_at = time.time()
        self._task = asyncio.create_task(self._run())

        logger.info("Worker %s started", self._worker_id)

    async def stop(self, timeout: float = 30.0) -> None:
        """
        Stop the worker gracefully.

        Waits for the current job to finish (up to timeout).

        Args:
            timeout: Maximum seconds to wait for current job.
        """
        self._info.state = WorkerState.STOPPING
        self._shutdown_event.set()

        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Worker %s stop timed out, cancelling",
                    self._worker_id,
                )
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

        self._info.state = WorkerState.STOPPED
        logger.info(
            "Worker %s stopped (processed=%d, failed=%d)",
            self._worker_id,
            self._info.jobs_processed,
            self._info.jobs_failed,
        )

    async def _run(self) -> None:
        """Main worker loop."""
        while not self._shutdown_event.is_set():
            try:
                # Dequeue with short timeout
                item = await self._backend.dequeue(timeout=self._poll_interval)

                if item is None:
                    self._info.state = WorkerState.RUNNING
                    continue

                # Process
                self._info.state = WorkerState.PROCESSING
                self._info.current_job = item.job_id
                self._info.last_active = time.time()

                await self._process_item(item)

                self._info.current_job = ""

            except asyncio.CancelledError:
                break

            except Exception as e:
                self._info.state = WorkerState.ERROR
                logger.error(
                    "Worker %s error: %s",
                    self._worker_id,
                    e,
                    exc_info=True,
                )
                # Brief pause before retrying
                await asyncio.sleep(1.0)
                self._info.state = WorkerState.RUNNING

    async def _process_item(self, item: Any) -> None:
        """
        Process a single queue item.

        Routes to the appropriate handler based on job type.

        Args:
            item: QueueItem to process.
        """
        job_type = item.job_type
        handler = self._handlers.get(job_type)

        if handler is None:
            error_msg = f"No handler for job type: {job_type}"
            logger.error("Worker %s: %s", self._worker_id, error_msg)
            await self._backend.reject(item.item_id, error=error_msg, retry=False)
            self._info.jobs_failed += 1
            return

        try:
            logger.info(
                "Worker %s processing: %s (job=%s, type=%s, attempt=%d)",
                self._worker_id,
                item.item_id,
                item.job_id,
                job_type,
                item.attempts,
            )

            start = time.perf_counter()

            # Execute handler
            result = await handler(self._engine, item)

            elapsed = (time.perf_counter() - start) * 1000

            # Acknowledge
            await self._backend.acknowledge(item.item_id, result=result)
            self._info.jobs_processed += 1

            logger.info(
                "Worker %s completed: %s (%.0fms)",
                self._worker_id,
                item.item_id,
                elapsed,
            )

            # Completion callback
            if self._on_complete:
                try:
                    await self._on_complete(item.job_id, result)
                except Exception as e:
                    logger.warning("on_complete callback error: %s", e)

        except Exception as e:
            error_msg = str(e)
            self._info.jobs_failed += 1

            logger.error(
                "Worker %s failed: %s — %s",
                self._worker_id,
                item.item_id,
                error_msg,
                exc_info=True,
            )

            # Reject (will retry if attempts remain)
            await self._backend.reject(item.item_id, error=error_msg, retry=True)

            # Error callback
            if self._on_error:
                try:
                    await self._on_error(item.job_id, error_msg)
                except Exception as cb_err:
                    logger.warning("on_error callback error: %s", cb_err)


# ══════════════════════════════════════════════════════════════
# Worker Pool
# ══════════════════════════════════════════════════════════════

class WorkerPool:
    """
    Pool of queue workers for concurrent job processing.

    Args:
        backend: Queue backend.
        engine: CrawlEngine instance.
        num_workers: Number of worker instances.
        handlers: Job type → handler mapping.
        poll_interval: Queue poll interval.
        webhook_dispatcher: Optional webhook dispatcher.
        metrics: Optional metrics collector.

    Example:
        >>> pool = WorkerPool(
        ...     backend=queue_backend,
        ...     engine=crawl_engine,
        ...     num_workers=3,
        ... )
        >>> await pool.start()
        >>> # Jobs are processed automatically
        >>> await pool.stop()
    """

    def __init__(
        self,
        backend: Any,
        engine: Any,
        num_workers: int = 2,
        handlers: dict[str, JobHandler] | None = None,
        poll_interval: float = 1.0,
        webhook_dispatcher: Any = None,
        metrics: Any = None,
    ):
        self._backend = backend
        self._engine = engine
        self._num_workers = num_workers
        self._poll_interval = poll_interval
        self._webhook_dispatcher = webhook_dispatcher
        self._metrics = metrics

        # Default handlers
        self._handlers = handlers or self._default_handlers()

        # Workers
        self._workers: list[QueueWorker] = []
        self._started = False

    def _default_handlers(self) -> dict[str, JobHandler]:
        """Get default job handlers."""
        return {
            "crawl": handle_crawl_job,
            "scrape": handle_scrape_job,
            "batch": handle_batch_job,
        }

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all workers."""
        if self._started:
            return

        logger.info("Starting worker pool (%d workers)...", self._num_workers)

        for i in range(self._num_workers):
            worker = QueueWorker(
                worker_id=f"worker-{i}",
                backend=self._backend,
                engine=self._engine,
                handlers=self._handlers,
                poll_interval=self._poll_interval,
                on_complete=self._on_job_complete,
                on_error=self._on_job_error,
            )
            await worker.start()
            self._workers.append(worker)

        self._started = True
        logger.info("Worker pool started (%d workers)", self._num_workers)

    async def stop(self, timeout: float = 30.0) -> None:
        """
        Stop all workers gracefully.

        Args:
            timeout: Max seconds to wait per worker.
        """
        if not self._started:
            return

        logger.info("Stopping worker pool...")

        # Stop all workers concurrently
        tasks = [worker.stop(timeout=timeout) for worker in self._workers]
        await asyncio.gather(*tasks, return_exceptions=True)

        self._workers.clear()
        self._started = False

        logger.info("Worker pool stopped")

    # ──────────────────────────────────────────────────────────
    # Callbacks
    # ──────────────────────────────────────────────────────────

    async def _on_job_complete(
        self,
        job_id: str,
        result: dict[str, Any],
    ) -> None:
        """Handle job completion."""
        # Webhook
        if self._webhook_dispatcher:
            try:
                await self._webhook_dispatcher.dispatch_job_event(
                    job_id=job_id,
                    status="completed",
                    data=result,
                )
            except Exception as e:
                logger.warning("Webhook dispatch error: %s", e)

        # Metrics
        if self._metrics:
            pages = result.get("total_pages", result.get("pages", 0))
            if isinstance(pages, list):
                pages = len(pages)
            self._metrics.record_crawl_end(pages)

    async def _on_job_error(self, job_id: str, error: str) -> None:
        """Handle job error."""
        # Webhook
        if self._webhook_dispatcher:
            try:
                await self._webhook_dispatcher.dispatch_job_event(
                    job_id=job_id,
                    status="failed",
                    data={"error": error},
                )
            except Exception as e:
                logger.warning("Webhook dispatch error: %s", e)

    # ──────────────────────────────────────────────────────────
    # Status
    # ──────────────────────────────────────────────────────────

    def get_worker_info(self) -> list[dict[str, Any]]:
        """Get status of all workers."""
        return [w.info.to_dict() for w in self._workers]

    def get_pool_stats(self) -> dict[str, Any]:
        """Get aggregate pool statistics."""
        total_processed = sum(w.info.jobs_processed for w in self._workers)
        total_failed = sum(w.info.jobs_failed for w in self._workers)
        active = sum(
            1 for w in self._workers
            if w.info.state == WorkerState.PROCESSING
        )

        return {
            "num_workers": len(self._workers),
            "active_workers": active,
            "idle_workers": len(self._workers) - active,
            "total_processed": total_processed,
            "total_failed": total_failed,
            "started": self._started,
        }

    @property
    def is_started(self) -> bool:
        return self._started

    def __repr__(self) -> str:
        return (
            f"WorkerPool(workers={len(self._workers)}, "
            f"started={self._started})"
        )


# ══════════════════════════════════════════════════════════════
# Default Job Handlers
# ══════════════════════════════════════════════════════════════

async def handle_crawl_job(engine: Any, item: Any) -> dict[str, Any]:
    """
    Handle a crawl job.

    Args:
        engine: CrawlEngine instance.
        item: QueueItem with crawl payload.

    Returns:
        Crawl result dictionary.
    """
    from agentcrawl.config.crawler_config import CrawlerConfig
    from agentcrawl.crawling.adaptive import AdaptiveCrawler
    from agentcrawl.crawling.best_first import BestFirstCrawler
    from agentcrawl.crawling.bfs import BFSCrawler
    from agentcrawl.crawling.dfs import DFSCrawler

    payload = item.payload

    url = payload.get("url", "")
    if not url:
        raise ValueError("Crawl job missing 'url' in payload")

    # Build strategy
    strategy_name = payload.get("strategy", "bfs")
    max_depth = payload.get("max_depth", 3)
    max_pages = payload.get("max_pages", 50)

    strategies = {
        "bfs": BFSCrawler,
        "dfs": DFSCrawler,
        "best_first": BestFirstCrawler,
        "adaptive": AdaptiveCrawler,
    }

    strategy_cls = strategies.get(strategy_name, BFSCrawler)
    strategy = strategy_cls(max_depth=max_depth, max_pages=max_pages)

    # Build config
    config = CrawlerConfig(
        output_format=payload.get("output_format", "markdown"),
        only_main_content=payload.get("only_main_content", True),
        content_filter=payload.get("content_filter", "none"),
        cache=True,
    )

    # Execute
    result = await engine.crawl(url, strategy=strategy, config=config)

    # Serialize
    pages = []
    for page in result.pages:
        page_data: dict[str, Any] = {
            "url": page.url,
            "success": page.success,
            "word_count": page.word_count,
        }
        if page.success:
            md = page.markdown
            if len(md) > 3000:
                md = md[:3000] + "\n\n[... truncated]"
            page_data["markdown"] = md
            page_data["metadata"] = page.metadata
        pages.append(page_data)

    return {
        "job_id": item.job_id,
        "total_pages": result.total_pages,
        "successful_pages": result.successful_pages,
        "failed_pages": result.failed_pages,
        "total_words": result.total_words,
        "total_tokens": result.total_tokens,
        "duration_ms": result.duration_ms,
        "pages": pages,
    }


async def handle_scrape_job(engine: Any, item: Any) -> dict[str, Any]:
    """
    Handle a scrape job.

    Args:
        engine: CrawlEngine instance.
        item: QueueItem with scrape payload.

    Returns:
        Scrape result dictionary.
    """
    from agentcrawl.config.crawler_config import CrawlerConfig

    payload = item.payload

    url = payload.get("url", "")
    if not url:
        raise ValueError("Scrape job missing 'url' in payload")

    config = CrawlerConfig(
        output_format=payload.get("output_format", "markdown"),
        include_links=payload.get("include_links", True),
        include_metadata=payload.get("include_metadata", True),
        only_main_content=payload.get("only_main_content", True),
        content_filter=payload.get("content_filter", "none"),
        chunker=payload.get("chunker", "none"),
        cache=True,
    )

    result = await engine.scrape(url, config)

    if not result.success:
        raise RuntimeError(f"Scrape failed: {result.error}")

    return {
        "job_id": item.job_id,
        "url": result.url,
        "word_count": result.word_count,
        "token_count": result.token_count,
        "markdown": result.markdown[:5000],
        "metadata": result.metadata,
    }


async def handle_batch_job(engine: Any, item: Any) -> dict[str, Any]:
    """
    Handle a batch scrape job.

    Args:
        engine: CrawlEngine instance.
        item: QueueItem with batch payload.

    Returns:
        Batch result dictionary.
    """
    from agentcrawl.config.crawler_config import CrawlerConfig

    payload = item.payload

    urls = payload.get("urls", [])
    if not urls:
        raise ValueError("Batch job missing 'urls' in payload")

    config = CrawlerConfig(
        output_format=payload.get("output_format", "markdown"),
        only_main_content=payload.get("only_main_content", True),
        cache=True,
    )

    max_concurrent = payload.get("max_concurrent", 5)

    results = await engine.batch_scrape(
        urls,
        config=config,
        max_concurrent=max_concurrent,
    )

    pages = []
    for r in results:
        page: dict[str, Any] = {
            "url": r.url,
            "success": r.success,
            "word_count": r.word_count,
        }
        if r.success:
            page["markdown"] = r.markdown[:3000]
        else:
            page["error"] = r.error
        pages.append(page)

    successful = sum(1 for r in results if r.success)

    return {
        "job_id": item.job_id,
        "total": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "pages": pages,
    }
