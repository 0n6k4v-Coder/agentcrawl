"""
AgentCrawl — Redis Cache Backend
===================================

Redis-backed cache with native TTL, atomic operations, pipeline
batching, tag-based invalidation via Redis SETs, and automatic
reconnection.

Requires:
    pip install "agentcrawl[redis]"
    # or
    pip install "redis[hiredis]>=5.0.0"

Features:
    - Native Redis TTL (EXPIRE / PEXPIRE)
    - Atomic INCR / DECR operations
    - Pipeline batching for MGET / MSET
    - SCAN-based key pattern matching (non-blocking)
    - Tag-based grouped invalidation (SADD / SMEMBERS)
    - Connection pooling with automatic retry
    - Optional key compression (zlib)
    - Health check via PING

Usage:
    from agentcrawl.cache.redis import RedisCacheBackend
    from agentcrawl.cache.base import CacheConfig

    config = CacheConfig(
        backend="redis",
        redis_url="redis://localhost:6379/0",
        ttl=3600,
        prefix="agentcrawl",
    )

    async with RedisCacheBackend(config) as cache:
        await cache.set("page:abc", {"markdown": "# Hello"}, ttl=600)
        result = await cache.get("page:abc")
        print(result)

        # Tag-based invalidation
        await cache.set_with_tags("page:xyz", data, tags=["site:example.com"])
        await cache.delete_by_tag("site:example.com")

        # Atomic counter
        count = await cache.increment("stats:scrapes")
"""

from __future__ import annotations

import logging
import time
import zlib
from typing import Any

from agentcrawl.cache.base import (
    CacheBackend,
    CacheConfig,
    CacheEntry,
)

logger = logging.getLogger("agentcrawl.cache.redis")


# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════

# Redis key suffix for tag-to-keys mapping
_TAG_PREFIX = "__tags__:"

# Default SCAN batch size
_SCAN_COUNT = 200

# Maximum retry attempts for connection
_MAX_RETRIES = 3

# Delay between retries (seconds)
_RETRY_DELAY = 1.0


# ══════════════════════════════════════════════════════════════
# Redis Cache Backend
# ══════════════════════════════════════════════════════════════


