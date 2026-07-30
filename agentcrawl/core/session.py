"""
AgentCrawl — Session Management
===================================

Manages crawl session state across multiple requests, including
cookie persistence, browser context reuse, visit history, and
session-level configuration.

A CrawlSession allows an AI agent or user to maintain state
across multiple page interactions — logging in once, then
navigating multiple pages while preserving authentication.

Features:
    - Unique session ID generation
    - Cookie and storage state persistence
    - Browser context reuse (same session = same context)
    - Visit history tracking
    - Session-level header and User-Agent overrides
    - Session timeout and expiry
    - Serialization / deserialization
    - Session metadata (custom key-value pairs)

Usage:
    from agentcrawl.core.session import CrawlSession

    # Create a session
    async with CrawlSession(engine) as session:
        # Login
        await session.goto("https://app.example.com/login")
        await session.execute_actions([
            {"type": "type", "selector": "#email", "text": "user@example.com"},
            {"type": "type", "selector": "#password", "text": "secret"},
            {"type": "click", "selector": "#login-btn"},
            {"type": "wait", "selector": "#dashboard"},
        ])

        # Navigate — cookies are preserved
        result = await session.scrape("https://app.example.com/dashboard")
        print(result.markdown)

        # Another page — still authenticated
        result = await session.scrape("https://app.example.com/settings")

        # Session history
        print(session.history)
        print(session.page_count)

    # Session is automatically persisted and cleaned up
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("agentcrawl.core.session")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class PageVisit:
    """
    Record of a single page visit within a session.

    Attributes:
        url: The visited URL.
        timestamp: Unix timestamp of the visit.
        status_code: HTTP status code.
        success: Whether the visit was successful.
        duration_ms: Time taken in milliseconds.
        word_count: Words extracted.
        action_count: Number of actions performed.
        error: Error message (if failed).
    """
    url: str
    timestamp: float = field(default_factory=time.time)
    status_code: int = 0
    success: bool = True
    duration_ms: float = 0.0
    word_count: int = 0
    action_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "timestamp": self.timestamp,
            "status_code": self.status_code,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "word_count": self.word_count,
            "action_count": self.action_count,
            "error": self.error,
        }


@dataclass
class SessionState:
    """
    Serializable session state for persistence.

    Attributes:
        session_id: Unique session identifier.
        created_at: Unix timestamp of creation.
        last_active_at: Unix timestamp of last activity.
        expires_at: Unix timestamp of expiry (None = no expiry).
        cookies: List of cookie dictionaries.
        local_storage: LocalStorage key-value pairs per origin.
        history: List of page visit records.
        metadata: Custom session metadata.
        page_count: Total pages visited.
        user_agent: Session-level User-Agent override.
        headers: Session-level header overrides.
    """
    session_id: str = ""
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, dict[str, str]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    page_count: int = 0
    user_agent: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_active_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "expires_at": self.expires_at,
            "cookies_count": len(self.cookies),
            "local_storage_origins": list(self.local_storage.keys()),
            "history_count": len(self.history),
            "metadata": self.metadata,
            "page_count": self.page_count,
            "user_agent": self.user_agent,
            "is_expired": self.is_expired,
            "age_seconds": round(self.age_seconds, 1),
            "idle_seconds": round(self.idle_seconds, 1),
        }

    def to_json(self) -> str:
        return json.dumps({
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "expires_at": self.expires_at,
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "history": self.history,
            "metadata": self.metadata,
            "page_count": self.page_count,
            "user_agent": self.user_agent,
            "headers": self.headers,
        }, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> SessionState:
        data = json.loads(raw)
        return cls(
            session_id=data.get("session_id", ""),
            created_at=data.get("created_at", time.time()),
            last_active_at=data.get("last_active_at", time.time()),
            expires_at=data.get("expires_at"),
            cookies=data.get("cookies", []),
            local_storage=data.get("local_storage", {}),
            history=data.get("history", []),
            metadata=data.get("metadata", {}),
            page_count=data.get("page_count", 0),
            user_agent=data.get("user_agent"),
            headers=data.get("headers", {}),
        )


# ══════════════════════════════════════════════════════════════
# Crawl Session
# ══════════════════════════════════════════════════════════════

class CrawlSession:
    """
    Manages stateful crawl sessions across multiple requests.

    A session maintains a dedicated browser context with persistent
    cookies and storage, allowing authenticated navigation across
    multiple pages.

    Args:
        engine: CrawlEngine instance.
        session_id: Optional custom session ID (auto-generated if None).
        ttl: Session time-to-live in seconds (None = no expiry).
        persist: Whether to persist session state to disk.
        storage_dir: Directory for session state files.
        user_agent: Session-level User-Agent override.
        headers: Session-level header overrides.
        metadata: Custom session metadata.

    Example:
        >>> async with CrawlSession(engine, ttl=3600) as session:
        ...     await session.goto("https://example.com/login")
        ...     await session.execute_actions([...])
        ...     result = await session.scrape("https://example.com/dashboard")
        ...     print(session.page_count)
    """

    def __init__(
        self,
        engine: Any,  # CrawlEngine
        session_id: str | None = None,
        ttl: int | None = None,
        persist: bool = True,
        storage_dir: str = ".agentcrawl/sessions",
        user_agent: str | None = None,
        headers: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self._engine = engine
        self._state = SessionState(
            session_id=session_id or self._generate_id(),
            expires_at=(time.time() + ttl) if ttl else None,
            user_agent=user_agent,
            headers=headers or {},
            metadata=metadata or {},
        )
        self._persist = persist
        self._storage_dir = Path(storage_dir)
        self._context: Any = None  # Playwright BrowserContext
        self._started = False
        self._lock = asyncio.Lock()

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        """Unique session identifier."""
        return self._state.session_id

    @property
    def is_started(self) -> bool:
        """Whether the session has been initialized."""
        return self._started

    @property
    def is_expired(self) -> bool:
        """Whether the session has expired."""
        return self._state.is_expired

    @property
    def page_count(self) -> int:
        """Total pages visited in this session."""
        return self._state.page_count

    @property
    def history(self) -> list[PageVisit]:
        """Visit history as PageVisit objects."""
        return [
            PageVisit(
                url=h.get("url", ""),
                timestamp=h.get("timestamp", 0),
                status_code=h.get("status_code", 0),
                success=h.get("success", True),
                duration_ms=h.get("duration_ms", 0),
                word_count=h.get("word_count", 0),
                action_count=h.get("action_count", 0),
                error=h.get("error"),
            )
            for h in self._state.history
        ]

    @property
    def urls_visited(self) -> list[str]:
        """List of URLs visited in order."""
        return [h.get("url", "") for h in self._state.history]

    @property
    def last_url(self) -> str | None:
        """Last visited URL."""
        if self._state.history:
            return self._state.history[-1].get("url")
        return None

    @property
    def metadata(self) -> dict[str, Any]:
        """Session metadata."""
        return self._state.metadata

    @property
    def state(self) -> SessionState:
        """Current session state."""
        return self._state

    @property
    def age_seconds(self) -> float:
        """Session age in seconds."""
        return self._state.age_seconds

    @property
    def idle_seconds(self) -> float:
        """Seconds since last activity."""
        return self._state.idle_seconds

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Initialize the session.

        Creates or restores a browser context with persisted state.
        """
        async with self._lock:
            if self._started:
                return

            if self._state.is_expired:
                raise RuntimeError(
                    f"Session {self._state.session_id} has expired"
                )

            # Try to restore from disk
            if self._persist:
                restored = await self._restore_state()
                if restored:
                    logger.info(
                        "Restored session %s (%d pages visited)",
                        self._state.session_id,
                        self._state.page_count,
                    )

            # Create browser context
            await self._create_context()

            self._started = True
            logger.info(
                "Session %s started (persist=%s, ttl=%s)",
                self._state.session_id,
                self._persist,
                self._state.expires_at,
            )

    async def stop(self) -> None:
        """
        Shut down the session.

        Persists state and closes the browser context.
        """
        async with self._lock:
            if not self._started:
                return

            # Persist state
            if self._persist:
                await self._save_state()

            # Save browser storage state
            await self._save_browser_state()

            # Close context
            if self._context:
                try:
                    await self._context.close()
                except Exception as e:
                    logger.debug("Error closing session context: %s", e)
                self._context = None

            self._started = False
            logger.info(
                "Session %s stopped (%d pages visited)",
                self._state.session_id,
                self._state.page_count,
            )

    async def __aenter__(self) -> CrawlSession:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ──────────────────────────────────────────────────────────
    # Navigation & Scraping
    # ──────────────────────────────────────────────────────────

    async def goto(self, url: str, **kwargs: Any) -> Any:
        """
        Navigate to a URL within the session context.

        Args:
            url: URL to navigate to.
            **kwargs: Additional Playwright goto options.

        Returns:
            Playwright Response object.
        """
        self._ensure_started()
        self._check_expired()

        page = await self._context.new_page()
        try:
            response = await page.goto(url, **kwargs)
            self._record_visit(
                url=url,
                status_code=response.status if response else 0,
                success=True,
            )
            return response
        except Exception as e:
            self._record_visit(url=url, success=False, error=str(e))
            raise
        finally:
            await page.close()

    async def scrape(
        self,
        url: str,
        config: Any = None,
    ) -> Any:
        """
        Scrape a URL within the session context.

        Uses the session's browser context, preserving cookies
        and storage state.

        Args:
            url: URL to scrape.
            config: CrawlerConfig override.

        Returns:
            CrawlResult.
        """
        self._ensure_started()
        self._check_expired()

        start = time.perf_counter()

        # Use the engine's scrape but with session context
        # For simplicity, we scrape via the session's own context
        page = await self._context.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
            status_code = response.status if response else 0

            # Wait for content
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)

            raw_html = await page.content()

            # Process through engine pipeline
            from agentcrawl.config.crawler_config import CrawlerConfig
            from agentcrawl.content.html_parser import HTMLParser
            from agentcrawl.content.html_to_markdown import HTMLToMarkdown

            cfg = config or CrawlerConfig()
            parser = HTMLParser(raw_html, base_url=url)
            main = parser.get_main_content(
                only_main=getattr(cfg, "only_main_content", True),
            )

            converter = HTMLToMarkdown()
            markdown = converter.convert(main.html)

            duration = (time.perf_counter() - start) * 1000

            self._record_visit(
                url=url,
                status_code=status_code,
                success=True,
                duration_ms=duration,
                word_count=len(markdown.split()),
            )

            # Build result
            from agentcrawl.core.engine import CrawlResult
            result = CrawlResult(
                url=url,
                success=True,
                status_code=status_code,
                markdown=markdown,
                html=main.html,
                text=main.text,
                response_time_ms=duration,
            )

            if getattr(cfg, "include_metadata", True):
                result.metadata = parser.get_metadata().to_dict()

            if getattr(cfg, "include_links", True):
                links = parser.get_links(base_url=url)
                result.links = {
                    "internal": [link.to_dict() for link in links["internal"]],
                    "external": [link.to_dict() for link in links["external"]],
                    "all": [link.to_dict() for link in links["all"]],
                }

            return result

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            self._record_visit(url=url, success=False, error=str(e), duration_ms=duration)

            from agentcrawl.core.engine import CrawlResult
            return CrawlResult(
                url=url,
                success=False,
                error=str(e),
                response_time_ms=duration,
            )
        finally:
            await page.close()

    async def execute_actions(
        self,
        actions: list[dict[str, Any]],
        url: str | None = None,
    ) -> list[Any]:
        """
        Execute page actions within the session context.

        Args:
            actions: List of action dictionaries.
            url: Optional URL to navigate to first.

        Returns:
            List of ActionResult objects.
        """
        self._ensure_started()
        self._check_expired()

        from agentcrawl.browser.actions import PageActions

        page = await self._context.new_page()
        try:
            if url:
                await page.goto(url, wait_until="domcontentloaded")

            pa = PageActions(actions)
            results = await pa.execute(page)

            if url:
                self._record_visit(
                    url=url,
                    success=True,
                    action_count=len(actions),
                )

            return results

        finally:
            await page.close()

    async def execute_javascript(self, expression: str) -> Any:
        """
        Execute JavaScript in the session context.

        Args:
            expression: JavaScript expression to evaluate.

        Returns:
            Evaluation result.
        """
        self._ensure_started()

        page = await self._context.new_page()
        try:
            return await page.evaluate(expression)
        finally:
            await page.close()

    async def get_cookies(self) -> list[dict[str, Any]]:
        """Get all cookies in the session context."""
        self._ensure_started()
        cookies = await self._context.cookies()
        return list(cookies)

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Set cookies in the session context."""
        self._ensure_started()
        await self._context.add_cookies(cookies)

    async def clear_cookies(self) -> None:
        """Clear all cookies in the session context."""
        self._ensure_started()
        await self._context.clear_cookies()

    # ──────────────────────────────────────────────────────────
    # Session State Management
    # ──────────────────────────────────────────────────────────

    def set_metadata(self, key: str, value: Any) -> None:
        """Set a custom metadata value."""
        self._state.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get a custom metadata value."""
        return self._state.metadata.get(key, default)

    def touch(self) -> None:
        """Update the last activity timestamp."""
        self._state.last_active_at = time.time()

    def extend_ttl(self, seconds: int) -> None:
        """Extend the session TTL."""
        if self._state.expires_at:
            self._state.expires_at = time.time() + seconds
        else:
            self._state.expires_at = time.time() + seconds

    # ──────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────

    async def save(self) -> None:
        """Manually save session state to disk."""
        await self._save_state()
        await self._save_browser_state()

    async def _save_state(self) -> None:
        """Save session state to disk."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        state_path = self._storage_dir / f"{self._state.session_id}.json"

        try:
            raw = self._state.to_json()
            state_path.write_text(raw, encoding="utf-8")
            logger.debug("Saved session state: %s", state_path)
        except Exception as e:
            logger.warning("Failed to save session state: %s", e)

    async def _restore_state(self) -> bool:
        """Restore session state from disk."""
        state_path = self._storage_dir / f"{self._state.session_id}.json"

        if not state_path.exists():
            return False

        try:
            raw = state_path.read_text(encoding="utf-8")
            restored = SessionState.from_json(raw)

            if restored.is_expired:
                logger.info("Session %s expired, starting fresh", self._state.session_id)
                state_path.unlink(missing_ok=True)
                return False

            self._state = restored
            return True

        except Exception as e:
            logger.warning("Failed to restore session state: %s", e)
            return False

    async def _save_browser_state(self) -> None:
        """Save browser context storage state (cookies, localStorage)."""
        if not self._context:
            return

        try:
            storage = await self._context.storage_state()
            self._state.cookies = storage.get("cookies", [])

            # Extract localStorage per origin
            for origin in storage.get("origins", []):
                origin_name = origin.get("origin", "")
                ls = origin.get("localStorage", [])
                if ls:
                    self._state.local_storage[origin_name] = {
                        item["name"]: item["value"] for item in ls
                    }

        except Exception as e:
            logger.debug("Failed to save browser state: %s", e)

    async def _create_context(self) -> None:
        """Create a browser context for this session."""
        browser_manager = self._engine.browser_manager

        # Build context options
        context_options: dict[str, Any] = {}

        if self._state.user_agent:
            context_options["userAgent"] = self._state.user_agent

        # Restore cookies if available
        if self._state.cookies:
            context_options["storageState"] = {
                "cookies": self._state.cookies,
                "origins": [
                    {
                        "origin": origin,
                        "localStorage": [
                            {"name": k, "value": v}
                            for k, v in items.items()
                        ],
                    }
                    for origin, items in self._state.local_storage.items()
                ],
            }

        self._context = await browser_manager.acquire_context(
            session_id=self._state.session_id,
            options=context_options,
        )

    @staticmethod
    def delete_persisted(session_id: str, storage_dir: str = ".agentcrawl/sessions") -> bool:
        """
        Delete a persisted session from disk.

        Args:
            session_id: Session ID to delete.
            storage_dir: Storage directory.

        Returns:
            True if the session file was deleted.
        """
        path = Path(storage_dir) / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    @staticmethod
    def list_persisted(storage_dir: str = ".agentcrawl/sessions") -> list[str]:
        """
        List all persisted session IDs.

        Args:
            storage_dir: Storage directory.

        Returns:
            List of session IDs.
        """
        path = Path(storage_dir)
        if not path.exists():
            return []
        return [
            f.stem for f in path.glob("*.json")
        ]

    # ──────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────

    def _record_visit(
        self,
        url: str,
        status_code: int = 0,
        success: bool = True,
        duration_ms: float = 0.0,
        word_count: int = 0,
        action_count: int = 0,
        error: str | None = None,
    ) -> None:
        """Record a page visit in the session history."""
        visit = PageVisit(
            url=url,
            status_code=status_code,
            success=success,
            duration_ms=duration_ms,
            word_count=word_count,
            action_count=action_count,
            error=error,
        )
        self._state.history.append(visit.to_dict())
        self._state.page_count += 1
        self._state.last_active_at = time.time()

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError(
                "Session not started. Call start() or use 'async with' first."
            )

    def _check_expired(self) -> None:
        if self._state.is_expired:
            raise RuntimeError(
                f"Session {self._state.session_id} has expired "
                f"(age={self._state.age_seconds:.0f}s)"
            )

    @staticmethod
    def _generate_id() -> str:
        """Generate a unique session ID."""
        return f"sess_{uuid.uuid4().hex[:16]}"

    # ──────────────────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict[str, Any]:
        """Get session diagnostics."""
        return {
            "session_id": self._state.session_id,
            "started": self._started,
            "expired": self._state.is_expired,
            "page_count": self._state.page_count,
            "history_length": len(self._state.history),
            "cookies_count": len(self._state.cookies),
            "local_storage_origins": list(self._state.local_storage.keys()),
            "age_seconds": round(self._state.age_seconds, 1),
            "idle_seconds": round(self._state.idle_seconds, 1),
            "last_url": self.last_url,
            "metadata": self._state.metadata,
            "persist": self._persist,
        }

    def __repr__(self) -> str:
        status = "started" if self._started else "stopped"
        return (
            f"CrawlSession(id={self._state.session_id!r}, "
            f"pages={self._state.page_count}, "
            f"status={status})"
        )
