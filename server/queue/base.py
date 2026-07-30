"""
AgentCrawl — Queue Backend Base
===================================

Abstract base class and data models for job queue backends.

The queue system handles asynchronous crawl job processing:
    - Producers enqueue crawl jobs
    - Workers dequeue and process jobs
    - Results are stored for retrieval

Backends:
    - MemoryQueueBackend (default, single-process)
    - RedisQueueBackend (distributed, production)

Usage:
    from server.queue.base import QueueBackend, QueueItem

    class MyBackend(QueueBackend):
        async def enqueue(self, item): ...
        async def dequeue(self): ...
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


class JobPriority(int, Enum):
    """Job priority levels."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class JobStatus(str, Enum):
    """Job lifecycle status."""

    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class QueueItem:
    """
    An item in the job queue.

    Attributes:
        item_id: Unique item identifier.
        job_id: Associated crawl job ID.
        job_type: Type of job (crawl, scrape, batch).
        payload: Job payload data.
        priority: Job priority level.
        status: Current job status.
        created_at: Creation timestamp.
        scheduled_at: When the job should be processed.
        started_at: When processing began.
        completed_at: When processing finished.
        attempts: Number of processing attempts.
        max_attempts: Maximum retry attempts.
        timeout_seconds: Processing timeout.
        error: Error message (if failed).
        result: Processing result data.
        metadata: Additional metadata.
    """

    item_id: str = field(default_factory=lambda: f"qi_{uuid.uuid4().hex[:12]}")
    job_id: str = ""
    job_type: str = "crawl"
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = JobPriority.NORMAL
    status: str = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    scheduled_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    attempts: int = 0
    max_attempts: int = 3
    timeout_seconds: int = 300
    error: str | None = None
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        """Check if the item is ready for processing."""
        if self.scheduled_at > 0:
            return time.time() >= self.scheduled_at
        return True

    @property
    def is_expired(self) -> bool:
        """Check if the item has timed out."""
        if self.started_at > 0 and self.timeout_seconds > 0:
            return time.time() - self.started_at > self.timeout_seconds
        return False

    @property
    def can_retry(self) -> bool:
        """Check if the item can be retried."""
        return self.attempts < self.max_attempts

    @property
    def age_seconds(self) -> float:
        """Age of the item in seconds."""
        return time.time() - self.created_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "item_id": self.item_id,
            "job_id": self.job_id,
            "job_type": self.job_type,
            "payload": self.payload,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at,
            "scheduled_at": self.scheduled_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "timeout_seconds": self.timeout_seconds,
            "error": self.error,
            "result": self.result,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueueItem:
        """Deserialize from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class QueueStats:
    """
    Queue statistics.

    Attributes:
        pending: Items waiting to be processed.
        processing: Items currently being processed.
        completed: Successfully processed items.
        failed: Failed items.
        total_enqueued: Total items ever enqueued.
        total_dequeued: Total items ever dequeued.
        total_completed: Total items successfully completed.
        total_failed: Total items that failed.
        avg_wait_seconds: Average time in queue.
        avg_process_seconds: Average processing time.
    """

    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    total_enqueued: int = 0
    total_dequeued: int = 0
    total_completed: int = 0
    total_failed: int = 0
    avg_wait_seconds: float = 0.0
    avg_process_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pending": self.pending,
            "processing": self.processing,
            "completed": self.completed,
            "failed": self.failed,
            "total_enqueued": self.total_enqueued,
            "total_dequeued": self.total_dequeued,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "avg_wait_seconds": round(self.avg_wait_seconds, 2),
            "avg_process_seconds": round(self.avg_process_seconds, 2),
        }


# ══════════════════════════════════════════════════════════════
# Abstract Backend
# ══════════════════════════════════════════════════════════════


class QueueBackend(ABC):
    """
    Abstract base class for queue backends.

    Implementations must provide:
        - enqueue: Add an item to the queue
        - dequeue: Remove and return the next item
        - peek: View the next item without removing
        - acknowledge: Mark an item as successfully processed
        - reject: Mark an item as failed (optionally retry)
        - size: Current queue size
        - clear: Remove all items

    Example:
        >>> class MyBackend(QueueBackend):
        ...     async def enqueue(self, item):
        ...         ...
        ...     async def dequeue(self):
        ...         ...
    """

    @abstractmethod
    async def start(self) -> None:
        """Initialize the backend (connect, create tables, etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Shutdown the backend (disconnect, cleanup)."""
        ...

    @abstractmethod
    async def enqueue(self, item: QueueItem) -> str:
        """
        Add an item to the queue.

        Args:
            item: Queue item to enqueue.

        Returns:
            The item_id.
        """
        ...

    @abstractmethod
    async def dequeue(self, timeout: float = 0.0) -> QueueItem | None:
        """
        Remove and return the next ready item.

        Items are returned in priority order (highest first),
        then by creation time (oldest first).

        Args:
            timeout: Maximum seconds to wait for an item (0 = no wait).

        Returns:
            QueueItem, or None if queue is empty/timeout.
        """
        ...

    @abstractmethod
    async def peek(self) -> QueueItem | None:
        """
        View the next item without removing it.

        Returns:
            QueueItem, or None if queue is empty.
        """
        ...

    @abstractmethod
    async def acknowledge(self, item_id: str, result: dict[str, Any] | None = None) -> bool:
        """
        Mark an item as successfully processed.

        Args:
            item_id: Item identifier.
            result: Processing result data.

        Returns:
            True if the item was found and acknowledged.
        """
        ...

    @abstractmethod
    async def reject(
        self,
        item_id: str,
        error: str = "",
        retry: bool = True,
    ) -> bool:
        """
        Mark an item as failed.

        Args:
            item_id: Item identifier.
            error: Error message.
            retry: Whether to re-enqueue for retry.

        Returns:
            True if the item was found and rejected.
        """
        ...

    @abstractmethod
    async def cancel(self, item_id: str) -> bool:
        """
        Cancel a queued item.

        Args:
            item_id: Item identifier.

        Returns:
            True if the item was found and cancelled.
        """
        ...

    @abstractmethod
    async def get_item(self, item_id: str) -> QueueItem | None:
        """
        Get an item by ID.

        Args:
            item_id: Item identifier.

        Returns:
            QueueItem, or None if not found.
        """
        ...

    @abstractmethod
    async def size(self) -> int:
        """
        Get the number of items in the queue.

        Returns:
            Queue size.
        """
        ...

    @abstractmethod
    async def is_empty(self) -> bool:
        """
        Check if the queue is empty.

        Returns:
            True if empty.
        """
        ...

    @abstractmethod
    async def clear(self) -> int:
        """
        Remove all items from the queue.

        Returns:
            Number of items removed.
        """
        ...

    @abstractmethod
    async def stats(self) -> QueueStats:
        """
        Get queue statistics.

        Returns:
            QueueStats.
        """
        ...

    async def health_check(self) -> bool:
        """
        Check if the backend is operational.

        Returns:
            True if healthy.
        """
        try:
            await self.size()
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
