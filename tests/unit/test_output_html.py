"""Tests for agentcrawl.output.html module."""

import pytest

from agentcrawl.core.engine import CrawlResult
from agentcrawl.output.html import (
    HtmlOutputFormatter,
    HtmlSanitizer,
)


@pytest.fixture
def sample_result():
    """Create a sample CrawlResult for testing."""
    return CrawlResult(
        url="https://example.com/page",
        success=True,
        status_code=200,
        markdown="# Hello World",
        html="<p>Hello World</p>",
        text="Hello World",
        metadata={
            "title": "Test Page",
            "description": "A test page",
            "author": "Test Author",
            "keywords": "test, page",
            "og_title": "OG Title",
            "og_description": "OG Description",
            "og_image": "https://example.com/image.png",
            "og_url": "https://example.com",
            "og_type": "article",
            "og_site_name": "Example",
        },
    )


@pytest.fixture
def simple_result():
    """Create a minimal CrawlResult."""
    return CrawlResult(url="https://example.com", markdown="# Simple")


class TestHtmlSanitizerInit:
    """Tests for HtmlSanitizer initialization."""

    def test_defaults(self):
        sanitizer = HtmlSanitizer()
        assert sanitizer._allow_images is True
        assert sanitizer._allow_links is True
        assert sanitizer._allow_styles is False
        assert sanitizer._allowed_tags == set()
        assert sanitizer._allowed_attributes == set()

    def test_allow_images_false(self):
        sanitizer = HtmlSanitizer(allow_images=False)
        assert sanitizer._allow_images is False

    def test_allow_links_false(self):
        sanitizer = HtmlSanitizer(allow_links=False)
        assert sanitizer._allow_links is False

    def test_allow_styles(self):
        sanitizer = HtmlSanitizer(allow_styles=True)
        assert sanitizer._allow_styles is True

    def test_custom_allowed_tags(self):
        sanitizer = HtmlSanitizer(allowed_tags={"div", "span"})
        assert sanitizer._allowed_tags == {"div", "span"}

    def test_custom_allowed_attributes(self):
        sanitizer = HtmlSanitizer(allowed_attributes={"data-id"})
        assert sanitizer._allowed_attributes == {"data-id"}


