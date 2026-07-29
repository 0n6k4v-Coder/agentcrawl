"""
AgentCrawl — API Key Authentication
=======================================

API key management for the AgentCrawl REST API server.

Features:
    - API key generation with prefixes
    - Secure key hashing (SHA-256)
    - Key validation and lookup
    - Key expiration (TTL)
    - Permission scopes
    - In-memory and file-based storage
    - Key rotation
    - Per-key rate limiting
    - Usage tracking

Usage:
    from server.auth.api_key import APIKeyManager

    manager = APIKeyManager()

    # Generate a key
    key = manager.create_key(name="production", scopes=["scrape", "crawl"])
    print(key.plain_key)  # "agc_live_x7k9m2..."

    # Validate a key
    result = manager.validate("agc_live_x7k9m2...")
    if result.valid:
        print(f"Key: {result.key_info.name}")
        print(f"Scopes: {result.key_info.scopes}")

    # Middleware usage
    from fastapi import Depends
    from server.auth.api_key import require_api_key

    @app.post("/scrape")
    async def scrape(auth=Depends(require_api_key)):
        ...
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("agentcrawl.server.auth")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

class KeyScope(str, Enum):
    """Permission scopes for API keys."""
    SCRAPE = "scrape"
    CRAWL = "crawl"
    MAP = "map"
    SEARCH = "search"
    EXTRACT = "extract"
    BATCH = "batch"
    INTERACT = "interact"
    ADMIN = "admin"

    @classmethod
    def all(cls) -> list[KeyScope]:
        return list(cls)

    @classmethod
    def default(cls) -> list[KeyScope]:
        return [cls.SCRAPE, cls.CRAWL, cls.MAP, cls.SEARCH, cls.EXTRACT]


@dataclass
class APIKeyInfo:
    """
    Stored API key information.

    The plain key is never stored — only the SHA-256 hash.

    Attributes:
        key_id: Unique key identifier.
        key_hash: SHA-256 hash of the key.
        key_prefix: First 12 chars of the key (for identification).
        name: Human-readable key name.
        scopes: Permission scopes.
        created_at: Creation timestamp.
        expires_at: Expiration timestamp (0 = never).
        last_used_at: Last usage timestamp.
        is_active: Whether the key is active.
        usage_count: Total usage count.
        rate_limit: Requests per minute for this key.
        metadata: Additional metadata.
    """
    key_id: str
    key_hash: str
    key_prefix: str
    name: str = ""
    scopes: list[str] = field(default_factory=lambda: [s.value for s in KeyScope.default()])
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    last_used_at: float = 0.0
    is_active: bool = True
    usage_count: int = 0
    rate_limit: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if the key has expired."""
        if self.expires_at == 0:
            return False
        return time.time() > self.expires_at

    def has_scope(self, scope: str | KeyScope) -> bool:
        """Check if the key has a specific scope."""
        scope_value = scope.value if isinstance(scope, KeyScope) else scope
        return scope_value in self.scopes or KeyScope.ADMIN.value in self.scopes

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (no sensitive data)."""
        return {
            "key_id": self.key_id,
            "key_prefix": self.key_prefix,
            "name": self.name,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used_at": self.last_used_at,
            "is_active": self.is_active,
            "is_expired": self.is_expired,
            "usage_count": self.usage_count,
            "rate_limit": self.rate_limit,
        }


@dataclass
class CreatedKey:
    """
    Result of key creation.

    The plain_key is only available at creation time.

    Attributes:
        plain_key: The full plain-text API key (show once).
        key_info: Stored key information.
    """
    plain_key: str
    key_info: APIKeyInfo


@dataclass
class ValidationResult:
    """
    Result of key validation.

    Attributes:
        valid: Whether the key is valid.
        key_info: Key information (if valid).
        error: Error message (if invalid).
    """
    valid: bool
    key_info: APIKeyInfo | None = None
    error: str = ""


# ══════════════════════════════════════════════════════════════
# API Key Manager
# ══════════════════════════════════════════════════════════════

class APIKeyManager:
    """
    Manages API key lifecycle: creation, validation, revocation.

    Keys are stored as SHA-256 hashes. The plain key is only
    returned once at creation time.

    Args:
        storage_path: Optional file path for persistent storage.
        default_rate_limit: Default requests per minute.
        key_prefix: Prefix for generated keys.

    Example:
        >>> manager = APIKeyManager()
        >>> created = manager.create_key(name="prod")
        >>> print(created.plain_key)  # Save this!
        >>> result = manager.validate(created.plain_key)
        >>> assert result.valid
    """

    def __init__(
        self,
        storage_path: str | None = None,
        default_rate_limit: int = 100,
        key_prefix: str = "agc",
    ):
        self._storage_path = storage_path
        self._default_rate_limit = default_rate_limit
        self._key_prefix = key_prefix

        # In-memory storage: key_hash → APIKeyInfo
        self._keys: dict[str, APIKeyInfo] = {}

        # Load from file if exists
        if storage_path:
            self._load_from_file()

    # ──────────────────────────────────────────────────────────
    # Key Creation
    # ──────────────────────────────────────────────────────────

    def create_key(
        self,
        name: str = "",
        scopes: list[str | KeyScope] | None = None,
        expires_in_seconds: int = 0,
        rate_limit: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CreatedKey:
        """
        Create a new API key.

        Args:
            name: Human-readable key name.
            scopes: Permission scopes (default: scrape, crawl, map, search, extract).
            expires_in_seconds: TTL in seconds (0 = never expires).
            rate_limit: Requests per minute (default: 100).
            metadata: Additional metadata.

        Returns:
            CreatedKey with plain_key (show once) and key_info.
        """
        # Generate key
        random_part = secrets.token_urlsafe(32)
        plain_key = f"{self._key_prefix}_live_{random_part}"

        # Hash it
        key_hash = self._hash_key(plain_key)
        key_prefix = plain_key[:16]

        # Resolve scopes
        if scopes is None:
            scope_values = [s.value for s in KeyScope.default()]
        else:
            scope_values = [
                s.value if isinstance(s, KeyScope) else s
                for s in scopes
            ]

        # Create info
        key_id = f"key_{secrets.token_hex(6)}"
        expires_at = time.time() + expires_in_seconds if expires_in_seconds > 0 else 0.0

        key_info = APIKeyInfo(
            key_id=key_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name or f"key-{key_id}",
            scopes=scope_values,
            expires_at=expires_at,
            rate_limit=rate_limit or self._default_rate_limit,
            metadata=metadata or {},
        )

        # Store
        self._keys[key_hash] = key_info
        self._save_to_file()

        logger.info(
            "API key created: %s (name=%s, scopes=%s)",
            key_info.key_id,
            key_info.name,
            scope_values,
        )

        return CreatedKey(plain_key=plain_key, key_info=key_info)

    # ──────────────────────────────────────────────────────────
    # Validation
    # ──────────────────────────────────────────────────────────

    def validate(self, plain_key: str) -> ValidationResult:
        """
        Validate an API key.

        Args:
            plain_key: The plain-text API key.

        Returns:
            ValidationResult with validity and key info.
        """
        if not plain_key:
            return ValidationResult(valid=False, error="Empty API key")

        key_hash = self._hash_key(plain_key)
        key_info = self._keys.get(key_hash)

        if key_info is None:
            return ValidationResult(valid=False, error="Invalid API key")

        if not key_info.is_active:
            return ValidationResult(valid=False, error="API key is revoked")

        if key_info.is_expired:
            return ValidationResult(valid=False, error="API key has expired")

        # Update usage
        key_info.last_used_at = time.time()
        key_info.usage_count += 1

        return ValidationResult(valid=True, key_info=key_info)

    def validate_with_scope(
        self,
        plain_key: str,
        required_scope: str | KeyScope,
    ) -> ValidationResult:
        """
        Validate an API key and check for a specific scope.

        Args:
            plain_key: The plain-text API key.
            required_scope: Required permission scope.

        Returns:
            ValidationResult.
        """
        result = self.validate(plain_key)

        if not result.valid:
            return result

        if result.key_info and not result.key_info.has_scope(required_scope):
            scope_value = (
                required_scope.value
                if isinstance(required_scope, KeyScope)
                else required_scope
            )
            return ValidationResult(
                valid=False,
                key_info=result.key_info,
                error=f"API key lacks required scope: {scope_value}",
            )

        return result

    # ──────────────────────────────────────────────────────────
    # Key Management
    # ──────────────────────────────────────────────────────────

    def revoke_key(self, key_id: str) -> bool:
        """
        Revoke an API key by ID.

        Args:
            key_id: Key identifier.

        Returns:
            True if the key was found and revoked.
        """
        for key_hash, info in self._keys.items():
            if info.key_id == key_id:
                info.is_active = False
                self._save_to_file()
                logger.info("API key revoked: %s", key_id)
                return True
        return False

    def delete_key(self, key_id: str) -> bool:
        """
        Permanently delete an API key.

        Args:
            key_id: Key identifier.

        Returns:
            True if the key was found and deleted.
        """
        for key_hash, info in list(self._keys.items()):
            if info.key_id == key_id:
                del self._keys[key_hash]
                self._save_to_file()
                logger.info("API key deleted: %s", key_id)
                return True
        return False

    def rotate_key(self, key_id: str) -> CreatedKey | None:
        """
        Rotate an API key: revoke old, create new with same settings.

        Args:
            key_id: Key identifier to rotate.

        Returns:
            New CreatedKey, or None if key not found.
        """
        old_info = None
        old_hash = None

        for key_hash, info in self._keys.items():
            if info.key_id == key_id:
                old_info = info
                old_hash = key_hash
                break

        if old_info is None:
            return None

        # Revoke old key
        old_info.is_active = False

        # Create new key with same settings
        new_key = self.create_key(
            name=old_info.name,
            scopes=old_info.scopes,
            rate_limit=old_info.rate_limit,
            metadata=old_info.metadata,
        )

        logger.info("API key rotated: %s → %s", key_id, new_key.key_info.key_id)
        return new_key

    def list_keys(self, include_inactive: bool = False) -> list[APIKeyInfo]:
        """
        List all API keys.

        Args:
            include_inactive: Include revoked/expired keys.

        Returns:
            List of APIKeyInfo objects.
        """
        keys = list(self._keys.values())

        if not include_inactive:
            keys = [k for k in keys if k.is_active and not k.is_expired]

        return sorted(keys, key=lambda k: k.created_at, reverse=True)

    def get_key(self, key_id: str) -> APIKeyInfo | None:
        """Get a key by ID."""
        for info in self._keys.values():
            if info.key_id == key_id:
                return info
        return None

    # ──────────────────────────────────────────────────────────
    # Simple Key Mode (single key from settings)
    # ──────────────────────────────────────────────────────────

    def set_simple_key(self, api_key: str) -> None:
        """
        Set a single API key (from environment/settings).

        Used when AGENTCRAWL_API_KEY is set directly.

        Args:
            api_key: Plain-text API key.
        """
        if not api_key:
            return

        key_hash = self._hash_key(api_key)

        if key_hash not in self._keys:
            self._keys[key_hash] = APIKeyInfo(
                key_id="key_default",
                key_hash=key_hash,
                key_prefix=api_key[:16],
                name="default",
                scopes=[s.value for s in KeyScope.all()],
                rate_limit=1000,
            )

    # ──────────────────────────────────────────────────────────
    # Storage
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _hash_key(plain_key: str) -> str:
        """Hash an API key with SHA-256."""
        return hashlib.sha256(plain_key.encode("utf-8")).hexdigest()

    def _save_to_file(self) -> None:
        """Save keys to file (if storage_path is set)."""
        if not self._storage_path:
            return

        try:
            path = Path(self._storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                info.key_id: {
                    "key_hash": info.key_hash,
                    "key_prefix": info.key_prefix,
                    "name": info.name,
                    "scopes": info.scopes,
                    "created_at": info.created_at,
                    "expires_at": info.expires_at,
                    "is_active": info.is_active,
                    "usage_count": info.usage_count,
                    "rate_limit": info.rate_limit,
                    "metadata": info.metadata,
                }
                for info in self._keys.values()
            }

            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        except Exception as e:
            logger.warning("Failed to save API keys: %s", e)

    def _load_from_file(self) -> None:
        """Load keys from file (if exists)."""
        if not self._storage_path:
            return

        path = Path(self._storage_path)
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))

            for key_id, key_data in data.items():
                info = APIKeyInfo(
                    key_id=key_id,
                    key_hash=key_data["key_hash"],
                    key_prefix=key_data.get("key_prefix", ""),
                    name=key_data.get("name", ""),
                    scopes=key_data.get("scopes", []),
                    created_at=key_data.get("created_at", 0),
                    expires_at=key_data.get("expires_at", 0),
                    is_active=key_data.get("is_active", True),
                    usage_count=key_data.get("usage_count", 0),
                    rate_limit=key_data.get("rate_limit", 100),
                    metadata=key_data.get("metadata", {}),
                )
                self._keys[info.key_hash] = info

            logger.info("Loaded %d API keys from %s", len(self._keys), path)

        except Exception as e:
            logger.warning("Failed to load API keys: %s", e)

    # ──────────────────────────────────────────────────────────
    # Stats
    # ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get API key statistics."""
        active = sum(1 for k in self._keys.values() if k.is_active and not k.is_expired)
        total_usage = sum(k.usage_count for k in self._keys.values())

        return {
            "total_keys": len(self._keys),
            "active_keys": active,
            "total_usage": total_usage,
            "storage": "file" if self._storage_path else "memory",
        }

    def __repr__(self) -> str:
        return f"APIKeyManager(keys={len(self._keys)})"


