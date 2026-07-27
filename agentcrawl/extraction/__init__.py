"""
AgentCrawl — Extraction Strategies Layer
============================================

Structured data extraction from web content using multiple
strategies: LLM-powered, CSS selectors, XPath, cosine similarity,
regex patterns, and table parsing.

Strategies:
    LLMExtractor        — LLM-powered extraction (any schema)
    JsonCssExtractor    — CSS selector-based extraction
    JsonXPathExtractor  — XPath expression-based extraction
    CosineExtractor     — Similarity-based clustering extraction
    RegexExtractor      — Regex pattern extraction
    MarkdownExtractor   — Standard Markdown extraction
    FitMarkdownExtractor — LLM-optimized Markdown extraction
    TableExtractor      — HTML table extraction

Utilities:
    SchemaBuilder       — Fluent schema construction API
    SchemaTemplate      — Pre-built schema templates
    SchemaConverter     — Cross-format schema conversion
    SchemaValidator     — Schema validation
    create_extractor    — Factory function

Quick Start:
    # LLM extraction with Pydantic schema
    from agentcrawl.extraction import LLMExtractor
    from pydantic import BaseModel

    class Product(BaseModel):
        name: str
        price: float

    extractor = LLMExtractor(schema=Product)
    result = await extractor.extract(markdown=content)
    print(result.data)  # Product instance

    # CSS extraction
    from agentcrawl.extraction import JsonCssExtractor

    schema = {
        "name": "Product",
        "baseSelector": "div.product",
        "fields": [
            {"name": "title", "selector": "h2", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
        ]
    }
    extractor = JsonCssExtractor(schema=schema)
    result = await extractor.extract(html=html)

    # Build schema with fluent API
    from agentcrawl.extraction import SchemaBuilder

    schema = (
        SchemaBuilder("Product")
        .base_selector("div.product")
        .field("title", selector="h2", type="text")
        .field("price", selector=".price", type="text")
        .build()
    )

    # Factory function
    from agentcrawl.extraction import create_extractor
    extractor = create_extractor("llm", schema=Product)
    extractor = create_extractor("css", schema=css_schema)
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatus,
    ExtractionStrategy,
    SchemaResolver,
    create_extractor,
    create_extractor_from_config,
)

# ──────────────────────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────────────────────

from agentcrawl.extraction.llm import LLMExtractor
from agentcrawl.extraction.json_css import JsonCssExtractor
from agentcrawl.extraction.json_xpath import JsonXPathExtractor
from agentcrawl.extraction.cosine import (
    Cluster,
    CosineExtractor,
    ElementInfo,
    HTMLElementParser,
    TFIDFVectorizer,
)
from agentcrawl.extraction.regex import RegexExtractor
from agentcrawl.extraction.markdown import MarkdownExtractor
from agentcrawl.extraction.fit_markdown import FitMarkdownExtractor
from agentcrawl.extraction.table import (
    ColumnTypeInferrer,
    TableColumn,
    TableData,
    TableExtractor,
)

# ──────────────────────────────────────────────────────────────
# Schema Utilities
# ──────────────────────────────────────────────────────────────

from agentcrawl.extraction.schema import (
    FieldDef,
    SchemaBuilder,
    SchemaConverter,
    SchemaTemplate,
    SchemaValidator,
    infer_schema_from_html,
)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Base
    "ExtractionStrategy",
    "ExtractionResult",
    "ExtractionConfig",
    "ExtractionMethod",
    "ExtractionStatus",
    "SchemaResolver",
    "create_extractor",
    "create_extractor_from_config",
    # Strategies
    "LLMExtractor",
    "JsonCssExtractor",
    "JsonXPathExtractor",
    "CosineExtractor",
    "TFIDFVectorizer",
    "HTMLElementParser",
    "ElementInfo",
    "Cluster",
    "RegexExtractor",
    "MarkdownExtractor",
    "FitMarkdownExtractor",
    "TableExtractor",
    "TableData",
    "TableColumn",
    "ColumnTypeInferrer",
    # Schema
    "SchemaBuilder",
    "SchemaTemplate",
    "SchemaConverter",
    "SchemaValidator",
    "FieldDef",
    "infer_schema_from_html",
]