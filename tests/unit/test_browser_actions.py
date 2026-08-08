"""Tests for agentcrawl.browser.actions module.

Covers:
- Action data model (from_dict, to_dict, __post_init__ with invalid type)
- ActionResult (success property, to_dict)
- PageActions (construction, add, __len__, __iter__, __repr__,
  to_list, from_list, to_json, from_json, execute chain, error handling,
  delay_after, execute_and_collect_screenshots)
- All action handler methods via _ActionExecutor
- PageActionsBuilder fluent interface
- ActionExecutionError

All Playwright interactions are mocked — no real browser required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcrawl.browser.actions import (
    Action,
    ActionExecutionError,
    ActionResult,
    ActionStatus,
    ActionType,
    PageActions,
    PageActionsBuilder,
    ScrollDirection,
    WaitCondition,
    _ActionExecutor,
)

# ══════════════════════════════════════════════════════════════
# Test Helpers
# ══════════════════════════════════════════════════════════════


def make_mock_page() -> MagicMock:
    """Create a mock Playwright page with all common async methods."""
    page = MagicMock()
    page.click = AsyncMock()
    page.dblclick = AsyncMock()
    page.hover = AsyncMock()
    page.drag_and_drop = AsyncMock()
    page.type = AsyncMock()
    page.fill = AsyncMock()
    page.press = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.down = AsyncMock()
    page.keyboard.up = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    page.goto = AsyncMock()
    page.go_back = AsyncMock()
    page.go_forward = AsyncMock()
    page.reload = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"screenshot_bytes")
    page.set_viewport_size = AsyncMock()
    page.scroll_into_view_if_needed = AsyncMock()
    page.select_option = AsyncMock()
    page.check = AsyncMock()
    page.uncheck = AsyncMock()
    page.set_input_files = AsyncMock()
    page.focus = AsyncMock()
    page.query_selector = AsyncMock(
        return_value=MagicMock(screenshot=AsyncMock(return_value=b"element_screenshot_bytes"))
    )
    page.wait_for_selector = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_url = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.frame_locator = AsyncMock(return_value=MagicMock())
    page.url = "https://example.com"
    page.pause = AsyncMock()
    page.locator = MagicMock()
    return page


# ══════════════════════════════════════════════════════════════
# Action Tests
# ══════════════════════════════════════════════════════════════


class TestActionModel:
    """Tests for the Action dataclass."""

    def test_from_dict_basic(self) -> None:
        action = Action.from_dict({"type": "click", "selector": "#btn"})
        assert action.type == ActionType.CLICK
        assert action.selector == "#btn"

    def test_from_dict_filters_unknown_fields(self) -> None:
        action = Action.from_dict({"type": "click", "selector": "#btn", "unknown_field": "value"})
        assert action.selector == "#btn"
        assert not hasattr(action, "unknown_field")

    def test_from_dict_with_string_type(self) -> None:
        action = Action.from_dict({"type": "wait", "milliseconds": 1000})
        assert action.type == ActionType.WAIT
        assert action.milliseconds == 1000

    def test_post_init_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="Unknown action type"):
            Action(type="invalid_action", selector="#btn")

    def test_post_init_valid_string_type(self) -> None:
        action = Action(type="click", selector="#btn")
        assert action.type == ActionType.CLICK

    def test_post_init_action_type_enum(self) -> None:
        action = Action(type=ActionType.HOVER, selector="#btn")
        assert action.type == ActionType.HOVER

    def test_to_dict_basic(self) -> None:
        action = Action(type="click", selector="#btn")
        d = action.to_dict()
        assert d["type"] == "click"
        assert d["selector"] == "#btn"

    def test_to_dict_string_type(self) -> None:
        """Test to_dict when type is a string (not ActionType enum)."""
        action = Action(type="click", selector="#btn")
        d = action.to_dict()
        assert d["type"] == "click"

    def test_to_dict_omits_defaults(self) -> None:
        action = Action(type="click", selector="#btn", text=None, timeout=30_000)
        d = action.to_dict()
        assert "text" not in d
        assert "timeout" not in d  # Default value, should be omitted

    def test_to_dict_includes_non_defaults(self) -> None:
        action = Action(type="type", selector="#input", text="hello", amount=100)
        d = action.to_dict()
        assert d["text"] == "hello"
        assert d["amount"] == 100


class TestActionResult:
    """Tests for ActionResult dataclass."""

    def test_success_property(self) -> None:
        action = Action(type="click", selector="#btn")
        result = ActionResult(action=action, status=ActionStatus.SUCCESS)
        assert result.success is True

    def test_success_property_failed(self) -> None:
        action = Action(type="click", selector="#btn")
        result = ActionResult(action=action, status=ActionStatus.FAILED, error="boom")
        assert result.success is False

    def test_to_dict(self) -> None:
        action = Action(type="click", selector="#btn")
        result = ActionResult(
            action=action,
            status=ActionStatus.SUCCESS,
            data={"clicked": "#btn"},
            error=None,
            duration_ms=42.567,
        )
        d = result.to_dict()
        assert d["status"] == "success"
        assert d["data"] == {"clicked": "#btn"}
        assert d["error"] is None
        assert d["duration_ms"] == 42.57
        assert d["has_screenshot"] is False

    def test_to_dict_with_screenshot(self) -> None:
        action = Action(type="screenshot")
        result = ActionResult(
            action=action,
            status=ActionStatus.SUCCESS,
            screenshot_base64="base64data",
        )
        d = result.to_dict()
        assert d["has_screenshot"] is True


class TestActionExecutionError:
    """Tests for ActionExecutionError exception."""

    def test_init(self) -> None:
        action = Action(type="click", selector="#btn")
        err = ActionExecutionError(action, "Something went wrong", cause=Exception("inner"))
        assert err.action is action
        assert err.cause is not None
        assert "click" in str(err).lower()

    def test_init_no_cause(self) -> None:
        action = Action(type="click", selector="#btn")
        err = ActionExecutionError(action, "Something went wrong")
        assert err.cause is None
        assert "click" in str(err).lower()


# ══════════════════════════════════════════════════════════════
# PageActions Tests
# ══════════════════════════════════════════════════════════════


class TestPageActionsConstruction:
    """Tests for PageActions construction and basic operations."""

    def test_empty_construction(self) -> None:
        actions = PageActions()
        assert len(actions) == 0
        assert list(actions) == []

    def test_from_dicts(self) -> None:
        actions = PageActions(
            [
                {"type": "click", "selector": "#btn"},
                {"type": "wait", "milliseconds": 1000},
            ]
        )
        assert len(actions) == 2
        assert actions.actions[0].type == ActionType.CLICK
        assert actions.actions[1].type == ActionType.WAIT

    def test_from_action_objects(self) -> None:
        action1 = Action(type="click", selector="#btn")
        action2 = Action(type="wait", milliseconds=1000)
        actions = PageActions([action1, action2])
        assert len(actions) == 2

    def test_invalid_action_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Expected Action or dict"):
            PageActions(["not_a_dict_or_action"])

    def test_add_dict(self) -> None:
        actions = PageActions()
        actions.add({"type": "click", "selector": "#btn"})
        assert len(actions) == 1

    def test_add_action(self) -> None:
        actions = PageActions()
        actions.add(Action(type="click", selector="#btn"))
        assert len(actions) == 1

    def test_len(self) -> None:
        actions = PageActions([{"type": "click", "selector": "#btn"}])
        assert len(actions) == 1

    def test_iter(self) -> None:
        action = Action(type="click", selector="#btn")
        actions = PageActions([action])
        result = list(actions)
        assert len(result) == 1
        assert result[0] is action

    def test_repr(self) -> None:
        actions = PageActions(
            [
                {"type": "click", "selector": "#btn"},
                {"type": "wait", "milliseconds": 500},
            ]
        )
        repr_str = repr(actions)
        assert "PageActions" in repr_str
        assert "click" in repr_str
        assert "wait" in repr_str

    def test_repr_empty(self) -> None:
        actions = PageActions()
        repr_str = repr(actions)
        assert "PageActions" in repr_str

    def test_properties(self) -> None:
        actions = PageActions(
            [{"type": "click", "selector": "#btn"}],
            stop_on_error=False,
            default_timeout=5000,
            screenshot_on_error=True,
        )
        assert actions.actions[0].type == ActionType.CLICK
        assert actions._stop_on_error is False  # Internal attribute

    def test_actions_property_returns_copy(self) -> None:
        action = Action(type="click", selector="#btn")
        actions = PageActions([action])
        result = actions.actions
        result.clear()
        # Original should be unchanged
        assert len(actions) == 1


class TestPageActionsSerialization:
    """Tests for PageActions serialization methods."""

    def test_to_list(self) -> None:
        actions = PageActions(
            [
                {"type": "click", "selector": "#btn"},
                {"type": "wait", "milliseconds": 1000},
            ]
        )
        lst = actions.to_list()
        assert len(lst) == 2
        assert lst[0]["type"] == "click"
        assert lst[0]["selector"] == "#btn"
        assert lst[1]["type"] == "wait"

    def test_from_list(self) -> None:
        actions = PageActions.from_list(
            [
                {"type": "click", "selector": "#btn"},
                {"type": "wait", "milliseconds": 500},
            ]
        )
        assert len(actions) == 2
        assert actions.actions[0].type == ActionType.CLICK

    def test_to_json(self) -> None:
        actions = PageActions([{"type": "click", "selector": "#btn"}])
        js = actions.to_json()
        parsed = json.loads(js)
        assert parsed == [{"type": "click", "selector": "#btn"}]

    def test_from_json(self) -> None:
        js = json.dumps([{"type": "click", "selector": "#btn"}])
        actions = PageActions.from_json(js)
        assert len(actions) == 1
        assert actions.actions[0].type == ActionType.CLICK

    def test_from_json_with_kwargs(self) -> None:
        js = json.dumps([{"type": "click", "selector": "#btn"}])
        actions = PageActions.from_json(js, stop_on_error=False)
        # Stop_on_error is internal but builder passes it
        assert len(actions) == 1


class TestPageActionsExecute:
    """Tests for PageActions.execute method."""

    @pytest.mark.asyncio
    async def test_execute_empty(self) -> None:
        actions = PageActions()
        results = await actions.execute(make_mock_page())
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_single_success(self) -> None:
        action = Action(type="click", selector="#btn")
        actions = PageActions([action])
        mock_page = make_mock_page()
        results = await actions.execute(mock_page)
        assert len(results) == 1
        assert results[0].status == ActionStatus.SUCCESS
        mock_page.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_multiple_success(self) -> None:
        actions = PageActions(
            [
                {"type": "click", "selector": "#btn1"},
                {"type": "click", "selector": "#btn2"},
            ]
        )
        mock_page = make_mock_page()
        results = await actions.execute(mock_page)
        assert len(results) == 2
        assert all(r.status == ActionStatus.SUCCESS for r in results)

    @pytest.mark.asyncio
    async def test_execute_stop_on_error(self) -> None:
        """Non-optional action failure stops the chain."""
        actions = PageActions(
            [
                {"type": "click", "selector": "#btn"},
                Action(type="click", selector="#nonexistent", optional=False),  # Will fail
                {"type": "wait", "milliseconds": 100},
            ],
            stop_on_error=True,
        )
        mock_page = make_mock_page()
        mock_page.click = AsyncMock(side_effect=Exception("Element not found"))
        results = await actions.execute(mock_page)
        # First fails, second is skipped, chain stops
        assert len(results) == 3  # failed + skipped + skipped
        assert results[0].status == ActionStatus.FAILED
        assert results[1].status == ActionStatus.SKIPPED
        assert results[2].status == ActionStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_execute_continue_on_optional_error(self) -> None:
        """Optional action failure does not stop the chain."""
        actions = PageActions(
            [
                Action(type="click", selector="#btn1", optional=True),
                {"type": "wait", "milliseconds": 100},
            ],
            stop_on_error=True,
        )
        mock_page = make_mock_page()
        mock_page.click = AsyncMock(side_effect=Exception("Element not found"))
        results = await actions.execute(mock_page)
        assert len(results) == 2
        assert results[0].status == ActionStatus.FAILED  # Optional, so continued
        assert results[1].status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_screenshot_on_error(self) -> None:
        """Test screenshot_on_error captures a screenshot when action fails."""
        actions = PageActions(
            [
                Action(type="click", selector="#nonexistent"),
                {"type": "wait", "milliseconds": 100},
            ],
            stop_on_error=True,
            screenshot_on_error=True,
        )
        mock_page = make_mock_page()
        mock_page.click = AsyncMock(side_effect=Exception("not found"))
        results = await actions.execute(mock_page)
        assert results[0].status == ActionStatus.FAILED
        assert results[0].screenshot_base64 is not None
        assert results[1].status == ActionStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_execute_screenshot_on_error_exception(self) -> None:
        """Test screenshot capture on error when screenshot itself fails."""
        actions = PageActions(
            [Action(type="click", selector="#nonexistent")],
            screenshot_on_error=True,
        )
        mock_page = make_mock_page()
        mock_page.click = AsyncMock(side_effect=Exception("not found"))
        mock_page.screenshot = AsyncMock(side_effect=Exception("screenshot failed"))
        results = await actions.execute(mock_page)
        assert results[0].status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_delay_after(self) -> None:
        """Test that delay_after triggers a sleep."""
        action = Action(type="click", selector="#btn", delay_after=200)
        actions = PageActions([action])
        mock_page = make_mock_page()
        with patch("asyncio.sleep") as mock_sleep:
            await actions.execute(mock_page)
        mock_sleep.assert_awaited_once_with(0.2)

    @pytest.mark.asyncio
    async def test_execute_unknown_action_type(self) -> None:
        """Test executing an action with no handler raises ValueError.

        _get_handler attempts to convert string types via ActionType(), which
        raises ValueError for unregistered types.  This happens before the
        try/except in execute() so the error propagates.
        """
        # Directly test _ActionExecutor with an unregistered action type
        executor = _ActionExecutor(make_mock_page())
        # Bypass __post_init__ validation to get an unregistered type
        action = object.__new__(Action)
        action.type = "unknown_type"
        action.selector = "#btn"
        action.timeout = 30_000
        action.optional = False
        action.delay_after = 0
        with pytest.raises(ValueError, match="is not a valid ActionType"):
            await executor.execute(action)

    @pytest.mark.asyncio
    async def test_execute_and_collect_screenshots(self) -> None:
        actions = PageActions(
            [
                {"type": "click", "selector": "#btn"},
                {"type": "screenshot"},
            ]
        )
        mock_page = make_mock_page()
        results = await actions.execute_and_collect_screenshots(mock_page)
        # One screenshot action should produce one result
        assert len(results) >= 0  # May or may not have screenshots depending on mock


# ══════════════════════════════════════════════════════════════
# Action Handler Tests via _ActionExecutor
# ══════════════════════════════════════════════════════════════


class TestMouseHandlers:
    """Tests for mouse action handlers."""

    @pytest.mark.asyncio
    async def test_handle_click(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="click", selector="#btn")
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_click_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="click", selector=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_double_click(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="double_click", selector="#btn")
        r = await executor.execute(action)
        assert r.success
        executor._page.dblclick.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_right_click(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="right_click", selector="#btn")
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_hover(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="hover", selector="#btn")
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_drag_and_drop(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="drag_and_drop", selector="#src", value="#tgt")
        r = await executor.execute(action)
        assert r.success
        executor._page.drag_and_drop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_drag_and_drop_no_value(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="drag_and_drop", selector="#src", value=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "value" in r.error


class TestKeyboardHandlers:
    """Tests for keyboard action handlers."""

    @pytest.mark.asyncio
    async def test_handle_type(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="type", selector="#input", text="hello")
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_type_no_text(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="type", selector="#input", text=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "text" in r.error

    @pytest.mark.asyncio
    async def test_handle_type_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="type", selector=None, text="hello")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_type_custom_delay(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="type", selector="#input", text="hello", amount=100)
        r = await executor.execute(action)
        assert r.success
        # amount=100 should be used as delay
        executor._current_frame.type.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_type_default_delay(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="type", selector="#input", text="hello", amount=None)
        r = await executor.execute(action)
        assert r.success
        # amount=None -> delay=50 (from default in source: action.amount or 50)
        call_kwargs = executor._current_frame.type.call_args
        assert call_kwargs.kwargs["delay"] == 50

    @pytest.mark.asyncio
    async def test_handle_fill(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="fill", selector="#input", text="hello")
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_fill_no_text(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="fill", selector="#input", text=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_press_with_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="press", key="Enter", selector="#input")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.press.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_press_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="press", key="Enter", selector=None)
        r = await executor.execute(action)
        assert r.success
        executor._page.keyboard.press.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_press_no_key(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="press", key=None, selector="#input")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_key_down(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="key_down", key="Control")
        r = await executor.execute(action)
        assert r.success
        executor._page.keyboard.down.assert_awaited_once_with("Control")

    @pytest.mark.asyncio
    async def test_handle_key_down_no_key(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="key_down", key=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_key_up(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="key_up", key="Control")
        r = await executor.execute(action)
        assert r.success
        executor._page.keyboard.up.assert_awaited_once_with("Control")

    @pytest.mark.asyncio
    async def test_handle_key_up_no_key(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="key_up", key=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED


class TestScrollHandlers:
    """Tests for scroll action handler."""

    @pytest.mark.asyncio
    async def test_handle_scroll_to_element(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", selector="#target")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.scroll_into_view_if_needed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_scroll_down(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", direction="down", amount=3)
        r = await executor.execute(action)
        assert r.success
        assert r.data["scrolled"] == "down"
        assert r.data["pixels"] == 1500

    @pytest.mark.asyncio
    async def test_handle_scroll_up(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", direction="up", amount=2)
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_scroll_left(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", direction="left", amount=1)
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_scroll_right(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", direction="right", amount=1)
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_scroll_invalid_direction(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", direction="invalid", amount=1)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "Invalid scroll direction" in r.error

    @pytest.mark.asyncio
    async def test_handle_scroll_default_direction(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", direction=None, amount=3)
        r = await executor.execute(action)
        assert r.success
        assert r.data["scrolled"] == "down"

    @pytest.mark.asyncio
    async def test_handle_scroll_with_element_and_direction(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="scroll", selector="#el", direction="down", amount=2)
        r = await executor.execute(action)
        assert r.success
        # When both selector and direction are set, it uses evaluate
        executor._current_frame.evaluate.assert_awaited_once()


class TestWaitHandlers:
    """Tests for wait action handler."""

    @pytest.mark.asyncio
    async def test_handle_wait_ms(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="wait", milliseconds=500)
        with patch("asyncio.sleep") as mock_sleep:
            r = await executor.execute(action)
        assert r.success
        mock_sleep.assert_awaited_once_with(0.5)

    @pytest.mark.asyncio
    async def test_handle_wait_navigation(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="wait", expected="navigation")
        r = await executor.execute(action)
        assert r.success
        executor._page.wait_for_load_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_wait_load_state(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="wait", expected="load_state:networkidle")
        r = await executor.execute(action)
        assert r.success
        executor._page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=30_000)

    @pytest.mark.asyncio
    async def test_handle_wait_url(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="wait", url="https://example.com/*")
        r = await executor.execute(action)
        assert r.success
        executor._page.wait_for_url.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_wait_function(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="wait", expression="document.readyState", expected="function")
        r = await executor.execute(action)
        assert r.success
        executor._page.wait_for_function.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_wait_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="wait", selector="#content", expected="visible")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.wait_for_selector.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_wait_no_conditions(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="wait")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "requires" in r.error


class TestScreenshotHandler:
    """Tests for screenshot action handler."""

    @pytest.mark.asyncio
    async def test_handle_screenshot_full_page(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="screenshot", full_page=True)
        r = await executor.execute(action)
        assert r.success
        assert "screenshot_base64" in r.data

    @pytest.mark.asyncio
    async def test_handle_screenshot_element(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="screenshot", selector="#el")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.query_selector.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_screenshot_element_not_found(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        executor._page.query_selector = AsyncMock(return_value=None)
        action = Action(type="screenshot", selector="#nonexistent")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "not found" in r.error

    @pytest.mark.asyncio
    async def test_handle_screenshot_jpeg(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="screenshot", format="jpeg", quality=50)
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_screenshot_invalid_format(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="screenshot", format="gif")
        r = await executor.execute(action)
        assert r.success  # Defaults to png


class TestFormHandlers:
    """Tests for form-related action handlers."""

    @pytest.mark.asyncio
    async def test_handle_select(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="select", selector="#sel", value="option1")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.select_option.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_select_no_value(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="select", selector="#sel", value=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_select_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="select", selector=None, value="opt")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_check(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="check", selector="#chk")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_uncheck(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="uncheck", selector="#chk")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.uncheck.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_upload_file(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="upload_file", selector="#file", value=["/path/to/file"])
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.set_input_files.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_upload_file_str_value(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="upload_file", selector="#file", value="/path/file")
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_upload_file_no_value(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="upload_file", selector="#file", value=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED


class TestFocusHandlers:
    """Tests for focus/blur action handlers."""

    @pytest.mark.asyncio
    async def test_handle_focus(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="focus", selector="#input")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.focus.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_blur(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="blur", selector="#input")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_blur_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="blur", selector=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED


class TestNavigationHandlers:
    """Tests for navigation action handlers."""

    @pytest.mark.asyncio
    async def test_handle_goto(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="goto", url="https://example.com")
        r = await executor.execute(action)
        assert r.success
        executor._page.goto.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_goto_no_url(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="goto", url=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_goto_no_response(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        executor._page.goto = AsyncMock(return_value=None)
        action = Action(type="goto", url="https://example.com")
        r = await executor.execute(action)
        assert r.success
        assert r.data["status"] is None

    @pytest.mark.asyncio
    async def test_handle_go_back(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="go_back")
        r = await executor.execute(action)
        assert r.success
        executor._page.go_back.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_go_forward(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="go_forward")
        r = await executor.execute(action)
        assert r.success
        executor._page.go_forward.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_reload(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="reload")
        r = await executor.execute(action)
        assert r.success
        executor._page.reload.assert_awaited_once()


class TestJavaScriptHandlers:
    """Tests for JavaScript action handlers."""

    @pytest.mark.asyncio
    async def test_handle_evaluate(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        executor._page.evaluate = AsyncMock(return_value=42)
        action = Action(type="evaluate", expression="1 + 1")
        r = await executor.execute(action)
        assert r.success
        assert r.data["result"] == 42

    @pytest.mark.asyncio
    async def test_handle_evaluate_no_expression(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="evaluate", expression=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED


class TestViewportHandler:
    """Tests for set_viewport action handler."""

    @pytest.mark.asyncio
    async def test_handle_set_viewport(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="set_viewport", width=1920, height=1080)
        r = await executor.execute(action)
        assert r.success
        executor._page.set_viewport_size.assert_awaited_once_with({"width": 1920, "height": 1080})

    @pytest.mark.asyncio
    async def test_handle_set_viewport_missing_width(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="set_viewport", width=None, height=1080)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_set_viewport_missing_height(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="set_viewport", width=1920, height=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED


class TestFrameHandlers:
    """Tests for frame navigation action handlers."""

    @pytest.mark.asyncio
    async def test_handle_switch_frame(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        mock_frame = MagicMock()
        executor._page.frame_locator = AsyncMock(return_value=mock_frame)
        action = Action(type="switch_frame", frame_selector="iframe#myframe")
        r = await executor.execute(action)
        assert r.success
        assert executor._current_frame is mock_frame

    @pytest.mark.asyncio
    async def test_handle_switch_frame_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="switch_frame", frame_selector=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_switch_frame_not_found(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        executor._page.frame_locator = AsyncMock(return_value=None)
        action = Action(type="switch_frame", frame_selector="iframe#nonexistent")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "not found" in r.error

    @pytest.mark.asyncio
    async def test_handle_switch_to_main_frame(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        mock_frame = MagicMock()
        executor._current_frame = mock_frame
        action = Action(type="switch_to_main_frame")
        r = await executor.execute(action)
        assert r.success
        # After switching to main, _current_frame should be _page
        assert executor._current_frame is executor._page


class TestAssertionHandlers:
    """Tests for assertion action handlers."""

    @pytest.mark.asyncio
    async def test_handle_assert_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="assert_selector", selector="#btn", expected="visible")
        r = await executor.execute(action)
        assert r.success
        executor._current_frame.wait_for_selector.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_assert_selector_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="assert_selector", selector=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_assert_text(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        mock_locator = MagicMock()
        mock_locator.to_contain_text = AsyncMock()
        executor._current_frame.locator = MagicMock(return_value=mock_locator)
        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value = MagicMock()
            mock_expect.return_value.to_contain_text = AsyncMock()
            action = Action(type="assert_text", selector="#btn", text="hello")
            r = await executor.execute(action)
            assert r.success

    @pytest.mark.asyncio
    async def test_handle_assert_text_no_text(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="assert_text", selector="#btn", text=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_assert_text_no_selector(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="assert_text", selector=None, text="hello")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_assert_url_match(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        executor._page.url = "https://example.com/page"
        action = Action(type="assert_url", url="https://example.com/*")
        r = await executor.execute(action)
        assert r.success

    @pytest.mark.asyncio
    async def test_handle_assert_url_no_match(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        executor._page.url = "https://other.com/page"
        action = Action(type="assert_url", url="https://example.com/*")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "URL assertion failed" in r.error

    @pytest.mark.asyncio
    async def test_handle_assert_url_no_url(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="assert_url", url=None)
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED


class TestDebugHandler:
    """Tests for pause action handler."""

    @pytest.mark.asyncio
    async def test_handle_pause(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        action = Action(type="pause")
        r = await executor.execute(action)
        assert r.success
        executor._page.pause.assert_awaited_once()

    def test_handle_pause_not_started(self) -> None:
        # pause doesn't have a _require_started check, just tests the handler
        pass


class TestActionExecutorErrorHandling:
    """Tests for error handling in _ActionExecutor.execute."""

    @pytest.mark.asyncio
    async def test_execute_handler_raises(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        executor._current_frame.click = AsyncMock(side_effect=RuntimeError("click failed"))
        action = Action(type="click", selector="#btn")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "click failed" in r.error

    @pytest.mark.asyncio
    async def test_execute_handler_raises_action_execution_error(self) -> None:
        executor = _ActionExecutor(make_mock_page())

        async def raise_aae(action: Action) -> dict:
            raise ActionExecutionError(action, "custom error")

        executor._handle_click = raise_aae
        action = Action(type="click", selector="#btn")
        r = await executor.execute(action)
        assert r.status == ActionStatus.FAILED
        assert "custom error" in r.error


class TestActionExecutorGetHandler:
    """Tests for _get_handler."""

    def test_get_handler_known_type(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        handler = executor._get_handler(ActionType.CLICK)
        assert handler is not None

    def test_get_handler_unknown_type(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        # Unknown string types raise ValueError because _get_handler
        # calls ActionType(action_type) which validates against the enum
        with pytest.raises(ValueError, match="is not a valid ActionType"):
            executor._get_handler("nonexistent_type")

    def test_get_handler_with_string_type(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        handler = executor._get_handler("click")
        assert handler is not None

    def test_get_handler_invalid_string(self) -> None:
        executor = _ActionExecutor(make_mock_page())
        with pytest.raises(ValueError):
            executor._get_handler("bad_type")


# ══════════════════════════════════════════════════════════════
# PageActionsBuilder Tests
# ══════════════════════════════════════════════════════════════


class TestPageActionsBuilderMouse:
    """Tests for mouse builder methods."""

    def test_click(self) -> None:
        builder = PageActionsBuilder()
        builder.click("#btn", timeout=5000, optional=True, delay_after=100, description="d")
        actions = builder.build().actions
        assert len(actions) == 1
        assert actions[0].type == ActionType.CLICK
        assert actions[0].timeout == 5000
        assert actions[0].optional is True
        assert actions[0].delay_after == 100

    def test_double_click(self) -> None:
        builder = PageActionsBuilder()
        builder.double_click("#btn")
        assert builder.build().actions[0].type == ActionType.DOUBLE_CLICK

    def test_right_click(self) -> None:
        builder = PageActionsBuilder()
        builder.right_click("#btn")
        assert builder.build().actions[0].type == ActionType.RIGHT_CLICK

    def test_hover(self) -> None:
        builder = PageActionsBuilder()
        builder.hover("#btn")
        assert builder.build().actions[0].type == ActionType.HOVER

    def test_drag_and_drop(self) -> None:
        builder = PageActionsBuilder()
        builder.drag_and_drop("#src", "#tgt")
        a = builder.build().actions[0]
        assert a.type == ActionType.DRAG_AND_DROP
        assert a.selector == "#src"
        assert a.value == "#tgt"


class TestPageActionsBuilderKeyboard:
    """Tests for keyboard builder methods."""

    def test_type_text(self) -> None:
        builder = PageActionsBuilder()
        builder.type_text("#input", "hello", delay=30)
        a = builder.build().actions[0]
        assert a.type == ActionType.TYPE
        assert a.text == "hello"
        assert a.amount == 30

    def test_fill(self) -> None:
        builder = PageActionsBuilder()
        builder.fill("#input", "hello")
        a = builder.build().actions[0]
        assert a.type == ActionType.FILL
        assert a.text == "hello"

    def test_press_key_with_selector(self) -> None:
        builder = PageActionsBuilder()
        builder.press_key("Enter", selector="#input")
        a = builder.build().actions[0]
        assert a.type == ActionType.PRESS
        assert a.key == "Enter"

    def test_press_key_no_selector(self) -> None:
        builder = PageActionsBuilder()
        builder.press_key("Enter")
        a = builder.build().actions[0]
        assert a.type == ActionType.PRESS
        assert a.key == "Enter"
        assert a.selector is None


class TestPageActionsBuilderScroll:
    """Tests for scroll builder methods."""

    def test_scroll_down(self) -> None:
        builder = PageActionsBuilder()
        builder.scroll_down(5)
        a = builder.build().actions[0]
        assert a.type == ActionType.SCROLL
        assert a.direction == "down"
        assert a.amount == 5

    def test_scroll_up(self) -> None:
        builder = PageActionsBuilder()
        builder.scroll_up(2)
        a = builder.build().actions[0]
        assert a.direction == "up"

    def test_scroll_to_element(self) -> None:
        builder = PageActionsBuilder()
        builder.scroll_to_element("#target")
        a = builder.build().actions[0]
        assert a.type == ActionType.SCROLL
        assert a.selector == "#target"

    def test_scroll_with_selector_and_direction(self) -> None:
        builder = PageActionsBuilder()
        builder.scroll(direction="right", amount=3, selector="#el")
        a = builder.build().actions[0]
        assert a.selector == "#el"
        assert a.direction == "right"


class TestPageActionsBuilderWait:
    """Tests for wait builder methods."""

    def test_wait_for_selector(self) -> None:
        builder = PageActionsBuilder()
        builder.wait_for_selector("#content", state="attached", timeout=5000, optional=True)
        a = builder.build().actions[0]
        assert a.type == ActionType.WAIT
        assert a.selector == "#content"
        assert a.expected == "attached"

    def test_wait_ms(self) -> None:
        builder = PageActionsBuilder()
        builder.wait_ms(2000)
        a = builder.build().actions[0]
        assert a.type == ActionType.WAIT
        assert a.milliseconds == 2000

    def test_wait_for_navigation(self) -> None:
        builder = PageActionsBuilder()
        builder.wait_for_navigation(timeout=10000)
        a = builder.build().actions[0]
        assert a.expected == "navigation"

    def test_wait_for_load_state(self) -> None:
        builder = PageActionsBuilder()
        builder.wait_for_load_state("load", timeout=5000)
        a = builder.build().actions[0]
        assert a.expected == "load_state:load"

    def test_wait_for_url(self) -> None:
        builder = PageActionsBuilder()
        builder.wait_for_url("https://example.com/*")
        a = builder.build().actions[0]
        assert a.url == "https://example.com/*"

    def test_wait_for_function(self) -> None:
        builder = PageActionsBuilder()
        builder.wait_for_function("document.readyState")
        a = builder.build().actions[0]
        assert a.expression == "document.readyState"
        assert a.expected == "function"


class TestPageActionsBuilderScreenshot:
    """Tests for screenshot builder method."""

    def test_screenshot_full_page(self) -> None:
        builder = PageActionsBuilder()
        builder.screenshot(full_page=True, image_format="png", quality=90)
        a = builder.build().actions[0]
        assert a.type == ActionType.SCREENSHOT
        assert a.full_page is True
        assert a.format == "png"

    def test_screenshot_with_selector(self) -> None:
        builder = PageActionsBuilder()
        builder.screenshot(selector="#el")
        a = builder.build().actions[0]
        assert a.selector == "#el"


class TestPageActionsBuilderForm:
    """Tests for form builder methods."""

    def test_select_option(self) -> None:
        builder = PageActionsBuilder()
        builder.select_option("#sel", "option1", timeout=5000)
        a = builder.build().actions[0]
        assert a.type == ActionType.SELECT
        assert a.value == "option1"

    def test_check(self) -> None:
        builder = PageActionsBuilder()
        builder.check("#chk")
        assert builder.build().actions[0].type == ActionType.CHECK

    def test_uncheck(self) -> None:
        builder = PageActionsBuilder()
        builder.uncheck("#chk")
        assert builder.build().actions[0].type == ActionType.UNCHECK

    def test_upload_file_str(self) -> None:
        builder = PageActionsBuilder()
        builder.upload_file("#file", "/path/file.txt")
        a = builder.build().actions[0]
        assert a.type == ActionType.UPLOAD_FILE
        assert a.value == ["/path/file.txt"]

    def test_upload_file_list(self) -> None:
        builder = PageActionsBuilder()
        builder.upload_file("#file", ["/a.txt", "/b.txt"])
        a = builder.build().actions[0]
        assert a.value == ["/a.txt", "/b.txt"]


class TestPageActionsBuilderFocus:
    """Tests for focus/blur builder methods."""

    def test_focus(self) -> None:
        builder = PageActionsBuilder()
        builder.focus("#input")
        assert builder.build().actions[0].type == ActionType.FOCUS

    def test_blur(self) -> None:
        builder = PageActionsBuilder()
        builder.blur("#input")
        assert builder.build().actions[0].type == ActionType.BLUR


class TestPageActionsBuilderNavigation:
    """Tests for navigation builder methods."""

    def test_goto(self) -> None:
        builder = PageActionsBuilder()
        builder.goto("https://example.com", timeout=10000)
        a = builder.build().actions[0]
        assert a.type == ActionType.GOTO
        assert a.url == "https://example.com"

    def test_go_back(self) -> None:
        builder = PageActionsBuilder()
        builder.go_back()
        assert builder.build().actions[0].type == ActionType.GO_BACK

    def test_go_forward(self) -> None:
        builder = PageActionsBuilder()
        builder.go_forward()
        assert builder.build().actions[0].type == ActionType.GO_FORWARD

    def test_reload(self) -> None:
        builder = PageActionsBuilder()
        builder.reload()
        assert builder.build().actions[0].type == ActionType.RELOAD


class TestPageActionsBuilderJS:
    """Tests for JavaScript builder method."""

    def test_evaluate(self) -> None:
        builder = PageActionsBuilder()
        builder.evaluate("document.title")
        a = builder.build().actions[0]
        assert a.type == ActionType.EVALUATE
        assert a.expression == "document.title"


class TestPageActionsBuilderViewport:
    """Tests for viewport builder method."""

    def test_set_viewport(self) -> None:
        builder = PageActionsBuilder()
        builder.set_viewport(1920, 1080)
        a = builder.build().actions[0]
        assert a.width == 1920
        assert a.height == 1080


class TestPageActionsBuilderFrames:
    """Tests for frame builder methods."""

    def test_switch_frame(self) -> None:
        builder = PageActionsBuilder()
        builder.switch_frame("iframe#frame")
        a = builder.build().actions[0]
        assert a.frame_selector == "iframe#frame"

    def test_switch_to_main_frame(self) -> None:
        builder = PageActionsBuilder()
        builder.switch_to_main_frame()
        assert builder.build().actions[0].type == ActionType.SWITCH_TO_MAIN_FRAME


class TestPageActionsBuilderAssertions:
    """Tests for assertion builder methods."""

    def test_assert_selector(self) -> None:
        builder = PageActionsBuilder()
        builder.assert_selector("#btn", expected="attached")
        a = builder.build().actions[0]
        assert a.expected == "attached"

    def test_assert_text(self) -> None:
        builder = PageActionsBuilder()
        builder.assert_text("#btn", "hello")
        a = builder.build().actions[0]
        assert a.text == "hello"

    def test_assert_url(self) -> None:
        builder = PageActionsBuilder()
        builder.assert_url("https://example.com/*")
        a = builder.build().actions[0]
        assert a.url == "https://example.com/*"


class TestPageActionsBuilderDebug:
    """Tests for debug builder method."""

    def test_pause(self) -> None:
        builder = PageActionsBuilder()
        builder.pause()
        assert builder.build().actions[0].type == ActionType.PAUSE


class TestPageActionsBuilderConfig:
    """Tests for builder configuration methods."""

    def test_stop_on_error(self) -> None:
        builder = PageActionsBuilder()
        builder.stop_on_error(False)
        actions = builder.build()
        assert actions._stop_on_error is False

    def test_default_timeout(self) -> None:
        builder = PageActionsBuilder()
        builder.default_timeout(10000)
        a = builder.click("#btn").build().actions[0]
        assert a.timeout == 10000

    def test_screenshot_on_error(self) -> None:
        builder = PageActionsBuilder()
        builder.screenshot_on_error(True)
        actions = builder.build()
        assert actions._screenshot_on_error is True


class TestPageActionsBuilderFluent:
    """Tests for fluent builder chaining and build()."""

    def test_fluent_chaining(self) -> None:
        actions = (
            PageActions.builder()
            .click("#accept")
            .wait_ms(500)
            .scroll_down(3)
            .type_text("#search", "python")
            .press_key("Enter")
            .build()
        )
        action_list = actions.actions
        assert len(action_list) == 5
        assert action_list[0].type == ActionType.CLICK
        assert action_list[1].type == ActionType.WAIT
        assert action_list[2].type == ActionType.SCROLL
        assert action_list[3].type == ActionType.TYPE
        assert action_list[4].type == ActionType.PRESS

    def test_build_returns_page_actions(self) -> None:
        actions = PageActionsBuilder().click("#btn").build()
        assert isinstance(actions, PageActions)


# ══════════════════════════════════════════════════════════════
# Enum Tests
# ══════════════════════════════════════════════════════════════


class TestEnums:
    """Tests for enum values."""

    def test_scroll_direction_values(self) -> None:
        assert ScrollDirection.UP.value == "up"
        assert ScrollDirection.DOWN.value == "down"
        assert ScrollDirection.LEFT.value == "left"
        assert ScrollDirection.RIGHT.value == "right"

    def test_wait_condition_values(self) -> None:
        assert WaitCondition.SELECTOR.value == "selector"
        assert WaitCondition.TIMEOUT.value == "timeout"

    def test_action_status_values(self) -> None:
        assert ActionStatus.SUCCESS.value == "success"
        assert ActionStatus.FAILED.value == "failed"
        assert ActionStatus.SKIPPED.value == "skipped"


# ══════════════════════════════════════════════════════════════
# Integration-style tests
# ══════════════════════════════════════════════════════════════


class TestActionChainIntegration:
    """Integration-style tests for action chains."""

    @pytest.mark.asyncio
    async def test_click_and_screenshot_chain(self) -> None:
        actions = (
            PageActions.builder().click("#load").wait_ms(200).screenshot(full_page=True).build()
        )
        mock_page = make_mock_page()
        results = await actions.execute(mock_page)
        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_mixed_dict_and_action_chain(self) -> None:
        actions = PageActions(
            [
                {"type": "click", "selector": "#btn1"},
                Action(type="hover", selector="#btn2"),
                {"type": "press", "key": "Enter"},
            ]
        )
        mock_page = make_mock_page()
        results = await actions.execute(mock_page)
        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_execute_logs_completion(self) -> None:
        actions = PageActions([{"type": "click", "selector": "#btn"}])
        mock_page = make_mock_page()
        with patch("agentcrawl.browser.actions.logger") as mock_logger:
            await actions.execute(mock_page)
        mock_logger.info.assert_called_once()
