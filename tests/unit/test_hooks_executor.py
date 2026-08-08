"""Tests for agentcrawl.hooks.executor module."""

import asyncio
import time

import pytest

from agentcrawl.hooks.executor import (
    HookContext,
    HookEvent,
    HookExecutor,
    HookRegistration,
    HookStats,
)


class TestHookContext:
    """Tests for HookContext dataclass."""

    def test_default_values(self):
        ctx = HookContext()
        assert ctx.url == ""
        assert ctx.data == {}
        assert ctx.html == ""
        assert ctx.markdown == ""
        assert ctx.status_code == 0
        assert ctx.error is None
        assert ctx.stage == ""
        assert ctx.extra == {}

    def test_with_url(self):
        ctx = HookContext(url="https://example.com")
        assert ctx.url == "https://example.com"

    def test_with_data(self):
        ctx = HookContext(data={"key": "value"})
        assert ctx.data["key"] == "value"

    def test_set_and_get(self):
        ctx = HookContext()
        ctx.set("foo", "bar")
        assert ctx.get("foo") == "bar"

    def test_get_with_default(self):
        ctx = HookContext()
        assert ctx.get("missing", "default") == "default"

    def test_elapsed_ms(self):
        ctx = HookContext()
        elapsed = ctx.elapsed_ms
        assert elapsed >= 0

    def test_to_dict(self):
        ctx = HookContext(
            url="https://example.com",
            status_code=200,
            stage="pre_scrape",
            error=None,
        )
        d = ctx.to_dict()
        assert d["url"] == "https://example.com"
        assert d["status_code"] == 200
        assert d["stage"] == "pre_scrape"
        assert d["error"] is None
        assert "elapsed_ms" in d
        assert "data_keys" in d

    def test_to_dict_with_error(self):
        ctx = HookContext(url="https://example.com", error="Failed")
        d = ctx.to_dict()
        assert d["error"] == "Failed"


class TestHookStats:
    """Tests for HookStats dataclass."""

    def test_default_values(self):
        stats = HookStats()
        assert stats.total_executions == 0
        assert stats.total_errors == 0
        assert stats.total_skipped == 0
        assert stats.total_timeouts == 0
        assert stats.execution_times == {}

    def test_record_success(self):
        stats = HookStats()
        stats.record("my_hook", 1.5)
        assert stats.total_executions == 1
        assert stats.execution_times["my_hook"] == [1.5]

    def test_record_error(self):
        stats = HookStats()
        stats.record("my_hook", 1.0, error=True)
        assert stats.total_executions == 1
        assert stats.total_errors == 1

    def test_record_skip(self):
        stats = HookStats()
        stats.record_skip()
        assert stats.total_skipped == 1

    def test_record_timeout(self):
        stats = HookStats()
        stats.record_timeout()
        assert stats.total_timeouts == 1

    def test_avg_time(self):
        stats = HookStats()
        stats.record("hook1", 10.0)
        stats.record("hook1", 20.0)
        assert stats.avg_time("hook1") == 15.0

    def test_avg_time_no_executions(self):
        stats = HookStats()
        assert stats.avg_time("unknown") == 0.0

    def test_avg_time_multiple_hooks(self):
        stats = HookStats()
        stats.record("hook1", 10.0)
        stats.record("hook2", 5.0)
        assert stats.avg_time("hook1") == 10.0
        assert stats.avg_time("hook2") == 5.0

    def test_to_dict(self):
        stats = HookStats()
        stats.record("hook1", 10.0)
        stats.record("hook1", 20.0)
        d = stats.to_dict()
        assert d["total_executions"] == 2
        assert d["total_errors"] == 0
        assert "hook1" in d["hooks"]
        assert d["hooks"]["hook1"]["avg_ms"] == 15.0
        assert d["hooks"]["hook1"]["executions"] == 2

    def test_to_dict_with_errors(self):
        stats = HookStats()
        stats.record("hook1", 10.0, error=True)
        stats.record_timeout()
        stats.record_skip()
        d = stats.to_dict()
        assert d["total_errors"] == 1
        assert d["total_timeouts"] == 1
        assert d["total_skipped"] == 1

    def test_to_dict_no_hooks(self):
        stats = HookStats()
        d = stats.to_dict()
        assert d["total_executions"] == 0
        assert d["hooks"] == {}