class TestHtmlSanitizerSanitize:
    """Tests for HtmlSanitizer.sanitize method."""

    def test_sanitize_empty(self):
        sanitizer = HtmlSanitizer()
        assert sanitizer.sanitize("") == ""

    def test_remove_script_tags(self):
        sanitizer = HtmlSanitizer()
        html = "<div>Hello</div><script>alert('xss')</script>"
        result = sanitizer.sanitize(html)
        assert "<script>" not in result
        assert "alert" not in result

    def test_remove_style_tags(self):
        sanitizer = HtmlSanitizer()
        html = "<style>body { color: red; }</style><p>Hello</p>"
        result = sanitizer.sanitize(html)
        assert "<style>" not in result
        assert "color" not in result
        assert "<p>Hello</p>" in result

    def test_remove_noscript(self):
        sanitizer = HtmlSanitizer()
        html = "<noscript>Fallback</noscript><p>Hello</p>"
        result = sanitizer.sanitize(html)
        assert "<noscript>" not in result
        assert "</noscript>" not in result
        assert "<p>Hello</p>" in result

    def test_remove_iframe(self):
        sanitizer = HtmlSanitizer()
        html = "<iframe src='evil.com'></iframe><p>Hello</p>"
        result = sanitizer.sanitize(html)
        assert "<iframe" not in result
        assert "<p>Hello</p>" in result

    def test_remove_embed(self):
        sanitizer = HtmlSanitizer()
        html = "<embed src='evil.swf'>Hello</p>"
        result = sanitizer.sanitize(html)
        assert "<embed" not in result

    def test_remove_object(self):
        sanitizer = HtmlSanitizer()
        html = "<object data='evil.swf'></object><p>Hello</p>"
        result = sanitizer.sanitize(html)
        assert "<object" not in result
        assert "<p>Hello</p>" in result

    def test_remove_form_tags(self):
        sanitizer = HtmlSanitizer()
        html = "<form><input type='text'><button>Submit</button></form><p>Hi</p>"
        result = sanitizer.sanitize(html)
        assert "<form" not in result
        assert "<input" not in result
        assert "<button" not in result
        assert "<p>Hi</p>" in result

    def test_remove_meta_link_base(self):
        sanitizer = HtmlSanitizer()
        html = (
            "<meta charset='utf-8'><link rel='stylesheet'><base href='http://evil.com'><p>Hello</p>"
        )
        result = sanitizer.sanitize(html)
        assert "<meta" not in result
        assert "<link" not in result
        assert "<base" not in result

    def test_remove_event_handlers(self):
        sanitizer = HtmlSanitizer()
        html = '<div onclick="evil()">Hello</div>'
        result = sanitizer.sanitize(html)
        assert "onclick" not in result
        assert "evil" not in result

    def test_remove_all_event_handlers(self):
        sanitizer = HtmlSanitizer()
        html = '<div onload="evil()" onchange="evil2()" onkeydown="evil3()">Hello</div>'
        result = sanitizer.sanitize(html)
        assert "onload" not in result
        assert "onchange" not in result
        assert "onkeydown" not in result

    def test_remove_javascript_urls(self):
        sanitizer = HtmlSanitizer()
        html = '<a href="javascript:alert(1)">Click</a>'
        result = sanitizer.sanitize(html)
        assert "javascript:" not in result
        assert "alert" not in result

    def test_remove_data_urls_href(self):
        sanitizer = HtmlSanitizer()
        html = '<a href="data:text/html,<script>alert(1)</script>">Click</a>'
        result = sanitizer.sanitize(html)
        assert "data:" not in result.lower()

    def test_remove_css_expressions(self):
        sanitizer = HtmlSanitizer()
        html = "<div style='width: expression(alert(1))'>Hello</div>"
        result = sanitizer.sanitize(html)
        assert "expression" not in result.lower()

    def test_remove_style_attrs(self):
        sanitizer = HtmlSanitizer()
        html = '<div style="color: red;">Hello</div>'
        result = sanitizer.sanitize(html)
        assert "style=" not in result
        assert "color" not in result

    def test_keep_styles_when_allowed(self):
        sanitizer = HtmlSanitizer(allow_styles=True)
        html = '<div style="color: red;">Hello</div>'
        result = sanitizer.sanitize(html)
        assert "style=" in result

    def test_remove_img_tags_when_not_allowed(self):
        sanitizer = HtmlSanitizer(allow_images=False)
        html = '<p>Hello</p><img src="image.png">'
        result = sanitizer.sanitize(html)
        assert "<img" not in result
        assert "<p>Hello</p>" in result

    def test_keep_img_when_allowed(self):
        sanitizer = HtmlSanitizer(allow_images=True)
        html = '<p>Hello</p><img src="image.png">'
        result = sanitizer.sanitize(html)
        assert "<img" in result

    def test_sanitize_preserves_safe_content(self):
        sanitizer = HtmlSanitizer()
        html = "<div class='container'><p>Hello World</p></div>"
        result = sanitizer.sanitize(html)
        assert "<p>Hello World</p>" in result

    def test_remove_event_handler_with_unquoted_value(self):
        sanitizer = HtmlSanitizer()
        html = "<div onclick=evil()>Hello</div>"
        result = sanitizer.sanitize(html)
        assert "onclick" not in result

    def test_javascript_url_with_data_uri_prefix(self):
        sanitizer = HtmlSanitizer()
        html = '<a href="JavaScript:alert(1)">Click</a>'
        result = sanitizer.sanitize(html)
        assert "JavaScript:" not in result

    def test_repr(self):
        sanitizer = HtmlSanitizer(allow_images=False, allow_links=True, allow_styles=True)
        repr_str = repr(sanitizer)
        assert "HtmlSanitizer" in repr_str
        assert "images=False" in repr_str
        assert "links=True" in repr_str
        assert "styles=True" in repr_str


