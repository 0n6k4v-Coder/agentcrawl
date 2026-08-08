"""Tests for agentcrawl.output.markdown module."""

import os

import pytest

from agentcrawl.core.engine import CrawlResult
from agentcrawl.output.markdown import MarkdownOutputFormatter


@pytest.fixture
def sample_result():
    """Create a sample CrawlResult for testing."""
    return CrawlResult(
        url="https://example.com/page",
        success=True,
        status_code=200,
        markdown="# Hello World\n\nThis is a test page.",
        html="<html><body><h1>Hello World</h1><p>This is a test page.</p></body></html>",
        text="Hello World This is a test page.",
        metadata={
            "title": "Test Page",
            "description": "A test page for testing",
            "author": "Test Author",
            "date": "2024-01-01",
        },
        links={
            "internal": [
                {"url": "https://example.com/about", "text": "About", "title": "About Us"},
            ],
            "external": [
                {"url": "https://other.com", "text": "External Link"},
            ],
        },
        citations=[
            {
                "number": 1,
                "url": "https://example.com/ref1",
                "title": "Reference 1",
                "domain": "example.com",
            },
            {
                "number": 2,
                "url": "https://other.com/ref2",
                "title": "Reference 2",
                "domain": "other.com",
            },
        ],
        chunks=[
            {"index": 0, "heading": "Section 1", "token_count": 50, "text": "Content of chunk 1"},
            {"index": 1, "heading": "Section 2", "token_count": 30, "text": "Short"},
        ],
        extracted_data=None,
        screenshot="",
        error=None,
        response_time_ms=150.5,
        word_count=100,
        token_count=25,
        cached=False,
    )


@pytest.fixture
def simple_result():
    """Create a minimal CrawlResult."""
    return CrawlResult(
        url="https://example.com",
        markdown="# Simple",
    )


class TestMarkdownOutputFormatterInit:
    """Tests for MarkdownOutputFormatter initialization."""

    def test_defaults(self):
        formatter = MarkdownOutputFormatter()
        d = formatter.to_dict()
        assert d["include_front_matter"] is False
        assert d["include_metadata"] is False
        assert d["include_links"] is False
        assert d["include_citations"] is True
        assert d["include_chunks"] is False
        assert d["include_stats"] is False
        assert d["citation_format"] == "markdown"
        assert d["link_format"] == "markdown"

    def test_custom_template(self):
        formatter = MarkdownOutputFormatter(
            template="# {{title}}\n{{content}}\n---\n{{citations_section}}"
        )
        assert formatter._template == "# {{title}}\n{{content}}\n---\n{{citations_section}}"

    def test_custom_front_matter_fields(self):
        formatter = MarkdownOutputFormatter(front_matter_fields=["custom_field"])
        assert "custom_field" in formatter._front_matter_fields

    def test_custom_separator(self):
        formatter = MarkdownOutputFormatter(separator="\n\n***\n\n")
        assert formatter._separator == "\n\n***\n\n"

    def test_citation_format_apa(self):
        formatter = MarkdownOutputFormatter(citation_format="apa")
        assert formatter._citation_format == "apa"

    def test_citation_format_plain(self):
        formatter = MarkdownOutputFormatter(citation_format="plain")
        assert formatter._citation_format == "plain"

    def test_link_format_plain(self):
        formatter = MarkdownOutputFormatter(link_format="plain")
        assert formatter._link_format == "plain"


