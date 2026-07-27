"""
AgentCrawl — Content Processing Layer
========================================

Content extraction, filtering, chunking, and citation management
for LLM-optimized output. Transforms raw HTML into clean Markdown,
filters noise, chunks for RAG, and extracts citations.

Modules:
    html_parser       — Fast lxml-based HTML parsing and extraction
    html_to_markdown  — HTML to Markdown conversion
    content_filter    — Content filter ABC and Pruning filter
    bm25_filter       — BM25 query-based relevance filter
    pruning_filter    — Advanced pruning with boilerplate detection
    chunker           — Chunker ABC and standard strategies
    regex_chunker     — Extended regex chunking with presets
    sentence_chunker  — Multilingual sentence-aware chunking
    topic_chunker     — Heading/topic-based chunking with hierarchy
    citation          — Citation extraction and management

Quick Start:
    # Parse HTML
    from agentcrawl.content import HTMLParser

    parser = HTMLParser(html, base_url="https://example.com")
    content = parser.get_main_content()
    meta = parser.get_metadata()
    links = parser.get_links()

    # Convert to Markdown
    from agentcrawl.content import HTMLToMarkdown, html_to_markdown

    converter = HTMLToMarkdown()
    markdown = converter.convert(html)

    # Filter content
    from agentcrawl.content import PruningContentFilter, BM25ContentFilter

    filter = PruningContentFilter(threshold=0.4)
    result = filter.apply(markdown)

    filter = BM25ContentFilter(query="machine learning", threshold=1.0)
    result = filter.apply(markdown)

    # Chunk for RAG
    from agentcrawl.content import TopicChunker, create_chunker

    chunker = TopicChunker(max_chunk_size=1000, overlap=200)
    result = chunker.chunk(markdown)

    chunker = create_chunker("sentence", max_chunk_size=500)

    # Extract citations
    from agentcrawl.content import CitationExtractor

    extractor = CitationExtractor()
    result = extractor.extract(markdown)
    print(result.format_bibliography("markdown"))
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# HTML Parser
# ──────────────────────────────────────────────────────────────

from agentcrawl.content.html_parser import (
    HTMLParser,
    HeadingInfo,
    ImageInfo,
    LinkInfo,
    MainContent,
    PageMetadata,
)

# ──────────────────────────────────────────────────────────────
# HTML to Markdown
# ──────────────────────────────────────────────────────────────

from agentcrawl.content.html_to_markdown import (
    HTMLToMarkdown,
    MarkdownOptions,
    clean_markdown,
    html_to_markdown,
)

# ──────────────────────────────────────────────────────────────
# Content Filters
# ──────────────────────────────────────────────────────────────

from agentcrawl.content.content_filter import (
    ContentBlock,
    ContentFilter,
    ContentFilterResult,
    PruningContentFilter,
    create_content_filter,
    create_content_filter_from_config,
)

from agentcrawl.content.bm25_filter import (
    BM25ContentFilter,
    BM25Scorer,
    BM25Tokenizer,
    FilterResult,
    TextBlock,
)

from agentcrawl.content.pruning_filter import (
    AdvancedPruningFilter,
    BoilerplateDetector,
    ContentDensityAnalyzer,
    DensityReport,
    create_pruning_filter,
)

# ──────────────────────────────────────────────────────────────
# Chunkers
# ──────────────────────────────────────────────────────────────

from agentcrawl.content.chunker import (
    Chunk,
    Chunker,
    ChunkResult,
    FixedChunker,
    MarkdownChunker,
    RegexChunker,
    SentenceChunker,
    TopicChunker,
    create_chunker,
    create_chunker_from_config,
)

from agentcrawl.content.regex_chunker import (
    AdvancedRegexChunker,
    PrebuiltPatterns,
    chunk_by_preset,
    chunk_by_regex,
    test_pattern,
    validate_pattern,
)

from agentcrawl.content.sentence_chunker import (
    AdvancedSentenceChunker,
    SentenceTokenizer,
    TokenCounter,
    chunk_by_sentences,
    count_tokens,
    detect_language,
    split_sentences,
)

from agentcrawl.content.topic_chunker import (
    AdvancedTopicChunker,
    HeadingHierarchy,
    HeadingNode,
    TopicSection,
    TopicSimilarityDetector,
    chunk_by_topics,
    extract_sections,
    generate_toc,
)

# ──────────────────────────────────────────────────────────────
# Citations
# ──────────────────────────────────────────────────────────────

from agentcrawl.content.citation import (
    BibliographyFormat,
    Citation,
    CitationExtractor,
    CitationManager,
    CitationResult,
    CitationSource,
)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # HTML Parser
    "HTMLParser",
    "PageMetadata",
    "LinkInfo",
    "HeadingInfo",
    "ImageInfo",
    "MainContent",
    # HTML to Markdown
    "HTMLToMarkdown",
    "MarkdownOptions",
    "html_to_markdown",
    "clean_markdown",
    # Content Filters
    "ContentFilter",
    "ContentBlock",
    "ContentFilterResult",
    "PruningContentFilter",
    "AdvancedPruningFilter",
    "BM25ContentFilter",
    "BM25Tokenizer",
    "BM25Scorer",
    "TextBlock",
    "FilterResult",
    "BoilerplateDetector",
    "ContentDensityAnalyzer",
    "DensityReport",
    "create_content_filter",
    "create_content_filter_from_config",
    "create_pruning_filter",
    # Chunkers
    "Chunker",
    "Chunk",
    "ChunkResult",
    "FixedChunker",
    "SentenceChunker",
    "RegexChunker",
    "TopicChunker",
    "MarkdownChunker",
    "AdvancedRegexChunker",
    "AdvancedSentenceChunker",
    "AdvancedTopicChunker",
    "PrebuiltPatterns",
    "SentenceTokenizer",
    "TokenCounter",
    "HeadingHierarchy",
    "HeadingNode",
    "TopicSection",
    "TopicSimilarityDetector",
    "create_chunker",
    "create_chunker_from_config",
    "chunk_by_regex",
    "chunk_by_preset",
    "chunk_by_sentences",
    "chunk_by_topics",
    "split_sentences",
    "count_tokens",
    "detect_language",
    "validate_pattern",
    "test_pattern",
    "generate_toc",
    "extract_sections",
    # Citations
    "CitationExtractor",
    "CitationManager",
    "Citation",
    "CitationResult",
    "CitationSource",
    "BibliographyFormat",
]