class TestHtmlOutputFormatterInit:
    """Tests for HtmlOutputFormatter initialization."""

    def test_defaults(self):
        formatter = HtmlOutputFormatter()
        assert formatter._sanitize is True
        assert formatter._include_metadata is True
        assert formatter._include_styles is False
        assert formatter._wrap_in_document is True
        assert formatter._sanitizer is not None

    def test_sanitize_false(self):
        formatter = HtmlOutputFormatter(sanitize=False)
        assert formatter._sanitize is False

    def test_include_metadata_false(self):
        formatter = HtmlOutputFormatter(include_metadata=False)
        assert formatter._include_metadata is False

    def test_include_styles(self):
        formatter = HtmlOutputFormatter(include_styles=True)
        assert formatter._include_styles is True

    def test_custom_template(self):
        template = "<html><body>{{content}}</body></html>"
        formatter = HtmlOutputFormatter(template=template)
        assert formatter._template == template

    def test_wrap_in_document_false(self):
        formatter = HtmlOutputFormatter(wrap_in_document=False)
        assert formatter._wrap_in_document is False

    def test_custom_sanitizer(self):
        sanitizer = HtmlSanitizer(allow_images=False)
        formatter = HtmlOutputFormatter(sanitizer=sanitizer)
        assert formatter._sanitizer is sanitizer


