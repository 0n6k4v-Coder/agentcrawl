"""
AgentCrawl — Browser Page Actions
===================================

Provides a declarative, chainable action system for interacting with
web pages before content extraction. Inspired by Firecrawl's /interact
endpoint and Playwright's page API.

Actions are defined as dictionaries or Action objects and executed
sequentially against a Playwright Page instance.

Supported Action Types:
    - click, double_click, right_click, hover
    - type, fill, press, key_down, key_up
    - scroll (direction, to element, to position)
    - wait (selector, timeout, navigation, load_state, url)
    - screenshot (full page, element, viewport)
    - select (dropdown option)
    - check, uncheck (checkboxes / radio buttons)
    - focus, blur
    - drag_and_drop
    - upload_file
    - evaluate (JavaScript execution)
    - goto (navigate to URL)
    - go_back, go_forward, reload
    - set_viewport
    - switch_frame (iframe navigation)
    - assert_selector (verify element exists / not exists)
    - pause (debugging)

Usage:
    from agentcrawl.browser.actions import PageActions, Action

    # Dictionary-based (simple)
    actions = PageActions([
        {"type": "wait", "selector": "#content-loaded"},
        {"type": "click", "selector": "#load-more"},
        {"type": "scroll", "direction": "down", "amount": 3},
        {"type": "type", "selector": "#search-input", "text": "query"},
        {"type": "press", "key": "Enter"},
        {"type": "wait", "milliseconds": 2000},
        {"type": "screenshot"},
    ])

    # Builder pattern (fluent)
    actions = (
        PageActions.builder()
        .wait_for_selector("#content-loaded")
        .click("#load-more")
        .scroll_down(3)
        .type_text("#search-input", "query")
        .press_key("Enter")
        .wait_ms(2000)
        .screenshot()
        .build()
    )

    # Execute against a Playwright page
    results = await actions.execute(page)
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger("agentcrawl.browser.actions")


# ══════════════════════════════════════════════════════════════
# Types & Enums
# ══════════════════════════════════════════════════════════════


class ActionType(str, Enum):
    """All supported page action types."""

    # Mouse
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    HOVER = "hover"
    DRAG_AND_DROP = "drag_and_drop"

    # Keyboard
    TYPE = "type"
    FILL = "fill"
    PRESS = "press"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"

    # Scroll
    SCROLL = "scroll"

    # Wait
    WAIT = "wait"

    # Screenshot
    SCREENSHOT = "screenshot"

    # Form elements
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    UPLOAD_FILE = "upload_file"

    # Focus
    FOCUS = "focus"
    BLUR = "blur"

    # Navigation
    GOTO = "goto"
    GO_BACK = "go_back"
    GO_FORWARD = "go_forward"
    RELOAD = "reload"

    # JavaScript
    EVALUATE = "evaluate"

    # Viewport
    SET_VIEWPORT = "set_viewport"

    # Frames
    SWITCH_FRAME = "switch_frame"
    SWITCH_TO_MAIN_FRAME = "switch_to_main_frame"

    # Assertions
    ASSERT_SELECTOR = "assert_selector"
    ASSERT_TEXT = "assert_text"
    ASSERT_URL = "assert_url"

    # Debug
    PAUSE = "pause"


class ScrollDirection(str, Enum):
    """Scroll direction."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class WaitCondition(str, Enum):
    """Wait condition type."""

    SELECTOR = "selector"
    TIMEOUT = "timeout"
    NAVIGATION = "navigation"
    LOAD_STATE = "load_state"
    URL = "url"
    FUNCTION = "function"


