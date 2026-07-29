"""
AgentCrawl — Markdown Extractor
===================================

Extracts clean Markdown content from HTML. This is the standard
markdown extraction strategy — for LLM-optimized output with
aggressive noise removal, see FitMarkdownExtractor.

Features:
    - HTML to Markdown conversion
    - Main content extraction (skips nav, footer, sidebar)
    - Configurable link/image inclusion
    - Optional content filtering
    - Heading structure preservation
    - Table and code block support

Usage:
    from agentcrawl.extraction.markdown import MarkdownExtractor

    extractor = MarkdownExtractor()
    result = await extractor.extract(html=raw_html)
    print(result.data)  # Clean markdown string

    # With options
    extractor = MarkdownExtractor(
        include_links=True,
        include_images=True,
        only_main_content=True,
    )
    result = await extractor.extract(html=raw_html)

    # With CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(extraction=MarkdownExtractor())
"""

from __future__ import annotations

import logging
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionStrategy,
)

logger = logging.getLogger("agentcrawl.extraction.markdown")


# ══════════════════════════════════════════════════════════════
# Markdown Extractor
# ══════════════════════════════════════════════════════════════

class MarkdownExtractor(ExtractionStrategy):
    """
    Standard Markdown extraction from HTML.

    Converts HTML to clean Markdown with configurable options
    for links, images, and content filtering.

    Args:
        include_links: Include links in the output.
        include_images: Include images in the output.
        only_main_content: Extract only main content (skip nav, footer).
        include_tables: Preserve tables in GFM format.
        include_code_blocks: Preserve code blocks.
        code_block_style: Code block style ('fenced' or 'indented').
        heading_style: Heading style ('atx' for # or 'setext').
        bullet_marker: Unordered list marker ('-', '*', '+').
        content_filter: Optional content filter type ('none', 'pruning').
        content_filter_query: Query for BM25 filter.
        selectors: CSS selectors to target specific content.
        exclude_selectors: CSS selectors to exclude.
        config: Extraction configuration.

    Example:
        >>> extractor = MarkdownExtractor(
        ...     include_links=True,
        ...     only_main_content=True,
        ... )
        >>> result = await extractor.extract(html=raw_html)
        >>> print(result.data)
    """

    method_name = "markdown"

    def __init__(
        self,
        include_links: bool = True,
        include_images: bool = False,
        only_main_content: bool = True,
        include_tables: bool = True,
        include_code_blocks: bool = True,
        code_block_style: str = "fenced",
        heading_style: str = "atx",
        bullet_marker: str = "-",
        content_filter: str = "none",
        content_filter_query: str | None = None,
        selectors: list[str] | None = None,
        exclude_selectors: list[str] | None = None,
        config: ExtractionConfig | None = None,
        **kwargs: Any,
    ):
        super().__init__(config=config)

        self._include_links = include_links
        self._include_images = include_images
        self._only_main_content = only_main_content
        self._include_tables = include_tables
        self._include_code_blocks = include_code_blocks
        self._code_block_style = code_block_style
        self._heading_style = heading_style
        self._bullet_marker = bullet_marker
        self._content_filter = content_filter
        self._content_filter_query = content_filter_query
        self._selectors = selectors or []
        self._exclude_selectors = exclude_selectors or []

    # ──────────────────────────────────────────────────────────
    # Core Extraction
    # ──────────────────────────────────────────────────────────

    async def _extract(
        self,
        html: str = "",
        markdown: str = "",
        url: str = "",
        **kwargs: Any,
    ) -> Any:
        """
        Extract markdown from HTML content.

        Args:
            html: Raw HTML content.
            markdown: Pre-converted markdown (returned as-is if html is empty).
            url: Source URL.

        Returns:
            Clean markdown string.
        """
        # If we already have markdown and no HTML, return it
        if markdown and not html:
            return markdown

        if not html.strip():
            return ""

        # Step 1: Parse HTML and extract main content
        content_html = self._extract_content_html(html, url)

        # Step 2: Convert to markdown
        result_markdown = self._convert_to_markdown(content_html)

        # Step 3: Apply content filter (if configured)
        if self._content_filter and self._content_filter != "none":
            result_markdown = self._apply_filter(result_markdown)

        return result_markdown

    # ──────────────────────────────────────────────────────────
    # HTML Processing
    # ──────────────────────────────────────────────────────────

    def _extract_content_html(self, html: str, url: str = "") -> str:
        """
        Extract main content HTML from the full page.

        Args:
            html: Raw HTML.
            url: Source URL (for link resolution).

        Returns:
            Main content HTML string.
        """
        from agentcrawl.content.html_parser import HTMLParser

        parser = HTMLParser(html, base_url=url)

        main_content = parser.get_main_content(
            include_selectors=self._selectors or None,
            exclude_selectors=self._exclude_selectors or None,
            only_main=self._only_main_content,
        )

        return main_content.html

    def _convert_to_markdown(self, html: str) -> str:
        """
        Convert HTML to markdown.

        Args:
            html: HTML content.

        Returns:
            Markdown string.
        """
        from agentcrawl.content.html_to_markdown import HTMLToMarkdown, MarkdownOptions

        options = MarkdownOptions(
            include_links=self._include_links,
            include_images=self._include_images,
            code_block_style=self._code_block_style,
            heading_style=self._heading_style,
            bullet_marker=self._bullet_marker,
        )

        converter = HTMLToMarkdown(options)
        return converter.convert(html)

    # ──────────────────────────────────────────────────────────
    # Content Filtering
    # ──────────────────────────────────────────────────────────

    def _apply_filter(self, markdown: str) -> str:
        """
        Apply content filter to the markdown.

        Args:
            markdown: Markdown text.

        Returns:
            Filtered markdown.
        """
        try:
            from agentcrawl.content.content_filter import create_content_filter

            filter_kwargs: dict[str, Any] = {}
            if self._content_filter_query:
                filter_kwargs["query"] = self._content_filter_query

            content_filter = create_content_filter(
                self._content_filter,
                **filter_kwargs,
            )

            result = content_filter.apply(markdown)
            return result.filtered_text

        except Exception as e:
            logger.debug("Content filter failed: %s", e)
            return markdown

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "include_links": self._include_links,
            "include_images": self._include_images,
            "only_main_content": self._only_main_content,
            "include_tables": self._include_tables,
            "include_code_blocks": self._include_code_blocks,
            "code_block_style": self._code_block_style,
            "heading_style": self._heading_style,
            "bullet_marker": self._bullet_marker,
            "content_filter": self._content_filter,
            "selectors": self._selectors,
            "exclude_selectors": self._exclude_selectors,
        })
        return d

    def __repr__(self) -> str:
        return (
            f"MarkdownExtractor(links={self._include_links}, "
            f"images={self._include_images}, "
            f"main_only={self._only_main_content})"
        )
