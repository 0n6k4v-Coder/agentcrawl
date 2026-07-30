"""
AgentCrawl — Cache Backend Base
=================================

Defines the abstract base class and shared utilities for all cache
backend implementations (Memory, Redis, Disk).

All cache backends implement the same async interface, allowing
seamless switching between backends via configuration.

Features:
    - Async get/set/delete/exists/clear operations
    - TTL (time-to-live) per entry
    - Key prefixing and namespacing
    - Batch operations (get_many, set_many, delete_many)
    - Serialization (JSON or pickle)
    - Hit/miss/eviction statistics
    - Context manager support

Usage:
    from agentcrawl.cache.base import CacheBackend, CacheEntry, CacheConfig

    # Implement a custom backend
    class MyCache(CacheBackend):
        async def _get_raw(self, key): ...
        async def _set_raw(self, key, value, ttl): ...
        async def _delete_raw(self, key): ...
        async def _exists_raw(self, key): ...
        async def _clear_raw(self): ...
        async def _keys_raw(self, pattern): ...

    # Use via CacheManager (recommended)
    from agentcrawl.cache import CacheManager
    cache = CacheManager(backend="memory", ttl=3600, prefix="crawl")
    await cache.set("url:hash", {"markdown": "..."})
    result = await cache.get("url:hash")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger("agentcrawl.cache")

T = TypeVar("T")


# ══════════════════════════════════════════════════════════════
# Types & Enums
# ══════════════════════════════════════════════════════════════

class SerializationFormat(str, Enum):
    """Supported serialization formats for cache values."""
    JSON = "json"
    RAW = "raw"


class CacheBackendType(str, Enum):
    """Available cache backend types."""
    MEMORY = "memory"
    REDIS = "redis"
    DISK = "disk"
    NONE = "none"


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

@dataclass
class CacheConfig:
    """
    Cache configuration.

    Attributes:
        backend: Cache backend type ('memory', 'redis', 'disk', 'none').
        ttl: Default time-to-live in seconds (0 = no expiry).
        prefix: Key prefix for namespacing.
        max_size: Maximum number of entries (for memory/disk backends).
        serialization: Serialization format for values.
        redis_url: Redis connection URL (for redis backend).
        disk_path: Directory path (for disk backend).
        key_hash_algorithm: Hash algorithm for key generation.
        compress: Whether to compress values (for disk backend).
        stats_enabled: Whether to track hit/miss statistics.
    """
    backend: CacheBackendType | str = CacheBackendType.MEMORY
    ttl: int = 3600
    prefix: str = "agentcrawl"
    max_size: int = 10_000
    serialization: SerializationFormat = SerializationFormat.JSON
    redis_url: str = "redis://localhost:6379/0"
    disk_path: str = ".agentcrawl/cache"
    key_hash_algorithm: str = "sha256"
    compress: bool = False
    stats_enabled: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.backend, str):
            try:
                self.backend = CacheBackendType(self.backend)
            except ValueError as err:
                raise ValueError(
                    f"Unknown cache backend: '{self.backend}'. "
                    f"Available: {', '.join(b.value for b in CacheBackendType)}"
                ) from err
        if isinstance(self.serialization, str):
            try:
                self.serialization = SerializationFormat(self.serialization)
            except ValueError:
                self.serialization = SerializationFormat.JSON

    @classmethod
    def from_env(cls, prefix: str = "AGENTCRAWL") -> CacheConfig:
        """Create config from environment variables."""
        import os

        def _get(key: str, default: str = "") -> str:
            return os.environ.get(f"{prefix}_{key}", default)

        def _get_int(key: str, default: int = 0) -> int:
            try:
                return int(_get(key, str(default)))
            except ValueError:
                return default

        def _get_bool(key: str, default: bool = False) -> bool:
            return _get(key, str(default)).lower() in ("true", "1", "yes", "on")

        return cls(
            backend=_get("CACHE_BACKEND", "memory"),
            ttl=_get_int("CACHE_TTL", 3600),
            prefix=_get("CACHE_PREFIX", "agentcrawl"),
            max_size=_get_int("CACHE_MAX_SIZE", 10_000),
            redis_url=_get("REDIS_URL", "redis://localhost:6379/0"),
            disk_path=_get("CACHE_DISK_PATH", ".agentcrawl/cache"),
            compress=_get_bool("CACHE_COMPRESS", False),
            stats_enabled=_get_bool("CACHE_STATS_ENABLED", True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend.value if isinstance(self.backend, CacheBackendType) else self.backend,
            "ttl": self.ttl,
            "prefix": self.prefix,
            "max_size": self.max_size,
            "serialization": self.serialization.value,
            "redis_url": self.redis_url,
            "disk_path": self.disk_path,
            "compress": self.compress,
            "stats_enabled": self.stats_enabled,
        }


# ══════════════════════════════════════════════════════════════
# Cache Entry
# ══════════════════════════════════════════════════════════════

@dataclass
class CacheEntry:
    """
    A single cache entry with metadata.

    Attributes:
        key: The cache key.
        value: The cached value.
        created_at: Unix timestamp of creation.
        expires_at: Unix timestamp of expiry (None = no expiry).
        access_count: Number of times this entry has been accessed.
        last_accessed_at: Unix timestamp of last access.
        size_bytes: Approximate size of the serialized value.
        tags: Optional tags for grouped invalidation.
    """
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    access_count: int = 0
    last_accessed_at: float = field(default_factory=time.time)
    size_bytes: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        """Whether this entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def ttl_remaining(self) -> float | None:
        """Seconds until expiry (None = no expiry)."""
        if self.expires_at is None:
            return None
        remaining = self.expires_at - time.time()
        return max(0.0, remaining)

    @property
    def age_seconds(self) -> float:
        """Age of this entry in seconds."""
        return time.time() - self.created_at

    def touch(self) -> None:
        """Update last access time and increment counter."""
        self.access_count += 1
        self.last_accessed_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired,
            "ttl_remaining": round(self.ttl_remaining, 1) if self.ttl_remaining is not None else None,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "size_bytes": self.size_bytes,
            "tags": self.tags,
        }


