"""
AgentCrawl — Cache Manager
=============================

High-level cache manager that provides a unified interface for all
cache backends and adds crawl-specific caching operations with
automatic key generation, per-content-type TTL, and optional
multi-level (L1 + L2) caching.

Architecture:
    CacheManager
    ├── L1 Cache (Memory — fast, small)
    ├── L2 Cache (Redis / Disk — persistent, large)
    ├── KeyGenerator (URL → cache key)
    ├── TTL Policies (per content type)
    └── Statistics Aggregator

Usage:
    from agentcrawl.cache.manager import CacheManager

    # Simple (single backend)
    async with CacheManager(backend="memory", ttl=3600) as cache:
        await cache.set("key", "value")
        result = await cache.get("key")

    # Crawl-specific operations
    async with CacheManager(backend="redis") as cache:
        # Cache a scraped page
        await cache.cache_page(
            url="https://example.com",
            content={"markdown": "# Hello"},
            output_format="markdown",
        )

        # Retrieve cached page
        cached = await cache.get_page(
            url="https://example.com",
            output_format="markdown",
        )

        # Cache search results
        await cache.cache_search("python tutorial", results=[...])

    # Multi-level caching (L1 memory + L2 disk)
    async with CacheManager(
        backend="memory",
        l2_backend="disk",
        l2_config={"disk_path": ".agentcrawl/cache"},
    ) as cache:
        await cache.set("key", "value")  # Written to both L1 and L2
        result = await cache.get("key")  # Read from L1, fallback to L2
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agentcrawl.cache.base import (
    CacheBackend,
    CacheBackendType,
    CacheConfig,
    CacheKeyGenerator,
    CacheStats,
    NullCacheBackend,
)

logger = logging.getLogger("agentcrawl.cache.manager")


# ══════════════════════════════════════════════════════════════
# TTL Policies
# ══════════════════════════════════════════════════════════════

class TTLPolicy:
    """
    Defines default TTL values for different content types.

    TTLs can be overridden per-call or via configuration.
    """

    # Default TTLs in seconds
    PAGE_MARKDOWN: int = 3600        # 1 hour
    PAGE_JSON: int = 3600            # 1 hour
    PAGE_HTML: int = 1800            # 30 minutes
    PAGE_SCREENSHOT: int = 900       # 15 minutes
    SEARCH_RESULTS: int = 1800       # 30 minutes
    CRAWL_RESULTS: int = 7200        # 2 hours
    URL_MAP: int = 86400             # 24 hours
    EXTRACTED_DATA: int = 3600       # 1 hour
    METADATA: int = 7200             # 2 hours
    DEFAULT: int = 3600              # 1 hour

    @classmethod
    def for_output_format(cls, output_format: str) -> int:
        """Get TTL for a specific output format."""
        mapping = {
            "markdown": cls.PAGE_MARKDOWN,
            "json": cls.PAGE_JSON,
            "html": cls.PAGE_HTML,
            "screenshot": cls.PAGE_SCREENSHOT,
        }
        return mapping.get(output_format, cls.DEFAULT)

    @classmethod
    def for_content_type(cls, content_type: str) -> int:
        """Get TTL for a specific content type."""
        mapping = {
            "page": cls.PAGE_MARKDOWN,
            "search": cls.SEARCH_RESULTS,
            "crawl": cls.CRAWL_RESULTS,
            "map": cls.URL_MAP,
            "extract": cls.EXTRACTED_DATA,
            "metadata": cls.METADATA,
        }
        return mapping.get(content_type, cls.DEFAULT)


# ══════════════════════════════════════════════════════════════
# Cache Manager
# ══════════════════════════════════════════════════════════════

class CacheManager:
    """
    Unified cache manager with crawl-specific operations.

    Provides a high-level API on top of pluggable cache backends,
    with automatic key generation, TTL policies, optional multi-level
    caching, and aggregated statistics.

    Args:
        backend: Primary cache backend type ('memory', 'redis', 'disk', 'none').
        config: Full cache configuration (overrides individual params).
        ttl: Default TTL in seconds.
        prefix: Key prefix for namespacing.
        l2_backend: Optional secondary backend for multi-level caching.
        l2_config: Configuration dict for the L2 backend.
        enable_stats: Whether to track statistics.

    Example:
        >>> async with CacheManager(backend="memory", ttl=3600) as cache:
        ...     await cache.cache_page("https://example.com", {"markdown": "# Hi"})
        ...     result = await cache.get_page("https://example.com")
        ...     print(result)
    """

    def __init__(
        self,
        backend: str | CacheBackendType = "memory",
        config: CacheConfig | None = None,
        ttl: int = 3600,
        prefix: str = "agentcrawl",
        l2_backend: str | CacheBackendType | None = None,
        l2_config: dict[str, Any] | None = None,
        enable_stats: bool = True,
    ):
        # Build primary config
        if config:
            self._config = config
        else:
            self._config = CacheConfig(
                backend=backend,
                ttl=ttl,
                prefix=prefix,
                stats_enabled=enable_stats,
            )

        # L2 config
        self._l2_backend_type = l2_backend
        self._l2_config_dict = l2_config or {}

        # Backends (initialized on start)
        self._l1: CacheBackend | None = None
        self._l2: CacheBackend | None = None

        # Key generator
        self._key_gen = CacheKeyGenerator(
            prefix=self._config.prefix,
            algorithm=self._config.key_hash_algorithm,
        )

        # Aggregated stats
        self._stats = CacheStats()
        self._started = False

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def config(self) -> CacheConfig:
        """Primary cache configuration."""
        return self._config

    @property
    def is_started(self) -> bool:
        """Whether the cache manager has been initialized."""
        return self._started

    @property
    def l1(self) -> CacheBackend | None:
        """Primary (L1) cache backend."""
        return self._l1

    @property
    def l2(self) -> CacheBackend | None:
        """Secondary (L2) cache backend."""
        return self._l2

    @property
    def has_l2(self) -> bool:
        """Whether multi-level caching is enabled."""
        return self._l2 is not None

    @property
    def key_generator(self) -> CacheKeyGenerator:
        """Key generator instance."""
        return self._key_gen

    @property
    def default_ttl(self) -> int:
        """Default TTL in seconds."""
        return self._config.ttl

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize cache backends."""
        if self._started:
            return

        # Create L1 backend
        self._l1 = self._create_backend(self._config)
        await self._l1.start()

        # Create L2 backend if configured
        if self._l2_backend_type:
            l2_config = CacheConfig(
                backend=self._l2_backend_type,
                ttl=self._config.ttl * 2,  # L2 lives longer
                prefix=self._config.prefix,
                stats_enabled=self._config.stats_enabled,
                **self._l2_config_dict,
            )
            self._l2 = self._create_backend(l2_config)
            await self._l2.start()
            logger.info(
                "Multi-level cache started (L1=%s, L2=%s)",
                self._config.backend,
                self._l2_backend_type,
            )
        else:
            logger.info(
                "Cache started (backend=%s, ttl=%ds, prefix=%s)",
                self._config.backend,
                self._config.ttl,
                self._config.prefix,
            )

        self._started = True

    async def stop(self) -> None:
        """Shut down all cache backends."""
        if not self._started:
            return

        if self._l1:
            await self._l1.stop()
            self._l1 = None

        if self._l2:
            await self._l2.stop()
            self._l2 = None

        self._started = False
        logger.info("Cache manager stopped")

    async def __aenter__(self) -> CacheManager:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ──────────────────────────────────────────────────────────
    # Backend Factory
    # ──────────────────────────────────────────────────────────

    def _create_backend(self, config: CacheConfig) -> CacheBackend:
        """
        Create a cache backend instance from configuration.

        Args:
            config: Cache configuration.

        Returns:
            CacheBackend instance.

        Raises:
            ValueError: If the backend type is unknown.
        """
        backend_type = config.backend
        if isinstance(backend_type, str):
            backend_type = CacheBackendType(backend_type)

        if backend_type == CacheBackendType.NONE:
            return NullCacheBackend(config)

        if backend_type == CacheBackendType.MEMORY:
            from agentcrawl.cache.memory import MemoryCacheBackend
            return MemoryCacheBackend(config)

        if backend_type == CacheBackendType.REDIS:
            from agentcrawl.cache.redis import RedisCacheBackend
            return RedisCacheBackend(config)

        if backend_type == CacheBackendType.DISK:
            from agentcrawl.cache.disk import DiskCacheBackend
            return DiskCacheBackend(config)

        raise ValueError(f"Unknown cache backend: {backend_type}")

    # ──────────────────────────────────────────────────────────
    # Generic Operations (with multi-level support)
    # ──────────────────────────────────────────────────────────

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get a value from the cache.

        Checks L1 first, then L2. On L2 hit, the value is
        promoted back to L1.

        Args:
            key: Cache key.
            default: Value to return on miss.

        Returns:
            Cached value, or default.
        """
        self._ensure_started()
        start = time.perf_counter()

        # L1 lookup
        if self._l1:
            value = await self._l1.get(key)
            if value is not None:
                duration_ms = (time.perf_counter() - start) * 1000
                self._stats.record_hit(duration_ms)
                return value

        # L2 lookup
        if self._l2:
            value = await self._l2.get(key)
            if value is not None:
                duration_ms = (time.perf_counter() - start) * 1000
                self._stats.record_hit(duration_ms)
                # Promote to L1
                if self._l1:
                    await self._l1.set(key, value, ttl=self._config.ttl)
                return value

        duration_ms = (time.perf_counter() - start) * 1000
        self._stats.record_miss(duration_ms)
        return default

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """
        Set a value in the cache (writes to both L1 and L2).

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Time-to-live in seconds.
            tags: Optional tags for grouped invalidation.

        Returns:
            True if stored successfully.
        """
        self._ensure_started()
        effective_ttl = ttl if ttl is not None else self._config.ttl
        start = time.perf_counter()

        success = False

        # Write to L1
        if self._l1:
            success = await self._l1.set(key, value, ttl=effective_ttl, tags=tags)

        # Write to L2
        if self._l2:
            l2_ttl = effective_ttl * 2 if effective_ttl > 0 else 0
            l2_success = await self._l2.set(key, value, ttl=l2_ttl, tags=tags)
            success = success or l2_success

        if success:
            duration_ms = (time.perf_counter() - start) * 1000
            self._stats.record_set(duration_ms)

        return success

    async def delete(self, key: str) -> bool:
        """Delete a key from all cache levels."""
        self._ensure_started()

        deleted = False
        if self._l1:
            deleted = await self._l1.delete(key) or deleted
        if self._l2:
            deleted = await self._l2.delete(key) or deleted

        if deleted:
            self._stats.record_delete()
        return deleted

    async def exists(self, key: str) -> bool:
        """Check if a key exists in any cache level."""
        self._ensure_started()

        if self._l1 and await self._l1.exists(key):
            return True
        if self._l2 and await self._l2.exists(key):
            return True
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
        """
        value = await self.get(key)
        if value is not None:
            return value

        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        elif callable(factory):
            value = factory()
        else:
            value = factory

        await self.set(key, value, ttl=ttl, tags=tags)
        return value

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Get multiple values at once."""
        self._ensure_started()
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
        """Set multiple values at once."""
        self._ensure_started()
        count = 0
        for key, value in items.items():
            if await self.set(key, value, ttl=ttl):
                count += 1
        return count

    async def delete_many(self, keys: list[str]) -> int:
        """Delete multiple keys at once."""
        self._ensure_started()
        count = 0
        for key in keys:
            if await self.delete(key):
                count += 1
        return count

    async def clear(self) -> bool:
        """Clear all cache levels."""
        self._ensure_started()

        success = True
        if self._l1:
            success = await self._l1.clear() and success
        if self._l2:
            success = await self._l2.clear() and success

        return success

    async def keys(self, pattern: str = "*") -> list[str]:
        """List keys matching a pattern (from L1, merged with L2)."""
        self._ensure_started()

        keys_set: set[str] = set()

        if self._l1:
            l1_keys = await self._l1.keys(pattern)
            keys_set.update(l1_keys)

        if self._l2:
            l2_keys = await self._l2.keys(pattern)
            keys_set.update(l2_keys)

        return sorted(keys_set)

    # ──────────────────────────────────────────────────────────
    # Crawl-Specific Operations
    # ──────────────────────────────────────────────────────────

    async def cache_page(
        self,
        url: str,
        content: Any,
        output_format: str = "markdown",
        extra_params: dict[str, Any] | None = None,
        ttl: int | None = None,
    ) -> bool:
        """
        Cache a scraped page result.

        Args:
            url: Page URL.
            content: Scraped content (markdown string, JSON dict, etc.).
            output_format: Output format used.
            extra_params: Additional parameters that affect the result.
            ttl: Override TTL (default: from TTLPolicy).

        Returns:
            True if cached successfully.
        """
        key = self._key_gen.from_url(url, output_format, extra_params)
        effective_ttl = ttl or TTLPolicy.for_output_format(output_format)

        return await self.set(
            key,
            content,
            ttl=effective_ttl,
            tags=["page", f"format:{output_format}"],
        )

    async def get_page(
        self,
        url: str,
        output_format: str = "markdown",
        extra_params: dict[str, Any] | None = None,
    ) -> Any | None:
        """
        Get a cached page result.

        Args:
            url: Page URL.
            output_format: Output format used.
            extra_params: Additional parameters that affect the result.

        Returns:
            Cached content, or None if not found.
        """
        key = self._key_gen.from_url(url, output_format, extra_params)
        return await self.get(key)

    async def has_page(
        self,
        url: str,
        output_format: str = "markdown",
        extra_params: dict[str, Any] | None = None,
    ) -> bool:
        """Check if a page result is cached."""
        key = self._key_gen.from_url(url, output_format, extra_params)
        return await self.exists(key)

    async def delete_page(
        self,
        url: str,
        output_format: str = "markdown",
        extra_params: dict[str, Any] | None = None,
    ) -> bool:
        """Delete a cached page result."""
        key = self._key_gen.from_url(url, output_format, extra_params)
        return await self.delete(key)

    async def cache_search(
        self,
        query: str,
        results: Any,
        engine: str = "google",
        max_results: int = 5,
        ttl: int | None = None,
    ) -> bool:
        """
        Cache search results.

        Args:
            query: Search query.
            results: Search results data.
            engine: Search engine used.
            max_results: Max results parameter.
            ttl: Override TTL.

        Returns:
            True if cached successfully.
        """
        key = self._key_gen.from_search(query, engine, max_results)
        effective_ttl = ttl or TTLPolicy.SEARCH_RESULTS

        return await self.set(
            key,
            results,
            ttl=effective_ttl,
            tags=["search", f"engine:{engine}"],
        )

    async def get_search(
        self,
        query: str,
        engine: str = "google",
        max_results: int = 5,
    ) -> Any | None:
        """Get cached search results."""
        key = self._key_gen.from_search(query, engine, max_results)
        return await self.get(key)

    async def cache_crawl(
        self,
        url: str,
        results: Any,
        strategy: str = "bfs",
        max_depth: int = 3,
        ttl: int | None = None,
    ) -> bool:
        """
        Cache crawl results.

        Args:
            url: Starting URL.
            results: Crawl results data.
            strategy: Crawling strategy used.
            max_depth: Max depth parameter.
            ttl: Override TTL.

        Returns:
            True if cached successfully.
        """
        key = self._key_gen.from_crawl(url, strategy, max_depth)
        effective_ttl = ttl or TTLPolicy.CRAWL_RESULTS

        return await self.set(
            key,
            results,
            ttl=effective_ttl,
            tags=["crawl", f"strategy:{strategy}"],
        )

    async def get_crawl(
        self,
        url: str,
        strategy: str = "bfs",
        max_depth: int = 3,
    ) -> Any | None:
        """Get cached crawl results."""
        key = self._key_gen.from_crawl(url, strategy, max_depth)
        return await self.get(key)

    async def cache_map(
        self,
        url: str,
        urls: Any,
        ttl: int | None = None,
    ) -> bool:
        """
        Cache URL map results.

        Args:
            url: Website URL.
            urls: List of discovered URLs.
            ttl: Override TTL.

        Returns:
            True if cached successfully.
        """
        key = self._key_gen.from_map(url)
        effective_ttl = ttl or TTLPolicy.URL_MAP

        return await self.set(
            key,
            urls,
            ttl=effective_ttl,
            tags=["map"],
        )

    async def get_map(self, url: str) -> Any | None:
        """Get cached URL map results."""
        key = self._key_gen.from_map(url)
        return await self.get(key)

    async def cache_extract(
        self,
        url: str,
        data: Any,
        schema_hash: str = "",
        method: str = "llm",
        ttl: int | None = None,
    ) -> bool:
        """
        Cache extracted structured data.

        Args:
            url: Source URL.
            data: Extracted data.
            schema_hash: Hash of the extraction schema.
            method: Extraction method used.
            ttl: Override TTL.

        Returns:
            True if cached successfully.
        """
        key = self._key_gen.custom(
            "extract",
            f"{url}|{schema_hash}|{method}",
        )
        effective_ttl = ttl or TTLPolicy.EXTRACTED_DATA

        return await self.set(
            key,
            data,
            ttl=effective_ttl,
            tags=["extract", f"method:{method}"],
        )

    async def get_extract(
        self,
        url: str,
        schema_hash: str = "",
        method: str = "llm",
    ) -> Any | None:
        """Get cached extracted data."""
        key = self._key_gen.custom(
            "extract",
            f"{url}|{schema_hash}|{method}",
        )
        return await self.get(key)

    # ──────────────────────────────────────────────────────────
    # Namespace Operations
    # ──────────────────────────────────────────────────────────

    async def clear_pages(self) -> int:
        """Clear all cached page results."""
        return await self._clear_namespace("page")

    async def clear_searches(self) -> int:
        """Clear all cached search results."""
        return await self._clear_namespace("search")

    async def clear_crawls(self) -> int:
        """Clear all cached crawl results."""
        return await self._clear_namespace("crawl")

    async def clear_maps(self) -> int:
        """Clear all cached URL maps."""
        return await self._clear_namespace("map")

    async def clear_extracts(self) -> int:
        """Clear all cached extracted data."""
        return await self._clear_namespace("extract")

    async def _clear_namespace(self, namespace: str) -> int:
        """Clear all entries in a namespace across all levels."""
        pattern = self._key_gen.make_pattern(namespace)
        keys = await self.keys(pattern)
        return await self.delete_many(keys)

    # ──────────────────────────────────────────────────────────
    # Statistics
    # ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """
        Get aggregated cache statistics.

        Returns:
            Dictionary with combined stats from all levels.
        """
        result = self._stats.to_dict()

        if self._l1:
            result["l1"] = self._l1.get_stats()
        if self._l2:
            result["l2"] = self._l2.get_stats()

        result["multi_level"] = self.has_l2
        result["backend"] = (
            self._config.backend.value
            if isinstance(self._config.backend, CacheBackendType)
            else self._config.backend
        )

        return result

    def reset_stats(self) -> None:
        """Reset statistics on all levels."""
        self._stats.reset()
        if self._l1:
            self._l1.reset_stats()
        if self._l2:
            self._l2.reset_stats()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    async def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics from all cache levels."""
        diag: dict[str, Any] = {
            "started": self._started,
            "config": self._config.to_dict(),
            "multi_level": self.has_l2,
            "stats": self.get_stats(),
        }

        if self._l1 and hasattr(self._l1, "get_diagnostics"):
            diag["l1"] = await self._l1.get_diagnostics()  # type: ignore[attr-defined]

        if self._l2 and hasattr(self._l2, "get_diagnostics"):
            diag["l2"] = await self._l2.get_diagnostics()  # type: ignore[attr-defined]

        return diag

    # ──────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────

    def _ensure_started(self) -> None:
        """Raise if the manager hasn't been started."""
        if not self._started:
            raise RuntimeError(
                "CacheManager not started. Call start() or use 'async with' first."
            )

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        l2_str = f", l2={self._l2_backend_type}" if self._l2_backend_type else ""
        return (
            f"CacheManager(backend={self._config.backend}{l2_str}, "
            f"prefix={self._config.prefix!r}, status={status})"
        )


