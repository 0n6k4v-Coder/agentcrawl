"""
AgentCrawl — Memory Queue Backend
=====================================

In-memory job queue backend for single-process deployments.

Features:
    - Priority-based ordering (highest priority first)
    - FIFO within same priority
    - Delayed/scheduled item support
    - Automatic retry with configurable attempts
    - Dead letter queue for permanently failed items
    - Statistics tracking
    - Expired item cleanup

Usage:
    from agentcrawl.server.queue.memory import MemoryQueueBackend
    from agentcrawl.server.queue.base import QueueItem

    backend = MemoryQueueBackend()
    await backend.start()

    # Enqueue
    item = QueueItem(job_id="job_123", job_type="crawl", payload={"url": "..."})
    await backend.enqueue(item)

    # Dequeue
    item = await backend.dequeue()
    if item:
        # Process...
        await backend.acknowledge(item.item_id, result={"pages": 10})
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from typing import Any

from agentcrawl.server.queue.base import (
    JobStatus,
    QueueBackend,
    QueueItem,
    QueueStats,
)

logger = logging.getLogger("agentcrawl.server.queue.memory")


# ══════════════════════════════════════════════════════════════
# Priority Wrapper
# ══════════════════════════════════════════════════════════════

class _PrioritizedItem:
    """
    Wrapper for heap ordering.

    Orders by:
        1. Priority (higher = first, so negate for min-heap)
        2. Scheduled time (earlier = first)
        3. Creation time (older = first)
    """

    __slots__ = ("priority_key", "scheduled_at", "created_at", "seq", "item")

    _counter: int = 0

    def __init__(self, item: QueueItem):
        # Negate priority so higher priority comes first in min-heap
        self.priority_key = -item.priority
        self.scheduled_at = item.scheduled_at if item.scheduled_at > 0 else item.created_at
        self.created_at = item.created_at
        _PrioritizedItem._counter += 1
        self.seq = _PrioritizedItem._counter
        self.item = item

    def __lt__(self, other: _PrioritizedItem) -> bool:
        if self.priority_key != other.priority_key:
            return self.priority_key < other.priority_key
        if self.scheduled_at != other.scheduled_at:
            return self.scheduled_at < other.scheduled_at
        if self.created_at != other.created_at:
            return self.created_at < other.created_at
        return self.seq < other.seq


# ══════════════════════════════════════════════════════════════
# Memory Queue Backend
# ══════════════════════════════════════════════════════════════

class MemoryQueueBackend(QueueBackend):
    """
    In-memory queue backend using a priority heap.

    Suitable for single-process deployments and development.
    Not suitable for distributed/multi-worker setups.

    Args:
        max_retries: Default max retry attempts.
        dead_letter_max: Max items in dead letter queue.
        cleanup_interval: Seconds between cleanup runs.

    Example:
        >>> backend = MemoryQueueBackend()
        >>> await backend.start()
        >>> await backend.enqueue(QueueItem(job_id="j1"))
        >>> item = await backend.dequeue()
    """

    def __init__(
        self,
        max_retries: int = 3,
        dead_letter_max: int = 100,
        cleanup_interval: float = 60.0,
    ):
        self._max_retries = max_retries
        self._dead_letter_max = dead_letter_max
        self._cleanup_interval = cleanup_interval

        # Main queue (min-heap of _PrioritizedItem)
        self._queue: list[_PrioritizedItem] = []

        # Items currently being processed: item_id → QueueItem
        self._processing: dict[str, QueueItem] = {}

        # All items by ID: item_id → QueueItem
        self._items: dict[str, QueueItem] = {}

        # Dead letter queue
        self._dead_letter: list[QueueItem] = []

        # Stats
        self._total_enqueued: int = 0
        self._total_dequeued: int = 0
        self._total_completed: int = 0
        self._total_failed: int = 0
        self._total_wait_time: float = 0.0
        self._total_process_time: float = 0.0

        # State
        self._started: bool = False
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the queue backend."""
        if self._started:
            return

        self._started = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Memory queue backend started")

    async def stop(self) -> None:
        """Stop the queue backend."""
        if not self._started:
            return

        self._started = False

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info(
            "Memory queue backend stopped (pending=%d, processing=%d)",
            len(self._queue),
            len(self._processing),
        )

    # ──────────────────────────────────────────────────────────
    # Queue Operations
    # ──────────────────────────────────────────────────────────

    async def enqueue(self, item: QueueItem) -> str:
        """
        Add an item to the queue.

        Args:
            item: Queue item.

        Returns:
            The item_id.
        """
        async with self._lock:
            item.status = JobStatus.QUEUED
            if item.max_attempts == 0:
                item.max_attempts = self._max_retries

            self._items[item.item_id] = item
            heapq.heappush(self._queue, _PrioritizedItem(item))
            self._total_enqueued += 1

        logger.debug(
            "Enqueued: %s (job=%s, type=%s, priority=%d)",
            item.item_id,
            item.job_id,
            item.job_type,
            item.priority,
        )

        return item.item_id

    async def dequeue(self, timeout: float = 0.0) -> QueueItem | None:
        """
        Remove and return the next ready item.

        Args:
            timeout: Max seconds to wait (0 = no wait).

        Returns:
            QueueItem, or None if empty/timeout.
        """
        deadline = time.time() + timeout if timeout > 0 else 0

        while True:
            async with self._lock:
                # Find next ready item
                item = self._pop_ready()

                if item is not None:
                    item.status = JobStatus.PROCESSING
                    item.started_at = time.time()
                    item.attempts += 1
                    self._processing[item.item_id] = item
                    self._total_dequeued += 1

                    # Track wait time
                    wait_time = item.started_at - item.created_at
                    self._total_wait_time += wait_time

                    logger.debug(
                        "Dequeued: %s (attempt=%d, wait=%.1fs)",
                        item.item_id,
                        item.attempts,
                        wait_time,
                    )

                    return item

            # No item available
            if deadline == 0:
                return None

            if time.time() >= deadline:
                return None

            # Wait briefly before retrying
            await asyncio.sleep(min(0.1, deadline - time.time()))

    async def peek(self) -> QueueItem | None:
        """
        View the next ready item without removing.

        Returns:
            QueueItem, or None if empty.
        """
        async with self._lock:
            for pitem in self._queue:
                if pitem.item.is_ready and pitem.item.status == JobStatus.QUEUED:
                    return pitem.item
            return None

    # ──────────────────────────────────────────────────────────
    # Acknowledgment
    # ──────────────────────────────────────────────────────────

    async def acknowledge(
        self,
        item_id: str,
        result: dict[str, Any] | None = None,
    ) -> bool:
        """
        Mark an item as successfully processed.

        Args:
            item_id: Item identifier.
            result: Processing result.

        Returns:
            True if found and acknowledged.
        """
        async with self._lock:
            item = self._processing.pop(item_id, None)

            if item is None:
                return False

            item.status = JobStatus.COMPLETED
            item.completed_at = time.time()
            item.result = result

            self._total_completed += 1

            # Track process time
            if item.started_at > 0:
                process_time = item.completed_at - item.started_at
                self._total_process_time += process_time

            logger.debug(
                "Acknowledged: %s (process=%.1fs)",
                item_id,
                item.completed_at - item.started_at if item.started_at else 0,
            )

            return True

    async def reject(
        self,
        item_id: str,
        error: str = "",
        retry: bool = True,
    ) -> bool:
        """
        Mark an item as failed, optionally retrying.

        Args:
            item_id: Item identifier.
            error: Error message.
            retry: Whether to re-enqueue.

        Returns:
            True if found and rejected.
        """
        async with self._lock:
            item = self._processing.pop(item_id, None)

            if item is None:
                return False

            item.error = error

            if retry and item.can_retry:
                # Re-enqueue for retry
                item.status = JobStatus.RETRYING
                item.started_at = 0.0
                item.completed_at = 0.0

                # Exponential backoff: 2^attempts seconds
                delay = min(2 ** item.attempts, 60)
                item.scheduled_at = time.time() + delay

                heapq.heappush(self._queue, _PrioritizedItem(item))

                logger.debug(
                    "Rejected (retry %d/%d in %ds): %s — %s",
                    item.attempts,
                    item.max_attempts,
                    delay,
                    item_id,
                    error[:100],
                )
            else:
                # Permanently failed
                item.status = JobStatus.FAILED
                item.completed_at = time.time()
                self._total_failed += 1

                # Move to dead letter queue
                self._dead_letter.append(item)
                if len(self._dead_letter) > self._dead_letter_max:
                    self._dead_letter = self._dead_letter[-self._dead_letter_max:]

                logger.warning(
                    "Rejected (permanent): %s — %s",
                    item_id,
                    error[:100],
                )

            return True

    async def cancel(self, item_id: str) -> bool:
        """
        Cancel a queued or processing item.

        Args:
            item_id: Item identifier.

        Returns:
            True if found and cancelled.
        """
        async with self._lock:
            # Check processing
            item = self._processing.pop(item_id, None)

            # Check queue
            if item is None:
                item = self._items.get(item_id)

            if item is None:
                return False

            item.status = JobStatus.CANCELLED
            item.completed_at = time.time()

            # Remove from heap (lazy deletion — will be skipped on dequeue)
            logger.debug("Cancelled: %s", item_id)
            return True

    # ──────────────────────────────────────────────────────────
    # Queries
    # ──────────────────────────────────────────────────────────

    async def get_item(self, item_id: str) -> QueueItem | None:
        """Get an item by ID."""
        return self._items.get(item_id)

    async def size(self) -> int:
        """Get queue size (pending items only)."""
        async with self._lock:
            return sum(
                1 for p in self._queue
                if p.item.status in (JobStatus.QUEUED, JobStatus.RETRYING)
            )

    async def is_empty(self) -> bool:
        """Check if queue is empty."""
        return await self.size() == 0

    async def clear(self) -> int:
        """Remove all items from the queue."""
        async with self._lock:
            count = len(self._queue)
            self._queue.clear()
            self._processing.clear()
            logger.info("Queue cleared: %d items removed", count)
            return count

    async def stats(self) -> QueueStats:
        """Get queue statistics."""
        async with self._lock:
            pending = sum(
                1 for p in self._queue
                if p.item.status in (JobStatus.QUEUED, JobStatus.RETRYING)
            )

            completed_count = sum(
                1 for item in self._items.values()
                if item.status == JobStatus.COMPLETED
            )

            failed_count = sum(
                1 for item in self._items.values()
                if item.status == JobStatus.FAILED
            )

            avg_wait = (
                self._total_wait_time / max(self._total_dequeued, 1)
            )
            avg_process = (
                self._total_process_time / max(self._total_completed, 1)
            )

            return QueueStats(
                pending=pending,
                processing=len(self._processing),
                completed=completed_count,
                failed=failed_count,
                total_enqueued=self._total_enqueued,
                total_dequeued=self._total_dequeued,
                total_completed=self._total_completed,
                total_failed=self._total_failed,
                avg_wait_seconds=avg_wait,
                avg_process_seconds=avg_process,
            )

    # ──────────────────────────────────────────────────────────
    # Dead Letter Queue
    # ──────────────────────────────────────────────────────────

    async def get_dead_letter_items(self, limit: int = 50) -> list[QueueItem]:
        """Get items from the dead letter queue."""
        return self._dead_letter[-limit:]

    async def retry_dead_letter(self, item_id: str) -> bool:
        """Re-enqueue a dead letter item."""
        async with self._lock:
            for i, item in enumerate(self._dead_letter):
                if item.item_id == item_id:
                    self._dead_letter.pop(i)
                    item.status = JobStatus.QUEUED
                    item.attempts = 0
                    item.error = None
                    item.scheduled_at = 0.0
                    heapq.heappush(self._queue, _PrioritizedItem(item))
                    return True
            return False

    # ──────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────

    def _pop_ready(self) -> QueueItem | None:
        """
        Pop the next ready item from the heap.

        Skips cancelled items and items not yet scheduled.
        """
        now = time.time()
        skipped: list[_PrioritizedItem] = []

        while self._queue:
            pitem = heapq.heappop(self._queue)
            item = pitem.item

            # Skip cancelled items
            if item.status == JobStatus.CANCELLED:
                continue

            # Skip items not yet ready
            if not item.is_ready:
                skipped.append(pitem)
                continue

            # Put back skipped items
            for s in skipped:
                heapq.heappush(self._queue, s)

            return item

        # Put back skipped items
        for s in skipped:
            heapq.heappush(self._queue, s)

        return None

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired and stale items."""
        while self._started:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Queue cleanup error: %s", e)

    async def _cleanup(self) -> None:
        """Remove expired processing items and old completed items."""
        async with self._lock:
            now = time.time()

            # Check for timed-out processing items
            timed_out = [
                item_id for item_id, item in self._processing.items()
                if item.is_expired
            ]

            for item_id in timed_out:
                item = self._processing.pop(item_id)
                item.error = "Processing timeout"

                if item.can_retry:
                    item.status = JobStatus.RETRYING
                    item.scheduled_at = now + 5
                    heapq.heappush(self._queue, _PrioritizedItem(item))
                    logger.warning("Timed out (retrying): %s", item_id)
                else:
                    item.status = JobStatus.FAILED
                    item.completed_at = now
                    self._total_failed += 1
                    self._dead_letter.append(item)
                    logger.warning("Timed out (failed): %s", item_id)

            # Remove old completed/failed items (keep last 1000)
            if len(self._items) > 1000:
                terminal = [
                    (iid, item) for iid, item in self._items.items()
                    if item.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
                ]
                terminal.sort(key=lambda x: x[1].completed_at or x[1].created_at)

                to_remove = len(self._items) - 1000
                for iid, _ in terminal[:to_remove]:
                    del self._items[iid]

    def __repr__(self) -> str:
        return (
            f"MemoryQueueBackend("
            f"pending={len(self._queue)}, "
            f"processing={len(self._processing)})"
        )