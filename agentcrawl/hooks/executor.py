"""
AgentCrawl — Hook Executor
==============================

Executes registered hooks at defined points in the crawl pipeline.
Supports sync and async hooks, priority ordering, error handling,
conditional execution, and hook chaining.

Hook Events:
    pre_scrape      — Before fetching a page
    post_scrape     — After fetching, before processing
    pre_extract     — Before content extraction
    post_extract    — After content extraction
    pre_filter      — Before content filtering
    post_filter     — After content filtering
    pre_chunk       — Before chunking
    post_chunk      — After chunking
    on_error        — When an error occurs
    on_complete     — When the full pipeline completes
    pre_crawl       — Before a crawl job starts
    post_crawl      — After a crawl job completes

Usage:
    from agentcrawl.hooks.executor import HookExecutor, HookEvent

    executor = HookExecutor()

    # Register hooks
    @executor.on(HookEvent.PRE_SCRAPE)
    async def log_url(ctx):
        print(f"Scraping: {ctx.url}")

    @executor.on(HookEvent.POST_SCRAPE, priority=10)
    async def add_metadata(ctx):
        ctx.data["scraped_at"] = time.time()

    @executor.on(HookEvent.ON_ERROR)
    async def handle_error(ctx):
        logger.error(f"Error: {ctx.error}")

    # Execute hooks
    ctx = HookContext(url="https://example.com")
    await executor.execute(HookEvent.PRE_SCRAPE, ctx)

    # Conditional hooks
    @executor.on(HookEvent.POST_SCRAPE, condition=lambda ctx: ctx.status_code == 200)
    async def only_success(ctx):
        ...
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger("agentcrawl.hooks")


# ══════════════════════════════════════════════════════════════
# Hook Events
# ══════════════════════════════════════════════════════════════

class HookEvent(str, Enum):
    """Available hook event types."""
    PRE_SCRAPE = "pre_scrape"
    POST_SCRAPE = "post_scrape"
    PRE_EXTRACT = "pre_extract"
    POST_EXTRACT = "post_extract"
    PRE_FILTER = "pre_filter"
    POST_FILTER = "post_filter"
    PRE_CHUNK = "pre_chunk"
    POST_CHUNK = "post_chunk"
    ON_ERROR = "on_error"
    ON_COMPLETE = "on_complete"
    PRE_CRAWL = "pre_crawl"
    POST_CRAWL = "post_crawl"
    PRE_NAVIGATE = "pre_navigate"
    POST_NAVIGATE = "post_navigate"
    PRE_ACTION = "pre_action"
    POST_ACTION = "post_action"


# ══════════════════════════════════════════════════════════════
# Hook Context
# ══════════════════════════════════════════════════════════════

@dataclass
class HookContext:
    """
    Shared context passed to all hooks during execution.

    Hooks can read from and write to this context to share
    data across the pipeline.

    Attributes:
        url: The target URL.
        data: Arbitrary data dictionary (mutable, shared across hooks).
        html: Raw HTML content.
        markdown: Markdown content.
        metadata: Page metadata.
        status_code: HTTP status code.
        error: Error message (if any).
        config: CrawlerConfig instance.
        result: CrawlResult instance (post-scrape).
        extra: Additional context data.
        started_at: Unix timestamp when the pipeline started.
        stage: Current pipeline stage name.
    """
    url: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    html: str = ""
    markdown: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    status_code: int = 0
    error: str | None = None
    config: Any = None
    result: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    stage: str = ""

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds since pipeline start."""
        return (time.time() - self.started_at) * 1000

    def set(self, key: str, value: Any) -> None:
        """Set a value in the data dictionary."""
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the data dictionary."""
        return self.data.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "error": self.error,
            "stage": self.stage,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "data_keys": list(self.data.keys()),
        }


# ══════════════════════════════════════════════════════════════
# Hook Registration
# ══════════════════════════════════════════════════════════════

@dataclass
class HookRegistration:
    """
    Internal registration record for a hook.

    Attributes:
        event: Hook event type.
        callback: The hook function.
        name: Hook name (for logging).
        priority: Execution priority (lower = earlier).
        condition: Optional condition function.
        timeout: Timeout in seconds (0 = no timeout).
        continue_on_error: Whether to continue on hook error.
        enabled: Whether the hook is enabled.
    """
    event: HookEvent
    callback: Callable[..., Any]
    name: str = ""
    priority: int = 100
    condition: Callable[[HookContext], bool] | None = None
    timeout: float = 0.0
    continue_on_error: bool = True
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            self.name = getattr(self.callback, "__name__", "anonymous_hook")


# ══════════════════════════════════════════════════════════════
# Hook Statistics
# ══════════════════════════════════════════════════════════════

@dataclass
class HookStats:
    """Statistics for hook execution."""
    total_executions: int = 0
    total_errors: int = 0
    total_skipped: int = 0
    total_timeouts: int = 0
    execution_times: dict[str, list[float]] = field(default_factory=dict)

    def record(self, hook_name: str, duration_ms: float, error: bool = False) -> None:
        self.total_executions += 1
        if error:
            self.total_errors += 1
        if hook_name not in self.execution_times:
            self.execution_times[hook_name] = []
        self.execution_times[hook_name].append(duration_ms)

    def record_skip(self) -> None:
        self.total_skipped += 1

    def record_timeout(self) -> None:
        self.total_timeouts += 1

    def avg_time(self, hook_name: str) -> float:
        times = self.execution_times.get(hook_name, [])
        return sum(times) / max(len(times), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_executions": self.total_executions,
            "total_errors": self.total_errors,
            "total_skipped": self.total_skipped,
            "total_timeouts": self.total_timeouts,
            "hooks": {
                name: {
                    "executions": len(times),
                    "avg_ms": round(sum(times) / max(len(times), 1), 2),
                    "max_ms": round(max(times), 2) if times else 0,
                }
                for name, times in self.execution_times.items()
            },
        }


# ══════════════════════════════════════════════════════════════
# Hook Executor
# ══════════════════════════════════════════════════════════════

class HookExecutor:
    """
    Manages and executes hooks at defined pipeline events.

    Supports sync and async hooks, priority ordering, conditional
    execution, timeouts, and error handling.

    Args:
        continue_on_error: Default behavior when a hook fails.
        default_timeout: Default timeout per hook in seconds.
        enable_stats: Whether to track execution statistics.

    Example:
        >>> executor = HookExecutor()
        >>>
        >>> @executor.on(HookEvent.PRE_SCRAPE)
        ... async def log_url(ctx):
        ...     print(f"Scraping: {ctx.url}")
        ...
        >>> ctx = HookContext(url="https://example.com")
        >>> await executor.execute(HookEvent.PRE_SCRAPE, ctx)
    """

    def __init__(
        self,
        continue_on_error: bool = True,
        default_timeout: float = 30.0,
        enable_stats: bool = True,
    ):
        self._hooks: dict[HookEvent, list[HookRegistration]] = {
            event: [] for event in HookEvent
        }
        self._continue_on_error = continue_on_error
        self._default_timeout = default_timeout
        self._enable_stats = enable_stats
        self._stats = HookStats()

    # ──────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────

    def on(
        self,
        event: HookEvent | str,
        priority: int = 100,
        condition: Callable[[HookContext], bool] | None = None,
        timeout: float = 0.0,
        continue_on_error: bool | None = None,
        name: str = "",
    ) -> Callable:
        """
        Decorator to register a hook for an event.

        Args:
            event: Hook event type.
            priority: Execution priority (lower = earlier).
            condition: Optional condition function.
            timeout: Timeout in seconds (0 = use default).
            continue_on_error: Override default error behavior.
            name: Hook name (for logging).

        Returns:
            Decorator function.

        Example:
            >>> @executor.on(HookEvent.PRE_SCRAPE, priority=10)
            ... async def my_hook(ctx):
            ...     print(f"Pre-scrape: {ctx.url}")
        """
        if isinstance(event, str):
            event = HookEvent(event)

        def decorator(func: Callable) -> Callable:
            self.register(
                event=event,
                callback=func,
                priority=priority,
                condition=condition,
                timeout=timeout,
                continue_on_error=continue_on_error,
                name=name or func.__name__,
            )
            return func

        return decorator

    def register(
        self,
        event: HookEvent | str,
        callback: Callable,
        priority: int = 100,
        condition: Callable[[HookContext], bool] | None = None,
        timeout: float = 0.0,
        continue_on_error: bool | None = None,
        name: str = "",
    ) -> None:
        """
        Register a hook programmatically.

        Args:
            event: Hook event type.
            callback: Hook function (sync or async).
            priority: Execution priority.
            condition: Optional condition function.
            timeout: Timeout in seconds.
            continue_on_error: Error behavior override.
            name: Hook name.
        """
        if isinstance(event, str):
            event = HookEvent(event)

        registration = HookRegistration(
            event=event,
            callback=callback,
            name=name or getattr(callback, "__name__", "anonymous"),
            priority=priority,
            condition=condition,
            timeout=timeout or self._default_timeout,
            continue_on_error=(
                continue_on_error
                if continue_on_error is not None
                else self._continue_on_error
            ),
        )

        self._hooks[event].append(registration)
        # Sort by priority
        self._hooks[event].sort(key=lambda h: h.priority)

        logger.debug(
            "Registered hook '%s' for event '%s' (priority=%d)",
            registration.name,
            event.value,
            priority,
        )

    def unregister(self, event: HookEvent | str, name: str) -> bool:
        """
        Unregister a hook by name.

        Args:
            event: Hook event type.
            name: Hook name.

        Returns:
            True if the hook was found and removed.
        """
        if isinstance(event, str):
            event = HookEvent(event)

        hooks = self._hooks[event]
        for i, hook in enumerate(hooks):
            if hook.name == name:
                hooks.pop(i)
                return True
        return False

    def clear(self, event: HookEvent | str | None = None) -> None:
        """
        Clear hooks for an event (or all events).

        Args:
            event: Event to clear, or None for all.
        """
        if event is None:
            for evt in HookEvent:
                self._hooks[evt].clear()
        else:
            if isinstance(event, str):
                event = HookEvent(event)
            self._hooks[event].clear()

    def enable(self, event: HookEvent | str, name: str) -> bool:
        """Enable a disabled hook."""
        if isinstance(event, str):
            event = HookEvent(event)
        for hook in self._hooks[event]:
            if hook.name == name:
                hook.enabled = True
                return True
        return False

    def disable(self, event: HookEvent | str, name: str) -> bool:
        """Disable a hook without removing it."""
        if isinstance(event, str):
            event = HookEvent(event)
        for hook in self._hooks[event]:
            if hook.name == name:
                hook.enabled = False
                return True
        return False

    # ──────────────────────────────────────────────────────────
    # Execution
    # ──────────────────────────────────────────────────────────

    async def execute(
        self,
        event: HookEvent | str,
        ctx: HookContext,
    ) -> HookContext:
        """
        Execute all hooks registered for an event.

        Hooks are executed in priority order (lower = earlier).
        Each hook receives the shared HookContext.

        Args:
            event: Hook event type.
            ctx: Hook context.

        Returns:
            The (possibly modified) HookContext.
        """
        if isinstance(event, str):
            event = HookEvent(event)

        hooks = self._hooks.get(event, [])
        if not hooks:
            return ctx

        ctx.stage = event.value

        for hook in hooks:
            if not hook.enabled:
                if self._enable_stats:
                    self._stats.record_skip()
                continue

            # Check condition
            if hook.condition is not None:
                try:
                    if not hook.condition(ctx):
                        if self._enable_stats:
                            self._stats.record_skip()
                        continue
                except Exception as e:
                    logger.debug(
                        "Hook '%s' condition error: %s",
                        hook.name, e,
                    )
                    continue

            # Execute hook
            await self._execute_hook(hook, ctx)

        return ctx

    async def _execute_hook(
        self,
        hook: HookRegistration,
        ctx: HookContext,
    ) -> None:
        """
        Execute a single hook with timeout and error handling.

        Args:
            hook: Hook registration.
            ctx: Hook context.
        """
        start = time.perf_counter()

        try:
            # Execute with timeout
            if asyncio.iscoroutinefunction(hook.callback):
                coro = hook.callback(ctx)
                if hook.timeout > 0:
                    await asyncio.wait_for(coro, timeout=hook.timeout)
                else:
                    await coro
            else:
                # Sync hook — run in executor
                loop = asyncio.get_event_loop()
                if hook.timeout > 0:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, hook.callback, ctx),
                        timeout=hook.timeout,
                    )
                else:
                    await loop.run_in_executor(None, hook.callback, ctx)

            duration = (time.perf_counter() - start) * 1000
            if self._enable_stats:
                self._stats.record(hook.name, duration)

            logger.debug(
                "Hook '%s' completed in %.1fms",
                hook.name, duration,
            )

        except asyncio.TimeoutError:
            duration = (time.perf_counter() - start) * 1000
            if self._enable_stats:
                self._stats.record_timeout()
                self._stats.record(hook.name, duration, error=True)
            logger.warning(
                "Hook '%s' timed out after %.0fms",
                hook.name, duration,
            )

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            if self._enable_stats:
                self._stats.record(hook.name, duration, error=True)
            logger.warning(
                "Hook '%s' failed: %s",
                hook.name, e,
            )

            if not hook.continue_on_error:
                raise

    async def execute_chain(
        self,
        event: HookEvent | str,
        ctx: HookContext,
        stop_on_none: bool = False,
    ) -> HookContext:
        """
        Execute hooks in chain mode — each hook's return value
        is passed as input to the next hook.

        Args:
            event: Hook event type.
            ctx: Hook context.
            stop_on_none: Stop chain if a hook returns None.

        Returns:
            Final HookContext.
        """
        if isinstance(event, str):
            event = HookEvent(event)

        hooks = self._hooks.get(event, [])
        ctx.stage = event.value

        current_input: Any = ctx

        for hook in hooks:
            if not hook.enabled:
                continue

            if hook.condition is not None:
                try:
                    if not hook.condition(ctx):
                        continue
                except Exception:
                    continue

            try:
                if asyncio.iscoroutinefunction(hook.callback):
                    result = await hook.callback(current_input)
                else:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, hook.callback, current_input
                    )

                if result is not None:
                    current_input = result
                elif stop_on_none:
                    break

            except Exception as e:
                logger.warning("Chain hook '%s' failed: %s", hook.name, e)
                if not hook.continue_on_error:
                    raise

        return ctx

    # ──────────────────────────────────────────────────────────
    # Query
    # ──────────────────────────────────────────────────────────

    def get_hooks(self, event: HookEvent | str) -> list[HookRegistration]:
        """Get all hooks registered for an event."""
        if isinstance(event, str):
            event = HookEvent(event)
        return list(self._hooks.get(event, []))

    def has_hooks(self, event: HookEvent | str) -> bool:
        """Check if any hooks are registered for an event."""
        if isinstance(event, str):
            event = HookEvent(event)
        return len(self._hooks.get(event, [])) > 0

    def hook_count(self, event: HookEvent | str | None = None) -> int:
        """Get the number of registered hooks."""
        if event is None:
            return sum(len(hooks) for hooks in self._hooks.values())
        if isinstance(event, str):
            event = HookEvent(event)
        return len(self._hooks.get(event, []))

    @property
    def stats(self) -> HookStats:
        """Hook execution statistics."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset execution statistics."""
        self._stats = HookStats()

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get executor diagnostics."""
        hooks_by_event: dict[str, list[dict[str, Any]]] = {}

        for event, hooks in self._hooks.items():
            if hooks:
                hooks_by_event[event.value] = [
                    {
                        "name": h.name,
                        "priority": h.priority,
                        "enabled": h.enabled,
                        "timeout": h.timeout,
                        "has_condition": h.condition is not None,
                    }
                    for h in hooks
                ]

        return {
            "total_hooks": self.hook_count(),
            "hooks_by_event": hooks_by_event,
            "stats": self._stats.to_dict() if self._enable_stats else {},
            "continue_on_error": self._continue_on_error,
            "default_timeout": self._default_timeout,
        }

    def __repr__(self) -> str:
        return (
            f"HookExecutor(hooks={self.hook_count()}, "
            f"continue_on_error={self._continue_on_error})"
        )