class TestHtmlFormat:
    """Tests for HtmlOutputFormatter.format method."""

    def test_format_with_html(self, sample_result):
        formatter = HtmlOutputFormatter()
        result = formatter.format(sample_result)
        assert "<html" in result
        assert "<body" in result
        assert "<title>" in result or "title" in result.lower()

    def test_format_with_raw_html(self):
        formatter = HtmlOutputFormatter()
        result = CrawlResult(url="https://example.com", raw_html="<p>Raw HTML</p>")
        output = formatter.format(result)
        assert "<p>Raw HTML</p>" in output

    def test_format_with_markdown(self, simple_result):
        formatter = HtmlOutputFormatter()
        output = formatter.format(simple_result)
        assert "<h1>Simple</h1>" in output

    def test_format_with_text(self):
        formatter = HtmlOutputFormatter()
        result = CrawlResult(url="https://example.com", text="Plain text content")
        output = formatter.format(result)
        assert "<p>Plain text content</p>" in output

    def test_format_empty_result(self):
        formatter = HtmlOutputFormatter()
        result = CrawlResult(url="https://example.com")
        output = formatter.format(result)
        # Should still produce a document structure
        assert "<html" in output or "<body" in output or "<title" in output

    def test_format_no_wrap(self, sample_result):
        formatter = HtmlOutputFormatter(wrap_in_document=False)
        result = formatter.format(sample_result)
        assert "<html" not in result

    def test_format_no_sanitize(self, sample_result):
        formatter = HtmlOutputFormatter(sanitize=False)
        result = formatter.format(sample_result)
        # Without sanitization, html content is passed through
        assert "Hello World" in result

    def test_format_with_styles(self, sample_result):
        formatter = HtmlOutputFormatter(include_styles=True)
        result = formatter.format(sample_result)
        assert "<style" in result

    def test_format_with_metadata_meta_tags(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        result = formatter.format(sample_result)
        assert 'meta name="description"' in result or "description" in result

    def test_format_template_replacement(self):
        formatter = HtmlOutputFormatter(template="<article>{{content}}</article>")
        result = CrawlResult(url="https://example.com", html="<p>Content</p>")
        output = formatter.format(result)
        assert "<article>" in output

    def test_format_title_from_metadata(self, sample_result):
        formatter = HtmlOutputFormatter()
        result = formatter.format(sample_result)
        assert "Test Page" in result

    def test_format_title_from_url_when_no_metadata_title(self):
        formatter = HtmlOutputFormatter()
        result = CrawlResult(url="https://example.com/page", html="<p>Hi</p>")
        output = formatter.format(result)
        assert "https://example.com/page" in output or "example.com" in output

    def test_format_meta_description(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        result = formatter.format(sample_result)
        assert "A test page" in result

    def test_format_meta_author(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        result = formatter.format(sample_result)
        assert "Test Author" in result

    def test_format_meta_keywords(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        result = formatter.format(sample_result)
        assert "test, page" in result

    def test_format_og_tags(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        result = formatter.format(sample_result)
        assert "og:title" in result or "og_title" in result

    def test_format_no_metadata_in_template(self):
        formatter = HtmlOutputFormatter(
            template="<html><body>{{content}}</body></html>",
            include_metadata=False,
        )
        result = CrawlResult(url="https://example.com", html="<p>Hi</p>")
        output = formatter.format(result)
        assert "<p>Hi</p>" in output

    def test_format_raw_without_document(self, sample_result):
        formatter = HtmlOutputFormatter()
        output = formatter.format_raw(sample_result)
        assert "<html" not in output


class TestMarkdownToHtml:
    """Tests for _markdown_to_html method."""

    def test_markdown_to_html_with_markdown_lib(self):
        from agentcrawl.output.html import HtmlOutputFormatter

        md = "# Header\n\nParagraph with **bold** text."
        result = HtmlOutputFormatter._markdown_to_html(md)
        assert "<h1>Header</h1>" in result
        assert "<strong>bold</strong>" in result

    def test_markdown_to_html_without_markdown_lib(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"markdown": None}):
            md = "# Header\n\n*italic*\n\n**bold**"
            result = HtmlOutputFormatter._markdown_to_html(md)
            assert "<h1>Header</h1>" in result
            assert "<em>italic</em>" in result
            assert "<strong>bold</strong>" in result

    def test_markdown_to_html_links(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"markdown": None}):
            md = "[link text](https://example.com)"
            result = HtmlOutputFormatter._markdown_to_html(md)
            assert '<a href="https://example.com">link text</a>' in result

    def test_markdown_to_html_paragraphs(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"markdown": None}):
            md = "First paragraph\n\nSecond paragraph"
            result = HtmlOutputFormatter._markdown_to_html(md)
            assert result.count("<p>") >= 1

    def test_markdown_to_html_multiple_headers(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"markdown": None}):
            md = "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6"
            result = HtmlOutputFormatter._markdown_to_html(md)
            assert "<h1>H1</h1>" in result
            assert "<h6>H6</h6>" in result


class TestEscapeMethods:
    """Tests for HTML escape utilities."""

    def test_escape_html(self):
        result = HtmlOutputFormatter._escape_html("<script>alert('xss')</script>")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "<script>" not in result

    def test_escape_html_ampersand(self):
        result = HtmlOutputFormatter._escape_html("a & b")
        assert "&amp;" in result

    def test_escape_html_no_change(self):
        result = HtmlOutputFormatter._escape_html("plain text")
        assert result == "plain text"

    def test_escape_attr(self):
        result = HtmlOutputFormatter._escape_attr('">"<alert(1)')
        assert "&quot;" in result
        assert "&lt;" in result
        assert "&gt;" in result

    def test_escape_attr_ampersand(self):
        result = HtmlOutputFormatter._escape_attr("a & b")
        assert "&amp;" in result


class TestToPdf:
    """Tests for to_pdf method."""

    @pytest.mark.asyncio
    async def test_to_pdf_requires_weasyprint(self):
        formatter = HtmlOutputFormatter()
        result = CrawlResult(url="https://example.com", html="<p>Hi</p>")
        with pytest.raises(ImportError, match="weasyprint"):
            await formatter.to_pdf(result)

    @pytest.mark.asyncio
    async def test_to_pdf_with_weasyprint(self):
        from unittest.mock import patch

        formatter = HtmlOutputFormatter()
        result = CrawlResult(url="https://example.com", html="<p>Hi</p>")

        class MockHTML:
            def __init__(self, string):
                self.string = string

            def write_pdf(self):
                return b"fake_pdf_bytes"

        mock_module = type("MockWeasyPrint", (), {"HTML": MockHTML})()
        with patch.dict("sys.modules", {"weasyprint": mock_module}):
            pdf_bytes = await formatter.to_pdf(result)
            assert pdf_bytes == b"fake_pdf_bytes"

    @pytest.mark.asyncio
    async def test_to_pdf_with_output_path(self, tmp_path):
        from unittest.mock import patch

        formatter = HtmlOutputFormatter()
        result = CrawlResult(url="https://example.com", html="<p>Hi</p>")

        class MockHTML:
            def __init__(self, string):
                self.string = string

            def write_pdf(self):
                return b"fake_pdf_bytes"

        mock_module = type("MockWeasyPrint", (), {"HTML": MockHTML})()
        with patch.dict("sys.modules", {"weasyprint": mock_module}):
            filepath = str(tmp_path / "output.pdf")
            pdf_bytes = await formatter.to_pdf(result, output_path=filepath)
            assert pdf_bytes == b"fake_pdf_bytes"
            assert (tmp_path / "output.pdf").exists()


class TestHtmlRepr:
    """Tests for __repr__."""

    def test_repr(self):
        formatter = HtmlOutputFormatter(sanitize=True, include_metadata=True, include_styles=False)
        repr_str = repr(formatter)
        assert "HtmlOutputFormatter" in repr_str
        assert "sanitize=True" in repr_str
        assert "metadata=True" in repr_str
        assert "styles=False" in repr_str


class TestHtmlMetaTags:
    """Tests for _build_meta_tags method."""

    def test_build_meta_tags_description(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags(sample_result.metadata)
        assert "description" in tags
        assert "A test page" in tags

    def test_build_meta_tags_author(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags(sample_result.metadata)
        assert "author" in tags
        assert "Test Author" in tags

    def test_build_meta_tags_keywords(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags(sample_result.metadata)
        assert "keywords" in tags
        assert "test, page" in tags

    def test_build_meta_tags_og(self, sample_result):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags(sample_result.metadata)
        assert "og:title" in tags
        assert "og:image" in tags

    def test_build_meta_tags_empty(self):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags({})
        assert tags == ""

    def test_build_meta_tags_no_description(self):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags({"title": "No Description"})
        assert "description" not in tags
        assert "title" not in tags  # title is not a meta tag

    def test_build_meta_tags_no_author(self):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags({"description": "Desc"})
        assert "author" not in tags

    def test_build_meta_tags_no_keywords(self):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags({"description": "Desc"})
        assert "keywords" not in tags

    def test_build_meta_tags_no_og_fields(self):
        formatter = HtmlOutputFormatter(include_metadata=True)
        tags = formatter._build_meta_tags({"description": "Desc"})
        assert "og:" not in tags


class TestHtmlRenderTemplate:
    """Tests for _render_template method."""

    def test_render_template_basic(self, sample_result):
        formatter = HtmlOutputFormatter()
        content = "<p>Test content</p>"
        result = formatter._render_template(sample_result, content)
        assert "<p>Test content</p>" in result
        assert "{{content}}" not in result

    def test_render_template_replaces_all_placeholders(self, sample_result):
        formatter = HtmlOutputFormatter()
        content = "<p>Test</p>"
        result = formatter._render_template(sample_result, content)
        assert "{{content}}" not in result
        assert "{{title}}" not in result
        assert "{{metadata}}" not in result
        assert "{{styles}}" not in result
        assert "{{url}}" not in result

    def test_render_template_with_empty_metadata(self):
        formatter = HtmlOutputFormatter(include_metadata=True)
        result = CrawlResult(url="https://example.com", html="<p>Hi</p>", metadata={})
        output = formatter._render_template(result, "<p>content</p>")
        assert "{{metadata}}" not in output

    def test_render_template_with_url_escape(self):
        formatter = HtmlOutputFormatter()
        result = CrawlResult(
            url="https://example.com/<script>",
            html="<p>Hi</p>",
            metadata={},
        )
        output = formatter._render_template(result, "<p>content</p>")
        assert "&lt;script&gt;" in output


class TestHtmlSanitizerEventHandlers:
    """Tests for all event handler attributes removal."""

    def test_all_event_attrs_removed(self):
        sanitizer = HtmlSanitizer()
        attrs = [
            "onclick",
            "ondblclick",
            "onmousedown",
            "onmouseup",
            "onmouseover",
            "onmousemove",
            "onmouseout",
            "onmouseenter",
            "onmouseleave",
            "onkeydown",
            "onkeypress",
            "onkeyup",
            "onfocus",
            "onblur",
            "onchange",
            "oninput",
            "onsubmit",
            "onreset",
            "onselect",
            "onload",
            "onunload",
            "onerror",
            "onresize",
            "onscroll",
            "onabort",
            "oncanplay",
            "ondrag",
            "ondragend",
            "ondragenter",
            "ondragleave",
            "ondragover",
            "ondragstart",
            "ondrop",
            "oncontextmenu",
            "onwheel",
            "ontouchstart",
            "ontouchmove",
            "ontouchend",
            "onanimationstart",
            "onanimationend",
            "ontransitionend",
        ]
        for attr in attrs:
            html = f'<div {attr}="evil()">Test</div>'
            result = sanitizer.sanitize(html)
            assert attr not in result
            assert "evil" not in result
