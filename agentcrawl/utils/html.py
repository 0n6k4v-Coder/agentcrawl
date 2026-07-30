"""
AgentCrawl — HTML Utilities
===============================

Utility functions for HTML processing: cleaning, tag stripping,
text extraction, entity decoding, and encoding detection.

These are lightweight, standalone functions that don't require
lxml or external parsers. For full HTML parsing, use
agentcrawl.content.html_parser.HTMLParser.

Usage:
    from agentcrawl.utils.html import (
        strip_tags,
        extract_text,
        clean_html,
        decode_entities,
        normalize_whitespace,
        extract_links,
        extract_meta_tags,
        detect_encoding,
        is_html,
    )

    # Strip all HTML tags
    text = strip_tags("<p>Hello <b>world</b></p>")
    # → "Hello world"

    # Clean HTML (remove scripts, styles, comments)
    clean = clean_html(dirty_html)

    # Extract links
    links = extract_links(html)
    # → [{"url": "https://...", "text": "..."}]

    # Detect encoding
    encoding = detect_encoding(raw_bytes)
"""

from __future__ import annotations

import html as html_module
import logging
import re

logger = logging.getLogger("agentcrawl.utils.html")


# ══════════════════════════════════════════════════════════════
# Tag Stripping
# ══════════════════════════════════════════════════════════════


def strip_tags(html: str, keep_tags: list[str] | None = None) -> str:
    """
    Remove HTML tags from a string.

    Args:
        html: HTML string.
        keep_tags: Tags to preserve (e.g., ['p', 'br', 'a']).

    Returns:
        Text with tags removed.

    Example:
        >>> strip_tags("<p>Hello <b>world</b></p>")
        'Hello world'
        >>> strip_tags("<p>Hello</p>", keep_tags=["p"])
        '<p>Hello</p>'
    """
    if not html:
        return ""

    if keep_tags:
        # Remove all tags except kept ones
        keep_set = {t.lower() for t in keep_tags}

        def _replace_tag(match: re.Match[str]) -> str:
            tag_match = re.match(r"</?(\w+)", match.group(0))
            if tag_match:
                tag_name = tag_match.group(1).lower()
                if tag_name in keep_set:
                    return str(match.group(0))
            return ""

        return re.sub(r"<[^>]+>", _replace_tag, html)

    # Remove all tags
    return re.sub(r"<[^>]+>", "", html)


def strip_specific_tags(html: str, tags: list[str]) -> str:
    """
    Remove specific HTML tags (and their content for block tags).

    Args:
        html: HTML string.
        tags: Tag names to remove (e.g., ['script', 'style']).

    Returns:
        HTML with specified tags removed.

    Example:
        >>> strip_specific_tags(
        ...     "<p>Hello</p><script>alert('x')</script>",
        ...     ["script"],
        ... )
        '<p>Hello</p>'
    """
    if not html:
        return ""

    result = html
    for tag in tags:
        # Remove tag with content
        result = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>",
            "",
            result,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Remove self-closing tags
        result = re.sub(
            rf"<{tag}\b[^>]*/?>",
            "",
            result,
            flags=re.IGNORECASE,
        )

    return result


# ══════════════════════════════════════════════════════════════
# Text Extraction
# ══════════════════════════════════════════════════════════════


