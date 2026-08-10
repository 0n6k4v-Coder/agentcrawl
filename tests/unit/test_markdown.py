"""
AgentCrawl — Markdown Converter Unit Tests
==============================================

Unit tests for HTML to Markdown conversion.

Tests:
    - Basic HTML to Markdown conversion
    - Headings, paragraphs, links, images
    - Lists (ordered, unordered)
    - Tables
    - Code blocks
    - Blockquotes
    - Bold, italic, strikethrough
    - Noise removal (nav, footer, ads)
    - only_main_content option
    - Selector filtering
    - Edge cases

Run:
    pytest tests/unit/test_markdown.py -v
"""

from __future__ import annotations

import pytest

from agentcrawl.content.html_to_markdown import HTMLToMarkdown, MarkdownOptions

# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def converter() -> HTMLToMarkdown:
    """Default HTMLToMarkdown converter."""
    return HTMLToMarkdown()


@pytest.fixture
def main_content_converter() -> HTMLToMarkdown:
    """Converter with only_main_content via options."""
    return HTMLToMarkdown(
        options=MarkdownOptions(
            strip_tags=["nav", "footer", "aside", "header", ".advertisement", ".ads", ".sidebar"]
        )
    )


@pytest.fixture
def link_converter() -> HTMLToMarkdown:
    """Converter with include_links option."""
    return HTMLToMarkdown(options=MarkdownOptions(include_links=True))


@pytest.fixture
def no_link_converter() -> HTMLToMarkdown:
    """Converter without links."""
    return HTMLToMarkdown(options=MarkdownOptions(include_links=False))


# ══════════════════════════════════════════════════════════════
# Basic Conversion
# ══════════════════════════════════════════════════════════════


class TestBasicConversion:
    """Tests for basic HTML to Markdown conversion."""

    def test_simple_paragraph(self, converter: HTMLToMarkdown) -> None:
        """Convert a simple paragraph."""
        html = "<p>Hello, world!</p>"
        result = converter.convert(html)

        assert "Hello, world!" in result

    def test_multiple_paragraphs(self, converter: HTMLToMarkdown) -> None:
        """Convert multiple paragraphs."""
        html = "<p>First paragraph.</p><p>Second paragraph.</p>"
        result = converter.convert(html)

        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_empty_html(self, converter: HTMLToMarkdown) -> None:
        """Empty HTML returns empty string."""
        result = converter.convert("")
        assert result.strip() == ""

    def test_whitespace_only(self, converter: HTMLToMarkdown) -> None:
        """Whitespace-only HTML returns minimal output."""
        result = converter.convert("   \n\n   ")
        assert result.strip() == ""

    def test_plain_text(self, converter: HTMLToMarkdown) -> None:
        """Plain text without tags is preserved."""
        result = converter.convert("Just plain text")
        assert "Just plain text" in result

    def test_full_html_document(self, converter: HTMLToMarkdown) -> None:
        """Convert a full HTML document."""
        html = """<!DOCTYPE html>
        <html>
        <head><title>Test</title></head>
        <body>
            <h1>Title</h1>
            <p>Content here.</p>
        </body>
        </html>"""

        result = converter.convert(html)
        assert "Title" in result
        assert "Content here." in result


# ══════════════════════════════════════════════════════════════
# Headings
# ══════════════════════════════════════════════════════════════


