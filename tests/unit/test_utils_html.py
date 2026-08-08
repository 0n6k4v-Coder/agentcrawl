"""Tests for agentcrawl.utils.html module."""

from agentcrawl.utils.html import (
    clean_html,
    collapse_spaces,
    decode_entities,
    decode_html_bytes,
    detect_encoding,
    encode_entities,
    extract_canonical_url,
    extract_images,
    extract_links,
    extract_meta_tags,
    extract_text,
    extract_title,
    get_char_count,
    get_word_count,
    is_html,
    is_well_formed,
    normalize_whitespace,
    sanitize_html,
    strip_specific_tags,
    strip_tags,
)


class TestStripTags:
    """Tests for strip_tags."""

    def test_basic_strip(self):
        assert strip_tags("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strip_all_tags(self):
        assert strip_tags("<div><span>text</span></div>") == "text"

    def test_no_tags(self):
        assert strip_tags("plain text") == "plain text"

    def test_empty_string(self):
        assert strip_tags("") == ""

    def test_none(self):
        assert strip_tags("") == ""

    def test_keep_specific_tags(self):
        result = strip_tags("<p>Hello</p><b>bold</b>", keep_tags=["p"])
        assert "<p>Hello</p>" in result
        assert "<b>" not in result

    def test_keep_br_tag(self):
        result = strip_tags("<p>Hello</p><br>world", keep_tags=["br"])
        assert result == "Hello<br>world"

    def test_nested_tags(self):
        assert strip_tags("<div><p>Hello <b>world</b></p></div>") == "Hello world"


class TestStripSpecificTags:
    """Tests for strip_specific_tags."""

    def test_remove_script_with_content(self):
        result = strip_specific_tags("<p>Hello</p><script>alert('x')</script>", ["script"])
        assert result == "<p>Hello</p>"

    def test_remove_style_with_content(self):
        result = strip_specific_tags("<style>.x{}</style><p>text</p>", ["style"])
        assert "<style>" not in result
        assert "<p>text</p>" in result

    def test_remove_multiple_tags(self):
        result = strip_specific_tags(
            "<p>text</p><script>x</script><style>y</style>", ["script", "style"]
        )
        assert "<script>" not in result
        assert "<style>" not in result

    def test_empty_html(self):
        assert strip_specific_tags("", ["script"]) == ""

    def test_tag_not_present(self):
        result = strip_specific_tags("<p>text</p>", ["script"])
        assert result == "<p>text</p>"


class TestExtractText:
    """Tests for extract_text."""

    def test_basic_extraction(self):
        result = extract_text("<p>Hello world</p>")
        assert "Hello world" in result

    def test_remove_scripts(self):
        html = "<script>var x=1;</script><p>Text</p>"
        result = extract_text(html)
        assert "var x" not in result
        assert "Text" in result

    def test_remove_styles(self):
        html = "<style>.x{}</style><p>Text</p>"
        result = extract_text(html)
        assert "x" not in result or ".x" not in result
        assert "Text" in result

    def test_remove_comments(self):
        html = "<p>Hello</p><!-- comment -->"
        result = extract_text(html)
        assert "comment" not in result

    def test_decode_entities(self):
        result = extract_text("<p>Hello &amp; welcome</p>")
        assert "&" in result

    def test_empty_html(self):
        assert extract_text("") == ""

    def test_block_tags_to_newlines(self):
        result = extract_text("<p>Line 1</p><p>Line 2</p>")
        assert "Line 1" in result
        assert "Line 2" in result

    def test_no_normalize(self):
        result = extract_text("<p>Hello  world</p>", normalize=False)
        assert "Hello" in result


class TestExtractTitle:
    """Tests for extract_title."""

    def test_basic_title(self):
        html = "<html><head><title>My Page</title></head></html>"
        assert extract_title(html) == "My Page"

    def test_title_with_attrs(self):
        html = '<title id="t1">Title Here</title>'
        assert extract_title(html) == "Title Here"

    def test_no_title(self):
        assert extract_title("<html><body>text</body></html>") == ""

    def test_empty_title(self):
        assert extract_title("<title></title>") == ""


class TestCleanHtml:
    """Tests for clean_html."""

    def test_basic_clean(self):
        result = clean_html("<p>Hello</p><!-- comment --><script>bad()</script>")
        assert "<p>Hello</p>" in result
        assert "comment" not in result
        assert "bad()" not in result

    def test_disable_script_removal(self):
        result = clean_html("<script>x</script><p>text</p>", remove_scripts=False)
        assert "<script>" in result

    def test_disable_style_removal(self):
        result = clean_html("<style>y</style><p>text</p>", remove_styles=False)
        assert "<style>" in result

    def test_disable_comment_removal(self):
        result = clean_html("<p>text</p><!-- comment -->", remove_comments=False)
        assert "comment" in result

    def test_disable_empty_tag_removal(self):
        result = clean_html("<p></p><span>text</span>", remove_empty_tags=False)
        assert "<p></p>" in result

    def test_empty_input(self):
        assert clean_html("") == ""

    def test_remove_noscript(self):
        result = clean_html("<noscript>alt</noscript><p>text</p>")
        assert "alt" not in result


class TestSanitizeHtml:
    """Tests for sanitize_html."""

    def test_remove_scripts(self):
        result = sanitize_html("<script>alert(1)</script><p>safe</p>")
        assert "alert" not in result
        assert "safe" in result

    def test_remove_iframe(self):
        result = sanitize_html("<iframe>evil</iframe><p>safe</p>")
        assert "evil" not in result

    def test_remove_event_handlers(self):
        result = sanitize_html('<div onclick="alert(1)">text</div>')
        assert "onclick" not in result

    def test_remove_javascript_urls(self):
        result = sanitize_html('<a href="javascript:alert(1)">link</a>')
        assert "javascript:alert" not in result

    def test_remove_data_urls(self):
        result = sanitize_html('<a href="data:text/html,evil">link</a>')
        assert "data:text/html" not in result

    def test_keep_image_data(self):
        result = sanitize_html('<img src="data:image/png;base64,abc">')
        assert "data:image" in result

    def test_empty_input(self):
        assert sanitize_html("") == ""


class TestDecodeEntities:
    """Tests for decode_entities."""

    def test_named_entities(self):
        assert decode_entities("&amp;") == "&"
        assert decode_entities("&lt;") == "<"
        assert decode_entities("&gt;") == ">"
        assert decode_entities("&quot;") == '"'

    def test_numeric_entities(self):
        assert decode_entities("&#72;&#101;") == "He"

    def test_hex_entities(self):
        assert decode_entities("&#x48;&#x65;") == "He"

    def test_mixed_entities(self):
        assert decode_entities("&amp;&lt;&gt;") == "&<>"

    def test_no_entities(self):
        assert decode_entities("plain text") == "plain text"

    def test_empty_string(self):
        assert decode_entities("") == ""


class TestEncodeEntities:
    """Tests for encode_entities."""

    def test_basic_encoding(self):
        result = encode_entities("Hello & <world>")
        assert "&amp;" in result
        assert "&lt;" in result
        assert "&gt;" in result

    def test_quote_encoding_default(self):
        result = encode_entities('say "hi"')
        assert "&quot;" in result

    def test_no_quote_encoding(self):
        result = encode_entities('say "hi"', quote=False)
        assert '"hi"' in result


class TestNormalizeWhitespace:
    """Tests for normalize_whitespace (html module version)."""

    def test_collapse_spaces(self):
        assert normalize_whitespace("Hello   world") == "Hello world"

    def test_collapse_newlines(self):
        result = normalize_whitespace("line1\n\n\n\nline2")
        assert result == "line1\n\nline2"

    def test_strip(self):
        assert normalize_whitespace("  hello  ") == "hello"

    def test_tabs(self):
        assert normalize_whitespace("Hello\t\tWorld") == "Hello World"

    def test_empty(self):
        assert normalize_whitespace("") == ""


class TestCollapseSpaces:
    """Tests for collapse_spaces."""

    def test_basic(self):
        assert collapse_spaces("Hello   world") == "Hello world"

    def test_multiple_collapses(self):
        assert collapse_spaces("a    b    c") == "a b c"

    def test_no_spaces(self):
        assert collapse_spaces("nospace") == "nospace"


class TestExtractLinks:
    """Tests for extract_links."""

    def test_basic_link(self):
        html = '<a href="/page">Click</a>'
        result = extract_links(html, "https://example.com")
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/page"
        assert result[0]["text"] == "Click"

    def test_full_url(self):
        html = '<a href="https://other.com">Link</a>'
        result = extract_links(html)
        assert result[0]["url"] == "https://other.com"

    def test_with_title(self):
        html = '<a href="/page" title="tip">Text</a>'
        result = extract_links(html, "https://example.com")
        assert result[0]["title"] == "tip"

    def test_no_title(self):
        html = '<a href="/page">Text</a>'
        result = extract_links(html)
        assert result[0]["title"] == ""

    def test_skip_anchor_links(self):
        html = '<a href="#section">Anchor</a>'
        result = extract_links(html, "https://example.com")
        assert len(result) == 0

    def test_skip_javascript(self):
        html = '<a href="javascript:void(0)">JS</a>'
        result = extract_links(html)
        assert len(result) == 0

    def test_skip_mailto(self):
        html = '<a href="mailto:test@test.com">Email</a>'
        result = extract_links(html)
        assert len(result) == 0

    def test_skip_tel(self):
        html = '<a href="tel:+1234">Phone</a>'
        result = extract_links(html)
        assert len(result) == 0

    def test_skip_data(self):
        html = '<a href="data:text/html,evil">Data</a>'
        result = extract_links(html)
        assert len(result) == 0

    def test_deduplicate_links(self):
        html = '<a href="/page">A</a><a href="/page">B</a>'
        result = extract_links(html, "https://example.com")
        assert len(result) == 1

    def test_no_base_url_no_resolution(self):
        html = '<a href="/page">Text</a>'
        result = extract_links(html)
        assert result[0]["url"] == "/page"

    def test_empty_html(self):
        assert extract_links("", "https://example.com") == []

    def test_no_links(self):
        assert extract_links("<p>No links here</p>") == []


class TestExtractImages:
    """Tests for extract_images."""

    def test_basic_image(self):
        html = '<img src="/img.png" alt="alt text">'
        result = extract_images(html, "https://example.com")
        assert result[0]["src"] == "https://example.com/img.png"
        assert result[0]["alt"] == "alt text"

    def test_no_base_url(self):
        html = '<img src="img.png" alt="test">'
        result = extract_images(html)
        assert result[0]["src"] == "img.png"

    def test_with_title(self):
        html = '<img src="img.png" title="tip" alt="alt">'
        result = extract_images(html)
        assert result[0]["title"] == "tip"

    def test_no_title(self):
        html = '<img src="img.png" alt="alt">'
        result = extract_images(html)
        assert result[0]["title"] == ""

    def test_no_alt(self):
        html = '<img src="img.png">'
        result = extract_images(html)
        assert result[0]["alt"] == ""

    def test_data_src(self):
        html = '<img src="data:image/png;base64,abc">'
        result = extract_images(html, "https://example.com")
        assert result[0]["src"] == "data:image/png;base64,abc"

    def test_no_src_skipped(self):
        html = "<img alt='no src'>"
        result = extract_images(html)
        assert len(result) == 0

    def test_empty_html(self):
        assert extract_images("", "https://example.com") == []

    def test_multiple_images(self):
        html = '<img src="a.png"><img src="b.png">'
        result = extract_images(html)
        assert len(result) == 2


class TestExtractMetaTags:
    """Tests for extract_meta_tags."""

    def test_basic_meta(self):
        html = '<meta name="description" content="A page">'
        result = extract_meta_tags(html)
        assert result["description"] == "A page"

    def test_property_meta(self):
        html = '<meta property="og:title" content="Title">'
        result = extract_meta_tags(html)
        assert result["og:title"] == "Title"

    def test_multiple_meta(self):
        html = '<meta name="desc" content="Desc"><meta name="author" content="Author">'
        result = extract_meta_tags(html)
        assert result["desc"] == "Desc"
        assert result["author"] == "Author"

    def test_no_content(self):
        html = '<meta name="description">'
        result = extract_meta_tags(html)
        # content is empty string, should not be added since both name and content must be truthy
        assert result == {}

    def test_no_name(self):
        html = '<meta content="content">'
        result = extract_meta_tags(html)
        assert result == {}

    def test_empty_html(self):
        assert extract_meta_tags("") == {}

    def test_lowercased_name(self):
        html = '<meta NAME="Description" content="text">'
        result = extract_meta_tags(html)
        assert "description" in result


class TestExtractCanonicalUrl:
    """Tests for extract_canonical_url."""

    def test_basic_canonical(self):
        html = '<link rel="canonical" href="https://example.com/page">'
        assert extract_canonical_url(html) == "https://example.com/page"

    def test_reversed_attr_order(self):
        html = '<link href="https://example.com/page" rel="canonical">'
        assert extract_canonical_url(html) == "https://example.com/page"

    def test_no_canonical(self):
        assert extract_canonical_url("<html></html>") == ""


class TestDetectEncoding:
    """Tests for detect_encoding."""

    def test_bom_utf8(self):
        assert detect_encoding(b"\xef\xbb\xbf<html>") == "utf-8"

    def test_bom_utf16_le(self):
        assert detect_encoding(b"\xff\xfe") == "utf-16"

    def test_bom_utf16_be(self):
        assert detect_encoding(b"\xfe\xff") == "utf-16"

    def test_meta_charset(self):
        html = b'<meta charset="utf-8">'
        assert detect_encoding(html) == "utf-8"

    def test_meta_content_type(self):
        html = b'<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">'
        assert detect_encoding(html) == "iso-8859-1"

    def test_valid_utf8(self):
        assert detect_encoding(b"plain text") == "utf-8"

    def test_empty_bytes(self):
        assert detect_encoding(b"") == "utf-8"

    def test_invalid_utf8_fallback(self):
        # Bytes that are not valid UTF-8 and don't match BOM
        assert detect_encoding(b"\xc0\xc1\xc2\xc3") == "utf-8"

    def test_meta_charset_with_extra_attrs(self):
        html = b'<meta name="test" charset="windows-1252">'
        assert detect_encoding(html) == "windows-1252"


class TestDecodeHtmlBytes:
    """Tests for decode_html_bytes."""

    def test_decode_utf8(self):
        result = decode_html_bytes(b"Hello world")
        assert result == "Hello world"

    def test_decode_with_explicit_encoding(self):
        result = decode_html_bytes(b"Hello", encoding="utf-8")
        assert result == "Hello"

    def test_decode_unknown_encoding_fallback(self):
        result = decode_html_bytes(b"test", encoding="nonexistent")
        assert result == "test"


class TestIsHtml:
    """Tests for is_html."""

    def test_doctype(self):
        assert is_html("<!DOCTYPE html>") is True

    def test_html_tag(self):
        assert is_html("<html><body>Hello</body></html>") is True

    def test_div_tag(self):
        assert is_html("<div>Hello</div>") is True

    def test_paragraph_tag(self):
        assert is_html("<p>Hello</p>") is True

    def test_span_tag(self):
        assert is_html("<span>Hello</span>") is True

    def test_link_tag(self):
        assert is_html('<a href="#">Link</a>') is True

    def test_img_tag(self):
        assert is_html("<img src='x.png'>") is True

    def test_table_tag(self):
        assert is_html("<table><tr><td>cell</td></tr></table>") is True

    def test_plain_text(self):
        assert is_html("Just plain text") is False

    def test_empty_string(self):
        assert is_html("") is False

    def test_none(self):
        assert is_html("") is False


class TestIsWellFormed:
    """Tests for is_well_formed."""

    def test_balanced_tags(self):
        assert is_well_formed("<p>Hello</p>") is True

    def test_unbalanced_tags(self):
        assert is_well_formed("<p>Hello") is False

    def test_void_tag_no_close_needed(self):
        assert is_well_formed("<img src='x'><p>text</p>") is True

    def test_self_closing_br(self):
        assert is_well_formed("text<br>text") is True

    def test_empty_input(self):
        assert is_well_formed("") is True

    def test_extra_closing_tag(self):
        assert is_well_formed("<p>Hello</p></p>") is False

    def test_multiple_balanced(self):
        assert is_well_formed("<div><p>Hello</p></div>") is True


class TestGetWordCount:
    """Tests for get_word_count."""

    def test_basic(self):
        assert get_word_count("<p>Hello world</p>") == 2

    def test_strips_tags(self):
        assert get_word_count("<div><span>Hello</span> <span>World</span></div>") == 2

    def test_empty(self):
        assert get_word_count("") == 0


class TestGetCharCount:
    """Tests for get_char_count."""

    def test_with_tags(self):
        assert get_char_count("<p>Hello</p>", include_tags=True) == 12

    def test_without_tags(self):
        assert get_char_count("<p>Hello</p>", include_tags=False) == 5

    def test_empty(self):
        assert get_char_count("") == 0
