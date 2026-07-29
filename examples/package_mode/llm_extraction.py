"""
AgentCrawl — LLM Extraction Examples
========================================

Examples of structured data extraction using LLM, CSS, XPath,
Cosine, Regex, and Table strategies.

Prerequisites:
    pip install "agentcrawl[llm]"
    playwright install chromium

    # Set your LLM API key
    export OPENAI_API_KEY="sk-..."

Run:
    python examples/package_mode/llm_extraction.py
"""

from __future__ import annotations

import asyncio
import json

# ══════════════════════════════════════════════════════════════
# Example 1: LLM Extraction with Pydantic Schema
# ══════════════════════════════════════════════════════════════

async def example_llm_pydantic() -> None:
    """Extract structured data using LLM + Pydantic model."""
    from pydantic import BaseModel

    from agentcrawl import CrawlEngine, LLMConfig, LLMExtractor

    print("\n[1] LLM Extraction (Pydantic Schema)")
    print("-" * 45)

    # Define schema
    class PageInfo(BaseModel):
        title: str
        description: str
        main_topic: str
        key_points: list[str]

    # Create extractor
    extractor = LLMExtractor(
        schema=PageInfo,
        llm_config=LLMConfig(provider="openai/gpt-4o-mini"),
        max_content_tokens=4000,
    )

    # Scrape and extract
    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")

        extraction = await extractor.extract(
            html=result.html,
            markdown=result.markdown,
            url=result.url,
        )

        print(f"  Status: {extraction.status}")
        print(f"  Method: {extraction.method}")
        print(f"  Duration: {extraction.duration_ms:.0f}ms")

        if extraction.success and extraction.data:
            data = extraction.data
            if hasattr(data, "model_dump"):
                data = data.model_dump()
            print(f"  Data: {json.dumps(data, indent=4, ensure_ascii=False)}")

        if extraction.token_usage:
            print(f"  Tokens: {extraction.token_usage}")


# ══════════════════════════════════════════════════════════════
# Example 2: LLM Extraction with JSON Schema
# ══════════════════════════════════════════════════════════════

async def example_llm_json_schema() -> None:
    """Extract using a JSON Schema dictionary."""
    from agentcrawl import CrawlEngine, LLMExtractor

    print("\n[2] LLM Extraction (JSON Schema)")
    print("-" * 45)

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Page title"},
            "summary": {"type": "string", "description": "Brief summary"},
            "links_count": {"type": "integer", "description": "Number of links"},
        },
        "required": ["title", "summary"],
    }

    extractor = LLMExtractor(schema=schema)

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        extraction = await extractor.extract(markdown=result.markdown)

        print(f"  Status: {extraction.status}")
        if extraction.success:
            print(f"  Data: {json.dumps(extraction.data, indent=4)}")


# ══════════════════════════════════════════════════════════════
# Example 3: LLM Extraction with Custom Instructions
# ══════════════════════════════════════════════════════════════

async def example_llm_instructions() -> None:
    """Extract with additional instructions for the LLM."""
    from pydantic import BaseModel

    from agentcrawl import CrawlEngine, LLMExtractor

    print("\n[3] LLM Extraction (Custom Instructions)")
    print("-" * 45)

    class Analysis(BaseModel):
        page_type: str
        language: str
        readability_score: int
        target_audience: str

    extractor = LLMExtractor(
        schema=Analysis,
        instructions=(
            "Analyze the page content carefully. "
            "For readability_score, use a scale of 1-10 (10 = easiest to read). "
            "For page_type, choose from: informational, commercial, blog, documentation, other."
        ),
    )

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        extraction = await extractor.extract(markdown=result.markdown)

        if extraction.success and extraction.data:
            data = extraction.data
            if hasattr(data, "model_dump"):
                data = data.model_dump()
            print(f"  Data: {json.dumps(data, indent=4, ensure_ascii=False)}")


# ══════════════════════════════════════════════════════════════
# Example 4: CSS Selector Extraction
# ══════════════════════════════════════════════════════════════

async def example_css_extraction() -> None:
    """Extract using CSS selectors (no LLM cost)."""
    from agentcrawl import CrawlEngine, JsonCssExtractor

    print("\n[4] CSS Selector Extraction")
    print("-" * 45)

    schema = {
        "name": "Page Info",
        "fields": [
            {"name": "title", "selector": "h1", "type": "text"},
            {"name": "heading2", "selector": "h2", "type": "text"},
            {"name": "first_link_text", "selector": "a", "type": "text"},
            {"name": "first_link_url", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "paragraphs", "selector": "p", "type": "list", "fields": [
                {"name": "text", "selector": "", "type": "text"},
            ]},
        ],
    }

    extractor = JsonCssExtractor(schema=schema)

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        extraction = await extractor.extract(html=result.html)

        print(f"  Status: {extraction.status}")
        print(f"  Method: {extraction.method}")
        print(f"  Duration: {extraction.duration_ms:.0f}ms")

        if extraction.success:
            print(f"  Data: {json.dumps(extraction.data, indent=4, ensure_ascii=False)}")


