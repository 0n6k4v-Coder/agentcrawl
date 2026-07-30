"""
AgentCrawl — JSON XPath Extractor
=====================================

XPath expression-based structured data extraction. Defines a schema
using XPath expressions to extract fields from HTML elements without
requiring LLM calls.

Ideal for:
    - Complex HTML structures where CSS selectors are insufficient
    - Extracting data based on element relationships (parent, sibling)
    - Conditional extraction (contains, starts-with, etc.)
    - Pages with inconsistent class names but stable structure

Schema Format:
    {
        "name": "Product Listing",
        "baseXPath": "//div[@class='product-card']",
        "fields": [
            {"name": "title", "xpath": ".//h2[@class='title']", "type": "text"},
            {"name": "price", "xpath": ".//span[@class='price']", "type": "text"},
            {"name": "url", "xpath": ".//a", "type": "attribute", "attribute": "href"},
            {"name": "image", "xpath": ".//img", "type": "attribute", "attribute": "src"},
            {
                "name": "reviews",
                "xpath": ".//div[@class='review']",
                "type": "list",
                "fields": [
                    {"name": "author", "xpath": ".//span[@class='author']", "type": "text"},
                    {"name": "rating", "xpath": ".//span[@class='rating']", "type": "text"},
                ]
            }
        ]
    }

Usage:
    from agentcrawl.extraction.json_xpath import JsonXPathExtractor

    schema = {
        "name": "Product",
        "baseXPath": "//div[@class='product']",
        "fields": [
            {"name": "title", "xpath": ".//h1", "type": "text"},
            {"name": "price", "xpath": ".//span[contains(@class, 'price')]", "type": "text"},
            {"name": "url", "xpath": ".//a", "type": "attribute", "attribute": "href"},
        ]
    }

    extractor = JsonXPathExtractor(schema=schema)
    result = await extractor.extract(html=html_content)
    print(result.data)

    # Single item extraction
    schema = {
        "name": "Article",
        "fields": [
            {"name": "title", "xpath": "//h1", "type": "text"},
            {"name": "author", "xpath": "//span[@class='author']", "type": "text"},
            {"name": "date", "xpath": "//time/@datetime", "type": "text"},
        ]
    }
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionStrategy,
)

logger = logging.getLogger("agentcrawl.extraction.json_xpath")


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
# JSON XPath Extractor
# ══════════════════════════════════════════════════════════════


class JsonXPathExtractor(ExtractionStrategy):
    """
    XPath expression-based structured data extraction.

    Uses a declarative schema with XPath expressions to extract
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
        ...     "baseXPath": "//div[@class='product']",
        ...     "fields": [
        ...         {"name": "title", "xpath": ".//h2", "type": "text"},
        ...         {"name": "price", "xpath": ".//span[@class='price']", "type": "text"},
        ...     ]
        ... }
        >>> extractor = JsonXPathExtractor(schema=schema)
        >>> result = await extractor.extract(html=html)
        >>> print(result.data)
    """

    method_name = "xpath"

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
            if "xpath" not in field_def and field_def.get("type") != "nested":
                raise ValueError(f"Field '{field_def.get('name')}' missing 'xpath'")

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
        Extract structured data using XPath expressions.

        Args:
            html: HTML content.
            markdown: Markdown content (unused).
            url: Source URL.

        Returns:
            Extracted data (dict or list of dicts).
        """
        if not self._schema:
            raise ValueError("No schema provided for XPath extraction")

        if not html.strip():
            return [] if self._schema.get("baseXPath") else {}

        try:
            from lxml import html as lxml_html
        except ImportError as err:
            raise ImportError(
                "lxml is required for XPath extraction. Install with: pip install lxml"
            ) from err

        try:
            tree = lxml_html.document_fromstring(html)
        except Exception as e:
            logger.error("HTML parse error: %s", e)
            return [] if self._schema.get("baseXPath") else {}

        base_xpath = self._schema.get("baseXPath", "")
        fields = self._schema.get("fields", [])

        if base_xpath:
            # Multiple items: extract from each matching element
            try:
                elements = tree.xpath(base_xpath)
            except Exception as e:
                logger.error("Base XPath error '%s': %s", base_xpath, e)
                return []

            results: list[dict[str, Any]] = []
            for element in elements:
                item = self._extract_fields(element, fields)
                if item:
                    results.append(item)

            return results

        else:
            # Single item: extract from the whole document
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
                    name,
                    e,
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
        xpath = field_def.get("xpath", "")
        default = field_def.get("default", self._default_value)

        # Handle nested type (no xpath — use current element)
        if field_type == FIELD_TYPE_NESTED:
            nested_fields = field_def.get("fields", [])
            return self._extract_fields(element, nested_fields)

        # Evaluate XPath
        target = element if not xpath else self._xpath_one(element, xpath)

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
            return self._extract_text(target, field_def)

    # ──────────────────────────────────────────────────────────
    # XPath Helpers
    # ──────────────────────────────────────────────────────────

    def _xpath_one(self, element: Any, xpath: str) -> Any | None:
        """
        Evaluate an XPath expression and return the first result.

        Handles both element results and string/attribute results.

        Args:
            element: Context element.
            xpath: XPath expression.

        Returns:
            First result, or None.
        """
        try:
            results = element.xpath(xpath)
            if not results:
                return None

            first = results[0]

            # If result is a string (from @attr or text()), wrap it
            if isinstance(first, str):
                return _XPathStringResult(first)

            return first

        except Exception as e:
            logger.debug("XPath error '%s': %s", xpath, e)
            return None

    def _xpath_all(self, element: Any, xpath: str) -> list[Any]:
        """
        Evaluate an XPath expression and return all results.

        Args:
            element: Context element.
            xpath: XPath expression.

        Returns:
            List of results.
        """
        try:
            results = element.xpath(xpath)
            return results if results else []
        except Exception as e:
            logger.debug("XPath error '%s': %s", xpath, e)
            return []

    # ──────────────────────────────────────────────────────────
    # Value Extraction
    # ──────────────────────────────────────────────────────────

    def _extract_text(
        self,
        target: Any,
        field_def: dict[str, Any],
    ) -> str:
        """Extract text content from a target."""
        # Handle string results (from @attr or text() XPath)
        if isinstance(target, _XPathStringResult):
            text = target.value
        elif isinstance(target, str):
            text = target
        elif hasattr(target, "text_content"):
            text = target.text_content()
        else:
            text = str(target)

        if self._strip_whitespace:
            text = text.strip()
            text = re.sub(r"\s+", " ", text)

        # Apply transform
        transform = field_def.get("transform")
        if transform:
            text = self._apply_transform(text, transform)

        return text

    def _extract_html(self, target: Any) -> str:
        """Extract inner HTML from a target."""
        if isinstance(target, _XPathStringResult):
            return target.value

        try:
            from lxml.html import tostring

            return str(tostring(target, encoding="unicode", method="html"))
        except Exception:
            if hasattr(target, "text_content"):
                return str(target.text_content())
            return str(target)

    def _extract_attribute(
        self,
        target: Any,
        field_def: dict[str, Any],
    ) -> str:
        """Extract an attribute value from a target."""
        attr_name = field_def.get("attribute", "")

        # If target is already a string result (from @attr XPath)
        if isinstance(target, _XPathStringResult):
            value = target.value
        elif attr_name and hasattr(target, "get"):
            value = target.get(attr_name, "")
        else:
            value = ""

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
            field_def: Field definition with 'xpath' and 'fields'.

        Returns:
            List of extracted items.
        """
        xpath = field_def.get("xpath", "")
        sub_fields = field_def.get("fields", [])

        if not xpath:
            return []

        elements = self._xpath_all(element, xpath)
        items: list[Any] = []

        for el in elements:
            if sub_fields:
                item = self._extract_fields(el, sub_fields)
                if item:
                    items.append(item)
            else:
                # Simple text extraction
                if isinstance(el, str):
                    text = el.strip()
                elif hasattr(el, "text_content"):
                    text = el.text_content().strip()
                else:
                    text = str(el).strip()

                if text:
                    items.append(text)

        return items

    def _extract_regex(
        self,
        target: Any,
        field_def: dict[str, Any],
    ) -> str:
        """Extract text using a regex pattern."""
        if isinstance(target, _XPathStringResult):
            text = target.value
        elif hasattr(target, "text_content"):
            text = target.text_content()
        else:
            text = str(target)

        pattern = field_def.get("pattern", "")
        if not pattern:
            return text.strip()

        try:
            match = re.search(pattern, text)
            if match:
                if match.groups():
                    return match.group(1).strip()
                return match.group(0).strip()
        except re.error as e:
            logger.debug("Regex error '%s': %s", pattern, e)

        return str(field_def.get("default", self._default_value))

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
                return str(transform["prefix"]) + value

            if "suffix" in transform:
                return value + str(transform["suffix"])

            if "split" in transform:
                delimiter = transform["split"]
                index = transform.get("index", 0)
                parts = value.split(delimiter)
                if 0 <= index < len(parts):
                    return str(parts[index]).strip()
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
        d.update(
            {
                "default_value": self._default_value,
                "strip_whitespace": self._strip_whitespace,
                "raise_on_missing": self._raise_on_missing,
                "schema_name": self._schema.get("name", "") if self._schema else "",
                "base_xpath": self._schema.get("baseXPath", "") if self._schema else "",
                "field_count": len(self._schema.get("fields", [])) if self._schema else 0,
            }
        )
        return d

    def __repr__(self) -> str:
        schema_name = self._schema.get("name", "unnamed") if self._schema else "none"
        base = self._schema.get("baseXPath", "") if self._schema else ""
        return f"JsonXPathExtractor(schema={schema_name!r}, base='{base}')"


# ══════════════════════════════════════════════════════════════
# Helper: XPath String Result Wrapper
# ══════════════════════════════════════════════════════════════


class _XPathStringResult:
    """
    Wrapper for XPath string results (from @attr or text() expressions).

    lxml returns plain strings for attribute/text XPath results,
    which can't be distinguished from element results. This wrapper
    provides a consistent interface.
    """

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def text_content(self) -> str:
        return self.value

    def get(self, attr: str, default: str = "") -> str:
        return default

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"_XPathStringResult({self.value!r})"