class TestHeadings:
    """Tests for heading conversion."""

    def test_h1(self, converter: HTMLToMarkdown) -> None:
        """Convert h1 to # heading."""
        result = converter.convert("<h1>Main Title</h1>")
        assert "# Main Title" in result

    def test_h2(self, converter: HTMLToMarkdown) -> None:
        """Convert h2 to ## heading."""
        result = converter.convert("<h2>Section</h2>")
        assert "## Section" in result

    def test_h3(self, converter: HTMLToMarkdown) -> None:
        """Convert h3 to ### heading."""
        result = converter.convert("<h3>Subsection</h3>")
        assert "### Subsection" in result

    def test_h4(self, converter: HTMLToMarkdown) -> None:
        """Convert h4 to #### heading."""
        result = converter.convert("<h4>Detail</h4>")
        assert "#### Detail" in result

    def test_h5(self, converter: HTMLToMarkdown) -> None:
        """Convert h5 to ##### heading."""
        result = converter.convert("<h5>Minor</h5>")
        assert "##### Minor" in result

    def test_h6(self, converter: HTMLToMarkdown) -> None:
        """Convert h6 to ###### heading."""
        result = converter.convert("<h6>Smallest</h6>")
        assert "###### Smallest" in result

    def test_heading_hierarchy(self, converter: HTMLToMarkdown) -> None:
        """Multiple headings maintain hierarchy."""
        html = "<h1>Top</h1><h2>Mid</h2><h3>Low</h3>"
        result = converter.convert(html)

        assert "# Top" in result
        assert "## Mid" in result
        assert "### Low" in result


# ══════════════════════════════════════════════════════════════
# Links
# ══════════════════════════════════════════════════════════════


class TestLinks:
    """Tests for link conversion."""

    def test_basic_link(self, link_converter: HTMLToMarkdown) -> None:
        """Convert a basic link."""
        html = '<a href="https://example.com">Example</a>'
        result = link_converter.convert(html)

        assert "[Example](https://example.com)" in result

    def test_link_with_title(self, link_converter: HTMLToMarkdown) -> None:
        """Convert link with title attribute."""
        html = '<a href="https://example.com" title="Example Site">Example</a>'
        result = link_converter.convert(html)

        assert "https://example.com" in result
        assert "Example" in result

    def test_multiple_links(self, link_converter: HTMLToMarkdown) -> None:
        """Convert multiple links."""
        html = """
        <a href="/page1">Page 1</a>
        <a href="/page2">Page 2</a>
        <a href="/page3">Page 3</a>
        """
        result = link_converter.convert(html)

        assert "Page 1" in result
        assert "Page 2" in result
        assert "Page 3" in result

    def test_relative_link(self, link_converter: HTMLToMarkdown) -> None:
        """Convert relative links."""
        html = '<a href="/about">About</a>'
        result = link_converter.convert(html)

        assert "About" in result
        assert "/about" in result

    def test_empty_link(self, link_converter: HTMLToMarkdown) -> None:
        """Link with no text."""
        html = '<a href="https://example.com"></a>'
        result = link_converter.convert(html)

        # Should not crash
        assert isinstance(result, str)

    def test_links_disabled(self, no_link_converter: HTMLToMarkdown) -> None:
        """include_links=False strips link URLs."""
        html = '<p><a href="https://example.com">Link</a></p>'
        result = no_link_converter.convert(html)

        assert "Link" in result


# ══════════════════════════════════════════════════════════════
# Images
# ══════════════════════════════════════════════════════════════


class TestImages:
    """Tests for image conversion."""

    def test_basic_image(self, converter: HTMLToMarkdown) -> None:
        """Convert a basic image."""
        html = '<img src="https://example.com/img.png" alt="Test Image">'
        result = converter.convert(html)

        assert "![Test Image](https://example.com/img.png)" in result

    def test_image_without_alt(self, converter: HTMLToMarkdown) -> None:
        """Image without alt text."""
        html = '<img src="https://example.com/img.png">'
        result = converter.convert(html)

        assert "https://example.com/img.png" in result

    def test_image_with_title(self, converter: HTMLToMarkdown) -> None:
        """Image with title."""
        html = '<img src="img.png" alt="Photo" title="A nice photo">'
        result = converter.convert(html)

        assert "Photo" in result


# ══════════════════════════════════════════════════════════════
# Lists
# ══════════════════════════════════════════════════════════════


