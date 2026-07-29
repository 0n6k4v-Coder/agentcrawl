"""
AgentCrawl — Memory Cache Backend
====================================

In-process LRU cache with TTL expiry, periodic cleanup, and
approximate memory tracking. Ideal for development, single-process
deployments, and as an L1 cache in multi-level configurations.

Storage:
    Entries are stored in a Python dictionary with O(1) lookup.
    An OrderedDict-based LRU tracker evicts the least-recently-used
    entries when max_size is exceeded.

Features:
    - O(1) get / set / delete / exists
    - Lazy TTL expiry (checked on read)
    - Background periodic cleanup of expired entries
    - LRU eviction when max_size is exceeded
    - Approximate memory usage tracking
    - Tag-based grouped invalidation
    - Thread-safe via asyncio.Lock

Usage:
    from agentcrawl.cache.memory import MemoryCacheBackend
    from agentcrawl.cache.base import CacheConfig

    config = CacheConfig(backend="memory", ttl=300, max_size=5000)

    async with MemoryCacheBackend(config) as cache:
        await cache.set("key", {"data": "value"}, ttl=60)
        result = await cache.get("key")
        print(result)

        # Stats
        print(cache.stats.hit_rate)
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.cache.base import (
    CacheBackend,
    CacheConfig,
    CacheEntry,
)

logger = logging.getLogger("agentcrawl.cache.memory")


# ══════════════════════════════════════════════════════════════
# Internal Entry Model
# ══════════════════════════════════════════════════════════════

@dataclass(slots=True)
class _MemEntry:
    """
    Internal in-memory cache entry.

    Stores the raw serialized bytes alongside metadata for
    TTL checking, LRU tracking, and tag-based invalidation.

    Attributes:
        value: Serialized value bytes.
        created_at: Unix timestamp of creation.
        expires_at: Unix timestamp of expiry (None = no expiry).
        last_accessed_at: Unix timestamp of last access (for LRU).
        access_count: Number of times accessed.
        size_bytes: Approximate memory size of the value.
        tags: Tags for grouped invalidation.
    """
    value: bytes
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    last_accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    size_bytes: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        """Whether this entry has passed its TTL."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def ttl_remaining(self) -> float | None:
        """Seconds until expiry (None = no expiry)."""
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - time.time())

    def touch(self) -> None:
        """Update access metadata."""
        self.access_count += 1
        self.last_accessed_at = time.time()


# ══════════════════════════════════════════════════════════════
# Memory Cache Backend
# ══════════════════════════════════════════════════════════════

