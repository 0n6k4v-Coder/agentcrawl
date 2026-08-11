"""Set F — MCP Release Readiness & Documentation Closure Tests

These tests verify the final release-readiness invariants that are not
sufficiently covered by the existing B/C/D/E suites. They focus on:

* REQ-F01 — Repository baseline integrity (HEAD, branch, no new commits)
* REQ-F03 — Canonical contract consistency (count, order, no duplicates)
* REQ-F06 — HTTP/stdio schema equivalence (independent verification)
* REQ-F07 — Compatibility alias safety (no legacy transports instantiated)
* REQ-F08 — Legacy transport elimination (source-level audit)
* REQ-F11 — Documentation closure (MCP_MIGRATION.md reference resolution)

All tests are local/deterministic — no external website is contacted.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import subprocess
from pathlib import Path
from shutil import which
from unittest.mock import AsyncMock, MagicMock

import pytest
from server.mcp.tools import CANONICAL_TOOL_ORDER, TOOL_DEFINITIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
_GIT: str = which("git") or "git"

EXPECTED_NAMES = [
    "scrape_webpage",
    "search_web",
    "crawl_website",
    "discover_urls",
    "extract_data",
    "batch_scrape",
]

# Patterns that indicate active legacy transport implementation (not just
# documentation/comment references).
_LEGACY_IMPL_PATTERNS = [
    "from mcp.client.sse",
    "import mcp.client.sse",
    "from mcp.client.websocket",
    "import mcp.client.websocket",
    "SseServerTransport(",
]


# ══════════════════════════════════════════════════════════════
# REQ-F01 — Repository Baseline Integrity
# ══════════════════════════════════════════════════════════════


class TestRepositoryBaselineIntegrity:
    """Verify the repository identity, branch, and HEAD are unchanged."""

    def test_branch_is_mcp_modernization(self):
        """Current branch must be refactor/mcp-modernization."""
        result = subprocess.run(  # noqa: S603
            [_GIT, "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.stdout.strip() == "refactor/mcp-modernization"

    def test_head_matches_expected(self):
        """HEAD must remain 52b4012b453447c16540dfd9698d499b0105399c."""
        result = subprocess.run(  # noqa: S603
            [_GIT, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.stdout.strip() == "52b4012b453447c16540dfd9698d499b0105399c"

    def test_no_commit_created_by_set_f(self):
        """HEAD must still match the base commit — no new commits."""
        result = subprocess.run(  # noqa: S603
            [_GIT, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.stdout.strip() == "52b4012b453447c16540dfd9698d499b0105399c"


# ══════════════════════════════════════════════════════════════
# REQ-F03 — Canonical Contract Integrity
# ══════════════════════════════════════════════════════════════


class TestCanonicalContractIntegrity:
    """Verify exactly six canonical tools, deterministic order, no duplicates."""

    def test_exact_count(self):
        assert len(TOOL_DEFINITIONS) == 6

    def test_deterministic_order(self):
        assert CANONICAL_TOOL_ORDER == EXPECTED_NAMES

    def test_no_duplicate_names(self):
        names = [t.name for t in TOOL_DEFINITIONS]
        assert len(names) == len(set(names))

    def test_no_web_screenshot(self):
        names = [t.name for t in TOOL_DEFINITIONS]
        assert "web_screenshot" not in names

    def test_no_legacy_names(self):
        legacy = {
            "web_scrape",
            "web_crawl",
            "web_search",
            "web_map",
            "web_extract",
            "web_screenshot",
            "web_batch_scrape",
        }
        names = {t.name for t in TOOL_DEFINITIONS}
        assert not (names & legacy)

    def test_every_tool_has_exactly_one_handler(self):
        """Each tool has exactly one callable handler; no handler shared."""
        handler_ids = [id(t.handler) for t in TOOL_DEFINITIONS]
        assert len(handler_ids) == len(set(handler_ids))

    def test_handler_names_unique(self):
        names = [t.handler.__name__ for t in TOOL_DEFINITIONS]
        assert len(names) == len(set(names))


# ══════════════════════════════════════════════════════════════
# REQ-F06 — HTTP/stdio Contract Equivalence
# ══════════════════════════════════════════════════════════════


class TestHttpStdioContractEquivalence:
    """Verify HTTP and stdio expose the same canonical contract."""

    def test_server_definitions_are_source_of_truth(self):
        """The server's list_tools callback iterates TOOL_DEFINITIONS."""
        import server.mcp.server as srv

        src = inspect.getsource(srv)
        assert "TOOL_DEFINITIONS" in src

    def test_streamable_http_app_exposes_mcp_route(self):
        from server.mcp.server import create_mcp_server

        app = create_mcp_server().streamable_http_app(stateless_http=True)
        paths = {r.path for r in app.router.routes if hasattr(r, "path") and r.path}
        assert "/mcp" in paths

    def test_no_sse_or_messages_routes(self):
        from server.mcp.server import create_mcp_server

        app = create_mcp_server().streamable_http_app(stateless_http=True)
        paths = {r.path for r in app.router.routes if hasattr(r, "path") and r.path}
        assert "/sse" not in paths
        assert "/messages/" not in paths
        assert "/mcp" in paths


