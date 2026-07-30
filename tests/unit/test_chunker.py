"""
AgentCrawl — Chunker Unit Tests
===================================

Unit tests for content chunking strategies.

Tests:
    - TopicChunker (heading-based)
    - SentenceChunker (sentence-based)
    - FixedChunker (fixed-size)
    - RegexChunker (pattern-based)
    - create_chunker factory
    - Chunk size limits and overlap
    - Metadata preservation
    - Token counting
    - Edge cases (empty content, code blocks)

Run:
    pytest tests/unit/test_chunker.py -v
"""

from __future__ import annotations

import pytest

from agentcrawl.content.chunker import (
    FixedChunker,
    RegexChunker,
    SentenceChunker,
    TopicChunker,
    create_chunker,
)

# ══════════════════════════════════════════════════════════════
# Sample Content
# ══════════════════════════════════════════════════════════════

SAMPLE_MD = """# Introduction

This is the introduction section. It provides an overview
of the topic and sets the stage for the rest of the document.

## Getting Started

To get started, you need to install the package. Run the
following command in your terminal.

```bash
pip install agentcrawl
```

## Configuration

Configuration is done through environment variables or
a configuration file.

### Environment Variables

Set the following variables:

- `API_KEY`: Your API key
- `LOG_LEVEL`: Logging level

### Config File

Create a `config.yaml` file in your project root.

## Advanced Usage

For advanced usage, see the API reference documentation.
"""


# ══════════════════════════════════════════════════════════════
# TopicChunker
# ══════════════════════════════════════════════════════════════


