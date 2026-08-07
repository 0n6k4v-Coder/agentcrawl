"""
AgentCrawl — Citation Extraction & Management
================================================

Extracts, manages, and formats citations from web content.
Converts inline links and references into numbered citations
optimized for LLM consumption and RAG attribution.

Features:
    - Extract inline links as numbered citations [1], [2], ...
    - Extract existing numbered references from text
    - Deduplicate citations by URL
    - Renumber citations sequentially
    - Generate formatted bibliography (Markdown, APA, plain)
    - Insert citation markers into clean text
    - Track citation context (surrounding text)

Usage:
    from agentcrawl.content.citation import CitationExtractor, CitationManager

    # Extract citations from markdown
    extractor = CitationExtractor()
    result = extractor.extract(markdown_text)

    print(result.text_with_citations)   # Text with [1], [2] markers
    print(result.bibliography)          # Numbered reference list
    print(result.citations)             # List of Citation objects

    # Format bibliography
    print(result.format_bibliography("markdown"))
    print(result.format_bibliography("apa"))

    # Manage citations manually
    manager = CitationManager()
    manager.add(url="https://example.com", title="Example", text="Example Domain")
    manager.add(url="https://python.org", title="Python", text="Python Language")
    text = manager.insert_citations("Visit [Example](https://example.com) and [Python](https://python.org)")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
from urllib.parse import urlparse

logger = logging.getLogger("agentcrawl.content.citation")


# ══════════════════════════════════════════════════════════════
# Types & Enums
# ══════════════════════════════════════════════════════════════


class BibliographyFormat(str, Enum):
    """Supported bibliography output formats."""

    MARKDOWN = "markdown"
    APA = "apa"
    PLAIN = "plain"
    JSON = "json"
    BIBTEX = "bibtex"


class CitationSource(str, Enum):
    """How a citation was discovered."""

    INLINE_LINK = "inline_link"  # [text](url) in markdown
    NUMBERED_REF = "numbered_ref"  # [1] style reference in text
    RAW_URL = "raw_url"  # Bare URL in text
    FOOTNOTE = "footnote"  # [^1] style footnote
    MANUAL = "manual"  # Manually added


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class Citation:
    """
    A single citation reference.

    Attributes:
        number: Citation number (1-based).
        url: The cited URL.
        title: Page title or link text.
        text: The link/anchor text in the document.
        context: Surrounding text where the citation appears.
        source: How this citation was discovered.
        domain: Extracted domain from the URL.
        appears_count: Number of times this URL appears in the document.
        first_occurrence: Character offset of first occurrence.
        markers: List of marker positions in the text [(start, end), ...].
    """

    number: int = 0
    url: str = ""
    title: str = ""
    text: str = ""
    context: str = ""
    source: CitationSource = CitationSource.INLINE_LINK
    domain: str = ""
    appears_count: int = 1
    first_occurrence: int = 0
    markers: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.domain and self.url:
            try:
                parsed = urlparse(self.url)
                self.domain = parsed.netloc.replace("www.", "")
            except Exception:
                self.domain = ""

    @property
    def display_title(self) -> str:
        """Best available title for display."""
        if self.title:
            return self.title
        if self.text:
            return self.text
        if self.domain:
            return self.domain
        return self.url

    @property
    def short_url(self) -> str:
        """Shortened URL for display."""
        url = self.url
        if len(url) > 80:
            url = url[:77] + "..."
        return url

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "context": self.context[:200] if self.context else "",
            "source": self.source.value,
            "domain": self.domain,
            "appears_count": self.appears_count,
        }

    def to_markdown_ref(self) -> str:
        """Format as a Markdown reference line."""
        title = self.display_title
        return f"[{self.number}] [{title}]({self.url})"

    def to_apa_ref(self) -> str:
        """Format as an APA-style reference."""
        title = self.display_title
        domain = self.domain or "unknown"
        return f"{title}. {domain}. {self.url}"

    def to_plain_ref(self) -> str:
        """Format as a plain text reference."""
        return f"[{self.number}] {self.display_title} - {self.url}"

    def to_bibtex_ref(self) -> str:
        """Format as a BibTeX entry."""
        key = re.sub(r"[^a-zA-Z0-9]", "", self.domain)[:10] + str(self.number)
        return (
            f"@misc{{{key},\n"
            f"  title = {{{self.display_title}}},\n"
            f"  url = {{{self.url}}},\n"
            f"  note = {{Accessed via AgentCrawl}}\n"
            f"}}"
        )

    def __repr__(self) -> str:
        return f"Citation([{self.number}] {self.display_title!r} → {self.domain})"


@dataclass
class CitationResult:
    """
    Result of citation extraction.

    Attributes:
        citations: List of extracted Citation objects.
        text_with_citations: Original text with [N] markers inserted.
        clean_text: Text with links replaced by [N] markers only.
        bibliography: Formatted bibliography string (Markdown).
        original_text: The original unmodified text.
        total_citations: Number of unique citations.
        total_references: Total reference occurrences (including duplicates).
    """

    citations: list[Citation] = field(default_factory=list)
    text_with_citations: str = ""
    clean_text: str = ""
    bibliography: str = ""
    original_text: str = ""
    total_citations: int = 0
    total_references: int = 0

    def __post_init__(self) -> None:
        self.total_citations = len(self.citations)

    def format_bibliography(
        self, fmt: str | BibliographyFormat = BibliographyFormat.MARKDOWN
    ) -> str:
        """
        Format the bibliography in a specific style.

        Args:
            fmt: Format type ('markdown', 'apa', 'plain', 'json', 'bibtex').

        Returns:
            Formatted bibliography string.
        """
        if isinstance(fmt, str):
            try:
                fmt = BibliographyFormat(fmt)
            except ValueError:
                fmt = BibliographyFormat.MARKDOWN

        if not self.citations:
            return ""

        if fmt == BibliographyFormat.MARKDOWN:
            lines = [c.to_markdown_ref() for c in self.citations]
            return "\n".join(lines)

        if fmt == BibliographyFormat.APA:
            lines = [c.to_apa_ref() for c in self.citations]
            return "\n".join(lines)

        if fmt == BibliographyFormat.PLAIN:
            lines = [c.to_plain_ref() for c in self.citations]
            return "\n".join(lines)

        if fmt == BibliographyFormat.BIBTEX:
            entries = [c.to_bibtex_ref() for c in self.citations]
            return "\n\n".join(entries)

        if fmt == BibliographyFormat.JSON:
            import json

            return json.dumps(
                [c.to_dict() for c in self.citations],
                ensure_ascii=False,
                indent=2,
            )

        return ""

    def get_citation_by_number(self, number: int) -> Citation | None:
        """Get a citation by its number."""
        for c in self.citations:
            if c.number == number:
                return c
        return None

    def get_citations_by_domain(self, domain: str) -> list[Citation]:
        """Get all citations from a specific domain."""
        return [c for c in self.citations if c.domain == domain]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_citations": self.total_citations,
            "total_references": self.total_references,
            "citations": [c.to_dict() for c in self.citations],
            "bibliography_markdown": self.format_bibliography("markdown"),
        }


# ══════════════════════════════════════════════════════════════
# Citation Extractor
# ══════════════════════════════════════════════════════════════


class CitationExtractor:
    """
    Extracts citations from Markdown/HTML text and converts inline
    links into numbered references.

    Processing pipeline:
        1. Find all Markdown inline links [text](url)
        2. Find all existing numbered references [N]
        3. Find all bare URLs
        4. Find all footnotes [^N]
        5. Deduplicate by URL
        6. Assign sequential numbers
        7. Replace inline links with [N] markers
        8. Generate bibliography

    Args:
        extract_inline_links: Extract [text](url) links.
        extract_numbered_refs: Extract existing [N] references.
        extract_raw_urls: Extract bare URLs.
        extract_footnotes: Extract [^N] footnotes.
        deduplicate: Deduplicate citations by URL.
        include_context: Capture surrounding text as context.
        context_window: Characters of context around each citation.
        min_url_length: Minimum URL length to consider.
        exclude_domains: Domains to exclude from citations.
        exclude_patterns: URL patterns to exclude (regex).

    Example:
        >>> extractor = CitationExtractor()
        >>> result = extractor.extract(markdown_text)
        >>> print(result.text_with_citations)
        >>> print(result.format_bibliography("markdown"))
    """

    # Regex patterns
    _INLINE_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    _NUMBERED_REF_PATTERN = re.compile(r"\[(\d+)\]")
    _RAW_URL_PATTERN = re.compile(r"(?<!\()(?<!\[)(https?://[^\s\)\]>\"']+)")
    _FOOTNOTE_PATTERN = re.compile(r"\[\^(\d+)\]:\s*(.+)")
    _IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

    def __init__(
        self,
        extract_inline_links: bool = True,
        extract_numbered_refs: bool = True,
        extract_raw_urls: bool = True,
        extract_footnotes: bool = True,
        deduplicate: bool = True,
        include_context: bool = True,
        context_window: int = 100,
        min_url_length: int = 10,
        exclude_domains: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        self._extract_inline_links = extract_inline_links
        self._extract_numbered_refs = extract_numbered_refs
        self._extract_raw_urls = extract_raw_urls
        self._extract_footnotes = extract_footnotes
        self._deduplicate = deduplicate
        self._include_context = include_context
        self._context_window = context_window
        self._min_url_length = min_url_length
        self._exclude_domains = set(exclude_domains or [])
        self._exclude_patterns = [re.compile(p) for p in (exclude_patterns or [])]

    # ──────────────────────────────────────────────────────────
    # Main API
    # ──────────────────────────────────────────────────────────

    def extract(self, text: str) -> CitationResult:
        """
        Extract all citations from text.

        Args:
            text: Markdown or plain text content.

        Returns:
            CitationResult with citations, modified text, and bibliography.
        """
        if not text.strip():
            return CitationResult(original_text=text)

        # Collect raw citations from all sources
        raw_citations: list[Citation] = []

        if self._extract_inline_links:
            raw_citations.extend(self._extract_inline_links_from(text))

        if self._extract_footnotes:
            raw_citations.extend(self._extract_footnotes_from(text))

        if self._extract_numbered_refs:
            raw_citations.extend(self._extract_numbered_refs_from(text))

        if self._extract_raw_urls:
            raw_citations.extend(self._extract_raw_urls_from(text))

        # Filter excluded
        raw_citations = self._filter_excluded(raw_citations)

        # Deduplicate
        if self._deduplicate:
            citations = self._deduplicate_citations(raw_citations)
        else:
            citations = raw_citations

        # Assign sequential numbers
        for i, citation in enumerate(citations, 1):
            citation.number = i

        # Build URL → number mapping
        url_to_number: dict[str, int] = {}
        for c in citations:
            url_to_number[c.url] = c.number

        # Generate modified text
        text_with_citations = self._insert_citation_markers(text, url_to_number)
        clean_text = self._create_clean_text(text, url_to_number)

        # Generate bibliography
        bibliography = "\n".join(c.to_markdown_ref() for c in citations)

        # Count total references
        total_refs = sum(c.appears_count for c in citations)

        return CitationResult(
            citations=citations,
            text_with_citations=text_with_citations,
            clean_text=clean_text,
            bibliography=bibliography,
            original_text=text,
            total_references=total_refs,
        )

    def extract_urls(self, text: str) -> list[str]:
        """
        Extract just the URLs from text (convenience method).

        Args:
            text: Input text.

        Returns:
            Deduplicated list of URLs in order of appearance.
        """
        result = self.extract(text)
        return [c.url for c in result.citations]

    # ──────────────────────────────────────────────────────────
    # Extraction Methods
    # ──────────────────────────────────────────────────────────

    def _extract_inline_links_from(self, text: str) -> list[Citation]:
        """Extract Markdown inline links [text](url)."""
        citations: list[Citation] = []

        # Remove images first (they use ![text](url))
        text_no_images = self._IMAGE_PATTERN.sub("", text)

        for match in self._INLINE_LINK_PATTERN.finditer(text_no_images):
            link_text = match.group(1).strip()
            url = match.group(2).strip()

            # Skip anchors and relative links
            if url.startswith("#") or url.startswith("mailto:"):
                continue

            if len(url) < self._min_url_length:
                continue

            # Extract context
            context = ""
            if self._include_context:
                start = max(0, match.start() - self._context_window)
                end = min(len(text_no_images), match.end() + self._context_window)
                context = text_no_images[start:end].strip()

            citations.append(
                Citation(
                    url=url,
                    title=link_text,
                    text=link_text,
                    context=context,
                    source=CitationSource.INLINE_LINK,
                    first_occurrence=match.start(),
                    markers=[(match.start(), match.end())],
                )
            )

        return citations

    def _extract_numbered_refs_from(self, text: str) -> list[Citation]:
        """Extract existing numbered references [1], [2], etc."""
        citations: list[Citation] = []

        # Look for reference definitions: [1]: url or [1]: title url
        ref_def_pattern = re.compile(
            r"^\[(\d+)\]:\s*(\S+)(?:\s+\"(.+)\")?\s*$",
            re.MULTILINE,
        )

        for match in ref_def_pattern.finditer(text):
            number = int(match.group(1))
            url = match.group(2)
            title = match.group(3) or ""

            if len(url) < self._min_url_length:
                continue

            citations.append(
                Citation(
                    number=number,
                    url=url,
                    title=title,
                    text=title,
                    source=CitationSource.NUMBERED_REF,
                    first_occurrence=match.start(),
                )
            )

        return citations

    def _extract_raw_urls_from(self, text: str) -> list[Citation]:
        """Extract bare URLs not already in Markdown links."""
        citations: list[Citation] = []

        # Remove existing markdown links to avoid double-counting
        text_clean = self._INLINE_LINK_PATTERN.sub("", text)
        text_clean = self._IMAGE_PATTERN.sub("", text_clean)

        for match in self._RAW_URL_PATTERN.finditer(text_clean):
            url = match.group(1).rstrip(".,;:!?")

            if len(url) < self._min_url_length:
                continue

            context = ""
            if self._include_context:
                start = max(0, match.start() - self._context_window)
                end = min(len(text_clean), match.end() + self._context_window)
                context = text_clean[start:end].strip()

            citations.append(
                Citation(
                    url=url,
                    text=url,
                    context=context,
                    source=CitationSource.RAW_URL,
                    first_occurrence=match.start(),
                    markers=[(match.start(), match.end())],
                )
            )

        return citations

    def _extract_footnotes_from(self, text: str) -> list[Citation]:
        """Extract footnotes [^1]: content."""
        citations: list[Citation] = []

        for match in self._FOOTNOTE_PATTERN.finditer(text):
            content = match.group(2).strip()

            # Try to extract URL from footnote content
            url_match = self._RAW_URL_PATTERN.search(content)
            if url_match:
                url = url_match.group(1).rstrip(".,;:!?")
                title = content.replace(url, "").strip().strip("-\u2013\u2014")

                citations.append(
                    Citation(
                        url=url,
                        title=title or url,
                        text=content,
                        source=CitationSource.FOOTNOTE,
                        first_occurrence=match.start(),
                    )
                )

        return citations

    # ──────────────────────────────────────────────────────────
    # Processing
    # ──────────────────────────────────────────────────────────

    def _filter_excluded(self, citations: list[Citation]) -> list[Citation]:
        """Remove citations matching exclusion rules."""
        filtered: list[Citation] = []

        for c in citations:
            # Check domain exclusion
            if c.domain in self._exclude_domains:
                continue

            # Check pattern exclusion
            excluded = False
            for pattern in self._exclude_patterns:
                if pattern.search(c.url):
                    excluded = True
                    break
            if excluded:
                continue

            filtered.append(c)

        return filtered

    def _deduplicate_citations(self, citations: list[Citation]) -> list[Citation]:
        """Deduplicate citations by URL, merging occurrence data."""
        url_map: dict[str, Citation] = {}
        ordered: list[Citation] = []

        for c in citations:
            # Normalize URL
            normalized = self._normalize_url(c.url)

            if normalized in url_map:
                # Merge: increment count, add markers
                existing = url_map[normalized]
                existing.appears_count += 1
                existing.markers.extend(c.markers)
                # Prefer longer title
                if len(c.title) > len(existing.title):
                    existing.title = c.title
                if len(c.text) > len(existing.text):
                    existing.text = c.text
            else:
                c.url = normalized
                url_map[normalized] = c
                ordered.append(c)

        return ordered

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize a URL for deduplication."""
        url = url.strip().rstrip("/")
        # Remove fragment
        if "#" in url:
            url = url.split("#")[0]
        # Remove trailing slash after domain
        if url.endswith("/"):
            url = url[:-1]
        return url

    def _insert_citation_markers(
        self,
        text: str,
        url_to_number: dict[str, int],
    ) -> str:
        """
        Insert [N] citation markers after inline links.

        Transforms: [text](url) → text [N]
        """

        def _replace_link(match: re.Match[str]) -> str:
            link_text = match.group(1).strip()
            url = match.group(2).strip()
            normalized = self._normalize_url(url)
            number = url_to_number.get(normalized)

            if number:
                return f"{link_text} [{number}]"
            return match.group(0)  # Keep original if no citation number

        result = self._INLINE_LINK_PATTERN.sub(_replace_link, text)

        # Also mark bare URLs
        def _replace_url(match: re.Match[str]) -> str:
            url = match.group(1).rstrip(".,;:!?")
            normalized = self._normalize_url(url)
            number = url_to_number.get(normalized)

            if number:
                return f"{url} [{number}]"
            return match.group(0)

        # Only apply to text that doesn't already have markers
        result = self._RAW_URL_PATTERN.sub(_replace_url, result)

        return result

    def _create_clean_text(
        self,
        text: str,
        url_to_number: dict[str, int],
    ) -> str:
        """
        Create clean text with links replaced by [N] markers only.

        Transforms: [text](url) → text [N]
        Removes: raw URLs (replaced by [N])
        """

        def _replace_link(match: re.Match[str]) -> str:
            link_text = match.group(1).strip()
            url = match.group(2).strip()
            normalized = self._normalize_url(url)
            number = url_to_number.get(normalized)

            if number:
                return f"{link_text} [{number}]"
            return link_text

        result = self._INLINE_LINK_PATTERN.sub(_replace_link, text)

        # Remove images
        result = self._IMAGE_PATTERN.sub("", result)

        # Replace bare URLs with markers
        def _replace_url(match: re.Match[str]) -> str:
            url = match.group(1).rstrip(".,;:!?")
            normalized = self._normalize_url(url)
            number = url_to_number.get(normalized)

            if number:
                return f"[{number}]"
            return ""

        result = self._RAW_URL_PATTERN.sub(_replace_url, result)

        # Remove footnote definitions
        result = self._FOOTNOTE_PATTERN.sub("", result)

        # Remove reference definitions
        result = re.sub(
            r"^\[\d+\]:\s*\S+(?:\s+\".+\")?\s*$",
            "",
            result,
            flags=re.MULTILINE,
        )

        # Clean up extra whitespace
        result = re.sub(r"\n{3,}", "\n\n", result)

        return result.strip()

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "extract_inline_links": self._extract_inline_links,
            "extract_numbered_refs": self._extract_numbered_refs,
            "extract_raw_urls": self._extract_raw_urls,
            "extract_footnotes": self._extract_footnotes,
            "deduplicate": self._deduplicate,
            "include_context": self._include_context,
            "context_window": self._context_window,
            "exclude_domains": list(self._exclude_domains),
        }

    def __repr__(self) -> str:
        return f"CitationExtractor(dedup={self._deduplicate}, context={self._include_context})"


