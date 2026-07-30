"""
AgentCrawl — Redis Queue Backend
====================================

Redis-backed job queue for distributed/production deployments.

Features:
    - Redis sorted sets for priority ordering
    - Redis hashes for item storage
    - Atomic dequeue via Lua scripts
    - Exponential backoff retry
    - Dead letter queue
    - TTL-based expiration
    - Connection pooling
    - Statistics via Redis keys

Prerequisites:
    pip install redis

Usage:
    from server.queue.redis import RedisQueueBackend

    backend = RedisQueueBackend(redis_url="redis://localhost:6379")
    await backend.start()

    await backend.enqueue(QueueItem(job_id="j1", payload={"url": "..."}))
    item = await backend.dequeue()
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from server.queue.base import (
    JobStatus,
    QueueBackend,
    QueueItem,
    QueueStats,
)

logger = logging.getLogger("agentcrawl.server.queue.redis")


# ══════════════════════════════════════════════════════════════
# Lua Scripts
# ══════════════════════════════════════════════════════════════

# Atomic dequeue: pop highest-priority ready item
DEQUEUE_LUA = """
local queue_key = KEYS[1]
local processing_key = KEYS[2]
local now = tonumber(ARGV[1])

-- Get items sorted by score (priority + time)
local items = redis.call('ZRANGEBYSCORE', queue_key, '-inf', now, 'LIMIT', 0, 1)

if #items == 0 then
    return nil
end

local item_id = items[1]

-- Remove from queue
redis.call('ZREM', queue_key, item_id)

-- Add to processing set
redis.call('SADD', processing_key, item_id)

return item_id
"""

# Atomic acknowledge: remove from processing, mark completed
ACK_LUA = """
local processing_key = KEYS[1]
local item_id = ARGV[1]