class RedisCacheBackend(CacheBackend):
    """
    Redis-backed cache backend with native TTL and atomic operations.

    Uses the ``redis.asyncio`` client with connection pooling.
    Supports optional zlib compression for large values and
    tag-based grouped invalidation via Redis SETs.

    Args:
        config: Cache configuration.
        compress: Whether to compress values with zlib.
        compress_threshold: Minimum value size (bytes) to trigger compression.
        max_connections: Maximum connections in the pool.
        socket_timeout: Socket timeout in seconds.
        retry_on_timeout: Whether to retry on timeout errors.

    Example:
        >>> config = CacheConfig(backend="redis", redis_url="redis://localhost:6379/0")
        >>> async with RedisCacheBackend(config) as cache:
        ...     await cache.set("key", {"data": "value"}, ttl=300)
        ...     result = await cache.get("key")
        ...     print(result)
    """

    def __init__(
        self,
        config: CacheConfig | None = None,
        compress: bool = False,
        compress_threshold: int = 1024,
        max_connections: int = 20,
        socket_timeout: float = 5.0,
        retry_on_timeout: bool = True,
    ):
        super().__init__(config)

        self._compress = compress or self._config.compress
        self._compress_threshold = compress_threshold
        self._max_connections = max_connections
        self._socket_timeout = socket_timeout
        self._retry_on_timeout = retry_on_timeout

        # Redis client (initialized on start)
        self._redis: Any = None
        self._pool: Any = None

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def redis_url(self) -> str:
        """Redis connection URL."""
        return self._config.redis_url

    @property
    def client(self) -> Any:
        """The underlying redis.asyncio client instance."""
        if self._redis is None:
            raise RuntimeError("Redis client not initialized. Call start() first.")
        return self._redis

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def _start_impl(self) -> None:
        """Initialize Redis connection pool and verify connectivity."""
        try:
            import redis.asyncio as aioredis
        except ImportError as err:
            raise ImportError(
                "redis package required. Install with: "
                "pip install 'redis[hiredis]>=5.0.0' "
                "or pip install 'agentcrawl[redis]'"
            ) from err

        # Build connection pool
        self._pool = aioredis.ConnectionPool.from_url(
            self._config.redis_url,
            max_connections=self._max_connections,
            socket_timeout=self._socket_timeout,
            socket_connect_timeout=self._socket_timeout,
            retry_on_timeout=self._retry_on_timeout,
            decode_responses=False,  # We handle bytes ourselves
        )

        self._redis = aioredis.Redis(connection_pool=self._pool)

        # Verify connectivity
        try:
            pong = await self._redis.ping()
            if not pong:
                raise ConnectionError("Redis PING returned False")
        except Exception as e:
            await self._cleanup_client()
            raise ConnectionError(
                f"Failed to connect to Redis at {self._config.redis_url}: {e}"
            ) from e

        logger.info(
            "Redis cache connected to %s (max_connections=%d, compress=%s)",
            self._config.redis_url,
            self._max_connections,
            self._compress,
        )

    async def _stop_impl(self) -> None:
        """Close Redis connection pool."""
        await self._cleanup_client()
        logger.info("Redis cache disconnected")

    async def _cleanup_client(self) -> None:
        """Close the Redis client and pool."""
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.debug("Error closing Redis client: %s", e)
            self._redis = None

        if self._pool:
            try:
                await self._pool.disconnect()
            except Exception as e:
                logger.debug("Error disconnecting Redis pool: %s", e)
            self._pool = None

    # ──────────────────────────────────────────────────────────
    # Compression Helpers
    # ──────────────────────────────────────────────────────────

    def _maybe_compress(self, data: bytes) -> bytes:
        """Compress data if enabled and above threshold."""
        if self._compress and len(data) >= self._compress_threshold:
            # Prefix with magic byte to indicate compression
            return b"\x01" + zlib.compress(data, level=6)
        return b"\x00" + data

    def _maybe_decompress(self, data: bytes) -> bytes:
        """Decompress data if it was compressed."""
        if not data:
            return data

        flag = data[0:1]
        payload = data[1:]

        if flag == b"\x01":
            try:
                return zlib.decompress(payload)
            except zlib.error:
                logger.warning("Failed to decompress Redis value, returning raw")
                return payload
        return payload

    # ──────────────────────────────────────────────────────────
    # Tag Helpers
    # ──────────────────────────────────────────────────────────

    def _tag_key(self, tag: str) -> str:
        """Build the Redis key for a tag's member set."""
        return f"{self._config.prefix}:{_TAG_PREFIX}{tag}"

    async def _add_tags(self, full_key: str, tags: list[str]) -> None:
        """Register a key under its tags."""
        if not tags or not self._redis:
            return

        pipe = self._redis.pipeline(transaction=False)
        for tag in tags:
            tag_redis_key = self._tag_key(tag)
            pipe.sadd(tag_redis_key, full_key)
            # Give tag sets a long TTL so they don't leak
            pipe.expire(tag_redis_key, self._config.ttl * 4 if self._config.ttl > 0 else 86400 * 7)
        await pipe.execute()

    async def _remove_tags(self, full_key: str, tags: list[str]) -> None:
        """Unregister a key from its tags."""
        if not tags or not self._redis:
            return

        pipe = self._redis.pipeline(transaction=False)
        for tag in tags:
            pipe.srem(self._tag_key(tag), full_key)
        await pipe.execute()

    # ──────────────────────────────────────────────────────────
    # CacheBackend Implementation
    # ──────────────────────────────────────────────────────────

    async def _get_raw(self, key: str) -> bytes | None:
        """Get raw bytes from Redis."""
        if not self._redis:
            return None

        try:
            data = await self._redis.get(key)
            if data is None:
                return None
            return self._maybe_decompress(data)
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis GET error for key '%s': %s", key, e)
            return None

    async def _set_raw(self, key: str, value: bytes, ttl: int) -> None:
        """Store raw bytes in Redis with optional TTL."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        compressed = self._maybe_compress(value)

        try:
            if ttl > 0:
                await self._redis.setex(key, ttl, compressed)
            else:
                await self._redis.set(key, compressed)
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis SET error for key '%s': %s", key, e)
            raise

    async def _delete_raw(self, key: str) -> bool:
        """Delete a key from Redis."""
        if not self._redis:
            return False

        try:
            result = await self._redis.delete(key)
            return bool(result > 0)
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis DELETE error for key '%s': %s", key, e)
            return False

    async def _exists_raw(self, key: str) -> bool:
        """Check if a key exists in Redis."""
        if not self._redis:
            return False

        try:
            return bool(await self._redis.exists(key))
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis EXISTS error for key '%s': %s", key, e)
            return False

    async def _clear_raw(self) -> None:
        """Delete all keys with the configured prefix using SCAN."""
        if not self._redis:
            return

        prefix = f"{self._config.prefix}:"
        cursor = 0
        deleted_count = 0

        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor,
                match=f"{prefix}*",
                count=_SCAN_COUNT,
            )

            if keys:
                # Filter out tag keys (they'll be cleaned separately)
                data_keys = [
                    k
                    for k in keys
                    if _TAG_PREFIX
                    not in (k.decode("utf-8", errors="replace") if isinstance(k, bytes) else k)
                ]
                if data_keys:
                    await self._redis.delete(*data_keys)
                    deleted_count += len(data_keys)

            if cursor == 0:
                break

        logger.debug("Cleared %d keys from Redis", deleted_count)

    async def _keys_raw(self, pattern: str) -> list[str]:
        """List keys matching a pattern using SCAN (non-blocking)."""
        if not self._redis:
            return []

        keys: list[str] = []
        cursor = 0

        while True:
            cursor, batch = await self._redis.scan(
                cursor=cursor,
                match=pattern,
                count=_SCAN_COUNT,
            )

            for k in batch:
                key_str = k.decode("utf-8", errors="replace") if isinstance(k, bytes) else k
                # Skip tag keys
                if _TAG_PREFIX not in key_str:
                    keys.append(key_str)

            if cursor == 0:
                break

        return keys

    async def _size_raw(self) -> int:
        """Approximate entry count via SCAN."""
        if not self._redis:
            return 0

        prefix = f"{self._config.prefix}:"
        count = 0
        cursor = 0

        while True:
            cursor, batch = await self._redis.scan(
                cursor=cursor,
                match=f"{prefix}*",
                count=_SCAN_COUNT,
            )

            for k in batch:
                key_str = k.decode("utf-8", errors="replace") if isinstance(k, bytes) else k
                if _TAG_PREFIX not in key_str:
                    count += 1

            if cursor == 0:
                break

        return count

    async def _increment_raw(self, key: str, amount: int) -> int:
        """Atomic increment via Redis INCRBY."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        try:
            return int(await self._redis.incrby(key, amount))
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis INCRBY error for key '%s': %s", key, e)
            return 0

    # ──────────────────────────────────────────────────────────
    # Batch Operations (Pipeline)
    # ──────────────────────────────────────────────────────────

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """
        Get multiple values using Redis MGET (single round-trip).

        Args:
            keys: List of cache keys (without prefix).

        Returns:
            Dictionary of found key-value pairs.
        """
        if not self._redis or not keys:
            return {}

        full_keys = [self._prefix_key(k) for k in keys]

        try:
            raw_values = await self._redis.mget(full_keys)
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis MGET error: %s", e)
            return {}

        results: dict[str, Any] = {}
        for key, raw in zip(keys, raw_values, strict=True):
            if raw is not None:
                try:
                    decompressed = self._maybe_decompress(raw)
                    results[key] = self._serializer.deserialize(decompressed)
                    self._stats.record_hit()
                except Exception as e:
                    logger.debug("Deserialization error for key '%s': %s", key, e)
                    self._stats.record_miss()
            else:
                self._stats.record_miss()

        return results

    async def set_many(
        self,
        items: dict[str, Any],
        ttl: int | None = None,
    ) -> int:
        """
        Set multiple values using Redis pipeline (single round-trip).

        Args:
            items: Dictionary of key-value pairs.
            ttl: Time-to-live for all entries.

        Returns:
            Number of successfully stored entries.
        """
        if not self._redis or not items:
            return 0

        effective_ttl = ttl if ttl is not None else self._config.ttl
        pipe = self._redis.pipeline(transaction=False)
        count = 0

        for key, value in items.items():
            full_key = self._prefix_key(key)
            try:
                raw = self._serializer.serialize(value)
                compressed = self._maybe_compress(raw)

                if effective_ttl > 0:
                    pipe.setex(full_key, effective_ttl, compressed)
                else:
                    pipe.set(full_key, compressed)
                count += 1
            except Exception as e:
                logger.debug("Serialization error for key '%s': %s", key, e)

        try:
            await pipe.execute()
            self._stats.sets += count
            return count
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis pipeline SET error: %s", e)
            return 0

    async def delete_many(self, keys: list[str]) -> int:
        """
        Delete multiple keys in a single pipeline.

        Args:
            keys: List of cache keys.

        Returns:
            Number of keys deleted.
        """
        if not self._redis or not keys:
            return 0

        full_keys = [self._prefix_key(k) for k in keys]

        try:
            result = await self._redis.delete(*full_keys)
            self._stats.deletes += result
            return int(result)
        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis pipeline DELETE error: %s", e)
            return 0

    # ──────────────────────────────────────────────────────────
    # Tag-Based Invalidation
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

        Tags are stored as Redis SETs mapping tag → set of keys.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Time-to-live in seconds.
            tags: Tags for grouped deletion.

        Returns:
            True if stored successfully.
        """
        success = await self.set(key, value, ttl=ttl)

        if success and tags:
            full_key = self._prefix_key(key)
            await self._add_tags(full_key, tags)

        return success

    async def delete_by_tag(self, tag: str) -> int:
        """
        Delete all entries associated with a tag.

        Args:
            tag: Tag to invalidate.

        Returns:
            Number of entries deleted.
        """
        if not self._redis:
            return 0

        tag_redis_key = self._tag_key(tag)

        try:
            # Get all keys for this tag
            members = await self._redis.smembers(tag_redis_key)
            if not members:
                return 0

            # Delete all member keys + the tag set itself
            keys_to_delete = [*list(members), tag_redis_key.encode("utf-8")]
            result = await self._redis.delete(*keys_to_delete)

            # Subtract 1 for the tag key itself
            deleted = max(0, int(result) - 1)
            self._stats.deletes += deleted

            logger.debug("Deleted %d entries for tag '%s'", deleted, tag)
            return deleted

        except Exception as e:
            self._stats.record_error()
            logger.warning("Redis delete_by_tag error for '%s': %s", tag, e)
            return 0

    async def delete_by_tags(self, tags: list[str]) -> int:
        """
        Delete all entries matching ANY of the given tags.

        Args:
            tags: List of tags to invalidate.

        Returns:
            Total number of entries deleted.
        """
        total = 0
        for tag in tags:
            total += await self.delete_by_tag(tag)
        return total

    async def get_tags_for_key(self, key: str) -> list[str]:
        """
        Get all tags associated with a key.

        Note: This scans all tag sets, which can be slow with many tags.

        Args:
            key: Cache key.

        Returns:
            List of tags.
        """
        if not self._redis:
            return []

        full_key = self._prefix_key(key)
        tags: list[str] = []
        cursor = 0
        tag_pattern = f"{self._config.prefix}:{_TAG_PREFIX}*"

        while True:
            cursor, batch = await self._redis.scan(
                cursor=cursor,
                match=tag_pattern,
                count=_SCAN_COUNT,
            )

            for tag_key in batch:
                is_member = await self._redis.sismember(tag_key, full_key)
                if is_member:
                    tag_str = (
                        tag_key.decode("utf-8", errors="replace")
                        if isinstance(tag_key, bytes)
                        else tag_key
                    )
                    # Extract tag name
                    tag_name = tag_str.split(f"{_TAG_PREFIX}")[-1]
                    tags.append(tag_name)

            if cursor == 0:
                break

        return tags

    # ──────────────────────────────────────────────────────────
    # TTL Operations
    # ──────────────────────────────────────────────────────────

    async def get_ttl(self, key: str) -> int | None:
        """
        Get the remaining TTL for a key in seconds.

        Args:
            key: Cache key.

        Returns:
            Seconds remaining, -1 if no expiry, -2 if key not found.
        """
        if not self._redis:
            return None

        full_key = self._prefix_key(key)
        try:
            return int(await self._redis.ttl(full_key))
        except Exception as e:
            logger.warning("Redis TTL error for key '%s': %s", key, e)
            return None

    async def set_ttl(self, key: str, ttl: int) -> bool:
        """
        Update the TTL for an existing key.

        Args:
            key: Cache key.
            ttl: New TTL in seconds (0 = remove expiry / persist).

        Returns:
            True if the key existed and TTL was updated.
        """
        if not self._redis:
            return False

        full_key = self._prefix_key(key)
        try:
            if ttl > 0:
                result = await self._redis.expire(full_key, ttl)
            else:
                result = await self._redis.persist(full_key)
            return bool(result)
        except Exception as e:
            logger.warning("Redis EXPIRE error for key '%s': %s", key, e)
            return False

    async def get_entry(self, key: str) -> CacheEntry | None:
        """
        Get metadata for a cache entry.

        Args:
            key: Cache key.

        Returns:
            CacheEntry with metadata, or None if not found.
        """
        if not self._redis:
            return None

        full_key = self._prefix_key(key)

        try:
            pipe = self._redis.pipeline(transaction=False)
            pipe.ttl(full_key)
            pipe.memory_usage(full_key)
            pipe.type(full_key)
            ttl_val, memory, _key_type = await pipe.execute()
        except Exception:
            # MEMORY USAGE may not be available on all Redis versions
            try:
                ttl_val = await self._redis.ttl(full_key)
                memory = 0
            except Exception:
                return None

        if ttl_val == -2:
            return None  # Key does not exist

        expires_at = None
        if ttl_val > 0:
            expires_at = time.time() + ttl_val

        return CacheEntry(
            key=key,
            value=None,
            created_at=0.0,  # Redis doesn't store creation time
            expires_at=expires_at,
            access_count=0,
            last_accessed_at=0.0,
            size_bytes=memory or 0,
            tags=[],
        )

    # ──────────────────────────────────────────────────────────
    # Redis-Specific Operations
    # ──────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """
        Check Redis connectivity and server info.

        Returns:
            Dictionary with health status and server info.
        """
        if not self._redis:
            return {"healthy": False, "error": "Not connected"}

        try:
            start = time.perf_counter()
            pong = await self._redis.ping()
            latency_ms = (time.perf_counter() - start) * 1000

            info = await self._redis.info(section="server")

            return {
                "healthy": bool(pong),
                "latency_ms": round(latency_ms, 2),
                "redis_version": info.get("redis_version", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def get_redis_info(self) -> dict[str, Any]:
        """
        Get Redis server information.

        Returns:
            Dictionary with server stats.
        """
        if not self._redis:
            return {}

        try:
            info = await self._redis.info()
            return {
                "redis_version": info.get("redis_version"),
                "uptime_in_seconds": info.get("uptime_in_seconds"),
                "connected_clients": info.get("connected_clients"),
                "used_memory": info.get("used_memory"),
                "used_memory_human": info.get("used_memory_human"),
                "used_memory_peak_human": info.get("used_memory_peak_human"),
                "total_connections_received": info.get("total_connections_received"),
                "total_commands_processed": info.get("total_commands_processed"),
                "keyspace_hits": info.get("keyspace_hits"),
                "keyspace_misses": info.get("keyspace_misses"),
                "db_count": len([k for k in info if k.startswith("db")]),
            }
        except Exception as e:
            logger.warning("Redis INFO error: %s", e)
            return {"error": str(e)}

    async def flush_db(self) -> bool:
        """
        Flush the entire Redis database.

        WARNING: This deletes ALL keys in the current database,
        not just AgentCrawl keys. Use with extreme caution.

        Returns:
            True if flushed successfully.
        """
        if not self._redis:
            return False

        try:
            await self._redis.flushdb()
            logger.warning("Redis database flushed!")
            return True
        except Exception as e:
            logger.error("Redis FLUSHDB error: %s", e)
            return False

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    async def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics for monitoring."""
        health = await self.health_check()
        entry_count = await self._size_raw()

        return {
            "backend": "redis",
            "redis_url": self._config.redis_url.replace(
                self._config.redis_url.split("@")[-1] if "@" in self._config.redis_url else "",
                "***" if "@" in self._config.redis_url else self._config.redis_url.split("//")[-1],
            ),
            "compress": self._compress,
            "compress_threshold": self._compress_threshold,
            "max_connections": self._max_connections,
            "entry_count": entry_count,
            "health": health,
            "stats": self._stats.to_dict(),
        }

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"RedisCacheBackend(url={self._config.redis_url!r}, "
            f"compress={self._compress}, status={status})"
        )