class TestMarkdownFormat:
    """Tests for format method."""

    def test_content_only(self, simple_result):
        formatter = MarkdownOutputFormatter()
        result = formatter.format(simple_result)
        assert "# Simple" in result

    def test_with_front_matter(self, sample_result):
        formatter = MarkdownOutputFormatter(include_front_matter=True)
        result = formatter.format(sample_result)
        assert "---" in result
        assert "title:" in result
        assert "url:" in result

    def test_with_metadata(self, sample_result):
        formatter = MarkdownOutputFormatter(include_metadata=True)
        result = formatter.format(sample_result)
        assert "## Metadata" in result
        assert "Test Page" in result

    def test_with_links(self, sample_result):
        formatter = MarkdownOutputFormatter(include_links=True)
        result = formatter.format(sample_result)
        assert "## Links" in result
        assert "https://example.com/about" in result
        assert "https://other.com" in result

    def test_links_plain_format(self, sample_result):
        formatter = MarkdownOutputFormatter(include_links=True, link_format="plain")
        result = formatter.format(sample_result)
        assert "https://example.com/about" in result

    def test_with_citations(self, sample_result):
        formatter = MarkdownOutputFormatter(include_citations=True)
        result = formatter.format(sample_result)
        assert "## References" in result
        assert "[1]" in result

    def test_citations_apa_format(self, sample_result):
        formatter = MarkdownOutputFormatter(include_citations=True, citation_format="apa")
        result = formatter.format(sample_result)
        assert "## References" in result

    def test_citations_plain_format(self, sample_result):
        formatter = MarkdownOutputFormatter(include_citations=True, citation_format="plain")
        result = formatter.format(sample_result)
        assert "## References" in result

    def test_with_chunks(self, sample_result):
        formatter = MarkdownOutputFormatter(include_chunks=True)
        result = formatter.format(sample_result)
        assert "## Chunks" in result
        assert "Chunk 0" in result

    def test_chunks_truncated(self, sample_result):
        formatter = MarkdownOutputFormatter(include_chunks=True)
        result = formatter.format(sample_result)
        # The short chunk text should be fully shown
        assert "Content of chunk 1" in result

    def test_with_stats(self, sample_result):
        formatter = MarkdownOutputFormatter(include_stats=True)
        result = formatter.format(sample_result)
        assert "## Statistics" in result
        assert "Words" in result
        assert "Tokens" in result
        assert "Response time" in result
        assert "Status code" in result
        assert "Cached" in result

    def test_all_sections_together(self, sample_result):
        formatter = MarkdownOutputFormatter(
            include_front_matter=True,
            include_metadata=True,
            include_links=True,
            include_citations=True,
            include_chunks=True,
            include_stats=True,
        )
        result = formatter.format(sample_result)
        assert "---" in result  # front matter
        assert "## Metadata" in result
        assert "## Links" in result
        assert "## References" in result
        assert "## Chunks" in result
        assert "## Statistics" in result

    def test_format_content_only(self, sample_result):
        formatter = MarkdownOutputFormatter()
        result = formatter.format_content_only(sample_result)
        assert "# Hello World" in result

    def test_format_empty_result(self):
        formatter = MarkdownOutputFormatter()
        result = CrawlResult(url="https://example.com")
        output = formatter.format(result)
        assert output == ""

    def test_format_dict_result(self):
        formatter = MarkdownOutputFormatter()
        result = {"url": "https://example.com", "metadata": {"title": "Test"}}
        output = formatter.format(result)
        # Dict doesn't have markdown field, should return empty
        assert output == ""

    def test_format_object_with_extracted_data(self):
        formatter = MarkdownOutputFormatter()

        class MockResult:
            url = "https://example.com"

            @property
            def extracted_data(self):
                return {"key": "value"}

        output = formatter.format(MockResult())
        assert "key" in output
        assert "value" in output

    def test_format_strips_trailing_whitespace(self, sample_result):
        formatter = MarkdownOutputFormatter(include_front_matter=True)
        output = formatter.format(sample_result)
        assert not output.endswith(" ")

    def test_cleanup_excessive_separators(self, sample_result):
        formatter = MarkdownOutputFormatter(
            include_citations=True,
            include_stats=True,
            separator="\n\n---\n\n",
        )
        output = formatter.format(sample_result)
        # Should not have multiple consecutive separators
        assert "\n---\n\n\n---\n" not in output

    def test_cleanup_excessive_blank_lines(self, sample_result):
        formatter = MarkdownOutputFormatter(
            include_front_matter=True,
            include_metadata=True,
        )
        output = formatter.format(sample_result)
        assert "\n\n\n\n" not in output

    def test_custom_template_with_citations(self, sample_result):
        formatter = MarkdownOutputFormatter(
            template="# {{title}}\n\n{{content}}\n\n{{citations_section}}",
            include_citations=True,
        )
        result = formatter.format(sample_result)
        assert "# Test Page" not in result  # title not in template
        assert "## References" in result

    def test_front_matter_with_empty_metadata(self):
        formatter = MarkdownOutputFormatter(include_front_matter=True)
        result = CrawlResult(url="https://example.com", markdown="content")
        output = formatter.format(result)
        assert "---" in output
        assert "url:" in output

    def test_front_matter_url_fallback(self):
        formatter = MarkdownOutputFormatter(
            include_front_matter=True, front_matter_fields=["title", "url"]
        )
        result = CrawlResult(
            url="https://example.com", markdown="content", metadata={"title": "My Title"}
        )
        output = formatter.format(result)
        assert "title" in output
        assert "url" in output

    def test_metadata_empty(self):
        formatter = MarkdownOutputFormatter(include_metadata=True)
        result = CrawlResult(url="https://example.com", markdown="content")
        output = formatter.format(result)
        # No metadata section if metadata is empty
        assert "## Metadata" not in output

    def test_links_empty(self):
        formatter = MarkdownOutputFormatter(include_links=True)
        result = CrawlResult(url="https://example.com", markdown="content")
        output = formatter.format(result)
        assert "## Links" not in output

    def test_citations_empty(self):
        formatter = MarkdownOutputFormatter(include_citations=True)
        result = CrawlResult(url="https://example.com", markdown="content")
        output = formatter.format(result)
        assert "## References" not in output

    def test_chunks_empty(self):
        formatter = MarkdownOutputFormatter(include_chunks=True)
        result = CrawlResult(url="https://example.com", markdown="content")
        output = formatter.format(result)
        assert "## Chunks" not in output

    def test_citations_without_url(self):
        formatter = MarkdownOutputFormatter(include_citations=True)
        result = CrawlResult(
            url="https://example.com",
            markdown="content",
            citations=[{"number": 1, "title": "No URL"}],
        )
        output = formatter.format(result)
        assert "No URL" in output

    def test_citations_with_text_field(self):
        formatter = MarkdownOutputFormatter(include_citations=True)
        result = CrawlResult(
            url="https://example.com",
            markdown="content",
            citations=[{"number": 1, "text": "Citation Text"}],
        )
        output = formatter.format(result)
        assert "Citation Text" in output

    def test_long_chunk_truncated(self):
        formatter = MarkdownOutputFormatter(include_chunks=True)
        long_text = "x" * 600
        result = CrawlResult(
            url="https://example.com",
            markdown="content",
            chunks=[{"index": 0, "heading": "Test", "token_count": 100, "text": long_text}],
        )
        output = formatter.format(result)
        assert "..." in output
        assert len(output) < 1000  # truncated

    def test_stats_all_zero(self):
        formatter = MarkdownOutputFormatter(include_stats=True)
        result = CrawlResult(url="https://example.com", markdown="content")
        output = formatter.format(result)
        assert "## Statistics" in output
        assert "0" in output


