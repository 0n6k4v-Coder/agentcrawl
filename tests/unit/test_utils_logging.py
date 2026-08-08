"""Tests for agentcrawl.utils.logging module."""

import json
import logging
import logging.handlers
import sys
from unittest.mock import MagicMock, patch

import pytest

from agentcrawl.utils.logging import (
    ColoredFormatter,
    ContextFilter,
    JsonFormatter,
    LoggingContext,
    ModuleFilter,
    PerformanceTimer,
    clear_log_context,
    enable_debug_logging,
    get_log_context,
    get_logger,
    log_performance,
    set_log_level,
    setup_logging,
    suppress_logging,
)


class TestLoggingContext:
    """Tests for LoggingContext."""

    def test_context_set_and_get(self):
        with LoggingContext(request_id="req_123"):
            ctx = LoggingContext.get_context()
            assert ctx["request_id"] == "req_123"

    def test_context_cleared_on_exit(self):
        LoggingContext.set_context(request_id="req_123")
        ctx = LoggingContext.get_context()
        assert ctx["request_id"] == "req_123"

        with LoggingContext(request_id="req_456"):
            inner_ctx = LoggingContext.get_context()
            assert inner_ctx["request_id"] == "req_456"
            assert inner_ctx["request_id"] == "req_456"

    def test_nested_context_merges(self):
        with LoggingContext(a="1"), LoggingContext(b="2"):
            ctx = LoggingContext.get_context()
            assert ctx["a"] == "1"
            assert ctx["b"] == "2"

        # After exiting, context should be back to original
        ctx = LoggingContext.get_context()
        assert "a" not in ctx or ctx.get("a") != "1"

    def test_set_context_persists(self):
        LoggingContext.set_context(key="value")
        assert LoggingContext.get_context()["key"] == "value"
        LoggingContext.clear_context()

    def test_clear_context(self):
        LoggingContext.set_context(key="value")
        LoggingContext.clear_context()
        assert LoggingContext.get_context() == {}

    def test_set_context_merges(self):
        LoggingContext.set_context(a="1")
        LoggingContext.set_context(b="2")
        ctx = LoggingContext.get_context()
        assert ctx["a"] == "1"
        assert ctx["b"] == "2"
        LoggingContext.clear_context()

    def test_get_context_no_context(self):
        LoggingContext.clear_context()
        assert LoggingContext.get_context() == {}


class TestJsonFormatter:
    """Tests for JsonFormatter."""

    def _make_record(self, **kwargs):
        exc_info = kwargs.pop("exc_info", None)
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=None,
            exc_info=exc_info,
        )
        for key, value in kwargs.items():
            setattr(record, key, value)
        return record

    def test_basic_format(self):
        formatter = JsonFormatter()
        record = self._make_record()
        result = json.loads(formatter.format(record))
        assert result["level"] == "INFO"
        assert result["logger"] == "test_logger"
        assert result["msg"] == "Test message"
        assert "ts" in result

    def test_include_context(self):
        formatter = JsonFormatter(include_context=True)
        LoggingContext.set_context(request_id="req_123")
        record = self._make_record()
        result = json.loads(formatter.format(record))
        assert result["request_id"] == "req_123"
        LoggingContext.clear_context()

    def test_exclude_context(self):
        formatter = JsonFormatter(include_context=False)
        record = self._make_record()
        result = json.loads(formatter.format(record))
        assert "request_id" not in result

    def test_include_extra(self):
        formatter = JsonFormatter(include_extra=True)
        record = self._make_record()
        record.request_id = "req_test"
        result = json.loads(formatter.format(record))
        assert result["request_id"] == "req_test"

    def test_exclude_extra(self):
        formatter = JsonFormatter(include_extra=False)
        record = self._make_record()
        record.request_id = "req_test"
        result = json.loads(formatter.format(record))
        assert "request_id" not in result

    def test_custom_timestamp_format(self):
        formatter = JsonFormatter(timestamp_format="%Y-%m-%d")
        record = self._make_record()
        result = json.loads(formatter.format(record))
        assert "ts" in result

    def test_exception_info(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = self._make_record(exc_info=sys.exc_info())
        result = json.loads(formatter.format(record))
        assert "exception" in result


class TestColoredFormatter:
    """Tests for ColoredFormatter."""

    def _make_record(self, level=logging.INFO, msg="Test"):
        return logging.LogRecord(
            name="test_logger",
            level=level,
            pathname="",
            lineno=0,
            msg=msg,
            args=None,
            exc_info=None,
        )

    def test_format_basic(self):
        formatter = ColoredFormatter()
        record = self._make_record()
        result = formatter.format(record)
        assert "Test" in result
        assert "INFO" in result

    def test_format_with_colors(self):
        formatter = ColoredFormatter(use_colors=True)
        record = self._make_record(level=logging.INFO)
        result = formatter.format(record)
        assert "\033[0m" in result  # Reset code present

    def test_format_no_colors(self):
        formatter = ColoredFormatter(use_colors=False)
        record = self._make_record(level=logging.INFO)
        result = formatter.format(record)
        assert "\033[0m" not in result

    def test_format_with_context(self):
        formatter = ColoredFormatter()
        with LoggingContext(request_id="req_123"):
            record = self._make_record(msg="Processing")
            result = formatter.format(record)
        assert "request_id=req_123" in result

    def test_warning_color(self):
        formatter = ColoredFormatter(use_colors=True)
        record = self._make_record(level=logging.WARNING)
        result = formatter.format(record)
        assert "\033[33m" in result  # Yellow

    def test_error_color(self):
        formatter = ColoredFormatter(use_colors=True)
        record = self._make_record(level=logging.ERROR)
        result = formatter.format(record)
        assert "\033[31m" in result  # Red

    def test_critical_color(self):
        formatter = ColoredFormatter(use_colors=True)
        record = self._make_record(level=logging.CRITICAL)
        result = formatter.format(record)
        assert "\033[35m" in result  # Magenta

    def test_debug_color(self):
        formatter = ColoredFormatter(use_colors=True)
        record = self._make_record(level=logging.DEBUG)
        result = formatter.format(record)
        assert "\033[36m" in result  # Cyan

    def test_unknown_level_no_color(self):
        formatter = ColoredFormatter(use_colors=True)
        record = self._make_record()
        record.levelname = "UNKNOWN"
        result = formatter.format(record)
        assert "\033[33m" not in result or "\033[0m" in result

    def test_custom_fmt(self):
        formatter = ColoredFormatter(fmt="%(levelname)s - %(message)s")
        record = self._make_record()
        result = formatter.format(record)
        assert "INFO - Test" in result

    def test_custom_datefmt(self):
        formatter = ColoredFormatter(datefmt="%H:%M")
        record = self._make_record()
        result = formatter.format(record)
        assert "Test" in result


class TestContextFilter:
    """Tests for ContextFilter."""

    def test_filter_adds_context(self):
        flt = ContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )
        with LoggingContext(request_id="req_123", url="https://example.com"):
            assert flt.filter(record) is True
            assert record.request_id == "req_123"
            assert record.url == "https://example.com"
        LoggingContext.clear_context()

    def test_filter_no_context(self):
        flt = ContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )
        LoggingContext.clear_context()
        assert flt.filter(record) is True


