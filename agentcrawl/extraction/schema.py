"""
AgentCrawl — Extraction Schema Utilities
============================================

Schema building, validation, conversion, and inference utilities
for structured data extraction. Provides a fluent builder API,
pre-built templates, and cross-format schema conversion.

Features:
    - SchemaBuilder: Fluent API for building extraction schemas
    - Schema validation and normalization
    - Cross-format conversion (Pydantic ↔ JSON Schema ↔ CSS ↔ XPath)
    - Schema inference from HTML structure
    - Pre-built templates (product, article, profile, etc.)
    - Field type definitions and constraints

Usage:
    from agentcrawl.extraction.schema import (
        SchemaBuilder,
        SchemaTemplate,
        SchemaConverter,
        SchemaValidator,
        infer_schema_from_html,
    )

    # Build a schema with the fluent API
    schema = (
        SchemaBuilder("Product")
        .base_selector("div.product-card")
        .field("title", selector="h2.title", type="text")
        .field("price", selector="span.price", type="text")
        .field("url", selector="a", type="attribute", attribute="href")
        .field("image", selector="img", type="attribute", attribute="src")
        .list_field("reviews", selector="div.review", fields=[
            {"name": "author", "selector": "span.author", "type": "text"},
            {"name": "rating", "selector": "span.stars", "type": "text"},
        ])
        .build()
    )

    # Use a pre-built template
    schema = SchemaTemplate.product()
    schema = SchemaTemplate.article()

    # Convert between formats
    converter = SchemaConverter()
    json_schema = converter.to_json_schema(pydantic_model)
    css_schema = converter.json_schema_to_css(json_schema)

    # Infer schema from HTML
    schema = infer_schema_from_html(html_content)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.extraction.schema")


# ══════════════════════════════════════════════════════════════
# Field Definitions
# ══════════════════════════════════════════════════════════════

@dataclass
class FieldDef:
    """
    Definition of a single extraction field.

    Attributes:
        name: Field name (output key).
        selector: CSS selector or XPath expression.
        type: Field type ('text', 'html', 'attribute', 'list', 'nested', 'regex').
        attribute: Attribute name (for 'attribute' type).
        pattern: Regex pattern (for 'regex' type).
        group: Regex group index (for 'regex' type).
        default: Default value if not found.
        required: Whether the field is required.
        transform: Transform to apply to the value.
        fields: Sub-fields (for 'list' and 'nested' types).
        description: Human-readable description.
    """
    name: str
    selector: str = ""
    type: str = "text"
    attribute: str = ""
    pattern: str = ""
    group: int = 0
    default: Any = None
    required: bool = False
    transform: str | dict[str, Any] | None = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
        }
        if self.selector:
            d["selector"] = self.selector
        if self.attribute:
            d["attribute"] = self.attribute
        if self.pattern:
            d["pattern"] = self.pattern
        if self.group:
            d["group"] = self.group
        if self.default is not None:
            d["default"] = self.default
        if self.required:
            d["required"] = True
        if self.transform:
            d["transform"] = self.transform
        if self.fields:
            d["fields"] = self.fields
        if self.description:
            d["description"] = self.description
        return d

    def to_json_schema_property(self) -> dict[str, Any]:
        """Convert to a JSON Schema property definition."""
        type_map = {
            "text": "string",
            "html": "string",
            "attribute": "string",
            "regex": "string",
            "list": "array",
            "nested": "object",
        }

        prop: dict[str, Any] = {
            "type": type_map.get(self.type, "string"),
        }

        if self.description:
            prop["description"] = self.description

        if self.default is not None:
            prop["default"] = self.default

        if self.type == "list" and self.fields:
            prop["items"] = {
                "type": "object",
                "properties": {
                    f["name"]: {"type": "string"}
                    for f in self.fields
                    if isinstance(f, dict) and "name" in f
                },
            }

        return prop


# ══════════════════════════════════════════════════════════════
# Schema Builder
# ══════════════════════════════════════════════════════════════

class SchemaBuilder:
    """
    Fluent builder for constructing extraction schemas.

    Supports building schemas for CSS, XPath, and regex extractors
    with a unified API.

    Args:
        name: Schema name.
        method: Extraction method ('css', 'xpath', 'regex').

    Example:
        >>> schema = (
        ...     SchemaBuilder("Product", method="css")
        ...     .base_selector("div.product")
        ...     .field("title", selector="h1", type="text")
        ...     .field("price", selector=".price", type="text", transform="strip")
        ...     .field("url", selector="a", type="attribute", attribute="href")
        ...     .list_field("images", selector="img", fields=[
        ...         {"name": "src", "selector": "img", "type": "attribute", "attribute": "src"},
        ...         {"name": "alt", "selector": "img", "type": "attribute", "attribute": "alt"},
        ...     ])
        ...     .build()
        ... )
    """

    def __init__(
        self,
        name: str = "Schema",
        method: str = "css",
    ):
        self._name = name
        self._method = method
        self._base_selector: str = ""
        self._fields: list[FieldDef] = []
        self._description: str = ""

    def base_selector(self, selector: str) -> SchemaBuilder:
        """Set the base selector for multi-item extraction."""
        self._base_selector = selector
        return self

    def description(self, desc: str) -> SchemaBuilder:
        """Set the schema description."""
        self._description = desc
        return self

    def field(
        self,
        name: str,
        selector: str = "",
        type: str = "text",
        attribute: str = "",
        pattern: str = "",
        group: int = 0,
        default: Any = None,
        required: bool = False,
        transform: str | dict[str, Any] | None = None,
        description: str = "",
    ) -> SchemaBuilder:
        """
        Add a field to the schema.

        Args:
            name: Field name.
            selector: CSS selector or XPath.
            type: Field type.
            attribute: Attribute name (for 'attribute' type).
            pattern: Regex pattern (for 'regex' type).
            group: Regex group index.
            default: Default value.
            required: Whether required.
            transform: Value transform.
            description: Field description.

        Returns:
            Self for chaining.
        """
        self._fields.append(FieldDef(
            name=name,
            selector=selector,
            type=type,
            attribute=attribute,
            pattern=pattern,
            group=group,
            default=default,
            required=required,
            transform=transform,
            description=description,
        ))
        return self

    def text_field(
        self,
        name: str,
        selector: str,
        **kwargs: Any,
    ) -> SchemaBuilder:
        """Add a text field (shorthand)."""
        return self.field(name, selector=selector, type="text", **kwargs)

    def attribute_field(
        self,
        name: str,
        selector: str,
        attribute: str,
        **kwargs: Any,
    ) -> SchemaBuilder:
        """Add an attribute field (shorthand)."""
        return self.field(
            name, selector=selector, type="attribute",
            attribute=attribute, **kwargs,
        )

    def link_field(
        self,
        name: str,
        selector: str = "a",
        **kwargs: Any,
    ) -> SchemaBuilder:
        """Add a link href field (shorthand)."""
        return self.field(
            name, selector=selector, type="attribute",
            attribute="href", **kwargs,
        )

    def image_field(
        self,
        name: str,
        selector: str = "img",
        **kwargs: Any,
    ) -> SchemaBuilder:
        """Add an image src field (shorthand)."""
        return self.field(
            name, selector=selector, type="attribute",
            attribute="src", **kwargs,
        )

    def regex_field(
        self,
        name: str,
        pattern: str,
        group: int = 0,
        **kwargs: Any,
    ) -> SchemaBuilder:
        """Add a regex field (shorthand)."""
        return self.field(
            name, type="regex", pattern=pattern,
            group=group, **kwargs,
        )

    def list_field(
        self,
        name: str,
        selector: str,
        fields: list[dict[str, Any]],
        **kwargs: Any,
    ) -> SchemaBuilder:
        """
        Add a list field (repeated elements).

        Args:
            name: Field name.
            selector: Selector for repeated elements.
            fields: Sub-field definitions.

        Returns:
            Self for chaining.
        """
        self._fields.append(FieldDef(
            name=name,
            selector=selector,
            type="list",
            fields=fields,
            **kwargs,
        ))
        return self

    def nested_field(
        self,
        name: str,
        fields: list[dict[str, Any]],
        **kwargs: Any,
    ) -> SchemaBuilder:
        """
        Add a nested object field.

        Args:
            name: Field name.
            fields: Sub-field definitions.

        Returns:
            Self for chaining.
        """
        self._fields.append(FieldDef(
            name=name,
            type="nested",
            fields=fields,
            **kwargs,
        ))
        return self

    def build(self) -> dict[str, Any]:
        """
        Build the schema dictionary.

        Returns:
            Schema dictionary ready for use with extractors.
        """
        schema: dict[str, Any] = {
            "name": self._name,
            "fields": [f.to_dict() for f in self._fields],
        }

        if self._base_selector:
            if self._method == "xpath":
                schema["baseXPath"] = self._base_selector
            else:
                schema["baseSelector"] = self._base_selector

        if self._description:
            schema["description"] = self._description

        return schema

    def build_css(self) -> dict[str, Any]:
        """Build a CSS extractor schema."""
        self._method = "css"
        return self.build()

    def build_xpath(self) -> dict[str, Any]:
        """Build an XPath extractor schema."""
        self._method = "xpath"
        # Convert selectors to XPath key
        schema = self.build()
        if "baseSelector" in schema:
            schema["baseXPath"] = schema.pop("baseSelector")
        for f in schema.get("fields", []):
            if "selector" in f:
                f["xpath"] = f.pop("selector")
        return schema

    def build_regex(self) -> dict[str, Any]:
        """Build a regex extractor schema."""
        self._method = "regex"
        return self.build()

    def __repr__(self) -> str:
        return (
            f"SchemaBuilder(name={self._name!r}, "
            f"method={self._method!r}, "
            f"fields={len(self._fields)})"
        )


# ══════════════════════════════════════════════════════════════
# Schema Templates
# ══════════════════════════════════════════════════════════════

class SchemaTemplate:
    """
    Pre-built schema templates for common extraction use cases.

    Example:
        >>> schema = SchemaTemplate.product()
        >>> schema = SchemaTemplate.article()
        >>> schema = SchemaTemplate.profile()
    """

    @classmethod
    def product(cls) -> dict[str, Any]:
        """Product listing schema."""
        return (
            SchemaBuilder("Product", method="css")
            .base_selector("div.product, article.product, li.product")
            .text_field("name", selector="h1, h2, h3, .title, .product-title, .product-name")
            .text_field("price", selector=".price, .product-price, [data-price]")
            .text_field("description", selector=".description, .product-description, p")
            .link_field("url", selector="a")
            .image_field("image", selector="img")
            .text_field("sku", selector=".sku, .product-sku, [data-sku]")
            .text_field("brand", selector=".brand, .manufacturer")
            .attribute_field("rating", selector=".rating, .stars", attribute="data-rating")
            .text_field("availability", selector=".availability, .stock, .in-stock")
            .build()
        )

    @classmethod
    def article(cls) -> dict[str, Any]:
        """Article/blog post schema."""
        return (
            SchemaBuilder("Article", method="css")
            .text_field("title", selector="h1, .title, .post-title, .article-title")
            .text_field("author", selector=".author, .byline, [rel='author']")
            .text_field("date", selector="time, .date, .published, .post-date")
            .text_field("content", selector="article, .content, .post-content, .article-body")
            .text_field("summary", selector=".summary, .excerpt, .description, meta[name='description']")
            .image_field("featured_image", selector="img.hero, img.featured, .thumbnail img")
            .list_field("tags", selector=".tag, .category, a[rel='tag']", fields=[
                {"name": "text", "selector": "", "type": "text"},
            ])
            .build()
        )

    @classmethod
    def profile(cls) -> dict[str, Any]:
        """User profile schema."""
        return (
            SchemaBuilder("Profile", method="css")
            .text_field("name", selector="h1, .name, .username, .display-name")
            .text_field("bio", selector=".bio, .description, .about")
            .image_field("avatar", selector="img.avatar, img.profile, .avatar img")
            .text_field("location", selector=".location, .place")
            .link_field("website", selector="a.website, a[rel='me']")
            .text_field("followers", selector=".followers, .follower-count")
            .text_field("following", selector=".following, .following-count")
            .build()
        )

    @classmethod
    def job_listing(cls) -> dict[str, Any]:
        """Job listing schema."""
        return (
            SchemaBuilder("JobListing", method="css")
            .text_field("title", selector="h1, h2, .title, .job-title")
            .text_field("company", selector=".company, .employer, .organization")
            .text_field("location", selector=".location, .place, .job-location")
            .text_field("salary", selector=".salary, .compensation, .pay")
            .text_field("type", selector=".type, .employment-type, .job-type")
            .text_field("description", selector=".description, .job-description, .details")
            .text_field("posted_date", selector="time, .date, .posted")
            .link_field("apply_url", selector="a.apply, a[href*='apply']")
            .build()
        )

    @classmethod
    def event(cls) -> dict[str, Any]:
        """Event listing schema."""
        return (
            SchemaBuilder("Event", method="css")
            .text_field("name", selector="h1, h2, .title, .event-title")
            .text_field("date", selector="time, .date, .event-date")
            .text_field("time", selector=".time, .event-time")
            .text_field("location", selector=".location, .venue, .place")
            .text_field("description", selector=".description, .event-description")
            .text_field("price", selector=".price, .ticket-price, .cost")
            .image_field("image", selector="img")
            .link_field("url", selector="a")
            .build()
        )

    @classmethod
    def search_result(cls) -> dict[str, Any]:
        """Search result schema."""
        return (
            SchemaBuilder("SearchResult", method="css")
            .base_selector(".result, .search-result, li.result")
            .text_field("title", selector="h3, .title, a")
            .link_field("url", selector="a")
            .text_field("snippet", selector=".snippet, .description, p")
            .text_field("date", selector=".date, time")
            .build()
        )

    @classmethod
    def faq(cls) -> dict[str, Any]:
        """FAQ schema."""
        return (
            SchemaBuilder("FAQ", method="css")
            .base_selector(".faq-item, .qa, details, .question-answer")
            .text_field("question", selector="h3, h4, summary, .question, dt")
            .text_field("answer", selector=".answer, p, dd")
            .build()
        )

    @classmethod
    def recipe(cls) -> dict[str, Any]:
        """Recipe schema."""
        return (
            SchemaBuilder("Recipe", method="css")
            .text_field("name", selector="h1, .recipe-title")
            .text_field("description", selector=".description, .recipe-description")
            .text_field("prep_time", selector=".prep-time, [data-prep-time]")
            .text_field("cook_time", selector=".cook-time, [data-cook-time]")
            .text_field("servings", selector=".servings, .yield")
            .list_field("ingredients", selector=".ingredient, li.ingredient", fields=[
                {"name": "text", "selector": "", "type": "text"},
            ])
            .list_field("instructions", selector=".step, li.step, .instruction", fields=[
                {"name": "text", "selector": "", "type": "text"},
            ])
            .image_field("image", selector="img")
            .build()
        )

    @classmethod
    def list_templates(cls) -> list[dict[str, str]]:
        """List all available templates."""
        return [
            {"name": "product", "description": "Product listing (name, price, image, etc.)"},
            {"name": "article", "description": "Article/blog post (title, author, date, content)"},
            {"name": "profile", "description": "User profile (name, bio, avatar, stats)"},
            {"name": "job_listing", "description": "Job listing (title, company, salary, etc.)"},
            {"name": "event", "description": "Event (name, date, location, price)"},
            {"name": "search_result", "description": "Search result (title, url, snippet)"},
            {"name": "faq", "description": "FAQ item (question, answer)"},
            {"name": "recipe", "description": "Recipe (name, ingredients, instructions)"},
        ]


# ══════════════════════════════════════════════════════════════
# Schema Converter
# ══════════════════════════════════════════════════════════════

class SchemaConverter:
    """
    Converts schemas between different formats.

    Supports:
        - Pydantic model → JSON Schema
        - JSON Schema → CSS extraction schema
        - JSON Schema → XPath extraction schema
        - CSS schema → XPath schema (basic conversion)
        - Any schema → Pydantic model (dynamic)

    Example:
        >>> converter = SchemaConverter()
        >>> json_schema = converter.to_json_schema(MyPydanticModel)
        >>> css_schema = converter.json_schema_to_css(json_schema)
    """

    @staticmethod
    def to_json_schema(schema: Any) -> dict[str, Any]:
        """
        Convert any schema to JSON Schema format.

        Args:
            schema: Pydantic model, dict, or TypedDict.

        Returns:
            JSON Schema dictionary.
        """
        if schema is None:
            return {}

        if isinstance(schema, dict):
            return schema

        if hasattr(schema, "model_json_schema"):
            return schema.model_json_schema()

        if hasattr(schema, "schema"):
            return schema.schema()

        return {}

    @staticmethod
    def json_schema_to_css(
        json_schema: dict[str, Any],
        base_selector: str = "",
    ) -> dict[str, Any]:
        """
        Convert a JSON Schema to a CSS extraction schema.

        Note: This creates a basic mapping. Selectors must be
        manually adjusted for the target HTML structure.

        Args:
            json_schema: JSON Schema dictionary.
            base_selector: Base CSS selector.

        Returns:
            CSS extraction schema.
        """
        properties = json_schema.get("properties", {})
        required = set(json_schema.get("required", []))

        fields: list[dict[str, Any]] = []
        for name, prop in properties.items():
            field_def: dict[str, Any] = {
                "name": name,
                "selector": f".{name}",  # Default: class-based selector
                "type": "text",
                "required": name in required,
            }

            prop_type = prop.get("type", "string")
            if prop_type == "array":
                field_def["type"] = "list"
                field_def["fields"] = [
                    {"name": "item", "selector": "li", "type": "text"}
                ]
            elif prop_type == "object":
                field_def["type"] = "nested"

            fields.append(field_def)

        schema: dict[str, Any] = {
            "name": json_schema.get("title", "Schema"),
            "fields": fields,
        }

        if base_selector:
            schema["baseSelector"] = base_selector

        return schema

    @staticmethod
    def json_schema_to_xpath(
        json_schema: dict[str, Any],
        base_xpath: str = "",
    ) -> dict[str, Any]:
        """
        Convert a JSON Schema to an XPath extraction schema.

        Args:
            json_schema: JSON Schema dictionary.
            base_xpath: Base XPath expression.

        Returns:
            XPath extraction schema.
        """
        properties = json_schema.get("properties", {})
        required = set(json_schema.get("required", []))

        fields: list[dict[str, Any]] = []
        for name, prop in properties.items():
            field_def: dict[str, Any] = {
                "name": name,
                "xpath": f".//*[contains(@class, '{name}')]",
                "type": "text",
                "required": name in required,
            }

            prop_type = prop.get("type", "string")
            if prop_type == "array":
                field_def["type"] = "list"
                field_def["fields"] = [
                    {"name": "item", "xpath": ".//li", "type": "text"}
                ]

            fields.append(field_def)

        schema: dict[str, Any] = {
            "name": json_schema.get("title", "Schema"),
            "fields": fields,
        }

        if base_xpath:
            schema["baseXPath"] = base_xpath

        return schema

    @staticmethod
    def css_to_xpath_schema(css_schema: dict[str, Any]) -> dict[str, Any]:
        """
        Convert a CSS extraction schema to XPath format.

        Note: Only handles simple selectors. Complex CSS selectors
        may not convert accurately.

        Args:
            css_schema: CSS extraction schema.

        Returns:
            XPath extraction schema.
        """
        schema = dict(css_schema)

        # Convert base selector
        if "baseSelector" in schema:
            schema["baseXPath"] = SchemaConverter._css_to_xpath(
                schema.pop("baseSelector")
            )

        # Convert field selectors
        for field_def in schema.get("fields", []):
            if "selector" in field_def:
                field_def["xpath"] = SchemaConverter._css_to_xpath(
                    field_def.pop("selector")
                )

            # Recurse into sub-fields
            for sub_field in field_def.get("fields", []):
                if "selector" in sub_field:
                    sub_field["xpath"] = SchemaConverter._css_to_xpath(
                        sub_field.pop("selector")
                    )

        return schema

    @staticmethod
    def _css_to_xpath(css: str) -> str:
        """
        Convert a simple CSS selector to XPath.

        Handles: tag, .class, #id, tag.class, tag#id
        """
        css = css.strip()

        # ID selector
        if css.startswith("#"):
            return f"//*[@id='{css[1:]}']"

        # Class selector
        if css.startswith("."):
            return f"//*[contains(@class, '{css[1:]}')]"

        # Tag with class (tag.class)
        match = re.match(r"^(\w+)\.([\w-]+)$", css)
        if match:
            tag, cls = match.groups()
            return f"//{tag}[contains(@class, '{cls}')]"

        # Tag with ID (tag#id)
        match = re.match(r"^(\w+)#([\w-]+)$", css)
        if match:
            tag, id_val = match.groups()
            return f"//{tag}[@id='{id_val}']"

        # Plain tag
        if re.match(r"^\w+$", css):
            return f"//{css}"

        # Fallback: descendant with class
        return f"//*[contains(@class, '{css}')]"

    @staticmethod
    def to_pydantic_model(
        json_schema: dict[str, Any],
        model_name: str = "ExtractedData",
    ) -> Any:
        """
        Dynamically create a Pydantic model from a JSON Schema.

        Args:
            json_schema: JSON Schema dictionary.
            model_name: Name for the generated model.

        Returns:
            Pydantic BaseModel class.
        """
        try:
            from pydantic import create_model
        except ImportError:
            raise ImportError("pydantic is required for dynamic model creation")

        properties = json_schema.get("properties", {})
        required = set(json_schema.get("required", []))

        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        field_definitions: dict[str, Any] = {}
        for name, prop in properties.items():
            python_type = type_map.get(prop.get("type", "string"), str)

            if name in required:
                field_definitions[name] = (python_type, ...)
            else:
                field_definitions[name] = (python_type | None, None)

        return create_model(model_name, **field_definitions)


# ══════════════════════════════════════════════════════════════
# Schema Validator
# ══════════════════════════════════════════════════════════════

class SchemaValidator:
    """
    Validates extraction schemas for correctness.

    Example:
        >>> validator = SchemaValidator()
        >>> is_valid, errors = validator.validate(schema)
    """

    @staticmethod
    def validate(schema: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate an extraction schema.

        Args:
            schema: Schema dictionary.

        Returns:
            Tuple of (is_valid, error_messages).
        """
        errors: list[str] = []

        if not isinstance(schema, dict):
            return False, ["Schema must be a dictionary"]

        # Check name
        if "name" not in schema:
            errors.append("Schema missing 'name' field")

        # Check fields
        fields = schema.get("fields", [])
        if not fields:
            errors.append("Schema has no fields defined")

        field_names: set[str] = set()
        for i, field_def in enumerate(fields):
            if not isinstance(field_def, dict):
                errors.append(f"Field {i} is not a dictionary")
                continue

            name = field_def.get("name", "")
            if not name:
                errors.append(f"Field {i} missing 'name'")
                continue

            if name in field_names:
                errors.append(f"Duplicate field name: '{name}'")
            field_names.add(name)

            field_type = field_def.get("type", "text")
            valid_types = {"text", "html", "attribute", "list", "nested", "regex"}
            if field_type not in valid_types:
                errors.append(
                    f"Field '{name}': invalid type '{field_type}'. "
                    f"Must be one of: {', '.join(sorted(valid_types))}"
                )

            # Type-specific validation
            if field_type == "attribute" and not field_def.get("attribute"):
                errors.append(f"Field '{name}': 'attribute' type requires 'attribute' key")

            if field_type == "regex" and not field_def.get("pattern"):
                errors.append(f"Field '{name}': 'regex' type requires 'pattern' key")

            if field_type in ("list", "nested") and not field_def.get("fields"):
                errors.append(f"Field '{name}': '{field_type}' type requires 'fields' key")

            # Validate regex pattern
            if field_type == "regex" and field_def.get("pattern"):
                try:
                    re.compile(field_def["pattern"])
                except re.error as e:
                    errors.append(f"Field '{name}': invalid regex: {e}")

        return len(errors) == 0, errors