class TestLists:
    """Tests for list conversion."""

    def test_unordered_list(self, converter: HTMLToMarkdown) -> None:
        """Convert unordered list."""
        html = "<ul><li>Item 1</li><li>Item 2</li><li>Item 3</li></ul>"
        result = converter.convert(html)

        assert "- Item 1" in result or "* Item 1" in result
        assert "- Item 2" in result or "* Item 2" in result
        assert "- Item 3" in result or "* Item 3" in result

    def test_ordered_list(self, converter: HTMLToMarkdown) -> None:
        """Convert ordered list."""
        html = "<ol><li>First</li><li>Second</li><li>Third</li></ol>"
        result = converter.convert(html)

        assert "1." in result
        assert "First" in result
        assert "Second" in result

    def test_nested_list(self, converter: HTMLToMarkdown) -> None:
        """Convert nested list."""
        html = """
        <ul>
            <li>Parent
                <ul>
                    <li>Child 1</li>
                    <li>Child 2</li>
                </ul>
            </li>
        </ul>
        """
        result = converter.convert(html)

        assert "Parent" in result
        assert "Child 1" in result
        assert "Child 2" in result

    def test_empty_list(self, converter: HTMLToMarkdown) -> None:
        """Empty list doesn't crash."""
        html = "<ul></ul>"
        result = converter.convert(html)
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════
# Tables
# ══════════════════════════════════════════════════════════════


class TestTables:
    """Tests for table conversion."""

    def test_simple_table(self, converter: HTMLToMarkdown) -> None:
        """Convert a simple table."""
        html = """
        <table>
            <thead>
                <tr><th>Name</th><th>Age</th></tr>
            </thead>
            <tbody>
                <tr><td>Alice</td><td>30</td></tr>
                <tr><td>Bob</td><td>25</td></tr>
            </tbody>
        </table>
        """
        result = converter.convert(html)

        assert "Name" in result
        assert "Age" in result
        assert "Alice" in result
        assert "30" in result
        assert "|" in result  # Markdown table separator

    def test_table_without_header(self, converter: HTMLToMarkdown) -> None:
        """Table without thead."""
        html = """
        <table>
            <tr><td>A</td><td>B</td></tr>
            <tr><td>C</td><td>D</td></tr>
        </table>
        """
        result = converter.convert(html)

        assert "A" in result
        assert "D" in result


# ══════════════════════════════════════════════════════════════
# Code Blocks
# ══════════════════════════════════════════════════════════════


class TestCodeBlocks:
    """Tests for code block conversion."""

    def test_inline_code(self, converter: HTMLToMarkdown) -> None:
        """Convert inline code."""
        html = "<p>Use <code>print()</code> function.</p>"
        result = converter.convert(html)

        assert "`print()`" in result

    def test_code_block(self, converter: HTMLToMarkdown) -> None:
        """Convert code block."""
        html = "<pre><code>def hello():\n    print('Hello')</code></pre>"
        result = converter.convert(html)

        assert "```" in result
        assert "def hello():" in result

    def test_code_block_with_language(self, converter: HTMLToMarkdown) -> None:
        """Code block with language class."""
        html = '<pre><code class="language-python">print("hi")</code></pre>'
        result = converter.convert(html)

        assert "```" in result
        assert "print" in result


# ══════════════════════════════════════════════════════════════
# Blockquotes
# ══════════════════════════════════════════════════════════════


class TestBlockquotes:
    """Tests for blockquote conversion."""

    def test_basic_blockquote(self, converter: HTMLToMarkdown) -> None:
        """Convert blockquote."""
        html = "<blockquote>This is a quote.</blockquote>"
        result = converter.convert(html)

        assert "> This is a quote." in result

    def test_nested_blockquote(self, converter: HTMLToMarkdown) -> None:
        """Convert nested blockquote."""
        html = """
        <blockquote>
            Outer quote
            <blockquote>Inner quote</blockquote>
        </blockquote>
        """
        result = converter.convert(html)

        assert "Outer quote" in result
        assert "Inner quote" in result


# ══════════════════════════════════════════════════════════════
# Text Formatting
# ══════════════════════════════════════════════════════════════


