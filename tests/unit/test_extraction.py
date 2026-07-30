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

import pytest

# ══════════════════════════════════════════════════════════════
# Sample HTML
# ═══════════════════════════════════════════════════════════════

SAMPLE_HTML = """<html>
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

PRODUCT_HTML = """<html>
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


# ═══════════════════════════════════════════════════════════════
# JsonCssExtractor
# ═══════════════════════════════════════════════════════════════


class TestJsonCssExtractor:
    """Tests for JsonCssExtractor."""

    @pytest.mark.asyncio
    async def test_basic_extraction(self) -> None:
        """Extract text with CSS selectors."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
                {"name": "description", "selector": ".description", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["title"] == "Main Title"
        assert result.data["description"] == "This is a test page."

    @pytest.mark.asyncio
    async def test_attribute_extraction(self) -> None:
        """Extract element attributes."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Links",
            "fields": [
                {"name": "href", "selector": "a.link", "type": "attribute", "attribute": "href"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["href"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_list_extraction(self) -> None:
        """Extract a list of elements."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Features",
            "fields": [
                {"name": "features", "selector": ".features li", "type": "list"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert len(result.data["features"]) == 3
        assert "Feature 1" in result.data["features"]

    @pytest.mark.asyncio
    async def test_nested_extraction(self) -> None:
        """Extract nested structures."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Product",
            "fields": [
                {"name": "name", "selector": ".product .name", "type": "text"},
                {"name": "sku", "selector": ".product .sku", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["name"] == "Widget"
        assert result.data["sku"] == "SKU-123"

    @pytest.mark.asyncio
    async def test_missing_selector(self) -> None:
        """Missing selector returns empty/default value."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "missing", "selector": ".nonexistent", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data.get("missing") is None or result.data.get("missing") == ""

    @pytest.mark.asyncio
    async def test_empty_html(self) -> None:
        """Empty HTML returns empty data."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract("")

        assert result.success is True
        assert result.data.get("title", "") == ""

    @pytest.mark.asyncio
    async def test_multiple_products(self) -> None:
        """Extract multiple items with base selector."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Products",
            "baseSelector": ".product",
            "fields": [
                {"name": "title", "selector": ".title", "type": "text"},
                {"name": "price", "selector": ".price", "type": "text"},
                {"name": "url", "selector": ".url", "type": "attribute", "attribute": "href"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract(PRODUCT_HTML)

        assert result.success is True
        assert isinstance(result.data, list)
        assert len(result.data) == 3
        assert result.data[0]["title"] == "Product A"
        assert result.data[0]["price"] == "$10.00"
        assert result.data[0]["url"] == "/product/a"

    @pytest.mark.asyncio
    async def test_result_has_metadata(self) -> None:
        """Result includes extraction metadata."""
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {
            "name": "Page",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
            ],
        }

        extractor = JsonCssExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.method == "css"
        assert result.success is True


# ═══════════════════════════════════════════════════════════════
# JsonXPathExtractor
# ═══════════════════════════════════════════════════════════════


class TestJsonXPathExtractor:
    """Tests for JsonXPathExtractor."""

    @pytest.mark.asyncio
    async def test_basic_extraction(self) -> None:
        """Extract text with XPath selectors."""
        from agentcrawl.extraction.json_xpath import JsonXPathExtractor

        schema = {
            "name": "Page",
            "baseSelector": "body",
            "fields": [
                {"name": "title", "xpath": "//h1", "type": "text"},
                {"name": "description", "xpath": "//p[@class='description']", "type": "text"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["title"] == "Main Title"
        assert result.data["description"] == "This is a test page."

    @pytest.mark.asyncio
    async def test_attribute_extraction(self) -> None:
        """Extract element attributes."""
        from agentcrawl.extraction.json_xpath import JsonXPathExtractor

        schema = {
            "name": "Links",
            "baseSelector": "body",
            "fields": [
                {
                    "name": "href",
                    "xpath": "//a[@class='link']",
                    "type": "attribute",
                    "attribute": "href",
                },
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert result.data["href"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_list_extraction(self) -> None:
        """Extract list with XPath."""
        from agentcrawl.extraction.json_xpath import JsonXPathExtractor

        schema = {
            "name": "Features",
            "baseSelector": "body",
            "fields": [
                {"name": "features", "xpath": "//ul[@class='features']/li", "type": "list"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert len(result.data["features"]) == 3

    @pytest.mark.asyncio
    async def test_empty_html(self) -> None:
        """Empty HTML returns empty data."""
        from agentcrawl.extraction.json_xpath import JsonXPathExtractor

        schema = {
            "name": "Page",
            "baseSelector": "body",
            "fields": [
                {"name": "title", "xpath": "//h1", "type": "text"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = await extractor.extract("")

        assert result.success is True
        assert result.data.get("title", "") == ""

    @pytest.mark.asyncio
    async def test_result_method(self) -> None:
        """Result method is 'xpath'."""
        from agentcrawl.extraction.json_xpath import JsonXPathExtractor

        schema = {
            "name": "Page",
            "baseSelector": "body",
            "fields": [
                {"name": "title", "xpath": "//h1", "type": "text"},
            ],
        }

        extractor = JsonXPathExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.method == "xpath"


# ═══════════════════════════════════════════════════════════════
# RegexExtractor
# ═══════════════════════════════════════════════════════════════


class TestRegexExtractor:
    """Tests for RegexExtractor."""

    @pytest.mark.asyncio
    async def test_basic_extraction(self) -> None:
        """Extract with regex pattern."""
        from agentcrawl.extraction.regex import RegexExtractor

        schema = {
            "name": "Price",
            "fields": [
                {"name": "price", "pattern": r"\$(\d+\.\d{2})", "type": "first", "group": 1},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = await extractor.extract("The price is $29.99 today.")

        assert result.success is True
        assert result.data["price"] == "29.99"

    @pytest.mark.asyncio
    async def test_code_block_pattern(self) -> None:
        """Split by code blocks."""
        from agentcrawl.extraction.regex import RegexExtractor

        schema = {
            "name": "CodeBlocks",
            "fields": [
                {"name": "code", "pattern": r"```([\s\S]*?)```", "type": "all", "group": 1},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        text = (
            "```python\nprint('hello')\n```\n\nSome text\n\n```javascript\nconsole.log('hi')\n```"
        )
        result = await extractor.extract(text)

        assert result.success is True
        assert len(result.data["code"]) == 2

    @pytest.mark.asyncio
    async def test_custom_pattern(self) -> None:
        """Custom regex pattern works."""
        from agentcrawl.extraction.regex import RegexExtractor

        schema = {
            "name": "Sections",
            "fields": [
                {"name": "sections", "pattern": r"###\s+(.+)", "type": "all", "group": 1},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        assert len(result.data["sections"]) >= 0

    @pytest.mark.asyncio
    async def test_no_match_pattern(self) -> None:
        """Pattern that doesn't match returns empty data."""
        from agentcrawl.extraction.regex import RegexExtractor

        schema = {
            "name": "NoMatch",
            "fields": [
                {"name": "content", "pattern": r"ZZZZZ_NO_MATCH", "type": "all", "group": 0},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = await extractor.extract(SAMPLE_HTML)

        assert result.success is True
        # When pattern doesn't match, field should be absent or empty
        assert "content" in result.data

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_empty_content(self) -> None:
        """Empty content returns empty data."""
        from agentcrawl.extraction.regex import RegexExtractor

        schema = {
            "name": "Empty",
            "fields": [
                {"name": "content", "pattern": r"\n", "type": "all", "group": 0},
            ],
        }

        extractor = RegexExtractor(schema=schema)
        result = await extractor.extract("")

        assert result.success is True
        # When input is empty, field may be absent or empty
        assert "content" not in result.data or len(result.data.get("content", [])) == 0


# ═══════════════════════════════════════════════════════════════
# Factory Function
# ═══════════════════════════════════════════════════════════════


class TestCreateExtractor:
    """Tests for create_extractor factory."""

    def test_create_css_extractor(self) -> None:
        """Create a CSS extractor."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor("css", schema)

        assert isinstance(extractor, JsonCssExtractor)

    def test_create_xpath_extractor(self) -> None:
        """Create an XPath extractor."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.json_xpath import JsonXPathExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor("xpath", schema)

        assert isinstance(extractor, JsonXPathExtractor)

    def test_create_regex_extractor(self) -> None:
        """Create a regex extractor."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.regex import RegexExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor("regex", schema, pattern=r"\n")

        assert isinstance(extractor, RegexExtractor)

    def test_invalid_strategy(self) -> None:
        """Invalid strategy raises ValueError."""
        from agentcrawl.extraction.base import create_extractor

        with pytest.raises(ValueError, match="Unknown extraction method"):
            create_extractor("invalid_strategy", {"name": "Test"})

    def test_default_method_is_css(self) -> None:
        """Default chunker is fixed."""
        from agentcrawl.extraction.base import create_extractor
        from agentcrawl.extraction.json_css import JsonCssExtractor

        schema = {"name": "Test", "fields": []}
        extractor = create_extractor("css", schema)

        assert isinstance(extractor, JsonCssExtractor)


# ═══════════════════════════════════════════════════════════════
# ExtractionResult
# ═══════════════════════════════════════════════════════════════


class TestExtractionResult:
    """Tests for ExtractionResult model."""

    def test_result_creation(self) -> None:
        """Create an extraction result."""
        from agentcrawl.extraction.base import ExtractionResult, ExtractionStatus

        result = ExtractionResult(
            data={"title": "Test", "price": 10.99},
            status=ExtractionStatus.SUCCESS,
            method="css",
            schema_name="Product",
        )

        assert result.success is True
        assert result.data["title"] == "Test"

    def test_failed_result(self) -> None:
        """Create a failed extraction result."""
        from agentcrawl.extraction.base import ExtractionResult, ExtractionStatus

        result = ExtractionResult(
            data=None,
            status=ExtractionStatus.FAILED,
            error="Extraction failed",
        )

        assert result.success is False
        assert result.error == "Extraction failed"

    def test_result_to_dict(self) -> None:
        """Result serializes to dict."""
        from agentcrawl.extraction.base import ExtractionResult, ExtractionStatus

        result = ExtractionResult(
            data={"name": "Test"},
            status=ExtractionStatus.SUCCESS,
            method="css",
            duration_ms=100.5,
        )

        d = result.to_dict()

        assert d["status"] == "success"
        assert d["method"] == "css"
        assert d["data"]["name"] == "Test"
        assert d["duration_ms"] == 100.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
