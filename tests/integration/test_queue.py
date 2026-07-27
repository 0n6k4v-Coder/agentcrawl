"""
AgentCrawl — Queue Integration Tests
========================================

Integration tests for the job queue system including
backends, workers, and webhook dispatch.

Tests:
    - MemoryQueueBackend operations
    - Priority ordering
    - Retry and dead letter
    - Worker pool processing
    - Webhook dispatch
    - Concurrent operations
    - Stats tracking

Run:
    pytest tests/integration/test_queue.py -v
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio

from agentcrawl.server.queue.base import JobPriority, JobStatus, QueueItem
from agentcrawl.server.queue.memory import MemoryQueueBackend


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def queue() -> AsyncGenerator[MemoryQueueBackend, None]:
    """Create a started memory queue backend."""
    backend = MemoryQueueBackend(max_retries=3, cleanup_interval=3600)
    await backend.start()

    yield backend

    await backend.stop()


@pytest.fixture
def make_item() -> Any:
    """Factory for creating queue items."""
    counter = 0

    def _make(
        job_id: str = "",
        job_type: str = "crawl",
        priority: int = JobPriority.NORMAL,
        payload: dict[str, Any] | None = None,
    ) -> QueueItem:
        nonlocal counter
        counter += 1
        return QueueItem(
            job_id=job_id or f"job_{counter}",
            job_type=job_type,
            priority=priority,
            payload=payload or {"url": f"https://example.com/{counter}"},
        )

    return _make


# ══════════════════════════════════════════════════════════════
# Basic Operations
# ══════════════════════════════════════════════════════════════

class TestBasicOperations:
    """Tests for basic queue operations."""

    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Enqueue an item and dequeue it."""
        item = make_item(job_id="job_1")
        item_id = await queue.enqueue(item)

        assert item_id == item.item_id

        dequeued = await queue.dequeue()
        assert dequeued is not None
        assert dequeued.job_id == "job_1"
        assert dequeued.status == JobStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_dequeue_empty_queue(self, queue: MemoryQueueBackend) -> None:
        """Dequeue from empty queue returns None."""
        result = await queue.dequeue()
        assert result is None

    @pytest.mark.asyncio
    async def test_fifo_order(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Items are dequeued in FIFO order (same priority)."""
        for i in range(5):
            await queue.enqueue(make_item(job_id=f"job_{i}"))

        for i in range(5):
            item = await queue.dequeue()
            assert item is not None
            assert item.job_id == f"job_{i}"

    @pytest.mark.asyncio
    async def test_size(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Queue size reflects enqueued items."""
        assert await queue.size() == 0

        await queue.enqueue(make_item())
        assert await queue.size() == 1

        await queue.enqueue(make_item())
        assert await queue.size() == 2

        await queue.dequeue()
        assert await queue.size() == 1

    @pytest.mark.asyncio
    async def test_is_empty(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """is_empty reflects queue state."""
        assert await queue.is_empty()

        await queue.enqueue(make_item())
        assert not await queue.is_empty()

        await queue.dequeue()
        assert await queue.is_empty()

    @pytest.mark.asyncio
    async def test_peek(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Peek returns item without removing."""
        await queue.enqueue(make_item(job_id="job_peek"))

        peeked = await queue.peek()
        assert peeked is not None
        assert peeked.job_id == "job_peek"

        # Item still in queue
        assert await queue.size() == 1

    @pytest.mark.asyncio
    async def test_clear(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Clear removes all items."""
        for _ in range(5):
            await queue.enqueue(make_item())

        removed = await queue.clear()
        assert removed == 5
        assert await queue.is_empty()


# ══════════════════════════════════════════════════════════════
# Priority
# ══════════════════════════════════════════════════════════════

class TestPriority:
    """Tests for priority-based ordering."""

    @pytest.mark.asyncio
    async def test_high_priority_first(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Higher priority items are dequeued first."""
        await queue.enqueue(make_item(job_id="low", priority=JobPriority.LOW))
        await queue.enqueue(make_item(job_id="high", priority=JobPriority.HIGH))
        await queue.enqueue(make_item(job_id="normal", priority=JobPriority.NORMAL))

        first = await queue.dequeue()
        assert first is not None
        assert first.job_id == "high"

        second = await queue.dequeue()
        assert second is not None
        assert second.job_id == "normal"

        third = await queue.dequeue()
        assert third is not None
        assert third.job_id == "low"

    @pytest.mark.asyncio
    async def test_critical_priority(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Critical priority beats all others."""
        await queue.enqueue(make_item(job_id="high", priority=JobPriority.HIGH))
        await queue.enqueue(make_item(job_id="critical", priority=JobPriority.CRITICAL))

        first = await queue.dequeue()
        assert first is not None
        assert first.job_id == "critical"


# ══════════════════════════════════════════════════════════════
# Acknowledge & Reject
# ══════════════════════════════════════════════════════════════

class TestAckReject:
    """Tests for acknowledge and reject operations."""

    @pytest.mark.asyncio
    async def test_acknowledge(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Acknowledge marks item as completed."""
        await queue.enqueue(make_item(job_id="job_ack"))
        item = await queue.dequeue()
        assert item is not None

        result = await queue.acknowledge(item.item_id, result={"pages": 5})
        assert result is True

        # Item no longer in processing
        assert await queue.size() == 0

    @pytest.mark.asyncio
    async def test_acknowledge_nonexistent(self, queue: MemoryQueueBackend) -> None:
        """Acknowledge non-existent item returns False."""
        result = await queue.acknowledge("nonexistent_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_reject_with_retry(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Reject with retry re-enqueues the item."""
        item = make_item(job_id="job_retry")
        item.max_attempts = 3
        await queue.enqueue(item)

        dequeued = await queue.dequeue()
        assert dequeued is not None
        assert dequeued.attempts == 1

        # Reject with retry
        await queue.reject(dequeued.item_id, error="Test error", retry=True)

        # Item should be back in queue (after delay)
        # Wait for scheduled time
        await asyncio.sleep(2.5)

        retried = await queue.dequeue()
        assert retried is not None
        assert retried.job_id == "job_retry"
        assert retried.attempts == 2

    @pytest.mark.asyncio
    async def test_reject_permanent(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Reject without retry moves to dead letter."""
        item = make_item(job_id="job_fail")
        await queue.enqueue(item)

        dequeued = await queue.dequeue()
        assert dequeued is not None

        await queue.reject(dequeued.item_id, error="Fatal error", retry=False)

        # Not in queue
        assert await queue.size() == 0

        # In dead letter
        dead = await queue.get_dead_letter_items()
        assert len(dead) == 1
        assert dead[0].job_id == "job_fail"

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Item goes to dead letter after max retries."""
        item = make_item(job_id="job_exhaust")
        item.max_attempts = 2
        await queue.enqueue(item)

        # Attempt 1
        d1 = await queue.dequeue()
        assert d1 is not None
        await queue.reject(d1.item_id, error="Error 1", retry=True)

        await asyncio.sleep(2.5)

        # Attempt 2
        d2 = await queue.dequeue()
        assert d2 is not None
        assert d2.attempts == 2
        await queue.reject(d2.item_id, error="Error 2", retry=True)

        # Should be in dead letter (max_attempts=2 exhausted)
        dead = await queue.get_dead_letter_items()
        assert any(d.job_id == "job_exhaust" for d in dead)


# ══════════════════════════════════════════════════════════════
# Cancel
# ══════════════════════════════════════════════════════════════

class TestCancel:
    """Tests for item cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_queued_item(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Cancel a queued item."""
        item = make_item(job_id="job_cancel")
        await queue.enqueue(item)

        result = await queue.cancel(item.item_id)
        assert result is True

        # Item should be skipped on dequeue
        dequeued = await queue.dequeue()
        assert dequeued is None or dequeued.job_id != "job_cancel"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, queue: MemoryQueueBackend) -> None:
        """Cancel non-existent item returns False."""
        result = await queue.cancel("nonexistent")
        assert result is False


# ══════════════════════════════════════════════════════════════
# Stats
# ══════════════════════════════════════════════════════════════

class TestStats:
    """Tests for queue statistics."""

    @pytest.mark.asyncio
    async def test_stats_initial(self, queue: MemoryQueueBackend) -> None:
        """Initial stats are zero."""
        stats = await queue.stats()
        assert stats.pending == 0
        assert stats.processing == 0
        assert stats.total_enqueued == 0

    @pytest.mark.asyncio
    async def test_stats_after_operations(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Stats reflect operations."""
        await queue.enqueue(make_item())
        await queue.enqueue(make_item())

        stats = await queue.stats()
        assert stats.total_enqueued == 2
        assert stats.pending == 2

        await queue.dequeue()
        stats = await queue.stats()
        assert stats.total_dequeued == 1
        assert stats.processing == 1

    @pytest.mark.asyncio
    async def test_stats_after_ack(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Stats track completions."""
        await queue.enqueue(make_item())
        item = await queue.dequeue()
        assert item is not None

        await queue.acknowledge(item.item_id)

        stats = await queue.stats()
        assert stats.total_completed == 1


# ══════════════════════════════════════════════════════════════
# Get Item
# ══════════════════════════════════════════════════════════════

class TestGetItem:
    """Tests for item retrieval."""

    @pytest.mark.asyncio
    async def test_get_item_by_id(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Retrieve item by ID."""
        item = make_item(job_id="job_get")
        await queue.enqueue(item)

        retrieved = await queue.get_item(item.item_id)
        assert retrieved is not None
        assert retrieved.job_id == "job_get"

    @pytest.mark.asyncio
    async def test_get_nonexistent_item(self, queue: MemoryQueueBackend) -> None:
        """Get non-existent item returns None."""
        result = await queue.get_item("nonexistent")
        assert result is None


# ══════════════════════════════════════════════════════════════
# Concurrent Operations
# ══════════════════════════════════════════════════════════════

class TestConcurrent:
    """Tests for concurrent queue operations."""

    @pytest.mark.asyncio
    async def test_concurrent_enqueue(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Multiple concurrent enqueues."""
        tasks = [queue.enqueue(make_item(job_id=f"job_{i}")) for i in range(20)]
        await asyncio.gather(*tasks)

        assert await queue.size() == 20

    @pytest.mark.asyncio
    async def test_concurrent_dequeue(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Multiple concurrent dequeues don't duplicate."""
        for i in range(10):
            await queue.enqueue(make_item(job_id=f"job_{i}"))

        results = await asyncio.gather(*[queue.dequeue() for _ in range(10)])

        # All should be unique
        job_ids = [r.job_id for r in results if r is not None]
        assert len(job_ids) == len(set(job_ids))
        assert len(job_ids) == 10


# ══════════════════════════════════════════════════════════════
# Delayed Items
# ══════════════════════════════════════════════════════════════

class TestDelayedItems:
    """Tests for scheduled/delayed items."""

    @pytest.mark.asyncio
    async def test_delayed_item_not_ready(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Delayed item is not dequeued before scheduled time."""
        item = make_item(job_id="job_delayed")
        item.scheduled_at = time.time() + 10  # 10 seconds in future

        await queue.enqueue(item)

        # Should not be available yet
        result = await queue.dequeue()
        assert result is None

    @pytest.mark.asyncio
    async def test_delayed_item_becomes_ready(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Delayed item becomes available after scheduled time."""
        item = make_item(job_id="job_delayed2")
        item.scheduled_at = time.time() + 0.5

        await queue.enqueue(item)

        # Wait for scheduled time
        await asyncio.sleep(0.6)

        result = await queue.dequeue()
        assert result is not None
        assert result.job_id == "job_delayed2"


# ══════════════════════════════════════════════════════════════
# Health Check
# ══════════════════════════════════════════════════════════════

class TestHealthCheck:
    """Tests for backend health check."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, queue: MemoryQueueBackend) -> None:
        """Health check returns True when operational."""
        assert await queue.health_check() is True


# ══════════════════════════════════════════════════════════════
# Dead Letter Queue
# ══════════════════════════════════════════════════════════════

class TestDeadLetter:
    """Tests for dead letter queue."""

    @pytest.mark.asyncio
    async def test_retry_dead_letter(
        self,
        queue: MemoryQueueBackend,
        make_item: Any,
    ) -> None:
        """Retry a dead letter item."""
        item = make_item(job_id="job_dl_retry")
        await queue.enqueue(item)

        dequeued = await queue.dequeue()
        assert dequeued is not None
        await queue.reject(dequeued.item_id, error="Failed", retry=False)

        # In dead letter
        dead = await queue.get_dead_letter_items()
        assert len(dead) == 1

        # Retry
        result = await queue.retry_dead_letter(dead[0].item_id)
        assert result is True

        # Dead letter should be empty
        dead_after = await queue.get_dead_letter_items()
        assert len(dead_after) == 0

        # Item back in queue
        assert await queue.size() == 1


# ══════════════════════════════════════════════════════════════
# QueueItem Model
# ══════════════════════════════════════════════════════════════

class TestQueueItemModel:
    """Tests for QueueItem data model."""

    def test_item_creation(self) -> None:
        """Create a queue item with defaults."""
        item = QueueItem(job_id="test", job_type="crawl")
        assert item.item_id.startswith("qi_")
        assert item.status == JobStatus.PENDING
        assert item.attempts == 0

    def test_item_serialization(self) -> None:
        """Serialize and deserialize."""
        item = QueueItem(
            job_id="test",
            job_type="scrape",
            payload={"url": "https://example.com"},
        )

        data = item.to_dict()
        restored = QueueItem.from_dict(data)

        assert restored.job_id == item.job_id
        assert restored.job_type == item.job_type
        assert restored.payload == item.payload

    def test_item_is_ready(self) -> None:
        """is_ready checks scheduled time."""
        item = QueueItem(job_id="test")
        assert item.is_ready  # No scheduled time

        item.scheduled_at = time.time() + 100
        assert not item.is_ready

        item.scheduled_at = time.time() - 1
        assert item.is_ready

    def test_item_can_retry(self) -> None:
        """can_retry checks attempts vs max."""
        item = QueueItem(job_id="test", max_attempts=3)
        assert item.can_retry

        item.attempts = 3
        assert not item.can_retry