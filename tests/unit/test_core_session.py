"""Tests for agentcrawl.core.session module — data models, lifecycle,
navigation, cookies, persistence, and static helpers.

Uses ``tmp_path`` for filesystem tests and AsyncMock for browser interactions.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcrawl.core.session import (
    CrawlSession,
    PageVisit,
    SessionState,
)

# ═══ PageVisit Tests ═══


class TestPageVisit:
    """Tests for PageVisit dataclass."""

    def test_defaults(self) -> None:
        visit = PageVisit(url="https://example.com")
        assert visit.url == "https://example.com"
        assert visit.success is True
        assert visit.status_code == 0
        assert visit.duration_ms == 0.0
        assert visit.word_count == 0
        assert visit.action_count == 0
        assert visit.error is None

    def test_to_dict(self) -> None:
        t = time.time()
        visit = PageVisit(
            url="https://example.com",
            timestamp=t,
            status_code=200,
            success=True,
            duration_ms=500.0,
            word_count=100,
            action_count=3,
            error=None,
        )
        d = visit.to_dict()
        assert d["url"] == "https://example.com"
        assert d["success"] is True
        assert d["status_code"] == 200
        assert d["duration_ms"] == 500.0
        assert d["word_count"] == 100
        assert d["action_count"] == 3
        assert d["error"] is None

    def test_to_dict_with_error(self) -> None:
        visit = PageVisit(url="https://example.com", success=False, error="Timeout")
        d = visit.to_dict()
        assert d["error"] == "Timeout"
        assert d["success"] is False

    def test_to_dict_duration_rounded(self) -> None:
        visit = PageVisit(url="https://x", duration_ms=123.456789)
        d = visit.to_dict()
        assert d["duration_ms"] == 123.46


# ═══ SessionState Tests ═══


class TestSessionState:
    """Tests for SessionState dataclass."""

    def test_defaults(self) -> None:
        state = SessionState()
        assert state.session_id == ""
        assert state.expires_at is None
        assert state.cookies == []
        assert state.local_storage == {}
        assert state.history == []
        assert state.metadata == {}
        assert state.page_count == 0
        assert state.user_agent is None
        assert state.headers == {}
        assert state.is_expired is False

    def test_is_expired_true(self) -> None:
        state = SessionState(expires_at=0.0)
        assert state.is_expired is True

    def test_is_expired_false(self) -> None:
        state = SessionState(expires_at=time.time() + 3600)
        assert state.is_expired is False

    def test_is_expired_none(self) -> None:
        state = SessionState(expires_at=None)
        assert state.is_expired is False

    def test_age_seconds(self) -> None:
        t = time.time() - 100
        state = SessionState(created_at=t)
        assert state.age_seconds >= 100

    def test_idle_seconds(self) -> None:
        t = time.time() - 50
        state = SessionState(last_active_at=t)
        assert state.idle_seconds >= 50

    def test_to_dict(self) -> None:
        state = SessionState(session_id="sess_1", page_count=3)
        d = state.to_dict()
        assert d["session_id"] == "sess_1"
        assert d["page_count"] == 3
        assert d["cookies_count"] == 0
        assert d["is_expired"] is False

    def test_to_dict_with_data(self) -> None:
        state = SessionState(
            session_id="sess_1",
            cookies=[{"name": "session", "value": "abc"}],
            local_storage={"https://example.com": {"key": "val"}},
            history=[{"url": "https://example.com"}],
            metadata={"user": "test"},
            page_count=5,
            user_agent="TestAgent/1.0",
            expires_at=time.time() + 3600,
        )
        d = state.to_dict()
        assert d["cookies_count"] == 1
        assert "https://example.com" in d["local_storage_origins"]
        assert d["history_count"] == 1
        assert d["metadata"] == {"user": "test"}
        assert d["page_count"] == 5
        assert d["user_agent"] == "TestAgent/1.0"
        assert d["is_expired"] is False

    def test_to_json(self) -> None:
        state = SessionState(session_id="sess_1", page_count=3)
        data = json.loads(state.to_json())
        assert data["session_id"] == "sess_1"
        assert data["page_count"] == 3

    def test_from_json(self) -> None:
        raw = json.dumps(
            {
                "session_id": "sess_abc",
                "created_at": 1000.0,
                "last_active_at": 2000.0,
                "expires_at": None,
                "cookies": [{"name": "test"}],
                "local_storage": {"https://x": {"k": "v"}},
                "history": [{"url": "https://x"}],
                "metadata": {"key": "val"},
                "page_count": 5,
                "user_agent": "Mozilla",
                "headers": {"Accept": "text/html"},
            }
        )
        state = SessionState.from_json(raw)
        assert state.session_id == "sess_abc"
        assert state.cookies == [{"name": "test"}]
        assert state.local_storage == {"https://x": {"k": "v"}}
        assert state.history == [{"url": "https://x"}]
        assert state.metadata == {"key": "val"}
        assert state.page_count == 5
        assert state.user_agent == "Mozilla"
        assert state.headers == {"Accept": "text/html"}

    def test_from_json_defaults(self) -> None:
        state = SessionState.from_json(json.dumps({}))
        assert state.session_id == ""
        assert state.cookies == []
        assert state.history == []


# ═══ CrawlSession Properties ═══


class TestCrawlSessionProperties:
    """Tests for CrawlSession read-only properties."""

    def _make_session(self, **kwargs: Any) -> CrawlSession:
        return CrawlSession(engine=MagicMock(), **kwargs)

    def test_session_id_auto(self) -> None:
        assert self._make_session().session_id.startswith("sess_")

    def test_session_id_custom(self) -> None:
        assert self._make_session(session_id="custom").session_id == "custom"

    def test_is_started_false(self) -> None:
        assert self._make_session().is_started is False

    def test_is_expired_true(self) -> None:
        s = self._make_session()
        s._state.expires_at = time.time() - 1
        assert s.is_expired is True

    def test_page_count(self) -> None:
        assert self._make_session().page_count == 0

    def test_history_empty(self) -> None:
        assert self._make_session().history == []

    def test_urls_visited_empty(self) -> None:
        assert self._make_session().urls_visited == []

    def test_last_url_empty(self) -> None:
        assert self._make_session().last_url is None

    def test_metadata_default(self) -> None:
        assert self._make_session().metadata == {}

    def test_age_seconds(self) -> None:
        assert self._make_session().age_seconds >= 0

    def test_idle_seconds(self) -> None:
        assert self._make_session().idle_seconds >= 0

    def test_diagnostics(self) -> None:
        diag = self._make_session().get_diagnostics()
        assert "session_id" in diag
        assert "started" in diag
        assert "expired" in diag
        assert "page_count" in diag

    def test_repr_not_started(self) -> None:
        assert "stopped" in repr(self._make_session())

    def test_repr_started(self) -> None:
        s = self._make_session()
        s._started = True
        assert "started" in repr(s)


# ═══ CrawlSession Metadata ═══


class TestCrawlSessionMetadata:
    """Tests for CrawlSession metadata operations."""

    def _make_session(self, **kwargs: Any) -> CrawlSession:
        return CrawlSession(engine=MagicMock(), **kwargs)

    def test_set_and_get_metadata(self) -> None:
        s = self._make_session()
        s.set_metadata("key", "value")
        assert s.get_metadata("key") == "value"

    def test_get_metadata_default(self) -> None:
        assert self._make_session().get_metadata("missing", "default") == "default"

    def test_touch(self) -> None:
        s = self._make_session()
        old = s._state.last_active_at
        time.sleep(0.01)
        s.touch()
        assert s._state.last_active_at > old

    def test_extend_ttl_no_expiry(self) -> None:
        s = self._make_session()
        assert s._state.expires_at is None
        s.extend_ttl(3600)
        assert s._state.expires_at is not None

    def test_extend_ttl_with_expiry(self) -> None:
        s = self._make_session(ttl=3600)
        old = s._state.expires_at
        time.sleep(0.01)
        s.extend_ttl(7200)
        assert s._state.expires_at > old


# ═══ CrawlSession Lifecycle ═══


class TestCrawlSessionLifecycle:
    """Tests for start/stop and async context manager."""

    def _engine(self) -> MagicMock:
        engine = MagicMock()
        engine.browser_manager = AsyncMock()
        engine.browser_manager.acquire_context = AsyncMock(return_value=MagicMock())
        return engine

    @pytest.mark.asyncio
    async def test_start_already_started(self) -> None:
        s = CrawlSession(engine=MagicMock())
        s._started = True
        await s.start()  # should return early

    @pytest.mark.asyncio
    async def test_start_expired_raises(self) -> None:
        s = CrawlSession(engine=MagicMock())
        s._state.expires_at = time.time() - 1
        with pytest.raises(RuntimeError, match="expired"):
            await s.start()

    @pytest.mark.asyncio
    async def test_start_not_started(self) -> None:
        engine = self._engine()
        s = CrawlSession(engine=engine)
        await s.start()
        assert s.is_started is True

    @pytest.mark.asyncio
    async def test_start_with_restore(self) -> None:
        engine = self._engine()
        s = CrawlSession(engine=engine, persist=True)
        await s.start()
        assert s.is_started is True

    @pytest.mark.asyncio
    async def test_stop_not_started(self) -> None:
        await CrawlSession(engine=MagicMock()).stop()

    @pytest.mark.asyncio
    async def test_stop_started(self) -> None:
        s = CrawlSession(engine=MagicMock())
        s._started = True
        s._state.page_count = 5
        mock_ctx = MagicMock()
        mock_ctx.close = AsyncMock()
        s._context = mock_ctx
        await s.stop()
        assert not s.is_started
        assert s._context is None

    @pytest.mark.asyncio
    async def test_stop_close_error(self) -> None:
        s = CrawlSession(engine=MagicMock(), persist=False)
        s._started = True
        mock_ctx = MagicMock()
        mock_ctx.close = AsyncMock(side_effect=Exception("close error"))
        s._context = mock_ctx
        await s.stop()  # should not raise
        assert not s.is_started

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        engine = self._engine()
        async with CrawlSession(engine=engine) as s:
            assert s.is_started
        assert not s.is_started


# ═══ CrawlSession Persistence ═══


class TestCrawlSessionPersistence:
    """Tests for _save_state, _restore_state, _save_browser_state, save."""

    def _make_session(self, **kwargs: Any) -> CrawlSession:
        return CrawlSession(engine=MagicMock(), **kwargs)

    @pytest.mark.asyncio
    async def test_save_state(self, tmp_path: Any) -> None:
        s = self._make_session(persist=True, storage_dir=str(tmp_path))
        await s._save_state()
        state_path = tmp_path / f"{s.session_id}.json"
        assert state_path.exists()

    @pytest.mark.asyncio
    async def test_save_state_error_caught(self, tmp_path: Any) -> None:
        """Test _save_state catches errors when to_json fails."""
        s = self._make_session(persist=True, storage_dir=str(tmp_path))
        # Mock to_json to raise, triggering the except block
        with patch.object(s._state, "to_json", side_effect=Exception("json error")):
            await s._save_state()  # should not raise

    @pytest.mark.asyncio
    async def test_restore_state_no_file(self, tmp_path: Any) -> None:
        s = self._make_session(storage_dir=str(tmp_path))
        assert await s._restore_state() is False

    @pytest.mark.asyncio
    async def test_restore_state_valid(self, tmp_path: Any) -> None:
        s = self._make_session(storage_dir=str(tmp_path))
        state = SessionState(session_id=s.session_id, page_count=10)
        state_path = tmp_path / f"{s.session_id}.json"
        state_path.write_text(state.to_json())
        assert await s._restore_state() is True
        assert s._state.page_count == 10

    @pytest.mark.asyncio
    async def test_restore_state_expired(self, tmp_path: Any) -> None:
        s = self._make_session(storage_dir=str(tmp_path))
        state = SessionState(session_id=s.session_id, expires_at=0.0)
        state_path = tmp_path / f"{s.session_id}.json"
        state_path.write_text(state.to_json())
        assert await s._restore_state() is False
        assert not state_path.exists()

    @pytest.mark.asyncio
    async def test_restore_state_invalid_json(self, tmp_path: Any) -> None:
        s = self._make_session(storage_dir=str(tmp_path))
        state_path = tmp_path / f"{s.session_id}.json"
        state_path.write_text("not json")
        assert await s._restore_state() is False

    @pytest.mark.asyncio
    async def test_save_browser_state_no_context(self) -> None:
        s = self._make_session()
        s._context = None
        await s._save_browser_state()

    @pytest.mark.asyncio
    async def test_save_browser_state_with_context(self) -> None:
        s = self._make_session()
        mock_ctx = MagicMock()
        mock_ctx.storage_state = AsyncMock(
            return_value={
                "cookies": [{"name": "t", "value": "v"}],
                "origins": [
                    {"origin": "https://e.com", "localStorage": [{"name": "k", "value": "v"}]}
                ],
            }
        )
        s._context = mock_ctx
        await s._save_browser_state()
        assert s._state.cookies == [{"name": "t", "value": "v"}]
        assert "https://e.com" in s._state.local_storage

    @pytest.mark.asyncio
    async def test_save_browser_state_empty_ls(self) -> None:
        s = self._make_session()
        mock_ctx = MagicMock()
        mock_ctx.storage_state = AsyncMock(
            return_value={"cookies": [], "origins": [{"origin": "https://x", "localStorage": []}]}
        )
        s._context = mock_ctx
        await s._save_browser_state()
        assert s._state.cookies == []

    @pytest.mark.asyncio
    async def test_save_browser_state_error(self) -> None:
        s = self._make_session()
        mock_ctx = MagicMock()
        mock_ctx.storage_state = AsyncMock(side_effect=Exception("err"))
        s._context = mock_ctx
        await s._save_browser_state()  # should not raise

    @pytest.mark.asyncio
    async def test_manual_save(self, tmp_path: Any) -> None:
        s = self._make_session(persist=True, storage_dir=str(tmp_path))
        await s.save()
        assert (tmp_path / f"{s.session_id}.json").exists()


# ═══ CrawlSession Navigation ═══


class TestCrawlSessionNavigation:
    """Tests for goto, _ensure_started, _check_expired."""

    def _make_session(self, **kwargs: Any) -> CrawlSession:
        return CrawlSession(engine=MagicMock(), **kwargs)

    def test_ensure_started_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            self._make_session()._ensure_started()

    def test_check_expired_raises(self) -> None:
        s = self._make_session()
        s._state.expires_at = time.time() - 1
        with pytest.raises(RuntimeError, match="expired"):
            s._check_expired()

    def test_check_expired_ok(self) -> None:
        s = self._make_session(ttl=3600)
        s._check_expired()  # Should not raise

    def test_generate_id_unique(self) -> None:
        id1 = CrawlSession._generate_id()
        id2 = CrawlSession._generate_id()
        assert id1 != id2
        assert id1.startswith("sess_")

    @pytest.mark.asyncio
    async def test_goto_success(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_page.goto = AsyncMock(return_value=mock_resp)
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        result = await s.goto("https://example.com")
        assert result is mock_resp

    @pytest.mark.asyncio
    async def test_goto_no_response(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        await s.goto("https://example.com")
        assert len(s._state.history) == 1

    @pytest.mark.asyncio
    async def test_goto_exception(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("nav failed"))
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        with pytest.raises(Exception, match="nav failed"):
            await s.goto("https://example.com")

    def test_goto_not_started(self) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            asyncio_run(CrawlSession(engine=MagicMock()).goto("https://x"))


# ═══ CrawlSession Scraper ═══


class TestCrawlSessionScraper:
    """Tests for scrape and _create_context."""

    def _make_session(self, **kwargs: Any) -> CrawlSession:
        engine = MagicMock()
        engine.browser_manager = AsyncMock()
        engine.browser_manager.acquire_context = AsyncMock(return_value=MagicMock())
        return CrawlSession(engine=engine, **kwargs)

    @pytest.mark.asyncio
    async def test_scrape_success(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_page.goto = AsyncMock(return_value=mock_resp)
        mock_page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        result = await s.scrape("https://example.com")
        assert result.success is True
        assert result.markdown is not None

    @pytest.mark.asyncio
    async def test_scrape_with_config(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_page.goto = AsyncMock(return_value=mock_resp)
        mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        with patch.object(s, "scrape") as mock_scrape:
            mock_scrape.return_value = MagicMock(success=True)
            await s.scrape("https://x", config=MagicMock())

    @pytest.mark.asyncio
    async def test_scrape_exception(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("nav error"))
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        result = await s.scrape("https://example.com")
        assert result.success is False
        assert "nav error" in result.error

    @pytest.mark.asyncio
    async def test_create_context(self) -> None:
        s = self._make_session()
        await s._create_context()
        assert s._context is not None

    @pytest.mark.asyncio
    async def test_create_context_with_user_agent(self) -> None:
        s = self._make_session(user_agent="TestAgent/1.0")
        await s._create_context()
        assert s._context is not None

    @pytest.mark.asyncio
    async def test_create_context_with_cookies(self) -> None:
        s = self._make_session()
        s._state.cookies = [{"name": "session", "value": "abc"}]
        await s._create_context()
        assert s._context is not None


# ═══ CrawlSession Cookies ═══


class TestCrawlSessionCookies:
    """Tests for cookie operations."""

    @pytest.mark.asyncio
    async def test_get_cookies(self) -> None:
        s = CrawlSession(engine=MagicMock())
        s._started = True
        mock_ctx = MagicMock()
        mock_ctx.cookies = AsyncMock(return_value=[{"name": "t", "value": "v"}])
        s._context = mock_ctx
        cookies = await s.get_cookies()
        assert len(cookies) == 1

    @pytest.mark.asyncio
    async def test_set_cookies(self) -> None:
        s = CrawlSession(engine=MagicMock())
        s._started = True
        mock_ctx = MagicMock()
        mock_ctx.add_cookies = AsyncMock()
        s._context = mock_ctx
        await s.set_cookies([{"name": "t", "value": "v"}])
        mock_ctx.add_cookies.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clear_cookies(self) -> None:
        s = CrawlSession(engine=MagicMock())
        s._started = True
        mock_ctx = MagicMock()
        mock_ctx.clear_cookies = AsyncMock()
        s._context = mock_ctx
        await s.clear_cookies()
        mock_ctx.clear_cookies.assert_awaited_once()

    def test_get_cookies_not_started(self) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            asyncio_run(CrawlSession(engine=MagicMock()).get_cookies())


# ═══ CrawlSession Actions & JS ═══


class TestCrawlSessionActions:
    """Tests for execute_actions and execute_javascript."""

    def _make_session(self, **kwargs: Any) -> CrawlSession:
        return CrawlSession(engine=MagicMock(), **kwargs)

    @pytest.mark.asyncio
    async def test_execute_actions_with_url(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        with patch("agentcrawl.browser.actions.PageActions") as mock_pa_cls:
            mock_pa = MagicMock()
            mock_pa.execute = AsyncMock(return_value=[{"success": True}])
            mock_pa_cls.return_value = mock_pa
            results = await s.execute_actions(
                [{"type": "click", "selector": "#btn"}], url="https://example.com"
            )
            assert len(results) == 1
            assert len(s._state.history) == 1

    @pytest.mark.asyncio
    async def test_execute_actions_no_url(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        with patch("agentcrawl.browser.actions.PageActions") as mock_pa_cls:
            mock_pa = MagicMock()
            mock_pa.execute = AsyncMock(return_value=[{"success": True}])
            mock_pa_cls.return_value = mock_pa
            results = await s.execute_actions([{"type": "click", "selector": "#btn"}])
            assert len(results) == 1
            assert len(s._state.history) == 0

    def test_execute_actions_not_started(self) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            asyncio_run(CrawlSession(engine=MagicMock()).execute_actions([]))

    @pytest.mark.asyncio
    async def test_execute_javascript(self) -> None:
        s = self._make_session()
        s._started = True
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="result")
        mock_page.close = AsyncMock()
        s._context = MagicMock()
        s._context.new_page = AsyncMock(return_value=mock_page)
        result = await s.execute_javascript("1 + 1")
        assert result == "result"

    def test_execute_javascript_not_started(self) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            asyncio_run(CrawlSession(engine=MagicMock()).execute_javascript("1+1"))

    def test_record_visit(self) -> None:
        s = self._make_session()
        s._record_visit(url="https://example.com", status_code=200)
        assert len(s._state.history) == 1
        assert s._state.page_count == 1


# ═══ CrawlSession Static Methods ═══


class TestCrawlSessionStatic:
    """Tests for delete_persisted and list_persisted static methods."""

    def test_delete_persisted_exists(self, tmp_path: Any) -> None:
        session_path = tmp_path / "sess_test.json"
        session_path.write_text("{}")
        assert CrawlSession.delete_persisted("sess_test", str(tmp_path)) is True
        assert not session_path.exists()

    def test_delete_persisted_not_exists(self, tmp_path: Any) -> None:
        assert CrawlSession.delete_persisted("nonexistent", str(tmp_path)) is False

    def test_list_persisted(self, tmp_path: Any) -> None:
        (tmp_path / "sess_1.json").write_text("{}")
        (tmp_path / "sess_2.json").write_text("{}")
        result = CrawlSession.list_persisted(str(tmp_path))
        assert "sess_1" in result
        assert "sess_2" in result

    def test_list_persisted_no_dir(self, tmp_path: Any) -> None:
        import os

        nonexistent = os.path.join(str(tmp_path), "nonexistent_sub")
        assert CrawlSession.list_persisted(nonexistent) == []


# ═══ Helper ═══


def asyncio_run(coro: Any) -> Any:
    """Run an async coroutine synchronously (for non-async tests)."""
    import asyncio

    return asyncio.run(coro)
