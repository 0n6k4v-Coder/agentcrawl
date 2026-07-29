"""
AgentCrawl — JSON CSS Extractor
===================================

CSS selector-based structured data extraction. Defines a schema
using CSS selectors to extract fields from HTML elements without
requiring LLM calls.

Ideal for:
    - Extracting data from well-structured pages
    - Product listings, article metadata, profiles
    - Fast, deterministic extraction (no LLM cost)
    - Pages with consistent HTML structure

Schema Format:
    {
        "name": "Product Listing",
        "baseSelector": "div.product-card",
        "fields": [
            {"name": "title", "selector": "h2.title", "type": "text"},
            {"name": "price", "selector": "span.price", "type": "text"},
            {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "image", "selector": "img", "type": "attribute", "attribute": "src"},
            {
                "name": "reviews",
                "selector": "div.review",
                "type": "list",
                "fields": [
                    {"name": "author", "selector": "span.author", "type": "text"},
                    {"name": "rating", "selector": "span.rating", "type": "text"},
                ]
            }
        ]
    }

Usage:
    from agentcrawl.extraction.json_css import JsonCssExtractor

    schema = {
        "name": "Product",
        "baseSelector": "div.product",
        "fields": [
            {"name": "title", "selector": "h1", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
            {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
        ]
    }

    extractor = JsonCssExtractor(schema=schema)
    result = await extractor.extract(html=html_content)
    print(result.data)  # List of extracted products

    # Single item extraction (no baseSelector)
    schema = {
        "name": "Article",
        "fields": [
            {"name": "title", "selector": "h1", "type": "text"},
            {"name": "author", "selector": ".author", "type": "text"},
            {"name": "date", "selector": "time", "type": "attribute", "attribute": "datetime"},
        ]
    }
    extractor = JsonCssExtractor(schema=schema)
    result = await extractor.extract(html=article_html)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionStrategy,
)

logger = logging.getLogger("agentcrawl.extraction.json_css")


# ══════════════════════════════════════════════════════════════
# Field Types
# ══════════════════════════════════════════════════════════════

FIELD_TYPE_TEXT = "text"
FIELD_TYPE_HTML = "html"
FIELD_TYPE_ATTRIBUTE = "attribute"
FIELD_TYPE_LIST = "list"
FIELD_TYPE_NESTED = "nested"
FIELD_TYPE_REGEX = "regex"


# ══════════════════════════════════════════════════════════════
# JSON CSS Extractor
# ══════════════════════════════════════════════════════════════

class JsonCssExtractor(ExtractionStrategy):
    """
    CSS selector-based structured data extraction.

    Uses a declarative schema with CSS selectors to extract
    fields from HTML elements. Supports nested objects, lists,
    attributes, and regex transforms.

    Args:
        schema: Extraction schema dictionary.
        config: Extraction configuration.
        default_value: Default value for missing fields.
        strip_whitespace: Strip whitespace from extracted text.
        raise_on_missing: Raise error if required fields are missing.

    Example:
        >>> schema = {
        ...     "name": "Product",
        ...     "baseSelector": "div.product",
        ...     "fields": [
        ...         {"name": "title", "selector": "h2", "type": "text"},
        ...         {"name": "price", "selector": ".price", "type": "text"},
        ...     ]
        ... }
        >>> extractor = JsonCssExtractor(schema=schema)
        >>> result = await extractor.extract(html=html)
        >>> print(result.data)
    """

    method_name = "css"

    def __init__(
        self,
        schema: dict[str, Any] | None = None,
        config: ExtractionConfig | None = None,
        default_value: Any = None,
        strip_whitespace: bool = True,
        raise_on_missing: bool = False,
        **kwargs: Any,
    ):
        super().__init__(schema=schema, config=config)

        self._default_value = default_value
        self._strip_whitespace = strip_whitespace
        self._raise_on_missing = raise_on_missing

        # Validate schema
        if schema:
            self._validate_schema(schema)

    # ──────────────────────────────────────────────────────────
    # Schema Validation
    # ──────────────────────────────────────────────────────────

    def _validate_schema(self, schema: dict[str, Any]) -> None:
        """Validate the extraction schema."""
        if not isinstance(schema, dict):
            raise ValueError("Schema must be a dictionary")

        fields = schema.get("fields", [])
        if not fields:
            logger.warning("Schema has no fields defined")

        for field_def in fields:
            if not isinstance(field_def, dict):
                raise ValueError(f"Field definition must be a dict: {field_def}")
            if "name" not in field_def:
                raise ValueError(f"Field missing 'name': {field_def}")
            if "selector" not in field_def and field_def.get("type") != "nested":
                raise ValueError(
                    f"Field '{field_def.get('name')}' missing 'selector'"
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
        Extract structured data using CSS selectors.

        Args:
            html: HTML content.
            markdown: Markdown content (unused).
            url: Source URL.

        Returns:
            Extracted data (dict or list of dicts).
        """
        if not self._schema:
            raise ValueError("No schema provided for CSS extraction")

        if not html.strip():
            return [] if self._schema.get("baseSelector") else {}

        try:
            from lxml import html as lxml_html
        except ImportError:
            raise ImportError(
                "lxml is required for CSS extraction. "
                "Install with: pip install lxml"
            )

        try:
            tree = lxml_html.document_fromstring(html)
        except Exception as e:
            logger.error("HTML parse error: %s", e)
            return [] if self._schema.get("baseSelector") else {}

        base_selector = self._schema.get("baseSelector", "")
        fields = self._schema.get("fields", [])

        if base_selector:
            # Multiple items: extract from each matching element
            try:
                from lxml.cssselect import CSSSelector
                css = CSSSelector(base_selector)
                elements = css(tree)
            except Exception as e:
                logger.error("Base selector error '%s': %s", base_selector, e)
                return []

            results: list[dict[str, Any]] = []
            for element in elements:
                item = self._extract_fields(element, fields)
                if item:
                    results.append(item)

            return results

        else:
            # Single item: extract from the whole document
            logger.debug("No baseSelector, extracting from whole document (tree type: %s)", type(tree))
            # Debug: check what elements exist
            from lxml.cssselect import CSSSelector
            try:
                h1_css = CSSSelector("h1")
                h1_matches = h1_css(tree)
                logger.debug(f"h1 selector matched {len(h1_matches)} elements")
                if h1_matches:
                    logger.debug(f"First h1 text: {h1_matches[0].text_content()}")
            except Exception as e:
                logger.debug(f"h1 selector error: {e}")

            return self._extract_fields(tree, fields)

    # ──────────────────────────────────────────────────────────
    # Field Extraction
    # ──────────────────────────────────────────────────────────

    def _extract_fields(
        self,
        element: Any,
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Extract all fields from an element.

        Args:
            element: lxml element to extract from.
            fields: List of field definitions.

        Returns:
            Dictionary of extracted field values.
        """
        result: dict[str, Any] = {}

        for field_def in fields:
            name = field_def.get("name", "")
            if not name:
                continue

            try:
                value = self._extract_field(element, field_def)
                result[name] = value
            except Exception as e:
                logger.debug(
                    "Field '%s' extraction error: %s",
                    name, e,
                )
                result[name] = field_def.get("default", self._default_value)

        return result

    def _extract_field(
        self,
        element: Any,
        field_def: dict[str, Any],
    ) -> Any:
        """
        Extract a single field from an element.

        Args:
            element: lxml element.
            field_def: Field definition dict.

        Returns:
            Extracted value.
        """
        field_type = field_def.get("type", FIELD_TYPE_TEXT)
        selector = field_def.get("selector", "")
        default = field_def.get("default", self._default_value)

        # Handle nested type (no selector — use current element)
        if field_type == FIELD_TYPE_NESTED:
            nested_fields = field_def.get("fields", [])
            return self._extract_fields(element, nested_fields)

        # Find target element(s)
        if not selector:
            target = element
        else:
            target = self._select_one(element, selector)

        if target is None:
            return default

        # Extract based on type
        if field_type == FIELD_TYPE_TEXT:
            return self._extract_text(target, field_def)

        elif field_type == FIELD_TYPE_HTML:
            return self._extract_html(target)

        elif field_type == FIELD_TYPE_ATTRIBUTE:
            return self._extract_attribute(target, field_def)

        elif field_type == FIELD_TYPE_LIST:
            return self._extract_list(element, field_def)

        elif field_type == FIELD_TYPE_REGEX:
            return self._extract_regex(target, field_def)

        else:
            # Default to text
            return self._extract_text(target, field_def)

    def _select_one(self, element: Any, selector: str) -> Any | None:
        """Select the first matching element."""
        try:
            from lxml.cssselect import CSSSelector
            css = CSSSelector(selector)
            matches = css(element)
            logger.debug(f"Selector '{selector}' matched {len(matches)} elements")
            return matches[0] if matches else None
        except Exception as e:
            logger.debug("Selector error '%s': %s", selector, e)
            return None

    def _select_all(self, element: Any, selector: str) -> list[Any]:
        """Select all matching elements."""
        try:
            from lxml.cssselect import CSSSelector
            css = CSSSelector(selector)
            return css(element)
        except Exception as e:
            logger.debug("Selector error '%s': %s", selector, e)
            return []

    def _extract_text(
        self,
        element: Any,
        field_def: dict[str, Any],
    ) -> str:
        """Extract text content from an element."""
        text = element.text_content()

        if self._strip_whitespace:
            text = text.strip()
            # Collapse internal whitespace
            text = re.sub(r"\s+", " ", text)

        # Apply transform if specified
        transform = field_def.get("transform")
        if transform:
            text = self._apply_transform(text, transform)

        return text

    def _extract_html(self, element: Any) -> str:
        """Extract inner HTML from an element."""
        try:
            from lxml.html import tostring
            return tostring(element, encoding="unicode", method="html")
        except Exception:
            return element.text_content()

    def _extract_attribute(
        self,
        element: Any,
        field_def: dict[str, Any],
    ) -> str:
        """Extract an attribute value from an element."""
        attr_name = field_def.get("attribute", "")
        if not attr_name:
            return ""

        value = element.get(attr_name, "")

        if self._strip_whitespace and isinstance(value, str):
            value = value.strip()

        # Apply transform
        transform = field_def.get("transform")
        if transform and value:
            value = self._apply_transform(value, transform)

        return value

    def _extract_list(
        self,
        element: Any,
        field_def: dict[str, Any],
    ) -> list[Any]:
        """
        Extract a list of items from repeated elements.

        Args:
            element: Parent element.
            field_def: Field definition with 'selector' and 'fields'.

        Returns:
            List of extracted items.
        """
        selector = field_def.get("selector", "")
        sub_fields = field_def.get("fields", [])

        if not selector:
            return []

        elements = self._select_all(element, selector)
        items: list[Any] = []

        for el in elements:
            if sub_fields:
                item = self._extract_fields(el, sub_fields)
                if item:
                    items.append(item)
            else:
                # Simple text extraction
                text = el.text_content().strip()
                if text:
                    items.append(text)

        return items

    def _extract_regex(
        self,
        element: Any,
        field_def: dict[str, Any],
    ) -> str:
        """Extract text using a regex pattern."""
        text = element.text_content()
        pattern = field_def.get("pattern", "")

        if not pattern:
            return text.strip()

        try:
            match = re.search(pattern, text)
            if match:
                # Return first group if available, else full match
                if match.groups():
                    return match.group(1).strip()
                return match.group(0).strip()
        except re.error as e:
            logger.debug("Regex error '%s': %s", pattern, e)

        return field_def.get("default", self._default_value)

    # ──────────────────────────────────────────────────────────
    # Transforms
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _apply_transform(value: str, transform: str | dict[str, Any]) -> str:
        """
        Apply a transform to an extracted value.

        Supported transforms:
            - "lowercase": Convert to lowercase
            - "uppercase": Convert to uppercase
            - "strip": Strip whitespace
            - "trim": Alias for strip
            - {"regex": "pattern", "replacement": "rep"}: Regex replace
            - {"prefix": "..."}: Add prefix
            - {"suffix": "..."}: Add suffix
            - {"split": "delimiter", "index": N}: Split and take index

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
                return transform["prefix"] + value

            if "suffix" in transform:
                return value + transform["suffix"]

            if "split" in transform:
                delimiter = transform["split"]
                index = transform.get("index", 0)
                parts = value.split(delimiter)
                if 0 <= index < len(parts):
                    return parts[index].strip()
                return value

            if "replace" in transform:
                old = transform.get("old", "")
                new = transform.get("new", "")
                return value.replace(old, new)

        return value

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "default_value": self._default_value,
            "strip_whitespace": self._strip_whitespace,
            "raise_on_missing": self._raise_on_missing,
            "schema_name": self._schema.get("name", "") if self._schema else "",
            "base_selector": self._schema.get("baseSelector", "") if self._schema else "",
            "field_count": len(self._schema.get("fields", [])) if self._schema else 0,
        })
        return d

    def __repr__(self) -> str:
        schema_name = self._schema.get("name", "unnamed") if self._schema else "none"
        base = self._schema.get("baseSelector", "") if self._schema else ""
        return (
            f"JsonCssExtractor(schema={schema_name!r}, "
            f"base='{base}')"
        )