# ══════════════════════════════════════════════════════════════
# Example 5: XPath Extraction
# ══════════════════════════════════════════════════════════════

async def example_xpath_extraction() -> None:
    """Extract using XPath expressions."""
    from agentcrawl import CrawlEngine, JsonXPathExtractor

    print("\n[5] XPath Extraction")
    print("-" * 45)

    schema = {
        "name": "Page Info",
        "fields": [
            {"name": "title", "xpath": "//h1", "type": "text"},
            {"name": "all_headings", "xpath": "//h1 | //h2 | //h3", "type": "list"},
            {"name": "link_href", "xpath": "//a/@href", "type": "text"},
            {"name": "paragraph_count", "xpath": "count(//p)", "type": "text"},
        ],
    }

    extractor = JsonXPathExtractor(schema=schema)

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        extraction = await extractor.extract(html=result.html)

        print(f"  Status: {extraction.status}")
        if extraction.success:
            print(f"  Data: {json.dumps(extraction.data, indent=4, ensure_ascii=False)}")


# ══════════════════════════════════════════════════════════════
# Example 6: Regex Extraction
# ══════════════════════════════════════════════════════════════

async def example_regex_extraction() -> None:
    """Extract using regex patterns."""
    from agentcrawl import CrawlEngine, RegexExtractor

    print("\n[6] Regex Extraction")
    print("-" * 45)

    schema = {
        "name": "Pattern Match",
        "fields": [
            {"name": "urls", "pattern": r"https?://[^\s<>\"']+", "type": "all"},
            {"name": "emails", "pattern": r"[\w.+-]+@[\w-]+\.[\w.]+", "type": "all"},
            {"name": "domain", "pattern": r"https?://(?:www\.)?([^/\s]+)", "type": "first", "group": 1},
        ],
    }

    extractor = RegexExtractor(schema=schema)

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        extraction = await extractor.extract(
            html=result.html,
            markdown=result.markdown,
        )

        print(f"  Status: {extraction.status}")
        if extraction.success:
            print(f"  Data: {json.dumps(extraction.data, indent=4, ensure_ascii=False)}")


# ══════════════════════════════════════════════════════════════
# Example 7: Table Extraction
# ══════════════════════════════════════════════════════════════

async def example_table_extraction() -> None:
    """Extract data from HTML tables."""
    from agentcrawl import TableExtractor

    print("\n[7] Table Extraction")
    print("-" * 45)

    # Use a page with tables
    html_with_table = """
    <html><body>
    <table id="pricing">
        <thead>
            <tr><th>Plan</th><th>Price</th><th>Features</th></tr>
        </thead>
        <tbody>
            <tr><td>Free</td><td>$0</td><td>Basic features</td></tr>
            <tr><td>Pro</td><td>$29</td><td>All features</td></tr>
            <tr><td>Enterprise</td><td>$99</td><td>Custom</td></tr>
        </tbody>
    </table>
    </body></html>
    """

    extractor = TableExtractor(
        output_format="dict",
        infer_types=True,
    )

    extraction = await extractor.extract(html=html_with_table)

    print(f"  Status: {extraction.status}")
    if extraction.success and extraction.data:
        for table in extraction.data:
            print(f"  Table: {table.get('row_count', 0)} rows x {table.get('col_count', 0)} cols")
            print(f"  Headers: {table.get('headers', [])}")
            for row in table.get("rows", []):
                print(f"    {row}")


# ══════════════════════════════════════════════════════════════
# Example 8: Schema Builder
# ══════════════════════════════════════════════════════════════

async def example_schema_builder() -> None:
    """Build extraction schemas with the fluent API."""
    from agentcrawl import CrawlEngine, JsonCssExtractor, SchemaBuilder

    print("\n[8] Schema Builder")
    print("-" * 45)

    # Build schema
    schema = (
        SchemaBuilder("PageContent", method="css")
        .text_field("title", selector="h1")
        .text_field("subtitle", selector="h2")
        .link_field("main_link", selector="a")
        .field("paragraph", selector="p", type="text")
        .build()
    )

    print(f"  Schema: {json.dumps(schema, indent=4)}")

    # Use it
    extractor = JsonCssExtractor(schema=schema)

    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        extraction = await extractor.extract(html=result.html)

        if extraction.success:
            print(f"\n  Extracted: {json.dumps(extraction.data, indent=4, ensure_ascii=False)}")


# ══════════════════════════════════════════════════════════════
# Example 9: Schema Templates
# ══════════════════════════════════════════════════════════════

async def example_schema_templates() -> None:
    """Use pre-built schema templates."""
    from agentcrawl import SchemaTemplate

    print("\n[9] Schema Templates")
    print("-" * 45)

    templates = SchemaTemplate.list_templates()
    print("  Available templates:")
    for t in templates:
        print(f"    • {t['name']}: {t['description']}")

    # Use a template
    product_schema = SchemaTemplate.product()
    article_schema = SchemaTemplate.article()

    print(f"\n  Product schema fields: {[f['name'] for f in product_schema.get('fields', [])]}")
    print(f"  Article schema fields: {[f['name'] for f in article_schema.get('fields', [])]}")