# ══════════════════════════════════════════════════════════════
# REQ-F07 — Compatibility Alias Safety
# ══════════════════════════════════════════════════════════════


class TestCompatibilityAliasSafety:
    """Verify create_sse_client and create_websocket_client are safe aliases."""

    def test_create_sse_client_is_create_http_client(self):
        from agentcrawl.agent.mcp_client import create_http_client, create_sse_client

        assert create_sse_client is create_http_client

    def test_create_websocket_client_returns_http_transport(self):
        from agentcrawl.agent.mcp_client import MCPClient, create_websocket_client

        client = create_websocket_client(url="ws://localhost:9000/ws")
        assert isinstance(client, MCPClient)
        assert client._transport_type.value == "http"
        # URL must have been rewritten from ws:// to http://
        assert client._url == "http://localhost:9000/ws"

    def test_no_legacy_transport_imports_in_client(self):
        """Client source must not import legacy transports."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        for pattern in _LEGACY_IMPL_PATTERNS:
            assert pattern not in src, f"Legacy implementation pattern found: {pattern}"

    def test_client_uses_native_sdk_primitives(self):
        """Client imports the native MCP SDK 2.0.0 client primitives."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        assert "ClientSession" in src
        assert "streamable_http_client" in src
        assert "stdio_client" in src
        assert "StdioServerParameters" in src


# ══════════════════════════════════════════════════════════════
# REQ-F08 — Legacy Transport Elimination (Source Audit)
# ══════════════════════════════════════════════════════════════


class TestLegacyTransportElimination:
    """Repository-wide audit for legacy transport code."""

    def test_server_no_legacy_imports(self):
        """server/mcp/server.py must not import legacy transports."""
        import server.mcp.server as srv

        src = inspect.getsource(srv)
        for pattern in _LEGACY_IMPL_PATTERNS:
            assert pattern not in src, f"Legacy pattern in server: {pattern}"

    def test_server_no_sse_messages_routes(self):
        """Server source must not register /sse or /messages/ routes."""
        from server.mcp.server import create_mcp_server

        app = create_mcp_server().streamable_http_app(stateless_http=True)
        paths = {r.path for r in app.router.routes if hasattr(r, "path") and r.path}
        assert "/sse" not in paths
        assert "/messages/" not in paths
        assert "/mcp" in paths

    def test_server_run_sse_raises(self):
        """run_sse must raise RuntimeError (backward-compat stub)."""
        from server.mcp.server import run_sse

        with pytest.raises(RuntimeError, match="Legacy SSE"):
            asyncio.run(run_sse())

    def test_transport_type_no_legacy_members(self):
        from agentcrawl.agent.mcp_client import TransportType

        members = {m.name for m in TransportType}
        assert members == {"HTTP", "STDIO"}


# ══════════════════════════════════════════════════════════════
# REQ-F11 — Documentation Closure
# ══════════════════════════════════════════════════════════════


class TestDocumentationClosure:
    """Verify migration documentation reference is resolved."""

    @property
    def _doc_path(self):
        return REPO_ROOT / "docs" / "MCP_MIGRATION.md"

    def test_mcp_migration_doc_exists(self):
        """docs/MCP_MIGRATION.md must exist (resolving the stale docstring reference)."""
        assert self._doc_path.exists(), f"Migration doc not found at {self._doc_path}"

    def test_server_docstring_migration_reference_valid(self):
        """The docs/MCP_MIGRATION.md reference in server.py now resolves."""
        assert self._doc_path.exists()

    def test_mcp_migration_doc_contains_required_sections(self):
        """MCP_MIGRATION.md must document key migration facts."""
        content = self._doc_path.read_text(encoding="utf-8")
        # Must mention MCP SDK 2.0.0
        assert "2.0.0" in content
        # Must document the /mcp endpoint
        assert "/mcp" in content
        # Must document stdio transport
        assert "stdio" in content
        # Must list the six canonical tools
        for name in EXPECTED_NAMES:
            assert name in content, f"Canonical tool {name} not in migration doc"
        # Must state web_screenshot is unsupported
        assert "web_screenshot" in content
        # Must list deferred features
        assert "Authorization" in content
        assert "MRTR" in content
        assert "Sampling" in content
        assert "Roots" in content

    def test_mcp_migration_doc_deferred_not_claimed_implemented(self):
        """Migration doc must not claim deferred features are implemented."""
        content = self._doc_path.read_text(encoding="utf-8")
        # The "Deferred Functionality" section must clearly state not implemented.
        deferred_idx = content.lower().find("deferred")
        assert deferred_idx != -1, "No 'Deferred' section found"
        deferred_section = content[deferred_idx:]
        assert (
            "not yet implemented" in deferred_section.lower()
            or "not implemented" in deferred_section.lower()
        )

    def test_readme_matches_runtime(self):
        """README MCP section must match actual runtime commands."""
        readme = REPO_ROOT / "README.md"
        content = readme.read_text(encoding="utf-8")
        # README must document MCP SDK 2.0.0
        assert "2.0.0" in content
        # README must document /mcp endpoint
        assert "/mcp" in content
        # README must document Streamable HTTP
        assert "Streamable HTTP" in content
        # README must document stdio transport command
        assert "--transport stdio" in content
        # README must document HTTP transport command
        assert "--transport http" in content
        # Verify the canonical tools are in the MCP section
        mcp_section = content[content.find("### MCP") :]
        assert "scrape_webpage" in mcp_section
        assert "batch_scrape" in mcp_section

    def test_run_sse_error_mentions_migration_doc(self):
        """run_sse RuntimeError must reference docs/MCP_MIGRATION.md."""
        import server.mcp.server as srv

        src = inspect.getsource(srv)
        assert "MCP_MIGRATION.md" in src

    def test_server_docstring_mentions_migration_doc(self):
        """Module docstring in server.py references docs/MCP_MIGRATION.md."""
        import server.mcp.server as srv

        src = inspect.getsource(srv)
        assert "MCP_MIGRATION" in src