local removed = redis.call('SREM', processing_key, item_id)
return removed
"""


# ══════════════════════════════════════════════════════════════
# Redis Queue Backend
# ══════════════════════════════════════════════════════════════

class RedisQueueBackend(QueueBackend):
    """
    Redis-backed queue backend for distributed deployments.

    Uses Redis sorted sets for priority ordering and hashes
    for item storage. All critical operations are atomic
    via Lua scripts.

    Args:
        redis_url: Redis connection URL.
        prefix: Key prefix for all queue keys.
        max_retries: Default max retry attempts.
        item_ttl: TTL for completed items (seconds).
        dead_letter_max: Max dead letter items.

    Example:
        >>> backend = RedisQueueBackend("redis://localhost:6379")
        >>> await backend.start()
        >>> await backend.enqueue(QueueItem(job_id="j1"))
        >>> item = await backend.dequeue()
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        prefix: str = "agentcrawl:queue",
        max_retries: int = 3,
        item_ttl: int = 86400,
        dead_letter_max: int = 1000,
    ):
        self._redis_url = redis_url
        self._prefix = prefix
        self._max_retries = max_retries
        self._item_ttl = item_ttl
        self._dead_letter_max = dead_letter_max

        self._redis: Any = None
        self._started: bool = False

        # Lua script SHAs
        self._dequeue_sha: str = ""
        self._ack_sha: str = ""

    # ──────────────────────────────────────────────────────────
    # Key Helpers
    # ──────────────────────────────────────────────────────────

    @property
    def _queue_key(self) -> str:
        """Sorted set of queued item IDs."""
        return f"{self._prefix}:pending"

    @property
    def _processing_key(self) -> str:
        """Set of processing item IDs."""
        return f"{self._prefix}:processing"

    @property
    def _dead_letter_key(self) -> str:
        """List of dead letter item IDs."""
        return f"{self._prefix}:dead_letter"

    @property
    def _stats_key(self) -> str:
        """Hash of queue statistics."""
        return f"{self._prefix}:stats"

    def _item_key(self, item_id: str) -> str:
        """Hash key for a specific item."""
        return f"{self._prefix}:item:{item_id}"

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Redis and load Lua scripts."""
        if self._started:
            return

        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise ImportError(
                "redis is required for RedisQueueBackend. "
                "Install with: pip install redis"
            ) from None

        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            max_connections=10,
        )

        # Test connection
        await self._redis.ping()

        # Load Lua scripts
        self._dequeue_sha = await self._redis.script_load(DEQUEUE_LUA)
        self._ack_sha = await self._redis.script_load(ACK_LUA)

        self._started = True
        logger.info("Redis queue backend connected: %s", self._redis_url)

    async def stop(self) -> None:
        """Disconnect from Redis."""
        if not self._started:
            return

        if self._redis:
            await self._redis.aclose()
            self._redis = None

        self._started = False
        logger.info("Redis queue backend disconnected")

    # ──────────────────────────────────────────────────────────
    # Queue Operations
    # ──────────────────────────────────────────────────────────

    async def enqueue(self, item: QueueItem) -> str:
        """
        Add an item to the queue.

        Stores item data in a Redis hash and adds the item_id
        to the priority sorted set.

        Args:
            item: Queue item.

        Returns:
            The item_id.
        """
        self._ensure_started()

        if item.max_attempts == 0:
            item.max_attempts = self._max_retries

        item.status = JobStatus.QUEUED

        # Calculate priority score
        # Higher priority = lower score (sorted set is ascending)
        # Within same priority, older items first
        scheduled = item.scheduled_at if item.scheduled_at > 0 else time.time()
        score = (-item.priority * 1_000_000_000) + scheduled

        # Store item data
        item_data = json.dumps(item.to_dict(), default=str)
        pipe = self._redis.pipeline()

        pipe.set(self._item_key(item.item_id), item_data)
        pipe.zadd(self._queue_key, {item.item_id: score})
        pipe.hincrby(self._stats_key, "total_enqueued", 1)

        # Set TTL on item data
        if self._item_ttl > 0:
            pipe.expire(self._item_key(item.item_id), self._item_ttl)

        await pipe.execute()

        logger.debug(
            "Enqueued: %s (job=%s, priority=%d, score=%.0f)",
            item.item_id,
            item.job_id,
            item.priority,
            score,
        )

        return item.item_id

    async def dequeue(self, timeout: float = 0.0) -> QueueItem | None:
        """
        Atomically dequeue the next ready item.

        Uses a Lua script for atomic pop from sorted set.

        Args:
            timeout: Max seconds to wait (0 = no wait).

        Returns:
            QueueItem, or None if empty/timeout.
        """
        self._ensure_started()

        deadline = time.time() + timeout if timeout > 0 else 0

        while True:
            now = time.time()

            # Atomic dequeue via Lua
            item_id = await self._redis.evalsha(
                self._dequeue_sha,
                2,  # number of keys
                self._queue_key,
                self._processing_key,
                str(now),
            )

            if item_id:
                # Load item data
                item = await self._load_item(item_id)

                if item:
                    item.status = JobStatus.PROCESSING
                    item.started_at = time.time()
                    item.attempts += 1

                    # Update stored item
                    await self._save_item(item)

                    # Track stats
                    wait_time = item.started_at - item.created_at
                    pipe = self._redis.pipeline()
                    pipe.hincrby(self._stats_key, "total_dequeued", 1)
                    pipe.hincrbyfloat(self._stats_key, "total_wait_time", wait_time)
                    await pipe.execute()

                    logger.debug(
                        "Dequeued: %s (attempt=%d, wait=%.1fs)",
                        item_id,
                        item.attempts,
                        wait_time,
                    )

                    return item

            # No item available
            if deadline == 0:
                return None

            if time.time() >= deadline:
                return None

            import asyncio
            await asyncio.sleep(min(0.1, deadline - time.time()))

    async def peek(self) -> QueueItem | None:
        """View the next item without removing."""
        self._ensure_started()

        # Get first item from sorted set
        items = await self._redis.zrange(self._queue_key, 0, 0)

        if not items:
            return None

        return await self._load_item(items[0])

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
            True if acknowledged.
        """
        self._ensure_started()

        # Atomic remove from processing
        removed = await self._redis.evalsha(
            self._ack_sha,
            1,
            self._processing_key,
            item_id,
        )

        if not removed:
            return False

        # Update item
        item = await self._load_item(item_id)
        if item:
            item.status = JobStatus.COMPLETED
            item.completed_at = time.time()
            item.result = result

            process_time = item.completed_at - item.started_at if item.started_at else 0

            await self._save_item(item)

            # Stats
            pipe = self._redis.pipeline()
            pipe.hincrby(self._stats_key, "total_completed", 1)
            pipe.hincrbyfloat(self._stats_key, "total_process_time", process_time)
            await pipe.execute()

            logger.debug("Acknowledged: %s (%.1fs)", item_id, process_time)

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
            True if rejected.
        """
        self._ensure_started()

        # Remove from processing
        await self._redis.srem(self._processing_key, item_id)

        item = await self._load_item(item_id)
        if not item:
            return False

        item.error = error

        if retry and item.can_retry:
            # Re-enqueue with backoff
            item.status = JobStatus.RETRYING
            item.started_at = 0.0
            item.completed_at = 0.0

            delay = min(2 ** item.attempts, 60)
            item.scheduled_at = time.time() + delay

            score = (-item.priority * 1_000_000_000) + item.scheduled_at

            pipe = self._redis.pipeline()
            pipe.set(self._item_key(item_id), json.dumps(item.to_dict(), default=str))
            pipe.zadd(self._queue_key, {item_id: score})
            await pipe.execute()

            logger.debug(
                "Rejected (retry %d/%d in %ds): %s",
                item.attempts,
                item.max_attempts,
                delay,
                item_id,
            )
        else:
            # Permanent failure
            item.status = JobStatus.FAILED
            item.completed_at = time.time()

            pipe = self._redis.pipeline()
            pipe.set(self._item_key(item_id), json.dumps(item.to_dict(), default=str))
            pipe.hincrby(self._stats_key, "total_failed", 1)

            # Dead letter queue
            pipe.lpush(self._dead_letter_key, item_id)
            pipe.ltrim(self._dead_letter_key, 0, self._dead_letter_max - 1)

            await pipe.execute()

            logger.warning("Rejected (permanent): %s — %s", item_id, error[:100])

        return True

    async def cancel(self, item_id: str) -> bool:
        """Cancel a queued or processing item."""
        self._ensure_started()

        # Remove from queue and processing
        pipe = self._redis.pipeline()
        pipe.zrem(self._queue_key, item_id)
        pipe.srem(self._processing_key, item_id)
        results = await pipe.execute()

        removed = any(r for r in results)

        if removed:
            item = await self._load_item(item_id)
            if item:
                item.status = JobStatus.CANCELLED
                item.completed_at = time.time()
                await self._save_item(item)

        return removed

    # ──────────────────────────────────────────────────────────
    # Queries
    # ──────────────────────────────────────────────────────────

    async def get_item(self, item_id: str) -> QueueItem | None:
        """Get an item by ID."""
        self._ensure_started()
        return await self._load_item(item_id)

    async def size(self) -> int:
        """Get queue size."""
        self._ensure_started()
        return await self._redis.zcard(self._queue_key)

    async def is_empty(self) -> bool:
        """Check if queue is empty."""
        return await self.size() == 0

    async def clear(self) -> int:
        """Remove all items."""
        self._ensure_started()

        count = await self.size()

        # Get all item IDs
        item_ids = await self._redis.zrange(self._queue_key, 0, -1)
        processing_ids = await self._redis.smembers(self._processing_key)

        pipe = self._redis.pipeline()

        # Delete item data
        for item_id in item_ids + list(processing_ids):
            pipe.delete(self._item_key(item_id))

        # Clear queue structures
        pipe.delete(self._queue_key)
        pipe.delete(self._processing_key)

        await pipe.execute()

        logger.info("Queue cleared: %d items removed", count)
        return count

    async def stats(self) -> QueueStats:
        """Get queue statistics."""
        self._ensure_started()

        pending = await self._redis.zcard(self._queue_key)
        processing = await self._redis.scard(self._processing_key)

        # Get counters from stats hash
        stats_data = await self._redis.hgetall(self._stats_key)

        total_enqueued = int(stats_data.get("total_enqueued", 0))
        total_dequeued = int(stats_data.get("total_dequeued", 0))
        total_completed = int(stats_data.get("total_completed", 0))
        total_failed = int(stats_data.get("total_failed", 0))
        total_wait = float(stats_data.get("total_wait_time", 0))
        total_process = float(stats_data.get("total_process_time", 0))

        dead_letter_count = await self._redis.llen(self._dead_letter_key)

        return QueueStats(
            pending=pending,
            processing=processing,
            completed=total_completed,
            failed=total_failed + dead_letter_count,
            total_enqueued=total_enqueued,
            total_dequeued=total_dequeued,
            total_completed=total_completed,
            total_failed=total_failed,
            avg_wait_seconds=total_wait / max(total_dequeued, 1),
            avg_process_seconds=total_process / max(total_completed, 1),
        )

    # ──────────────────────────────────────────────────────────
    # Dead Letter Queue
    # ──────────────────────────────────────────────────────────

    async def get_dead_letter_items(self, limit: int = 50) -> list[QueueItem]:
        """Get items from the dead letter queue."""
        self._ensure_started()

        item_ids = await self._redis.lrange(self._dead_letter_key, 0, limit - 1)

        items = []
        for item_id in item_ids:
            item = await self._load_item(item_id)
            if item:
                items.append(item)

        return items

    async def retry_dead_letter(self, item_id: str) -> bool:
        """Re-enqueue a dead letter item."""
        self._ensure_started()

        removed = await self._redis.lrem(self._dead_letter_key, 1, item_id)

        if not removed:
            return False

        item = await self._load_item(item_id)
        if not item:
            return False

        item.status = JobStatus.QUEUED
        item.attempts = 0
        item.error = None
        item.scheduled_at = 0.0

        score = (-item.priority * 1_000_000_000) + time.time()

        pipe = self._redis.pipeline()
        pipe.set(self._item_key(item_id), json.dumps(item.to_dict(), default=str))
        pipe.zadd(self._queue_key, {item_id: score})
        await pipe.execute()

        return True

    # ──────────────────────────────────────────────────────────
    # Health Check
    # ──────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            self._ensure_started()
            await self._redis.ping()
            return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────

    def _ensure_started(self) -> None:
        """Ensure the backend is started."""
        if not self._started or self._redis is None:
            raise RuntimeError("RedisQueueBackend not started. Call start() first.")

    async def _save_item(self, item: QueueItem) -> None:
        """Save item data to Redis."""
        data = json.dumps(item.to_dict(), default=str)
        await self._redis.set(self._item_key(item.item_id), data)

    async def _load_item(self, item_id: str) -> QueueItem | None:
        """Load item data from Redis."""
        data = await self._redis.get(self._item_key(item_id))

        if not data:
            return None

        try:
            return QueueItem.from_dict(json.loads(data))
        except Exception as e:
            logger.warning("Failed to deserialize item %s: %s", item_id, e)
            return None

    def __repr__(self) -> str:
        return f"RedisQueueBackend(url={self._redis_url!r})"