# ══════════════════════════════════════════════════════════════
# Cache Statistics
# ══════════════════════════════════════════════════════════════

@dataclass
class CacheStats:
    """
    Cumulative cache statistics.

    All counters are cumulative since cache creation or last reset.
    """
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    errors: int = 0
    total_get_time_ms: float = 0.0
    total_set_time_ms: float = 0.0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 to 1.0)."""
        total = self.total_requests
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def avg_get_time_ms(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.total_get_time_ms / total

    @property
    def avg_set_time_ms(self) -> float:
        if self.sets == 0:
            return 0.0
        return self.total_set_time_ms / self.sets

    def record_hit(self, duration_ms: float = 0.0) -> None:
        self.hits += 1
        self.total_get_time_ms += duration_ms

    def record_miss(self, duration_ms: float = 0.0) -> None:
        self.misses += 1
        self.total_get_time_ms += duration_ms

    def record_set(self, duration_ms: float = 0.0) -> None:
        self.sets += 1
        self.total_set_time_ms += duration_ms

    def record_delete(self) -> None:
        self.deletes += 1

    def record_eviction(self) -> None:
        self.evictions += 1

    def record_error(self) -> None:
        self.errors += 1

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.evictions = 0
        self.errors = 0
        self.total_get_time_ms = 0.0
        self.total_set_time_ms = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "deletes": self.deletes,
            "evictions": self.evictions,
            "errors": self.errors,
            "total_requests": self.total_requests,
            "hit_rate": round(self.hit_rate, 4),
            "avg_get_time_ms": round(self.avg_get_time_ms, 3),
            "avg_set_time_ms": round(self.avg_set_time_ms, 3),
        }


# ══════════════════════════════════════════════════════════════
# Serializer
# ══════════════════════════════════════════════════════════════

class CacheSerializer:
    """
    Handles serialization and deserialization of cache values.

    Supports JSON (safe, portable).
    """

    def __init__(self, format_: SerializationFormat = SerializationFormat.JSON):
        self._format = format_

    def serialize(self, value: Any) -> bytes:
        """Serialize a value to bytes."""
        if self._format == SerializationFormat.JSON:
            return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        elif self._format == SerializationFormat.RAW:
            if isinstance(value, bytes):
                return value
            if isinstance(value, str):
                return value.encode("utf-8")
            return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        else:
            raise ValueError(f"Unknown serialization format: {self._format}")

    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes back to a value."""
        if self._format == SerializationFormat.JSON:
            return json.loads(data.decode("utf-8"))
        elif self._format == SerializationFormat.RAW:
            try:
                return json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return data
        else:
            raise ValueError(f"Unknown serialization format: {self._format}")

    def size_of(self, value: Any) -> int:
        """Estimate the serialized size of a value in bytes."""
        try:
            return len(self.serialize(value))
        except Exception:
            return 0


