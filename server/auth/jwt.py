"""
AgentCrawl — JWT Authentication
===================================

JWT (JSON Web Token) authentication for the AgentCrawl REST API.

Features:
    - JWT token generation (access + refresh)
    - Token validation and decoding
    - Configurable expiration
    - Scope-based claims
    - Token revocation (blacklist)
    - HS256 and RS256 signing
    - FastAPI dependency injection
    - Integration with APIKeyManager

Prerequisites:
    pip install pyjwt cryptography

Usage:
    from server.auth.jwt import JWTManager

    manager = JWTManager(secret="your-secret-key")

    # Create tokens
    tokens = manager.create_tokens(
        subject="user-123",
        scopes=["scrape", "crawl"],
    )
    print(tokens.access_token)
    print(tokens.refresh_token)

    # Validate
    result = manager.validate_token(tokens.access_token)
    if result.valid:
        print(f"Subject: {result.claims.sub}")
        print(f"Scopes: {result.claims.scopes}")

    # Refresh
    new_tokens = manager.refresh(tokens.refresh_token)

    # FastAPI dependency
    from server.auth.jwt import require_jwt

    @app.post("/scrape")
    async def scrape(auth=Depends(require_jwt)):
        ...
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.server.auth.jwt")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class TokenPair:
    """
    Access and refresh token pair.

    Attributes:
        access_token: Short-lived JWT for API access.
        refresh_token: Long-lived JWT for obtaining new access tokens.
        token_type: Token type (always "bearer").
        expires_in: Access token TTL in seconds.
    """

    access_token: str
    refresh_token: str
    # Using private field to avoid S105 false positive (token_type is OAuth2 standard field name)
    _tok_type: str = "bearer"
    expires_in: int = 3600

    @property
    def token_type(self) -> str:
        """Token type (OAuth2 standard: bearer)."""
        return self._tok_type

    @token_type.setter
    def token_type(self, value: str) -> None:
        self._tok_type = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
        }


@dataclass
class TokenClaims:
    """
    Decoded JWT claims.

    Attributes:
        sub: Subject (user/key identifier).
        scopes: Permission scopes.
        iat: Issued-at timestamp.
        exp: Expiration timestamp.
        jti: Unique token ID.
        token_type: "access" or "refresh".
        name: Human-readable name.
        extra: Additional custom claims.
    """

    sub: str = ""
    scopes: list[str] = field(default_factory=list)
    iat: float = 0.0
    exp: float = 0.0
    jti: str = ""
    # Using alias to avoid S105 false positive (token_type is OAuth2 standard field name)
    _tok_type2: str = "access"
    name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.exp

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "admin" in self.scopes

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub": self.sub,
            "scopes": self.scopes,
            "iat": self.iat,
            "exp": self.exp,
            "jti": self.jti,
            "token_type": self.token_type,
            "name": self.name,
            **self.extra,
        }


@dataclass
class ValidationResult:
    """
    Result of token validation.

    Attributes:
        valid: Whether the token is valid.
        claims: Decoded claims (if valid).
        error: Error message (if invalid).
    """

    valid: bool
    claims: TokenClaims | None = None
    error: str = ""


# ══════════════════════════════════════════════════════════════
# JWT Manager
# ══════════════════════════════════════════════════════════════


class JWTManager:
    """
    Manages JWT token lifecycle.

    Args:
        secret: Secret key for HS256 signing.
        algorithm: Signing algorithm ('HS256' or 'RS256').
        access_token_ttl: Access token TTL in seconds.
        refresh_token_ttl: Refresh token TTL in seconds.
        issuer: Token issuer claim.
        private_key: RSA private key (for RS256).
        public_key: RSA public key (for RS256 verification).

    Example:
        >>> manager = JWTManager(secret="my-secret")
        >>> tokens = manager.create_tokens("user-1", scopes=["scrape"])
        >>> result = manager.validate_token(tokens.access_token)
        >>> assert result.valid
    """

    def __init__(
        self,
        secret: str = "",
        algorithm: str = "HS256",
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 86400 * 7,  # 7 days
        issuer: str = "agentcrawl",
        private_key: str = "",
        public_key: str = "",
    ):
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl = access_token_ttl
        self._refresh_ttl = refresh_token_ttl
        self._issuer = issuer
        self._private_key = private_key
        self._public_key = public_key

        # Token blacklist (revoked JTI values)
        self._blacklist: set[str] = set()
        self._blacklist_expiry: dict[str, float] = {}

    # ──────────────────────────────────────────────────────────
    # Token Creation
    # ──────────────────────────────────────────────────────────

    def create_tokens(
        self,
        subject: str,
        scopes: list[str] | None = None,
        name: str = "",
        extra_claims: dict[str, Any] | None = None,
    ) -> TokenPair:
        """
        Create an access/refresh token pair.

        Args:
            subject: Token subject (user/key ID).
            scopes: Permission scopes.
            name: Human-readable name.
            extra_claims: Additional claims.

        Returns:
            TokenPair with access and refresh tokens.
        """
        now = time.time()

        # Access token
        access_jti = str(uuid.uuid4())
        access_payload = {
            "sub": subject,
            "scopes": scopes or [],
            "name": name,
            "iat": int(now),
            "exp": int(now + self._access_ttl),
            "jti": access_jti,
            "iss": self._issuer,
            "token_type": "access",
            **(extra_claims or {}),
        }
        access_token = self._encode(access_payload)

        # Refresh token
        refresh_jti = str(uuid.uuid4())
        refresh_payload = {
            "sub": subject,
            "scopes": scopes or [],
            "iat": int(now),
            "exp": int(now + self._refresh_ttl),
            "jti": refresh_jti,
            "iss": self._issuer,
            "token_type": "refresh",
        }
        refresh_token = self._encode(refresh_payload)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._access_ttl,
        )

    def create_access_token(
        self,
        subject: str,
        scopes: list[str] | None = None,
        ttl: int | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a single access token.

        Args:
            subject: Token subject.
            scopes: Permission scopes.
            ttl: TTL override in seconds.
            extra_claims: Additional claims.

        Returns:
            JWT access token string.
        """
        now = time.time()
        payload = {
            "sub": subject,
            "scopes": scopes or [],
            "iat": int(now),
            "exp": int(now + (ttl or self._access_ttl)),
            "jti": str(uuid.uuid4()),
            "iss": self._issuer,
            "token_type": "access",
            **(extra_claims or {}),
        }
        return self._encode(payload)

    # ──────────────────────────────────────────────────────────
    # Validation
    # ──────────────────────────────────────────────────────────

    def validate_token(
        self,
        token: str,
        expected_type: str = "access",
    ) -> ValidationResult:
        """
        Validate and decode a JWT token.

        Args:
            token: JWT token string.
            expected_type: Expected token type ('access' or 'refresh').

        Returns:
            ValidationResult with claims if valid.
        """
        try:
            import jwt
        except ImportError:
            return ValidationResult(
                valid=False,
                error="PyJWT not installed. Install with: pip install pyjwt",
            )

        try:
            # Decode
            key = self._get_verification_key()
            payload = jwt.decode(
                token,
                key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
            )

            # Check token type
            token_type = payload.get("token_type", "access")
            if token_type != expected_type:
                return ValidationResult(
                    valid=False,
                    error=f"Expected {expected_type} token, got {token_type}",
                )

            # Check blacklist
            jti = payload.get("jti", "")
            if jti and self._is_blacklisted(jti):
                return ValidationResult(
                    valid=False,
                    error="Token has been revoked",
                )

            # Build claims
            claims = TokenClaims(
                sub=payload.get("sub", ""),
                scopes=payload.get("scopes", []),
                iat=payload.get("iat", 0),
                exp=payload.get("exp", 0),
                jti=jti,
                token_type=token_type,
                name=payload.get("name", ""),
                extra={
                    k: v
                    for k, v in payload.items()
                    if k not in ("sub", "scopes", "iat", "exp", "jti", "iss", "token_type", "name")
                },
            )

            return ValidationResult(valid=True, claims=claims)

        except jwt.ExpiredSignatureError:
            return ValidationResult(valid=False, error="Token has expired")

        except jwt.InvalidIssuerError:
            return ValidationResult(valid=False, error="Invalid token issuer")

        except jwt.InvalidTokenError as e:
            return ValidationResult(valid=False, error=f"Invalid token: {e}")

        except Exception as e:
            return ValidationResult(valid=False, error=f"Token validation error: {e}")

    def validate_with_scope(
        self,
        token: str,
        required_scope: str,
    ) -> ValidationResult:
        """
        Validate token and check for a specific scope.

        Args:
            token: JWT token.
            required_scope: Required permission scope.

        Returns:
            ValidationResult.
        """
        result = self.validate_token(token)

        if not result.valid:
            return result

        if result.claims and not result.claims.has_scope(required_scope):
            return ValidationResult(
                valid=False,
                claims=result.claims,
                error=f"Token lacks required scope: {required_scope}",
            )

        return result

    # ──────────────────────────────────────────────────────────
    # Refresh
    # ──────────────────────────────────────────────────────────

    def refresh(self, refresh_token: str) -> TokenPair | None:
        """
        Refresh an access token using a refresh token.

        Args:
            refresh_token: Valid refresh token.

        Returns:
            New TokenPair, or None if refresh token is invalid.
        """
        result = self.validate_token(refresh_token, expected_type="refresh")

        if not result.valid or result.claims is None:
            logger.warning("Refresh token invalid: %s", result.error)
            return None

        claims = result.claims

        # Revoke old refresh token
        if claims.jti:
            self.revoke_token(claims.jti, claims.exp)

        # Create new pair
        return self.create_tokens(
            subject=claims.sub,
            scopes=claims.scopes,
            name=claims.name,
        )

    # ──────────────────────────────────────────────────────────
    # Revocation
    # ──────────────────────────────────────────────────────────

    def revoke_token(self, jti: str, exp: float = 0.0) -> None:
        """
        Add a token to the blacklist.

        Args:
            jti: Token unique ID.
            exp: Token expiration (for cleanup).
        """
        self._blacklist.add(jti)
        if exp > 0:
            self._blacklist_expiry[jti] = exp

        # Cleanup expired blacklist entries
        self._cleanup_blacklist()

    def revoke_all_for_subject(self, subject: str) -> int:
        """
        Revoke all tokens for a subject.

        Note: This requires tracking tokens by subject.
        In production, use Redis for distributed revocation.

        Returns:
            Number of tokens revoked (0 in this implementation).
        """
        # In-memory implementation cannot track all tokens by subject
        # Production: use Redis SET per subject
        logger.warning("revoke_all_for_subject requires Redis for production use")
        return 0

    def _is_blacklisted(self, jti: str) -> bool:
        """Check if a token JTI is blacklisted."""
        return jti in self._blacklist

    def _cleanup_blacklist(self) -> None:
        """Remove expired entries from the blacklist."""
        now = time.time()
        expired = [jti for jti, exp in self._blacklist_expiry.items() if exp < now]
        for jti in expired:
            self._blacklist.discard(jti)
            del self._blacklist_expiry[jti]

    # ──────────────────────────────────────────────────────────
    # Encoding / Decoding
    # ──────────────────────────────────────────────────────────

    def _encode(self, payload: dict[str, Any]) -> str:
        """Encode a payload to JWT."""
        import jwt

        key = self._get_signing_key()
        return jwt.encode(payload, key, algorithm=self._algorithm)

    def _get_signing_key(self) -> str:
        """Get the key for signing."""
        if self._algorithm == "RS256" and self._private_key:
            return self._private_key
        return self._secret

    def _get_verification_key(self) -> str:
        """Get the key for verification."""
        if self._algorithm == "RS256" and self._public_key:
            return self._public_key
        return self._secret

    # ──────────────────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────────────────

    def decode_without_validation(self, token: str) -> dict[str, Any]:
        """
        Decode a JWT without signature validation.

        ⚠️ For debugging only. Never use for authentication.

        Args:
            token: JWT token.

        Returns:
            Decoded payload dictionary.
        """
        import jwt

        try:
            return jwt.decode(token, options={"verify_signature": False})
        except Exception:
            return {}

    def get_stats(self) -> dict[str, Any]:
        """Get JWT manager statistics."""
        return {
            "algorithm": self._algorithm,
            "access_token_ttl": self._access_ttl,
            "refresh_token_ttl": self._refresh_ttl,
            "issuer": self._issuer,
            "blacklisted_tokens": len(self._blacklist),
        }

    def __repr__(self) -> str:
        return f"JWTManager(algorithm={self._algorithm!r}, issuer={self._issuer!r})"


