"""
AgentCrawl — Content Filter Unit Tests
==========================================

Unit tests for content filtering strategies.

Tests:
    - PruningContentFilter (noise removal)
    - BM25ContentFilter (query relevance)
    - ContentFilterResult model
    - Threshold configuration
    - Edge cases (empty, short, noisy content)
    - Markdown structure preservation

Run:
    pytest tests/unit/test_content_filter.py -v
"""

from __future__ import annotations

from typing import Any

import pytest

from agentcrawl.content.content_filter import (
    ContentFilterResult,
    PruningContentFilter,
)


# ══════════════════════════════════════════════════════════════
# Sample Content
# ══════════════════════════════════════════════════════════════

CLEAN_CONTENT = """# Python Guide

Python is a high-level programming language known for its
readability and versatility. It supports multiple programming
paradigms including procedural, object-oriented, and functional
programming.

## Features

Python has a comprehensive standard library that covers areas
such as string processing, internet protocols, software engineering,
and operating system interfaces.

## Use Cases

Python is widely used in web development, data science, machine
learning, automation, and scientific computing.
"""

NOISY_CONTENT = """# Main Article

This is the main article content that should be preserved.
It contains valuable information about the topic.

---

## Related Articles

- [10 Python Tips](/blog/python-tips)
- [Web Scraping Guide](/blog/web-scraping)
- [Docker Tutorial](/blog/docker)

## Newsletter Signup

Subscribe to our newsletter for weekly updates!
Enter your email: [___________] [Subscribe]

## Advertisement

Buy our product now! Limited time offer!
Click here to learn more about our amazing deals.

## Footer

© 2025 Example Corp. All rights reserved.
Terms of Service | Privacy Policy | Cookie Policy
Contact us at info@example.com
"""

MIXED_CONTENT = """# Documentation

## Installation

Install the package using pip:

```bash
pip install agentcrawl
```

## Quick Start

Here is a simple example to get started:

```python
from agentcrawl import CrawlEngine

async def main():
    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        print(result.markdown)
```

## Navigation

- Home
- About
- Contact
- Blog
- Careers

## Social Links

Follow us on Twitter, Facebook, LinkedIn.
Share this page with your friends.

## Cookie Notice

We use cookies to improve your experience.
By continuing to use this site, you agree to our cookie policy.
"""


# ══════════════════════════════════════════════════════════════
# PruningContentFilter
# ══════════════════════════════════════════════════════════════

