"""
AgentCrawl — Fit Markdown Extractor
=======================================

Extracts clean, LLM-optimized Markdown from HTML by removing
noise, boilerplate, and non-content elements while preserving
document structure.

"Fit Markdown" is Markdown that has been trimmed to fit within
an LLM's context window while retaining maximum information
density. It removes:
    - Navigation, headers, footers, sidebars
    - Cookie banners, popups, modals
    - Advertisements and sponsored content
    - Social media widgets
    - Comment sections
    - Related/recommended content
    - Empty headings and sections
    - Excessive whitespace
    - Tracking pixels and hidden elements

While preserving:
    - Heading hierarchy (h1-h6)
    - Paragraphs and text content
    - Lists (ordered, unordered, nested)
    - Tables (GFM format)
    - Code blocks (fenced with language)
    - Blockquotes
    - Meaningful links
    - Images with alt text

Usage:
    from agentcrawl.extraction.fit_markdown import FitMarkdownExtractor

    extractor = FitMarkdownExtractor()
    result = await extractor.extract(html=raw_html)
    print(result.data)  # Clean markdown string

    # With options
    extractor = FitMarkdownExtractor(
        include_links=True,
        include_images=False,
        remove_boilerplate=True,
        max_length=10000,
    )
    result = await extractor.extract(html=raw_html)

    # With CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(extraction=FitMarkdownExtractor())
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionStrategy,
)

logger = logging.getLogger("agentcrawl.extraction.fit_markdown")


# ══════════════════════════════════════════════════════════════
# Noise Patterns
# ══════════════════════════════════════════════════════════════

# CSS class/ID patterns that indicate noise
NOISE_CLASS_PATTERNS: list[str] = [
    r"nav", r"navbar", r"navigation", r"menu", r"sidebar",
    r"footer", r"header", r"breadcrumb", r"pagination",
    r"comment", r"comments", r"disqus", r"social",
    r"share", r"sharing", r"related", r"recommend",
    r"advert", r"ad-", r"ads-", r"adsby", r"sponsor",
    r"popup", r"modal", r"overlay", r"cookie",
    r"banner", r"promo", r"newsletter", r"subscribe",
    r"widget", r"toc", r"table-of-contents",
    r"skip-to", r"sr-only", r"visually-hidden",
    r"gdpr", r"consent", r"privacy",
    r"cart", r"checkout", r"payment",
]

# Text patterns that indicate boilerplate
BOILERPLATE_TEXT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"cookie\s*(policy|consent|notice|banner|settings)", re.I),
    re.compile(r"(accept|reject|manage)\s*(all\s*)?cookies", re.I),
    re.compile(r"we\s+use\s+cookies", re.I),
    re.compile(r"subscribe\s+to\s+(our\s+)?newsletter", re.I),
    re.compile(r"(sign|subscribe)\s*(up)?\s*(for|to)\s*(our\s+)?(email|mailing)", re.I),
    re.compile(r"(follow|share)\s+(us\s+)?(on|via)\s+(twitter|facebook|instagram|linkedin)", re.I),
    re.compile(r"(all\s+)?rights?\s+reserved", re.I),
    re.compile(r"terms?\s+(of\s+)?(service|use|conditions)", re.I),
    re.compile(r"privacy\s+(policy|statement|notice)", re.I),
    re.compile(r"powered\s+by|built\s+with|made\s+with", re.I),
    re.compile(r"©\s*\d{4}", re.I),
    re.compile(r"download\s+(our\s+)?(app|application)", re.I),
    re.compile(r"(leave|post|write)\s+a\s+comment", re.I),
    re.compile(r"\d+\s+(comments?|replies|responses)", re.I),
    re.compile(r"(related|recommended|suggested)\s+(articles?|posts?|content)", re.I),
    re.compile(r"you\s+may\s+also\s+(like|enjoy|want)", re.I),
    re.compile(r"skip\s+to\s+(main\s+)?content", re.I),
    re.compile(r"toggle\s+(navigation|menu|sidebar)", re.I),
]

# HTML tags to always remove
REMOVE_TAGS: set[str] = {
    "script", "style", "noscript", "iframe", "svg", "canvas",
    "button", "input", "select", "textarea", "form",
    "dialog", "template", "embed", "object", "applet",
    "link", "meta", "head", "nav", "footer",
}


# ══════════════════════════════════════════════════════════════
# Fit Markdown Extractor
# ══════════════════════════════════════════════════════════════

class FitMarkdownExtractor(ExtractionStrategy):
    """
    Extracts clean, LLM-optimized Markdown from HTML.

    Produces "fit markdown" — content trimmed to maximize
    information density while fitting within LLM context windows.

    Args:
        include_links: Preserve meaningful links in output.
        include_images: Preserve images with alt text.
        include_tables: Preserve tables in GFM format.
        include_code_blocks: Preserve fenced code blocks.
        remove_boilerplate: Remove boilerplate text patterns.
        remove_empty_sections: Remove headings with no content.
        remove_noise_elements: Remove nav, footer, ads, etc.
        max_length: Maximum output length in characters (0 = unlimited).
        min_section_words: Minimum words for a section to be kept.
        normalize_whitespace: Collapse excessive whitespace.
        preserve_heading_hierarchy: Maintain heading level structure.
        config: Extraction configuration.

    Example:
        >>> extractor = FitMarkdownExtractor(
        ...     include_links=True,
        ...     remove_boilerplate=True,
        ...     max_length=10000,
        ... )
        >>> result = await extractor.extract(html=raw_html)
        >>> print(result.data)  # Clean markdown
        >>> print(f"Length: {len(result.data)} chars")
    """

    method_name = "fit_markdown"

    def __init__(
        self,
        include_links: bool = True,
        include_images: bool = False,
        include_tables: bool = True,
        include_code_blocks: bool = True,
        remove_boilerplate: bool = True,
        remove_empty_sections: bool = True,
        remove_noise_elements: bool = True,
        max_length: int = 0,
        min_section_words: int = 5,
        normalize_whitespace: bool = True,
        preserve_heading_hierarchy: bool = True,
        config: ExtractionConfig | None = None,
        **kwargs: Any,
    ):
        super().__init__(config=config)

        self._include_links = include_links
        self._include_images = include_images
        self._include_tables = include_tables
        self._include_code_blocks = include_code_blocks
        self._remove_boilerplate = remove_boilerplate
        self._remove_empty_sections = remove_empty_sections
        self._remove_noise_elements = remove_noise_elements
        self._max_length = max_length
        self._min_section_words = min_section_words
        self._normalize_whitespace = normalize_whitespace
        self._preserve_heading_hierarchy = preserve_heading_hierarchy

        # Compile noise patterns
        self._noise_regex = re.compile(
            "|".join(NOISE_CLASS_PATTERNS),
            re.IGNORECASE,
        )

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
        Extract fit markdown from HTML content.

        Args:
            html: Raw HTML content.
            markdown: Pre-converted markdown (used if html is empty).
            url: Source URL.

        Returns:
            Clean markdown string.
        """
        # If we already have markdown, clean it directly
        if markdown and not html:
            return self._clean_markdown(markdown)

        if not html.strip():
            return ""

        # Step 1: Parse HTML and extract main content
        clean_html = self._extract_main_content(html)

        # Step 2: Convert to markdown
        raw_markdown = self._convert_to_markdown(clean_html)

        # Step 3: Clean and optimize
        fit_markdown = self._clean_markdown(raw_markdown)

        # Step 4: Truncate if needed
        if self._max_length > 0 and len(fit_markdown) > self._max_length:
            fit_markdown = self._truncate(fit_markdown, self._max_length)

        return fit_markdown

    # ──────────────────────────────────────────────────────────
    # HTML Processing
    # ──────────────────────────────────────────────────────────

    def _extract_main_content(self, html: str) -> str:
        """
        Extract main content HTML, removing noise elements.

        Args:
            html: Raw HTML.

        Returns:
            Cleaned HTML string.
        """
        try:
            from copy import deepcopy

            from lxml import html as lxml_html
            from lxml.html import tostring
        except ImportError:
            # Fallback: return raw HTML
            return html

        try:
            tree = lxml_html.document_fromstring(html)
        except Exception:
            return html

        clone = deepcopy(tree)

        if self._remove_noise_elements:
            self._remove_noise_from_tree(clone)

        # Find main content container
        content_el = self._find_content_element(clone)

        if content_el is not None:
            try:
                return tostring(content_el, encoding="unicode", method="html")
            except Exception:
                pass

        # Fallback: return body
        body = clone.find(".//body")
        if body is not None:
            try:
                return tostring(body, encoding="unicode", method="html")
            except Exception:
                pass

        return html

    def _remove_noise_from_tree(self, element: Any) -> None:
        """Remove noise elements from an lxml tree (in-place)."""
        # Remove by tag
        for tag in REMOVE_TAGS:
            for el in element.iter(tag):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)

        # Remove by class/ID patterns
        for el in list(element.iter()):
            if not hasattr(el, "get"):
                continue

            class_attr = el.get("class", "")
            id_attr = el.get("id", "")
            role_attr = el.get("role", "")

            if (
                self._noise_regex.search(class_attr)
                or self._noise_regex.search(id_attr)
                or role_attr in ("navigation", "banner", "complementary")
            ):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)

        # Remove hidden elements
        for el in list(element.iter()):
            if not hasattr(el, "get"):
                continue
            style = el.get("style", "")
            if "display:none" in style.replace(" ", "") or "display: none" in style:
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
            if el.get("hidden") is not None or el.get("aria-hidden") == "true":
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)

    def _find_content_element(self, tree: Any) -> Any | None:
        """Find the main content element in the tree."""
        # Priority selectors
        selectors = [
            "article",
            "main",
            "[role='main']",
            "#content",
            "#main-content",
            "#main",
            ".content",
            ".main-content",
            ".post-content",
            ".article-content",
            ".entry-content",
        ]

        try:
            from lxml.cssselect import CSSSelector

            for selector in selectors:
                try:
                    css = CSSSelector(selector)
                    matches = css(tree)
                    if matches:
                        # Pick the one with the most text
                        best = max(matches, key=lambda el: len(el.text_content()))
                        if len(best.text_content().strip()) > 100:
                            return best
                except Exception:
                    continue
        except ImportError:
            pass

        return None

    def _convert_to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        from agentcrawl.content.html_to_markdown import HTMLToMarkdown, MarkdownOptions

        converter = HTMLToMarkdown(MarkdownOptions(
            include_links=self._include_links,
            include_images=self._include_images,
            code_block_style="fenced" if self._include_code_blocks else "indented",
        ))

        return converter.convert(html)

    # ──────────────────────────────────────────────────────────
    # Markdown Cleaning
    # ──────────────────────────────────────────────────────────

    def _clean_markdown(self, markdown: str) -> str:
        """
        Clean and optimize markdown for LLM consumption.

        Args:
            markdown: Raw markdown text.

        Returns:
            Cleaned markdown.
        """
        if not markdown:
            return ""

        text = markdown

        # Remove boilerplate
        if self._remove_boilerplate:
            text = self._remove_boilerplate_text(text)

        # Remove empty sections
        if self._remove_empty_sections:
            text = self._remove_empty_sections_from_text(text)

        # Remove sections with too few words
        text = self._remove_short_sections(text)

        # Normalize whitespace
        if self._normalize_whitespace:
            text = self._normalize_ws(text)

        # Remove excessive horizontal rules
        text = re.sub(r"(\n---\n){2,}", "\n---\n", text)

        # Remove excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    def _remove_boilerplate_text(self, text: str) -> str:
        """Remove boilerplate text patterns."""
        lines = text.split("\n")
        kept: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Check against boilerplate patterns
            is_boilerplate = False
            for pattern in BOILERPLATE_TEXT_PATTERNS:
                if pattern.search(stripped):
                    is_boilerplate = True
                    break

            if not is_boilerplate:
                kept.append(line)

        return "\n".join(kept)

    def _remove_empty_sections_from_text(self, text: str) -> str:
        """Remove headings that have no content below them."""
        lines = text.split("\n")
        result: list[str] = []
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        i = 0
        while i < len(lines):
            line = lines[i]
            match = heading_pattern.match(line.strip())

            if match:
                # Check if there's content before the next heading
                has_content = False
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if heading_pattern.match(next_line):
                        break
                    if next_line:
                        has_content = True
                        break
                    j += 1

                if has_content:
                    result.append(line)
                # else: skip empty heading
            else:
                result.append(line)

            i += 1

        return "\n".join(result)

    def _remove_short_sections(self, text: str) -> str:
        """Remove sections with fewer than min_section_words words."""
        if self._min_section_words <= 0:
            return text

        lines = text.split("\n")
        result: list[str] = []
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        current_section: list[str] = []
        current_heading: str | None = None

        def _flush_section() -> None:
            nonlocal current_section, current_heading
            if current_heading is not None:
                section_text = "\n".join(current_section)
                word_count = len(section_text.split())
                if word_count >= self._min_section_words:
                    result.append(current_heading)
                    result.extend(current_section)
            else:
                result.extend(current_section)
            current_section = []
            current_heading = None

        for line in lines:
            match = heading_pattern.match(line.strip())
            if match:
                _flush_section()
                current_heading = line
            else:
                current_section.append(line)

        _flush_section()

        return "\n".join(result)

    @staticmethod
    def _normalize_ws(text: str) -> str:
        """Normalize whitespace in text."""
        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove trailing whitespace per line
        lines = [line.rstrip() for line in text.split("\n")]
        text = "\n".join(lines)

        # Remove zero-width characters
        text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)

        # Collapse multiple spaces (but not in code blocks)
        # Simple approach: collapse outside of ``` blocks
        parts = text.split("```")
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"[ \t]{2,}", " ", parts[i])
        text = "```".join(parts)

        return text

    def _truncate(self, text: str, max_length: int) -> str:
        """
        Truncate text to max_length at a natural boundary.

        Tries to break at:
            1. Paragraph boundary (\\n\\n)
            2. Sentence boundary (. ! ?)
            3. Word boundary (space)
        """
        if len(text) <= max_length:
            return text

        # Try paragraph boundary
        truncated = text[:max_length]
        last_para = truncated.rfind("\n\n")
        if last_para > max_length * 0.7:
            return truncated[:last_para].strip() + "\n\n[... content truncated]"

        # Try sentence boundary
        last_sentence = max(
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if last_sentence > max_length * 0.7:
            return truncated[:last_sentence + 1].strip() + "\n\n[... content truncated]"

        # Try word boundary
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.7:
            return truncated[:last_space].strip() + "\n\n[... content truncated]"

        return truncated.strip() + "\n\n[... content truncated]"

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "include_links": self._include_links,
            "include_images": self._include_images,
            "include_tables": self._include_tables,
            "include_code_blocks": self._include_code_blocks,
            "remove_boilerplate": self._remove_boilerplate,
            "remove_empty_sections": self._remove_empty_sections,
            "remove_noise_elements": self._remove_noise_elements,
            "max_length": self._max_length,
            "min_section_words": self._min_section_words,
            "normalize_whitespace": self._normalize_whitespace,
        })
        return d

    def __repr__(self) -> str:
        return (
            f"FitMarkdownExtractor(links={self._include_links}, "
            f"boilerplate={self._remove_boilerplate}, "
            f"max_len={self._max_length})"
        )
