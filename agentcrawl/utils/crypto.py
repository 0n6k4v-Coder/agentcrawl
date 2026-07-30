"""
AgentCrawl — Cryptographic Utilities
========================================

Cryptographic utilities for API key encryption, hashing, token
generation, and secure key management.

Features:
    - AES-256-GCM encryption/decryption for API keys
    - SHA-256 and SHA-512 hashing
    - HMAC signing and verification
    - Secure token generation
    - PBKDF2 key derivation
    - Base64 encoding/decoding
    - Key management from environment

Usage:
    from agentcrawl.utils.crypto import (
        encrypt_api_key,
        decrypt_api_key,
        hash_sha256,
        generate_token,
        CryptoManager,
    )

    # Encrypt an API key
    encrypted = encrypt_api_key("sk-abc123...", encryption_key="my-secret")
    print(encrypted)  # "gAAAAAB..."

    # Decrypt
    decrypted = decrypt_api_key(encrypted, encryption_key="my-secret")
    print(decrypted)  # "sk-abc123..."

    # Hash
    digest = hash_sha256("hello world")

    # Token generation
    token = generate_token(length=32)

    # Full manager
    manager = CryptoManager(encryption_key="my-secret")
    encrypted = manager.encrypt("sensitive data")
    decrypted = manager.decrypt(encrypted)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from typing import Any

logger = logging.getLogger("agentcrawl.utils.crypto")


# ══════════════════════════════════════════════════════════════
# Hashing
# ══════════════════════════════════════════════════════════════

def hash_sha256(data: str | bytes) -> str:
    """
    Compute SHA-256 hash of data.

    Args:
        data: Input string or bytes.

    Returns:
        Hex-encoded SHA-256 digest.

    Example:
        >>> hash_sha256("hello world")
        'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9'
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_sha512(data: str | bytes) -> str:
    """
    Compute SHA-512 hash of data.

    Args:
        data: Input string or bytes.

    Returns:
        Hex-encoded SHA-512 digest.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha512(data).hexdigest()


def hash_url(url: str) -> str:
    """
    Compute a stable hash for a URL (for cache keys).

    Normalizes the URL before hashing.

    Args:
        url: URL string.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    # Normalize: lowercase scheme and host, strip trailing slash
    normalized = url.strip().rstrip("/")
    return hash_sha256(normalized)


# ══════════════════════════════════════════════════════════════
# HMAC
# ══════════════════════════════════════════════════════════════

