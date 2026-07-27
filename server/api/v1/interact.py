"""
AgentCrawl — Interact API Routes
====================================

Handles browser interaction operations via the REST API.
Allows executing actions on pages, managing sessions,
and capturing screenshots.

Endpoints:
    POST /interact              — Execute actions on a page
    POST /interact/session      — Create an interactive session
    GET  /interact/session/{id} — Get session info
    DELETE /interact/session/{id} — Destroy a session

Usage:
    Registered automatically by server/app.py.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("agentcrawl.server.interact")


# ══════════════════════════════════════════════════════════════
# Session Management
# ══════════════════════════════════════════════════════════════

@dataclass
class InteractionSession:
    """
    An interactive browser session.

    Maintains a browser context with cookies and state
    across multiple interaction requests.
    """
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    url: str = ""
    title: str = ""
    actions_executed: int = 0
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "url": self.url,
            "title": self.title,
            "actions_executed": self.actions_executed,
            "is_active": self.is_active,
            "age_seconds": round(time.time() - self.created_at, 1),
        }


# In-memory session store
_sessions: dict[str, InteractionSession] = {}


def _create_session() -> InteractionSession:
    """Create a new interaction session."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session = InteractionSession(session_id=session_id)
    _sessions[session_id] = session

    # Cleanup old sessions (keep last 50)
    if len(_sessions) > 50:
        sorted_sessions = sorted(_sessions.values(), key=lambda s: s.last_active)
        for old in sorted_sessions[:len(_sessions) - 50]:
            old.is_active = False
            del _sessions[old.session_id]

    return session


def _get_session(session_id: str) -> InteractionSession | None:
    """Get a session by ID."""
    session = _sessions.get(session_id)
    if session:
        session.last_active = time.time()
    return session


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class ActionStep(BaseModel):
    """A single browser action."""

    type: str = Field(
        ...,
        description=(
            "Action type: click, type, press, scroll, wait, "
            "screenshot, evaluate, navigate, select, hover"
        ),
    )
    selector: str = Field(default="", description="CSS selector for the target element")
    text: str = Field(default="", description="Text to type (for type action)")
    key: str = Field(default="", description="Key to press (for press action)")
    direction: str = Field(default="down", description="Scroll direction: up, down")
    amount: int = Field(default=1, description="Scroll amount (viewport heights)")
    milliseconds: int = Field(default=0, description="Wait duration in ms")
    url: str = Field(default="", description="URL to navigate to")
    script: str = Field(default="", description="JavaScript to evaluate")
    value: str = Field(default="", description="Value to select (for select action)")
    timeout: int = Field(default=5000, description="Action timeout in ms")


class InteractRequest(BaseModel):
    """Request body for POST /interact."""

    url: str = Field(default="", description="URL to navigate to first (optional)")
    session_id: str = Field(default="", description="Existing session ID (optional)")
    actions: list[ActionStep] = Field(
        default_factory=list,
        description="List of actions to execute",
    )
    screenshot: bool = Field(
        default=False,
        description="Capture screenshot after actions",
    )
    full_page: bool = Field(
        default=False,
        description="Full page screenshot",
    )
    get_content: bool = Field(
        default=False,
        description="Return page content after actions",
    )
    get_html: bool = Field(
        default=False,
        description="Return page HTML after actions",
    )
    timeout: int = Field(
        default=30,
        description="Overall timeout in seconds",
    )


class SessionCreateRequest(BaseModel):
    """Request body for POST /interact/session."""

    url: str = Field(default="", description="Initial URL to navigate to")
    user_agent: str = Field(default="", description="Custom User-Agent")
    viewport_width: int = Field(default=1280, description="Viewport width")
    viewport_height: int = Field(default=720, description="Viewport height")


# ══════════════════════════════════════════════════════════════
# Handlers
# ══════════════════════════════════════════════════════════════

async def handle_interact(
    engine: Any,
    body: dict[str, Any],
) -> JSONResponse:
    """
    Handle POST /interact.

    Executes browser actions on a page and returns results.

    Args:
        engine: CrawlEngine instance.
        body: Request body.

    Returns:
        JSONResponse with action results.
    """
    # Validate
    try:
        request = InteractRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": str(e)}},
        )

    if engine is None or not engine.is_started:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "SERVICE_UNAVAILABLE", "message": "Engine not started"}},
        )

    if not request.actions and not request.url:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Either 'url' or 'actions' must be provided",
                }
            },
        )

    # Get or create session
    session: InteractionSession | None = None
    if request.session_id:
        session = _get_session(request.session_id)
        if session is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "SESSION_NOT_FOUND",
                        "message": f"Session not found: {request.session_id}",
                    }
                },
            )
    else:
        session = _create_session()

    # Execute actions
    start = time.perf_counter()

    try:
        result = await _execute_interaction(engine, session, request)
    except Exception as e:
        logger.error("Interaction failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERACTION_FAILED", "message": str(e)}},
        )

    elapsed = (time.perf_counter() - start) * 1000

    # Update session
    session.actions_executed += len(request.actions)
    if request.url:
        session.url = request.url

    # Build response
    response_data: dict[str, Any] = {
        "session_id": session.session_id,
        "success": result.get("success", False),
        "actions_executed": len(request.actions),
        "duration_ms": round(elapsed, 2),
    }

    if result.get("error"):
        response_data["error"] = result["error"]

    if result.get("screenshot"):
        response_data["screenshot"] = result["screenshot"]

    if result.get("content"):
        response_data["content"] = result["content"]

    if result.get("html"):
        response_data["html"] = result["html"]

    if result.get("url"):
        response_data["url"] = result["url"]
        session.url = result["url"]

    if result.get("title"):
        response_data["title"] = result["title"]
        session.title = result["title"]

    if result.get("action_results"):
        response_data["action_results"] = result["action_results"]

    logger.info(
        "Interact: session=%s actions=%d (%.0fms)",
        session.session_id,
        len(request.actions),
        elapsed,
    )

    return JSONResponse(status_code=200, content=response_data)


