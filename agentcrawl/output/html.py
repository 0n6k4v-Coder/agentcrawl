"""
AgentCrawl — HTML Output Formatter
======================================

Formats crawl results as clean HTML output with optional
sanitization, metadata injection, and template rendering.

Features:
    - Clean HTML extraction from crawl results
    - HTML sanitization (remove scripts, event handlers)
    - Metadata injection (title, description, og:tags)
    - Template-based HTML rendering
    - HTML to PDF conversion (via weasyprint, optional)
    - Readable HTML output for LLM consumption

Usage:
    from agentcrawl.output.html import HtmlOutputFormatter

    formatter = HtmlOutputFormatter()
    html = formatter.format(result)
    print(html)

    # With sanitization
    formatter = HtmlOutputFormatter(sanitize=True)
    html = formatter.format(result)

    # With template
    formatter = HtmlOutputFormatter(
        template="<html><body>{{content}}</body></html>",
    )
    html = formatter.format(result)

    # To PDF
    pdf_bytes = await formatter.to_pdf(result)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("agentcrawl.output.html")


# ══════════════════════════════════════════════════════════════
# HTML Sanitizer
# ══════════════════════════════════════════════════════════════

class HtmlSanitizer:
    """
    Sanitizes HTML by removing potentially dangerous elements
    and attributes.

    Removes:
        - <script> tags and inline JavaScript
        - Event handler attributes (onclick, onload, etc.)
        - javascript: URLs
        - <iframe>, <embed>, <object> tags
        - data: URLs (except images)
        - CSS expressions

    Args:
        allow_images: Whether to allow <img> tags.
        allow_links: Whether to allow <a> tags.
        allow_styles: Whether to allow style attributes.
        allowed_tags: Additional tags to allow.
        allowed_attributes: Additional attributes to allow.

    Example:
        >>> sanitizer = HtmlSanitizer()
        >>> clean = sanitizer.sanitize(dirty_html)
    """

    # Tags to always remove
    REMOVE_TAGS: set[str] = {
        "script", "noscript", "iframe", "embed", "object",
        "applet", "form", "input", "button", "select",
        "textarea", "link", "meta", "base",
    }

    # Event handler attributes to remove
    EVENT_ATTRS: set[str] = {
        "onclick", "ondblclick", "onmousedown", "onmouseup",
        "onmouseover", "onmousemove", "onmouseout", "onmouseenter",
        "onmouseleave", "onkeydown", "onkeypress", "onkeyup",
        "onfocus", "onblur", "onchange", "oninput", "onsubmit",
        "onreset", "onselect", "onload", "onunload", "onerror",
        "onresize", "onscroll", "onabort", "oncanplay",
        "ondrag", "ondragend", "ondragenter", "ondragleave",
        "ondragover", "ondragstart", "ondrop", "oncontextmenu",
        "onwheel", "ontouchstart", "ontouchmove", "ontouchend",
        "onanimationstart", "onanimationend", "ontransitionend",
    }

    # Safe attributes
    SAFE_ATTRS: set[str] = {
        "href", "src", "alt", "title", "class", "id", "name",
        "width", "height", "colspan", "rowspan", "align",
        "valign", "border", "cellpadding", "cellspacing",
        "target", "rel", "type", "value", "placeholder",
        "datetime", "cite", "lang", "dir", "role",
        "aria-label", "aria-hidden", "aria-describedby",
    }

    def __init__(
        self,
        allow_images: bool = True,
        allow_links: bool = True,
        allow_styles: bool = False,
        allowed_tags: set[str] | None = None,
        allowed_attributes: set[str] | None = None,
    ):
        self._allow_images = allow_images
        self._allow_links = allow_links
        self._allow_styles = allow_styles
        self._allowed_tags = allowed_tags or set()
        self._allowed_attributes = allowed_attributes or set()

    def sanitize(self, html: str) -> str:
        """
        Sanitize HTML content.

        Args:
            html: Raw HTML string.

        Returns:
            Sanitized HTML string.
        """
        if not html:
            return ""

        text = html

        # Remove script tags and content
        text = re.sub(
            r"<script\b[^>]*>.*?</script>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Remove style tags and content
        text = re.sub(
            r"<style\b[^>]*>.*?</style>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Remove other dangerous tags
        for tag in self.REMOVE_TAGS:
            if tag == "script":
                continue  # Already handled
            # Remove opening and closing tags
            text = re.sub(
                rf"</?{tag}\b[^>]*>",
                "",
                text,
                flags=re.IGNORECASE,
            )

        # Remove img tags if not allowed
        if not self._allow_images:
            text = re.sub(r"<img\b[^>]*>", "", text, flags=re.IGNORECASE)

        # Remove event handler attributes
        for attr in self.EVENT_ATTRS:
            text = re.sub(
                rf'\s+{attr}\s*=\s*["\'][^"\']*["\']',
                "",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(
                rf"\s+{attr}\s*=\s*\S+",
                "",
                text,
                flags=re.IGNORECASE,
            )

        # Remove javascript: URLs
        text = re.sub(
            r'(href|src|action)\s*=\s*["\']?\s*javascript:[^"\'>\s]*',
            r'\1=""',
            text,
            flags=re.IGNORECASE,
        )

        # Remove data: URLs (except images)
        text = re.sub(
            r'(href|action)\s*=\s*["\']?\s*data:[^"\'>\s]*',
            r'\1=""',
            text,
            flags=re.IGNORECASE,
        )

        # Remove CSS expressions
        text = re.sub(
            r"expression\s*\(",
            "removed(",
            text,
            flags=re.IGNORECASE,
        )

        # Remove style attributes if not allowed
        if not self._allow_styles:
            text = re.sub(
                r'\s+style\s*=\s*["\'][^"\']*["\']',
                "",
                text,
                flags=re.IGNORECASE,
            )

        return text

    def __repr__(self) -> str:
        return (
            f"HtmlSanitizer(images={self._allow_images}, "
            f"links={self._allow_links}, "
            f"styles={self._allow_styles})"
        )


# ══════════════════════════════════════════════════════════════
# HTML Output Formatter
# ══════════════════════════════════════════════════════════════

class HtmlOutputFormatter:
    """
    Formats crawl results as clean HTML output.

    Args:
        sanitize: Whether to sanitize the HTML output.
        include_metadata: Inject metadata as HTML meta tags.
        include_styles: Include basic CSS styles.
        template: Custom HTML template (use {{content}}, {{title}}, etc.).
        wrap_in_document: Wrap output in a full HTML document.
        sanitizer: Custom HtmlSanitizer instance.

    Example:
        >>> formatter = HtmlOutputFormatter(sanitize=True)
        >>> html = formatter.format(crawl_result)
        >>> print(html)
    """

    DEFAULT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{title}}</title>
    {{metadata}}
    {{styles}}
</head>
<body>
    <article>
        {{content}}
    </article>
</body>
</html>"""

    DEFAULT_STYLES = """\
<style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        line-height: 1.6;
        max-width: 800px;
        margin: 0 auto;
        padding: 2rem;
        color: #333;
    }
    h1, h2, h3, h4, h5, h6 { margin-top: 1.5em; margin-bottom: 0.5em; }
    a { color: #0066cc; }
    img { max-width: 100%; height: auto; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background-color: #f5f5f5; }
    code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }
    pre { background: #f4f4f4; padding: 1em; overflow-x: auto; border-radius: 5px; }
    blockquote { border-left: 4px solid #ddd; margin: 1em 0; padding-left: 1em; color: #666; }
</style>"""

    def __init__(
        self,
        sanitize: bool = True,
        include_metadata: bool = True,
        include_styles: bool = False,
        template: str | None = None,
        wrap_in_document: bool = True,
        sanitizer: HtmlSanitizer | None = None,
    ):
        self._sanitize = sanitize
        self._include_metadata = include_metadata
        self._include_styles = include_styles
        self._template = template or self.DEFAULT_TEMPLATE
        self._wrap_in_document = wrap_in_document
        self._sanitizer = sanitizer or HtmlSanitizer()

    # ──────────────────────────────────────────────────────────
    # Formatting
    # ──────────────────────────────────────────────────────────

    def format(self, result: Any) -> str:
        """
        Format a CrawlResult as HTML.

        Args:
            result: CrawlResult instance.

        Returns:
            Formatted HTML string.
        """
        # Get HTML content
        html = self._get_html_content(result)

        # Sanitize
        if self._sanitize:
            html = self._sanitizer.sanitize(html)

        # Wrap in document
        if self._wrap_in_document:
            html = self._render_template(result, html)

        return html

    def format_raw(self, result: Any) -> str:
        """
        Format without wrapping in a document template.

        Args:
            result: CrawlResult instance.

        Returns:
            Raw HTML content.
        """
        html = self._get_html_content(result)

        if self._sanitize:
            html = self._sanitizer.sanitize(html)

        return html

    def _get_html_content(self, result: Any) -> str:
        """Extract HTML content from a CrawlResult."""
        # Try html field first
        html = getattr(result, "html", "")
        if html:
            return html

        # Try raw_html
        raw_html = getattr(result, "raw_html", "")
        if raw_html:
            return raw_html

        # Convert markdown to HTML as fallback
        markdown = getattr(result, "markdown", "")
        if markdown:
            return self._markdown_to_html(markdown)

        # Try text
        text = getattr(result, "text", "")
        if text:
            return f"<p>{self._escape_html(text)}</p>"

        return ""

    def _render_template(self, result: Any, content: str) -> str:
        """Render the HTML template with content and metadata."""
        # Extract metadata
        metadata = getattr(result, "metadata", {}) or {}
        title = metadata.get("title", "")
        if not title:
            title = getattr(result, "url", "Untitled")

        # Build metadata tags
        meta_tags = ""
        if self._include_metadata and metadata:
            meta_tags = self._build_meta_tags(metadata)

        # Build styles
        styles = self.DEFAULT_STYLES if self._include_styles else ""

        # Render template
        html = self._template
        html = html.replace("{{title}}", self._escape_html(title))
        html = html.replace("{{content}}", content)
        html = html.replace("{{metadata}}", meta_tags)
        html = html.replace("{{styles}}", styles)
        html = html.replace("{{url}}", self._escape_html(getattr(result, "url", "")))

        return html

    def _build_meta_tags(self, metadata: dict[str, Any]) -> str:
        """Build HTML meta tags from metadata dictionary."""
        tags: list[str] = []

        if metadata.get("description"):
            tags.append(
                f'<meta name="description" content="{self._escape_attr(metadata["description"])}">'
            )

        if metadata.get("author"):
            tags.append(
                f'<meta name="author" content="{self._escape_attr(metadata["author"])}">'
            )

        if metadata.get("keywords"):
            tags.append(
                f'<meta name="keywords" content="{self._escape_attr(metadata["keywords"])}">'
            )

        # Open Graph tags
        og_map = {
            "og_title": "og:title",
            "og_description": "og:description",
            "og_image": "og:image",
            "og_url": "og:url",
            "og_type": "og:type",
            "og_site_name": "og:site_name",
        }

        for key, og_name in og_map.items():
            value = metadata.get(key, "")
            if value:
                tags.append(
                    f'<meta property="{og_name}" content="{self._escape_attr(value)}">'
                )

        return "\n    ".join(tags)

    # ──────────────────────────────────────────────────────────
    # Conversion
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _markdown_to_html(markdown: str) -> str:
        """Convert markdown to HTML."""
        try:
            import markdown
            return markdown.markdown(
                markdown,
                extensions=["tables", "fenced_code", "codehilite"],
            )
        except ImportError:
            # Fallback: basic conversion
            html = markdown
            # Headers
            for i in range(6, 0, -1):
                html = re.sub(
                    rf"^{'#' * i}\s+(.+)$",
                    rf"<h{i}>\1</h{i}>",
                    html,
                    flags=re.MULTILINE,
                )
            # Bold
            html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
            # Italic
            html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
            # Links
            html = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', html)
            # Paragraphs
            html = re.sub(r"\n{2,}", "</p><p>", html)
            html = f"<p>{html}</p>"
            return html

    async def to_pdf(
        self,
        result: Any,
        output_path: str | None = None,
    ) -> bytes:
        """
        Convert a CrawlResult to PDF.

        Requires weasyprint to be installed.

        Args:
            result: CrawlResult instance.
            output_path: Optional file path to save the PDF.

        Returns:
            PDF bytes.

        Raises:
            ImportError: If weasyprint is not installed.
        """
        try:
            from weasyprint import HTML as WeasyprintHTML
        except ImportError:
            raise ImportError(
                "weasyprint is required for PDF conversion. "
                "Install with: pip install weasyprint"
            )

        html = self.format(result)
        pdf_bytes = WeasyprintHTML(string=html).write_pdf()

        if output_path:
            with open(output_path, "wb") as f:
                f.write(pdf_bytes)

        return pdf_bytes

    # ──────────────────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @staticmethod
    def _escape_attr(text: str) -> str:
        """Escape HTML attribute value."""
        return (
            text.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "sanitize": self._sanitize,
            "include_metadata": self._include_metadata,
            "include_styles": self._include_styles,
            "wrap_in_document": self._wrap_in_document,
        }

    def __repr__(self) -> str:
        return (
            f"HtmlOutputFormatter(sanitize={self._sanitize}, "
            f"metadata={self._include_metadata}, "
            f"styles={self._include_styles})"
        )