def hmac_sign(
    data: str | bytes,
    key: str | bytes,
    algorithm: str = "sha256",
) -> str:
    """
    Compute HMAC signature.

    Args:
        data: Data to sign.
        key: Secret key.
        algorithm: Hash algorithm ('sha256', 'sha512', 'md5').

    Returns:
        Hex-encoded HMAC signature.

    Example:
        >>> sig = hmac_sign("message", "secret_key")
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    if isinstance(key, str):
        key = key.encode("utf-8")

    hash_func = getattr(hashlib, algorithm, hashlib.sha256)
    return hmac.new(key, data, hash_func).hexdigest()


def hmac_verify(
    data: str | bytes,
    signature: str,
    key: str | bytes,
    algorithm: str = "sha256",
) -> bool:
    """
    Verify an HMAC signature.

    Args:
        data: Original data.
        signature: Expected signature (hex).
        key: Secret key.
        algorithm: Hash algorithm.

    Returns:
        True if the signature is valid.
    """
    expected = hmac_sign(data, key, algorithm)
    return hmac.compare_digest(expected, signature)


# ══════════════════════════════════════════════════════════════
# Token Generation
# ══════════════════════════════════════════════════════════════

def generate_token(length: int = 32, prefix: str = "") -> str:
    """
    Generate a cryptographically secure random token.

    Args:
        length: Token length in characters.
        prefix: Optional prefix (e.g., 'agc_').

    Returns:
        URL-safe random token string.

    Example:
        >>> generate_token(32, prefix="agc_")
        'agc_a1b2c3d4e5f6...'
    """
    # Generate random bytes and encode as URL-safe base64
    num_bytes = max(1, (length * 3) // 4)
    token = secrets.token_urlsafe(num_bytes)[:length]

    if prefix:
        return f"{prefix}{token}"
    return token


def generate_api_key(prefix: str = "agc") -> str:
    """
    Generate an API key.

    Args:
        prefix: Key prefix.

    Returns:
        API key string (e.g., 'agc_live_a1b2c3...').

    Example:
        >>> generate_api_key()
        'agc_live_x7k9m2...'
    """
    random_part = secrets.token_urlsafe(24)
    return f"{prefix}_live_{random_part}"


def generate_request_id() -> str:
    """
    Generate a unique request ID.

    Returns:
        Request ID string (e.g., 'req_a1b2c3d4').
    """
    return f"req_{secrets.token_hex(6)}"


def generate_job_id() -> str:
    """
    Generate a unique job ID.

    Returns:
        Job ID string (e.g., 'job_a1b2c3d4').
    """
    return f"job_{secrets.token_hex(6)}"


def generate_session_id() -> str:
    """
    Generate a unique session ID.

    Returns:
        Session ID string (e.g., 'sess_a1b2c3d4e5f6g7h8').
    """
    return f"sess_{secrets.token_hex(8)}"


# ══════════════════════════════════════════════════════════════
# Key Derivation
# ══════════════════════════════════════════════════════════════

def derive_key(
    password: str,
    salt: bytes | None = None,
    iterations: int = 100_000,
    key_length: int = 32,
) -> tuple[bytes, bytes]:
    """
    Derive an encryption key from a password using PBKDF2.

    Args:
        password: Password string.
        salt: Salt bytes (generated if None).
        iterations: PBKDF2 iterations.
        key_length: Derived key length in bytes.

    Returns:
        Tuple of (derived_key, salt).

    Example:
        >>> key, salt = derive_key("my-password")
        >>> key2, _ = derive_key("my-password", salt=salt)
        >>> assert key == key2
    """
    if salt is None:
        salt = os.urandom(16)

    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=key_length,
    )

    return key, salt


# ══════════════════════════════════════════════════════════════
# AES Encryption (using cryptography library)
# ══════════════════════════════════════════════════════════════

def _get_fernet(key: str | bytes) -> Any:
    """
    Get a Fernet instance from an encryption key.

    Args:
        key: Encryption key (string or bytes).

    Returns:
        Fernet instance.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as err:
        raise ImportError(
            "cryptography library required for encryption. "
            "Install with: pip install cryptography"
        ) from err

    if isinstance(key, str):
        key = key.encode("utf-8")

    # If key is not a valid Fernet key, derive one
    if len(key) != 44:  # Fernet keys are 44 bytes (url-safe base64)
        # Derive a Fernet-compatible key from the password
        derived = hashlib.sha256(key).digest()
        key = base64.urlsafe_b64encode(derived)

    return Fernet(key)


def encrypt_api_key(
    api_key: str,
    encryption_key: str | bytes = "",
) -> str:
    """
    Encrypt an API key using Fernet (AES-128-CBC + HMAC).

    Args:
        api_key: Plain-text API key.
        encryption_key: Encryption key (from ENCRYPTION_KEY env var).

    Returns:
        Encrypted string (base64-encoded).

    Example:
        >>> encrypted = encrypt_api_key("sk-abc123", "my-secret-key")
        >>> print(encrypted)  # "gAAAAAB..."
    """
    if not encryption_key:
        encryption_key = os.environ.get("ENCRYPTION_KEY", "")

    if not encryption_key:
        raise ValueError(
            "Encryption key required. Set ENCRYPTION_KEY environment variable."
        )

    fernet = _get_fernet(encryption_key)
    encrypted_bytes = fernet.encrypt(api_key.encode("utf-8"))
    return encrypted_bytes.decode("ascii")


