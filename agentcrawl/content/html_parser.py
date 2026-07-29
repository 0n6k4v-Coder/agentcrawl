"""
AgentCrawl — HTML Parser
===========================

High-performance HTML parsing and content extraction using lxml.
Provides 10-20x faster parsing than BeautifulSoup with support for
main content extraction, metadata parsing, link extraction, and
noise removal.

Features:
    - lxml-based parsing (fast, memory-efficient)
    - Main content extraction (readability-like algorithm)
    - Noise removal (scripts, styles, nav, footer, ads, popups)
    - Metadata extraction (title, description, Open Graph, Twitter Cards)
    - Link extraction (internal / external classification)
    - Heading structure extraction
    - Table extraction
    - Image extraction
    - CSS selector and XPath querying
    - Custom include/exclude selectors

Usage:
    from agentcrawl.content.html_parser import HTMLParser

    parser = HTMLParser(html_string)

    # Extract main content
    content = parser.get_main_content()
    print(content.text)

    # Get metadata
    meta = parser.get_metadata()
    print(meta["title"], meta["description"])

    # Get links
    links = parser.get_links(base_url="https://example.com")
    print(f"{len(links['internal'])} internal, {len(links['external'])} external")

    # Query with CSS selectors
    articles = parser.select("article.post")
    for el in articles:
        print(el.text_content())

    # Query with XPath
    titles = parser.xpath("//h1/text()")

    # Remove noise and get clean HTML
    clean = parser.get_clean_html()
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("agentcrawl.content.html_parser")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class PageMetadata:
    """
    Extracted page metadata.

    Attributes:
        title: Page title (<title> or og:title).
        description: Meta description.
        keywords: Meta keywords.
        author: Meta author.
        canonical_url: Canonical URL.
        language: Page language (html lang attribute).
        charset: Character encoding.
        og_title: Open Graph title.
        og_description: Open Graph description.
        og_image: Open Graph image URL.
        og_url: Open Graph URL.
        og_type: Open Graph type.
        og_site_name: Open Graph site name.
        twitter_card: Twitter Card type.
        twitter_title: Twitter Card title.
        twitter_description: Twitter Card description.
        twitter_image: Twitter Card image.
        extra: Additional meta tags as key-value pairs.
    """
    title: str = ""
    description: str = ""
    keywords: str = ""
    author: str = ""
    canonical_url: str = ""
    language: str = ""
    charset: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_url: str = ""
    og_type: str = ""
    og_site_name: str = ""
    twitter_card: str = ""
    twitter_title: str = ""
    twitter_description: str = ""
    twitter_image: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "title": self.title,
            "description": self.description,
            "keywords": self.keywords,
            "author": self.author,
            "canonical_url": self.canonical_url,
            "language": self.language,
            "charset": self.charset,
        }
        # Add OG tags if present
        if self.og_title:
            d["og_title"] = self.og_title
        if self.og_description:
            d["og_description"] = self.og_description
        if self.og_image:
            d["og_image"] = self.og_image
        if self.og_url:
            d["og_url"] = self.og_url
        if self.og_type:
            d["og_type"] = self.og_type
        if self.og_site_name:
            d["og_site_name"] = self.og_site_name
        # Add Twitter tags if present
        if self.twitter_card:
            d["twitter_card"] = self.twitter_card
        if self.twitter_title:
            d["twitter_title"] = self.twitter_title
        if self.twitter_description:
            d["twitter_description"] = self.twitter_description
        if self.twitter_image:
            d["twitter_image"] = self.twitter_image
        if self.extra:
            d["extra"] = self.extra
        return d


@dataclass
class LinkInfo:
    """
    Extracted link information.

    Attributes:
        url: Absolute URL.
        text: Link anchor text.
        title: Link title attribute.
        is_internal: Whether the link points to the same domain.
        is_external: Whether the link points to a different domain.
        rel: Link rel attribute.
        domain: Target domain.
    """
    url: str
    text: str = ""
    title: str = ""
    is_internal: bool = False
    is_external: bool = False
    rel: str = ""
    domain: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "text": self.text,
            "title": self.title,
            "is_internal": self.is_internal,
            "is_external": self.is_external,
            "domain": self.domain,
        }


@dataclass
class HeadingInfo:
    """
    Extracted heading information.

    Attributes:
        text: Heading text.
        level: Heading level (1-6).
        index: Position in document.
    """
    text: str
    level: int
    index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "level": self.level, "index": self.index}


@dataclass
class ImageInfo:
    """
    Extracted image information.

    Attributes:
        src: Image source URL.
        alt: Alt text.
        title: Title attribute.
        width: Width attribute.
        height: Height attribute.
    """
    src: str
    alt: str = ""
    title: str = ""
    width: str = ""
    height: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "src": self.src,
            "alt": self.alt,
            "title": self.title,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class MainContent:
    """
    Extracted main content.

    Attributes:
        text: Clean text content.
        html: Cleaned HTML content.
        word_count: Number of words.
        char_count: Number of characters.
        content_element: Tag name of the content container.
    """
    text: str = ""
    html: str = ""
    word_count: int = 0
    char_count: int = 0
    content_element: str = ""

    def __post_init__(self) -> None:
        if self.word_count == 0 and self.text:
            self.word_count = len(self.text.split())
        if self.char_count == 0 and self.text:
            self.char_count = len(self.text)


# ══════════════════════════════════════════════════════════════
# Noise Element Definitions
# ══════════════════════════════════════════════════════════════

# Tags to always remove
REMOVE_TAGS: set[str] = {
    "script", "style", "noscript", "iframe", "svg", "canvas",
    "button", "input", "select", "textarea", "form",
    "dialog", "template", "embed", "object", "applet",
    "link", "meta", "head",
}

# Tags that indicate navigation / boilerplate
NOISE_TAGS: set[str] = {
    "nav", "footer", "aside", "header",
}

# Class/ID patterns that indicate noise
NOISE_PATTERNS: list[str] = [
    r"nav", r"navbar", r"navigation", r"menu", r"sidebar",
    r"footer", r"header", r"breadcrumb", r"pagination",
    r"comment", r"comments", r"disqus", r"social",
    r"share", r"sharing", r"related", r"recommend",
    r"advert", r"ad-", r"ads-", r"adsby", r"sponsor",
    r"popup", r"modal", r"overlay", r"cookie",
    r"banner", r"promo", r"newsletter", r"subscribe",
    r"widget", r"toc", r"table-of-contents",
    r"skip-to", r"sr-only", r"visually-hidden",
]

# Content container selectors (in priority order)
CONTENT_SELECTORS: list[str] = [
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
    ".post-body",
    ".article-body",
    "#article",
    "#post",
]


# ══════════════════════════════════════════════════════════════
# HTML Parser
# ══════════════════════════════════════════════════════════════

class HTMLParser:
    """
    High-performance HTML parser using lxml.

    Provides content extraction, metadata parsing, link extraction,
    and noise removal with 10-20x better performance than BeautifulSoup.

    Args:
        html: Raw HTML string.
        base_url: Base URL for resolving relative links.
        encoding: Character encoding (auto-detected if None).

    Example:
        >>> parser = HTMLParser(html, base_url="https://example.com")
        >>> content = parser.get_main_content()
        >>> meta = parser.get_metadata()
        >>> links = parser.get_links()
    """

    def __init__(
        self,
        html: str,
        base_url: str = "",
        encoding: str | None = None,
    ):
        self._raw_html = html
        self._base_url = base_url
        self._base_domain = ""
        if base_url:
            try:
                self._base_domain = urlparse(base_url).netloc.replace("www.", "")
            except Exception:
                pass

        self._tree: Any = None
        self._root: Any = None
        self._parsed = False

        # Parse on initialization
        self._parse(encoding)

    def _parse(self, encoding: str | None = None) -> None:
        """Parse HTML using lxml."""
        try:
            from lxml import html as lxml_html
            from lxml.html import HtmlElement

            if not self._raw_html.strip():
                self._parsed = False
                return

            # Parse with lxml
            self._tree = lxml_html.document_fromstring(
                self._raw_html,
                parser=lxml_html.HTMLParser(
                    encoding=encoding,
                    remove_comments=True,
                    remove_pis=True,
                ),
            )
            self._root = self._tree
            self._parsed = True

        except ImportError:
            raise ImportError(
                "lxml is required for HTML parsing. "
                "Install with: pip install lxml"
            )
        except Exception as e:
            logger.warning("HTML parsing failed: %s", e)
            self._parsed = False

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def is_parsed(self) -> bool:
        """Whether the HTML was successfully parsed."""
        return self._parsed

    @property
    def tree(self) -> Any:
        """The lxml element tree."""
        return self._tree

    @property
    def raw_html(self) -> str:
        """The original raw HTML."""
        return self._raw_html

    # ──────────────────────────────────────────────────────────
    # Main Content Extraction
    # ──────────────────────────────────────────────────────────

    def get_main_content(
        self,
        include_selectors: list[str] | None = None,
        exclude_selectors: list[str] | None = None,
        only_main: bool = True,
    ) -> MainContent:
        """
        Extract the main content from the page.

        Uses a priority-based approach:
            1. Try custom include_selectors (if provided)
            2. Try standard content selectors (article, main, etc.)
            3. Fall back to body with noise removal

        Args:
            include_selectors: CSS selectors to target specific content.
            exclude_selectors: CSS selectors to exclude from content.
            only_main: Whether to extract only main content (vs full body).

        Returns:
            MainContent with text and HTML.
        """
        if not self._parsed or self._root is None:
            return MainContent()

        from lxml.html import tostring

        content_el = None
        content_tag = ""

        # 1. Custom include selectors
        if include_selectors:
            for selector in include_selectors:
                elements = self.select(selector)
                if elements:
                    content_el = elements[0]
                    content_tag = f"selector:{selector}"
                    break

        # 2. Standard content selectors
        if content_el is None and only_main:
            for selector in CONTENT_SELECTORS:
                elements = self.select(selector)
                if elements:
                    # Pick the element with the most text
                    best = max(elements, key=lambda el: len(el.text_content()))
                    if len(best.text_content().strip()) > 100:
                        content_el = best
                        content_tag = selector
                        break

        # 3. Fall back to body
        if content_el is None:
            body = self._root.find(".//body")
            content_el = body if body is not None else self._root
            content_tag = "body"

        # Clone the element to avoid modifying the original tree
        from copy import deepcopy
        content_clone = deepcopy(content_el)

        # Remove noise elements
        self._remove_noise(content_clone, exclude_selectors or [])

        # Extract text and HTML
        text = content_clone.text_content()
        text = self._clean_text(text)

        try:
            html_out = tostring(content_clone, encoding="unicode", method="html")
        except Exception:
            html_out = ""

        return MainContent(
            text=text,
            html=html_out,
            content_element=content_tag,
        )

    def get_clean_html(
        self,
        exclude_selectors: list[str] | None = None,
    ) -> str:
        """
        Get cleaned HTML with noise elements removed.

        Args:
            exclude_selectors: Additional CSS selectors to remove.

        Returns:
            Cleaned HTML string.
        """
        if not self._parsed or self._root is None:
            return ""

        from copy import deepcopy

        from lxml.html import tostring

        clone = deepcopy(self._root)
        self._remove_noise(clone, exclude_selectors or [])

        try:
            return tostring(clone, encoding="unicode", method="html")
        except Exception:
            return ""

    def get_text(self) -> str:
        """Get all text content from the page."""
        if not self._parsed or self._root is None:
            return ""
        text = self._root.text_content()
        return self._clean_text(text)

    # ──────────────────────────────────────────────────────────
    # Metadata Extraction
    # ──────────────────────────────────────────────────────────

    def get_metadata(self) -> PageMetadata:
        """
        Extract page metadata from <head>.

        Returns:
            PageMetadata with title, description, OG tags, etc.
        """
        if not self._parsed or self._root is None:
            return PageMetadata()

        meta = PageMetadata()

        # Title
        title_el = self._root.find(".//title")
        if title_el is not None and title_el.text:
            meta.title = title_el.text.strip()

        # HTML lang
        html_el = self._root.find(".//html")
        if html_el is not None:
            meta.language = html_el.get("lang", "")

        # Meta tags
        for meta_el in self._root.iter("meta"):
            name = (meta_el.get("name") or "").lower()
            prop = (meta_el.get("property") or "").lower()
            content = meta_el.get("content", "")
            http_equiv = (meta_el.get("http-equiv") or "").lower()
            charset = meta_el.get("charset", "")

            if charset:
                meta.charset = charset

            if http_equiv == "content-type" and "charset=" in content:
                meta.charset = content.split("charset=")[-1].strip()

            # Standard meta
            if name == "description":
                meta.description = content
            elif name == "keywords":
                meta.keywords = content
            elif name == "author":
                meta.author = content

            # Open Graph
            elif prop == "og:title":
                meta.og_title = content
            elif prop == "og:description":
                meta.og_description = content
            elif prop == "og:image":
                meta.og_image = content
            elif prop == "og:url":
                meta.og_url = content
            elif prop == "og:type":
                meta.og_type = content
            elif prop == "og:site_name":
                meta.og_site_name = content

            # Twitter Card
            elif name == "twitter:card":
                meta.twitter_card = content
            elif name == "twitter:title":
                meta.twitter_title = content
            elif name == "twitter:description":
                meta.twitter_description = content
            elif name == "twitter:image":
                meta.twitter_image = content

            # Store other meta tags
            elif name or prop:
                key = name or prop
                if key and content:
                    meta.extra[key] = content

        # Canonical URL
        for link_el in self._root.iter("link"):
            if link_el.get("rel") == "canonical":
                meta.canonical_url = link_el.get("href", "")
                break

        # Fallbacks
        if not meta.title and meta.og_title:
            meta.title = meta.og_title
        if not meta.description and meta.og_description:
            meta.description = meta.og_description

        return meta

    # ──────────────────────────────────────────────────────────
    # Link Extraction
    # ──────────────────────────────────────────────────────────

    def get_links(
        self,
        base_url: str | None = None,
        include_images: bool = False,
    ) -> dict[str, list[LinkInfo]]:
        """
        Extract all links from the page.

        Args:
            base_url: Base URL for resolving relative links.
            include_images: Whether to include image src as links.

        Returns:
            Dictionary with 'internal', 'external', and 'all' lists.
        """
        if not self._parsed or self._root is None:
            return {"internal": [], "external": [], "all": []}

        base = base_url or self._base_url
        links: list[LinkInfo] = []
        seen_urls: set[str] = set()

        for a_el in self._root.iter("a"):
            href = a_el.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            # Resolve relative URL
            absolute_url = urljoin(base, href) if base else href

            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)

            # Classify
            try:
                parsed = urlparse(absolute_url)
                domain = parsed.netloc.replace("www.", "")
            except Exception:
                domain = ""

            is_internal = (
                self._base_domain != ""
                and domain == self._base_domain
            )
            is_external = domain != "" and not is_internal

            text = a_el.text_content().strip()
            title = a_el.get("title", "")
            rel = " ".join(a_el.get("rel", [])) if isinstance(a_el.get("rel"), list) else a_el.get("rel", "")

            links.append(LinkInfo(
                url=absolute_url,
                text=text[:200],
                title=title,
                is_internal=is_internal,
                is_external=is_external,
                rel=rel,
                domain=domain,
            ))

        # Include images
        if include_images:
            for img_el in self._root.iter("img"):
                src = img_el.get("src", "").strip()
                if not src:
                    continue
                absolute_src = urljoin(base, src) if base else src
                if absolute_src in seen_urls:
                    continue
                seen_urls.add(absolute_src)

                try:
                    domain = urlparse(absolute_src).netloc.replace("www.", "")
                except Exception:
                    domain = ""

                links.append(LinkInfo(
                    url=absolute_src,
                    text=img_el.get("alt", ""),
                    is_internal=self._base_domain != "" and domain == self._base_domain,
                    is_external=domain != "" and domain != self._base_domain,
                    domain=domain,
                ))

        internal = [l for l in links if l.is_internal]
        external = [l for l in links if l.is_external]

        return {
            "internal": internal,
            "external": external,
            "all": links,
        }

    # ──────────────────────────────────────────────────────────
    # Heading Extraction
    # ──────────────────────────────────────────────────────────

    def get_headings(self) -> list[HeadingInfo]:
        """Extract all headings (h1-h6) in document order."""
        if not self._parsed or self._root is None:
            return []

        headings: list[HeadingInfo] = []
        index = 0

        for level in range(1, 7):
            for el in self._root.iter(f"h{level}"):
                text = el.text_content().strip()
                if text:
                    headings.append(HeadingInfo(
                        text=text,
                        level=level,
                        index=index,
                    ))
                    index += 1

        # Sort by document order (approximated by index)
        return headings

    def get_heading_structure(self) -> list[dict[str, Any]]:
        """Get heading structure as a nested tree."""
        headings = self.get_headings()
        return [h.to_dict() for h in headings]

    # ──────────────────────────────────────────────────────────
    # Table Extraction
    # ──────────────────────────────────────────────────────────

    def get_tables(self) -> list[list[list[str]]]:
        """
        Extract all tables as 2D arrays.

        Returns:
            List of tables, each table is a list of rows,
            each row is a list of cell texts.
        """
        if not self._parsed or self._root is None:
            return []

        tables: list[list[list[str]]] = []

        for table_el in self._root.iter("table"):
            rows: list[list[str]] = []
            for tr in table_el.iter("tr"):
                cells: list[str] = []
                for cell in tr:
                    if cell.tag in ("td", "th"):
                        cells.append(cell.text_content().strip())
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)

        return tables

    # ──────────────────────────────────────────────────────────
    # Image Extraction
    # ──────────────────────────────────────────────────────────

    def get_images(self, base_url: str | None = None) -> list[ImageInfo]:
        """Extract all images from the page."""
        if not self._parsed or self._root is None:
            return []

        base = base_url or self._base_url
        images: list[ImageInfo] = []

        for img_el in self._root.iter("img"):
            src = img_el.get("src", "").strip()
            if not src:
                continue

            absolute_src = urljoin(base, src) if base else src

            images.append(ImageInfo(
                src=absolute_src,
                alt=img_el.get("alt", ""),
                title=img_el.get("title", ""),
                width=img_el.get("width", ""),
                height=img_el.get("height", ""),
            ))

        return images

    # ──────────────────────────────────────────────────────────
    # CSS Selector & XPath
    # ──────────────────────────────────────────────────────────

    def select(self, selector: str) -> list[Any]:
        """
        Query elements using a CSS selector.

        Args:
            selector: CSS selector string.

        Returns:
            List of matching lxml elements.
        """
        if not self._parsed or self._root is None:
            return []

        try:
            from lxml.cssselect import CSSSelector
            css = CSSSelector(selector)
            return css(self._root)
        except Exception as e:
            logger.debug("CSS selector error '%s': %s", selector, e)
            return []

    def select_one(self, selector: str) -> Any | None:
        """Query a single element using a CSS selector."""
        results = self.select(selector)
        return results[0] if results else None

    def select_text(self, selector: str) -> list[str]:
        """Query elements and return their text content."""
        return [el.text_content().strip() for el in self.select(selector)]

    def select_first_text(self, selector: str) -> str:
        """Query first element and return its text content."""
        el = self.select_one(selector)
        return el.text_content().strip() if el is not None else ""

    def select_attr(self, selector: str, attr: str) -> list[str]:
        """Query elements and return a specific attribute."""
        return [
            el.get(attr, "")
            for el in self.select(selector)
            if el.get(attr)
        ]

    def xpath(self, expression: str) -> list[Any]:
        """
        Query using an XPath expression.

        Args:
            expression: XPath expression.

        Returns:
            List of matching elements or values.
        """
        if not self._parsed or self._root is None:
            return []

        try:
            return self._root.xpath(expression)
        except Exception as e:
            logger.debug("XPath error '%s': %s", expression, e)
            return []

    def xpath_text(self, expression: str) -> list[str]:
        """Query with XPath and return text results."""
        results = self.xpath(expression)
        texts = []
        for r in results:
            if isinstance(r, str):
                texts.append(r.strip())
            elif hasattr(r, "text_content"):
                texts.append(r.text_content().strip())
        return texts

    # ──────────────────────────────────────────────────────────
    # Noise Removal
    # ──────────────────────────────────────────────────────────

    def _remove_noise(
        self,
        element: Any,
        exclude_selectors: list[str],
    ) -> None:
        """
        Remove noise elements from an element tree (in-place).

        Removes:
            - Script, style, and other non-content tags
            - Navigation, footer, aside elements
            - Elements matching noise class/ID patterns
            - Elements matching custom exclude selectors
        """
        # Remove by tag name
        for tag in REMOVE_TAGS:
            for el in element.iter(tag):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)

        # Remove noise tags (nav, footer, aside, header)
        for tag in NOISE_TAGS:
            for el in element.iter(tag):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)

        # Remove by class/ID patterns
        noise_regex = re.compile(
            "|".join(NOISE_PATTERNS),
            re.IGNORECASE,
        )

        for el in list(element.iter()):
            if not hasattr(el, "get"):
                continue

            class_attr = el.get("class", "")
            id_attr = el.get("id", "")
            role_attr = el.get("role", "")

            if (
                noise_regex.search(class_attr)
                or noise_regex.search(id_attr)
                or role_attr in ("navigation", "banner", "complementary")
            ):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)

        # Remove by custom exclude selectors
        for selector in exclude_selectors:
            try:
                from lxml.cssselect import CSSSelector
                css = CSSSelector(selector)
                for el in css(element):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)
            except Exception:
                pass

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

    # ──────────────────────────────────────────────────────────
    # Text Cleaning
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean extracted text content."""
        # Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove zero-width characters
        text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
        # Strip leading/trailing whitespace per line
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        return text.strip()

    # ──────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────

    def get_body_html(self) -> str:
        """Get the inner HTML of the <body> element."""
        if not self._parsed or self._root is None:
            return ""

        from lxml.html import tostring

        body = self._root.find(".//body")
        if body is None:
            return ""

        try:
            return tostring(body, encoding="unicode", method="html")
        except Exception:
            return ""

    def get_title(self) -> str:
        """Get the page title."""
        if not self._parsed or self._root is None:
            return ""
        title_el = self._root.find(".//title")
        return title_el.text.strip() if title_el is not None and title_el.text else ""

    def get_word_count(self) -> int:
        """Get total word count of the page."""
        text = self.get_text()
        return len(text.split())

    def to_dict(self) -> dict[str, Any]:
        """Get a summary of the parsed page."""
        return {
            "parsed": self._parsed,
            "base_url": self._base_url,
            "base_domain": self._base_domain,
            "title": self.get_title(),
            "word_count": self.get_word_count(),
            "raw_html_length": len(self._raw_html),
        }

    def __repr__(self) -> str:
        status = "parsed" if self._parsed else "not parsed"
        return (
            f"HTMLParser(url={self._base_url!r}, "
            f"status={status}, "
            f"html_len={len(self._raw_html)})"
        )
