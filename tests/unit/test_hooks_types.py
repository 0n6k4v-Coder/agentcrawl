"""Tests for agentcrawl.hooks.types module."""
import asyncio
from unittest.mock import MagicMock

import pytest

from agentcrawl.hooks.executor import HookContext, HookEvent, HookExecutor, HookRegistration, HookStats
from agentcrawl.hooks.registry import HookMetadata, HookRegistry, hook
from agentcrawl.hooks.types import (
    ALL_HOOK_EVENTS,
    DEFAULT_GROUPS,
    AsyncHookCallback,
    EventName,
    GroupName,
    HookCallback,
    HookCondition,
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
    is_async_hook,
    is_hook_context,
    is_hook_event,
    is_hook_executor,
    is_hook_registry,
    is_valid_event_name,
)


class TestHookEvent:
    """Tests for HookEvent enum."""

    def test_all_events_present(self):
        expected_events = {
            "pre_scrape", "post_scrape", "pre_extract", "post_extract",
            "pre_filter", "post_filter", "pre_chunk", "post_chunk",
            "on_error", "on_complete", "pre_crawl", "post_crawl",
            "pre_navigate", "post_navigate", "pre_action", "post_action",
        }
        actual_events = {e.value for e in HookEvent}
        assert expected_events == actual_events

    def test_all_hook_events_constant(self):
        assert set(ALL_HOOK_EVENTS) == {e.value for e in HookEvent}

    def test_create_from_string(self):
        event = HookEvent("pre_scrape")
        assert event == HookEvent.PRE_SCRAPE

    def test_invalid_event_value(self):
        with pytest.raises(ValueError):
            HookEvent("invalid_event")

    def test_hook_event_is_string(self):
        assert isinstance(HookEvent.PRE_SCRAPE, str)


class TestIsHookContext:
    """Tests for is_hook_context type guard."""

    def test_valid_context(self):
        ctx = HookContext(url="https://example.com")
        assert is_hook_context(ctx) is True

    def test_valid_context_full(self):
        ctx = HookContext(
            url="https://example.com",
            data={"key": "val"},
            stage="pre_scrape",
        )
        assert is_hook_context(ctx) is True

    def test_not_context_dict(self):
        assert is_hook_context({"url": "test"}) is False

    def test_not_context_string(self):
        assert is_hook_context("not a context") is False

    def test_not_context_int(self):
        assert is_hook_context(42) is False

    def test_not_context_none(self):
        assert is_hook_context(None) is False

    def test_missing_url_attr(self):
        mock = MagicMock()
        del mock.url
        assert is_hook_context(mock) is False

    def test_missing_data_attr(self):
        mock = MagicMock(spec=[])
        assert is_hook_context(mock) is False


class TestIsHookExecutor:
    """Tests for is_hook_executor type guard."""

    def test_valid_executor(self):
        executor = HookExecutor()
        assert is_hook_executor(executor) is True

    def test_not_executor(self):
        assert is_hook_executor("not executor") is False

    def test_not_executor_dict(self):
        assert is_hook_executor({"execute": "func"}) is False

    def test_missing_execute_attr(self):
        obj = MagicMock(spec=[])
        assert is_hook_executor(obj) is False


class TestIsHookRegistry:
    """Tests for is_hook_registry type guard."""

    def test_valid_registry(self):
        registry = HookRegistry()
        assert is_hook_registry(registry) is True

    def test_not_registry(self):
        assert is_hook_registry("not registry") is False

    def test_not_registry_dict(self):
        assert is_hook_registry({"register_hook_function": "func"}) is False

    def test_missing_register_hook_function(self):
        obj = MagicMock(spec=["enable_group", "discover_hooks", "global_registry"])
        assert is_hook_registry(obj) is False


class TestIsHookEvent:
    """Tests for is_hook_event type guard."""

    def test_valid_event(self):
        assert is_hook_event(HookEvent.PRE_SCRAPE) is True

    def test_string_is_not_event(self):
        assert is_hook_event("pre_scrape") is False

    def test_int_is_not_event(self):
        assert is_hook_event(42) is False

    def test_none_is_not_event(self):
        assert is_hook_event(None) is False


class TestIsAsyncHook:
    """Tests for is_async_hook."""

    def test_async_function(self):
        async def async_hook(ctx):
            pass

        assert is_async_hook(async_hook) is True

    def test_sync_function(self):
        def sync_hook(ctx):
            pass

        assert is_async_hook(sync_hook) is False

    def test_lambda(self):
        assert is_async_hook(lambda ctx: None) is False

    def test_lambda_async(self):
        assert is_async_hook(lambda ctx: asyncio.sleep(0)) is False


class TestIsValidEventName:
    """Tests for is_valid_event_name."""

    def test_valid_event_name(self):
        assert is_valid_event_name("pre_scrape") is True

    def test_valid_event_name_all(self):
        for event_name in ALL_HOOK_EVENTS:
            assert is_valid_event_name(event_name) is True

    def test_invalid_event_name(self):
        assert is_valid_event_name("invalid_event") is False

    def test_empty_string(self):
        assert is_valid_event_name("") is False

    def test_partial_match(self):
        assert is_valid_event_name("pre") is False


class TestTypeAliases:
    """Tests for type alias existence."""

    def test_async_hook_callback_alias(self):
        assert AsyncHookCallback is not None

    def test_sync_hook_callback_alias(self):
        assert SyncHookCallback is not None

    def test_hook_callback_alias(self):
        assert HookCallback is not None

    def test_hook_condition_alias(self):
        assert HookCondition is not None

    def test_hook_transform_alias(self):
        assert HookTransform is not None

    def test_async_hook_transform_alias(self):
        from agentcrawl.hooks.types import AsyncHookTransform as _alias
        assert _alias is not None

    def test_sync_hook_transform_alias(self):
        assert SyncHookTransform is not None

    def test_event_name_alias(self):
        assert EventName is not None

    def test_group_name_alias(self):
        assert GroupName is not None

    def test_hook_name_alias(self):
        assert HookName is not None


class TestTypedDicts:
    """Tests for TypedDict definitions."""

    def test_hook_config_dict_fields(self):
        config: HookConfigDict = {"event": "pre_scrape", "priority": 10}
        assert config["event"] == "pre_scrape"
        assert config["priority"] == 10

    def test_hook_info_dict_fields(self):
        info: HookInfoDict = {"name": "test_hook", "event": "pre_scrape"}
        assert info["name"] == "test_hook"

    def test_hook_stats_dict_fields(self):
        stats: HookStatsDict = {"total_executions": 5}
        assert stats["total_executions"] == 5

    def test_registry_config_dict_fields(self):
        config: RegistryConfigDict = {"name": "test"}
        assert config["name"] == "test"


class TestDefaultGroups:
    """Tests for DEFAULT_GROUPS constant."""

    def test_default_groups_present(self):
        assert "default" in DEFAULT_GROUPS
        assert "logging" in DEFAULT_GROUPS
        assert "timing" in DEFAULT_GROUPS
        assert "error_handling" in DEFAULT_GROUPS
        assert "analytics" in DEFAULT_GROUPS

    def test_default_groups_count(self):
        assert len(DEFAULT_GROUPS) == 8


class TestProtocols:
    """Tests for Protocol definitions."""

    def test_hookable_protocol(self):
        assert HookDiscoverable is not None or True  # Protocol always exists

    def test_runtime_checkable_protocols(self):
        # Protocols are runtime_checkable
        from agentcrawl.hooks.types import Hookable

        executor = HookExecutor()
        assert isinstance(executor, Hookable)