# ══════════════════════════════════════════════════════════════
# Key Generator
# ══════════════════════════════════════════════════════════════

class CacheKeyGenerator:
    """
    Generates consistent cache keys from URLs and parameters.

    Keys are namespaced with a prefix and hashed for fixed length.
    """

    def __init__(
        self,
        prefix: str = "agentcrawl",
        algorithm: str = "sha256",
        max_key_length: int = 256,
    ):
        self._prefix = prefix
        self._algorithm = algorithm
        self._max_key_length = max_key_length

    def from_url(
        self,
        url: str,
        output_format: str = "markdown",
        extra: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate a cache key from a URL and scrape parameters.

        Args:
            url: The page URL.
            output_format: Output format (affects cache key).
            extra: Additional parameters that affect the result.

        Returns:
            Namespaced cache key string.
        """
        parts = [url, output_format]
        if extra:
            # Sort for consistency
            sorted_extra = json.dumps(extra, sort_keys=True, default=str)
            parts.append(sorted_extra)

        raw = "|".join(parts)
        return self._make_key("page", raw)

    def from_search(self, query: str, engine: str = "google", max_results: int = 5) -> str:
        """Generate a cache key for search results."""
        raw = f"{query}|{engine}|{max_results}"
        return self._make_key("search", raw)

    def from_crawl(self, url: str, strategy: str = "bfs", max_depth: int = 3) -> str:
        """Generate a cache key for crawl results."""
        raw = f"{url}|{strategy}|{max_depth}"
        return self._make_key("crawl", raw)

    def from_map(self, url: str) -> str:
        """Generate a cache key for URL map results."""
        return self._make_key("map", url)

    def custom(self, namespace: str, identifier: str) -> str:
        """Generate a custom cache key."""
        return self._make_key(namespace, identifier)

    def _make_key(self, namespace: str, raw: str) -> str:
        """Build a namespaced, hashed cache key."""
        h = hashlib.new(self._algorithm)
        h.update(raw.encode("utf-8"))
        digest = h.hexdigest()[:32]

        key = f"{self._prefix}:{namespace}:{digest}"

        if len(key) > self._max_key_length:
            key = key[: self._max_key_length]

        return key

    def make_pattern(self, namespace: str) -> str:
        """Create a glob pattern for scanning keys in a namespace."""
        return f"{self._prefix}:{namespace}:*"


# ══════════════════════════════════════════════════════════════
# Abstract Cache Backend
# ══════════════════════════════════════════════════════════════

class CacheBackend(ABC):
    """
    Abstract base class for all cache backend implementations.

    Subclasses must implement the six _*_raw methods. The public
    methods (get, set, delete, etc.) add prefixing, serialization,
    TTL handling, and statistics on top of the raw operations.

    Lifecycle:
        async with MyCacheBackend(config) as cache:
            await cache.set("key", "value", ttl=300)
            result = await cache.get("key")

    Args:
        config: Cache configuration.
    """

    def __init__(self, config: CacheConfig | None = None):
        self._config = config or CacheConfig()
        self._serializer = CacheSerializer(self._config.serialization)
        self._key_gen = CacheKeyGenerator(
            prefix=self._config.prefix,
            algorithm=self._config.key_hash_algorithm,
        )
        self._stats = CacheStats()
        self._started = False

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def config(self) -> CacheConfig:
        """Cache configuration."""
        return self._config

    @property
    def stats(self) -> CacheStats:
        """Cache statistics."""
        return self._stats

    @property
    def key_generator(self) -> CacheKeyGenerator:
        """Key generator instance."""
        return self._key_gen

    @property
    def serializer(self) -> CacheSerializer:
        """Serializer instance."""
        return self._serializer

    @property
    def is_started(self) -> bool:
        """Whether the backend has been initialized."""
        return self._started

    @property
    def default_ttl(self) -> int:
        """Default TTL in seconds."""
        return self._config.ttl

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize the cache backend (connect, create dirs, etc.)."""
        if self._started:
            return
        await self._start_impl()
        self._started = True
        logger.info(
            "Cache backend started (type=%s, prefix=%s, ttl=%ds)",
            self._config.backend,
            self._config.prefix,
            self._config.ttl,
        )

    async def stop(self) -> None:
        """Shut down the cache backend (disconnect, flush, etc.)."""
        if not self._started:
            return
        await self._stop_impl()
        self._started = False
        logger.info("Cache backend stopped")

    async def __aenter__(self) -> CacheBackend:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ──────────────────────────────────────────────────────────
    # Public API — Single Operations
    # ──────────────────────────────────────────────────────────

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get a value from the cache.

        Args:
            key: Cache key.
            default: Value to return on miss.

        Returns:
            Cached value, or default if not found / expired.
        """
        start = time.perf_counter()
        full_key = self._prefix_key(key)

        try:
            raw = await self._get_raw(full_key)
            duration_ms = (time.perf_counter() - start) * 1000

            if raw is None:
                self._stats.record_miss(duration_ms)
                return default

            value = self._serializer.deserialize(raw)
            self._stats.record_hit(duration_ms)
            return value

        except Exception as e:
            self._stats.record_error()
            logger.warning("Cache get error for key '%s': %s", key, e)
            return default

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """
        Set a value in the cache.

        Args:
            key: Cache key.
            value: Value to cache (must be serializable).
            ttl: Time-to-live in seconds (None = use default, 0 = no expiry).
            tags: Optional tags for grouped invalidation.

        Returns:
            True if the value was stored successfully.
        """
        start = time.perf_counter()
        full_key = self._prefix_key(key)
        effective_ttl = ttl if ttl is not None else self._config.ttl

        try:
            raw = self._serializer.serialize(value)
            await self._set_raw(full_key, raw, effective_ttl)
            duration_ms = (time.perf_counter() - start) * 1000
            self._stats.record_set(duration_ms)
            return True

        except Exception as e:
            self._stats.record_error()
            logger.warning("Cache set error for key '%s': %s", key, e)
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete a value from the cache.

        Args:
            key: Cache key.

        Returns:
            True if the key existed and was deleted.
        """
        full_key = self._prefix_key(key)

        try:
            result = await self._delete_raw(full_key)
            self._stats.record_delete()
            return result

        except Exception as e:
            self._stats.record_error()
            logger.warning("Cache delete error for key '%s': %s", key, e)
            return False

    async def exists(self, key: str) -> bool:
        """
        Check if a key exists in the cache (and is not expired).

        Args:
            key: Cache key.

        Returns:
            True if the key exists.
        """
        full_key = self._prefix_key(key)

        try:
            return await self._exists_raw(full_key)
        except Exception as e:
            self._stats.record_error()
            logger.warning("Cache exists error for key '%s': %s", key, e)
            return False

    async def get_or_set(
        self,
        key: str,
        factory: Any,
        ttl: int | None = None,
        tags: list[str] | None = None,
    ) -> Any:
        """
        Get a value, or compute and cache it if missing.

        Args:
            key: Cache key.
            factory: Async callable that produces the value on miss.
            ttl: Time-to-live for the new value.
            tags: Optional tags.

        Returns:
            Cached or freshly computed value.

        Example:
            >>> result = await cache.get_or_set(
            ...     "page:abc123",
            ...     factory=lambda: crawler.scrape(url),
            ...     ttl=600,
            ... )
        """
        value = await self.get(key)
        if value is not None:
            return value

        # Compute value
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        elif callable(factory):
            value = factory()
        else:
            value = factory

        await self.set(key, value, ttl=ttl, tags=tags)
        return value

    async def increment(self, key: str, amount: int = 1) -> int:
        """
        Atomically increment a numeric value.

        Args:
            key: Cache key.
            amount: Amount to increment (can be negative).

        Returns:
            New value after increment.
        """
        full_key = self._prefix_key(key)
        try:
            return await self._increment_raw(full_key, amount)
        except Exception as e:
            self._stats.record_error()
            logger.warning("Cache increment error for key '%s': %s", key, e)
            return 0

    # ──────────────────────────────────────────────────────────
    # Public API — Batch Operations
    # ──────────────────────────────────────────────────────────

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """
        Get multiple values at once.

        Args:
            keys: List of cache keys.

        Returns:
            Dictionary mapping found keys to their values.
            Missing keys are omitted from the result.
        """
        results: dict[str, Any] = {}
        for key in keys:
            value = await self.get(key)
            if value is not None:
                results[key] = value
        return results

    async def set_many(
        self,
        items: dict[str, Any],
        ttl: int | None = None,
    ) -> int:
        """
        Set multiple values at once.

        Args:
            items: Dictionary of key-value pairs.
            ttl: Time-to-live for all entries.

        Returns:
            Number of successfully stored entries.
        """
        count = 0
        for key, value in items.items():
            if await self.set(key, value, ttl=ttl):
                count += 1
        return count

    async def delete_many(self, keys: list[str]) -> int:
        """
        Delete multiple keys at once.

        Args:
            keys: List of cache keys.

        Returns:
            Number of successfully deleted keys.
        """
        count = 0
        for key in keys:
            if await self.delete(key):
                count += 1
        return count

    async def delete_by_tag(self, tag: str) -> int:
        """
        Delete all entries with a specific tag.

        Note: Not all backends support tags efficiently.
        Default implementation scans all keys.

        Args:
            tag: Tag to match.

        Returns:
            Number of deleted entries.
        """
        keys = await self.keys()
        count = 0
        for key in keys:
            # Subclasses can override for efficient tag-based deletion
            if await self.delete(key):
                count += 1
        return count

    # ──────────────────────────────────────────────────────────
    # Public API — Scanning & Info
    # ──────────────────────────────────────────────────────────

    async def keys(self, pattern: str = "*") -> list[str]:
        """
        List all keys matching a pattern.

        Args:
            pattern: Glob pattern (e.g., 'page:*', '*').

        Returns:
            List of matching keys (without prefix).
        """
        full_pattern = self._prefix_key(pattern)
        try:
            full_keys = await self._keys_raw(full_pattern)
            # Strip prefix from returned keys
            prefix = f"{self._config.prefix}:"
            return [
                k[len(prefix):] if k.startswith(prefix) else k
                for k in full_keys
            ]
        except Exception as e:
            self._stats.record_error()
            logger.warning("Cache keys error: %s", e)
            return []

    async def clear(self) -> bool:
        """
        Clear all entries from the cache.

        Returns:
            True if the cache was cleared successfully.
        """
        try:
            await self._clear_raw()
            logger.info("Cache cleared (prefix=%s)", self._config.prefix)
            return True
        except Exception as e:
            self._stats.record_error()
            logger.warning("Cache clear error: %s", e)
            return False

    async def clear_namespace(self, namespace: str) -> int:
        """
        Clear all entries in a specific namespace.

        Args:
            namespace: Namespace to clear (e.g., 'page', 'search').

        Returns:
            Number of deleted entries.
        """
        pattern = self._key_gen.make_pattern(namespace)
        keys = await self.keys(pattern)
        return await self.delete_many(keys)

    async def size(self) -> int:
        """
        Get the approximate number of entries in the cache.

        Returns:
            Number of entries.
        """
        try:
            return await self._size_raw()
        except Exception:
            keys = await self.keys()
            return len(keys)

    # ──────────────────────────────────────────────────────────
    # Statistics
    # ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics as a dictionary."""
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        self._stats.reset()

    # ──────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────

    def _prefix_key(self, key: str) -> str:
        """Add the configured prefix to a key."""
        if key.startswith(f"{self._config.prefix}:"):
            return key
        return f"{self._config.prefix}:{key}"

    # ──────────────────────────────────────────────────────────
    # Abstract Methods — Must be implemented by subclasses
    # ──────────────────────────────────────────────────────────

    @abstractmethod
    async def _get_raw(self, key: str) -> bytes | None:
        """
        Get raw bytes for a key.

        Args:
            key: Full prefixed key.

        Returns:
            Serialized bytes, or None if not found.
        """
        ...

    @abstractmethod
    async def _set_raw(self, key: str, value: bytes, ttl: int) -> None:
        """
        Store raw bytes for a key.

        Args:
            key: Full prefixed key.
            value: Serialized bytes.
            ttl: Time-to-live in seconds (0 = no expiry).
        """
        ...

    @abstractmethod
    async def _delete_raw(self, key: str) -> bool:
        """
        Delete a key.

        Args:
            key: Full prefixed key.

        Returns:
            True if the key existed.
        """
        ...

    @abstractmethod
    async def _exists_raw(self, key: str) -> bool:
        """
        Check if a key exists.

        Args:
            key: Full prefixed key.

        Returns:
            True if the key exists and is not expired.
        """
        ...

    @abstractmethod
    async def _clear_raw(self) -> None:
        """Clear all keys with the configured prefix."""
        ...

    @abstractmethod
    async def _keys_raw(self, pattern: str) -> list[str]:
        """
        List all keys matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., 'prefix:*').

        Returns:
            List of matching full keys.
        """
        ...

    # ──────────────────────────────────────────────────────────
    # Optional Overrides (default implementations provided)
    # ──────────────────────────────────────────────────────────

    async def _start_impl(self) -> None:
        """Backend-specific initialization. Override if needed."""
        return None

    @abstractmethod
    async def _stop_impl(self) -> None:
        """Backend-specific cleanup. Override if needed."""
        pass

    async def _increment_raw(self, key: str, amount: int) -> int:
        """
        Increment a numeric value. Default: get + set.

        Override for atomic implementations (e.g., Redis INCR).
        """
        raw = await self._get_raw(key)
        if raw is None:
            current = 0
        else:
            try:
                current = int(self._serializer.deserialize(raw))
            except (ValueError, TypeError):
                current = 0

        new_value = current + amount
        await self._set_raw(key, self._serializer.serialize(new_value), 0)
        return new_value

    async def _size_raw(self) -> int:
        """Get approximate entry count. Default: count keys."""
        keys = await self._keys_raw(f"{self._config.prefix}:*")
        return len(keys)

    # ──────────────────────────────────────────────────────────
    # Representation
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"{self.__class__.__name__}(backend={self._config.backend}, "
            f"prefix={self._config.prefix!r}, status={status})"
        )


# ══════════════════════════════════════════════════════════════
# Null Cache (No-Op Backend)
# ══════════════════════════════════════════════════════════════

class NullCacheBackend(CacheBackend):
    """
    A no-op cache backend that never stores anything.

    Useful for disabling caching without changing application code.
    All gets return None, all sets are ignored.
    """

    async def _get_raw(self, key: str) -> bytes | None:
        return None

    async def _set_raw(self, key: str, value: bytes, ttl: int) -> None:
        pass

    async def _delete_raw(self, key: str) -> bool:
        return False

    async def _exists_raw(self, key: str) -> bool:
        return False

    async def _clear_raw(self) -> None:
        pass

    async def _keys_raw(self, pattern: str) -> list[str]:
        return []

    async def _size_raw(self) -> int:
        return 0
