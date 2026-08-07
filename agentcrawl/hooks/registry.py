"""
AgentCrawl — Hook Registry
==============================

Central registry for managing hook registrations across the
application. Supports global and per-engine registries, hook
grouping, dependency management, and auto-discovery.

Features:
    - Global singleton registry
    - Per-engine isolated registries
    - Hook grouping (enable/disable by group)
    - Hook metadata (description, author, version)
    - Hook dependencies (ordering constraints)
    - Auto-discovery from modules
    - Built-in hooks (logging, timing, error handling)
    - Serialization (save/load configurations)

Usage:
    from agentcrawl.hooks.registry import HookRegistry, hook

    # Global registry
    registry = HookRegistry.global_registry()

    # Register with decorator
    @hook(event="pre_scrape", group="logging", priority=10)
    async def log_scrape(ctx):
        print(f"Scraping: {ctx.url}")

    # Register with metadata
    @hook(
        event="post_scrape",
        group="analytics",
        description="Track scrape metrics",
        author="team",
        version="1.0",
    )
    async def track_metrics(ctx):
        ...

    # Enable/disable groups
    registry.disable_group("analytics")
    registry.enable_group("logging")

    # Create per-engine registry
    engine_registry = HookRegistry()
    engine_registry.register_all_from(registry)

    # Built-in hooks
    registry.register_builtins()
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentcrawl.hooks.executor import (
    HookContext,
    HookEvent,
    HookExecutor,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("agentcrawl.hooks.registry")


# ══════════════════════════════════════════════════════════════
# Hook Metadata
# ══════════════════════════════════════════════════════════════


@dataclass
class HookMetadata:
    """
    Metadata about a registered hook.

    Attributes:
        name: Hook name.
        event: Hook event type.
        group: Hook group name.
        description: Human-readable description.
        author: Hook author.
        version: Hook version.
        tags: Arbitrary tags for categorization.
        dependencies: Names of hooks that must run before this one.
    """

    name: str = ""
    event: str = ""
    group: str = "default"
    description: str = ""
    author: str = ""
    version: str = "1.0"
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "event": self.event,
            "group": self.group,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
            "dependencies": self.dependencies,
        }


# ══════════════════════════════════════════════════════════════
# Hook Decorator
# ══════════════════════════════════════════════════════════════


def hook(
    event: str | HookEvent,
    group: str = "default",
    priority: int = 100,
    description: str = "",
    author: str = "",
    version: str = "1.0",
    tags: list[str] | None = None,
    dependencies: list[str] | None = None,
    condition: Callable[[HookContext], bool] | None = None,
    timeout: float = 0.0,
    continue_on_error: bool = True,
) -> Callable[..., Any]:
    """
    Decorator to mark a function as a hook and register it
    with the global registry.

    Args:
        event: Hook event type.
        group: Hook group name.
        priority: Execution priority (lower = earlier).
        description: Human-readable description.
        author: Hook author.
        version: Hook version.
        tags: Arbitrary tags.
        dependencies: Names of hooks that must run first.
        condition: Optional condition function.
        timeout: Timeout in seconds.
        continue_on_error: Whether to continue on error.

    Returns:
        Decorator function.

    Example:
        >>> @hook(event="pre_scrape", group="logging", priority=10)
        ... async def log_scrape(ctx):
        ...     print(f"Scraping: {ctx.url}")
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # Attach metadata to the function
        func._hook_metadata = HookMetadata(  # type: ignore[attr-defined]
            name=func.__name__,
            event=event.value if isinstance(event, HookEvent) else event,
            group=group,
            description=description,
            author=author,
            version=version,
            tags=tags or [],
            dependencies=dependencies or [],
        )
        func._hook_config = {  # type: ignore[attr-defined]
            "event": event,
            "priority": priority,
            "condition": condition,
            "timeout": timeout,
            "continue_on_error": continue_on_error,
        }

        # Register with global registry
        registry = HookRegistry.global_registry()
        registry.register_hook_function(func)

        return func

    return decorator


