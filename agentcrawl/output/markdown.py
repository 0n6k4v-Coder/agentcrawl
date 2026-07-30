"""
AgentCrawl — Markdown Output Formatter
==========================================

Formats crawl results as structured Markdown output with optional
YAML front matter, citations, links, and chunk sections.

Features:
    - Clean Markdown content output
    - YAML front matter with metadata
    - Citation bibliography section
    - Link list section
    - Chunk output section
    - Template-based rendering
    - Configurable section inclusion
    - File output

Usage:
    from agentcrawl.output.markdown import MarkdownOutputFormatter

    formatter = MarkdownOutputFormatter()
    md = formatter.format(result)
    print(md)

    # With front matter and citations
    formatter = MarkdownOutputFormatter(
        include_front_matter=True,
        include_citations=True,
        include_links=True,
    )
    md = formatter.format(result)

    # Custom template
    formatter = MarkdownOutputFormatter(
        template="# {{title}}\\n\\n{{content}}\\n\\n---\\n{{citations}}",
    )
    md = formatter.format(result)

    # Save to file
    formatter.save(result, "output.md")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("agentcrawl.output.markdown")


# ══════════════════════════════════════════════════════════════
# Markdown Output Formatter
# ══════════════════════════════════════════════════════════════


class MarkdownOutputFormatter:
    """
    Formats crawl results as structured Markdown output.

    Args:
        include_front_matter: Include YAML front matter with metadata.
        include_metadata: Include metadata section.
        include_links: Include links section.
        include_citations: Include citations/bibliography section.
        include_chunks: Include chunks section.
        include_stats: Include word/token count stats.
        template: Custom template string.
        citation_format: Citation bibliography format ('markdown', 'apa', 'plain').
        link_format: Link list format ('markdown', 'plain').
        front_matter_fields: Fields to include in front matter.
        separator: Section separator string.

    Example:
        >>> formatter = MarkdownOutputFormatter(
        ...     include_front_matter=True,
        ...     include_citations=True,
        ... )
        >>> md = formatter.format(crawl_result)
        >>> print(md)
    """

    DEFAULT_TEMPLATE = """\
{{front_matter}}
{{content}}
{{metadata_section}}
{{links_section}}
{{citations_section}}
{{chunks_section}}
{{stats_section}}"""

    def __init__(
        self,
        include_front_matter: bool = False,
        include_metadata: bool = False,
        include_links: bool = False,
        include_citations: bool = True,
        include_chunks: bool = False,
        include_stats: bool = False,
        template: str | None = None,
        citation_format: str = "markdown",
        link_format: str = "markdown",
        front_matter_fields: list[str] | None = None,
        separator: str = "\n\n---\n\n",
    ):
        self._include_front_matter = include_front_matter
        self._include_metadata = include_metadata
        self._include_links = include_links
        self._include_citations = include_citations
        self._include_chunks = include_chunks
        self._include_stats = include_stats
        self._template = template or self.DEFAULT_TEMPLATE
        self._citation_format = citation_format
        self._link_format = link_format
        self._front_matter_fields = front_matter_fields or [
            "title",
            "url",
            "description",
            "author",
            "date",
        ]
        self._separator = separator

    # ──────────────────────────────────────────────────────────
    # Formatting
    # ──────────────────────────────────────────────────────────

    def format(self, result: Any) -> str:
        """
        Format a CrawlResult as Markdown.

        Args:
            result: CrawlResult instance.

        Returns:
            Formatted Markdown string.
        """
        # Build each section
        front_matter = ""
        if self._include_front_matter:
            front_matter = self._build_front_matter(result)

        content = self._get_content(result)

        metadata_section = ""
        if self._include_metadata:
            metadata_section = self._build_metadata_section(result)

        links_section = ""
        if self._include_links:
            links_section = self._build_links_section(result)

        citations_section = ""
        if self._include_citations:
            citations_section = self._build_citations_section(result)

        chunks_section = ""
        if self._include_chunks:
            chunks_section = self._build_chunks_section(result)

        stats_section = ""
        if self._include_stats:
            stats_section = self._build_stats_section(result)

        # Render template
        output = self._template
        output = output.replace("{{front_matter}}", front_matter)
        output = output.replace("{{content}}", content)
        output = output.replace("{{metadata_section}}", metadata_section)
        output = output.replace("{{links_section}}", links_section)
        output = output.replace("{{citations_section}}", citations_section)
        output = output.replace("{{chunks_section}}", chunks_section)
        output = output.replace("{{stats_section}}", stats_section)

        # Clean up excessive blank lines
        output = self._cleanup(output)

        return output.strip()

    def format_content_only(self, result: Any) -> str:
        """
        Format only the main content (no sections).

        Args:
            result: CrawlResult instance.

        Returns:
            Markdown content string.
        """
        return self._get_content(result).strip()

    # ──────────────────────────────────────────────────────────
    # Section Builders
    # ──────────────────────────────────────────────────────────

    def _get_content(self, result: Any) -> str:
        """Get the main Markdown content from a result."""
        # Try markdown field
        markdown = getattr(result, "markdown", "")
        if markdown:
            return markdown

        # Try text field
        text = getattr(result, "text", "")
        if text:
            return text

        # Try extracted data
        extracted = getattr(result, "extracted_data", None)
        if extracted:
            if isinstance(extracted, dict):
                return self._dict_to_markdown(extracted)
            elif isinstance(extracted, list):
                return self._list_to_markdown(extracted)
            return str(extracted)

        return ""

    def _build_front_matter(self, result: Any) -> str:
        """Build YAML front matter from metadata."""
        metadata = getattr(result, "metadata", {}) or {}
        url = getattr(result, "url", "")

        lines: list[str] = ["---"]

        for field_name in self._front_matter_fields:
            value = metadata.get(field_name, "")
            if not value and field_name == "url":
                value = url

            if value:
                # Escape YAML special characters
                value_str = str(value).replace('"', '\\"')
                lines.append(f'{field_name}: "{value_str}"')

        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    def _build_metadata_section(self, result: Any) -> str:
        """Build a metadata section."""
        metadata = getattr(result, "metadata", {}) or {}
        if not metadata:
            return ""

        lines: list[str] = [
            self._separator,
            "## Metadata",
            "",
        ]

        for key, value in metadata.items():
            if value and key != "extra":
                lines.append(f"- **{key}**: {value}")

        lines.append("")
        return "\n".join(lines)

    def _build_links_section(self, result: Any) -> str:
        """Build a links section."""
        links = getattr(result, "links", {}) or {}
        if not links:
            return ""

        lines: list[str] = [
            self._separator,
            "## Links",
            "",
        ]

        # Internal links
        internal = links.get("internal", [])
        if internal:
            lines.append(f"### Internal ({len(internal)})")
            lines.append("")
            for link in internal[:50]:  # Limit to 50
                url = link.get("url", "")
                text = link.get("text", url)
                if self._link_format == "markdown":
                    lines.append(f"- [{text}]({url})")
                else:
                    lines.append(f"- {text}: {url}")
            lines.append("")

        # External links
        external = links.get("external", [])
        if external:
            lines.append(f"### External ({len(external)})")
            lines.append("")
            for link in external[:50]:
                url = link.get("url", "")
                text = link.get("text", url)
                if self._link_format == "markdown":
                    lines.append(f"- [{text}]({url})")
                else:
                    lines.append(f"- {text}: {url}")
            lines.append("")

        return "\n".join(lines)

    def _build_citations_section(self, result: Any) -> str:
        """Build a citations/bibliography section."""
        citations = getattr(result, "citations", []) or []
        if not citations:
            return ""

        lines: list[str] = [
            self._separator,
            "## References",
            "",
        ]

        for citation in citations:
            number = citation.get("number", 0)
            url = citation.get("url", "")
            title = citation.get("title", "") or citation.get("text", url)
            domain = citation.get("domain", "")

            if self._citation_format == "markdown":
                lines.append(f"[{number}] [{title}]({url})")
            elif self._citation_format == "apa":
                lines.append(f"{title}. {domain}. {url}")
            else:  # plain
                lines.append(f"[{number}] {title} - {url}")

        lines.append("")
        return "\n".join(lines)

    def _build_chunks_section(self, result: Any) -> str:
        """Build a chunks section."""
        chunks = getattr(result, "chunks", []) or []
        if not chunks:
            return ""

        lines: list[str] = [
            self._separator,
            f"## Chunks ({len(chunks)})",
            "",
        ]

        for chunk in chunks:
            index = chunk.get("index", 0)
            heading = chunk.get("heading", "")
            token_count = chunk.get("token_count", 0)
            text = chunk.get("text", "")

            header = f"### Chunk {index}"
            if heading:
                header += f": {heading}"
            header += f" ({token_count} tokens)"

            lines.append(header)
            lines.append("")
            # Truncate long chunks for display
            if len(text) > 500:
                lines.append(text[:500] + "...")
            else:
                lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def _build_stats_section(self, result: Any) -> str:
        """Build a statistics section."""
        word_count = getattr(result, "word_count", 0)
        token_count = getattr(result, "token_count", 0)
        response_time = getattr(result, "response_time_ms", 0)
        cached = getattr(result, "cached", False)
        status_code = getattr(result, "status_code", 0)

        lines: list[str] = [
            self._separator,
            "## Statistics",
            "",
            f"- **Words**: {word_count:,}",
            f"- **Tokens**: {token_count:,}",
            f"- **Response time**: {response_time:.0f}ms",
            f"- **Status code**: {status_code}",
            f"- **Cached**: {'Yes' if cached else 'No'}",
            "",
        ]

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _dict_to_markdown(data: dict[str, Any]) -> str:
        """Convert a dictionary to Markdown key-value list."""
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"- **{key}**:")
                if isinstance(value, dict):
                    for k, v in value.items():
                        lines.append(f"  - {k}: {v}")
                else:
                    for item in value:
                        lines.append(f"  - {item}")
            else:
                lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)

    @staticmethod
    def _list_to_markdown(data: list[Any]) -> str:
        """Convert a list to Markdown bullet list."""
        lines: list[str] = []
        for item in data:
            if isinstance(item, dict):
                parts = [f"{k}: {v}" for k, v in item.items()]
                lines.append(f"- {', '.join(parts)}")
            else:
                lines.append(f"- {item}")
        return "\n".join(lines)

    @staticmethod
    def _cleanup(text: str) -> str:
        """Clean up excessive whitespace and separators."""
        import re

        # Remove multiple consecutive separators
        text = re.sub(r"(\n---\n){2,}", "\n---\n", text)

        # Remove excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Remove leading/trailing whitespace per line
        lines = [line.rstrip() for line in text.split("\n")]
        text = "\n".join(lines)

        return text

    # ──────────────────────────────────────────────────────────
    # File Output
    # ──────────────────────────────────────────────────────────

    def save(self, result: Any, filepath: str) -> None:
        """
        Save formatted Markdown to a file.

        Args:
            result: CrawlResult instance.
            filepath: Output file path.
        """
        md = self.format(result)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md)

    def save_batch(
        self,
        results: list[Any],
        directory: str,
        filename_template: str = "{index:04d}_{url_slug}.md",
    ) -> list[str]:
        """
        Save multiple results to individual Markdown files.

        Args:
            results: List of CrawlResult instances.
            directory: Output directory.
            filename_template: Filename template with {index} and {url_slug}.

        Returns:
            List of created file paths.
        """
        import os
        import re

        os.makedirs(directory, exist_ok=True)
        paths: list[str] = []

        for i, result in enumerate(results):
            url = getattr(result, "url", f"page_{i}")

            # Create URL slug
            url_slug = re.sub(r"[^\w-]", "_", url.split("//")[-1])[:50]

            filename = filename_template.format(
                index=i,
                url_slug=url_slug,
            )
            filepath = os.path.join(directory, filename)

            self.save(result, filepath)
            paths.append(filepath)

        return paths

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_front_matter": self._include_front_matter,
            "include_metadata": self._include_metadata,
            "include_links": self._include_links,
            "include_citations": self._include_citations,
            "include_chunks": self._include_chunks,
            "include_stats": self._include_stats,
            "citation_format": self._citation_format,
            "link_format": self._link_format,
        }

    def __repr__(self) -> str:
        sections = []
        if self._include_front_matter:
            sections.append("front_matter")
        if self._include_metadata:
            sections.append("metadata")
        if self._include_links:
            sections.append("links")
        if self._include_citations:
            sections.append("citations")
        if self._include_chunks:
            sections.append("chunks")
        if self._include_stats:
            sections.append("stats")

        return f"MarkdownOutputFormatter(sections=[{', '.join(sections) or 'content_only'}])"