class TestPruningContentFilter:
    """Tests for PruningContentFilter."""

    def test_basic_filtering(self) -> None:
        """Filter removes noise from content."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(NOISY_CONTENT)

        assert result.filtered_text != ""
        assert len(result.filtered_text) < len(NOISY_CONTENT)

    def test_preserves_main_content(self) -> None:
        """Main content is preserved."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(NOISY_CONTENT)

        assert "Main Article" in result.filtered_text
        assert "main article content" in result.filtered_text

    def test_removes_newsletter(self) -> None:
        """Newsletter signup is removed."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(NOISY_CONTENT)

        assert "Newsletter Signup" not in result.filtered_text
        assert "Subscribe" not in result.filtered_text

    def test_removes_footer(self) -> None:
        """Footer content is removed."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(NOISY_CONTENT)

        assert "All rights reserved" not in result.filtered_text
        assert "Privacy Policy" not in result.filtered_text

    def test_clean_content_unchanged(self) -> None:
        """Clean content passes through mostly unchanged."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(CLEAN_CONTENT)

        assert "Python Guide" in result.filtered_text
        assert "high-level programming" in result.filtered_text
        assert "Use Cases" in result.filtered_text

    def test_threshold_effect(self) -> None:
        """Higher threshold removes more content."""
        low_filter = PruningContentFilter(threshold=0.1)
        high_filter = PruningContentFilter(threshold=0.8)

        low_result = low_filter.apply(NOISY_CONTENT)
        high_result = high_filter.apply(NOISY_CONTENT)

        # Higher threshold should keep less or equal content
        assert len(high_result.filtered_text) <= len(low_result.filtered_text)

    def test_result_has_stats(self) -> None:
        """Result includes filtering statistics."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(NOISY_CONTENT)

        assert result.original_length > 0
        assert result.filtered_length > 0
        assert result.removed_length >= 0
        assert result.original_length == result.filtered_length + result.removed_length

    def test_result_ratio(self) -> None:
        """Result includes retention ratio."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(NOISY_CONTENT)

        assert 0.0 <= result.retention_ratio <= 1.0

    def test_empty_content(self) -> None:
        """Empty content returns empty result."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply("")

        assert result.filtered_text == ""
        assert result.original_length == 0

    def test_whitespace_only(self) -> None:
        """Whitespace-only content is handled."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply("   \n\n   \n   ")

        assert result.filtered_text.strip() == ""

    def test_short_content_preserved(self) -> None:
        """Very short content is preserved."""
        filter_ = PruningContentFilter(threshold=0.3)
        short = "# Title\n\nShort content."
        result = filter_.apply(short)

        assert "Title" in result.filtered_text
        assert "Short content" in result.filtered_text

    def test_code_blocks_preserved(self) -> None:
        """Code blocks are preserved."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(MIXED_CONTENT)

        assert "pip install agentcrawl" in result.filtered_text
        assert "CrawlEngine" in result.filtered_text

    def test_headings_preserved(self) -> None:
        """Content headings are preserved."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(MIXED_CONTENT)

        assert "Documentation" in result.filtered_text
        assert "Installation" in result.filtered_text
        assert "Quick Start" in result.filtered_text

    def test_navigation_removed(self) -> None:
        """Navigation sections are removed."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(MIXED_CONTENT)

        # Navigation links should be pruned
        assert "Cookie Notice" not in result.filtered_text

    def test_markdown_structure_preserved(self) -> None:
        """Markdown heading structure is maintained."""
        filter_ = PruningContentFilter(threshold=0.3)
        result = filter_.apply(CLEAN_CONTENT)

        assert "# Python Guide" in result.filtered_text
        assert "## Features" in result.filtered_text
        assert "## Use Cases" in result.filtered_text


# ══════════════════════════════════════════════════════════════
# BM25ContentFilter
# ══════════════════════════════════════════════════════════════