# ══════════════════════════════════════════════════════════════
# Hook Registry
# ══════════════════════════════════════════════════════════════


class HookRegistry:
    """
    Central registry for managing hook registrations.

    Supports global and per-engine registries, hook grouping,
    dependency management, and auto-discovery.

    Args:
        name: Registry name (for logging).
        executor: HookExecutor instance (created if None).

    Example:
        >>> registry = HookRegistry.global_registry()
        >>> registry.register_builtins()
        >>> registry.disable_group("analytics")
        >>> print(registry.list_hooks())
    """

    _global_instance: HookRegistry | None = None

    def __init__(
        self,
        name: str = "default",
        executor: HookExecutor | None = None,
    ):
        self._name = name
        self._executor = executor or HookExecutor()
        self._metadata: dict[str, HookMetadata] = {}
        self._groups: dict[str, set[str]] = {}  # group → hook names
        self._disabled_groups: set[str] = set()
        self._disabled_hooks: set[str] = set()

    # ──────────────────────────────────────────────────────────
    # Singleton
    # ──────────────────────────────────────────────────────────

    @classmethod
    def global_registry(cls) -> HookRegistry:
        """
        Get the global singleton registry.

        Returns:
            Global HookRegistry instance.
        """
        if cls._global_instance is None:
            cls._global_instance = cls(name="global")
        return cls._global_instance

    @classmethod
    def reset_global(cls) -> None:
        """Reset the global registry (for testing)."""
        cls._global_instance = None

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Registry name."""
        return self._name

    @property
    def executor(self) -> HookExecutor:
        """The underlying HookExecutor."""
        return self._executor

    @property
    def groups(self) -> list[str]:
        """All registered group names."""
        return list(self._groups.keys())

    @property
    def disabled_groups(self) -> set[str]:
        """Currently disabled groups."""
        return set(self._disabled_groups)

    # ──────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────

    def register_hook_function(self, func: Callable[..., Any]) -> None:
        """
        Register a function that has been decorated with @hook.

        Args:
            func: Decorated hook function.
        """
        metadata: HookMetadata | None = getattr(func, "_hook_metadata", None)
        config: dict[str, Any] | None = getattr(func, "_hook_config", None)

        if metadata is None or config is None:
            logger.warning(
                "Function '%s' is not decorated with @hook",
                getattr(func, "__name__", "unknown"),
            )
            return

        event = config["event"]
        if isinstance(event, str):
            event = HookEvent(event)

        # Register with executor
        self._executor.register(
            event=event,
            callback=func,
            priority=config.get("priority", 100),
            condition=config.get("condition"),
            timeout=config.get("timeout", 0.0),
            continue_on_error=config.get("continue_on_error", True),
            name=metadata.name,
        )

        # Store metadata
        self._metadata[metadata.name] = metadata

        # Track group
        group = metadata.group
        if group not in self._groups:
            self._groups[group] = set()
        self._groups[group].add(metadata.name)

        logger.debug(
            "Registered hook '%s' (event=%s, group=%s, priority=%d)",
            metadata.name,
            event.value,
            group,
            config.get("priority", 100),
        )

    def register(
        self,
        event: HookEvent | str,
        callback: Callable[..., Any],
        name: str = "",
        group: str = "default",
        priority: int = 100,
        description: str = "",
        author: str = "",
        version: str = "1.0",
        tags: list[str] | None = None,
        dependencies: list[str] | None = None,
        condition: Callable[[HookContext], bool] | None = None,
        timeout: float = 0.0,
        continue_on_error: bool = True,
    ) -> None:
        """
        Register a hook programmatically with full metadata.

        Args:
            event: Hook event type.
            callback: Hook function.
            name: Hook name.
            group: Hook group.
            priority: Execution priority.
            description: Description.
            author: Author.
            version: Version.
            tags: Tags.
            dependencies: Dependency hook names.
            condition: Condition function.
            timeout: Timeout in seconds.
            continue_on_error: Error behavior.
        """
        hook_name = name or getattr(callback, "__name__", "anonymous")

        # Register with executor
        self._executor.register(
            event=event,
            callback=callback,
            priority=priority,
            condition=condition,
            timeout=timeout,
            continue_on_error=continue_on_error,
            name=hook_name,
        )

        # Store metadata
        event_str = event.value if isinstance(event, HookEvent) else event
        self._metadata[hook_name] = HookMetadata(
            name=hook_name,
            event=event_str,
            group=group,
            description=description,
            author=author,
            version=version,
            tags=tags or [],
            dependencies=dependencies or [],
        )

        # Track group
        if group not in self._groups:
            self._groups[group] = set()
        self._groups[group].add(hook_name)

    def unregister(self, name: str) -> bool:
        """
        Unregister a hook by name from all events.

        Args:
            name: Hook name.

        Returns:
            True if the hook was found and removed.
        """
        metadata = self._metadata.get(name)
        if metadata is None:
            return False

        event = HookEvent(metadata.event)
        removed = self._executor.unregister(event, name)

        if removed:
            del self._metadata[name]
            # Remove from group
            group = metadata.group
            if group in self._groups:
                self._groups[group].discard(name)

        return removed

    def register_all_from(self, other: HookRegistry) -> int:
        """
        Copy all hook registrations from another registry.

        Args:
            other: Source registry.

        Returns:
            Number of hooks copied.
        """
        count = 0
        for name, metadata in other._metadata.items():
            if name in self._metadata:
                continue  # Skip duplicates

            # Get hooks from the other executor
            event = HookEvent(metadata.event)
            hooks = other._executor.get_hooks(event)

            for hook_reg in hooks:
                if hook_reg.name == name:
                    self._executor.register(
                        event=event,
                        callback=hook_reg.callback,
                        priority=hook_reg.priority,
                        condition=hook_reg.condition,
                        timeout=hook_reg.timeout,
                        continue_on_error=hook_reg.continue_on_error,
                        name=name,
                    )
                    self._metadata[name] = metadata

                    group = metadata.group
                    if group not in self._groups:
                        self._groups[group] = set()
                    self._groups[group].add(name)

                    count += 1
                    break

        return count

    # ──────────────────────────────────────────────────────────
    # Group Management
    # ──────────────────────────────────────────────────────────

    def enable_group(self, group: str) -> int:
        """
        Enable all hooks in a group.

        Args:
            group: Group name.

        Returns:
            Number of hooks enabled.
        """
        self._disabled_groups.discard(group)
        hook_names = self._groups.get(group, set())

        count = 0
        for name in hook_names:
            metadata = self._metadata.get(name)
            if metadata:
                event = HookEvent(metadata.event)
                if self._executor.enable(event, name):
                    count += 1

        return count

    def disable_group(self, group: str) -> int:
        """
        Disable all hooks in a group.

        Args:
            group: Group name.

        Returns:
            Number of hooks disabled.
        """
        self._disabled_groups.add(group)
        hook_names = self._groups.get(group, set())

        count = 0
        for name in hook_names:
            metadata = self._metadata.get(name)
            if metadata:
                event = HookEvent(metadata.event)
                if self._executor.disable(event, name):
                    count += 1

        return count

    def enable_hook(self, name: str) -> bool:
        """Enable a specific hook."""
        self._disabled_hooks.discard(name)
        metadata = self._metadata.get(name)
        if metadata:
            event = HookEvent(metadata.event)
            return self._executor.enable(event, name)
        return False

    def disable_hook(self, name: str) -> bool:
        """Disable a specific hook."""
        self._disabled_hooks.add(name)
        metadata = self._metadata.get(name)
        if metadata:
            event = HookEvent(metadata.event)
            return self._executor.disable(event, name)
        return False

    # ──────────────────────────────────────────────────────────
    # Discovery
    # ──────────────────────────────────────────────────────────

    def discover_hooks(self, module_path: str = "agentcrawl.hooks.builtin") -> int:
        """
        Auto-discover and register hooks from a module.

        Imports the module and registers all functions decorated
        with @hook.

        Args:
            module_path: Dotted module path to scan.

        Returns:
            Number of hooks discovered.
        """
        count = 0

        try:
            module = importlib.import_module(module_path)

            # Find all functions with hook metadata
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if callable(attr) and hasattr(attr, "_hook_metadata"):
                    # Already registered via decorator
                    count += 1

        except ImportError as e:
            logger.debug("Hook discovery failed for %s: %s", module_path, e)
        except Exception as e:
            logger.warning("Hook discovery error for %s: %s", module_path, e)

        if count > 0:
            logger.info("Discovered %d hooks from %s", count, module_path)

        return count

    def discover_from_package(self, package_path: str = "agentcrawl.hooks") -> int:
        """
        Discover hooks from all modules in a package.

        Args:
            package_path: Dotted package path.

        Returns:
            Total hooks discovered.
        """
        total = 0

        try:
            package = importlib.import_module(package_path)
            if not hasattr(package, "__path__"):
                return 0

            for _importer, modname, _ispkg in pkgutil.walk_packages(
                package.__path__,
                prefix=package.__name__ + ".",
            ):
                try:
                    total += self.discover_hooks(modname)
                except Exception as e:
                    logger.debug("Failed to discover from %s: %s", modname, e)

        except ImportError as e:
            logger.debug("Package discovery failed for %s: %s", package_path, e)

        return total

    # ──────────────────────────────────────────────────────────
    # Built-in Hooks
    # ──────────────────────────────────────────────────────────

    def register_builtins(self) -> None:
        """
        Register built-in hooks for logging, timing, and
        error handling.
        """
        # Logging hooks
        self.register(
            event=HookEvent.PRE_SCRAPE,
            callback=_builtin_log_pre_scrape,
            name="builtin_log_pre_scrape",
            group="logging",
            priority=1,
            description="Log URL before scraping",
        )

        self.register(
            event=HookEvent.POST_SCRAPE,
            callback=_builtin_log_post_scrape,
            name="builtin_log_post_scrape",
            group="logging",
            priority=999,
            description="Log result after scraping",
        )

        # Timing hooks
        self.register(
            event=HookEvent.PRE_SCRAPE,
            callback=_builtin_start_timer,
            name="builtin_start_timer",
            group="timing",
            priority=0,
            description="Start scrape timer",
        )

        self.register(
            event=HookEvent.POST_SCRAPE,
            callback=_builtin_stop_timer,
            name="builtin_stop_timer",
            group="timing",
            priority=1000,
            description="Stop scrape timer and record duration",
        )

        # Error handling hooks
        self.register(
            event=HookEvent.ON_ERROR,
            callback=_builtin_log_error,
            name="builtin_log_error",
            group="error_handling",
            priority=1,
            description="Log errors",
        )

        logger.debug("Built-in hooks registered")

    # ──────────────────────────────────────────────────────────
    # Query
    # ──────────────────────────────────────────────────────────

    def list_hooks(
        self,
        group: str | None = None,
        event: HookEvent | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List registered hooks with metadata.

        Args:
            group: Filter by group.
            event: Filter by event.

        Returns:
            List of hook info dictionaries.
        """
        results: list[dict[str, Any]] = []

        for name, metadata in self._metadata.items():
            if group and metadata.group != group:
                continue
            if event:
                event_str = event.value if isinstance(event, HookEvent) else event
                if metadata.event != event_str:
                    continue

            results.append(
                {
                    **metadata.to_dict(),
                    "enabled": name not in self._disabled_hooks
                    and metadata.group not in self._disabled_groups,
                }
            )

        return results

    def get_metadata(self, name: str) -> HookMetadata | None:
        """Get metadata for a specific hook."""
        return self._metadata.get(name)

    def get_group_hooks(self, group: str) -> list[str]:
        """Get all hook names in a group."""
        return list(self._groups.get(group, set()))

    def hook_count(self, group: str | None = None) -> int:
        """Get the number of registered hooks."""
        if group:
            return len(self._groups.get(group, set()))
        return len(self._metadata)

    # ──────────────────────────────────────────────────────────
    # Execution (delegated to executor)
    # ──────────────────────────────────────────────────────────

    async def execute(
        self,
        event: HookEvent | str,
        ctx: HookContext,
    ) -> HookContext:
        """Execute hooks for an event (delegated to executor)."""
        return await self._executor.execute(event, ctx)

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize registry state."""
        return {
            "name": self._name,
            "hooks": [h.to_dict() for h in self._metadata.values()],
            "groups": {g: list(names) for g, names in self._groups.items()},
            "disabled_groups": list(self._disabled_groups),
            "disabled_hooks": list(self._disabled_hooks),
        }

    def save_config(self, filepath: str) -> None:
        """
        Save registry configuration to a JSON file.

        Note: Only saves metadata and group settings, not
        the actual callback functions.

        Args:
            filepath: Output file path.
        """
        import json

        config = {
            "name": self._name,
            "disabled_groups": list(self._disabled_groups),
            "disabled_hooks": list(self._disabled_hooks),
            "hooks": {name: meta.to_dict() for name, meta in self._metadata.items()},
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def load_config(self, filepath: str) -> None:
        """
        Load registry configuration from a JSON file.

        Restores group and enable/disable settings.

        Args:
            filepath: Input file path.
        """
        import json

        with open(filepath, encoding="utf-8") as f:
            config = json.load(f)

        self._disabled_groups = set(config.get("disabled_groups", []))
        self._disabled_hooks = set(config.get("disabled_hooks", []))

        # Apply disabled states
        for group in self._disabled_groups:
            self.disable_group(group)

        for name in self._disabled_hooks:
            self.disable_hook(name)

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get full registry diagnostics."""
        return {
            "name": self._name,
            "hook_count": self.hook_count(),
            "groups": {
                g: {
                    "hooks": list(names),
                    "enabled": g not in self._disabled_groups,
                }
                for g, names in self._groups.items()
            },
            "disabled_groups": list(self._disabled_groups),
            "disabled_hooks": list(self._disabled_hooks),
            "executor": self._executor.get_diagnostics(),
        }

    def __repr__(self) -> str:
        return (
            f"HookRegistry(name={self._name!r}, "
            f"hooks={self.hook_count()}, "
            f"groups={len(self._groups)})"
        )


