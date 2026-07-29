"""
AgentCrawl — Logging Utilities
==================================

Structured logging setup with JSON and colored console formatters,
context-aware logging, and performance tracking.

Features:
    - Structured JSON logging (for production)
    - Colored console logging (for development)
    - Context-aware logging (request ID, URL, session)
    - Performance logging decorator
    - File handler with rotation
    - Log level configuration
    - Module-level logger factory

Usage:
    from agentcrawl.utils.logging import (
        setup_logging,
        get_logger,
        log_performance,
        LoggingContext,
    )

    # Setup logging
    setup_logging(level="INFO", json_format=False)

    # Get a logger
    logger = get_logger("agentcrawl.browser")
    logger.info("Browser started")

    # With context
    with LoggingContext(request_id="req_abc123", url="https://example.com"):
        logger.info("Scraping page")
        # → {"message": "Scraping page", "request_id": "req_abc123", "url": "..."}

    # Performance decorator
    @log_performance
    async def my_function():
        ...
"""

from __future__ import annotations

import functools
import json
import logging
import logging.handlers
import sys
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

# ══════════════════════════════════════════════════════════════
# Context Variables
# ══════════════════════════════════════════════════════════════

# Thread/task-local context for structured logging
_log_context: ContextVar[dict[str, Any]] = ContextVar("_log_context", default={})


# ══════════════════════════════════════════════════════════════
# Logging Context Manager
# ══════════════════════════════════════════════════════════════

class LoggingContext:
    """
    Context manager for adding structured context to log records.

    Sets context variables that are automatically included in
    all log records within the context.

    Args:
        **kwargs: Context key-value pairs (e.g., request_id, url).

    Example:
        >>> with LoggingContext(request_id="req_123", url="https://example.com"):
        ...     logger.info("Processing")
        ...     # Log includes: {"request_id": "req_123", "url": "https://example.com"}
    """

    def __init__(self, **kwargs: Any):
        self._kwargs = kwargs
        self._token: Any = None

    def __enter__(self) -> LoggingContext:
        current = _log_context.get()
        merged = {**current, **self._kwargs}
        self._token = _log_context.set(merged)
        return self

    def __exit__(self, *args: Any) -> None:
        if self._token is not None:
            _log_context.reset(self._token)

    @staticmethod
    def get_context() -> dict[str, Any]:
        """Get the current logging context."""
        return dict(_log_context.get())

    @staticmethod
    def set_context(**kwargs: Any) -> None:
        """Set context values (persists until cleared)."""
        current = _log_context.get()
        _log_context.set({**current, **kwargs})

    @staticmethod
    def clear_context() -> None:
        """Clear all context values."""
        _log_context.set({})


# ══════════════════════════════════════════════════════════════
# Formatters
# ══════════════════════════════════════════════════════════════

class JsonFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.

    Outputs each log record as a single JSON line with
    timestamp, level, message, logger name, and context.

    Example output:
        {"ts": "2025-01-15T10:30:00.123Z", "level": "INFO",
         "logger": "agentcrawl.browser", "msg": "Started",
         "request_id": "req_abc"}
    """

    def __init__(
        self,
        include_context: bool = True,
        include_extra: bool = True,
        timestamp_format: str = "%Y-%m-%dT%H:%M:%S.%f",
    ):
        super().__init__()
        self._include_context = include_context
        self._include_extra = include_extra
        self._timestamp_format = timestamp_format

    def format(self, record: logging.LogRecord) -> str:
        # Build log entry
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, self._timestamp_format),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Add exception info
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        # Add logging context
        if self._include_context:
            ctx = _log_context.get()
            if ctx:
                entry.update(ctx)

        # Add extra fields
        if self._include_extra:
            for key in ("request_id", "url", "session_id", "job_id", "duration_ms"):
                value = getattr(record, key, None)
                if value is not None:
                    entry[key] = value

        return json.dumps(entry, ensure_ascii=False, default=str)


class ColoredFormatter(logging.Formatter):
    """
    Colored console formatter for development.

    Adds ANSI color codes based on log level.

    Example output:
        10:30:00 INFO  [browser] Started
        10:30:01 ERROR [engine] Failed: timeout
    """

    # ANSI color codes
    COLORS: dict[str, str] = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        use_colors: bool = True,
    ):
        if fmt is None:
            fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
        if datefmt is None:
            datefmt = "%H:%M:%S"

        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        # Add context to message
        ctx = _log_context.get()
        if ctx:
            ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items())
            record.msg = f"{record.msg} ({ctx_str})"

        formatted = super().format(record)

        if self._use_colors:
            color = self.COLORS.get(record.levelname, "")
            if color:
                formatted = f"{color}{formatted}{self.RESET}"

        return formatted


# ══════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════

class ContextFilter(logging.Filter):
    """
    Log filter that injects context variables into log records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _log_context.get()
        for key, value in ctx.items():
            setattr(record, key, value)
        return True


class ModuleFilter(logging.Filter):
    """
    Log filter that only allows records from specific modules.
    """

    def __init__(self, allowed_modules: list[str]):
        super().__init__()
        self._allowed = allowed_modules

    def filter(self, record: logging.LogRecord) -> bool:
        return any(
            record.name.startswith(module)
            for module in self._allowed
        )