# ══════════════════════════════════════════════════════════════
# Example 10: Factory Function
# ══════════════════════════════════════════════════════════════

async def example_factory() -> None:
    """Create extractors with the factory function."""
    from pydantic import BaseModel

    from agentcrawl import CrawlEngine, create_extractor

    print("\n[10] Extractor Factory")
    print("-" * 45)

    class SimpleData(BaseModel):
        title: str
        content: str

    # Create different extractors
    llm_extractor = create_extractor("llm", schema=SimpleData)
    css_extractor = create_extractor("css", schema={
        "name": "Simple",
        "fields": [
            {"name": "title", "selector": "h1", "type": "text"},
        ],
    })
    regex_extractor = create_extractor("regex", patterns={
        "urls": r"https?://[^\s]+",
    })

    print(f"  LLM extractor: {llm_extractor}")
    print(f"  CSS extractor: {css_extractor}")
    print(f"  Regex extractor: {regex_extractor}")

    # Use CSS extractor
    async with CrawlEngine.default() as engine:
        result = await engine.scrape("https://example.com")
        extraction = await css_extractor.extract(html=result.html)
        print(f"\n  CSS result: {extraction.data}")


# ══════════════════════════════════════════════════════════════
# Example 11: Engine Extract (Convenience)
# ══════════════════════════════════════════════════════════════

async def example_engine_extract() -> None:
    """Use engine.extract() convenience method."""
    from pydantic import BaseModel

    from agentcrawl import CrawlEngine

    print("\n[11] Engine Extract")
    print("-" * 45)

    class PageSummary(BaseModel):
        title: str
        summary: str
        word_count_estimate: int

    async with CrawlEngine.default() as engine:
        result = await engine.extract(
            "https://example.com",
            schema=PageSummary,
            method="llm",
        )

        print(f"  Success: {result.success}")
        if result.extracted_data:
            data = result.extracted_data
            if hasattr(data, "model_dump"):
                data = data.model_dump()
            print(f"  Data: {json.dumps(data, indent=4, ensure_ascii=False)}")


# ══════════════════════════════════════════════════════════════
# Example 12: Extraction with Validation
# ══════════════════════════════════════════════════════════════

async def example_validation() -> None:
    """Handle extraction validation errors."""
    from pydantic import BaseModel, Field

    from agentcrawl import LLMExtractor

    print("\n[12] Extraction Validation")
    print("-" * 45)

    class StrictProduct(BaseModel):
        name: str = Field(min_length=1)
        price: float = Field(ge=0)
        in_stock: bool

    extractor = LLMExtractor(schema=StrictProduct)

    # Extract from content that may not match schema
    extraction = await extractor.extract(
        markdown="This is a page about Python programming. No products here.",
    )

    print(f"  Status: {extraction.status}")
    print(f"  Validation errors: {extraction.validation_errors}")
    print(f"  Data: {extraction.data}")


# ══════════════════════════════════════════════════════════════
# Example 13: Cost Tracking
# ══════════════════════════════════════════════════════════════

async def example_cost_tracking() -> None:
    """Track LLM token usage and costs."""
    from pydantic import BaseModel

    from agentcrawl import LLMConfig, LLMExtractor

    print("\n[13] Cost Tracking")
    print("-" * 45)

    class Info(BaseModel):
        title: str

    extractor = LLMExtractor(
        schema=Info,
        llm_config=LLMConfig(provider="openai/gpt-4o-mini"),
    )

    # Run multiple extractions
    for i in range(3):
        await extractor.extract(markdown=f"Sample content {i} " * 100)

    print(f"  Total calls: {extractor.total_calls}")
    print(f"  Total input tokens: {extractor.total_input_tokens}")
    print(f"  Total output tokens: {extractor.total_output_tokens}")
    print(f"  Estimated cost: ${extractor.estimated_cost:.6f}")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

async def main() -> None:
    """Run all examples."""
    print("=" * 55)
    print("  AgentCrawl — LLM Extraction Examples")
    print("=" * 55)

    # Non-LLM examples (always work)
    await example_css_extraction()
    await example_xpath_extraction()
    await example_regex_extraction()
    await example_table_extraction()
    await example_schema_builder()
    await example_schema_templates()
    await example_factory()

    # LLM examples (require API key)
    print("\n" + "-" * 55)
    print("  LLM Examples (require OPENAI_API_KEY)")
    print("-" * 55)

    try:
        await example_llm_pydantic()
        await example_llm_json_schema()
        await example_llm_instructions()
        await example_engine_extract()
        await example_validation()
        await example_cost_tracking()
    except Exception as e:
        print(f"\n  Skipped LLM examples: {e}")
        print("  Set OPENAI_API_KEY to run these examples.")

    print("\n" + "=" * 55)
    print("  All examples completed!")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