# ══════════════════════════════════════════════════════════════
# Built-in Hook Functions
# ══════════════════════════════════════════════════════════════


async def _builtin_log_pre_scrape(ctx: HookContext) -> None:
    """Log the URL before scraping."""
    logger.info("Scraping: %s", ctx.url)


async def _builtin_log_post_scrape(ctx: HookContext) -> None:
    """Log the result after scraping."""
    if ctx.error:
        logger.warning("Scrape failed for %s: %s", ctx.url, ctx.error)
    else:
        logger.info(
            "Scraped: %s (status=%d, %.0fms)",
            ctx.url,
            ctx.status_code,
            ctx.elapsed_ms,
        )


async def _builtin_start_timer(ctx: HookContext) -> None:
    """Start the scrape timer."""
    ctx.set("_scrape_start", time.time())


async def _builtin_stop_timer(ctx: HookContext) -> None:
    """Stop the scrape timer and record duration."""
    import time as time_mod

    start = ctx.get("_scrape_start")
    if start:
        duration = (time_mod.time() - start) * 1000
        ctx.set("scrape_duration_ms", round(duration, 2))


async def _builtin_log_error(ctx: HookContext) -> None:
    """Log errors."""
    if ctx.error:
        logger.error("Error at %s: %s", ctx.url, ctx.error)


# Import time for built-in hooks
import time  # noqa: E402