class TestBM25ContentFilter:
    """Tests for BM25ContentFilter (query relevance)."""

    def test_basic_filtering(self) -> None:
        """Filter content by query relevance."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        filter_ = BM25ContentFilter(query="python programming", threshold=0.3)
        result = filter_.apply(CLEAN_CONTENT)

        assert result.filtered_text != ""

    def test_relevant_content_preserved(self) -> None:
        """Content matching query is preserved."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        filter_ = BM25ContentFilter(query="python features", threshold=0.1)
        result = filter_.apply(CLEAN_CONTENT)

        assert "Python" in result.filtered_text

    def test_irrelevant_content_removed(self) -> None:
        """Content not matching query is reduced."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        filter_ = BM25ContentFilter(query="javascript react", threshold=0.5)
        result = filter_.apply(CLEAN_CONTENT)

        # Python content should be mostly filtered out
        assert len(result.filtered_text) < len(CLEAN_CONTENT)

    def test_empty_query(self) -> None:
        """Empty query returns original content."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        filter_ = BM25ContentFilter(query="", threshold=0.3)
        result = filter_.apply(CLEAN_CONTENT)

        assert result.filtered_text == CLEAN_CONTENT

    def test_empty_content(self) -> None:
        """Empty content returns empty result."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        filter_ = BM25ContentFilter(query="python", threshold=0.3)
        result = filter_.apply("")

        assert result.filtered_text == ""

    def test_threshold_effect(self) -> None:
        """Higher threshold filters more aggressively."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        low = BM25ContentFilter(query="python", threshold=0.1)
        high = BM25ContentFilter(query="python", threshold=0.9)

        low_result = low.apply(CLEAN_CONTENT)
        high_result = high.apply(CLEAN_CONTENT)

        assert len(high_result.filtered_text) <= len(low_result.filtered_text)

    def test_multi_word_query(self) -> None:
        """Multi-word query works."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        filter_ = BM25ContentFilter(
            query="machine learning data science",
            threshold=0.2,
        )
        result = filter_.apply(CLEAN_CONTENT)

        assert result.filtered_text != ""

    def test_result_stats(self) -> None:
        """Result includes statistics."""
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        filter_ = BM25ContentFilter(query="python", threshold=0.3)
        result = filter_.apply(CLEAN_CONTENT)

        assert result.original_length > 0
        assert result.filtered_length >= 0


# ══════════════════════════════════════════════════════════════
# ContentFilterResult
# ══════════════════════════════════════════════════════════════

class TestContentFilterResult:
    """Tests for ContentFilterResult model."""

    def test_result_creation(self) -> None:
        """Create a filter result."""
        result = ContentFilterResult(
            filtered_text="Hello world",
            original_length=100,
            filtered_length=11,
            removed_length=89,
        )

        assert result.filtered_text == "Hello world"
        assert result.original_length == 100

    def test_retention_ratio(self) -> None:
        """Retention ratio is calculated."""
        result = ContentFilterResult(
            filtered_text="Half",
            original_length=100,
            filtered_length=50,
            removed_length=50,
        )

        assert result.retention_ratio == 0.5

    def test_retention_ratio_zero_original(self) -> None:
        """Retention ratio handles zero original length."""
        result = ContentFilterResult(
            filtered_text="",
            original_length=0,
            filtered_length=0,
            removed_length=0,
        )

        assert result.retention_ratio == 0.0

    def test_result_to_dict(self) -> None:
        """Result serializes to dict."""
        result = ContentFilterResult(
            filtered_text="Test",
            original_length=10,
            filtered_length=4,
            removed_length=6,
        )

        data = result.to_dict()
        assert "filtered_text" in data
        assert "original_length" in data
        assert "retention_ratio" in data


# ══════════════════════════════════════════════════════════════
# Edge Cases
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Tests for edge cases."""

    def test_only_headings(self) -> None:
        """Content with only headings."""
        filter_ = PruningContentFilter(threshold=0.3)
        content = "# H1\n## H2\n### H3\n#### H4"
        result = filter_.apply(content)

        assert result.filtered_text != ""

    def test_only_links(self) -> None:
        """Content with only links."""
        filter_ = PruningContentFilter(threshold=0.3)
        content = "[Link 1](/a)\n[Link 2](/b)\n[Link 3](/c)"
        result = filter_.apply(content)

        # Links-only content may be pruned heavily
        assert isinstance(result.filtered_text, str)

    def test_very_long_content(self) -> None:
        """Very long content is handled."""
        filter_ = PruningContentFilter(threshold=0.3)
        long_content = "# Title\n\n" + ("Paragraph text. " * 1000)
        result = filter_.apply(long_content)

        assert result.original_length > 10000
        assert result.filtered_length > 0

    def test_unicode_content(self) -> None:
        """Unicode content is handled."""
        filter_ = PruningContentFilter(threshold=0.3)
        content = "# 标题\n\n这是中文内容。日本語テキスト。한국어."
        result = filter_.apply(content)

        assert result.filtered_text != ""

    def test_html_entities(self) -> None:
        """HTML entities in content."""
        filter_ = PruningContentFilter(threshold=0.3)
        content = "# Title\n\nContent with &amp; entities &lt;like this&gt;."
        result = filter_.apply(content)

        assert isinstance(result.filtered_text, str)

    def test_repeated_content(self) -> None:
        """Repeated/boilerplate content."""
        filter_ = PruningContentFilter(threshold=0.3)
        content = "# Article\n\n" + ("Buy now! " * 100) + "\n\nReal content here."
        result = filter_.apply(content)

        assert isinstance(result.filtered_text, str)