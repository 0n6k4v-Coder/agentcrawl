"""
AgentCrawl — Regex Extractor
================================

Regular expression-based structured data extraction. Defines a
schema using regex patterns to extract fields from text content
without requiring LLM calls or HTML parsing.

Ideal for:
    - Extracting data from unstructured text
    - Parsing log files, emails, or plain text content
    - Extracting prices, dates, emails, phone numbers
    - Simple pattern-based extraction from HTML text content
    - Fast, deterministic extraction (no LLM cost)

Schema Format:
    {
        "name": "Contact Info",
        "fields": [
            {
                "name": "email",
                "pattern": r"[\\w.+-]+@[\\w-]+\\.[\\w.]+",
                "type": "first"
            },
            {
                "name": "phone",
                "pattern": r"\\+?[\\d\\s\\-\\(\\)]{10,}",
                "type": "first"
            },
            {
                "name": "price",
                "pattern": r"\\$([\\d,]+\\.?\\d*)",
                "type": "first",
                "group": 1
            },
            {
                "name": "tags",
                "pattern": r"#(\\w+)",
                "type": "all",
                "group": 1
            }
        ]
    }

Usage:
    from agentcrawl.extraction.regex import RegexExtractor

    schema = {
        "name": "Product",
        "fields": [
            {"name": "price", "pattern": r"\\$([\\d.]+)", "type": "first", "group": 1},
            {"name": "sku", "pattern": r"SKU:\\s*([\\w-]+)", "type": "first", "group": 1},
            {"name": "tags", "pattern": r"#(\\w+)", "type": "all", "group": 1},
        ]
    }

    extractor = RegexExtractor(schema=schema)
    result = await extractor.extract(html=html_content)
    print(result.data)

    # Simple pattern extraction (no schema)
    extractor = RegexExtractor(
        patterns={
            "emails": r"[\\w.+-]+@[\\w-]+\\.[\\w.]+",
            "urls": r"https?://[^\\s]+",
        }
    )
    result = await extractor.extract(markdown=text_content)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionStrategy,
)

logger = logging.getLogger("agentcrawl.extraction.regex")


# ══════════════════════════════════════════════════════════════
# Field Types
# ══════════════════════════════════════════════════════════════

FIELD_TYPE_FIRST = "first"  # First match only
FIELD_TYPE_ALL = "all"  # All matches (list)
FIELD_TYPE_NAMED = "named"  # Named groups → dict


# ══════════════════════════════════════════════════════════════
# Regex Extractor
# ══════════════════════════════════════════════════════════════


class RegexExtractor(ExtractionStrategy):
    """
    Regular expression-based structured data extraction.

    Uses regex patterns defined in a schema to extract fields
    from text content. Supports first match, all matches, and
    named group extraction.

    Args:
        schema: Extraction schema with regex patterns.
        patterns: Simple dict of {field_name: pattern} (alternative to schema).
        config: Extraction configuration.
        default_value: Default value for missing fields.
        strip_whitespace: Strip whitespace from extracted values.
        source: Content source to search ('html', 'markdown', 'text', 'all').
        flags: Regex flags (default: re.IGNORECASE | re.MULTILINE).

    Example:
        >>> schema = {
        ...     "name": "Contact",
        ...     "fields": [
        ...         {"name": "email", "pattern": r"[\\w.+-]+@[\\w-]+\\.[\\w.]+", "type": "first"},
        ...         {"name": "phones", "pattern": r"\\+?[\\d\\s\\-]{10,}", "type": "all"},
        ...     ]
        ... }
        >>> extractor = RegexExtractor(schema=schema)
        >>> result = await extractor.extract(markdown=text)
        >>> print(result.data)
    """

    method_name = "regex"

    def __init__(
        self,
        schema: dict[str, Any] | None = None,
        patterns: dict[str, str] | None = None,
        config: ExtractionConfig | None = None,
        default_value: Any = None,
        strip_whitespace: bool = True,
        source: str = "all",
        flags: int = re.IGNORECASE | re.MULTILINE,
        **kwargs: Any,
    ):
        super().__init__(schema=schema, config=config)

        self._default_value = default_value
        self._strip_whitespace = strip_whitespace
        self._source = source
        self._flags = flags

        # Build field definitions from schema or patterns
        self._fields: list[dict[str, Any]] = []

        if schema and "fields" in schema:
            self._fields = schema["fields"]
            self._validate_fields(self._fields)
        elif patterns:
            # Convert simple patterns dict to field definitions
            for name, pattern in patterns.items():
                self._fields.append(
                    {
                        "name": name,
                        "pattern": pattern,
                        "type": FIELD_TYPE_ALL,
                    }
                )

        # Pre-compile patterns
        self._compiled: dict[str, re.Pattern[str]] = {}
        self._compile_patterns()

    # ──────────────────────────────────────────────────────────
    # Validation & Compilation
    # ──────────────────────────────────────────────────────────

    def _validate_fields(self, fields: list[dict[str, Any]]) -> None:
        """Validate field definitions."""
        for field_def in fields:
            if not isinstance(field_def, dict):
                raise ValueError(f"Field definition must be a dict: {field_def}")
            if "name" not in field_def:
                raise ValueError(f"Field missing 'name': {field_def}")
            if "pattern" not in field_def:
                raise ValueError(f"Field '{field_def.get('name')}' missing 'pattern'")

    def _compile_patterns(self) -> None:
        """Pre-compile all regex patterns."""
        for field_def in self._fields:
            name = field_def.get("name", "")
            pattern = field_def.get("pattern", "")

            if not name or not pattern:
                continue

            try:
                self._compiled[name] = re.compile(pattern, self._flags)
            except re.error as err:
                raise ValueError(f"Invalid regex pattern for field '{name}': {err}") from err

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
        Extract structured data using regex patterns.

        Args:
            html: HTML content.
            markdown: Markdown content.
            url: Source URL.

        Returns:
            Dictionary of extracted field values.
        """
        # Build search text based on source preference
        search_text = self._build_search_text(html, markdown)

        if not search_text.strip():
            return {}

        # Extract each field
        result: dict[str, Any] = {}

        for field_def in self._fields:
            name = field_def.get("name", "")
            if not name:
                continue

            try:
                value = self._extract_field(search_text, field_def)
                result[name] = value
            except Exception as e:
                logger.debug("Field '%s' extraction error: %s", name, e)
                result[name] = field_def.get("default", self._default_value)

        return result

    def _build_search_text(self, html: str, markdown: str) -> str:
        """
        Build the text to search based on source preference.

        Args:
            html: HTML content.
            markdown: Markdown content.

        Returns:
            Combined search text.
        """
        if self._source == "html":
            return html
        elif self._source == "markdown":
            return markdown
        elif self._source == "text":
            # Strip HTML tags for plain text search
            if html:
                return re.sub(r"<[^>]+>", " ", html)
            return markdown
        else:  # "all"
            # Combine both, preferring markdown
            parts = []
            if markdown:
                parts.append(markdown)
            if html:
                # Strip tags from HTML to avoid matching tag attributes
                text = re.sub(r"<[^>]+>", " ", html)
                parts.append(text)
            return "\n".join(parts)

    # ──────────────────────────────────────────────────────────
    # Field Extraction
    # ──────────────────────────────────────────────────────────

    def _extract_field(
        self,
        text: str,
        field_def: dict[str, Any],
    ) -> Any:
        """
        Extract a single field using its regex pattern.

        Args:
            text: Search text.
            field_def: Field definition.

        Returns:
            Extracted value.
        """
        name = field_def.get("name", "")
        field_type = field_def.get("type", FIELD_TYPE_FIRST)
        group = field_def.get("group", 0)
        default = field_def.get("default", self._default_value)
        transform = field_def.get("transform")

        compiled = self._compiled.get(name)
        if compiled is None:
            return default

        if field_type == FIELD_TYPE_FIRST:
            return self._extract_first(compiled, text, group, default, transform)

        elif field_type == FIELD_TYPE_ALL:
            return self._extract_all(compiled, text, group, default, transform)

        elif field_type == FIELD_TYPE_NAMED:
            return self._extract_named(compiled, text, default, transform)

        else:
            return self._extract_first(compiled, text, group, default, transform)

    def _extract_first(
        self,
        pattern: re.Pattern[str],
        text: str,
        group: int,
        default: Any,
        transform: Any = None,
    ) -> Any:
        """Extract the first match."""
        match = pattern.search(text)
        if not match:
            return default

        try:
            value = match.group(group)
        except (IndexError, error):
            return default

        if value is None:
            return default

        if self._strip_whitespace and isinstance(value, str):
            value = value.strip()

        if transform:
            value = self._apply_transform(value, transform)

        return value

    def _extract_all(
        self,
        pattern: re.Pattern[str],
        text: str,
        group: int,
        default: Any,
        transform: Any = None,
    ) -> list[Any]:
        """Extract all matches."""
        matches = pattern.finditer(text)
        results: list[Any] = []

        for match in matches:
            try:
                value = match.group(group)
            except (IndexError, error):
                continue

            if value is None:
                continue

            if self._strip_whitespace and isinstance(value, str):
                value = value.strip()

            if transform:
                value = self._apply_transform(value, transform)

            results.append(value)

        return results if results else (default if default is not None else [])

    def _extract_named(
        self,
        pattern: re.Pattern[str],
        text: str,
        default: Any,
        transform: Any = None,
    ) -> dict[str, str]:
        """Extract named groups as a dictionary."""
        match = pattern.search(text)
        if not match:
            return default if isinstance(default, dict) else {}

        result = match.groupdict()

        if self._strip_whitespace:
            result = {
                k: v.strip() if isinstance(v, str) else v
                for k, v in result.items()
                if v is not None
            }

        if transform:
            result = {
                k: self._apply_transform(v, transform) if isinstance(v, str) else v
                for k, v in result.items()
            }

        return result

    # ──────────────────────────────────────────────────────────
    # Transforms
    # ┐─────────────────────────────────────────────────────────

    @staticmethod
    def _apply_transform(value: str, transform: str | dict[str, Any]) -> str:
        """
        Apply a transform to an extracted value.

        Supported transforms:
            - "lowercase", "uppercase", "strip", "title"
            - {"regex": "pattern", "replacement": "rep"}
            - {"prefix": "..."}, {"suffix": "..."}
            - {"replace": {"old": "...", "new": "..."}}

        Args:
            value: Input value.
            transform: Transform specification.

        Returns:
            Transformed value.
        """
        if isinstance(transform, str):
            if transform == "lowercase":
                return value.lower()
            elif transform == "uppercase":
                return value.upper()
            elif transform in ("strip", "trim"):
                return value.strip()
            elif transform == "title":
                return value.title()

        elif isinstance(transform, dict):
            if "regex" in transform:
                pattern = transform["regex"]
                replacement = transform.get("replacement", "")
                try:
                    return re.sub(pattern, replacement, value)
                except re.error:
                    return value

            if "prefix" in transform:
                return str(transform["prefix"]) + value

            if "suffix" in transform:
                return value + str(transform["suffix"])

            if "replace" in transform:
                old = transform.get("old", "")
                new = transform.get("new", "")
                return value.replace(old, new)

        return value

    # ──────────────────────────────────────────────────────────
    # Utility Methods
    # ──────────────────────────────────────────────────────────

    def test_pattern(self, pattern: str, text: str) -> list[dict[str, Any]]:
        """
        Test a regex pattern against text.

        Args:
            pattern: Regex pattern string.
            text: Text to test against.

        Returns:
            List of match info dicts.
        """
        try:
            compiled = re.compile(pattern, self._flags)
        except re.error as e:
            return [{"error": str(e)}]

        results: list[dict[str, Any]] = []
        for match in compiled.finditer(text):
            results.append(
                {
                    "match": match.group(0),
                    "groups": list(match.groups()),
                    "named_groups": match.groupdict(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )

        return results

    def validate_patterns(self) -> list[dict[str, Any]]:
        """
        Validate all patterns in the schema.

        Returns:
            List of validation results per field.
        """
        results: list[dict[str, Any]] = []

        for field_def in self._fields:
            name = field_def.get("name", "")
            pattern = field_def.get("pattern", "")

            try:
                re.compile(pattern, self._flags)
                results.append(
                    {
                        "field": name,
                        "pattern": pattern,
                        "valid": True,
                        "error": None,
                    }
                )
            except re.error as e:
                results.append(
                    {
                        "field": name,
                        "pattern": pattern,
                        "valid": False,
                        "error": str(e),
                    }
                )

        return results

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "default_value": self._default_value,
                "strip_whitespace": self._strip_whitespace,
                "source": self._source,
                "field_count": len(self._fields),
                "fields": [
                    {
                        "name": f.get("name"),
                        "type": f.get("type", "first"),
                        "pattern": f.get("pattern", "")[:50],
                    }
                    for f in self._fields
                ],
            }
        )
        return d

    def __repr__(self) -> str:
        schema_name = self._schema.get("name", "unnamed") if self._schema else "patterns"
        return (
            f"RegexExtractor(schema={schema_name!r}, "
            f"fields={len(self._fields)}, "
            f"source={self._source!r})"
        )


# Import re.error for exception handling
from re import error  # noqa: E402