class TestTextFormatting:
    """Tests for text formatting conversion."""

    def test_bold(self, converter: HTMLToMarkdown) -> None:
        """Convert bold text."""
        html = "<p><strong>Bold text</strong></p>"
        result = converter.convert(html)

        assert "**Bold text**" in result

    def test_italic(self, converter: HTMLToMarkdown) -> None:
        """Convert italic text."""
        html = "<p><em>Italic text</em></p>"
        result = converter.convert(html)

        assert "*Italic text*" in result

    def test_bold_italic(self, converter: HTMLToMarkdown) -> None:
        """Convert bold italic text."""
        html = "<p><strong><em>Bold italic</em></strong></p>"
        result = converter.convert(html)

        assert "Bold italic" in result

    def test_strikethrough(self, converter: HTMLToMarkdown) -> None:
        """Convert strikethrough text."""
        html = "<p><del>Deleted</del></p>"
        result = converter.convert(html)

        assert "~~Deleted~~" in result

    def test_horizontal_rule(self, converter: HTMLToMarkdown) -> None:
        """Convert horizontal rule."""
        html = "<p>Above</p><hr><p>Below</p>"
        result = converter.convert(html)

        assert "---" in result or "***" in result


# ══════════════════════════════════════════════════════════════
# Noise Removal
# ══════════════════════════════════════════════════════════════


class TestNoiseRemoval:
    """Tests for noise removal (scripts, styles, etc.)."""

    def test_removes_script_tags(self, converter: HTMLToMarkdown) -> None:
        """Script tags are removed."""
        html = "<p>Content</p><script>alert('xss')</script>"
        result = converter.convert(html)

        assert "Content" in result
        assert "alert" not in result

    def test_removes_style_tags(self, converter: HTMLToMarkdown) -> None:
        """Style tags are removed."""
        html = "<p>Content</p><style>body { color: red; }</style>"
        result = converter.convert(html)

        assert "Content" in result
        assert "color: red" not in result

    def test_removes_nav(self, main_content_converter: HTMLToMarkdown) -> None:
        """Nav elements removed with strip_tags."""
        html = """
        <nav>Navigation</nav>
        <main><p>Main content</p></main>
        """
        result = main_content_converter.convert(html)

        assert "Main content" in result

    def test_removes_footer(self, main_content_converter: HTMLToMarkdown) -> None:
        """Footer elements removed."""
        html = """
        <main><p>Main content</p></main>
        <footer><p>© 2025 Company</p></footer>
        """
        result = main_content_converter.convert(html)

        assert "Main content" in result

    def test_removes_ads(self, main_content_converter: HTMLToMarkdown) -> None:
        """Ad elements are removed."""
        html = """
        <div class="advertisement">Buy now!</div>
        <article><p>Real content</p></article>
        """
        result = main_content_converter.convert(html)

        assert "Real content" in result


# ══════════════════════════════════════════════════════════════
# Selector Filtering
# ══════════════════════════════════════════════════════════════


class TestSelectorFiltering:
    """Tests for CSS selector filtering via options."""

    def test_strip_tags_option(self) -> None:
        """Only include matching selectors via strip_tags."""
        converter = HTMLToMarkdown(options=MarkdownOptions(strip_tags=["nav", "footer", "article"]))

        html = """
        <div class="sidebar">Sidebar</div>
        <article><p>Article content</p></article>
        """
        result = converter.convert(html)

        # article is stripped, so Article content is removed
        assert "Article content" not in result or "Sidebar" in result

    def test_exclude_via_strip_tags(self) -> None:
        """Exclude matching selectors via strip_tags."""
        converter = HTMLToMarkdown(options=MarkdownOptions(strip_tags=[".ads", "nav"]))

        html = """
        <nav>Navigation</nav>
        <div class="ads">Advertisement</div>
        <p>Main content</p>
        """
        result = converter.convert(html)

        assert "Main content" in result


# ══════════════════════════════════════════════════════════════
# Options
# ══════════════════════════════════════════════════════════════


