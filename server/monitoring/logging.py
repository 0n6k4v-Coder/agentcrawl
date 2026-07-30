"""
AgentCrawl — Server Logging
===============================

Logging configuration and middleware for the AgentCrawl server.

Features:
    - Structured JSON logging (production)
    - Colored console logging (development)
    - Request ID tracking and correlation
    - Access log formatting
    - Sensitive data filtering
    - File handler with rotation
    - Per-module log level control
    - Integration with utils/logging.py

Usage:
    from server.monitoring.logging import (
        configure_server_logging,
        RequestIdMiddleware,
        AccessLogMiddleware,
    )

    # Configure logging
    configure_server_logging(level="INFO", json_format=True)

    # Add middleware
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time
import uuid
from contextvars import ContextVar
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger("agentcrawl.server")


# ══════════════════════════════════════════════════════════════
# Context Variables
# ══════════════════════════════════════════════════════════════

# Request ID for correlation across logs
_request_id: ContextVar[str] = ContextVar("_request_id", default="")


def get_request_id() -> str:
    """Get the current request ID."""
    return _request_id.get()


def set_request_id(request_id: str) -> None:
    """Set the current request ID."""
    _request_id.set(request_id)


# ══════════════════════════════════════════════════════════════
# Logging Configuration
# ══════════════════════════════════════════════════════════════


def configure_server_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: str | None = None,
    max_file_size: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    use_colors: bool = True,
    access_log: bool = True,
) -> None:
    """
    Configure logging for the AgentCrawl server.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: Use JSON structured logging.
        log_file: Optional log file path.
        max_file_size: Max log file size before rotation.
        backup_count: Number of backup files.
        use_colors: Use colored console output.
        access_log: Enable access logging.
    """
    # Resolve level
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Root logger for agentcrawl
    root = logging.getLogger("agentcrawl")
    root.setLevel(log_level)
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)

    if json_format:
        console.setFormatter(ServerJsonFormatter())
    else:
        # Auto-detect TTY
        if use_colors and not sys.stdout.isatty():
            use_colors = False
        console.setFormatter(ServerColoredFormatter(use_colors=use_colors))

    root.addHandler(console)

    # File handler
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(ServerJsonFormatter())
        root.addHandler(file_handler)

    # Suppress noisy libraries
    for lib in ("uvicorn.access", "httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    # Uvicorn access log
    if not access_log:
        logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)

    logger.info(
        "Server logging configured: level=%s, json=%s, file=%s",
        level,
        json_format,
        log_file or "none",
    )


# ══════════════════════════════════════════════════════════════
# Formatters
# ══════════════════════════════════════════════════════════════


class ServerJsonFormatter(logging.Formatter):
    """
    JSON log formatter with request ID correlation.

    Output:
        {"ts": "...", "level": "INFO", "logger": "...",
         "msg": "...", "request_id": "req_abc123"}
    """

    def format(self, record: logging.LogRecord) -> str:
        import json

        entry: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Add request ID
        req_id = _request_id.get()
        if req_id:
            entry["request_id"] = req_id

        # Add exception
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key in ("method", "path", "status_code", "duration_ms", "client_ip"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value

        return json.dumps(entry, ensure_ascii=False, default=str)


class ServerColoredFormatter(logging.Formatter):
    """
    Colored console formatter with request ID.

    Output:
        10:30:00 INFO  [server] Message [req_abc123]
    """

    COLORS: MappingProxyType[str, str] = MappingProxyType(
        {
            "DEBUG": "\033[36m",
            "INFO": "\033[32m",
            "WARNING": "\033[33m",
            "ERROR": "\033[31m",
            "CRITICAL": "\033[35m",
        }
    )
    RESET = "\033[0m"
    DIM = "\033[2m"

    def __init__(self, use_colors: bool = True):
        fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
        super().__init__(fmt=fmt, datefmt="%H:%M:%S")
        self._use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        # Append request ID
        req_id = _request_id.get()
        if req_id:
            record.msg = (
                f"{record.msg} {self.DIM}[{req_id}]{self.RESET if self._use_colors else ''}"
            )

        formatted = super().format(record)

        if self._use_colors:
            color = self.COLORS.get(record.levelname, "")
            if color:
                formatted = f"{color}{formatted}{self.RESET}"

        return formatted


# ══════════════════════════════════════════════════════════════
# Request ID Middleware
# ══════════════════════════════════════════════════════════════


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that assigns a unique request ID to each request.

    The ID is:
        - Read from X-Request-ID header (if provided)
        - Generated as UUID (if not provided)
        - Stored in context var for log correlation
        - Returned in X-Request-ID response header

    Example:
        >>> app.add_middleware(RequestIdMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID", "")
        if not request_id:
            request_id = f"req_{uuid.uuid4().hex[:12]}"

        # Set in context
        set_request_id(request_id)

        # Store on request state
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add to response headers
        response.headers["X-Request-ID"] = request_id

        # Clear context
        set_request_id("")

        return response


# ══════════════════════════════════════════════════════════════
# Access Log Middleware
# ══════════════════════════════════════════════════════════════


class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all HTTP requests in access log format.

    Logs: method, path, status, duration, client IP, request ID.

    Example:
        >>> app.add_middleware(AccessLogMiddleware)
    """

    def __init__(self, app: Any, logger_name: str = "agentcrawl.server.access"):
        super().__init__(app)
        self._logger = logging.getLogger(logger_name)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.perf_counter()

        # Process
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.perf_counter() - start) * 1000

        # Get client IP
        client_ip = "unknown"
        if request.client:
            client_ip = request.client.host

        # Get request ID
        req_id = getattr(request.state, "request_id", "")

        # Log
        self._logger.info(
            "%s %s → %d (%.1fms) [%s] %s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_ip,
            req_id,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": client_ip,
            },
        )

        return response