async def handle_create_session(
    engine: Any,
    body: dict[str, Any],
) -> JSONResponse:
    """
    Handle POST /interact/session — create a new session.

    Args:
        engine: CrawlEngine instance.
        body: Request body.

    Returns:
        Session info.
    """
    try:
        request = SessionCreateRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": str(e)}},
        )

    session = _create_session()

    # Navigate to initial URL if provided
    if request.url and engine and engine.is_started:
        try:
            interact_request = InteractRequest(
                url=request.url,
                actions=[],
                get_content=False,
            )
            await _execute_interaction(engine, session, interact_request)
            session.url = request.url
        except Exception as e:
            logger.warning("Failed to navigate session to %s: %s", request.url, e)

    logger.info("Session created: %s", session.session_id)

    return JSONResponse(
        status_code=201,
        content={
            "session_id": session.session_id,
            "status": "created",
            "url": session.url,
        },
    )


async def handle_get_session(session_id: str) -> JSONResponse:
    """
    Handle GET /interact/session/{id}.

    Args:
        session_id: Session identifier.

    Returns:
        Session info.
    """
    session = _get_session(session_id)

    if session is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"Session not found: {session_id}",
                }
            },
        )

    return JSONResponse(status_code=200, content=session.to_dict())


async def handle_destroy_session(session_id: str) -> JSONResponse:
    """
    Handle DELETE /interact/session/{id}.

    Args:
        session_id: Session identifier.

    Returns:
        Destruction result.
    """
    session = _sessions.pop(session_id, None)

    if session is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"Session not found: {session_id}",
                }
            },
        )

    session.is_active = False
    logger.info("Session destroyed: %s", session_id)

    return JSONResponse(
        status_code=200,
        content={
            "session_id": session_id,
            "status": "destroyed",
            "actions_executed": session.actions_executed,
        },
    )


# ══════════════════════════════════════════════════════════════
# Action Execution
# ══════════════════════════════════════════════════════════════

async def _execute_interaction(
    engine: Any,
    session: InteractionSession,
    request: InteractRequest,
) -> dict[str, Any]:
    """
    Execute browser interaction.

    Args:
        engine: CrawlEngine instance.
        session: Interaction session.
        request: Interaction request.

    Returns:
        Result dictionary.
    """
    from agentcrawl.config.crawler_config import CrawlerConfig

    # Build actions list for CrawlerConfig
    actions: list[dict[str, Any]] = []

    # Navigate first if URL provided
    if request.url:
        actions.append({"type": "navigate", "url": request.url})

    # Add user actions
    for action in request.actions:
        action_dict: dict[str, Any] = {"type": action.type}

        if action.selector:
            action_dict["selector"] = action.selector
        if action.text:
            action_dict["text"] = action.text
        if action.key:
            action_dict["key"] = action.key
        if action.type == "scroll":
            action_dict["direction"] = action.direction
            action_dict["amount"] = action.amount
        if action.type == "wait" and action.milliseconds:
            action_dict["milliseconds"] = action.milliseconds
        if action.type == "evaluate" and action.script:
            action_dict["script"] = action.script
        if action.type == "navigate" and action.url:
            action_dict["url"] = action.url
        if action.type == "select" and action.value:
            action_dict["value"] = action.value

        actions.append(action_dict)

    # Screenshot action
    if request.screenshot:
        actions.append({
            "type": "screenshot",
            "full_page": request.full_page,
        })

    # Build config
    config = CrawlerConfig(
        actions=actions,
        include_screenshot=request.screenshot,
        timeout=request.timeout,
    )

    # Use the target URL (or session URL)
    target_url = request.url or session.url or "about:blank"

    # Scrape with actions
    result = await engine.scrape(target_url, config)

    # Build response
    response: dict[str, Any] = {
        "success": result.success,
        "url": result.url,
        "title": result.metadata.get("title", ""),
    }

    if result.error:
        response["error"] = result.error

    if request.screenshot and result.screenshot:
        response["screenshot"] = result.screenshot

    if request.get_content:
        response["content"] = result.markdown

    if request.get_html:
        response["html"] = result.html

    return response