# ══════════════════════════════════════════════════════════════
# Setup
# ══════════════════════════════════════════════════════════════

def setup_logging(
    level: str | int = "INFO",
    json_format: bool = False,
    log_file: str | None = None,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    use_colors: bool = True,
    include_context: bool = True,
    quiet_modules: list[str] | None = None,
) -> None:
    """
    Configure logging for AgentCrawl.

    Args:
        level: Log level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
        json_format: Use JSON formatter (for production).
        log_file: Optional log file path.
        max_file_size: Maximum log file size before rotation.
        backup_count: Number of backup files to keep.
        use_colors: Use colored output (disable for non-TTY).
        include_context: Include context variables in logs.
        quiet_modules: Modules to suppress (set to WARNING).

    Example:
        >>> setup_logging(level="DEBUG", json_format=False)
        >>> setup_logging(level="INFO", json_format=True, log_file="app.log")
    """
    # Resolve level
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Root logger
    root_logger = logging.getLogger("agentcrawl")
    root_logger.setLevel(level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if json_format:
        console_handler.setFormatter(
            JsonFormatter(include_context=include_context)
        )
    else:
        # Auto-detect TTY for colors
        if use_colors and not sys.stdout.isatty():
            use_colors = False
        console_handler.setFormatter(
            ColoredFormatter(use_colors=use_colors)
        )

    # Add context filter
    console_handler.addFilter(ContextFilter())
    root_logger.addHandler(console_handler)

    # File handler (with rotation)
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(
            JsonFormatter(include_context=include_context)
        )
        file_handler.addFilter(ContextFilter())
        root_logger.addHandler(file_handler)

    # Quiet noisy modules
    if quiet_modules:
        for module in quiet_modules:
            logging.getLogger(module).setLevel(logging.WARNING)

    # Suppress common noisy libraries
    for lib in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name (usually __name__).

    Returns:
        Logger instance.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Hello")
    """
    return logging.getLogger(name)


# ══════════════════════════════════════════════════════════════
# Performance Logging
# ══════════════════════════════════════════════════════════════

def log_performance(
    func: Callable | None = None,
    *,
    logger_name: str | None = None,
    level: int = logging.DEBUG,
    message: str | None = None,
) -> Callable:
    """
    Decorator to log function execution time.

    Works with both sync and async functions.

    Args:
        func: Function to decorate.
        logger_name: Logger name (uses function module if None).
        level: Log level for the performance message.
        message: Custom message template.

    Returns:
        Decorated function.

    Example:
        >>> @log_performance
        ... async def fetch_page(url):
        ...     ...
        # → DEBUG [module] fetch_page completed in 123.45ms
    """
    def decorator(fn: Callable) -> Callable:
        _logger_name = logger_name or fn.__module__
        _logger = logging.getLogger(_logger_name)
        _message = message or f"{fn.__name__} completed in {{duration:.2f}}ms"

        if _is_async(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                    duration = (time.perf_counter() - start) * 1000
                    _logger.log(level, _message.format(duration=duration))
                    return result
                except Exception as e:
                    duration = (time.perf_counter() - start) * 1000
                    _logger.log(
                        level,
                        f"{fn.__name__} failed after {duration:.2f}ms: {e}",
                    )
                    raise
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                    duration = (time.perf_counter() - start) * 1000
                    _logger.log(level, _message.format(duration=duration))
                    return result
                except Exception as e:
                    duration = (time.perf_counter() - start) * 1000
                    _logger.log(
                        level,
                        f"{fn.__name__} failed after {duration:.2f}ms: {e}",
                    )
                    raise
            return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


class PerformanceTimer:
    """
    Context manager for timing code blocks.

    Example:
        >>> with PerformanceTimer("page_load") as timer:
        ...     await page.goto(url)
        >>> print(f"Took {timer.duration_ms:.1f}ms")
    """

    def __init__(self, name: str = "", logger: logging.Logger | None = None):
        self._name = name
        self._logger = logger
        self._start: float = 0.0
        self._end: float = 0.0

    @property
    def duration_ms(self) -> float:
        """Elapsed time in milliseconds."""
        if self._end > 0:
            return (self._end - self._start) * 1000
        return (time.perf_counter() - self._start) * 1000

    def __enter__(self) -> PerformanceTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self._end = time.perf_counter()
        if self._logger and self._name:
            self._logger.debug(
                "%s completed in %.2fms",
                self._name,
                self.duration_ms,
            )


# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

def _is_async(func: Callable) -> bool:
    """Check if a function is async."""
    import asyncio
    return asyncio.iscoroutinefunction(func)


def set_log_level(level: str | int, logger_name: str = "agentcrawl") -> None:
    """
    Change the log level at runtime.

    Args:
        level: New log level.
        logger_name: Logger name to change.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logging.getLogger(logger_name).setLevel(level)


def suppress_logging(logger_name: str) -> None:
    """Suppress all logging from a specific logger."""
    logging.getLogger(logger_name).setLevel(logging.CRITICAL + 1)


def enable_debug_logging() -> None:
    """Enable debug logging for all AgentCrawl modules."""
    setup_logging(level="DEBUG")


def get_log_context() -> dict[str, Any]:
    """Get the current logging context."""
    return LoggingContext.get_context()


def clear_log_context() -> None:
    """Clear the current logging context."""
    LoggingContext.clear_context()