# ══════════════════════════════════════════════════════════════
# REQ-F10 — Lifecycle & Resource Cleanup
# ══════════════════════════════════════════════════════════════


class TestLifecycleAndStatelessness:
    """Verify client lifecycle cleanup and statelessness invariants."""

    def test_client_cleanup_on_disconnect(self):
        """MCPClient._cleanup resets all state."""
        from agentcrawl.agent.mcp_client import MCPClient, MCPServerInfo, MCPToolInfo

        client = MCPClient(transport="http", url="http://localhost:9999/mcp")
        client._connected = True
        client._session = MagicMock()
        client._session.__aexit__ = AsyncMock(return_value=None)
        client._transport_cm = MagicMock()
        client._transport_cm.__aexit__ = AsyncMock(return_value=None)
        client._server_info = MCPServerInfo(name="test", version="1.0")
        client._tools_cache = [MCPToolInfo(name="t", description="d", input_schema={})]
        asyncio.run(client._cleanup())
        assert client._connected is False
        assert client._session is None
        assert client._transport_cm is None
        assert client._tools_cache is None
        assert client._server_info is None

    def test_no_persistent_session_store_attribute(self):
        """Client must not have a persistent MCP session store."""
        from agentcrawl.agent.mcp_client import MCPClient

        assert not hasattr(MCPClient, "_session_store")
        assert not hasattr(MCPClient, "_global_session")


# ══════════════════════════════════════════════════════════════
# Deferred feature isolation
# ══════════════════════════════════════════════════════════════


class TestDeferredFeatureIsolation:
    """Verify deferred MCP features are not implemented in client source."""

    def test_no_mcp_authorization_in_server(self):
        """Server app has no auth middleware for MCP routes."""
        from server.mcp.server import create_mcp_server

        app = create_mcp_server().streamable_http_app(stateless_http=True)
        for mw in app.user_middleware:
            mw_cls = getattr(mw, "cls", None)
            mw_cls_name = mw_cls.__name__ if mw_cls and hasattr(mw_cls, "__name__") else str(mw_cls)
            lower = mw_cls_name.lower()
            assert "auth" not in lower
            assert "token" not in lower

    def test_no_deferred_feature_implementation_in_client(self):
        """Client source must not implement deferred MCP features."""
        import agentcrawl.agent.mcp_client as mod

        src = inspect.getsource(mod)
        forbidden = [
            "mcp.server.auth",
            "mcp.types.TaskRequest",
            "mcp.types.SamplingRequest",
            "roots/list",
            "tasks/send",
        ]
        for pattern in forbidden:
            assert pattern not in src, f"Deferred feature pattern found: {pattern}"

    def test_no_mcp_tasks_in_client(self):
        import agentcrawl.agent.mcp_client as mod

        assert not hasattr(mod, "MCPTask")
        assert not hasattr(mod, "TaskError")


# ══════════════════════════════════════════════════════════════
# Duplicate client integrity
# ══════════════════════════════════════════════════════════════


class TestDuplicateClientIntegrity:
    """Verify agent/ and agentcrawl/agent/ are byte-identical."""

    def test_mcp_client_files_identical(self):
        hash_a = hashlib.sha256((REPO_ROOT / "agent/mcp_client.py").read_bytes()).hexdigest()
        hash_b = hashlib.sha256(
            (REPO_ROOT / "agentcrawl/agent/mcp_client.py").read_bytes()
        ).hexdigest()
        assert hash_a == hash_b

    def test_agent_init_files_identical(self):
        hash_a = hashlib.sha256((REPO_ROOT / "agent/__init__.py").read_bytes()).hexdigest()
        hash_b = hashlib.sha256(
            (REPO_ROOT / "agentcrawl/agent/__init__.py").read_bytes()
        ).hexdigest()
        assert hash_a == hash_b