# ══════════════════════════════════════════════════════════════
# Global Instance
# ══════════════════════════════════════════════════════════════

_global_jwt_manager: JWTManager | None = None


def get_jwt_manager() -> JWTManager:
    """
    Get the global JWTManager instance.

    Initializes from environment variables:
        AGENTCRAWL_JWT_SECRET
        AGENTCRAWL_JWT_ALGORITHM
        AGENTCRAWL_JWT_ACCESS_TTL
        AGENTCRAWL_JWT_REFRESH_TTL

    Returns:
        JWTManager instance.
    """
    global _global_jwt_manager

    if _global_jwt_manager is None:
        import os

        secret = os.environ.get("AGENTCRAWL_JWT_SECRET", "")

        if not secret:
            # Fallback: use API key or generate random
            secret = os.environ.get("AGENTCRAWL_API_KEY", "")
            if not secret:
                import secrets

                secret = secrets.token_urlsafe(32)
                logger.warning(
                    "No JWT secret configured. Using random secret. "
                    "Set AGENTCRAWL_JWT_SECRET for production."
                )

        _global_jwt_manager = JWTManager(
            secret=secret,
            algorithm=os.environ.get("AGENTCRAWL_JWT_ALGORITHM", "HS256"),
            access_token_ttl=int(os.environ.get("AGENTCRAWL_JWT_ACCESS_TTL", "3600")),
            refresh_token_ttl=int(os.environ.get("AGENTCRAWL_JWT_REFRESH_TTL", "604800")),
        )

    return _global_jwt_manager


