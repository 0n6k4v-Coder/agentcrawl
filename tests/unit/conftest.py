"""Pytest fixtures shared across unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_engine_manager():
    """Shared fixture for mocking the engine manager singleton.

    Patches ``agentcrawl.agent.tool._engine_manager`` and provides a
    pre-configured mock engine returned by ``get_engine``.  The mock
    engine comes with ``scrape``, ``crawl``, ``search``, ``batch_scrape``,
    ``map``, and ``startup`` already set up as ``AsyncMock`` instances —
    individual tests override return values / side effects as needed.

    The fixture yields the *mock manager* (the patched ``_engine_manager``).
    To retrieve the mock engine inside a test use ``mock_engine_manager.get_engine.return_value``.
    """
    with patch("agentcrawl.agent.tool._engine_manager") as mock_manager:
        mock_engine = MagicMock()
        mock_engine.scrape = AsyncMock()
        mock_engine.crawl = AsyncMock()
        mock_engine.search = AsyncMock()
        mock_engine.batch_scrape = AsyncMock()
        mock_engine.map = AsyncMock()
        mock_engine.startup = AsyncMock()
        mock_manager.get_engine = AsyncMock(return_value=mock_engine)
        mock_manager.shutdown = AsyncMock()
        yield mock_manager