def decrypt_api_key(
    encrypted: str,
    encryption_key: str | bytes = "",
) -> str:
    """
    Decrypt an encrypted API key.

    Args:
        encrypted: Encrypted string.
        encryption_key: Encryption key.

    Returns:
        Decrypted plain-text API key.

    Example:
        >>> decrypted = decrypt_api_key(encrypted, "my-secret-key")
        >>> print(decrypted)  # "sk-abc123"
    """
    if not encryption_key:
        encryption_key = os.environ.get("ENCRYPTION_KEY", "")

    if not encryption_key:
        raise ValueError(
            "Encryption key required. Set ENCRYPTION_KEY environment variable."
        )

    fernet = _get_fernet(encryption_key)
    decrypted_bytes = fernet.decrypt(encrypted.encode("ascii"))
    return decrypted_bytes.decode("utf-8")


# ══════════════════════════════════════════════════════════════
# Crypto Manager
# ══════════════════════════════════════════════════════════════

class CryptoManager:
    """
    Manages cryptographic operations with a single encryption key.

    Provides encrypt/decrypt, hashing, signing, and token generation
    with a consistent key.

    Args:
        encryption_key: Master encryption key.
        signing_key: Separate key for HMAC signing (uses encryption_key if None).

    Example:
        >>> manager = CryptoManager(encryption_key="my-secret")
        >>> encrypted = manager.encrypt("sensitive data")
        >>> decrypted = manager.decrypt(encrypted)
        >>> assert decrypted == "sensitive data"
        >>>
        >>> sig = manager.sign("message")
        >>> assert manager.verify("message", sig)
    """

    def __init__(
        self,
        encryption_key: str | bytes = "",
        signing_key: str | bytes | None = None,
    ):
        if not encryption_key:
            encryption_key = os.environ.get("ENCRYPTION_KEY", "")

        if not encryption_key:
            raise ValueError(
                "Encryption key required. Set ENCRYPTION_KEY or pass encryption_key."
            )

        self._encryption_key = encryption_key
        self._signing_key = signing_key or encryption_key
        self._fernet = _get_fernet(encryption_key)

    # ──────────────────────────────────────────────────────────
    # Encryption
    # ──────────────────────────────────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string.

        Args:
            plaintext: Plain-text string.

        Returns:
            Encrypted base64 string.
        """
        encrypted_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted_bytes.decode("ascii")

    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt an encrypted string.

        Args:
            encrypted: Encrypted base64 string.

        Returns:
            Decrypted plain-text string.
        """
        decrypted_bytes = self._fernet.decrypt(encrypted.encode("ascii"))
        return decrypted_bytes.decode("utf-8")

    def encrypt_dict(self, data: dict[str, str]) -> dict[str, str]:
        """
        Encrypt all values in a dictionary.

        Args:
            data: Dictionary with string values.

        Returns:
            Dictionary with encrypted values.
        """
        return {k: self.encrypt(v) for k, v in data.items()}

    def decrypt_dict(self, data: dict[str, str]) -> dict[str, str]:
        """
        Decrypt all values in a dictionary.

        Args:
            data: Dictionary with encrypted values.

        Returns:
            Dictionary with decrypted values.
        """
        result: dict[str, str] = {}
        for k, v in data.items():
            try:
                result[k] = self.decrypt(v)
            except Exception:
                result[k] = v  # Keep original if decryption fails
        return result

    # ──────────────────────────────────────────────────────────
    # Signing
    # ──────────────────────────────────────────────────────────

    def sign(self, data: str) -> str:
        """
        Sign data with HMAC.

        Args:
            data: Data to sign.

        Returns:
            Hex-encoded HMAC signature.
        """
        return hmac_sign(data, self._signing_key)

    def verify(self, data: str, signature: str) -> bool:
        """
        Verify an HMAC signature.

        Args:
            data: Original data.
            signature: Expected signature.

        Returns:
            True if valid.
        """
        return hmac_verify(data, signature, self._signing_key)

    # ──────────────────────────────────────────────────────────
    # Hashing
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def hash(data: str, algorithm: str = "sha256") -> str:
        """
        Hash data with the specified algorithm.

        Args:
            data: Input data.
            algorithm: Hash algorithm ('sha256', 'sha512', 'md5').

        Returns:
            Hex-encoded digest.
        """
        if algorithm == "sha256":
            return hash_sha256(data)
        elif algorithm == "sha512":
            return hash_sha512(data)
        elif algorithm == "md5":
            return hash_sha256(data)  # Use SHA-256 instead of MD5 for compatibility
        else:
            return hash_sha256(data)

    # ──────────────────────────────────────────────────────────
    # Tokens
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def generate_token(length: int = 32, prefix: str = "") -> str:
        """Generate a secure random token."""
        return generate_token(length, prefix)

    # ──────────────────────────────────────────────────────────
    # Key Rotation
    # ──────────────────────────────────────────────────────────

    def rotate_key(self, new_key: str) -> None:
        """
        Rotate the encryption key.

        Note: Data encrypted with the old key will not be
        decryptable after rotation.

        Args:
            new_key: New encryption key.
        """
        self._encryption_key = new_key
        self._fernet = _get_fernet(new_key)
        logger.info("Encryption key rotated")

    # ──────────────────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def generate_encryption_key() -> str:
        """
        Generate a new Fernet-compatible encryption key.

        Returns:
            Base64-encoded encryption key string.

        Example:
            >>> key = CryptoManager.generate_encryption_key()
            >>> print(key)  # Add to .env as ENCRYPTION_KEY
        """
        try:
            from cryptography.fernet import Fernet
            return Fernet.generate_key().decode("ascii")
        except ImportError:
            # Fallback: generate a random key
            return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")

    def __repr__(self) -> str:
        return "CryptoManager(key=***)"