class TestHookRegistration:
    """Tests for HookRegistration dataclass."""

    def test_default_name(self):
        async def my_hook(ctx):
            pass

        reg = HookRegistration(event=HookEvent.PRE_SCRAPE, callback=my_hook)
        assert reg.name == "my_hook"

    def test_provided_name(self):
        async def my_hook(ctx):
            pass

        reg = HookRegistration(event=HookEvent.PRE_SCRAPE, callback=my_hook, name="custom_name")
        assert reg.name == "custom_name"

    def test_anonymous_callback(self):
        reg = HookRegistration(event=HookEvent.PRE_SCRAPE, callback=lambda ctx: None)
        assert reg.name == "<lambda>"

    def test_default_values(self):
        async def my_hook(ctx):
            pass

        reg = HookRegistration(event=HookEvent.PRE_SCRAPE, callback=my_hook)
        assert reg.priority == 100
        assert reg.condition is None
        assert reg.timeout == 0.0
        assert reg.continue_on_error is True
        assert reg.enabled is True

    def test_custom_values(self):
        async def my_hook(ctx):
            pass

        reg = HookRegistration(
            event=HookEvent.PRE_SCRAPE,
            callback=my_hook,
            priority=10,
            timeout=5.0,
            continue_on_error=False,
            enabled=False,
        )
        assert reg.priority == 10
        assert reg.timeout == 5.0
        assert reg.continue_on_error is False
        assert reg.enabled is False