# ══════════════════════════════════════════════════════════════
# Global Instance
# ══════════════════════════════════════════════════════════════

_global_manager: APIKeyManager | None = None


def get_api_key_manager() -> APIKeyManager:
    """
    Get the global APIKeyManager instance.

    Initializes with the AGENTCRAWL_API_KEY environment variable
    if set.

    Returns:
        APIKeyManager instance.
    """
    global _global_manager

    if _global_manager is None:
        storage_path = os.environ.get("AGENTCRAWL_API_KEYS_FILE", "")
        _global_manager = APIKeyManager(
            storage_path=storage_path or None,
        )

        # Load simple key from environment
        env_key = os.environ.get("AGENTCRAWL_API_KEY", "")
        if env_key:
            _global_manager.set_simple_key(env_key)

    return _global_manager


# ══════════════════════════════════════════════════════════════
# FastAPI Dependency
# ══════════════════════════════════════════════════════════════

async def require_api_key(
    authorization: str = "",
    x_api_key: str = "",
    api_key_query: str = "",
) -> APIKeyInfo:
    """
    FastAPI dependency that requires a valid API key.

    Usage:
        from fastapi import Depends
        from server.auth.api_key import require_api_key

        @app.post("/scrape")
        async def scrape(key_info=Depends(require_api_key)):
            print(f"Authenticated as: {key_info.name}")
    """
    from fastapi import HTTPException

    # This is a simplified version — in production, use the
    # full dependency from server/api/deps.py
    manager = get_api_key_manager()

    # Extract key from various sources
    plain_key = ""

    if authorization and authorization.startswith("Bearer "):
        plain_key = authorization[7:]
    elif x_api_key:
        plain_key = x_api_key
    elif api_key_query:
        plain_key = api_key_query

    if not plain_key:
        # If no keys are configured, allow access
        if not manager._keys:
            return APIKeyInfo(
                key_id="anonymous",
                key_hash="",
                key_prefix="",
                name="anonymous",
                scopes=[s.value for s in KeyScope.all()],
            )

        from fastapi import HTTPException
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "API key required"},
        )

    result = manager.validate(plain_key)

    if not result.valid:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": result.error},
        )

    return result.key_info