class MemoryCacheBackend(CacheBackend):
    """
    In-process LRU cache with TTL expiry.

    Stores serialized values in a dictionary with an OrderedDict-based
    LRU tracker. Expired entries are lazily removed on read and
    periodically cleaned by a background task.

    Args:
        config: Cache configuration.

    Example:
        >>> config = CacheConfig(backend="memory", ttl=300, max_size=1000)
        >>> async with MemoryCacheBackend(config) as cache:
        ...     await cache.set("greeting", "hello world")
        ...     print(await cache.get("greeting"))
        ...     print(cache.stats.hit_rate)
    """

    def __init__(self, config: CacheConfig | None = None):
        super().__init__(config)

        # Core storage
        self._store: dict[str, _MemEntry] = {}

        # LRU tracker (key → last access order)
        self._lru: OrderedDict[str, None] = OrderedDict()

        # Concurrency lock
        self._lock = asyncio.Lock()

        # Background cleanup
        self._cleanup_task: asyncio.Task | None = None
        self._cleanup_interval: int = 60  # seconds

        # Memory tracking
        self._total_bytes: int = 0

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def entry_count(self) -> int:
        """Number of entries currently in the cache (including expired)."""
        return len(self._store)

    @property
    def active_count(self) -> int:
        """Number of non-expired entries."""
        now = time.time()
        return sum(
            1 for e in self._store.values()
            if e.expires_at is None or e.expires_at > now
        )

    @property
    def total_bytes(self) -> int:
        """Approximate total memory usage in bytes."""
        return self._total_bytes

    @property
    def total_mb(self) -> float:
        """Approximate total memory usage in megabytes."""
        return self._total_bytes / (1024 * 1024)

    @property
    def max_size(self) -> int:
        """Maximum number of entries."""
        return self._config.max_size

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def _start_impl(self) -> None:
        """Start the background cleanup task."""
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop()
        )
        logger.info(
            "Memory cache started (max_size=%d, ttl=%ds, cleanup_interval=%ds)",
            self._config.max_size,
            self._config.ttl,
            self._cleanup_interval,
        )

    async def _stop_impl(self) -> None:
        """Cancel the background cleanup task and clear storage."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        self._store.clear()
        self._lru.clear()
        self._total_bytes = 0
        logger.info("Memory cache stopped")

    # ──────────────────────────────────────────────────────────
    # CacheBackend Implementation
    # ──────────────────────────────────────────────────────────

    async def _get_raw(self, key: str) -> bytes | None:
        """Get raw bytes for a key."""
        async with self._lock:
            entry = self._store.get(key)

            if entry is None:
                return None

            # Lazy expiry check
            if entry.is_expired:
                self._remove_entry(key, entry)
                return None

            # Update LRU and access metadata
            entry.touch()
            self._lru_move_to_end(key)

            return entry.value

    async def _set_raw(self, key: str, value: bytes, ttl: int) -> None:
        """Store raw bytes for a key."""
        async with self._lock:
            # Calculate expiry
            now = time.time()
            expires_at = (now + ttl) if ttl > 0 else None

            # Estimate size
            size_bytes = self._estimate_size(key, value)

            # Remove existing entry if present (to update size tracking)
            existing = self._store.get(key)
            if existing is not None:
                self._remove_entry(key, existing)

            # Create new entry
            entry = _MemEntry(
                value=value,
                created_at=now,
                expires_at=expires_at,
                last_accessed_at=now,
                access_count=0,
                size_bytes=size_bytes,
            )

            # Evict if over capacity
            await self._evict_if_needed_unlocked()

            # Store
            self._store[key] = entry
            self._lru[key] = None
            self._total_bytes += size_bytes

    async def _delete_raw(self, key: str) -> bool:
        """Delete a key."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False

            self._remove_entry(key, entry)
            return True

    async def _exists_raw(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False

            if entry.is_expired:
                self._remove_entry(key, entry)
                return False

            return True

    async def _clear_raw(self) -> None:
        """Clear all entries with the configured prefix."""
        async with self._lock:
            prefix = f"{self._config.prefix}:"
            keys_to_remove = [
                k for k in self._store
                if k.startswith(prefix)
            ]

            for key in keys_to_remove:
                entry = self._store[key]
                self._remove_entry(key, entry)

            logger.debug("Cleared %d entries from memory cache", len(keys_to_remove))

    async def _keys_raw(self, pattern: str) -> list[str]:
        """List all keys matching a glob pattern."""
        async with self._lock:
            # Clean expired first
            self._remove_expired_unlocked()

            if pattern == "*":
                return list(self._store.keys())

            return [
                key for key in self._store
                if fnmatch.fnmatch(key, pattern)
            ]

    async def _size_raw(self) -> int:
        """Get the number of non-expired entries."""
        async with self._lock:
            self._remove_expired_unlocked()
            return len(self._store)

    async def _increment_raw(self, key: str, amount: int) -> int:
        """Atomically increment a numeric value."""
        async with self._lock:
            entry = self._store.get(key)

            if entry is None or entry.is_expired:
                current = 0
                if entry is not None:
                    self._remove_entry(key, entry)
            else:
                try:
                    current = int(self._serializer.deserialize(entry.value))
                except (ValueError, TypeError):
                    current = 0

            new_value = current + amount
            new_raw = self._serializer.serialize(new_value)

            now = time.time()
            new_entry = _MemEntry(
                value=new_raw,
                created_at=now,
                expires_at=entry.expires_at if entry else None,
                last_accessed_at=now,
                access_count=0,
                size_bytes=self._estimate_size(key, new_raw),
            )

            if entry is not None:
                self._total_bytes -= entry.size_bytes

            self._store[key] = new_entry
            self._lru[key] = None
            self._total_bytes += new_entry.size_bytes

            return new_value

    # ──────────────────────────────────────────────────────────
    # Tag-Based Operations
    # ──────────────────────────────────────────────────────────

    async def set_with_tags(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """
        Set a value with associated tags for grouped invalidation.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Time-to-live in seconds.
            tags: Tags for grouped deletion.

        Returns:
            True if stored successfully.
        """
        effective_ttl = ttl if ttl is not None else self._config.ttl
        full_key = self._prefix_key(key)

        async with self._lock:
            now = time.time()
            expires_at = (now + effective_ttl) if effective_ttl > 0 else None
            raw = self._serializer.serialize(value)
            size_bytes = self._estimate_size(full_key, raw)

            existing = self._store.get(full_key)
            if existing is not None:
                self._remove_entry(full_key, existing)

            await self._evict_if_needed_unlocked()

            entry = _MemEntry(
                value=raw,
                created_at=now,
                expires_at=expires_at,
                size_bytes=size_bytes,
                tags=tags or [],
            )

            self._store[full_key] = entry
            self._lru[full_key] = None
            self._total_bytes += size_bytes

        return True

    async def delete_by_tag(self, tag: str) -> int:
        """
        Delete all entries with a specific tag.

        Args:
            tag: Tag to match.

        Returns:
            Number of deleted entries.
        """
        async with self._lock:
            keys_to_remove = [
                key for key, entry in self._store.items()
                if tag in entry.tags
            ]

            for key in keys_to_remove:
                entry = self._store[key]
                self._remove_entry(key, entry)

            return len(keys_to_remove)

    async def delete_by_tags(self, tags: list[str]) -> int:
        """
        Delete all entries matching ANY of the given tags.

        Args:
            tags: List of tags to match.

        Returns:
            Number of deleted entries.
        """
        tag_set = set(tags)
        async with self._lock:
            keys_to_remove = [
                key for key, entry in self._store.items()
                if tag_set.intersection(entry.tags)
            ]

            for key in keys_to_remove:
                entry = self._store[key]
                self._remove_entry(key, entry)

            return len(keys_to_remove)

    # ──────────────────────────────────────────────────────────
    # Entry Inspection
    # ──────────────────────────────────────────────────────────

    async def get_entry(self, key: str) -> CacheEntry | None:
        """
        Get full metadata for a cache entry (without the value).

        Args:
            key: Cache key (without prefix).

        Returns:
            CacheEntry with metadata, or None if not found.
        """
        full_key = self._prefix_key(key)

        async with self._lock:
            entry = self._store.get(full_key)
            if entry is None:
                return None

            if entry.is_expired:
                self._remove_entry(full_key, entry)
                return None

            return CacheEntry(
                key=key,
                value=None,
                created_at=entry.created_at,
                expires_at=entry.expires_at,
                access_count=entry.access_count,
                last_accessed_at=entry.last_accessed_at,
                size_bytes=entry.size_bytes,
                tags=entry.tags,
            )

    async def get_ttl(self, key: str) -> float | None:
        """
        Get the remaining TTL for a key.

        Args:
            key: Cache key.

        Returns:
            Seconds remaining, None if no expiry, or None if key not found.
        """
        full_key = self._prefix_key(key)

        async with self._lock:
            entry = self._store.get(full_key)
            if entry is None:
                return None

            if entry.is_expired:
                self._remove_entry(full_key, entry)
                return None

            return entry.ttl_remaining

    async def set_ttl(self, key: str, ttl: int) -> bool:
        """
        Update the TTL for an existing key.

        Args:
            key: Cache key.
            ttl: New TTL in seconds (0 = remove expiry).

        Returns:
            True if the key existed and TTL was updated.
        """
        full_key = self._prefix_key(key)

        async with self._lock:
            entry = self._store.get(full_key)
            if entry is None:
                return False

            if entry.is_expired:
                self._remove_entry(full_key, entry)
                return False

            if ttl > 0:
                entry.expires_at = time.time() + ttl
            else:
                entry.expires_at = None

            return True

    # ──────────────────────────────────────────────────────────
    # LRU Eviction
    # ──────────────────────────────────────────────────────────

    async def _evict_if_needed_unlocked(self) -> None:
        """
        Evict LRU entries if over max_size.

        Must be called while holding self._lock.
        """
        if self._config.max_size <= 0:
            return

        while len(self._store) >= self._config.max_size and self._lru:
            # Pop the least recently used key
            evict_key, _ = self._lru.popitem(last=False)
            entry = self._store.pop(evict_key, None)
            if entry:
                self._total_bytes -= entry.size_bytes
                self._stats.record_eviction()
                logger.debug("LRU evicted: %s", evict_key)

    # ──────────────────────────────────────────────────────────
    # Background Cleanup
    # ──────────────────────────────────────────────────────────

    async def _cleanup_loop(self) -> None:
        """Periodically remove expired entries."""
        while self._started:
            try:
                await asyncio.sleep(self._cleanup_interval)
                if not self._started:
                    break

                async with self._lock:
                    removed = self._remove_expired_unlocked()

                if removed > 0:
                    logger.debug("Cleanup removed %d expired entries", removed)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Memory cache cleanup error: %s", e)

    def _remove_expired_unlocked(self) -> int:
        """
        Remove all expired entries.

        Must be called while holding self._lock.

        Returns:
            Number of entries removed.
        """
        expired_keys = [
            key for key, entry in self._store.items()
            if entry.is_expired
        ]

        for key in expired_keys:
            entry = self._store[key]
            self._remove_entry(key, entry)

        return len(expired_keys)

    # ──────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────

    def _remove_entry(self, key: str, entry: _MemEntry) -> None:
        """
        Remove an entry from storage and LRU tracker.

        Must be called while holding self._lock.
        """
        self._store.pop(key, None)
        self._lru.pop(key, None)
        self._total_bytes -= entry.size_bytes

    def _lru_move_to_end(self, key: str) -> None:
        """Move a key to the end of the LRU tracker (most recent)."""
        if key in self._lru:
            self._lru.move_to_end(key)

    @staticmethod
    def _estimate_size(key: str, value: bytes) -> int:
        """
        Estimate the memory footprint of an entry.

        Includes key string, value bytes, and entry overhead.
        """
        # Key string size
        key_size = sys.getsizeof(key)
        # Value bytes size
        value_size = len(value)
        # Entry object overhead (approximate)
        entry_overhead = 128
        return key_size + value_size + entry_overhead

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    async def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics for monitoring."""
        async with self._lock:
            # Sample of entries (first 20)
            sample = []
            for i, (key, entry) in enumerate(self._store.items()):
                if i >= 20:
                    break
                sample.append({
                    "key": key[:80],
                    "size_bytes": entry.size_bytes,
                    "is_expired": entry.is_expired,
                    "ttl_remaining": round(entry.ttl_remaining, 1) if entry.ttl_remaining is not None else None,
                    "access_count": entry.access_count,
                    "age_seconds": round(time.time() - entry.created_at, 1),
                    "tags": entry.tags,
                })

            return {
                "backend": "memory",
                "entry_count": len(self._store),
                "active_count": self.active_count,
                "total_bytes": self._total_bytes,
                "total_mb": round(self.total_mb, 3),
                "max_size": self._config.max_size,
                "default_ttl": self._config.ttl,
                "lru_size": len(self._lru),
                "cleanup_interval": self._cleanup_interval,
                "stats": self._stats.to_dict(),
                "sample_entries": sample,
            }

    async def cleanup_expired(self) -> int:
        """
        Manually trigger cleanup of expired entries.

        Returns:
            Number of entries removed.
        """
        async with self._lock:
            return self._remove_expired_unlocked()

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"MemoryCacheBackend(entries={self.entry_count}, "
            f"size={self.total_mb:.2f}MB, "
            f"max={self._config.max_size}, status={status})"
        )