def extract_text(html: str, normalize: bool = True) -> str:
    """
    Extract visible text content from HTML.

    Removes scripts, styles, comments, and tags. Decodes
    HTML entities and normalizes whitespace.

    Args:
        html: HTML string.
        normalize: Whether to normalize whitespace.

    Returns:
        Extracted text content.

    Example:
        >>> extract_text("<p>Hello &amp; welcome</p>")
        'Hello & welcome'
    """
    if not html:
        return ""

    text = html

    # Remove comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    # Remove script and style content
    text = strip_specific_tags(text, ["script", "style", "noscript"])

    # Replace block-level tags with newlines
    block_tags = (
        "p",
        "div",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "table",
        "section",
        "article",
        "header",
        "footer",
        "blockquote",
        "pre",
        "ul",
        "ol",
    )
    for tag in block_tags:
        text = re.sub(rf"<{tag}\b[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(rf"</{tag}>", "\n", text, flags=re.IGNORECASE)

    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode entities
    text = decode_entities(text)

    # Normalize whitespace
    if normalize:
        text = normalize_whitespace(text)

    return text.strip()


def extract_title(html: str) -> str:
    """
    Extract the <title> content from HTML.

    Args:
        html: HTML string.

    Returns:
        Title text, or empty string.

    Example:
        >>> extract_title("<html><head><title>My Page</title></head></html>")
        'My Page'
    """
    match = re.search(
        r"<title[^>]*>(.*?)</title>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return decode_entities(match.group(1)).strip()
    return ""


# ══════════════════════════════════════════════════════════════
# HTML Cleaning
# ══════════════════════════════════════════════════════════════


def clean_html(
    html: str,
    remove_scripts: bool = True,
    remove_styles: bool = True,
    remove_comments: bool = True,
    remove_empty_tags: bool = True,
) -> str:
    """
    Clean HTML by removing unwanted elements.

    Args:
        html: HTML string.
        remove_scripts: Remove <script> tags.
        remove_styles: Remove <style> tags.
        remove_comments: Remove HTML comments.
        remove_empty_tags: Remove empty tags.

    Returns:
        Cleaned HTML string.

    Example:
        >>> clean_html("<p>Hello</p><!-- comment --><script>bad()</script>")
        '<p>Hello</p>'
    """
    if not html:
        return ""

    result = html

    if remove_comments:
        result = re.sub(r"<!--.*?-->", "", result, flags=re.DOTALL)

    if remove_scripts:
        result = strip_specific_tags(result, ["script", "noscript"])

    if remove_styles:
        result = strip_specific_tags(result, ["style"])

    if remove_empty_tags:
        # Remove empty tags like <p></p>, <div></div>, <span></span>
        result = re.sub(r"<(\w+)\b[^>]*>\s*</\1>", "", result)

    return result.strip()


def sanitize_html(html: str) -> str:
    """
    Sanitize HTML by removing potentially dangerous elements.

    Removes scripts, event handlers, javascript: URLs, and
    other XSS vectors.

    Args:
        html: HTML string.

    Returns:
        Sanitized HTML string.
    """
    if not html:
        return ""

    result = html

    # Remove scripts
    result = strip_specific_tags(result, ["script", "noscript", "iframe", "embed", "object"])

    # Remove event handlers
    result = re.sub(
        r'\s+on\w+\s*=\s*["\'][^"\']*["\']',
        "",
        result,
        flags=re.IGNORECASE,
    )

    # Remove javascript: URLs
    result = re.sub(
        r'(href|src|action)\s*=\s*["\']?\s*javascript:[^"\'>\s]*',
        r'\1=""',
        result,
        flags=re.IGNORECASE,
    )

    # Remove data: URLs (except images)
    result = re.sub(
        r'(href|action)\s*=\s*["\']?\s*data:(?!image/)[^"\'>\s]*',
        r'\1=""',
        result,
        flags=re.IGNORECASE,
    )

    return result


# ══════════════════════════════════════════════════════════════
# Entity Handling
# ══════════════════════════════════════════════════════════════


def decode_entities(text: str) -> str:
    """
    Decode HTML entities in text.

    Handles named entities (&amp;, &lt;, etc.), decimal (&#123;),
    and hexadecimal (&#x1F600;) references.

    Args:
        text: Text with HTML entities.

    Returns:
        Decoded text.

    Example:
        >>> decode_entities("Hello &amp; welcome &lt;user&gt;")
        'Hello & welcome <user>'
        >>> decode_entities("&#72;&#101;&#108;&#108;&#111;")
        'Hello'
    """
    if not text:
        return ""

    # Use Python's html module for standard entities
    result = html_module.unescape(text)

    return result


def encode_entities(text: str, quote: bool = True) -> str:
    """
    Encode special characters as HTML entities.

    Args:
        text: Plain text.
        quote: Whether to encode quote characters.

    Returns:
        HTML-escaped text.

    Example:
        >>> encode_entities("Hello & <world>")
        'Hello &amp; &lt;world&gt;'
    """
    return html_module.escape(text, quote=quote)


# ══════════════════════════════════════════════════════════════
# Whitespace
# ══════════════════════════════════════════════════════════════


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.

    Collapses multiple spaces/tabs to single space, and
    multiple newlines to double newline.

    Args:
        text: Input text.

    Returns:
        Normalized text.

    Example:
        >>> normalize_whitespace("Hello   world\\n\\n\\n\\nNew para")
        'Hello world\\n\\nNew para'
    """
    if not text:
        return ""

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse horizontal whitespace
    text = re.sub(r"[ \t]+", " ", text)

    # Collapse vertical whitespace (3+ newlines → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def collapse_spaces(text: str) -> str:
    """Collapse multiple spaces to single space."""
    return re.sub(r" {2,}", " ", text)


# ══════════════════════════════════════════════════════════════
# Link Extraction
# ══════════════════════════════════════════════════════════════


def extract_links(html: str, base_url: str = "") -> list[dict[str, str]]:
    """
    Extract all links from HTML.

    Args:
        html: HTML string.
        base_url: Base URL for resolving relative links.

    Returns:
        List of link dicts with 'url', 'text', 'title' keys.

    Example:
        >>> links = extract_links('<a href="/page">Click</a>', "https://example.com")
        >>> print(links)
        [{'url': 'https://example.com/page', 'text': 'Click', 'title': ''}]
    """
    if not html:
        return []

    links: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # Match anchor tags
    pattern = re.compile(
        r"<a\b([^>]*)>(.*?)</a>",
        re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(html):
        attrs_str = match.group(1)
        inner_html = match.group(2)

        # Extract href
        href_match = re.search(
            r'href\s*=\s*["\']([^"\']*)["\']',
            attrs_str,
            re.IGNORECASE,
        )
        if not href_match:
            continue

        href = href_match.group(1).strip()

        # Skip non-HTTP links
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        # Resolve relative URL
        if base_url and not href.startswith(("http://", "https://")):
            from urllib.parse import urljoin

            href = urljoin(base_url, href)

        # Deduplicate
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Extract text
        text = strip_tags(inner_html).strip()

        # Extract title
        title_match = re.search(
            r'title\s*=\s*["\']([^"\']*)["\']',
            attrs_str,
            re.IGNORECASE,
        )
        title = title_match.group(1) if title_match else ""

        links.append(
            {
                "url": href,
                "text": text,
                "title": title,
            }
        )

    return links


def extract_images(html: str, base_url: str = "") -> list[dict[str, str]]:
    """
    Extract all images from HTML.

    Args:
        html: HTML string.
        base_url: Base URL for resolving relative src.

    Returns:
        List of image dicts with 'src', 'alt', 'title' keys.
    """
    if not html:
        return []

    images: list[dict[str, str]] = []

    pattern = re.compile(r"<img\b([^>]*)/?>", re.IGNORECASE)

    for match in pattern.finditer(html):
        attrs_str = match.group(1)

        # Extract src
        src_match = re.search(
            r'src\s*=\s*["\']([^"\']*)["\']',
            attrs_str,
            re.IGNORECASE,
        )
        if not src_match:
            continue

        src = src_match.group(1).strip()

        # Resolve relative URL
        if base_url and not src.startswith(("http://", "https://", "data:")):
            from urllib.parse import urljoin

            src = urljoin(base_url, src)

        # Extract alt
        alt_match = re.search(
            r'alt\s*=\s*["\']([^"\']*)["\']',
            attrs_str,
            re.IGNORECASE,
        )
        alt = alt_match.group(1) if alt_match else ""

        # Extract title
        title_match = re.search(
            r'title\s*=\s*["\']([^"\']*)["\']',
            attrs_str,
            re.IGNORECASE,
        )
        title = title_match.group(1) if title_match else ""

        images.append(
            {
                "src": src,
                "alt": alt,
                "title": title,
            }
        )

    return images


# ══════════════════════════════════════════════════════════════
# Meta Tags
# ══════════════════════════════════════════════════════════════


def extract_meta_tags(html: str) -> dict[str, str]:
    """
    Extract all meta tags from HTML.

    Args:
        html: HTML string.

    Returns:
        Dictionary of meta tag name/property → content.

    Example:
        >>> meta = extract_meta_tags(
        ...     '<meta name="description" content="A page">'
        ... )
        >>> print(meta)
        {'description': 'A page'}
    """
    if not html:
        return {}

    meta: dict[str, str] = {}

    pattern = re.compile(r"<meta\b([^>]*)/?>", re.IGNORECASE)

    for match in pattern.finditer(html):
        attrs_str = match.group(1)

        # Get name or property
        name_match = re.search(
            r'(?:name|property)\s*=\s*["\']([^"\']*)["\']',
            attrs_str,
            re.IGNORECASE,
        )
        if not name_match:
            continue

        name = name_match.group(1).strip().lower()

        # Get content
        content_match = re.search(
            r'content\s*=\s*["\']([^"\']*)["\']',
            attrs_str,
            re.IGNORECASE,
        )
        content = content_match.group(1).strip() if content_match else ""

        if name and content:
            meta[name] = content

    return meta


def extract_canonical_url(html: str) -> str:
    """
    Extract the canonical URL from HTML.

    Args:
        html: HTML string.

    Returns:
        Canonical URL, or empty string.
    """
    match = re.search(
        r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if not match:
        # Try reversed attribute order
        match = re.search(
            r'<link[^>]*href=["\']([^"\']*)["\'][^>]*rel=["\']canonical["\']',
            html,
            re.IGNORECASE,
        )

    return match.group(1).strip() if match else ""


# ══════════════════════════════════════════════════════════════
# Encoding Detection
# ══════════════════════════════════════════════════════════════


def detect_encoding(raw_bytes: bytes) -> str:
    """
    Detect the character encoding of raw HTML bytes.

    Checks (in order):
        1. BOM (Byte Order Mark)
        2. <meta charset="..."> tag
        3. <meta http-equiv="Content-Type" content="...; charset=...">
        4. UTF-8 validity check
        5. Fallback to 'utf-8'

    Args:
        raw_bytes: Raw HTML bytes.

    Returns:
        Detected encoding name (e.g., 'utf-8', 'iso-8859-1').

    Example:
        >>> detect_encoding(b'<html><head><meta charset="utf-8">')
        'utf-8'
    """
    if not raw_bytes:
        return "utf-8"

    # Check BOM
    if raw_bytes[:3] == b"\xef\xbb\xbf":
        return "utf-8"
    if raw_bytes[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"

    # Check meta charset in first 4KB
    head = raw_bytes[:4096]

    # <meta charset="...">
    match = re.search(
        rb'<meta[^>]*charset=["\']?([^"\'\s;>]+)',
        head,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).decode("ascii", errors="ignore").strip()

    # <meta http-equiv="Content-Type" content="...; charset=...">
    match = re.search(
        rb'content=["\'][^"\']*charset=([^"\'\s;]+)',
        head,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).decode("ascii", errors="ignore").strip()

    # Try UTF-8
    try:
        raw_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Fallback
    return "utf-8"


def decode_html_bytes(raw_bytes: bytes, encoding: str | None = None) -> str:
    """
    Decode raw HTML bytes to string with encoding detection.

    Args:
        raw_bytes: Raw HTML bytes.
        encoding: Known encoding (auto-detected if None).

    Returns:
        Decoded HTML string.
    """
    if encoding is None:
        encoding = detect_encoding(raw_bytes)

    try:
        return raw_bytes.decode(encoding, errors="replace")
    except (UnicodeDecodeError, LookupError):
        return raw_bytes.decode("utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════


def is_html(text: str) -> bool:
    """
    Check if a string looks like HTML.

    Args:
        text: Input string.

    Returns:
        True if the string appears to be HTML.

    Example:
        >>> is_html("<html><body>Hello</body></html>")
        True
        >>> is_html("Just plain text")
        False
    """
    if not text:
        return False

    stripped = text.strip()

    # Check for DOCTYPE or html tag
    if stripped.lower().startswith(("<!doctype", "<html")):
        return True

    # Check for common HTML tags in first 500 chars
    head = stripped[:500].lower()
    html_indicators = [
        "<div",
        "<p>",
        "<span",
        "<a ",
        "<img",
        "<table",
        "<h1",
        "<h2",
        "<h3",
        "<ul",
        "<ol",
        "<li",
        "<head",
        "<body",
        "<meta",
        "<link",
    ]

    return any(indicator in head for indicator in html_indicators)


def is_well_formed(html: str) -> bool:
    """
    Basic check if HTML is well-formed (balanced tags).

    Note: This is a heuristic check, not a full parser.

    Args:
        html: HTML string.

    Returns:
        True if tags appear balanced.
    """
    if not html:
        return True

    # Count opening and closing tags
    open_tags = re.findall(r"<(\w+)\b[^>]*(?<!/)>", html)
    close_tags = re.findall(r"</(\w+)>", html)

    # Self-closing tags don't need closing
    void_tags = {
        "br",
        "hr",
        "img",
        "input",
        "meta",
        "link",
        "area",
        "base",
        "col",
        "embed",
        "source",
        "track",
        "wbr",
    }

    open_count: dict[str, int] = {}
    for tag in open_tags:
        tag_lower = tag.lower()
        if tag_lower not in void_tags:
            open_count[tag_lower] = open_count.get(tag_lower, 0) + 1

    close_count: dict[str, int] = {}
    for tag in close_tags:
        tag_lower = tag.lower()
        close_count[tag_lower] = close_count.get(tag_lower, 0) + 1

    # Check balance
    for tag in set(list(open_count.keys()) + list(close_count.keys())):
        if open_count.get(tag, 0) != close_count.get(tag, 0):
            return False

    return True


def get_word_count(html: str) -> int:
    """
    Count words in HTML content (excluding tags).

    Args:
        html: HTML string.

    Returns:
        Word count.
    """
    text = extract_text(html)
    return len(text.split())


def get_char_count(html: str, include_tags: bool = False) -> int:
    """
    Count characters in HTML content.

    Args:
        html: HTML string.
        include_tags: Whether to include tag characters.

    Returns:
        Character count.
    """
    if include_tags:
        return len(html)
    return len(extract_text(html))
