"""
AgentCrawl — Output Formatters Layer
=======================================

Output formatting for crawl results in multiple formats:
HTML, JSON, Markdown, and screenshots.

Modules:
    html        — HTML output with sanitization and templates
    json        — JSON/JSONL output with field selection
    markdown    — Markdown output with front matter and citations
    screenshot  — Screenshot capture, storage, and comparison

Quick Start:
    from agentcrawl.output import (
        HtmlOutputFormatter,
        JsonOutputFormatter,
        MarkdownOutputFormatter,
        ScreenshotHandler,
    )

    # HTML output
    formatter = HtmlOutputFormatter(sanitize=True)
    html = formatter.format(result)

    # JSON output
    formatter = JsonOutputFormatter(pretty=True, fields=["url", "markdown"])
    json_str = formatter.format(result)

    # Markdown output
    formatter = MarkdownOutputFormatter(include_citations=True)
    md = formatter.format(result)

    # Screenshot
    handler = ScreenshotHandler()
    handler.save(result, "page.png")
    info = handler.get_info(result.screenshot)
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# HTML
# ──────────────────────────────────────────────────────────────
from agentcrawl.output.html import (
    HtmlOutputFormatter,
    HtmlSanitizer,
)

# ──────────────────────────────────────────────────────────────
# JSON
# ──────────────────────────────────────────────────────────────
from agentcrawl.output.json import JsonOutputFormatter

# ──────────────────────────────────────────────────────────────
# Markdown
# ──────────────────────────────────────────────────────────────
from agentcrawl.output.markdown import MarkdownOutputFormatter

# ──────────────────────────────────────────────────────────────
# Screenshot
# ──────────────────────────────────────────────────────────────
from agentcrawl.output.screenshot import (
    ScreenshotDiff,
    ScreenshotHandler,
    ScreenshotInfo,
)

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # HTML
    "HtmlOutputFormatter",
    "HtmlSanitizer",
    # JSON
    "JsonOutputFormatter",
    # Markdown
    "MarkdownOutputFormatter",
    # Screenshot
    "ScreenshotHandler",
    "ScreenshotInfo",
    "ScreenshotDiff",
]