# ══════════════════════════════════════════════════════════════
# Sensitive Data Filter
# ══════════════════════════════════════════════════════════════


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that masks sensitive data in log messages.

    Masks:
        - API keys (sk-..., agc_..., tvly-...)
        - Bearer tokens
        - Email addresses
        - Passwords in URLs

    Example:
        >>> handler.addFilter(SensitiveDataFilter())
    """

    import re

    PATTERNS: tuple[tuple[Any, str], ...] = (
        # API keys
        (re.compile(r"(sk-)[a-zA-Z0-9]{20,}"), r"\1***MASKED***"),
        (re.compile(r"(agc_live_)[a-zA-Z0-9_-]{20,}"), r"\1***MASKED***"),
        (re.compile(r"(tvly-)[a-zA-Z0-9-]{20,}"), r"\1***MASKED***"),
        # Bearer tokens
        (re.compile(r"(Bearer\s+)[a-zA-Z0-9._-]{20,}"), r"\1***MASKED***"),
        # Email
        (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "***EMAIL***"),
        # Passwords in URLs
        (re.compile(r"(://[^:]+:)[^@]+(@)"), r"\1***\2"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacement in self.PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._mask(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._mask(a) for a in record.args)

        return True

    def _mask(self, value: Any) -> Any:
        """Mask sensitive data in a value."""
        if isinstance(value, str):
            for pattern, replacement in self.PATTERNS:
                value = pattern.sub(replacement, value)
        return value


# ══════════════════════════════════════════════════════════════
# Structured Logger
# ══════════════════════════════════════════════════════════════


class ServerLogger:
    """
    Structured logger with request context.

    Wraps a standard logger and automatically includes
    request ID and other context in all log entries.

    Example:
        >>> log = ServerLogger("agentcrawl.server.scrape")
        >>> log.info("Scraping page", url="https://example.com")
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(
        self,
        level: int,
        msg: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        extra = kwargs.pop("extra", {})

        # Add request ID
        req_id = get_request_id()
        if req_id:
            extra["request_id"] = req_id

        # Add keyword args as extra fields
        for key, value in kwargs.items():
            extra[key] = value

        self._logger.log(level, msg, *args, extra=extra)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs["exc_info"] = True
        self._log(logging.ERROR, msg, *args, **kwargs)