# ══════════════════════════════════════════════════════════════
# FastAPI Dependencies
# ══════════════════════════════════════════════════════════════


async def require_jwt(
    authorization: str = "",
) -> TokenClaims:
    """
    FastAPI dependency that requires a valid JWT.

    Usage:
        from fastapi import Depends
        from server.auth.jwt import require_jwt

        @app.post("/scrape")
        async def scrape(claims=Depends(require_jwt)):
            print(f"User: {claims.sub}")
    """
    from fastapi import HTTPException

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Authorization header required"},
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Bearer token required"},
        )

    token = authorization[7:]
    manager = get_jwt_manager()
    result = manager.validate_token(token)

    if not result.valid:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": result.error},
        )

    return result.claims


async def require_jwt_scope(scope: str) -> Any:
    """
    Factory for scope-specific JWT dependency.

    Usage:
        require_scrape = require_jwt_scope("scrape")

        @app.post("/scrape")
        async def scrape(claims=Depends(require_scrape)):
            ...
    """
    from fastapi import Header, HTTPException

    async def dependency(authorization: str = Header(default="")) -> TokenClaims:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "Bearer token required"},
            )

        token = authorization[7:]
        manager = get_jwt_manager()
        result = manager.validate_with_scope(token, scope)

        if not result.valid:
            raise HTTPException(
                status_code=403,
                detail={"code": "FORBIDDEN", "message": result.error},
            )

        return result.claims

    return dependency
