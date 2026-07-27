"""
AgentCrawl — Authentication Middleware
==========================================

FastAPI/Starlette middleware for API key and JWT authentication.

Features:
    - API key validation (Bearer, X-API-Key, query param)
    - JWT validation (Bearer token)
    - Path-based exclusion (health, docs, OpenAPI)
    - Multiple auth methods (API key OR JWT)
    - Request context injection (auth info)
    - Consistent error responses
    - CORS preflight passthrough
    - Auth logging

Usage:
    from agentcrawl.server.auth.middleware import AuthMiddleware

    app = FastAPI()
    app.add_middleware(
        AuthMiddleware,
        api_key_manager=manager,
        jwt_manager=jwt_mgr,
        excluded_paths=["/health", "/docs"],
    )
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("agentcrawl.server.auth.middleware")


# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════

# Paths that skip authentication
DEFAULT_EXCLUDED_PATHS: set[str] = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}

# Paths that skip authentication (prefixes)
DEFAULT_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/docs",
    "/redoc",
    "/openapi",
)


# ══════════════════════════════════════════════════════════════
# Auth Context
# ══════════════════════════════════════════════════════════════

class AuthContext:
    """
    Authentication context attached to the request.

    Available as request.state.auth after middleware processing.

    Attributes:
        authenticated: Whether the request is authenticated.
        method: Auth method used ('api_key', 'jwt', 'none').
        subject: Authenticated subject (key ID or user ID).
        scopes: Granted permission scopes.
        name: Human-readable name.
        key_id: API key ID (if API key auth).
        token_jti: JWT token ID (if JWT auth).
    """

    def __init__(
        self,
        authenticated: bool = False,
        method: str = "none",
        subject: str = "",
        scopes: list[str] | None = None,
        name: str = "",
        key_id: str = "",
        token_jti: str = "",
    ):
        self.authenticated = authenticated
        self.method = method
        self.subject = subject
        self.scopes = scopes or []
        self.name = name
        self.key_id = key_id
        self.token_jti = token_jti

    def has_scope(self, scope: str) -> bool:
        """Check if a scope is granted."""
        return scope in self.scopes or "admin" in self.scopes

    def to_dict(self) -> dict[str, Any]:
        return {
            "authenticated": self.authenticated,
            "method": self.method,
            "subject": self.subject,
            "scopes": self.scopes,
            "name": self.name,
        }


# ══════════════════════════════════════════════════════════════
# Middleware
# ══════════════════════════════════════════════════════════════

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware for AgentCrawl API.

    Validates API keys and JWT tokens on every request.
    Injects an AuthContext into request.state.auth.

    Args:
        app: ASGI application.
        api_key_manager: APIKeyManager instance (optional).
        jwt_manager: JWTManager instance (optional).
        excluded_paths: Paths that skip auth.
        excluded_prefixes: Path prefixes that skip auth.
        require_auth: Whether to require authentication.
        log_auth: Whether to log authentication events.

    Example:
        >>> app.add_middleware(
        ...     AuthMiddleware,
        ...     api_key_manager=get_api_key_manager(),
        ...     jwt_manager=get_jwt_manager(),
        ... )
    """

    def __init__(
        self,
        app: Any,
        api_key_manager: Any = None,
        jwt_manager: Any = None,
        excluded_paths: set[str] | None = None,
        excluded_prefixes: tuple[str, ...] | None = None,
        require_auth: bool = False,
        log_auth: bool = True,
    ):
        super().__init__(app)
        self._api_key_manager = api_key_manager
        self._jwt_manager = jwt_manager
        self._excluded_paths = excluded_paths or DEFAULT_EXCLUDED_PATHS
        self._excluded_prefixes = excluded_prefixes or DEFAULT_EXCLUDED_PREFIXES
        self._require_auth = require_auth
        self._log_auth = log_auth

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process each request through authentication."""
        path = request.url.path

        # Skip auth for excluded paths
        if self._is_excluded(path):
            request.state.auth = AuthContext(authenticated=True, method="excluded")
            return await call_next(request)

        # Skip auth for CORS preflight
        if request.method == "OPTIONS":
            request.state.auth = AuthContext(authenticated=True, method="preflight")
            return await call_next(request)

        # Extract credentials
        auth_header = request.headers.get("Authorization", "")
        x_api_key = request.headers.get("X-API-Key", "")
        api_key_query = request.query_params.get("api_key", "")

        # Try authentication
        auth_context = await self._authenticate(
            auth_header=auth_header,
            x_api_key=x_api_key,
            api_key_query=api_key_query,
        )

        # Attach to request
        request.state.auth = auth_context

        # Check if auth is required
        if self._require_auth and not auth_context.authenticated:
            # If no auth is configured at all, allow access
            if not self._has_auth_configured():
                auth_context = AuthContext(
                    authenticated=True,
                    method="none",
                    subject="anonymous",
                    scopes=["admin"],
                )
                request.state.auth = auth_context
            else:
                return self._unauthorized_response(
                    "Authentication required. Provide API key or JWT token."
                )

        # Log
        if self._log_auth and auth_context.authenticated:
            logger.debug(
                "Auth: %s via %s (subject=%s)",
                path,
                auth_context.method,
                auth_context.subject,
            )

        return await call_next(request)

    # ──────────────────────────────────────────────────────────
    # Authentication Logic
    # ──────────────────────────────────────────────────────────

    async def _authenticate(
        self,
        auth_header: str,
        x_api_key: str,
        api_key_query: str,
    ) -> AuthContext:
        """
        Attempt authentication with available credentials.

        Tries (in order):
            1. JWT Bearer token
            2. API key Bearer token
            3. X-API-Key header
            4. api_key query parameter

        Args:
            auth_header: Authorization header value.
            x_api_key: X-API-Key header value.
            api_key_query: api_key query parameter.

        Returns:
            AuthContext with authentication result.
        """
        bearer_token = ""
        if auth_header.startswith("Bearer "):
            bearer_token = auth_header[7:]

        # 1. Try JWT
        if bearer_token and self._jwt_manager:
            ctx = self._try_jwt(bearer_token)
            if ctx.authenticated:
                return ctx

        # 2. Try API key (Bearer)
        if bearer_token and self._api_key_manager:
            ctx = self._try_api_key(bearer_token)
            if ctx.authenticated:
                return ctx

        # 3. Try X-API-Key header
        if x_api_key and self._api_key_manager:
            ctx = self._try_api_key(x_api_key)
            if ctx.authenticated:
                return ctx

        # 4. Try query parameter
        if api_key_query and self._api_key_manager:
            ctx = self._try_api_key(api_key_query)
            if ctx.authenticated:
                return ctx

        # No valid credentials
        return AuthContext(authenticated=False, method="none")

    def _try_jwt(self, token: str) -> AuthContext:
        """Try JWT authentication."""
        if not self._jwt_manager:
            return AuthContext(authenticated=False)

        try:
            result = self._jwt_manager.validate_token(token)

            if result.valid and result.claims:
                claims = result.claims
                return AuthContext(
                    authenticated=True,
                    method="jwt",
                    subject=claims.sub,
                    scopes=claims.scopes,
                    name=claims.name,
                    token_jti=claims.jti,
                )
        except Exception as e:
            logger.debug("JWT validation failed: %s", e)

        return AuthContext(authenticated=False)

    def _try_api_key(self, key: str) -> AuthContext:
        """Try API key authentication."""
        if not self._api_key_manager:
            return AuthContext(authenticated=False)

        try:
            result = self._api_key_manager.validate(key)

            if result.valid and result.key_info:
                info = result.key_info
                return AuthContext(
                    authenticated=True,
                    method="api_key",
                    subject=info.key_id,
                    scopes=info.scopes,
                    name=info.name,
                    key_id=info.key_id,
                )
        except Exception as e:
            logger.debug("API key validation failed: %s", e)

        return AuthContext(authenticated=False)

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _is_excluded(self, path: str) -> bool:
        """Check if a path is excluded from auth."""
        if path in self._excluded_paths:
            return True

        for prefix in self._excluded_prefixes:
            if path.startswith(prefix):
                return True

        return False

    def _has_auth_configured(self) -> bool:
        """Check if any auth method is configured."""
        if self._api_key_manager and self._api_key_manager._keys:
            return True

        if self._jwt_manager and self._jwt_manager._secret:
            return True

        return False

    @staticmethod
    def _unauthorized_response(message: str) -> JSONResponse:
        """Build a 401 response."""
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": message,
                }
            },
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )


# ══════════════════════════════════════════════════════════════
# Scope Enforcement Middleware
# ══════════════════════════════════════════════════════════════

class ScopeMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces scope requirements per path.

    Maps URL path prefixes to required scopes.

    Args:
        app: ASGI application.
        scope_rules: Dict of path prefix → required scope.

    Example:
        >>> app.add_middleware(
        ...     ScopeMiddleware,
        ...     scope_rules={
        ...         "/scrape": "scrape",
        ...         "/crawl": "crawl",
        ...         "/extract": "extract",
        ...         "/admin": "admin",
        ...     },
        ... )
    """

    def __init__(
        self,
        app: Any,
        scope_rules: dict[str, str] | None = None,
    ):
        super().__init__(app)
        self._scope_rules = scope_rules or {}

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Enforce scope requirements."""
        path = request.url.path

        # Find matching rule
        required_scope = ""
        for prefix, scope in self._scope_rules.items():
            if path.startswith(prefix):
                required_scope = scope
                break

        if not required_scope:
            return await call_next(request)

        # Check auth context
        auth: AuthContext | None = getattr(request.state, "auth", None)

        if auth is None or not auth.authenticated:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Authentication required",
                    }
                },
            )

        if not auth.has_scope(required_scope):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"Required scope: {required_scope}",
                        "granted_scopes": auth.scopes,
                    }
                },
            )

        return await call_next(request)


# ══════════════════════════════════════════════════════════════
# Request Logging Middleware
# ══════════════════════════════════════════════════════════════

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all requests with auth info.

    Logs method, path, status code, duration, and auth method.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.perf_counter()

        response = await call_next(request)

        elapsed = (time.perf_counter() - start) * 1000
        auth: AuthContext | None = getattr(request.state, "auth", None)
        auth_method = auth.method if auth else "unknown"

        logger.info(
            "%s %s → %d (%.1fms) [auth=%s]",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
            auth_method,
        )

        return response