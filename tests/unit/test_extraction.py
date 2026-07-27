"""
AgentCrawl — Extraction Unit Tests
======================================

Unit tests for structured data extractors.

Tests:
    - JsonCssExtractor (CSS selector extraction)
    - JsonXPathExtractor (XPath extraction)
    - RegexExtractor (regex pattern extraction)
    - LLMExtractor (LLM-powered, mocked)
    - create_extractor factory
    - Dynamic Pydantic model creation
    - List and attribute extraction
    - Nested extraction
    - Error handling

Run:
    pytest tests/unit/test_extraction.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════
# Sample HTML
# ══════════════════════════════════════════════════════════════

SAMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
    <h1>Main Title</h1>
    <p class="description">This is a test page.</p>
    <div class="price">$29.99</div>
    <a href="https://example.com" class="link">Example Link</a>
    <ul class="features">
        <li>Feature 1</li>
        <li>Feature 2</li>
        <li>Feature 3</li>
    </ul>
    <div class="product">
        <span class="name">Widget</span>
        <span class="sku">SKU-123</span>
    </div>
</body>
</html>
"""

PRODUCT_HTML = """
<html>
<body>
    <div class="products">
        <div class="product">
            <h2 class="title">Product A</h2>
            <span class="price">$10.00</span>
            <a href="/product/a" class="url">View</a>
        </div>
        <div class="product">
            <h2 class="title">Product B</h2>
            <span class="price">$20.00</span>
            <a href="/product/b" class="url">View</a>
        </div>
        <div class="product">
            <h2 class="title">Product C</h2>
            <span class="price">$30.00</span>
            <a href="/product/c" class="url">View</a>
        </div>
    </div>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════
# JsonCssExtractor
# ══════════════════════════════════════════════════════════════

class TestJsonCssExtractor:
    """Tests for JsonCssExtractor."""

    def test_basic_extraction(self) -> None:
        """Extract text with CSS selectors."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
                {"name": "description", "selector": ".description", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["title"] == "Main Title"
        assert result.data["description"] == "This is a test page."

    def test_attribute_extraction(self) -> None:
        """Extract element attributes."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Links",
            "fields": [
                {"name": "href", "selector": "a.link", "type": "attribute", "attribute": "href"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["href"] == "https://example.com"

    def test_list_extraction(self) -> None:
        """Extract a list of elements."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Features",
            "fields": [
                {"name": "features", "selector": ".features li", "type": "list"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert len(result.data["features"]) == 3
        assert "Feature 1" in result.data["features"]

    def test_nested_extraction(self) -> None:
        """Extract nested structures."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Product",
            "fields": [
                {"name": "name", "selector": ".product .name", "type": "text"},
                {"name": "sku", "selector": ".product .sku", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["name"] == "Widget"
        assert result.data["sku"] == "SKU-123"

    def test_missing_selector(self) -> None:
        """Missing selector returns empty/default value."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "missing", "selector": ".nonexistent", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data.get("missing", "") == ""

    def test_empty_html(self) -> None:
        """Empty HTML returns empty data."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract("")

        assert result.success is True
        assert result.data.get("title", "") == ""

    def test_multiple_products(self) -> None:
        """Extract multiple items with base selector."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Products",
            "baseSelector": ".product",
            "fields": [
                {"name": "title", "selector": ".title", "type": "text"},
                {"name": "price", "selector": ".price", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract(PRODUCT_HTML)

        assert result.success is True
        assert isinstance(result.data, list)
        assert len(result.data) == 3
        assert result.data[0]["title"] == "Product A"
        assert result.data[1]["price"] == "$20.00"

    def test_result_has_metadata(self) -> None:
        """Result includes extraction metadata."""
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.method == "css"
        assert result.fields_extracted >= 1


# ══════════════════════════════════════════════════════════════
# JsonXPathExtractor
# ══════════════════════════════════════════════════════════════

class TestJsonXPathExtractor:
    """Tests for JsonXPathExtractor."""

    def test_basic_extraction(self) -> None:
        """Extract text with XPath."""
        from agentcrawl.extraction.xpath_extractor import JsonXPathExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "xpath": "//h1", "type": "text"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["title"] == "Main Title"

    def test_attribute_extraction(self) -> None:
        """Extract attributes with XPath."""
        from agentcrawl.extraction.xpath_extractor import JsonXPathExtractor

        schema = {
            "name": "Links",
            "fields": [
                {"name": "href", "xpath": "//a[@class='link']/@href", "type": "text"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["href"] == "https://example.com"

    def test_list_extraction(self) -> None:
        """Extract list with XPath."""
        from agentcrawl.extraction.xpath_extractor import JsonXPathExtractor

        schema = {
            "name": "Features",
            "fields": [
                {"name": "features", "xpath": "//ul[@class='features']/li", "type": "list"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert len(result.data["features"]) == 3

    def test_empty_html(self) -> None:
        """Empty HTML returns empty data."""
        from agentcrawl.extraction.xpath_extractor import JsonXPathExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "xpath": "//h1", "type": "text"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = extractor.extract("")

        assert result.success is True

    def test_result_method(self) -> None:
        """Result method is 'xpath'."""
        from agentcrawl.extraction.xpath_extractor import JsonXPathExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "xpath": "//h1", "type": "text"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = extractor.extract(SAMPLE_HTML)

        assert result.method == "xpath"


# ══════════════════════════════════════════════════════════════
# RegexExtractor
# ══════════════════════════════════════════════════════════════

class TestRegexExtractor:
    """Tests for RegexExtractor."""

    def test_basic_extraction(self) -> None:
        """Extract with regex patterns."""
        from agentcrawl.extraction.regex_extractor import RegexExtractor

        schema = {
            "name": "Data",
            "fields": [
                {"name": "price", "pattern": r"\$(\d+\.\d{2})", "type": "first"},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = extractor.extract("The price is $29.99 today.")

        assert result.success is True
        assert result.data["price"] == "29.99"

    def test_all_matches(self) -> None:
        """Extract all regex matches."""
        from agentcrawl.extraction.regex_extractor import RegexExtractor

        schema = {
            "name": "Emails",
            "fields": [
                {"name": "emails", "pattern": r"[\w.+-]+@[\w-]+\.[\w.]+", "type": "all"},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = extractor.extract("Contact: alice@example.com or bob@test.org")

        assert result.success is True
        assert len(result.data["emails"]) == 2

    def test_no_match(self) -> None:
        """No match returns empty/default."""
        from agentcrawl.extraction.regex_extractor import RegexExtractor

        schema = {
            "name": "Data",
            "fields": [
                {"name": "phone", "pattern": r"\d{3}-\d{4}", "type": "first"},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = extractor.extract("No phone number here.")

        assert result.success is True
        assert result.data.get("phone", "") == ""

    def test_empty_content(self) -> None:
        """Empty content returns empty data."""
        from agentcrawl.extraction.regex_extractor import RegexExtractor

        schema = {
            "name": "Data",
            "fields": [
                {"name": "value", "pattern": r"\d+", "type": "first"},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = extractor.extract("")

        assert result.success is True

    def test_result_method(self) -> None:
        """Result method is 'regex'."""
        from agentcrawl.extraction.regex_extractor import RegexExtractor

        schema = {
            "name": "Data",
            "fields": [
                {"name": "num", "pattern": r"\d+", "type": "first"},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = extractor.extract("123")

        assert result.method == "regex"


# ══════════════════════════════════════════════════════════════
# LLMExtractor (Mocked)
# ══════════════════════════════════════════════════════════════

class TestLLMExtractor:
    """Tests for LLMExtractor (mocked LLM calls)."""

    @pytest.mark.asyncio
    async def test_basic_extraction(self) -> None:
        """LLM extraction with mocked response."""
        from agentcrawl.extraction.llm_extractor import LLMExtractor
        from pydantic import BaseModel

        class Product(BaseModel):
            name: str
            price: str

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "price": {"type": "string"},
            },
        }

        extractor = LLMExtractor(schema=schema)

        # Mock the LLM call
        mock_response = MagicMock()
        mock_response.name = "Widget"
        mock_response.price = "$29.99"
        mock_response.model_dump = MagicMock(return_value={"name": "Widget", "price": "$29.99"})

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            result = await extractor.extract_async("Product: Widget, Price: $29.99")

            assert result.success is True
            assert result.data["name"] == "Widget"

    @pytest.mark.asyncio
    async def test_llm_error_handling(self) -> None:
        """LLM extraction handles errors gracefully."""
        from agentcrawl.extraction.llm_extractor import LLMExtractor

        schema = {
            "type": "object",
            "properties": {"title": {"type": "string"}},
        }

        extractor = LLMExtractor(schema=schema)

        with patch.object(extractor, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("API error")

            result = await extractor.extract_async("Some content")

            assert result.success is False
            assert result.error is not None

    def test_result_method(self) -> None:
        """Result method is 'llm'."""
        from agentcrawl.extraction.llm_extractor import LLMExtractor

        schema = {"type": "object", "properties": {}}
        extractor = LLMExtractor(schema=schema)

        # Check the method attribute
        assert extractor.method == "llm"


# ══════════════════════════════════════════════════════════════
# Factory Function
# ══════════════════════════════════════════════════════════════

class TestCreateExtractor:
    """Tests for create_extractor factory."""

    def test_create_css_extractor(self) -> None:
        """Create CSS extractor."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor(schema, method="css")

        assert isinstance(extractor, JsonCssExtractor)

    def test_create_xpath_extractor(self) -> None:
        """Create XPath extractor."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.xpath_extractor import JsonXPathExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor(schema, method="xpath")

        assert isinstance(extractor, JsonXPathExtractor)

    def test_create_regex_extractor(self) -> None:
        """Create regex extractor."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.regex_extractor import RegexExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor(schema, method="regex")

        assert isinstance(extractor, RegexExtractor)

    def test_create_llm_extractor(self) -> None:
        """Create LLM extractor."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.llm_extractor import LLMExtractor

        schema = {"type": "object", "properties": {}}
        extractor = create_extractor(schema, method="llm")

        assert isinstance(extractor, LLMExtractor)

    def test_invalid_method(self) -> None:
        """Invalid method raises ValueError."""
        from agentcrawl.extraction.base import create_extractor

        with pytest.raises(ValueError, match="Unknown extraction method"):
            create_extractor({}, method="invalid")

    def test_default_method_is_css(self) -> None:
        """Default method is CSS."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.css_extractor import JsonCssExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor(schema)

        assert isinstance(extractor, JsonCssExtractor)


# ══════════════════════════════════════════════════════════════
# Dynamic Schema
# ══════════════════════════════════════════════════════════════

class TestDynamicSchema:
    """Tests for dynamic Pydantic model creation."""

    def test_build_from_fields(self) -> None:
        """Build model from field names."""
        from agentcrawl.extraction.dynamic_schema import build_dynamic_model

        model = build_dynamic_model("title,price,description")

        assert model is not None
        assert hasattr(model, "model_fields")
        assert "title" in model.model_fields
        assert "price" in model.model_fields
        assert "description" in model.model_fields

    def test_build_from_schema_dict(self) -> None:
        """Build model from JSON Schema dict."""
        from agentcrawl.extraction.dynamic_schema import build_dynamic_model

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }

        model = build_dynamic_model(schema)
        assert model is not None

    def test_empty_fields(self) -> None:
        """Empty fields returns None."""
        from agentcrawl.extraction.dynamic_schema import build_dynamic_model

        model = build_dynamic_model("")
        assert model is None

    def test_model_instantiation(self) -> None:
        """Dynamic model can be instantiated."""
        from agentcrawl.extraction.dynamic_schema import build_dynamic_model

        Model = build_dynamic_model("title,price")
        instance = Model(title="Widget", price="$10")

        assert instance.title == "Widget"
        assert instance.price == "$10"

    def test_model_serialization(self) -> None:
        """Dynamic model serializes to dict."""
        from agentcrawl.extraction.dynamic_schema import build_dynamic_model

        Model = build_dynamic_model("name,value")
        instance = Model(name="test", value="123")

        data = instance.model_dump()
        assert data["name"] == "test"
        assert data["value"] == "123"


# ══════════════════════════════════════════════════════════════
# ExtractorResult
# ══════════════════════════════════════════════════════════════

class TestExtractorResult:
    """Tests for ExtractorResult model."""

    def test_result_creation(self) -> None:
        """Create an extractor result."""
        from agentcrawl.extraction.base import ExtractorResult

        result = ExtractorResult(
            success=True,
            data={"title": "Test"},
            method="css",
        )

        assert result.success is True
        assert result.data["title"] == "Test"
        assert result.method == "css"

    def test_failed_result(self) -> None:
        """Create a failed result."""
        from agentcrawl.extraction.base import ExtractorResult

        result = ExtractorResult(
            success=False,
            error="Extraction failed",
            method="llm",
        )

        assert result.success is False
        assert result.error == "Extraction failed"

    def test_result_to_dict(self) -> None:
        """Result serializes to dict."""
        from agentcrawl.extraction.base import ExtractorResult

        result = ExtractorResult(
            success=True,
            data={"key": "value"},
            method="css",
        )

        data = result.to_dict()
        assert "success" in data
        assert "data" in data
        assert "method" in data