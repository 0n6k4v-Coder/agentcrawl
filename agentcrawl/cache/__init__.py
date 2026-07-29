"""
AgentCrawl — Cache Layer
==========================

Pluggable caching with support for Memory, Redis, and Disk backends.
Provides a unified async interface with TTL, LRU eviction, tag-based
invalidation, and crawl-specific caching operations.

Backends:
    memory  — In-process LRU cache (fastest, no persistence)
    redis   — Redis-backed cache (distributed, persistent)
    disk    — File-system cache (persistent, no external deps)
    none    — No-op cache (disables caching)

Quick Start:
    # Simple key-value caching
    from agentcrawl.cache import CacheManager

    async with CacheManager(backend="memory", ttl=3600) as cache:
        await cache.set("key", {"data": "value"})
        result = await cache.get("key")

    # Crawl-specific caching
    async with CacheManager(backend="redis") as cache:
        await cache.cache_page("https://example.com", content={"markdown": "# Hi"})
        cached = await cache.get_page("https://example.com")

    # Multi-level caching (L1 memory + L2 disk)
    async with CacheManager(
        backend="memory",
        l2_backend="disk",
        l2_config={"disk_path": ".agentcrawl/cache"},
    ) as cache:
        await cache.set("key", "value")

    # Direct backend usage
    from agentcrawl.cache import MemoryCacheBackend, CacheConfig

    config = CacheConfig(backend="memory", ttl=300, max_size=5000)
    async with MemoryCacheBackend(config) as cache:
        await cache.set("key", "value")

    # Factory functions
    from agentcrawl.cache import create_cache_manager, create_cache_from_env

    cache = create_cache_manager("redis", ttl=1800)
    cache = create_cache_from_env()  # reads AGENTCRAWL_CACHE_* env vars
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("agentcrawl.cache")

# ──────────────────────────────────────────────────────────────
# Base (always available)
# ──────────────────────────────────────────────────────────────

from agentcrawl.cache.base import (
    CacheBackend,
    CacheBackendType,
    CacheConfig,
    CacheEntry,
    CacheKeyGenerator,
    CacheSerializer,
    CacheStats,
    NullCacheBackend,
    SerializationFormat,
)

# ──────────────────────────────────────────────────────────────
# Disk backend (always available)
# ──────────────────────────────────────────────────────────────
from agentcrawl.cache.disk import DiskCacheBackend

# ──────────────────────────────────────────────────────────────
# Memory backend (always available)
# ──────────────────────────────────────────────────────────────
from agentcrawl.cache.memory import MemoryCacheBackend

# ──────────────────────────────────────────────────────────────
# Redis backend (conditional — requires redis package)
# ──────────────────────────────────────────────────────────────

try:
    from agentcrawl.cache.redis import RedisCacheBackend
    _HAS_REDIS = True
except ImportError:
    RedisCacheBackend = None  # type: ignore[assignment,misc]
    _HAS_REDIS = False

# ──────────────────────────────────────────────────────────────
# Manager (always available)
# ──────────────────────────────────────────────────────────────

from agentcrawl.cache.manager import (
    CacheManager,
    TTLPolicy,
    create_cache_from_env,
    create_cache_manager,
)

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Base
    "CacheBackend",
    "CacheBackendType",
    "CacheConfig",
    "CacheEntry",
    "CacheKeyGenerator",
    "CacheSerializer",
    "CacheStats",
    "NullCacheBackend",
    "SerializationFormat",
    # Backends
    "MemoryCacheBackend",
    "DiskCacheBackend",
    "RedisCacheBackend",
    # Manager
    "CacheManager",
    "TTLPolicy",
    "create_cache_manager",
    "create_cache_from_env",
    # Feature detection
    "has_redis",
    "get_available_backends",
]


# ──────────────────────────────────────────────────────────────
# Feature Detection Helpers
# ──────────────────────────────────────────────────────────────

def has_redis() -> bool:
    """Check if the redis package is installed and RedisCacheBackend is available."""
    return _HAS_REDIS


def get_available_backends() -> list[str]:
    """
    Get a list of available cache backend types.

    Returns:
        List of backend names that can be used with CacheManager.

    Example:
        >>> backends = get_available_backends()
        >>> print(backends)
        ['memory', 'disk', 'redis', 'none']
    """
    backends = ["memory", "disk"]
    if _HAS_REDIS:
        backends.append("redis")
    backends.append("none")
    return backends