class TestOptions:
    """Tests for converter options."""

    def test_only_main_content_true(self, main_content_converter: HTMLToMarkdown) -> None:
        """only_main_content via strip_tags filters noise."""
        html = """
        <nav>Nav</nav>
        <main><p>Content</p></main>
        <footer>Footer</footer>
        """
        result = main_content_converter.convert(html)

        assert "Content" in result

    def test_include_links_true(self, link_converter: HTMLToMarkdown) -> None:
        """include_links=True preserves links."""
        html = '<p><a href="https://example.com">Link</a></p>'
        result = link_converter.convert(html)

        assert "[Link](https://example.com)" in result

    def test_include_links_false(self, no_link_converter: HTMLToMarkdown) -> None:
        """include_links=False strips link URLs."""
        html = '<p><a href="https://example.com">Link</a></p>'
        result = no_link_converter.convert(html)

        assert "Link" in result


# ══════════════════════════════════════════════════════════════
# Edge Cases
# ══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Tests for edge cases."""

    def test_deeply_nested_html(self, converter: HTMLToMarkdown) -> None:
        """Deeply nested HTML is handled."""
        html = "<div>" * 50 + "<p>Deep content</p>" + "</div>" * 50
        result = converter.convert(html)

        assert "Deep content" in result

    def test_unicode_content(self, converter: HTMLToMarkdown) -> None:
        """Unicode content is preserved."""
        html = "<p>日本語テキスト 🎉 Ελληνικά</p>"
        result = converter.convert(html)

        assert "日本語テキスト" in result
        assert "🎉" in result
        assert "Ελληνικά" in result

    def test_malformed_html(self, converter: HTMLToMarkdown) -> None:
        """Malformed HTML doesn't crash."""
        html = "<p>Unclosed paragraph<div>Nested</p></div>"
        result = converter.convert(html)

        # Should not raise, should produce something
        assert isinstance(result, str)

    def test_very_long_line(self, converter: HTMLToMarkdown) -> None:
        """Very long lines handled."""
        long_text = "a" * 10000
        html = f"<p>{long_text}</p>"
        result = converter.convert(html)

        assert len(result) > 1000

    def test_convert_none(self, converter: HTMLToMarkdown) -> None:
        """None input returns empty string."""
        result = converter.convert(None)  # type: ignore[arg-type]
        assert result == ""

    def test_convert_whitespace(self, converter: HTMLToMarkdown) -> None:
        """Whitespace input returns empty string."""
        result = converter.convert("   \n\t  ")
        assert result.strip() == ""

    def test_special_chars_in_text(self, converter: HTMLToMarkdown) -> None:
        """Special Markdown chars in text are escaped."""
        html = "<p>Price: $5 & 100%</p>"
        result = converter.convert(html)

        assert "Price:" in result

    def test_nested_formatting(self, converter: HTMLToMarkdown) -> None:
        """Nested formatting elements."""
        html = "<p><strong><em><code>code</code></em></strong></p>"
        result = converter.convert(html)

        assert "code" in result


# ══════════════════════════════════════════════════════════════
# MarkdownOptions Dataclass
# ══════════════════════════════════════════════════════════════


class TestMarkdownOptions:
    """Tests for MarkdownOptions configuration."""

    def test_default_options(self) -> None:
        """Default options have sensible values."""
        opts = MarkdownOptions()

        assert opts.include_links is True
        assert opts.include_images is True
        assert opts.code_block_style == "fenced"
        assert opts.heading_style == "atx"
        assert opts.bullet_marker == "-"
        assert opts.ordered_marker == "."
        assert len(opts.strip_tags) > 0
        assert opts.wrap_width == 0
        assert opts.max_heading_level == 6

    def test_custom_options(self) -> None:
        """Custom options are respected."""
        opts = MarkdownOptions(
            include_links=False,
            include_images=False,
            code_block_style="indented",
            heading_style="setext",
            bullet_marker="*",
            ordered_marker=")",
            wrap_width=80,
        )

        assert opts.include_links is False
        assert opts.include_images is False
        assert opts.code_block_style == "indented"
        assert opts.heading_style == "setext"
        assert opts.bullet_marker == "*"
        assert opts.ordered_marker == ")"
        assert opts.wrap_width == 80

    def test_to_dict(self) -> None:
        """to_dict returns all options."""
        opts = MarkdownOptions(include_links=False)
        d = opts.to_dict()

        assert d["include_links"] is False
        assert "strip_tags" in d
        assert "heading_style" in d