# ══════════════════════════════════════════════════════════════
# Schema Inference
# ══════════════════════════════════════════════════════════════

def infer_schema_from_html(
    html: str,
    max_depth: int = 3,
    min_elements: int = 3,
) -> dict[str, Any]:
    """
    Infer an extraction schema from HTML structure.

    Analyzes repeated HTML patterns and generates a CSS-based
    extraction schema.

    Args:
        html: HTML content to analyze.
        max_depth: Maximum DOM depth to analyze.
        min_elements: Minimum repeated elements to detect a pattern.

    Returns:
        Inferred CSS extraction schema.

    Example:
        >>> schema = infer_schema_from_html(product_listing_html)
        >>> print(schema)
    """
    try:
        from lxml import html as lxml_html
    except ImportError:
        logger.warning("lxml not available for schema inference")
        return {"name": "InferredSchema", "fields": []}

    try:
        tree = lxml_html.document_fromstring(html)
    except Exception as e:
        logger.warning("HTML parse error: %s", e)
        return {"name": "InferredSchema", "fields": []}

    # Find repeated element patterns
    tag_class_counts: dict[str, int] = {}
    tag_class_examples: dict[str, Any] = {}

    def _walk(element: Any, depth: int) -> None:
        if depth > max_depth:
            return

        tag = element.tag if isinstance(element.tag, str) else ""
        classes = element.get("class", "")

        if tag and classes:
            for cls in classes.split():
                key = f"{tag}.{cls}"
                tag_class_counts[key] = tag_class_counts.get(key, 0) + 1
                if key not in tag_class_examples:
                    tag_class_examples[key] = element

        for child in element:
            _walk(child, depth + 1)

    _walk(tree, 0)

    # Find the most common repeated pattern
    repeated = {
        k: v for k, v in tag_class_counts.items()
        if v >= min_elements
    }

    if not repeated:
        return {"name": "InferredSchema", "fields": []}

    # Sort by count
    sorted_patterns = sorted(repeated.items(), key=lambda x: x[1], reverse=True)
    base_pattern = sorted_patterns[0][0]
    base_element = tag_class_examples.get(base_pattern)

    # Build schema from the base element's children
    fields: list[dict[str, Any]] = []

    if base_element is not None:
        # Extract child element patterns
        for child in base_element:
            child_tag = child.tag if isinstance(child.tag, str) else ""
            child_classes = child.get("class", "")
            text = child.text_content().strip()

            if not child_tag or not text:
                continue

            field_name = child_classes.split()[0] if child_classes else child_tag
            selector = f"{child_tag}.{child_classes.split()[0]}" if child_classes else child_tag

            # Check for links
            link = child.find(".//a")
            if link is not None:
                fields.append({
                    "name": f"{field_name}_url",
                    "selector": f"{selector} a",
                    "type": "attribute",
                    "attribute": "href",
                })

            # Check for images
            img = child.find(".//img")
            if img is not None:
                fields.append({
                    "name": f"{field_name}_image",
                    "selector": f"{selector} img",
                    "type": "attribute",
                    "attribute": "src",
                })

            fields.append({
                "name": field_name,
                "selector": selector,
                "type": "text",
            })

    return {
        "name": "InferredSchema",
        "baseSelector": f".{base_pattern.split('.')[-1]}" if "." in base_pattern else base_pattern,
        "fields": fields[:10],  # Limit to 10 fields
    }


# ══════════════════════════════════════════════════════════════
# Re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    "FieldDef",
    "SchemaBuilder",
    "SchemaConverter",
    "SchemaTemplate",
    "SchemaValidator",
    "infer_schema_from_html",
]
