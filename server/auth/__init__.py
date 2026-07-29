"""
AgentCrawl — Server Auth Package
====================================

Authentication, authorization, and rate limiting for the
AgentCrawl REST API server.

Modules:
    api_key      — API key management and validation
    jwt          — JWT token generation and validation
    middleware   — Auth and scope enforcement middleware
    rate_limiter — Rate limiting algorithms and middleware

Quick Start:
    from server.auth import (
        APIKeyManager,
        JWTManager,
        AuthMiddleware,
        RateLimiter,
    )

    # API keys
    manager = APIKeyManager()
    key = manager.create_key(name="production")
    print(key.plain_key)

    # JWT
    jwt_mgr = JWTManager(secret="your-secret")
    tokens = jwt_mgr.create_tokens("user-1", scopes=["scrape"])

    # Middleware
    app.add_middleware(AuthMiddleware, api_key_manager=manager)
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter())
"""

from __future__ import annotations

# API Key
from server.auth.api_key import (
    APIKeyInfo,
    APIKeyManager,
    CreatedKey,
    KeyScope,
    get_api_key_manager,
    require_api_key,
)
from server.auth.api_key import (
    ValidationResult as ApiKeyValidationResult,
)

# JWT
from server.auth.jwt import (
    JWTManager,
    TokenClaims,
    TokenPair,
    get_jwt_manager,
    require_jwt,
)
from server.auth.jwt import (
    ValidationResult as JWTValidationResult,
)

# Middleware
from server.auth.middleware import (
    AuthContext,
    AuthMiddleware,
    RequestLoggingMiddleware,
    ScopeMiddleware,
)

# Rate Limiter
from server.auth.rate_limiter import (
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimiter,
    RateLimitMiddleware,
    RateLimitResult,
    get_rate_limiter,
)

__all__ = [
    # API Key
    "APIKeyManager",
    "APIKeyInfo",
    "CreatedKey",
    "KeyScope",
    "ApiKeyValidationResult",
    "get_api_key_manager",
    "require_api_key",
    # JWT
    "JWTManager",
    "TokenPair",
    "TokenClaims",
    "JWTValidationResult",
    "get_jwt_manager",
    "require_jwt",
    # Middleware
    "AuthMiddleware",
    "AuthContext",
    "ScopeMiddleware",
    "RequestLoggingMiddleware",
    # Rate Limiter
    "RateLimiter",
    "RateLimitConfig",
    "RateLimitResult",
    "RateLimitAlgorithm",
    "RateLimitMiddleware",
    "get_rate_limiter",
]