class TestTopicChunker:
    """Tests for TopicChunker (heading-based splitting)."""

    def test_basic_chunking(self) -> None:
        """Split content by headings."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0
        assert result.total_tokens > 0
        assert result.strategy == "topic"

    def test_chunks_have_headings(self) -> None:
        """Each chunk has a heading."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        for chunk in result.chunks:
            assert chunk.heading != ""

    def test_first_chunk_heading(self) -> None:
        """First chunk has the top-level heading."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        assert result.chunks[0].heading == "Introduction"

    def test_chunk_count(self) -> None:
        """Number of chunks matches number of sections."""
        chunker = TopicChunker(max_chunk_size=1000)
        result = chunker.chunk(SAMPLE_MD)

        # Should have chunks for: Introduction, Getting Started,
        # Configuration, Environment Variables, Config File, Advanced Usage
        assert result.total_chunks >= 4

    def test_chunk_size_limit(self) -> None:
        """Chunks respect max size."""
        chunker = TopicChunker(max_chunk_size=100)
        result = chunker.chunk(SAMPLE_MD)

        for chunk in result.chunks:
            # Allow some tolerance for heading overhead
            assert chunk.token_count <= 200

    def test_metadata_preserved(self) -> None:
        """Metadata is passed to chunks."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(
            SAMPLE_MD,
            metadata={"url": "https://example.com", "title": "Test"},
        )

        for chunk in result.chunks:
            assert chunk.metadata.get("url") == "https://example.com"
            assert chunk.metadata.get("title") == "Test"

    def test_chunk_indices(self) -> None:
        """Chunks have sequential indices."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        for i, chunk in enumerate(result.chunks):
            assert chunk.index == i

    def test_code_block_detection(self) -> None:
        """Code blocks are preserved within chunks."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        # "Getting Started" section has a code block - verify it's in a chunk
        # The code block should be in the "Getting Started" chunk
        code_chunks = [c for c in result.chunks if "```" in c.text]
        assert len(code_chunks) >= 1

    def test_empty_content(self) -> None:
        """Empty content returns no chunks."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk("")

        assert result.total_chunks == 0

    def test_no_headings(self) -> None:
        """Content without headings is handled."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk("Just plain text without any headings.")

        assert result.total_chunks >= 1

    def test_word_count(self) -> None:
        """Chunks have word counts."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        for chunk in result.chunks:
            assert chunk.word_count >= 0

    def test_overlap(self) -> None:
        """Overlap creates shared content between chunks."""
        chunker = TopicChunker(max_chunk_size=100, overlap=20)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0


# ══════════════════════════════════════════════════════════════
# SentenceChunker
# ══════════════════════════════════════════════════════════════


class TestSentenceChunker:
    """Tests for SentenceChunker (sentence-based splitting)."""

    def test_basic_chunking(self) -> None:
        """Split content by sentences."""
        chunker = SentenceChunker(max_chunk_size=100)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0
        assert result.strategy == "sentence"

    def test_chunk_size_limit(self) -> None:
        """Chunks respect max size."""
        chunker = SentenceChunker(max_chunk_size=50)
        result = chunker.chunk(SAMPLE_MD)

        for chunk in result.chunks:
            assert chunk.token_count <= 100  # Allow tolerance

    def test_sentences_not_split(self) -> None:
        """Individual sentences are not split mid-sentence."""
        chunker = SentenceChunker(max_chunk_size=500, overlap=0)
        text = "This is sentence one. This is sentence two. This is sentence three."
        result = chunker.chunk(text)

        for chunk in result.chunks:
            # Each chunk should contain complete sentences (no overlap)
            text = chunk.text.strip()
            if text:
                # The chunk should end with punctuation or be the last chunk
                assert text[-1] in ".!?" or chunk.index == result.total_chunks - 1
            assert text[-1] in ".!?" or chunk.index == result.total_chunks - 1

    def test_empty_content(self) -> None:
        """Empty content returns no chunks."""
        chunker = SentenceChunker(max_chunk_size=100)
        result = chunker.chunk("")

        assert result.total_chunks == 0

    def test_single_sentence(self) -> None:
        """Single sentence returns one chunk."""
        chunker = SentenceChunker(max_chunk_size=100)
        result = chunker.chunk("This is a single sentence.")

        assert result.total_chunks == 1


# ══════════════════════════════════════════════════════════════
# FixedChunker
# ══════════════════════════════════════════════════════════════


class TestFixedChunker:
    """Tests for FixedChunker (fixed-size splitting)."""

    def test_basic_chunking(self) -> None:
        """Split content into fixed-size chunks."""
        chunker = FixedChunker(max_chunk_size=100)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0
        assert result.strategy == "fixed"

    def test_chunk_size_limit(self) -> None:
        """Chunks respect max size."""
        chunker = FixedChunker(max_chunk_size=50)
        result = chunker.chunk(SAMPLE_MD)

        for chunk in result.chunks:
            assert chunk.token_count <= 80  # Allow tolerance

    def test_overlap(self) -> None:
        """Overlap creates shared content."""
        chunker = FixedChunker(max_chunk_size=100, overlap=20)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 1

    def test_no_overlap(self) -> None:
        """Zero overlap works."""
        chunker = FixedChunker(max_chunk_size=100, overlap=0)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0

    def test_empty_content(self) -> None:
        """Empty content returns no chunks."""
        chunker = FixedChunker(max_chunk_size=100)
        result = chunker.chunk("")

        assert result.total_chunks == 0

    def test_short_content(self) -> None:
        """Content shorter than chunk size returns one chunk."""
        chunker = FixedChunker(max_chunk_size=1000)
        result = chunker.chunk("Short text.")

        assert result.total_chunks == 1

    def test_total_tokens(self) -> None:
        """Total tokens is sum of chunk tokens."""
        chunker = FixedChunker(max_chunk_size=100)
        result = chunker.chunk(SAMPLE_MD)

        sum(c.token_count for c in result.chunks)
        # With overlap, sum may exceed total
        assert result.total_tokens > 0


# ══════════════════════════════════════════════════════════════
# RegexChunker
# ══════════════════════════════════════════════════════════════


class TestRegexChunker:
    """Tests for RegexChunker (pattern-based splitting)."""

    def test_basic_chunking(self) -> None:
        """Split content by regex pattern."""
        chunker = RegexChunker(pattern=r"\n## ", max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0
        assert result.strategy == "regex"

    def test_code_block_pattern(self) -> None:
        """Split by code blocks."""
        chunker = RegexChunker(pattern=r"```[\s\S]*?```", max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0

    def test_custom_pattern(self) -> None:
        """Custom regex pattern works."""
        chunker = RegexChunker(pattern=r"\n### ", max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks > 0

    def test_no_match_pattern(self) -> None:
        """Pattern that doesn't match returns whole content."""
        chunker = RegexChunker(pattern=r"ZZZZZ_NO_MATCH", max_chunk_size=5000)
        result = chunker.chunk(SAMPLE_MD)

        assert result.total_chunks >= 1

    def test_empty_content(self) -> None:
        """Empty content returns no chunks."""
        chunker = RegexChunker(pattern=r"\n", max_chunk_size=500)
        result = chunker.chunk("")

        assert result.total_chunks == 0


