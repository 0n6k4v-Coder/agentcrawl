"""
AgentCrawl — HTML to Markdown Converter
==========================================

Converts HTML to clean, LLM-optimized Markdown with support for
all standard elements, GFM tables, fenced code blocks, and
configurable noise removal.

Uses a custom lxml-based walker for maximum control over output
quality, with markdownify as a fallback.

Features:
    - Headings (h1-h6) with ATX style (#)
    - Bold, italic, strikethrough, inline code
    - Links with optional reference-style output
    - Images with alt text
    - Ordered and unordered lists (nested)
    - GFM tables with alignment
    - Fenced code blocks with language detection
    - Blockquotes (nested)
    - Horizontal rules
    - Noise removal (scripts, styles, nav, ads)
    - Whitespace normalization
    - Configurable link/image inclusion

Usage:
    from agentcrawl.content.html_to_markdown import HTMLToMarkdown

    converter = HTMLToMarkdown()
    markdown = converter.convert(html_string)
    print(markdown)

    # With options
    converter = HTMLToMarkdown(
        include_links=True,
        include_images=False,
        code_block_style="fenced",
        heading_style="atx",
        strip_tags=["nav", "footer"],
    )
    markdown = converter.convert(html_string)

    # From a URL (fetch + convert)
    markdown = await converter.convert_url("https://example.com")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.content.html_to_md")


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════


@dataclass
class MarkdownOptions:
    """
    Options for HTML to Markdown conversion.

    Attributes:
        include_links: Convert <a> tags to Markdown links.
        include_images: Convert <img> tags to Markdown images.
        code_block_style: Code block style ('fenced' or 'indented').
        heading_style: Heading style ('atx' for # or 'setext' for ===).
        bullet_marker: Unordered list marker ('-', '*', '+').
        ordered_marker: Ordered list marker style ('.' or ')').
        strip_tags: HTML tags to remove entirely.
        convert_tags: HTML tags to convert (empty = all).
        wrap_width: Line wrap width (0 = no wrapping).
        escape_snob: Escape special characters more aggressively.
        default_lang: Default language for code blocks without one.
        link_reference: Use reference-style links [text][id].
        remove_empty_lines: Collapse multiple empty lines.
        max_heading_level: Maximum heading level to convert (1-6).
    """

    include_links: bool = True
    include_images: bool = True
    code_block_style: str = "fenced"
    heading_style: str = "atx"
    bullet_marker: str = "-"
    ordered_marker: str = "."
    strip_tags: list[str] = field(
        default_factory=lambda: [
            "script",
            "style",
            "noscript",
            "iframe",
            "svg",
            "canvas",
            "button",
            "input",
            "select",
            "textarea",
            "form",
            "dialog",
            "template",
            "embed",
            "object",
        ]
    )
    convert_tags: list[str] = field(default_factory=list)
    wrap_width: int = 0
    escape_snob: bool = False
    default_lang: str = ""
    link_reference: bool = False
    remove_empty_lines: bool = True
    max_heading_level: int = 6

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_links": self.include_links,
            "include_images": self.include_images,
            "code_block_style": self.code_block_style,
            "heading_style": self.heading_style,
            "bullet_marker": self.bullet_marker,
            "ordered_marker": self.ordered_marker,
            "strip_tags": self.strip_tags,
            "wrap_width": self.wrap_width,
            "default_lang": self.default_lang,
            "link_reference": self.link_reference,
            "remove_empty_lines": self.remove_empty_lines,
            "max_heading_level": self.max_heading_level,
        }


# ══════════════════════════════════════════════════════════════
# Tag Mapping
# ══════════════════════════════════════════════════════════════

# Inline formatting tags
INLINE_TAGS: dict[str, tuple[str, str]] = {
    "strong": ("**", "**"),
    "b": ("**", "**"),
    "em": ("*", "*"),
    "i": ("*", "*"),
    "del": ("~~", "~~"),
    "s": ("~~", "~~"),
    "strike": ("~~", "~~"),
    "code": ("`", "`"),
    "kbd": ("`", "`"),
    "samp": ("`", "`"),
    "mark": ("**", "**"),
    "ins": ("", ""),
    "u": ("", ""),
    "small": ("", ""),
    "sub": ("", ""),
    "sup": ("", ""),
    "abbr": ("", ""),
    "cite": ("*", "*"),
    "q": ('"', '"'),
}

# Block-level tags that add newlines
BLOCK_TAGS: set[str] = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "aside",
    "header",
    "footer",
    "figure",
    "figcaption",
    "blockquote",
    "pre",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "br",
    "dl",
    "dt",
    "dd",
}

# Tags to skip entirely (no content extracted)
SKIP_TAGS: set[str] = {
    "script",
    "style",
    "noscript",
    "head",
    "meta",
    "link",
    "title",
    "iframe",
    "svg",
    "canvas",
    "template",
}

# Language detection from class names
LANG_PATTERNS: list[tuple[str, str]] = [
    (r"language-(\w+)", ""),
    (r"lang-(\w+)", ""),
    (r"highlight-(\w+)", ""),
    (r"sourceCode\s+(\w+)", ""),
    (r"brush:\s*(\w+)", ""),
]


# ══════════════════════════════════════════════════════════════
# HTML to Markdown Converter
# ══════════════════════════════════════════════════════════════


class HTMLToMarkdown:
    """
    Converts HTML to clean, LLM-optimized Markdown.

    Uses an lxml-based tree walker for precise control over
    the conversion process. Falls back to markdownify if
    lxml is not available.

    Args:
        options: Conversion options.

    Example:
        >>> converter = HTMLToMarkdown()
        >>> md = converter.convert("<h1>Hello</h1><p>World</p>")
        >>> print(md)
        # Hello

        World
    """

    def __init__(self, options: MarkdownOptions | None = None):
        self._options = options or MarkdownOptions()
        self._link_refs: list[tuple[str, str]] = []  # (text, url) for reference-style

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def convert(self, html: str) -> str:
        """
        Convert HTML string to Markdown.

        Args:
            html: Raw HTML string.

        Returns:
            Clean Markdown string.
        """
        if not html or not html.strip():
            return ""

        # Try lxml-based conversion first
        try:
            return self._convert_with_lxml(html)
        except ImportError:
            pass
        except Exception as e:
            logger.debug("lxml conversion failed, trying markdownify: %s", e)

        # Fallback to markdownify
        try:
            return self._convert_with_markdownify(html)
        except ImportError:
            pass
        except Exception as e:
            logger.debug("markdownify conversion failed: %s", e)

        # Last resort: html2text
        try:
            return self._convert_with_html2text(html)
        except ImportError as err:
            raise ImportError(
                "No HTML-to-Markdown library available. "
                "Install with: pip install lxml markdownify html2text"
            ) from err

    def convert_element(self, element: Any) -> str:
        """
        Convert an lxml element to Markdown.

        Args:
            element: lxml HtmlElement.

        Returns:
            Markdown string.
        """
        return self._walk_element(element)

    async def convert_url(
        self,
        url: str,
        timeout: int = 30,
    ) -> str:
        """
        Fetch a URL and convert its HTML to Markdown.

        Args:
            url: URL to fetch.
            timeout: Request timeout in seconds.

        Returns:
            Markdown string.
        """
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return self.convert(response.text)

    # ──────────────────────────────────────────────────────────
    # lxml-Based Conversion
    # ──────────────────────────────────────────────────────────

    def _convert_with_lxml(self, html: str) -> str:
        """Convert using lxml tree walker."""
        from lxml import html as lxml_html

        # Parse
        tree = lxml_html.document_fromstring(html)

        # Find body or use root
        body = tree.find(".//body")
        root = body if body is not None else tree

        # Remove strip tags
        self._remove_tags(root, self._options.strip_tags)

        # Walk the tree
        self._link_refs = []
        markdown = self._walk_element(root)

        # Add reference-style links if enabled
        if self._options.link_reference and self._link_refs:
            markdown += "\n\n"
            for i, (_text, url) in enumerate(self._link_refs, 1):
                markdown += f"[{i}]: {url}\n"

        # Clean up
        markdown = self._cleanup_markdown(markdown)

        return markdown

    def _walk_element(self, element: Any) -> str:
        """Recursively walk an lxml element and convert to Markdown."""
        tag = element.tag if isinstance(element.tag, str) else ""

        # Skip certain tags
        if tag in SKIP_TAGS:
            return ""

        # Handle text before children
        parts: list[str] = []

        # Element's own text
        if element.text:
            parts.append(self._escape_text(element.text))

        # Process children
        for child in element:
            child_md = self._convert_tag(child)
            if child_md:
                parts.append(child_md)

            # Tail text (text after the child element)
            if child.tail:
                parts.append(self._escape_text(child.tail))

        result = "".join(parts)

        # Wrap with block-level formatting
        result = self._apply_block_format(tag, element, result)

        return result

    def _convert_tag(self, element: Any) -> str:
        """Convert a single element based on its tag."""
        tag = element.tag if isinstance(element.tag, str) else ""

        if tag in SKIP_TAGS:
            return ""

        # Headings
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return self._convert_heading(element, tag)

        # Paragraphs
        if tag == "p":
            return self._convert_paragraph(element)

        # Line breaks
        if tag == "br":
            return "\n"

        # Horizontal rule
        if tag == "hr":
            return "\n\n---\n\n"

        # Links
        if tag == "a":
            return self._convert_link(element)

        # Images
        if tag == "img":
            return self._convert_image(element)

        # Lists
        if tag in ("ul", "ol"):
            return self._convert_list(element, tag)

        if tag == "li":
            return self._walk_element(element)

        # Code blocks
        if tag == "pre":
            return self._convert_pre(element)

        # Blockquotes
        if tag == "blockquote":
            return self._convert_blockquote(element)

        # Tables
        if tag == "table":
            return self._convert_table(element)

        # Inline formatting
        if tag in INLINE_TAGS:
            return self._convert_inline(element, tag)

        # Definition lists
        if tag == "dl":
            return self._convert_definition_list(element)

        # Figures
        if tag == "figure":
            return self._convert_figure(element)

        # Div, section, article — just walk children
        if tag in ("div", "section", "article", "main", "aside", "span", "body", "html"):
            return self._walk_element(element)

        # Unknown tag — just extract text
        return self._walk_element(element)

    # ──────────────────────────────────────────────────────────
    # Tag Converters
    # ──────────────────────────────────────────────────────────

    def _convert_heading(self, element: Any, tag: str) -> str:
        """Convert heading element."""
        level = int(tag[1])
        if level > self._options.max_heading_level:
            level = self._options.max_heading_level

        text = self._get_text_content(element).strip()
        if not text:
            return ""

        if self._options.heading_style == "setext" and level <= 2:
            underline = "=" if level == 1 else "-"
            return f"\n\n{text}\n{underline * len(text)}\n\n"
        else:
            prefix = "#" * level
            return f"\n\n{prefix} {text}\n\n"

    def _convert_paragraph(self, element: Any) -> str:
        """Convert paragraph element."""
        text = self._walk_element(element).strip()
        if not text:
            return ""
        return f"\n\n{text}\n\n"

    def _convert_link(self, element: Any) -> str:
        """Convert anchor element."""
        if not self._options.include_links:
            return self._get_text_content(element)

        href = element.get("href", "").strip()
        text = self._get_text_content(element).strip()

        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return text

        if not text:
            text = href

        if self._options.link_reference:
            self._link_refs.append((text, href))
            ref_num = len(self._link_refs)
            return f"[{text}][{ref_num}]"

        title = element.get("title", "")
        if title:
            return f'[{text}]({href} "{title}")'
        return f"[{text}]({href})"

    def _convert_image(self, element: Any) -> str:
        """Convert image element."""
        if not self._options.include_images:
            return ""

        src = element.get("src", "").strip()
        alt = element.get("alt", "").strip()
        title = element.get("title", "")

        if not src:
            return ""

        if title:
            return f'![{alt}]({src} "{title}")'
        return f"![{alt}]({src})"

    def _convert_list(self, element: Any, tag: str) -> str:
        """Convert ul/ol element."""
        items: list[str] = []
        counter = 1

        for child in element:
            child_tag = child.tag if isinstance(child.tag, str) else ""
            if child_tag != "li":
                continue

            item_text = self._walk_element(child).strip()
            if not item_text:
                continue

            # Handle nested lists
            indent = ""
            parent = element.getparent()
            depth = 0
            while parent is not None:
                parent_tag = parent.tag if isinstance(parent.tag, str) else ""
                if parent_tag in ("ul", "ol"):
                    depth += 1
                parent = parent.getparent()
            indent = "  " * depth

            if tag == "ol":
                marker = f"{counter}{self._options.ordered_marker}"
                counter += 1
            else:
                marker = self._options.bullet_marker

            # Handle multi-line list items
            item_lines = item_text.split("\n")
            first_line = f"{indent}{marker} {item_lines[0]}"
            rest_lines = [
                f"{indent}{' ' * (len(marker) + 1)}{line}"
                for line in item_lines[1:]
                if line.strip()
            ]

            items.append("\n".join([first_line, *rest_lines]))

        if not items:
            return ""

        return "\n\n" + "\n".join(items) + "\n\n"

    def _convert_pre(self, element: Any) -> str:
        """Convert pre/code block element."""
        # Detect language from class
        lang = self._detect_language(element)

        # Get code content
        code_el = element.find(".//code")
        if code_el is not None:
            code_text = code_el.text_content()
            if not lang:
                lang = self._detect_language(code_el)
        else:
            code_text = element.text_content()

        code_text = code_text.rstrip()

        if self._options.code_block_style == "fenced":
            return f"\n\n```{lang}\n{code_text}\n```\n\n"
        else:
            # Indented style
            indented = "\n".join(f"    {line}" for line in code_text.split("\n"))
            return f"\n\n{indented}\n\n"

    def _convert_blockquote(self, element: Any) -> str:
        """Convert blockquote element."""
        content = self._walk_element(element).strip()
        if not content:
            return ""

        # Add > prefix to each line
        lines = content.split("\n")
        quoted = "\n".join(f"> {line}" for line in lines)
        return f"\n\n{quoted}\n\n"

    def _convert_table(self, element: Any) -> str:
        """Convert table element to GFM Markdown table."""
        rows: list[list[str]] = []
        alignments: list[str] = []

        # Process all rows
        for tr in element.iter("tr"):
            cells: list[str] = []
            for cell in tr:
                cell_tag = cell.tag if isinstance(cell.tag, str) else ""
                if cell_tag in ("td", "th"):
                    cell_text = self._get_text_content(cell).strip()
                    cell_text = cell_text.replace("|", "\\|").replace("\n", " ")
                    cells.append(cell_text)

                    # Detect alignment from th
                    if cell_tag == "th" and not alignments:
                        align = cell.get("style", "")
                        if "text-align: center" in align or "text-align:center" in align:
                            alignments.append("center")
                        elif "text-align: right" in align or "text-align:right" in align:
                            alignments.append("right")
                        else:
                            alignments.append("left")

            if cells:
                rows.append(cells)

        if not rows:
            return ""

        # Normalize column count
        max_cols = max(len(row) for row in rows)
        for row in rows:
            while len(row) < max_cols:
                row.append("")

        # Build table
        lines: list[str] = []

        # Header row
        header = rows[0]
        lines.append("| " + " | ".join(header) + " |")

        # Separator row
        seps: list[str] = []
        for i in range(max_cols):
            if i < len(alignments):
                if alignments[i] == "center":
                    seps.append(":---:")
                elif alignments[i] == "right":
                    seps.append("---:")
                else:
                    seps.append(":---")
            else:
                seps.append("---")
        lines.append("| " + " | ".join(seps) + " |")

        # Data rows
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n\n" + "\n".join(lines) + "\n\n"

    def _convert_inline(self, element: Any, tag: str) -> str:
        """Convert inline formatting element."""
        prefix, suffix = INLINE_TAGS.get(tag, ("", ""))
        content = self._walk_element(element)

        if not content.strip():
            return ""

        return f"{prefix}{content}{suffix}"

    def _convert_definition_list(self, element: Any) -> str:
        """Convert dl/dt/dd elements."""
        parts: list[str] = []
        for child in element:
            child_tag = child.tag if isinstance(child.tag, str) else ""
            if child_tag == "dt":
                text = self._get_text_content(child).strip()
                if text:
                    parts.append(f"\n\n**{text}**\n")
            elif child_tag == "dd":
                text = self._walk_element(child).strip()
                if text:
                    parts.append(f": {text}\n")
        return "".join(parts)

    def _convert_figure(self, element: Any) -> str:
        """Convert figure element."""
        parts: list[str] = []

        # Image
        img = element.find(".//img")
        if img is not None:
            parts.append(self._convert_image(img))

        # Caption
        caption = element.find(".//figcaption")
        if caption is not None:
            cap_text = self._get_text_content(caption).strip()
            if cap_text:
                parts.append(f"\n*{cap_text}*")

        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _apply_block_format(self, tag: str, element: Any, content: str) -> str:
        """Apply block-level formatting based on tag."""
        # Most block formatting is handled in specific converters
        return content

    def _get_text_content(self, element: Any) -> str:
        """Get all text content from an element (recursive)."""
        return str(element.text_content())

    def _escape_text(self, text: str) -> str:
        """Escape Markdown special characters in text."""
        if not text:
            return ""

        if self._options.escape_snob:
            # Aggressive escaping
            special = r"\`*_{}[]()#+-.!|~>"
            result = []
            for char in text:
                if char in special:
                    result.append(f"\\{char}")
                else:
                    result.append(char)
            return "".join(result)

        # Light escaping — only escape characters that would
        # create unintended formatting
        text = re.sub(r"(?<!\\)\*(?=\S)", "\\*", text)  # * at word start
        text = re.sub(r"(?<=\S)(?<!\\)\*", "\\*", text)  # * at word end

        return text

    def _detect_language(self, element: Any) -> str:
        """Detect programming language from element class."""
        class_attr = element.get("class", "")
        if not class_attr:
            return self._options.default_lang

        for pattern, _ in LANG_PATTERNS:
            match = re.search(pattern, class_attr, re.IGNORECASE)
            if match:
                return match.group(1).lower()

        return self._options.default_lang

    def _remove_tags(self, element: Any, tags: list[str]) -> None:
        """Remove specified tags from the element tree."""
        for tag in tags:
            for el in element.iter(tag):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)

    def _cleanup_markdown(self, text: str) -> str:
        """Clean up the final Markdown output."""
        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove excessive blank lines
        if self._options.remove_empty_lines:
            text = re.sub(r"\n{3,}", "\n\n", text)

        # Remove trailing whitespace per line
        lines = [line.rstrip() for line in text.split("\n")]
        text = "\n".join(lines)

        # Remove leading/trailing whitespace
        text = text.strip()

        # Wrap lines if configured
        if self._options.wrap_width > 0:
            text = self._wrap_lines(text, self._options.wrap_width)

        return text

    @staticmethod
    def _wrap_lines(text: str, width: int) -> str:
        """Wrap text lines to a maximum width (preserving code blocks)."""
        lines = text.split("\n")
        result: list[str] = []
        in_code = False

        for line in lines:
            if line.strip().startswith("```"):
                in_code = not in_code
                result.append(line)
                continue

            if in_code or line.startswith("|") or line.startswith(">"):
                result.append(line)
                continue

            if len(line) <= width:
                result.append(line)
                continue

            # Simple word wrap
            words = line.split()
            current_line = ""
            for word in words:
                if current_line and len(current_line) + len(word) + 1 > width:
                    result.append(current_line)
                    current_line = word
                else:
                    current_line = f"{current_line} {word}".strip()
            if current_line:
                result.append(current_line)

        return "\n".join(result)

    # ──────────────────────────────────────────────────────────
    # Fallback Converters
    # ──────────────────────────────────────────────────────────

    def _convert_with_markdownify(self, html: str) -> str:
        """Convert using the markdownify library."""
        import markdownify

        kwargs: dict[str, Any] = {
            "heading_style": "ATX",
            "bullets": self._options.bullet_marker,
            "code_language": self._options.default_lang,
            "strip": self._options.strip_tags,
            "convert": self._options.convert_tags or None,
        }

        if not self._options.include_images:
            kwargs["convert"] = [t for t in (kwargs.get("convert") or []) if t != "img"]

        result = markdownify.markdownify(html, **kwargs)
        return self._cleanup_markdown(result)

    def _convert_with_html2text(self, html: str) -> str:
        """Convert using the html2text library."""
        import html2text

        h = html2text.HTML2Text()
        h.body_width = self._options.wrap_width
        h.ignore_links = not self._options.include_links
        h.ignore_images = not self._options.include_images
        h.ignore_emphasis = False
        h.mark_code = True
        h.skip_internal_links = False
        h.inline_links = not self._options.link_reference
        h.protect_links = True
        h.unicode_snob = True
        h.wrap_links = False
        h.pad_tables = True

        result = h.handle(html)
        return self._cleanup_markdown(result)

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    @property
    def options(self) -> MarkdownOptions:
        """Current conversion options."""
        return self._options

    def to_dict(self) -> dict[str, Any]:
        return self._options.to_dict()

    def __repr__(self) -> str:
        return (
            f"HTMLToMarkdown(links={self._options.include_links}, "
            f"images={self._options.include_images}, "
            f"code={self._options.code_block_style})"
        )


# ══════════════════════════════════════════════════════════════
# Convenience Functions
# ══════════════════════════════════════════════════════════════


def html_to_markdown(
    html: str,
    include_links: bool = True,
    include_images: bool = True,
    **kwargs: Any,
) -> str:
    """
    Convert HTML to Markdown (convenience function).

    Args:
        html: Raw HTML string.
        include_links: Include links in output.
        include_images: Include images in output.
        **kwargs: Additional MarkdownOptions fields.

    Returns:
        Markdown string.

    Example:
        >>> md = html_to_markdown("<h1>Hello</h1><p>World</p>")
        >>> print(md)
        # Hello

        World
    """
    options = MarkdownOptions(
        include_links=include_links,
        include_images=include_images,
        **kwargs,
    )
    converter = HTMLToMarkdown(options)
    return converter.convert(html)


def clean_markdown(text: str) -> str:
    """
    Clean and normalize Markdown text.

    Removes excessive whitespace, normalizes line endings,
    and fixes common formatting issues.

    Args:
        text: Raw Markdown text.

    Returns:
        Cleaned Markdown text.
    """
    if not text:
        return ""

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove trailing whitespace
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Remove zero-width characters
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)

    # Normalize spaces
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()
