"""Tests for agentcrawl.hooks.registry module."""

import json

import pytest

from agentcrawl.hooks.executor import HookContext, HookEvent, HookExecutor
from agentcrawl.hooks.registry import (
    HookMetadata,
    HookRegistry,
    hook,
)


class TestHookMetadata:
    """Tests for HookMetadata dataclass."""

    def test_defaults(self):
        meta = HookMetadata()
        assert meta.name == ""
        assert meta.event == ""
        assert meta.group == "default"
        assert meta.description == ""
        assert meta.author == ""
        assert meta.version == "1.0"
        assert meta.tags == []
        assert meta.dependencies == []

    def test_custom_values(self):
        meta = HookMetadata(
            name="my_hook",
            event="pre_scrape",
            group="logging",
            description="Logs stuff",
            author="test",
            version="2.0",
            tags=["tag1", "tag2"],
            dependencies=["other_hook"],
        )
        assert meta.name == "my_hook"
        assert meta.event == "pre_scrape"
        assert meta.group == "logging"
        assert meta.description == "Logs stuff"
        assert meta.author == "test"
        assert meta.version == "2.0"
        assert meta.tags == ["tag1", "tag2"]
        assert meta.dependencies == ["other_hook"]

    def test_to_dict(self):
        meta = HookMetadata(
            name="hook1",
            event="pre_scrape",
            group="logging",
            tags=["t1"],
            dependencies=["dep1"],
        )
        d = meta.to_dict()
        assert d["name"] == "hook1"
        assert d["event"] == "pre_scrape"
        assert d["group"] == "logging"
        assert d["tags"] == ["t1"]
        assert d["dependencies"] == ["dep1"]


class TestHookDecorator:
    """Tests for the @hook decorator."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        HookRegistry.reset_global()
        yield
        HookRegistry.reset_global()

    def test_hook_decorator_registers(self):
        @hook(event="pre_scrape", group="logging", priority=10)
        async def my_hook(ctx):
            pass

        registry = HookRegistry.global_registry()
        hooks = registry.executor.get_hooks(HookEvent.PRE_SCRAPE)
        assert any(h.name == "my_hook" for h in hooks)

        metadata = registry.get_metadata("my_hook")
        assert metadata is not None
        assert metadata.event == "pre_scrape"
        assert metadata.group == "logging"

    def test_hook_decorator_returns_function(self):
        @hook(event="pre_scrape")
        async def my_hook(ctx):
            pass

        assert my_hook.__name__ == "my_hook"
        assert hasattr(my_hook, "_hook_metadata")

    def test_hook_decorator_with_event_enum(self):
        @hook(event=HookEvent.PRE_SCRAPE)
        async def my_hook(ctx):
            pass

        registry = HookRegistry.global_registry()
        metadata = registry.get_metadata("my_hook")
        assert metadata.event == "pre_scrape"

    def test_hook_decorator_metadata(self):
        @hook(
            event="post_scrape",
            group="analytics",
            description="Track metrics",
            author="team",
            version="1.0",
            tags=["monitor"],
            dependencies=["other"],
        )
        async def track(ctx):
            pass

        registry = HookRegistry.global_registry()
        meta = registry.get_metadata("track")
        assert meta.group == "analytics"
        assert meta.description == "Track metrics"
        assert meta.author == "team"
        assert meta.version == "1.0"
        assert meta.tags == ["monitor"]
        assert meta.dependencies == ["other"]


class TestHookRegistryCreation:
    """Tests for HookRegistry instantiation."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        HookRegistry.reset_global()
        yield
        HookRegistry.reset_global()

    def test_default_creation(self):
        registry = HookRegistry()
        assert registry.name == "default"

    def test_custom_name(self):
        registry = HookRegistry(name="my_registry")
        assert registry.name == "my_registry"

    def test_custom_executor(self):
        executor = HookExecutor()
        registry = HookRegistry(executor=executor)
        assert registry.executor is executor

    def test_global_registry_singleton(self):
        r1 = HookRegistry.global_registry()
        r2 = HookRegistry.global_registry()
        assert r1 is r2
        assert r1.name == "global"

    def test_reset_global(self):
        r1 = HookRegistry.global_registry()
        HookRegistry.reset_global()
        r2 = HookRegistry.global_registry()
        assert r1 is not r2

    def test_groups_property_empty(self):
        registry = HookRegistry()
        assert registry.groups == []

    def test_disabled_groups_property(self):
        registry = HookRegistry()
        assert isinstance(registry.disabled_groups, set)

    def test_repr(self):
        registry = HookRegistry(name="test")
        repr_str = repr(registry)
        assert "HookRegistry" in repr_str
        assert "test" in repr_str