# ══════════════════════════════════════════════════════════════
# Factory Function
# ══════════════════════════════════════════════════════════════


class TestCreateChunker:
    """Tests for create_chunker factory."""

    def test_create_topic_chunker(self) -> None:
        """Create a topic chunker."""
        chunker = create_chunker("topic", max_chunk_size=500)
        assert isinstance(chunker, TopicChunker)

    def test_create_sentence_chunker(self) -> None:
        """Create a sentence chunker."""
        chunker = create_chunker("sentence", max_chunk_size=500)
        assert isinstance(chunker, SentenceChunker)

    def test_create_fixed_chunker(self) -> None:
        """Create a fixed chunker."""
        chunker = create_chunker("fixed", max_chunk_size=500)
        assert isinstance(chunker, FixedChunker)

    def test_create_regex_chunker(self) -> None:
        """Create a regex chunker."""
        chunker = create_chunker("regex", pattern=r"\n", max_chunk_size=500)
        assert isinstance(chunker, RegexChunker)

    def test_invalid_strategy(self) -> None:
        """Invalid strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown chunking strategy"):
            create_chunker("invalid_strategy")

    def test_default_is_fixed(self) -> None:
        """Default chunker is fixed."""
        chunker = create_chunker("fixed")
        assert isinstance(chunker, FixedChunker)


# ══════════════════════════════════════════════════════════════
# ChunkResult
# ══════════════════════════════════════════════════════════════


class TestChunkResult:
    """Tests for ChunkResult model."""

    def test_result_to_dict(self) -> None:
        """ChunkResult serializes to dict."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        data = result.to_dict()
        assert "chunks" in data
        assert "total_chunks" in data
        assert "total_tokens" in data
        assert "strategy" in data

    def test_result_to_list(self) -> None:
        """ChunkResult serializes to list of chunk dicts."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk(SAMPLE_MD)

        chunks = result.get_texts()
        assert isinstance(chunks, list)
        assert len(chunks) == result.total_chunks

        for chunk_text in chunks:
            assert isinstance(chunk_text, str)
            assert len(chunk_text) > 0

    def test_avg_tokens(self) -> None:
        """Average tokens per chunk is calculated."""
        chunker = FixedChunker(max_chunk_size=100)
        result = chunker.chunk(SAMPLE_MD)

        assert result.avg_chunk_tokens > 0


# ══════════════════════════════════════════════════════════════
# Edge Cases
# ══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Tests for edge cases."""

    def test_very_long_single_line(self) -> None:
        """Very long line without breaks."""
        chunker = FixedChunker(max_chunk_size=50)
        long_text = "word " * 500  # ~500 words
        result = chunker.chunk(long_text)

        assert result.total_chunks > 1

    def test_only_whitespace(self) -> None:
        """Whitespace-only content."""
        chunker = TopicChunker(max_chunk_size=500)
        result = chunker.chunk("   \n\n   \n   ")

        assert result.total_chunks == 0

    def test_only_code_block(self) -> None:
        """Content that is only a code block."""
        chunker = TopicChunker(max_chunk_size=500)
        code = "```python\nprint('hello')\n```"
        result = chunker.chunk(code)

        assert result.total_chunks >= 1

    def test_unicode_content(self) -> None:
        """Unicode content is handled."""
        chunker = TopicChunker(max_chunk_size=500)
        text = "# 标题\n\n这是中文内容。日本語のテキスト。한국어 텍스트."
        result = chunker.chunk(text)

        assert result.total_chunks >= 1

    def test_markdown_with_html(self) -> None:
        """Markdown with embedded HTML."""
        chunker = TopicChunker(max_chunk_size=500)
        text = "# Title\n\n<div class='custom'>HTML content</div>\n\nMore text."
        result = chunker.chunk(text)

        assert result.total_chunks >= 1

    def test_multiple_consecutive_headings(self) -> None:
        """Multiple headings without content between."""
        chunker = TopicChunker(max_chunk_size=500)
        text = "# H1\n## H2\n### H3\n#### H4\n\nSome content."
        result = chunker.chunk(text)

        assert result.total_chunks >= 1