# ══════════════════════════════════════════════════════════════
# Factory Function
# ══════════════════════════════════════════════════════════════

def create_cache_manager(
    backend: str = "memory",
    ttl: int = 3600,
    prefix: str = "agentcrawl",
    l2_backend: str | None = None,
    l2_config: dict[str, Any] | None = None,
    **kwargs: Any,
) -> CacheManager:
    """
    Factory function to create a CacheManager.

    Args:
        backend: Primary backend type ('memory', 'redis', 'disk', 'none').
        ttl: Default TTL in seconds.
        prefix: Key prefix.
        l2_backend: Optional L2 backend type.
        l2_config: L2 backend configuration.
        **kwargs: Additional arguments passed to CacheManager.

    Returns:
        CacheManager instance (not yet started).

    Example:
        >>> cache = create_cache_manager("redis", ttl=1800)
        >>> await cache.start()
        >>> # ... use cache ...
        >>> await cache.stop()

        >>> # Or with context manager
        >>> async with create_cache_manager("memory") as cache:
        ...     await cache.set("key", "value")
    """
    return CacheManager(
        backend=backend,
        ttl=ttl,
        prefix=prefix,
        l2_backend=l2_backend,
        l2_config=l2_config,
        **kwargs,
    )


def create_cache_from_env(prefix: str = "AGENTCRAWL") -> CacheManager:
    """
    Create a CacheManager from environment variables.

    Reads:
        AGENTCRAWL_CACHE_BACKEND
        AGENTCRAWL_CACHE_TTL
        AGENTCRAWL_CACHE_PREFIX
        AGENTCRAWL_REDIS_URL
        AGENTCRAWL_CACHE_DISK_PATH
        AGENTCRAWL_CACHE_MAX_SIZE

    Args:
        prefix: Environment variable prefix.

    Returns:
        CacheManager instance (not yet started).
    """
    config = CacheConfig.from_env(prefix)
    return CacheManager(config=config)