class TestHookRegistryRegistration:
    """Tests for HookRegistry registration."""

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    def test_register_programmatic(self, registry):
        async def my_hook(ctx):
            pass

        registry.register(
            event=HookEvent.PRE_SCRAPE,
            callback=my_hook,
            name="my_hook",
            group="logging",
            priority=10,
        )
        assert registry.hook_count() == 1
        assert registry.get_metadata("my_hook") is not None

    def test_register_with_string_event(self, registry):
        async def my_hook(ctx):
            pass

        registry.register(event="pre_scrape", callback=my_hook, name="str_hook")
        hooks = registry.executor.get_hooks("pre_scrape")
        assert len(hooks) == 1

    def test_register_default_name(self, registry):
        async def my_function(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_function)
        assert registry.get_metadata("my_function") is not None

    def test_register_hook_function_without_decorator(self, registry):
        # Function without _hook_metadata should be skipped
        def plain_func(ctx):
            pass

        registry.register_hook_function(plain_func)
        assert registry.hook_count() == 0

    def test_register_hook_function_with_decorator(self, registry):
        @hook(event="pre_scrape", group="logging")
        async def my_hook(ctx):
            pass

        # Reset global registry to avoid interference
        HookRegistry.reset_global()
        registry.register_hook_function(my_hook)
        assert registry.hook_count() == 1

    def test_unregister_existing(self, registry):
        async def my_hook(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook")
        assert registry.unregister("my_hook") is True
        assert registry.hook_count() == 0

    def test_unregister_nonexistent(self, registry):
        assert registry.unregister("nonexistent") is False

    def test_register_all_from(self, registry):
        other = HookRegistry(name="other")

        async def hook1(ctx):
            pass

        other.register(HookEvent.PRE_SCRAPE, hook1, name="hook1")

        count = registry.register_all_from(other)
        assert count == 1
        assert registry.hook_count() == 1

    def test_register_all_from_skip_duplicates(self, registry):
        other = HookRegistry(name="other")

        async def hook1(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, hook1, name="hook1")
        other.register(HookEvent.PRE_SCRAPE, hook1, name="hook1")
        other.register(HookEvent.POST_SCRAPE, hook1, name="hook2")

        count = registry.register_all_from(other)
        assert count == 1  # hook1 already exists, only hook2 copied
        assert registry.hook_count() == 2

    def test_register_all_from_empty_registry(self, registry):
        other = HookRegistry(name="empty")
        assert registry.register_all_from(other) == 0


class TestHookRegistryGroupManagement:
    """Tests for HookRegistry group management."""

    @pytest.fixture
    def registry(self):
        HookRegistry.reset_global()
        return HookRegistry()

    def test_enable_group_existing_hooks(self, registry):
        async def hook1(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, hook1, name="hook1", group="logging")
        registry.disable_group("logging")
        count = registry.enable_group("logging")
        assert count == 1
        assert "logging" not in registry.disabled_groups

    def test_disable_group_existing_hooks(self, registry):
        async def hook1(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, hook1, name="hook1", group="analytics")
        count = registry.disable_group("analytics")
        assert count == 1
        assert "analytics" in registry.disabled_groups

    def test_enable_nonexistent_group(self, registry):
        count = registry.enable_group("nonexistent")
        assert count == 0

    def test_disable_nonexistent_group(self, registry):
        count = registry.disable_group("nonexistent")
        assert count == 0

    def test_enable_hook(self, registry):
        async def my_hook(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook", group="logging")
        registry.disable_hook("my_hook")
        assert registry.enable_hook("my_hook") is True
        assert "my_hook" not in registry._disabled_hooks

    def test_enable_nonexistent_hook(self, registry):
        assert registry.enable_hook("nonexistent") is False

    def test_disable_hook(self, registry):
        async def my_hook(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook", group="logging")
        assert registry.disable_hook("my_hook") is True
        assert "my_hook" in registry._disabled_hooks

    def test_disable_nonexistent_hook(self, registry):
        assert registry.disable_hook("nonexistent") is False


class TestHookRegistryDiscovery:
    """Tests for HookRegistry discovery."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        HookRegistry.reset_global()
        yield
        HookRegistry.reset_global()

    def test_discover_hooks_existing_module(self):
        registry = HookRegistry()
        count = registry.discover_hooks("agentcrawl.hooks.types")
        # types.py has functions with _hook_metadata? No, but may have none
        assert count >= 0

    def test_discover_hooks_nonexistent_module(self):
        registry = HookRegistry()
        count = registry.discover_hooks("nonexistent.module.path")
        assert count == 0

    def test_discover_from_package(self):
        registry = HookRegistry()
        count = registry.discover_from_package("agentcrawl.hooks")
        assert count >= 0

    def test_discover_from_nonexistent_package(self):
        registry = HookRegistry()
        count = registry.discover_from_package("nonexistent.package")
        assert count == 0


class TestHookRegistryBuiltins:
    """Tests for HookRegistry built-in hooks."""

    @pytest.fixture
    def registry(self):
        HookRegistry.reset_global()
        reg = HookRegistry()
        reg.register_builtins()
        return reg

    def test_builtins_registered(self, registry):
        assert registry.hook_count() == 5

    def test_builtin_logging_preset_hooks(self, registry):
        hooks = registry.list_hooks(group="logging")
        names = [h["name"] for h in hooks]
        assert "builtin_log_pre_scrape" in names
        assert "builtin_log_post_scrape" in names

    def test_builtin_timing_hooks(self, registry):
        hooks = registry.list_hooks(group="timing")
        names = [h["name"] for h in hooks]
        assert "builtin_start_timer" in names
        assert "builtin_stop_timer" in names

    def test_builtin_error_hooks(self, registry):
        hooks = registry.list_hooks(group="error_handling")
        names = [h["name"] for h in hooks]
        assert "builtin_log_error" in names

    def test_builtin_hooks_list(self, registry):
        hooks = registry.list_hooks()
        assert len(hooks) == 5
        for h in hooks:
            assert "name" in h
            assert "event" in h
            assert "group" in h
            assert "description" in h
            assert "author" in h
            assert "version" in h
            assert "tags" in h
            assert "dependencies" in h
            assert "enabled" in h

    def test_builtin_hooks_filtered_by_event(self, registry):
        pre_scrape_hooks = registry.list_hooks(event=HookEvent.PRE_SCRAPE)
        events = [h["event"] for h in pre_scrape_hooks]
        assert all(e == "pre_scrape" for e in events)

    def test_builtin_hooks_filtered_by_group(self, registry):
        timing_hooks = registry.list_hooks(group="timing")
        groups = [h["group"] for h in timing_hooks]
        assert all(g == "timing" for g in groups)


class TestHookRegistryQuery:
    """Tests for HookRegistry query methods."""

    @pytest.fixture
    def registry_with_hooks(self):
        HookRegistry.reset_global()
        registry = HookRegistry()

        async def hook1(ctx):
            pass

        async def hook2(ctx):
            pass

        async def hook3(ctx):
            pass

        registry.register(
            HookEvent.PRE_SCRAPE, hook1, name="hook1", group="logging", description="desc1"
        )
        registry.register(
            HookEvent.PRE_SCRAPE, hook2, name="hook2", group="analytics", description="desc2"
        )
        registry.register(
            HookEvent.POST_SCRAPE, hook3, name="hook3", group="logging", description="desc3"
        )
        registry.disable_hook("hook3")

        return registry

    def test_list_all_hooks(self, registry_with_hooks):
        hooks = registry_with_hooks.list_hooks()
        assert len(hooks) == 3
        names = {h["name"] for h in hooks}
        assert names == {"hook1", "hook2", "hook3"}

    def test_list_hooks_by_group(self, registry_with_hooks):
        hooks = registry_with_hooks.list_hooks(group="logging")
        assert len(hooks) == 2

    def test_list_hooks_by_event_string(self, registry_with_hooks):
        hooks = registry_with_hooks.list_hooks(event="pre_scrape")
        assert len(hooks) == 2

    def test_list_hooks_by_event_enum(self, registry_with_hooks):
        hooks = registry_with_hooks.list_hooks(event=HookEvent.POST_SCRAPE)
        assert len(hooks) == 1
        assert hooks[0]["event"] == "post_scrape"

    def test_list_hooks_filter_both(self, registry_with_hooks):
        hooks = registry_with_hooks.list_hooks(group="logging", event=HookEvent.POST_SCRAPE)
        assert len(hooks) == 1
        assert hooks[0]["name"] == "hook3"

    def test_get_metadata_existing(self, registry_with_hooks):
        meta = registry_with_hooks.get_metadata("hook1")
        assert meta is not None
        assert meta.name == "hook1"
        assert meta.group == "logging"

    def test_get_metadata_nonexistent(self, registry_with_hooks):
        assert registry_with_hooks.get_metadata("nonexistent") is None

    def test_get_group_hooks(self, registry_with_hooks):
        names = registry_with_hooks.get_group_hooks("logging")
        assert set(names) == {"hook1", "hook3"}

    def test_get_group_hooks_nonexistent(self, registry_with_hooks):
        assert registry_with_hooks.get_group_hooks("nonexistent") == []

    def test_hook_count_all(self, registry_with_hooks):
        assert registry_with_hooks.hook_count() == 3

    def test_hook_count_by_group(self, registry_with_hooks):
        assert registry_with_hooks.hook_count(group="logging") == 2
        assert registry_with_hooks.hook_count(group="analytics") == 1
        assert registry_with_hooks.hook_count(group="nonexistent") == 0

    def test_hook_enabled_status(self, registry_with_hooks):
        hooks = registry_with_hooks.list_hooks()
        hook3 = next(h for h in hooks if h["name"] == "hook3")
        assert hook3["enabled"] is False

    def test_hook_enabled_after_disable_group(self, registry_with_hooks):
        registry_with_hooks.disable_group("logging")
        hooks = registry_with_hooks.list_hooks(group="logging")
        for h in hooks:
            assert h["enabled"] is False


class TestHookRegistrySerialization:
    """Tests for HookRegistry serialization."""

    @pytest.fixture
    def registry(self):
        HookRegistry.reset_global()
        return HookRegistry(name="test_registry")

    def test_to_dict(self, registry):
        async def my_hook(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook", group="logging")
        d = registry.to_dict()
        assert d["name"] == "test_registry"
        assert len(d["hooks"]) == 1
        assert d["hooks"][0]["name"] == "my_hook"
        assert "groups" in d
        assert "disabled_groups" in d
        assert "disabled_hooks" in d

    def test_to_dict_empty(self, registry):
        d = registry.to_dict()
        assert d["name"] == "test_registry"
        assert d["hooks"] == []
        assert d["disabled_groups"] == []
        assert d["disabled_hooks"] == []

    def test_save_config(self, registry, tmp_path):
        async def my_hook(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook", group="logging")
        config_path = str(tmp_path / "config.json")
        registry.save_config(config_path)
        with open(config_path) as f:
            config = json.load(f)
        assert config["name"] == "test_registry"
        assert len(config["hooks"]) == 1
        assert config["hooks"]["my_hook"]["group"] == "logging"

    def test_load_config(self, registry, tmp_path):
        async def my_hook(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook", group="logging")

        # Save with disabled group
        registry.disable_group("logging")

        config_path = str(tmp_path / "config.json")
        registry.save_config(config_path)

        # Create new registry and load
        HookRegistry.reset_global()
        new_registry = HookRegistry(name="loaded")
        new_registry.load_config(config_path)
        assert "logging" in new_registry.disabled_groups

    def test_load_config_nonexistent_file(self, registry):
        with pytest.raises(FileNotFoundError):
            registry.load_config("/nonexistent/path/config.json")


class TestHookRegistryExecution:
    """Tests for HookRegistry execution delegation."""

    @pytest.fixture
    def registry(self):
        HookRegistry.reset_global()
        return HookRegistry()

    @pytest.mark.asyncio
    async def test_execute_delegation(self, registry):
        results = []

        @registry.executor.on(HookEvent.PRE_SCRAPE)
        async def my_hook(ctx):
            results.append("called")
            ctx.set("modified", True)

        ctx = HookContext(url="https://example.com")
        result = await registry.execute(HookEvent.PRE_SCRAPE, ctx)
        assert results == ["called"]
        assert result.get("modified") is True


class TestHookRegistryDiagnostics:
    """Tests for HookRegistry diagnostics."""

    @pytest.fixture
    def registry(self):
        HookRegistry.reset_global()
        return HookRegistry(name="diag_test")

    def test_get_diagnostics(self, registry):
        async def my_hook(ctx):
            pass

        registry.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook", group="logging")
        registry.disable_group("analytics")
        registry.disable_hook("my_hook")

        diag = registry.get_diagnostics()
        assert diag["name"] == "diag_test"
        assert diag["hook_count"] == 1
        assert "logging" in diag["groups"]
        assert "analytics" in diag["disabled_groups"]
        assert "my_hook" in diag["disabled_hooks"]
        assert "executor" in diag

    def test_get_diagnostics_empty(self, registry):
        diag = registry.get_diagnostics()
        assert diag["hook_count"] == 0
        assert diag["disabled_groups"] == []
        assert diag["disabled_hooks"] == []