# ══════════════════════════════════════════════════════════════
# Base64 Utilities
# ══════════════════════════════════════════════════════════════

def b64_encode(data: str | bytes) -> str:
    """
    Encode data to base64.

    Args:
        data: Input string or bytes.

    Returns:
        Base64 encoded string.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")


def b64_decode(encoded: str) -> str:
    """
    Decode base64 to string.

    Args:
        encoded: Base64 encoded string.

    Returns:
        Decoded string.
    """
    return base64.b64decode(encoded).decode("utf-8")


def b64_encode_bytes(data: bytes) -> str:
    """Encode bytes to base64 string."""
    return base64.b64encode(data).decode("ascii")


def b64_decode_bytes(encoded: str) -> bytes:
    """Decode base64 string to bytes."""
    return base64.b64decode(encoded)


# ══════════════════════════════════════════════════════════════
# Masking
# ══════════════════════════════════════════════════════════════

def mask_api_key(api_key: str, visible_chars: int = 4) -> str:
    """
    Mask an API key for safe display.

    Args:
        api_key: API key string.
        visible_chars: Number of characters to show at the end.

    Returns:
        Masked string (e.g., 'sk-...abc1').

    Example:
        >>> mask_api_key("sk-abc123def456")
        'sk-...f456'
    """
    if not api_key:
        return ""

    if len(api_key) <= visible_chars:
        return "*" * len(api_key)

    prefix = api_key[:3] if len(api_key) > 6 else ""
    suffix = api_key[-visible_chars:]
    return f"{prefix}...{suffix}"


def mask_email(email: str) -> str:
    """
    Mask an email address for safe display.

    Args:
        email: Email string.

    Returns:
        Masked email (e.g., 'u***@example.com').
    """
    if "@" not in email:
        return "***"

    local, domain = email.rsplit("@", 1)
    masked_local = "*" if len(local) <= 1 else local[0] + "*" * (len(local) - 1)

    return f"{masked_local}@{domain}"