class TestModuleFilter:
    """Tests for ModuleFilter."""

    def _make_record(self, name="agentcrawl.browser"):
        return logging.LogRecord(
            name=name,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )

    def test_allowed_module(self):
        flt = ModuleFilter(["agentcrawl.browser"])
        assert flt.filter(self._make_record()) is True

    def test_not_allowed_module(self):
        flt = ModuleFilter(["agentcrawl.browser"])
        assert flt.filter(self._make_record("other.module")) is False

    def test_partial_match(self):
        flt = ModuleFilter(["agentcrawl"])
        assert flt.filter(self._make_record("agentcrawl.browser")) is True

    def test_multiple_allowed(self):
        flt = ModuleFilter(["agentcrawl.browser", "agentcrawl.engine"])
        assert flt.filter(self._make_record("agentcrawl.browser")) is True
        assert flt.filter(self._make_record("agentcrawl.engine")) is True
        assert flt.filter(self._make_record("agentcrawl.cache")) is False


class TestSetupLogging:
    """Tests for setup_logging."""

    def test_setup_default(self):
        setup_logging()
        logger = logging.getLogger("agentcrawl")
        assert logger.level == logging.INFO
        assert len(logger.handlers) > 0

    def test_setup_debug_level(self):
        setup_logging(level="DEBUG")
        logger = logging.getLogger("agentcrawl")
        assert logger.level == logging.DEBUG

    def test_setup_json_format(self):
        setup_logging(json_format=True)
        logger = logging.getLogger("agentcrawl")
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_setup_colored_format(self):
        setup_logging(json_format=False)
        logger = logging.getLogger("agentcrawl")
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, ColoredFormatter)

    def test_setup_with_int_level(self):
        setup_logging(level=10)  # DEBUG
        logger = logging.getLogger("agentcrawl")
        assert logger.level == 10

    def test_setup_quiet_modules(self):
        setup_logging(quiet_modules=["some.loud.module"])
        noisy = logging.getLogger("some.loud.module")
        assert noisy.level == logging.WARNING

    def test_setup_suppresses_noisy_libs(self):
        setup_logging()
        for lib in ("httpx", "httpcore", "urllib3", "asyncio"):
            assert logging.getLogger(lib).level == logging.WARNING

    def test_setup_clears_handlers(self):
        setup_logging()
        setup_logging()
        logger = logging.getLogger("agentcrawl")
        # Should still have handlers but not duplicates
        assert len(logger.handlers) >= 1

    def test_setup_with_log_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        setup_logging(log_file=str(log_file))
        logger = logging.getLogger("agentcrawl")
        handler = logger.handlers[-1]
        assert isinstance(handler, logging.handlers.RotatingFileHandler)

    def test_setup_use_colors_no_tty(self):
        with patch.object(sys, "stdout") as mock_stdout:
            mock_stdout.isatty = MagicMock(return_value=False)
            setup_logging(use_colors=True)
            logger = logging.getLogger("agentcrawl")
            handler = logger.handlers[0]
            # Should have disabled colors since not a TTY
            assert isinstance(handler.formatter, ColoredFormatter)
            assert handler.formatter._use_colors is False

    def test_setup_use_colors_tty(self):
        setup_logging(use_colors=True)
        logger = logging.getLogger("agentcrawl")
        handler = logger.handlers[0]
        if sys.stdout.isatty():
            assert isinstance(handler.formatter, ColoredFormatter)
            assert handler.formatter._use_colors is True


