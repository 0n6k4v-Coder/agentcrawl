"""
AgentCrawl — Hooks Layer
===========================

Event-driven hook system for extending the crawl pipeline at
defined points. Register sync or async callbacks that execute
before/after scraping, extraction, filtering, and more.

Modules:
    executor  — HookExecutor: hook execution engine
    registry  — HookRegistry: central hook management
    types     — Type definitions, protocols, and aliases

Hook Events:
    pre_scrape / post_scrape      — Around page fetching
    pre_extract / post_extract    — Around content extraction
    pre_filter / post_filter      — Around content filtering
    pre_chunk / post_chunk        — Around chunking
    on_error                      — On pipeline errors
    on_complete                   — On pipeline completion
    pre_crawl / post_crawl        — Around crawl jobs
    pre_navigate / post_navigate  — Around page navigation
    pre_action / post_action      — Around page actions

Quick Start:
    from agentcrawl.hooks import HookExecutor, HookEvent, HookContext

    executor = HookExecutor()

    @executor.on(HookEvent.PRE_SCRAPE)
    async def log_url(ctx):
        print(f"Scraping: {ctx.url}")

    @executor.on(HookEvent.POST_SCRAPE, priority=10)
    async def add_timestamp(ctx):
        ctx.data["scraped_at"] = time.time()

    ctx = HookContext(url="https://example.com")
    await executor.execute(HookEvent.PRE_SCRAPE, ctx)

    # Global registry with decorator
    from agentcrawl.hooks import hook, HookRegistry

    @hook(event="pre_scrape", group="logging", priority=10)
    async def my_hook(ctx):
        print(f"Scraping: {ctx.url}")

    registry = HookRegistry.global_registry()
    registry.register_builtins()

    # Group management
    registry.disable_group("analytics")
    registry.enable_group("logging")
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# Executor
# ──────────────────────────────────────────────────────────────
from agentcrawl.hooks.executor import (
    HookContext,
    HookEvent,
    HookExecutor,
    HookRegistration,
    HookStats,
)

# ──────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────
from agentcrawl.hooks.registry import (
    HookMetadata,
    HookRegistry,
    hook,
)

# ──────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────
from agentcrawl.hooks.types import (
    # Constants
    ALL_HOOK_EVENTS,
    DEFAULT_GROUPS,
    # Type aliases
    AsyncHookCallback,
    AsyncHookTransform,
    EventName,
    GroupName,
    # Protocols
    Hookable,
    HookCallback,
    HookCondition,
    # TypedDicts
    HookConfigDict,
    HookDecorator,
    HookDiscoverable,
    HookGroupable,
    HookInfoDict,
    HookName,
    HookRegistrable,
    HookStatsDict,
    HookTransform,
    RegistryConfigDict,
    SyncHookCallback,
    SyncHookTransform,
    # Type guards
    is_async_hook,
    is_hook_context,
    is_hook_event,
    is_hook_executor,
    is_hook_registry,
    is_valid_event_name,
)

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Executor
    "HookExecutor",
    "HookEvent",
    "HookContext",
    "HookRegistration",
    "HookStats",
    # Registry
    "HookRegistry",
    "HookMetadata",
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