# ══════════════════════════════════════════════════════════════
# Citation Manager
# ══════════════════════════════════════════════════════════════


class CitationManager:
    """
    Manages a collection of citations with manual add/remove
    and text insertion capabilities.

    Useful for building citations incrementally during a crawl
    or for managing citations across multiple pages.

    Example:
        >>> manager = CitationManager()
        >>> manager.add(url="https://example.com", title="Example")
        >>> manager.add(url="https://python.org", title="Python")
        >>> text = manager.insert_citations("See [Example](https://example.com)")
        >>> print(manager.bibliography())
    """

    def __init__(self, start_number: int = 1):
        self._citations: list[Citation] = []
        self._url_map: dict[str, int] = {}  # url → index in _citations
        self._next_number = start_number

    @property
    def citations(self) -> list[Citation]:
        """All managed citations."""
        return list(self._citations)

    @property
    def count(self) -> int:
        """Number of citations."""
        return len(self._citations)

    def add(
        self,
        url: str,
        title: str = "",
        text: str = "",
        context: str = "",
        source: CitationSource = CitationSource.MANUAL,
    ) -> Citation:
        """
        Add a citation.

        If the URL already exists, increments its count and
        returns the existing citation.

        Args:
            url: Citation URL.
            title: Page title.
            text: Link text.
            context: Surrounding context.
            source: Citation source type.

        Returns:
            The Citation object (new or existing).
        """
        normalized = url.strip().rstrip("/")

        if normalized in self._url_map:
            idx = self._url_map[normalized]
            existing = self._citations[idx]
            existing.appears_count += 1
            if title and len(title) > len(existing.title):
                existing.title = title
            return existing

        citation = Citation(
            number=self._next_number,
            url=normalized,
            title=title,
            text=text or title,
            context=context,
            source=source,
        )

        self._url_map[normalized] = len(self._citations)
        self._citations.append(citation)
        self._next_number += 1

        return citation

    def remove(self, url: str) -> bool:
        """
        Remove a citation by URL.

        Args:
            url: URL to remove.

        Returns:
            True if the citation was found and removed.
        """
        normalized = url.strip().rstrip("/")
        if normalized not in self._url_map:
            return False

        idx = self._url_map.pop(normalized)
        self._citations.pop(idx)

        # Rebuild index map and renumber
        self._url_map.clear()
        for i, c in enumerate(self._citations):
            c.number = i + 1
            self._url_map[c.url] = i
        self._next_number = len(self._citations) + 1

        return True

    def get_number(self, url: str) -> int | None:
        """Get the citation number for a URL."""
        normalized = url.strip().rstrip("/")
        idx = self._url_map.get(normalized)
        if idx is not None:
            return self._citations[idx].number
        return None

    def get_by_number(self, number: int) -> Citation | None:
        """Get a citation by its number."""
        for c in self._citations:
            if c.number == number:
                return c
        return None

    def insert_citations(self, text: str) -> str:
        """
        Insert citation markers into text.

        Replaces [text](url) with text [N] for known URLs.

        Args:
            text: Input text with Markdown links.

        Returns:
            Text with citation markers.
        """
        CitationExtractor()
        pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

        def _replace(match: re.Match[str]) -> str:
            link_text = match.group(1).strip()
            url = match.group(2).strip()
            number = self.get_number(url)
            if number:
                return f"{link_text} [{number}]"
            return match.group(0)

        return pattern.sub(_replace, text)

    def bibliography(
        self,
        fmt: str | BibliographyFormat = BibliographyFormat.MARKDOWN,
    ) -> str:
        """
        Generate formatted bibliography.

        Args:
            fmt: Output format.

        Returns:
            Formatted bibliography string.
        """
        if isinstance(fmt, str):
            try:
                fmt = BibliographyFormat(fmt)
            except ValueError:
                fmt = BibliographyFormat.MARKDOWN

        if not self._citations:
            return ""

        format_methods: dict[BibliographyFormat, Callable[[Citation], str]] = {
            BibliographyFormat.MARKDOWN: lambda c: c.to_markdown_ref(),
            BibliographyFormat.APA: lambda c: c.to_apa_ref(),
            BibliographyFormat.PLAIN: lambda c: c.to_plain_ref(),
            BibliographyFormat.BIBTEX: lambda c: c.to_bibtex_ref(),
        }

        if fmt == BibliographyFormat.JSON:
            import json

            return json.dumps(
                [c.to_dict() for c in self._citations],
                ensure_ascii=False,
                indent=2,
            )

        formatter = format_methods.get(fmt, format_methods[BibliographyFormat.MARKDOWN])
        return "\n".join(formatter(c) for c in self._citations)

    def clear(self) -> None:
        """Remove all citations."""
        self._citations.clear()
        self._url_map.clear()
        self._next_number = 1

    def merge(self, other: CitationManager) -> None:
        """Merge citations from another manager."""
        for c in other.citations:
            self.add(
                url=c.url,
                title=c.title,
                text=c.text,
                context=c.context,
                source=c.source,
            )

    def to_result(self) -> CitationResult:
        """Convert to a CitationResult."""
        return CitationResult(
            citations=list(self._citations),
            bibliography=self.bibliography(),
            total_references=sum(c.appears_count for c in self._citations),
        )

    def __len__(self) -> int:
        return len(self._citations)

    def __repr__(self) -> str:
        return f"CitationManager(count={self.count})"
