"""
AgentCrawl — Disk Cache Backend
=================================

File-system-based cache backend with sharded directory layout,
TTL expiry, LRU eviction, optional compression, and atomic writes.

Each cache entry is stored as two files:
    <shard_dir>/<hash>.dat   — serialized value (optionally compressed)
    <shard_dir>/<hash>.meta  — JSON metadata (TTL, timestamps, tags)

Directory Structure:
    .agentcrawl/cache/
    ├── a1/
    │   ├── a1b2c3d4e5f6...dat
    │   └── a1b2c3d4e5f6...meta
    ├── f9/
    │   ├── f9e8d7c6b5a4...dat
    │   └── f9e8d7c6b5a4...meta
    └── _index.json          — optional key registry

Usage:
    from agentcrawl.cache.disk import DiskCacheBackend
    from agentcrawl.cache.base import CacheConfig

    config = CacheConfig(
        backend="disk",
        disk_path=".agentcrawl/cache",
        ttl=3600,
        max_size=5000,
        compress=True,
    )

    async with DiskCacheBackend(config) as cache:
        await cache.set("page:abc", {"markdown": "# Hello"})
        result = await cache.get("page:abc")
        print(result)
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import os
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any

from agentcrawl.cache.base import (
    CacheBackend,
    CacheConfig,
    CacheEntry,
)

logger = logging.getLogger("agentcrawl.cache.disk")


# ══════════════════════════════════════════════════════════════
# Metadata Model
# ══════════════════════════════════════════════════════════════

class _EntryMeta:
    """
    Internal metadata for a disk cache entry.

    Stored as a .meta JSON file alongside the .dat value file.
    """

    __slots__ = (
        "access_count",
        "compressed",
        "created_at",
        "expires_at",
        "key",
        "last_accessed_at",
        "size_bytes",
        "tags",
    )

    def __init__(
        self,
        key: str,
        created_at: float | None = None,
        expires_at: float | None = None,
        access_count: int = 0,
        last_accessed_at: float | None = None,
        size_bytes: int = 0,
        tags: list[str] | None = None,
        compressed: bool = False,
    ):
        self.key = key
        self.created_at = created_at or time.time()
        self.expires_at = expires_at
        self.access_count = access_count
        self.last_accessed_at = last_accessed_at or time.time()
        self.size_bytes = size_bytes
        self.tags = tags or []
        self.compressed = compressed

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "size_bytes": self.size_bytes,
            "tags": self.tags,
            "compressed": self.compressed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _EntryMeta:
        return cls(
            key=data.get("key", ""),
            created_at=data.get("created_at"),
            expires_at=data.get("expires_at"),
            access_count=data.get("access_count", 0),
            last_accessed_at=data.get("last_accessed_at"),
            size_bytes=data.get("size_bytes", 0),
            tags=data.get("tags", []),
            compressed=data.get("compressed", False),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> _EntryMeta:
        return cls.from_dict(json.loads(raw))


# ══════════════════════════════════════════════════════════════
# Disk Cache Backend
# ══════════════════════════════════════════════════════════════

class DiskCacheBackend(CacheBackend):
    """
    File-system-based cache backend.

    Stores each entry as a pair of files (.dat + .meta) in a
    sharded directory structure to avoid filesystem performance
    degradation with large numbers of files.

    Features:
        - Sharded directories (256 shards based on key hash prefix)
        - Atomic writes (write to temp file, then rename)
        - Optional zlib compression for values
        - TTL-based expiry (checked on read)
        - LRU eviction when max_size is exceeded
        - Async file I/O via thread pool executor

    Args:
        config: Cache configuration.

    Example:
        >>> config = CacheConfig(backend="disk", disk_path="/tmp/cache", compress=True)
        >>> async with DiskCacheBackend(config) as cache:
        ...     await cache.set("key", {"data": "value"}, ttl=300)
        ...     result = await cache.get("key")
    """

    # Number of shard directories (hex 00-ff)
    _SHARD_COUNT = 256

    def __init__(self, config: CacheConfig | None = None):
        super().__init__(config)
        self._base_path = Path(self._config.disk_path)
        self._compress = self._config.compress
        self._max_size = self._config.max_size
        self._lock = asyncio.Lock()
        self._executor: asyncio.AbstractEventLoop | None = None

        # In-memory index for fast key lookup (lazy-loaded)
        self._index: dict[str, _EntryMeta] | None = None
        self._index_dirty = False

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def _start_impl(self) -> None:
        """Create cache directory structure."""
        await self._run_sync(self._create_directories)
        logger.info(
            "Disk cache initialized at %s (compress=%s, max_size=%d)",
            self._base_path,
            self._compress,
            self._max_size,
        )

    async def _stop_impl(self) -> None:
        """Persist index and clean up."""
        if self._index_dirty and self._index is not None:
            await self._save_index()
        self._index = None

    def _create_directories(self) -> None:
        """Create the base and shard directories."""
        self._base_path.mkdir(parents=True, exist_ok=True)
        for i in range(self._SHARD_COUNT):
            shard_dir = self._base_path / f"{i:02x}"
            shard_dir.mkdir(exist_ok=True)

    # ──────────────────────────────────────────────────────────
    # Path Helpers
    # ──────────────────────────────────────────────────────────

    def _key_to_hash(self, key: str) -> str:
        """Hash a key to a fixed-length hex string."""
        h = hashlib.sha256(key.encode("utf-8"))
        return h.hexdigest()

    def _key_to_shard(self, key_hash: str) -> Path:
        """Determine the shard directory for a key hash."""
        shard_id = int(key_hash[:2], 16)
        return self._base_path / f"{shard_id:02x}"

    def _key_to_paths(self, key: str) -> tuple[Path, Path]:
        """
        Get the .dat and .meta file paths for a key.

        Returns:
            Tuple of (data_path, meta_path).
        """
        key_hash = self._key_to_hash(key)
        shard_dir = self._key_to_shard(key_hash)
        data_path = shard_dir / f"{key_hash}.dat"
        meta_path = shard_dir / f"{key_hash}.meta"
        return data_path, meta_path

    # ──────────────────────────────────────────────────────────
    # Sync I/O Helpers (run in thread pool)
    # ──────────────────────────────────────────────────────────

    async def _run_sync(self, fn: Any, *args: Any) -> Any:
        """Run a synchronous function in the default thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    def _read_file_sync(self, path: Path) -> bytes | None:
        """Read a file synchronously."""
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.debug("Read error for %s: %s", path, e)
            return None

    def _write_file_sync(self, path: Path, data: bytes) -> None:
        """Write a file atomically (write to temp, then rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".tmp_",
            suffix=".dat",
        )
        try:
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd)
            os.replace(tmp_path, str(path))
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _delete_file_sync(self, path: Path) -> bool:
        """Delete a file synchronously."""
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as e:
            logger.debug("Delete error for %s: %s", path, e)
            return False

    def _file_exists_sync(self, path: Path) -> bool:
        """Check if a file exists."""
        return path.exists()

    def _list_files_sync(self, directory: Path, suffix: str) -> list[Path]:
        """List files with a specific suffix in a directory."""
        try:
            return list(directory.glob(f"*{suffix}"))
        except OSError:
            return []

    # ──────────────────────────────────────────────────────────
    # Compression
    # ──────────────────────────────────────────────────────────

    def _compress_data(self, data: bytes) -> bytes:
        """Compress data with zlib."""
        if self._compress:
            return zlib.compress(data, level=6)
        return data

    def _decompress_data(self, data: bytes, compressed: bool) -> bytes:
        """Decompress data if it was compressed."""
        if compressed:
            try:
                return zlib.decompress(data)
            except zlib.error:
                logger.warning("Failed to decompress data, returning raw")
                return data
        return data

    # ──────────────────────────────────────────────────────────
    # Index Management
    # ──────────────────────────────────────────────────────────

    async def _ensure_index(self) -> dict[str, _EntryMeta]:
        """Load or return the in-memory index."""
        if self._index is not None:
            return self._index

        self._index = await self._run_sync(self._scan_all_meta)
        logger.info("Disk cache index loaded: %d entries", len(self._index))
        return self._index

    def _scan_all_meta(self) -> dict[str, _EntryMeta]:
        """Scan all .meta files to build the index."""
        index: dict[str, _EntryMeta] = {}

        if not self._base_path.exists():
            return index

        for shard_dir in self._base_path.iterdir():
            if not shard_dir.is_dir():
                continue
            for meta_file in shard_dir.glob("*.meta"):
                try:
                    raw = meta_file.read_text(encoding="utf-8")
                    meta = _EntryMeta.from_json(raw)
                    # Skip expired entries
                    if not meta.is_expired:
                        index[meta.key] = meta
                except Exception as e:
                    logger.debug("Skipping corrupt meta file %s: %s", meta_file, e)

        return index

    async def _save_index(self) -> None:
        """Persist the index to disk (for fast startup)."""
        if self._index is None:
            return

        index_path = self._base_path / "_index.json"
        data = {
            key: meta.to_dict()
            for key, meta in self._index.items()
        }

        try:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            await self._run_sync(self._write_file_sync, index_path, raw)
            self._index_dirty = False
        except Exception as e:
            logger.warning("Failed to save index: %s", e)

    async def _update_index(self, meta: _EntryMeta) -> None:
        """Add or update an entry in the index."""
        index = await self._ensure_index()
        index[meta.key] = meta
        self._index_dirty = True

    async def _remove_from_index(self, key: str) -> None:
        """Remove an entry from the index."""
        if self._index is not None:
            self._index.pop(key, None)
            self._index_dirty = True

    # ──────────────────────────────────────────────────────────
    # LRU Eviction
    # ──────────────────────────────────────────────────────────

    async def _evict_if_needed(self) -> None:
        """Evict least-recently-used entries if over max_size."""
        if self._max_size <= 0:
            return

        index = await self._ensure_index()

        if len(index) <= self._max_size:
            return

        # Sort by last_accessed_at (oldest first)
        entries = sorted(index.values(), key=lambda m: m.last_accessed_at)
        evict_count = len(index) - self._max_size

        logger.info(
            "Evicting %d entries (current=%d, max=%d)",
            evict_count,
            len(index),
            self._max_size,
        )

        for meta in entries[:evict_count]:
            await self._delete_entry(meta.key)
            self._stats.record_eviction()

    async def _delete_entry(self, key: str) -> bool:
        """Delete both .dat and .meta files for a key."""
        data_path, meta_path = self._key_to_paths(key)

        deleted = False
        deleted |= await self._run_sync(self._delete_file_sync, data_path)
        deleted |= await self._run_sync(self._delete_file_sync, meta_path)

        await self._remove_from_index(key)
        return deleted

    # ──────────────────────────────────────────────────────────
    # CacheBackend Implementation
    # ──────────────────────────────────────────────────────────

    async def _get_raw(self, key: str) -> bytes | None:
        """Read raw bytes for a key from disk."""
        data_path, meta_path = self._key_to_paths(key)

        # Read metadata
        meta_raw = await self._run_sync(self._read_file_sync, meta_path)
        if meta_raw is None:
            return None

        try:
            meta = _EntryMeta.from_json(meta_raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Corrupt meta — clean up
            await self._delete_entry(key)
            return None

        # Check expiry
        if meta.is_expired:
            await self._delete_entry(key)
            return None

        # Read data
        data = await self._run_sync(self._read_file_sync, data_path)
        if data is None:
            # Data file missing but meta exists — clean up
            await self._delete_entry(key)
            return None

        # Decompress
        data = self._decompress_data(data, meta.compressed)

        # Update access metadata
        meta.access_count += 1
        meta.last_accessed_at = time.time()
        await self._run_sync(
            self._write_file_sync,
            meta_path,
            meta.to_json().encode("utf-8"),
        )
        await self._update_index(meta)

        return data

    async def _set_raw(self, key: str, value: bytes, ttl: int) -> None:
        """Write raw bytes for a key to disk."""
        data_path, meta_path = self._key_to_paths(key)

        # Compress if enabled
        compressed = self._compress
        stored_data = self._compress_data(value)

        # Calculate expiry
        now = time.time()
        expires_at = (now + ttl) if ttl > 0 else None

        # Build metadata
        meta = _EntryMeta(
            key=key,
            created_at=now,
            expires_at=expires_at,
            access_count=0,
            last_accessed_at=now,
            size_bytes=len(value),
            compressed=compressed,
        )

        # Write data file (atomic)
        await self._run_sync(self._write_file_sync, data_path, stored_data)

        # Write meta file (atomic)
        await self._run_sync(
            self._write_file_sync,
            meta_path,
            meta.to_json().encode("utf-8"),
        )

        # Update index
        await self._update_index(meta)

        # Evict if over capacity
        await self._evict_if_needed()

    async def _delete_raw(self, key: str) -> bool:
        """Delete a key from disk."""
        return await self._delete_entry(key)

    async def _exists_raw(self, key: str) -> bool:
        """Check if a key exists on disk (and is not expired)."""
        data_path, meta_path = self._key_to_paths(key)

        # Quick check: does the data file exist?
        exists = await self._run_sync(self._file_exists_sync, data_path)
        if not exists:
            return False

        # Check expiry via meta
        meta_raw = await self._run_sync(self._read_file_sync, meta_path)
        if meta_raw is None:
            return False

        try:
            meta = _EntryMeta.from_json(meta_raw.decode("utf-8"))
            if meta.is_expired:
                # Clean up expired entry
                await self._delete_entry(key)
                return False
            return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    async def _clear_raw(self) -> None:
        """Clear all entries with the configured prefix."""
        index = await self._ensure_index()
        prefix = f"{self._config.prefix}:"

        keys_to_delete = [
            key for key in index
            if key.startswith(prefix)
        ]

        for key in keys_to_delete:
            await self._delete_entry(key)

        logger.info("Cleared %d entries from disk cache", len(keys_to_delete))

    async def _keys_raw(self, pattern: str) -> list[str]:
        """List all keys matching a glob pattern."""
        index = await self._ensure_index()

        # Clean expired entries from index
        expired = [k for k, m in index.items() if m.is_expired]
        for k in expired:
            await self._delete_entry(k)

        # Match pattern
        if pattern == "*":
            return list(index.keys())

        return [
            key for key in index
            if fnmatch.fnmatch(key, pattern)
        ]

    async def _size_raw(self) -> int:
        """Get the number of entries in the cache."""
        index = await self._ensure_index()
        # Exclude expired
        return sum(1 for m in index.values() if not m.is_expired)

    async def _increment_raw(self, key: str, amount: int) -> int:
        """Increment a numeric value on disk."""
        data_path, meta_path = self._key_to_paths(key)

        # Read current value
        raw = await self._get_raw(key)
        if raw is None:
            current = 0
        else:
            try:
                current = int(self._serializer.deserialize(raw))
            except (ValueError, TypeError):
                current = 0

        new_value = current + amount
        new_raw = self._serializer.serialize(new_value)
        await self._set_raw(key, new_raw, 0)
        return new_value

    # ──────────────────────────────────────────────────────────
    # Disk-Specific Operations
    # ──────────────────────────────────────────────────────────

    async def get_entry_meta(self, key: str) -> CacheEntry | None:
        """
        Get full metadata for a cache entry.

        Args:
            key: Cache key.

        Returns:
            CacheEntry with metadata, or None if not found.
        """
        full_key = self._prefix_key(key)
        _, meta_path = self._key_to_paths(full_key)

        meta_raw = await self._run_sync(self._read_file_sync, meta_path)
        if meta_raw is None:
            return None

        try:
            meta = _EntryMeta.from_json(meta_raw.decode("utf-8"))
            if meta.is_expired:
                await self._delete_entry(full_key)
                return None

            return CacheEntry(
                key=key,
                value=None,  # Don't load value for metadata-only queries
                created_at=meta.created_at,
                expires_at=meta.expires_at,
                access_count=meta.access_count,
                last_accessed_at=meta.last_accessed_at,
                size_bytes=meta.size_bytes,
                tags=meta.tags,
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def get_disk_usage(self) -> dict[str, Any]:
        """
        Calculate disk usage statistics.

        Returns:
            Dictionary with total size, file count, and per-shard info.
        """
        def _calc() -> dict[str, Any]:
            total_bytes = 0
            file_count = 0
            shard_sizes: dict[str, int] = {}

            if not self._base_path.exists():
                return {"total_bytes": 0, "file_count": 0, "shards": {}}

            for shard_dir in self._base_path.iterdir():
                if not shard_dir.is_dir():
                    continue

                shard_bytes = 0
                shard_files = 0

                for f in shard_dir.iterdir():
                    if f.is_file():
                        size = f.stat().st_size
                        shard_bytes += size
                        shard_files += 1

                total_bytes += shard_bytes
                file_count += shard_files
                shard_sizes[shard_dir.name] = shard_bytes

            return {
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / (1024 * 1024), 2),
                "file_count": file_count,
                "shard_count": len(shard_sizes),
                "shards": shard_sizes,
            }

        return await self._run_sync(_calc)

    async def cleanup_expired(self) -> int:
        """
        Scan and remove all expired entries.

        Returns:
            Number of expired entries removed.
        """
        index = await self._ensure_index()
        expired_keys = [k for k, m in index.items() if m.is_expired]

        for key in expired_keys:
            await self._delete_entry(key)

        if expired_keys:
            logger.info("Cleaned up %d expired entries", len(expired_keys))

        return len(expired_keys)

    async def cleanup_orphaned(self) -> int:
        """
        Remove orphaned files (data without meta or vice versa).

        Returns:
            Number of orphaned files removed.
        """
        def _find_orphans() -> list[Path]:
            orphans: list[Path] = []

            if not self._base_path.exists():
                return orphans

            for shard_dir in self._base_path.iterdir():
                if not shard_dir.is_dir():
                    continue

                dat_files = {f.stem for f in shard_dir.glob("*.dat")}
                meta_files = {f.stem for f in shard_dir.glob("*.meta")}

                # .dat without .meta
                for stem in dat_files - meta_files:
                    orphans.append(shard_dir / f"{stem}.dat")

                # .meta without .dat
                for stem in meta_files - dat_files:
                    orphans.append(shard_dir / f"{stem}.meta")

            return orphans

        orphans = await self._run_sync(_find_orphans)

        for path in orphans:
            await self._run_sync(self._delete_file_sync, path)

        if orphans:
            logger.info("Cleaned up %d orphaned files", len(orphans))

        return len(orphans)

    async def compact(self) -> dict[str, Any]:
        """
        Compact the cache by removing expired and orphaned entries.

        Returns:
            Summary of cleanup operations.
        """
        expired = await self.cleanup_expired()
        orphaned = await self.cleanup_orphaned()
        usage = await self.get_disk_usage()

        return {
            "expired_removed": expired,
            "orphaned_removed": orphaned,
            "disk_usage": usage,
        }

    async def rebuild_index(self) -> int:
        """
        Force a full rescan of the disk to rebuild the in-memory index.

        Returns:
            Number of entries found.
        """
        self._index = await self._run_sync(self._scan_all_meta)
        self._index_dirty = True
        logger.info("Index rebuilt: %d entries", len(self._index))
        return len(self._index)

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    async def get_diagnostics(self) -> dict[str, Any]:
        """Get detailed diagnostics for monitoring."""
        usage = await self.get_disk_usage()
        index = await self._ensure_index()

        return {
            "backend": "disk",
            "base_path": str(self._base_path),
            "compress": self._compress,
            "max_size": self._max_size,
            "index_size": len(index),
            "disk_usage": usage,
            "stats": self._stats.to_dict(),
        }

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"DiskCacheBackend(path={str(self._base_path)!r}, "
            f"compress={self._compress}, status={status})"
        )