class TestHookExecutorRegistration:
    """Tests for HookExecutor hook registration."""

    @pytest.fixture
    def executor(self):
        return HookExecutor()

    def test_register_sync_hook(self, executor):
        def my_hook(ctx):
            ctx.set("sync_called", True)

        executor.register(HookEvent.PRE_SCRAPE, my_hook, name="sync_hook")
        hooks = executor.get_hooks(HookEvent.PRE_SCRAPE)
        assert len(hooks) == 1
        assert hooks[0].name == "sync_hook"

    def test_register_async_hook(self, executor):
        async def my_hook(ctx):
            ctx.set("async_called", True)

        executor.register(HookEvent.PRE_SCRAPE, my_hook, name="async_hook")
        hooks = executor.get_hooks(HookEvent.PRE_SCRAPE)
        assert len(hooks) == 1
        assert hooks[0].name == "async_hook"

    def test_register_with_string_event(self, executor):
        def my_hook(ctx):
            pass

        executor.register("pre_scrape", my_hook, name="str_hook")
        hooks = executor.get_hooks("pre_scrape")
        assert len(hooks) == 1

    def test_register_with_default_name(self, executor):
        def my_function(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, my_function)
        hooks = executor.get_hooks(HookEvent.PRE_SCRAPE)
        assert hooks[0].name == "my_function"

    def test_register_lambda(self, executor):
        executor.register(HookEvent.PRE_SCRAPE, lambda ctx: None)
        hooks = executor.get_hooks(HookEvent.PRE_SCRAPE)
        assert hooks[0].name == "<lambda>"

    def test_unregister_existing(self, executor):
        def my_hook(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook")
        assert executor.unregister(HookEvent.PRE_SCRAPE, "my_hook") is True
        assert len(executor.get_hooks(HookEvent.PRE_SCRAPE)) == 0

    def test_unregister_nonexistent(self, executor):
        assert executor.unregister(HookEvent.PRE_SCRAPE, "nonexistent") is False

    def test_unregister_with_string_event(self, executor):
        def my_hook(ctx):
            pass

        executor.register("pre_scrape", my_hook, name="my_hook")
        assert executor.unregister("pre_scrape", "my_hook") is True

    def test_clear_specific_event(self, executor):
        def hook1(ctx):
            pass

        def hook2(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, hook1, name="hook1")
        executor.register(HookEvent.POST_SCRAPE, hook2, name="hook2")

        executor.clear(HookEvent.PRE_SCRAPE)
        assert len(executor.get_hooks(HookEvent.PRE_SCRAPE)) == 0
        assert len(executor.get_hooks(HookEvent.POST_SCRAPE)) == 1

    def test_clear_all_events(self, executor):
        def hook1(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, hook1, name="hook1")
        executor.clear()
        assert executor.hook_count() == 0

    def test_priority_ordering(self, executor):
        call_order = []

        async def high_priority(ctx):
            call_order.append("high")

        async def low_priority(ctx):
            call_order.append("low")

        executor.register(HookEvent.PRE_SCRAPE, low_priority, name="low", priority=200)
        executor.register(HookEvent.PRE_SCRAPE, high_priority, name="high", priority=10)

        hooks = executor.get_hooks(HookEvent.PRE_SCRAPE)
        assert hooks[0].name == "high"
        assert hooks[1].name == "low"

    def test_enable_disable_hook(self, executor):
        async def my_hook(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook")
        executor.disable(HookEvent.PRE_SCRAPE, "other")

        assert executor.enable(HookEvent.PRE_SCRAPE, "my_hook") is True
        assert executor.get_hooks(HookEvent.PRE_SCRAPE)[0].enabled is True

        assert executor.disable(HookEvent.PRE_SCRAPE, "my_hook") is True
        assert executor.get_hooks(HookEvent.PRE_SCRAPE)[0].enabled is False

    def test_enable_nonexistent_hook(self, executor):
        assert executor.enable(HookEvent.PRE_SCRAPE, "nonexistent") is False

    def test_disable_nonexistent_hook(self, executor):
        assert executor.disable(HookEvent.PRE_SCRAPE, "nonexistent") is False

    def test_hook_count_by_event(self, executor):
        def hook1(ctx):
            pass

        def hook2(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, hook1, name="hook1")
        executor.register(HookEvent.PRE_SCRAPE, hook2, name="hook2")
        assert executor.hook_count(HookEvent.PRE_SCRAPE) == 2

    def test_hook_count_all(self, executor):
        def hook1(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, hook1, name="hook1")
        executor.register(HookEvent.POST_SCRAPE, hook1, name="hook2")
        assert executor.hook_count() == 2

    def test_has_hooks_false(self, executor):
        assert executor.has_hooks(HookEvent.PRE_SCRAPE) is False

    def test_has_hooks_true(self, executor):
        def my_hook(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, my_hook)
        assert executor.has_hooks(HookEvent.PRE_SCRAPE) is True

    def test_repr(self, executor):
        repr_str = repr(executor)
        assert "HookExecutor" in repr_str

    def test_get_diagnostics(self, executor):
        def my_hook(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook")
        diag = executor.get_diagnostics()
        assert "total_hooks" in diag
        assert diag["total_hooks"] == 1
        assert "hooks_by_event" in diag
        assert "stats" in diag

    def test_stats_property(self, executor):
        assert isinstance(executor.stats, HookStats)

    def test_reset_stats(self, executor):
        async def my_hook(ctx):
            pass

        executor.register(HookEvent.PRE_SCRAPE, my_hook, name="my_hook")
        # Can't easily execute async here, just check reset works
        executor.reset_stats()
        assert executor.stats.total_executions == 0


class TestHookExecutorExecution:
    """Tests for HookExecutor execution."""

    @pytest.fixture
    def executor(self):
        return HookExecutor()

    @pytest.mark.asyncio
    async def test_execute_async_hook(self, executor):
        result = []

        @executor.on(HookEvent.PRE_SCRAPE)
        async def my_hook(ctx):
            result.append("called")
            ctx.set("test", True)

        ctx = HookContext(url="https://example.com")
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)

        assert result == ["called"]
        assert ctx.get("test") is True

    @pytest.mark.asyncio
    async def test_execute_sync_hook(self, executor):
        result = []

        def my_hook(ctx):
            result.append("sync_called")
            ctx.set("sync", True)

        executor.register(HookEvent.PRE_SCRAPE, my_hook, name="sync_hook")
        ctx = HookContext(url="https://example.com")
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)

        assert result == ["sync_called"]
        assert ctx.get("sync") is True

    @pytest.mark.asyncio
    async def test_execute_string_event(self, executor):
        @executor.on("pre_scrape")
        async def my_hook(ctx):
            ctx.set("called", True)

        ctx = HookContext(url="https://example.com")
        await executor.execute("pre_scrape", ctx)
        assert ctx.get("called") is True

    @pytest.mark.asyncio
    async def test_execute_no_hooks(self, executor):
        ctx = HookContext(url="https://example.com")
        result = await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_execute_multiple_hooks_priority_order(self, executor):
        order = []

        @executor.on(HookEvent.PRE_SCRAPE, priority=200)
        async def hook_low(ctx):
            order.append("low")

        @executor.on(HookEvent.PRE_SCRAPE, priority=10)
        async def hook_high(ctx):
            order.append("high")

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert order == ["high", "low"]

    @pytest.mark.asyncio
    async def test_execute_skips_disabled_hooks(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE)
        async def hook1(ctx):
            results.append("hook1")

        @executor.on(HookEvent.PRE_SCRAPE)
        async def hook2(ctx):
            results.append("hook2")

        executor.disable(HookEvent.PRE_SCRAPE, "hook2")

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert results == ["hook1"]

    @pytest.mark.asyncio
    async def test_execute_condition_true(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE, condition=lambda ctx: ctx.data.get("run") is True)
        async def my_hook(ctx):
            results.append("called")

        ctx = HookContext()
        ctx.set("run", True)
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert results == ["called"]

    @pytest.mark.asyncio
    async def test_execute_condition_false(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE, condition=lambda ctx: ctx.data.get("run") is True)
        async def my_hook(ctx):
            results.append("called")

        ctx = HookContext()
        ctx.set("run", False)
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_condition_exception(self, executor):
        results = []

        def condition(ctx):
            raise RuntimeError("condition error")

        @executor.on(HookEvent.PRE_SCRAPE, condition=condition)
        async def my_hook(ctx):
            results.append("called")

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        # Hook should be skipped due to condition exception
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_hook_exception_continues(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE)
        async def failing_hook(ctx):
            raise ValueError("hook error")

        @executor.on(HookEvent.PRE_SCRAPE)
        async def good_hook(ctx):
            results.append("called")

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        # continue_on_error=True (default), so execution continues
        assert results == ["called"]

    @pytest.mark.asyncio
    async def test_execute_hook_exception_no_continue(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE, continue_on_error=False)
        async def failing_hook(ctx):
            raise ValueError("hook error")

        ctx = HookContext()
        with pytest.raises(ValueError, match="hook error"):
            await executor.execute(HookEvent.PRE_SCRAPE, ctx)

    @pytest.mark.asyncio
    async def test_execute_sync_hook_exception_continues(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE)
        def failing_hook(ctx):
            raise ValueError("sync error")

        @executor.on(HookEvent.PRE_SCRAPE)
        async def good_hook(ctx):
            results.append("called")

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert results == ["called"]

    @pytest.mark.asyncio
    async def test_timeout_async_hook(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE, timeout=0.01)
        async def slow_hook(ctx):
            await asyncio.sleep(10)

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        # Should log timeout but not raise
        assert executor.stats.total_timeouts == 1

    @pytest.mark.asyncio
    async def test_timeout_sync_hook(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE, timeout=0.01)
        def slow_sync_hook(ctx):
            time.sleep(10)

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert executor.stats.total_timeouts == 1

    @pytest.mark.asyncio
    async def test_execute_chain_basic(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE)
        def hook1(ctx):
            results.append("hook1")
            return ctx

        @executor.on(HookEvent.PRE_SCRAPE)
        def hook2(ctx):
            results.append("hook2")
            return ctx

        ctx = HookContext()
        await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)
        assert results == ["hook1", "hook2"]

    @pytest.mark.asyncio
    async def test_execute_chain_stop_on_none(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE, priority=1)
        def hook1(ctx):
            results.append("hook1")
            return None  # Returns None

        @executor.on(HookEvent.PRE_SCRAPE, priority=2)
        def hook2(ctx):
            results.append("hook2")
            return ctx

        ctx = HookContext()
        await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx, stop_on_none=True)
        assert results == ["hook1"]

    @pytest.mark.asyncio
    async def test_execute_chain_returns_ctx(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE)
        def hook1(ctx):
            ctx.set("modified", True)
            return ctx

        ctx = HookContext()
        result = await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)
        assert result is ctx
        assert ctx.get("modified") is True

    @pytest.mark.asyncio
    async def test_execute_chain_skips_disabled(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE, priority=1)
        async def hook1(ctx):
            results.append("hook1")

        @executor.on(HookEvent.PRE_SCRAPE, priority=2)
        async def hook2(ctx):
            results.append("hook2")

        executor.disable(HookEvent.PRE_SCRAPE, "hook2")

        ctx = HookContext()
        await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)
        assert results == ["hook1"]

    @pytest.mark.asyncio
    async def test_execute_chain_condition(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE, condition=lambda ctx: False)
        async def hook1(ctx):
            results.append("hook1")

        ctx = HookContext()
        await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_chain_continue_on_error(self, executor):
        results = []

        @executor.on(HookEvent.PRE_SCRAPE, continue_on_error=True)
        async def failing_hook(ctx):
            raise ValueError("error")

        @executor.on(HookEvent.PRE_SCRAPE, priority=2)
        async def good_hook(ctx):
            results.append("called")

        ctx = HookContext()
        await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)
        assert results == ["called"]

    @pytest.mark.asyncio
    async def test_execute_chain_raise_on_error(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE, continue_on_error=False)
        async def failing_hook(ctx):
            raise ValueError("error")

        ctx = HookContext()
        with pytest.raises(ValueError, match="error"):
            await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)

    @pytest.mark.asyncio
    async def test_execute_chain_string_event(self, executor):
        @executor.on("pre_scrape")
        async def hook1(ctx):
            return ctx

        ctx = HookContext()
        result = await executor.execute_chain("pre_scrape", ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_execute_chain_no_hooks(self, executor):
        ctx = HookContext()
        result = await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_execute_sets_stage(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE)
        async def my_hook(ctx):
            pass

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert ctx.stage == "pre_scrape"

    @pytest.mark.asyncio
    async def test_execute_chain_sets_stage(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE)
        async def my_hook(ctx):
            pass

        ctx = HookContext()
        await executor.execute_chain(HookEvent.PRE_SCRAPE, ctx)
        assert ctx.stage == "pre_scrape"

    @pytest.mark.asyncio
    async def test_stats_recorded_on_success(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE)
        async def my_hook(ctx):
            pass

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert executor.stats.total_executions == 1
        assert "my_hook" in executor.stats.execution_times

    @pytest.mark.asyncio
    async def test_stats_recorded_on_error(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE, continue_on_error=True)
        async def my_hook(ctx):
            raise ValueError("error")

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert executor.stats.total_errors == 1

    @pytest.mark.asyncio
    async def test_stats_skipped_disabled(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE)
        async def my_hook(ctx):
            pass

        executor.disable(HookEvent.PRE_SCRAPE, "my_hook")
        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert executor.stats.total_skipped == 1

    @pytest.mark.asyncio
    async def test_stats_skipped_condition(self, executor):
        @executor.on(HookEvent.PRE_SCRAPE, condition=lambda ctx: False)
        async def my_hook(ctx):
            pass

        ctx = HookContext()
        await executor.execute(HookEvent.PRE_SCRAPE, ctx)
        assert executor.stats.total_skipped == 1