class TestGetLogger:
    """Tests for get_logger."""

    def test_get_logger(self):
        logger = get_logger("test.module")
        assert logger.name == "test.module"

    def test_get_logger_returns_logger(self):
        logger = get_logger("agentcrawl.test")
        assert isinstance(logger, logging.Logger)


class TestSetLogLevel:
    """Tests for set_log_level."""

    def test_set_level_string(self):
        set_log_level("DEBUG", "test.logger")
        assert logging.getLogger("test.logger").level == logging.DEBUG

    def test_set_level_int(self):
        set_log_level(logging.ERROR, "test.logger")
        assert logging.getLogger("test.logger").level == logging.ERROR

    def test_set_level_invalid_string(self):
        set_log_level("INVALID_LEVEL", "test.logger")
        assert logging.getLogger("test.logger").level == logging.INFO


class TestSuppressLogging:
    """Tests for suppress_logging."""

    def test_suppress(self):
        suppress_logging("test.quiet.module")
        assert logging.getLogger("test.quiet.module").level == logging.CRITICAL + 1


class TestEnableDebugLogging:
    """Tests for enable_debug_logging."""

    def test_enable_debug(self):
        enable_debug_logging()
        logger = logging.getLogger("agentcrawl")
        assert logger.level == logging.DEBUG


class TestGetLogContext:
    """Tests for get_log_context."""

    def test_get_log_context(self):
        LoggingContext.clear_context()
        assert get_log_context() == {}

    def test_get_log_context_with_values(self):
        with LoggingContext(key="value"):
            ctx = get_log_context()
            assert ctx["key"] == "value"


class TestClearLogContext:
    """Tests for clear_log_context."""

    def test_clear(self):
        LoggingContext.set_context(key="value")
        clear_log_context()
        assert get_log_context() == {}


class TestLogPerformanceSync:
    """Tests for log_performance decorator (sync)."""

    def test_sync_decorator(self):
        calls = []

        @log_performance(logger_name="test.perf", level=logging.DEBUG)
        def func():
            calls.append(1)
            return "result"

        result = func()
        assert result == "result"
        assert len(calls) == 1

    def test_sync_decorator_custom_message(self):
        @log_performance(
            logger_name="test.perf",
            level=logging.DEBUG,
            message="custom_{duration:.2f}ms",
        )
        def func():
            return "ok"

        assert func() == "ok"

    def test_sync_decorator_no_parens(self):
        @log_performance
        def func():
            return "ok"

        assert func() == "ok"

    def test_sync_decorator_exception_propagates(self):
        @log_performance(logger_name="test.perf")
        def func():
            raise ValueError("error")

        with pytest.raises(ValueError, match="error"):
            func()


class TestLogPerformanceAsync:
    """Tests for log_performance decorator (async)."""

    @pytest.mark.asyncio
    async def test_async_decorator(self):
        calls = []

        @log_performance(logger_name="test.perf", level=logging.DEBUG)
        async def func():
            calls.append(1)
            return "result"

        result = await func()
        assert result == "result"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_async_decorator_exception(self):
        @log_performance(logger_name="test.perf")
        async def func():
            raise ValueError("async error")

        with pytest.raises(ValueError, match="async error"):
            await func()

    @pytest.mark.asyncio
    async def test_async_decorator_no_parens(self):
        @log_performance
        async def func():
            return "ok"

        assert await func() == "ok"


class TestPerformanceTimer:
    """Tests for PerformanceTimer."""

    def test_timer_basic(self):
        timer = PerformanceTimer("test_operation")
        with timer:
            pass
        assert timer.duration_ms >= 0

    def test_timer_without_name(self):
        timer = PerformanceTimer()
        with timer:
            pass
        assert timer.duration_ms >= 0

    def test_timer_with_logger(self):
        mock_logger = MagicMock()
        timer = PerformanceTimer("test_op", logger=mock_logger)
        with timer:
            pass
        mock_logger.debug.assert_called_once()

    def test_timer_duration_after_exit(self):
        timer = PerformanceTimer("test")
        with timer:
            import time

            time.sleep(0.001)
        assert timer.duration_ms > 0

    def test_timer_duration_without_exit(self):
        timer = PerformanceTimer("test")
        timer.__enter__()
        assert timer.duration_ms >= 0
        timer.__exit__(None, None, None)
