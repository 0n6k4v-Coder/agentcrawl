"""
AgentCrawl — Hook Type Definitions
======================================

Shared type definitions, protocols, and type aliases for the
hooks module. Provides a single import point for all hook-related
types.

Usage:
    from agentcrawl.hooks.types import (
        HookEvent,
        HookContext,
        HookExecutor,
        HookRegistry,
        HookCallback,
        AsyncHookCallback,
        SyncHookCallback,
        HookCondition,
        HookDecorator,
        hook,
        is_hook_context,
        is_hook_executor,
    )
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import (
    Any,
    Protocol,
    TypeAlias,
    TypedDict,
    TypeGuard,
    runtime_checkable,
)

# ──────────────────────────────────────────────────────────────
# Re-exports from executor
# ──────────────────────────────────────────────────────────────
from agentcrawl.hooks.executor import (
    HookContext,
    HookEvent,
    HookExecutor,
    HookRegistration,
    HookStats,
)

# ──────────────────────────────────────────────────────────────
# Re-exports from registry
# ──────────────────────────────────────────────────────────────
from agentcrawl.hooks.registry import (
    HookMetadata,
    HookRegistry,
    hook,
)

# ══════════════════════════════════════════════════════════════
# Type Aliases
# ══════════════════════════════════════════════════════════════

# Hook callback types
AsyncHookCallback: TypeAlias = Callable[
    [HookContext], Coroutine[Any, Any, None]
]
SyncHookCallback: TypeAlias = Callable[[HookContext], None]
HookCallback: TypeAlias = AsyncHookCallback | SyncHookCallback

# Hook condition function
HookCondition: TypeAlias = Callable[[HookContext], bool]

# Hook decorator type
HookDecorator: TypeAlias = Callable[[HookCallback], HookCallback]

# Hook transform (returns modified context)
AsyncHookTransform: TypeAlias = Callable[
    [HookContext], Coroutine[Any, Any, HookContext | None]
]
SyncHookTransform: TypeAlias = Callable[[HookContext], HookContext | None]
HookTransform: TypeAlias = AsyncHookTransform | SyncHookTransform

# Event name string
EventName: TypeAlias = str

# Group name string
GroupName: TypeAlias = str

# Hook name string
HookName: TypeAlias = str


# ══════════════════════════════════════════════════════════════
# TypedDicts
# ══════════════════════════════════════════════════════════════

class HookConfigDict(TypedDict, total=False):
    """Typed dictionary for hook configuration."""
    event: str
    name: str
    group: str
    priority: int
    description: str
    author: str
    version: str
    tags: list[str]
    dependencies: list[str]
    timeout: float
    continue_on_error: bool
    enabled: bool


class HookInfoDict(TypedDict, total=False):
    """Typed dictionary for hook info (list output)."""
    name: str
    event: str
    group: str
    priority: int
    description: str
    author: str
    version: str
    tags: list[str]
    dependencies: list[str]
    enabled: bool


class HookStatsDict(TypedDict, total=False):
    """Typed dictionary for hook statistics."""
    total_executions: int
    total_errors: int
    total_skipped: int
    total_timeouts: int
    hooks: dict[str, dict[str, Any]]


class RegistryConfigDict(TypedDict, total=False):
    """Typed dictionary for registry serialization."""
    name: str
    hooks: dict[str, dict[str, Any]]
    groups: dict[str, list[str]]
    disabled_groups: list[str]
    disabled_hooks: list[str]


# ══════════════════════════════════════════════════════════════
# Protocols
# ══════════════════════════════════════════════════════════════

@runtime_checkable
class Hookable(Protocol):
    """Protocol for objects that can execute hooks."""

    async def execute(
        self,
        event: HookEvent | str,
        ctx: HookContext,
    ) -> HookContext: ...


@runtime_checkable
class HookRegistrable(Protocol):
    """Protocol for objects that can register hooks."""

    def register(
        self,
        event: HookEvent | str,
        callback: Callable[..., Any],
        **kwargs: Any,
    ) -> None: ...

    def unregister(self, name: str) -> bool: ...


@runtime_checkable
class HookGroupable(Protocol):
    """Protocol for objects that support hook groups."""

    def enable_group(self, group: str) -> int: ...
    def disable_group(self, group: str) -> int: ...


@runtime_checkable
class HookDiscoverable(Protocol):
    """Protocol for objects that can discover hooks."""

    def discover_hooks(self, module_path: str) -> int: ...


# ══════════════════════════════════════════════════════════════
# Type Guards
# ══════════════════════════════════════════════════════════════

def is_hook_context(obj: Any) -> TypeGuard[HookContext]:
    """Check if an object is a HookContext."""
    return (
        hasattr(obj, "url")
        and hasattr(obj, "data")
        and hasattr(obj, "stage")
        and hasattr(obj, "elapsed_ms")
    )


def is_hook_executor(obj: Any) -> TypeGuard[HookExecutor]:
    """Check if an object is a HookExecutor."""
    return (
        hasattr(obj, "execute")
        and hasattr(obj, "register")
        and hasattr(obj, "on")
        and hasattr(obj, "stats")
    )


def is_hook_registry(obj: Any) -> TypeGuard[HookRegistry]:
    """Check if an object is a HookRegistry."""
    return (
        hasattr(obj, "register_hook_function")
        and hasattr(obj, "enable_group")
        and hasattr(obj, "discover_hooks")
        and hasattr(obj, "global_registry")
    )


def is_hook_event(obj: Any) -> TypeGuard[HookEvent]:
    """Check if an object is a HookEvent."""
    return isinstance(obj, HookEvent)


def is_async_hook(callback: Callable) -> bool:
    """Check if a hook callback is async."""
    import asyncio
    return asyncio.iscoroutinefunction(callback)


def is_valid_event_name(name: str) -> bool:
    """Check if a string is a valid hook event name."""
    try:
        HookEvent(name)
        return True
    except ValueError:
        return False


# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════

# All available hook event names
ALL_HOOK_EVENTS: list[str] = [e.value for e in HookEvent]

# Default hook groups
DEFAULT_GROUPS: list[str] = [
    "default",
    "logging",
    "timing",
    "error_handling",
    "analytics",
    "caching",
    "validation",
    "transformation",
]


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

__all__ = [
    # Re-exports
    "HookEvent",
    "HookContext",
    "HookExecutor",
    "HookRegistration",
    "HookStats",
    "HookMetadata",
    "HookRegistry",
    "hook",
    # Type aliases
    "AsyncHookCallback",
    "SyncHookCallback",
    "HookCallback",
    "HookCondition",
    "HookDecorator",
    "AsyncHookTransform",
    "SyncHookTransform",
    "HookTransform",
    "EventName",
    "GroupName",
    "HookName",
    # TypedDicts
    "HookConfigDict",
    "HookInfoDict",
    "HookStatsDict",
    "RegistryConfigDict",
    # Protocols
    "Hookable",
    "HookRegistrable",
    "HookGroupable",
    "HookDiscoverable",
    # Type guards
    "is_hook_context",
    "is_hook_executor",
    "is_hook_registry",
    "is_hook_event",
    "is_async_hook",
    "is_valid_event_name",
    # Constants
    "ALL_HOOK_EVENTS",
    "DEFAULT_GROUPS",
]
