"""
AgentCrawl — Server Queue Package
=====================================

Asynchronous job queue system for processing crawl, scrape,
and batch jobs in the background.

Modules:
    base    — Abstract backend, data models (QueueItem, QueueStats)
    memory  — In-memory queue backend (single-process)
    redis   — Redis queue backend (distributed)
    worker  — Background workers and worker pool
    webhook — Webhook event delivery

Quick Start:
    from server.queue import (
        MemoryQueueBackend,
        WorkerPool,
        QueueItem,
    )

    # Create queue
    backend = MemoryQueueBackend()
    await backend.start()

    # Enqueue a job
    item = QueueItem(job_id="job_1", job_type="crawl", payload={"url": "..."})
    await backend.enqueue(item)

    # Start workers
    pool = WorkerPool(backend=backend, engine=engine, num_workers=3)
    await pool.start()
"""

from __future__ import annotations

# Base
from server.queue.base import (
    JobPriority,
    JobStatus,
    QueueBackend,
    QueueItem,
    QueueStats,
)

# Backends
from server.queue.memory import MemoryQueueBackend
from server.queue.redis import RedisQueueBackend

# Webhooks
from server.queue.webhook import (
    DeliveryResult,
    WebhookConfig,
    WebhookDispatcher,
    WebhookEvent,
)

# Workers
from server.queue.worker import (
    QueueWorker,
    WorkerInfo,
    WorkerPool,
    WorkerState,
)

__all__ = [
    "DeliveryResult",
    "JobPriority",
    "JobStatus",
    # Backends
    "MemoryQueueBackend",
    # Base
    "QueueBackend",
    "QueueItem",
    "QueueStats",
    # Workers
    "QueueWorker",
    "RedisQueueBackend",
    "WebhookConfig",
    # Webhooks
    "WebhookDispatcher",
    "WebhookEvent",
    "WorkerInfo",
    "WorkerPool",
    "WorkerState",
]