class ActionStatus(str, Enum):
    """Result status of an executed action."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ══════════════════════════════════════════════════════════════
# Action Data Model
# ══════════════════════════════════════════════════════════════


@dataclass
class Action:
    """
    A single page action to be executed against a Playwright page.

    Attributes:
        type: The action type (see ActionType enum).
        selector: CSS or XPath selector for the target element.
        text: Text to type or fill.
        key: Key to press (e.g., 'Enter', 'Tab', 'Control+a').
        direction: Scroll direction.
        amount: Scroll amount (number of steps or pixels).
        milliseconds: Wait duration in milliseconds.
        url: URL for navigation actions.
        value: Value for select/check actions.
        expression: JavaScript expression for evaluate.
        width: Viewport width.
        height: Viewport height.
        frame_selector: Selector for iframe to switch into.
        full_page: Whether screenshot captures full page.
        format: Screenshot format ('png' or 'jpeg').
        quality: JPEG quality (1-100).
        expected: Expected state for assertions ('visible', 'hidden', 'attached', 'detached').
        timeout: Per-action timeout in milliseconds.
        description: Human-readable description for logging.
        optional: If True, failure won't stop the action chain.
        delay_after: Milliseconds to wait after this action completes.
    """

    type: ActionType | str
    selector: str | None = None
    text: str | None = None
    key: str | None = None
    direction: str | None = None
    amount: int | None = None
    milliseconds: int | None = None
    url: str | None = None
    value: str | list[str] | None = None
    expression: str | None = None
    width: int | None = None
    height: int | None = None
    frame_selector: str | None = None
    full_page: bool = True
    format: str = "png"
    quality: int = 80
    expected: str = "visible"
    timeout: int = 30_000
    description: str | None = None
    optional: bool = False
    delay_after: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.type, str):
            try:
                self.type = ActionType(self.type)
            except ValueError:
                raise ValueError(
                    f"Unknown action type: '{self.type}'. "
                    f"Available: {', '.join(a.value for a in ActionType)}"
                ) from None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Action:
        """Create an Action from a dictionary."""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "type": self.type.value if isinstance(self.type, ActionType) else self.type
        }
        for f in self.__dataclass_fields__:
            if f == "type":
                continue
            val = getattr(self, f)
            if val is not None and val != self.__dataclass_fields__[f].default:
                result[f] = val
        return result


@dataclass
class ActionResult:
    """Result of executing a single action."""

    action: Action
    status: ActionStatus
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    screenshot_base64: str | None = None

    @property
    def success(self) -> bool:
        return self.status == ActionStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "has_screenshot": self.screenshot_base64 is not None,
        }


# ══════════════════════════════════════════════════════════════
# PageActions — Action Chain
# ══════════════════════════════════════════════════════════════


class PageActions:
    """
    A chain of page actions to execute sequentially.

    Can be constructed from a list of dictionaries, Action objects,
    or via the fluent builder pattern.

    Example:
        # From dictionaries
        actions = PageActions([
            {"type": "click", "selector": "#btn"},
            {"type": "wait", "milliseconds": 1000},
        ])

        # From Action objects
        actions = PageActions([
            Action(type="click", selector="#btn"),
            Action(type="wait", milliseconds=1000),
        ])

        # Builder pattern
        actions = (
            PageActions.builder()
            .click("#btn")
            .wait_ms(1000)
            .build()
        )

        # Execute
        results = await actions.execute(page)
    """

    def __init__(
        self,
        actions: Sequence[Action | dict[str, Any]] | None = None,
        stop_on_error: bool = True,
        default_timeout: int = 30_000,
        screenshot_on_error: bool = False,
    ):
        """
        Args:
            actions: List of Action objects or dictionaries.
            stop_on_error: Stop execution on first non-optional action failure.
            default_timeout: Default timeout for actions (ms).
            screenshot_on_error: Capture screenshot when an action fails.
        """
        self._actions: list[Action] = []
        self._stop_on_error = stop_on_error
        self._default_timeout = default_timeout
        self._screenshot_on_error = screenshot_on_error

        if actions:
            for a in actions:
                if isinstance(a, dict):
                    self._actions.append(Action.from_dict(a))
                elif isinstance(a, Action):
                    self._actions.append(a)
                else:
                    raise TypeError(f"Expected Action or dict, got {type(a)}")

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def actions(self) -> list[Action]:
        """Get the list of actions in this chain."""
        return list(self._actions)

    def __len__(self) -> int:
        return len(self._actions)

    def __iter__(self) -> Iterator[Action]:
        return iter(self._actions)

    def __repr__(self) -> str:
        types = [
            a.type.value if isinstance(a.type, ActionType) else str(a.type) for a in self._actions
        ]
        return f"PageActions({types})"

    # ──────────────────────────────────────────────────────────
    # Builder Pattern
    # ──────────────────────────────────────────────────────────

    @classmethod
    def builder(cls) -> PageActionsBuilder:
        """Create a new fluent builder."""
        return PageActionsBuilder()

    def add(self, action: Action | dict[str, Any]) -> PageActions:
        """Add an action to the chain (mutates in place)."""
        if isinstance(action, dict):
            self._actions.append(Action.from_dict(action))
        else:
            self._actions.append(action)
        return self

    # ──────────────────────────────────────────────────────────
    # Execution
    # ──────────────────────────────────────────────────────────

    async def execute(self, page: Any) -> list[ActionResult]:
        """
        Execute all actions sequentially against a Playwright page.

        Args:
            page: Playwright Page instance.

        Returns:
            List of ActionResult objects, one per action.

        Raises:
            ActionExecutionError: If a non-optional action fails and
                                  stop_on_error is True.
        """
        results: list[ActionResult] = []
        executor = _ActionExecutor(page, self._default_timeout)

        for i, action in enumerate(self._actions):
            logger.debug(
                "Executing action %d/%d: %s %s",
                i + 1,
                len(self._actions),
                action.type.value if isinstance(action.type, ActionType) else action.type,
                action.selector or "",
            )

            result = await executor.execute(action)
            results.append(result)

            if result.status == ActionStatus.FAILED:
                if self._screenshot_on_error:
                    try:
                        screenshot_bytes = await page.screenshot(full_page=False)
                        result.screenshot_base64 = base64.b64encode(screenshot_bytes).decode()
                    except Exception as e:
                        logger.debug("Failed to capture screenshot on error: %s", e)

                if not action.optional and self._stop_on_error:
                    logger.error(
                        "Action %d failed (stopping chain): %s",
                        i + 1,
                        result.error,
                    )
                    # Mark remaining actions as skipped
                    for remaining in self._actions[i + 1 :]:
                        results.append(
                            ActionResult(
                                action=remaining,
                                status=ActionStatus.SKIPPED,
                                error=f"Skipped due to failure of action {i + 1}",
                            )
                        )
                    break

            # Post-action delay
            if action.delay_after > 0:
                await asyncio.sleep(action.delay_after / 1000.0)

        succeeded = sum(1 for r in results if r.status == ActionStatus.SUCCESS)
        failed = sum(1 for r in results if r.status == ActionStatus.FAILED)
        skipped = sum(1 for r in results if r.status == ActionStatus.SKIPPED)

        logger.info(
            "Action chain complete: %d succeeded, %d failed, %d skipped",
            succeeded,
            failed,
            skipped,
        )

        return results

    async def execute_and_collect_screenshots(self, page: Any) -> list[str]:
        """
        Execute actions and return base64 screenshots from all
        screenshot actions in the chain.

        Args:
            page: Playwright Page instance.

        Returns:
            List of base64-encoded screenshot strings.
        """
        results = await self.execute(page)
        return [r.screenshot_base64 for r in results if r.screenshot_base64 is not None]

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_list(self) -> list[dict[str, Any]]:
        """Convert to a list of dictionaries."""
        return [a.to_dict() for a in self._actions]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]], **kwargs: Any) -> PageActions:
        """Create from a list of dictionaries."""
        return cls(actions=data, **kwargs)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json

        return json.dumps(self.to_list(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str, **kwargs: Any) -> PageActions:
        """Create from a JSON string."""
        import json

        data = json.loads(json_str)
        return cls.from_list(data, **kwargs)


# ══════════════════════════════════════════════════════════════
# PageActionsBuilder — Fluent Interface
# ══════════════════════════════════════════════════════════════


class PageActionsBuilder:
    """
    Fluent builder for constructing PageActions chains.

    Example:
        actions = (
            PageActions.builder()
            .wait_for_selector("#app-loaded")
            .click("#accept-cookies")
            .scroll_down(3)
            .type_text("#search", "python tutorial")
            .press_key("Enter")
            .wait_for_navigation()
            .wait_ms(1000)
            .screenshot(full_page=True)
            .build()
        )
    """

    def __init__(self) -> None:
        self._actions: list[Action] = []
        self._stop_on_error: bool = True
        self._default_timeout: int = 30_000
        self._screenshot_on_error: bool = False

    # ── Mouse Actions ─────────────────────────────────────────

    def click(
        self,
        selector: str,
        timeout: int | None = None,
        optional: bool = False,
        delay_after: int = 0,
        description: str | None = None,
    ) -> PageActionsBuilder:
        """Click an element."""
        self._actions.append(
            Action(
                type=ActionType.CLICK,
                selector=selector,
                timeout=timeout or self._default_timeout,
                optional=optional,
                delay_after=delay_after,
                description=description or f"Click '{selector}'",
            )
        )
        return self

    def double_click(
        self,
        selector: str,
        timeout: int | None = None,
        optional: bool = False,
    ) -> PageActionsBuilder:
        """Double-click an element."""
        self._actions.append(
            Action(
                type=ActionType.DOUBLE_CLICK,
                selector=selector,
                timeout=timeout or self._default_timeout,
                optional=optional,
                description=f"Double-click '{selector}'",
            )
        )
        return self

    def right_click(
        self,
        selector: str,
        timeout: int | None = None,
        optional: bool = False,
    ) -> PageActionsBuilder:
        """Right-click an element."""
        self._actions.append(
            Action(
                type=ActionType.RIGHT_CLICK,
                selector=selector,
                timeout=timeout or self._default_timeout,
                optional=optional,
                description=f"Right-click '{selector}'",
            )
        )
        return self

    def hover(
        self,
        selector: str,
        timeout: int | None = None,
        optional: bool = False,
    ) -> PageActionsBuilder:
        """Hover over an element."""
        self._actions.append(
            Action(
                type=ActionType.HOVER,
                selector=selector,
                timeout=timeout or self._default_timeout,
                optional=optional,
                description=f"Hover '{selector}'",
            )
        )
        return self

    def drag_and_drop(
        self,
        source: str,
        target: str,
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Drag an element to another element."""
        self._actions.append(
            Action(
                type=ActionType.DRAG_AND_DROP,
                selector=source,
                value=target,
                timeout=timeout or self._default_timeout,
                description=f"Drag '{source}' to '{target}'",
            )
        )
        return self

    # ── Keyboard Actions ──────────────────────────────────────

    def type_text(
        self,
        selector: str,
        text: str,
        delay: int = 50,
        timeout: int | None = None,
        optional: bool = False,
    ) -> PageActionsBuilder:
        """Type text character by character into an element."""
        self._actions.append(
            Action(
                type=ActionType.TYPE,
                selector=selector,
                text=text,
                amount=delay,
                timeout=timeout or self._default_timeout,
                optional=optional,
                description=f"Type '{text[:30]}...' into '{selector}'",
            )
        )
        return self

    def fill(
        self,
        selector: str,
        text: str,
        timeout: int | None = None,
        optional: bool = False,
    ) -> PageActionsBuilder:
        """Fill an input field (faster than type, no key events)."""
        self._actions.append(
            Action(
                type=ActionType.FILL,
                selector=selector,
                text=text,
                timeout=timeout or self._default_timeout,
                optional=optional,
                description=f"Fill '{selector}' with '{text[:30]}...'",
            )
        )
        return self

    def press_key(
        self,
        key: str,
        selector: str | None = None,
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Press a keyboard key (e.g., 'Enter', 'Tab', 'Control+a')."""
        self._actions.append(
            Action(
                type=ActionType.PRESS,
                key=key,
                selector=selector,
                timeout=timeout or self._default_timeout,
                description=f"Press '{key}'",
            )
        )
        return self

    # ── Scroll Actions ────────────────────────────────────────

    def scroll(
        self,
        direction: str = "down",
        amount: int = 3,
        selector: str | None = None,
    ) -> PageActionsBuilder:
        """Scroll the page or a specific element."""
        self._actions.append(
            Action(
                type=ActionType.SCROLL,
                direction=direction,
                amount=amount,
                selector=selector,
                description=f"Scroll {direction} x{amount}",
            )
        )
        return self

    def scroll_down(self, amount: int = 3) -> PageActionsBuilder:
        """Scroll down."""
        return self.scroll(direction="down", amount=amount)

    def scroll_up(self, amount: int = 3) -> PageActionsBuilder:
        """Scroll up."""
        return self.scroll(direction="up", amount=amount)

    def scroll_to_element(self, selector: str) -> PageActionsBuilder:
        """Scroll until an element is visible."""
        self._actions.append(
            Action(
                type=ActionType.SCROLL,
                selector=selector,
                description=f"Scroll to '{selector}'",
            )
        )
        return self

    # ── Wait Actions ──────────────────────────────────────────

    def wait_for_selector(
        self,
        selector: str,
        state: str = "visible",
        timeout: int | None = None,
        optional: bool = False,
    ) -> PageActionsBuilder:
        """Wait for an element to appear."""
        self._actions.append(
            Action(
                type=ActionType.WAIT,
                selector=selector,
                expected=state,
                timeout=timeout or self._default_timeout,
                optional=optional,
                description=f"Wait for '{selector}' ({state})",
            )
        )
        return self

    def wait_ms(self, milliseconds: int) -> PageActionsBuilder:
        """Wait for a fixed duration."""
        self._actions.append(
            Action(
                type=ActionType.WAIT,
                milliseconds=milliseconds,
                description=f"Wait {milliseconds}ms",
            )
        )
        return self

    def wait_for_navigation(self, timeout: int | None = None) -> PageActionsBuilder:
        """Wait for navigation to complete."""
        self._actions.append(
            Action(
                type=ActionType.WAIT,
                expected="navigation",
                timeout=timeout or self._default_timeout,
                description="Wait for navigation",
            )
        )
        return self

    def wait_for_load_state(
        self,
        state: str = "networkidle",
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Wait for page load state ('load', 'domcontentloaded', 'networkidle')."""
        self._actions.append(
            Action(
                type=ActionType.WAIT,
                expected=f"load_state:{state}",
                timeout=timeout or self._default_timeout,
                description=f"Wait for load state '{state}'",
            )
        )
        return self

    def wait_for_url(
        self,
        url: str,
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Wait for URL to match a pattern."""
        self._actions.append(
            Action(
                type=ActionType.WAIT,
                url=url,
                timeout=timeout or self._default_timeout,
                description=f"Wait for URL '{url}'",
            )
        )
        return self

    def wait_for_function(
        self,
        expression: str,
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Wait for a JavaScript function to return truthy."""
        self._actions.append(
            Action(
                type=ActionType.WAIT,
                expression=expression,
                expected="function",
                timeout=timeout or self._default_timeout,
                description=f"Wait for function: {expression[:50]}...",
            )
        )
        return self

    # ── Screenshot Actions ────────────────────────────────────

    def screenshot(
        self,
        full_page: bool = True,
        image_format: str = "png",
        quality: int = 80,
        selector: str | None = None,
    ) -> PageActionsBuilder:
        """Capture a screenshot."""
        desc = "Screenshot (full page)" if full_page else "Screenshot (viewport)"
        if selector:
            desc = f"Screenshot of '{selector}'"
        self._actions.append(
            Action(
                type=ActionType.SCREENSHOT,
                full_page=full_page,
                format=image_format,
                quality=quality,
                selector=selector,
                description=desc,
            )
        )
        return self

    # ── Form Actions ──────────────────────────────────────────

    def select_option(
        self,
        selector: str,
        value: str | list[str],
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Select option(s) in a <select> dropdown."""
        self._actions.append(
            Action(
                type=ActionType.SELECT,
                selector=selector,
                value=value,
                timeout=timeout or self._default_timeout,
                description=f"Select '{value}' in '{selector}'",
            )
        )
        return self

    def check(
        self,
        selector: str,
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Check a checkbox or radio button."""
        self._actions.append(
            Action(
                type=ActionType.CHECK,
                selector=selector,
                timeout=timeout or self._default_timeout,
                description=f"Check '{selector}'",
            )
        )
        return self

    def uncheck(
        self,
        selector: str,
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Uncheck a checkbox."""
        self._actions.append(
            Action(
                type=ActionType.UNCHECK,
                selector=selector,
                timeout=timeout or self._default_timeout,
                description=f"Uncheck '{selector}'",
            )
        )
        return self

    def upload_file(
        self,
        selector: str,
        file_path: str | list[str],
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Upload file(s) via a file input."""
        self._actions.append(
            Action(
                type=ActionType.UPLOAD_FILE,
                selector=selector,
                value=file_path if isinstance(file_path, list) else [file_path],
                timeout=timeout or self._default_timeout,
                description=f"Upload file to '{selector}'",
            )
        )
        return self

    # ── Focus Actions ─────────────────────────────────────────

    def focus(self, selector: str) -> PageActionsBuilder:
        """Focus an element."""
        self._actions.append(
            Action(
                type=ActionType.FOCUS,
                selector=selector,
                description=f"Focus '{selector}'",
            )
        )
        return self

    def blur(self, selector: str) -> PageActionsBuilder:
        """Remove focus from an element."""
        self._actions.append(
            Action(
                type=ActionType.BLUR,
                selector=selector,
                description=f"Blur '{selector}'",
            )
        )
        return self

    # ── Navigation Actions ────────────────────────────────────

    def goto(self, url: str, timeout: int | None = None) -> PageActionsBuilder:
        """Navigate to a URL."""
        self._actions.append(
            Action(
                type=ActionType.GOTO,
                url=url,
                timeout=timeout or self._default_timeout,
                description=f"Navigate to '{url}'",
            )
        )
        return self

    def go_back(self) -> PageActionsBuilder:
        """Navigate back in history."""
        self._actions.append(Action(type=ActionType.GO_BACK, description="Go back"))
        return self

    def go_forward(self) -> PageActionsBuilder:
        """Navigate forward in history."""
        self._actions.append(Action(type=ActionType.GO_FORWARD, description="Go forward"))
        return self

    def reload(self) -> PageActionsBuilder:
        """Reload the page."""
        self._actions.append(Action(type=ActionType.RELOAD, description="Reload page"))
        return self

    # ── JavaScript Actions ────────────────────────────────────

    def evaluate(self, expression: str) -> PageActionsBuilder:
        """Execute JavaScript in the page context."""
        self._actions.append(
            Action(
                type=ActionType.EVALUATE,
                expression=expression,
                description=f"Evaluate: {expression[:50]}...",
            )
        )
        return self

    # ── Viewport Actions ──────────────────────────────────────

    def set_viewport(self, width: int, height: int) -> PageActionsBuilder:
        """Set the browser viewport size."""
        self._actions.append(
            Action(
                type=ActionType.SET_VIEWPORT,
                width=width,
                height=height,
                description=f"Set viewport {width}x{height}",
            )
        )
        return self

    # ── Frame Actions ─────────────────────────────────────────

    def switch_frame(self, selector: str) -> PageActionsBuilder:
        """Switch into an iframe."""
        self._actions.append(
            Action(
                type=ActionType.SWITCH_FRAME,
                frame_selector=selector,
                description=f"Switch to frame '{selector}'",
            )
        )
        return self

    def switch_to_main_frame(self) -> PageActionsBuilder:
        """Switch back to the main frame."""
        self._actions.append(
            Action(
                type=ActionType.SWITCH_TO_MAIN_FRAME,
                description="Switch to main frame",
            )
        )
        return self

    # ── Assertion Actions ─────────────────────────────────────

    def assert_selector(
        self,
        selector: str,
        expected: str = "visible",
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Assert an element's state ('visible', 'hidden', 'attached', 'detached')."""
        self._actions.append(
            Action(
                type=ActionType.ASSERT_SELECTOR,
                selector=selector,
                expected=expected,
                timeout=timeout or self._default_timeout,
                description=f"Assert '{selector}' is {expected}",
            )
        )
        return self

    def assert_text(
        self,
        selector: str,
        text: str,
        timeout: int | None = None,
    ) -> PageActionsBuilder:
        """Assert an element contains specific text."""
        self._actions.append(
            Action(
                type=ActionType.ASSERT_TEXT,
                selector=selector,
                text=text,
                timeout=timeout or self._default_timeout,
                description=f"Assert '{selector}' contains '{text[:30]}'",
            )
        )
        return self

    def assert_url(self, url: str) -> PageActionsBuilder:
        """Assert the current URL matches a pattern."""
        self._actions.append(
            Action(
                type=ActionType.ASSERT_URL,
                url=url,
                description=f"Assert URL matches '{url}'",
            )
        )
        return self

    # ── Debug Actions ─────────────────────────────────────────

    def pause(self) -> PageActionsBuilder:
        """Pause execution (for debugging with Playwright inspector)."""
        self._actions.append(Action(type=ActionType.PAUSE, description="Pause (debug)"))
        return self

    # ── Configuration ─────────────────────────────────────────

    def stop_on_error(self, value: bool = True) -> PageActionsBuilder:
        """Set whether to stop on first error."""
        self._stop_on_error = value
        return self

    def default_timeout(self, ms: int) -> PageActionsBuilder:
        """Set default timeout for all actions."""
        self._default_timeout = ms
        return self

    def screenshot_on_error(self, value: bool = True) -> PageActionsBuilder:
        """Capture screenshot when an action fails."""
        self._screenshot_on_error = value
        return self

    # ── Build ─────────────────────────────────────────────────

    def build(self) -> PageActions:
        """Build the PageActions chain."""
        return PageActions(
            actions=self._actions,
            stop_on_error=self._stop_on_error,
            default_timeout=self._default_timeout,
            screenshot_on_error=self._screenshot_on_error,
        )


# ══════════════════════════════════════════════════════════════
# Action Executor (Internal)
# ══════════════════════════════════════════════════════════════


class ActionExecutionError(Exception):
    """Raised when a page action fails to execute."""

    def __init__(self, action: Action, message: str, cause: Exception | None = None):
        self.action = action
        self.cause = cause
        super().__init__(f"Action '{action.type}' failed: {message}")


class _ActionExecutor:
    """
    Internal executor that maps Action objects to Playwright page calls.

    Not intended for direct use — use PageActions.execute() instead.
    """

    def __init__(self, page: Any, default_timeout: int = 30_000):
        self._page = page
        self._default_timeout = default_timeout
        self._current_frame: Any = page  # Track frame context

    async def execute(self, action: Action) -> ActionResult:
        """Execute a single action and return the result."""
        import time

        start = time.perf_counter()

        handler = self._get_handler(action.type)
        if handler is None:
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                error=f"No handler for action type: {action.type}",
            )

        try:
            data = await handler(action)
            duration = (time.perf_counter() - start) * 1000
            return ActionResult(
                action=action,
                status=ActionStatus.SUCCESS,
                data=data,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            logger.warning(
                "Action '%s' failed: %s (optional=%s)",
                action.type,
                str(e),
                action.optional,
            )
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                error=str(e),
                duration_ms=duration,
            )

    def _get_handler(self, action_type: ActionType | str) -> Any:
        """Get the handler coroutine for an action type."""
        handlers = {
            ActionType.CLICK: self._handle_click,
            ActionType.DOUBLE_CLICK: self._handle_double_click,
            ActionType.RIGHT_CLICK: self._handle_right_click,
            ActionType.HOVER: self._handle_hover,
            ActionType.DRAG_AND_DROP: self._handle_drag_and_drop,
            ActionType.TYPE: self._handle_type,
            ActionType.FILL: self._handle_fill,
            ActionType.PRESS: self._handle_press,
            ActionType.KEY_DOWN: self._handle_key_down,
            ActionType.KEY_UP: self._handle_key_up,
            ActionType.SCROLL: self._handle_scroll,
            ActionType.WAIT: self._handle_wait,
            ActionType.SCREENSHOT: self._handle_screenshot,
            ActionType.SELECT: self._handle_select,
            ActionType.CHECK: self._handle_check,
            ActionType.UNCHECK: self._handle_uncheck,
            ActionType.UPLOAD_FILE: self._handle_upload_file,
            ActionType.FOCUS: self._handle_focus,
            ActionType.BLUR: self._handle_blur,
            ActionType.GOTO: self._handle_goto,
            ActionType.GO_BACK: self._handle_go_back,
            ActionType.GO_FORWARD: self._handle_go_forward,
            ActionType.RELOAD: self._handle_reload,
            ActionType.EVALUATE: self._handle_evaluate,
            ActionType.SET_VIEWPORT: self._handle_set_viewport,
            ActionType.SWITCH_FRAME: self._handle_switch_frame,
            ActionType.SWITCH_TO_MAIN_FRAME: self._handle_switch_to_main_frame,
            ActionType.ASSERT_SELECTOR: self._handle_assert_selector,
            ActionType.ASSERT_TEXT: self._handle_assert_text,
            ActionType.ASSERT_URL: self._handle_assert_url,
            ActionType.PAUSE: self._handle_pause,
        }
        return handlers.get(
            ActionType(action_type) if isinstance(action_type, str) else action_type
        )

    # ── Mouse Handlers ────────────────────────────────────────

    async def _handle_click(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.click(
            action.selector,
            timeout=action.timeout,
        )
        return {"clicked": action.selector}

    async def _handle_double_click(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.dblclick(
            action.selector,
            timeout=action.timeout,
        )
        return {"double_clicked": action.selector}

    async def _handle_right_click(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.click(
            action.selector,
            button="right",
            timeout=action.timeout,
        )
        return {"right_clicked": action.selector}

    async def _handle_hover(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.hover(
            action.selector,
            timeout=action.timeout,
        )
        return {"hovered": action.selector}

    async def _handle_drag_and_drop(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        if not action.value or not isinstance(action.value, str):
            raise ActionExecutionError(action, "drag_and_drop requires 'value' as target selector")
        await self._current_frame.drag_and_drop(
            action.selector,
            action.value,
            timeout=action.timeout,
        )
        return {"dragged": action.selector, "dropped_on": action.value}

    # ── Keyboard Handlers ─────────────────────────────────────

    async def _handle_type(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        if action.text is None:
            raise ActionExecutionError(action, "type action requires 'text'")
        delay = action.amount or 50
        await self._current_frame.type(
            action.selector,
            action.text,
            delay=delay,
            timeout=action.timeout,
        )
        return {"typed": action.text[:50], "into": action.selector}

    async def _handle_fill(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        if action.text is None:
            raise ActionExecutionError(action, "fill action requires 'text'")
        await self._current_frame.fill(
            action.selector,
            action.text,
            timeout=action.timeout,
        )
        return {"filled": action.text[:50], "into": action.selector}

    async def _handle_press(self, action: Action) -> dict[str, Any]:
        if action.key is None:
            raise ActionExecutionError(action, "press action requires 'key'")
        if action.selector:
            await self._current_frame.press(
                action.selector,
                action.key,
                timeout=action.timeout,
            )
        else:
            await self._page.keyboard.press(action.key)
        return {"pressed": action.key}

    async def _handle_key_down(self, action: Action) -> dict[str, Any]:
        if action.key is None:
            raise ActionExecutionError(action, "key_down action requires 'key'")
        await self._page.keyboard.down(action.key)
        return {"key_down": action.key}

    async def _handle_key_up(self, action: Action) -> dict[str, Any]:
        if action.key is None:
            raise ActionExecutionError(action, "key_up action requires 'key'")
        await self._page.keyboard.up(action.key)
        return {"key_up": action.key}

    # ── Scroll Handlers ───────────────────────────────────────

    async def _handle_scroll(self, action: Action) -> dict[str, Any]:
        # Scroll to specific element
        if action.selector and not action.direction:
            await self._current_frame.scroll_into_view_if_needed(
                action.selector,
                timeout=action.timeout,
            )
            return {"scrolled_to": action.selector}

        # Directional scroll
        direction = action.direction or "down"
        amount = action.amount or 3
        pixels = amount * 500  # Each "step" = 500px

        scroll_map = {
            "down": f"window.scrollBy(0, {pixels})",
            "up": f"window.scrollBy(0, -{pixels})",
            "left": f"window.scrollBy(-{pixels}, 0)",
            "right": f"window.scrollBy({pixels}, 0)",
        }

        js = scroll_map.get(direction)
        if js is None:
            raise ActionExecutionError(
                action,
                f"Invalid scroll direction: '{direction}'. Use up/down/left/right.",
            )

        if action.selector:
            # Scroll within a specific element
            await self._current_frame.evaluate(
                f"""(selector) => {{
                    const el = document.querySelector(selector);
                    if (el) {{
                        const delta = {pixels if direction in ("down", "right") else -pixels};
                        if ('{direction}' === 'down' || '{direction}' === 'up') {{
                            el.scrollBy(0, delta);
                        }} else {{
                            el.scrollBy(delta, 0);
                        }}
                    }}
                }}""",
                action.selector,
            )
        else:
            await self._page.evaluate(js)

        return {"scrolled": direction, "amount": amount, "pixels": pixels}

    # ── Wait Handlers ─────────────────────────────────────────

    async def _handle_wait(self, action: Action) -> dict[str, Any]:
        # Fixed timeout
        if action.milliseconds is not None:
            await asyncio.sleep(action.milliseconds / 1000.0)
            return {"waited_ms": action.milliseconds}

        # Wait for navigation
        if action.expected == "navigation":
            await self._page.wait_for_load_state("load", timeout=action.timeout)
            return {"waited_for": "navigation"}

        # Wait for load state
        if action.expected and action.expected.startswith("load_state:"):
            state = action.expected.split(":", 1)[1]
            await self._page.wait_for_load_state(state, timeout=action.timeout)
            return {"waited_for": f"load_state:{state}"}

        # Wait for URL
        if action.url:
            await self._page.wait_for_url(action.url, timeout=action.timeout)
            return {"waited_for_url": action.url}

        # Wait for JavaScript function
        if action.expected == "function" and action.expression:
            await self._page.wait_for_function(action.expression, timeout=action.timeout)
            return {"waited_for_function": action.expression[:50]}

        # Wait for selector
        if action.selector:
            state = action.expected or "visible"
            await self._current_frame.wait_for_selector(
                action.selector,
                state=state,
                timeout=action.timeout,
            )
            return {"waited_for_selector": action.selector, "state": state}

        raise ActionExecutionError(
            action,
            "wait action requires one of: milliseconds, selector, url, expression, or expected='navigation'",
        )

    # ── Screenshot Handlers ───────────────────────────────────

    async def _handle_screenshot(self, action: Action) -> dict[str, Any]:
        screenshot_opts: dict[str, Any] = {
            "type": action.format if action.format in ("png", "jpeg") else "png",
        }

        if action.format == "jpeg":
            screenshot_opts["quality"] = action.quality

        if action.selector:
            # Element screenshot
            element = await self._current_frame.query_selector(action.selector)
            if element is None:
                raise ActionExecutionError(
                    action,
                    f"Element not found for screenshot: '{action.selector}'",
                )
            screenshot_bytes = await element.screenshot(**screenshot_opts)
        else:
            screenshot_opts["full_page"] = action.full_page
            screenshot_bytes = await self._page.screenshot(**screenshot_opts)

        b64 = base64.b64encode(screenshot_bytes).decode()
        return {
            "screenshot_base64": b64,
            "format": action.format,
            "full_page": action.full_page,
            "size_bytes": len(screenshot_bytes),
        }

    # ── Form Handlers ─────────────────────────────────────────

    async def _handle_select(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        if action.value is None:
            raise ActionExecutionError(action, "select action requires 'value'")
        await self._current_frame.select_option(
            action.selector,
            action.value,
            timeout=action.timeout,
        )
        return {"selected": action.value, "in": action.selector}

    async def _handle_check(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.check(action.selector, timeout=action.timeout)
        return {"checked": action.selector}

    async def _handle_uncheck(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.uncheck(action.selector, timeout=action.timeout)
        return {"unchecked": action.selector}

    async def _handle_upload_file(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        if action.value is None:
            raise ActionExecutionError(action, "upload_file action requires 'value' (file path(s))")
        files = action.value if isinstance(action.value, list) else [action.value]
        await self._current_frame.set_input_files(
            action.selector,
            files,
            timeout=action.timeout,
        )
        return {"uploaded": files, "to": action.selector}

    # ── Focus Handlers ────────────────────────────────────────

    async def _handle_focus(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.focus(action.selector, timeout=action.timeout)
        return {"focused": action.selector}

    async def _handle_blur(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        await self._current_frame.evaluate(f"document.querySelector('{action.selector}')?.blur()")
        return {"blurred": action.selector}

    # ── Navigation Handlers ───────────────────────────────────

    async def _handle_goto(self, action: Action) -> dict[str, Any]:
        if action.url is None:
            raise ActionExecutionError(action, "goto action requires 'url'")
        response = await self._page.goto(action.url, timeout=action.timeout)
        status = response.status if response else None
        return {"navigated_to": action.url, "status": status}

    async def _handle_go_back(self, action: Action) -> dict[str, Any]:
        await self._page.go_back(timeout=action.timeout)
        return {"navigated": "back"}

    async def _handle_go_forward(self, action: Action) -> dict[str, Any]:
        await self._page.go_forward(timeout=action.timeout)
        return {"navigated": "forward"}

    async def _handle_reload(self, action: Action) -> dict[str, Any]:
        await self._page.reload(timeout=action.timeout)
        return {"reloaded": True}

    # ── JavaScript Handlers ───────────────────────────────────

    async def _handle_evaluate(self, action: Action) -> dict[str, Any]:
        if action.expression is None:
            raise ActionExecutionError(action, "evaluate action requires 'expression'")
        result = await self._page.evaluate(action.expression)
        return {"result": result}

    # ── Viewport Handlers ─────────────────────────────────────

    async def _handle_set_viewport(self, action: Action) -> dict[str, Any]:
        if action.width is None or action.height is None:
            raise ActionExecutionError(action, "set_viewport requires 'width' and 'height'")
        await self._page.set_viewport_size({"width": action.width, "height": action.height})
        return {"viewport": f"{action.width}x{action.height}"}

    # ── Frame Handlers ────────────────────────────────────────

    async def _handle_switch_frame(self, action: Action) -> dict[str, Any]:
        if action.frame_selector is None:
            raise ActionExecutionError(action, "switch_frame requires 'frame_selector'")
        frame = await self._page.frame_locator(action.frame_selector)
        if frame is None:
            raise ActionExecutionError(
                action,
                f"Frame not found: '{action.frame_selector}'",
            )
        self._current_frame = frame
        return {"switched_to_frame": action.frame_selector}

    async def _handle_switch_to_main_frame(self, action: Action) -> dict[str, Any]:
        self._current_frame = self._page
        return {"switched_to": "main_frame"}

    # ── Assertion Handlers ────────────────────────────────────

    async def _handle_assert_selector(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        state = action.expected or "visible"
        await self._current_frame.wait_for_selector(
            action.selector,
            state=state,
            timeout=action.timeout,
        )
        return {"asserted": action.selector, "state": state}

    async def _handle_assert_text(self, action: Action) -> dict[str, Any]:
        self._require_selector(action)
        if action.text is None:
            raise ActionExecutionError(action, "assert_text requires 'text'")
        from playwright.async_api import expect

        locator = self._current_frame.locator(action.selector)
        await expect(locator).to_contain_text(action.text, timeout=action.timeout)
        return {"asserted_text": action.text[:50], "in": action.selector}

    async def _handle_assert_url(self, action: Action) -> dict[str, Any]:
        if action.url is None:
            raise ActionExecutionError(action, "assert_url requires 'url'")
        current_url = self._page.url
        import fnmatch

        if not fnmatch.fnmatch(current_url, action.url):
            raise ActionExecutionError(
                action,
                f"URL assertion failed: expected '{action.url}', got '{current_url}'",
            )
        return {"asserted_url": action.url, "actual": current_url}

    # ── Debug Handlers ────────────────────────────────────────

    async def _handle_pause(self, action: Action) -> dict[str, Any]:
        await self._page.pause()
        return {"paused": True}

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _require_selector(action: Action) -> None:
        if action.selector is None:
            raise ActionExecutionError(
                action,
                f"'{action.type}' action requires a 'selector'",
            )