class TestMarkdownSave:
    """Tests for save and save_batch methods."""

    def test_save_to_file(self, sample_result, tmp_path):
        formatter = MarkdownOutputFormatter()
        filepath = str(tmp_path / "output.md")
        formatter.save(sample_result, filepath)
        with open(filepath) as f:
            content = f.read()
        assert "# Hello World" in content

    def test_save_batch(self, sample_result, tmp_path):
        formatter = MarkdownOutputFormatter()
        results = [sample_result, CrawlResult(url="https://example.com/2", markdown="content2")]
        directory = str(tmp_path / "batch")
        paths = formatter.save_batch(results, directory)
        assert len(paths) == 2
        assert all(p.endswith(".md") for p in paths)
        for p in paths:
            assert os.path.exists(p)


class TestMarkdownRepr:
    """Tests for __repr__."""

    def test_repr_content_only(self):
        formatter = MarkdownOutputFormatter(include_citations=False)
        repr_str = repr(formatter)
        assert "MarkdownOutputFormatter" in repr_str
        assert "content_only" in repr_str

    def test_repr_with_sections(self):
        formatter = MarkdownOutputFormatter(
            include_front_matter=True,
            include_metadata=True,
            include_links=True,
            include_citations=True,
            include_chunks=True,
            include_stats=True,
        )
        repr_str = repr(formatter)
        assert "front_matter" in repr_str
        assert "metadata" in repr_str
        assert "links" in repr_str
        assert "citations" in repr_str
        assert "chunks" in repr_str
        assert "stats" in repr_str
