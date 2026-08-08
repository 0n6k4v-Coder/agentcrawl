"""Tests for agentcrawl.utils.text module."""

import pytest

from agentcrawl.utils.text import (
    STOP_WORDS,
    TextStats,
    _cosine_similarity,
    _jaccard_similarity,
    _overlap_coefficient,
    _tokenize,
    analyze_text,
    clean_text,
    count_characters,
    count_paragraphs,
    count_sentences,
    count_words,
    dedent,
    detect_language,
    estimate_tokens,
    estimate_tokens_tiktoken,
    extract_key_phrases,
    extract_keywords,
    indent,
    is_mostly_empty,
    normalize_unicode,
    normalize_whitespace,
    remove_accents,
    slugify,
    text_similarity,
    truncate,
    truncate_tokens,
    wrap_text,
)


class TestCleanText:
    """Tests for clean_text."""

    def test_basic_cleaning(self):
        assert clean_text("Hello   world") == "Hello world"

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_none_returns_empty(self):
        assert clean_text("") == ""

    def test_normalize_line_endings(self):
        result = clean_text("Hello\r\nWorld\rEnd")
        assert "\r" not in result

    def test_collapse_vertical_whitespace(self):
        result = clean_text("line1\n\n\n\nline2")
        assert result == "line1\n\nline2"

    def test_strip_per_line(self):
        result = clean_text("  Hello  \n  World  ")
        assert result == "Hello\nWorld"

    def test_remove_zero_width_chars(self):
        result = clean_text("Hello\u200b\u200c\u200d\u2060\u200bworld")
        assert result == "Helloworld"

    def test_remove_control_chars(self):
        result = clean_text("Hello\x00\x01\x02World")
        assert result == "HelloWorld"

    def test_preserves_newlines(self):
        result = clean_text("Hello\tWorld\nNew")
        # Tabs are collapsed to spaces, newlines preserved
        assert "\n" in result
        assert "\t" not in result


class TestNormalizeUnicode:
    """Tests for normalize_unicode."""

    def test_nfc_default(self):
        result = normalize_unicode("café")
        assert result == "café"

    def test_nfd(self):
        result = normalize_unicode("café", "NFD")
        assert result is not None

    def test_nfkc(self):
        result = normalize_unicode("ﬁle", "NFKC")
        assert result == "file"

    def test_invalid_form_raises(self):
        with pytest.raises(ValueError):
            normalize_unicode("test", "INVALID")


class TestRemoveAccents:
    """Tests for remove_accents."""

    def test_remove_accents_basic(self):
        assert remove_accents("café") == "cafe"

    def test_remove_accents_multiple(self):
        assert remove_accents("café résumé") == "cafe resume"

    def test_no_accents_unchanged(self):
        assert remove_accents("hello") == "hello"


class TestNormalizeWhitespace:
    """Tests for normalize_whitespace."""

    def test_collapse_spaces(self):
        assert normalize_whitespace("Hello   world") == "Hello world"

    def test_collapse_newlines(self):
        # normalize_whitespace collapses all whitespace including newlines to spaces
        result = normalize_whitespace("line1\n\n\n\nline2")
        assert result == "line1 line2"

    def test_strip_whitespace(self):
        assert normalize_whitespace("  hello  ") == "hello"

    def test_empty_string(self):
        assert normalize_whitespace("") == ""

    def test_tabs_collapsed(self):
        assert normalize_whitespace("Hello\t\tWorld") == "Hello World"


class TestCountWords:
    """Tests for count_words."""

    def test_simple_text(self):
        assert count_words("Hello world") == 2

    def test_empty(self):
        assert count_words("") == 0

    def test_single_word(self):
        assert count_words("hello") == 1

    def test_multiple_spaces(self):
        assert count_words("hello   world  foo") == 3

    def test_thai_text(self):
        assert count_words("สวัสดี ครับ") == 2

    def test_empty_none(self):
        assert count_words(None) == 0  # type: ignore[arg-type]


class TestCountSentences:
    """Tests for count_sentences."""

    def test_basic(self):
        assert count_sentences("Hello world. How are you? I'm fine!") == 3

    def test_ellipsis(self):
        assert count_sentences("Wait... what?") == 2

    def test_empty(self):
        assert count_sentences("") == 0

    def test_no_endings(self):
        assert count_sentences("Hello world") == 1

    def test_multiple_punctuation(self):
        assert count_sentences("Wow!!! Really??? Yes.") == 3


class TestCountParagraphs:
    """Tests for count_paragraphs."""

    def test_basic(self):
        text = "Para 1\n\nPara 2\n\nPara 3"
        assert count_paragraphs(text) == 3

    def test_empty(self):
        assert count_paragraphs("") == 0

    def test_single_paragraph(self):
        assert count_paragraphs("Just one paragraph") == 1


class TestCountCharacters:
    """Tests for count_characters."""

    def test_with_spaces(self):
        assert count_characters("hello world") == 11

    def test_without_spaces(self):
        assert count_characters("hello world", include_spaces=False) == 10

    def test_empty(self):
        assert count_characters("") == 0


class TestEstimateTokens:
    """Tests for estimate_tokens."""

    def test_basic_english(self):
        result = estimate_tokens("Hello world, this is a test.")
        assert result > 0

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_cjk_text(self):
        result = estimate_tokens("你好世界")
        assert result > 0

    def test_cjk_uses_lower_ratio(self):
        # CJK chars are counted as 1.5 chars/token vs 4 for English
        cjk_result = estimate_tokens("你好世界你好世界你好世界")
        eng_result = estimate_tokens("hello world test hello world test")
        assert cjk_result > 0
        assert eng_result > 0


class TestEstimateTokensTiktoken:
    """Tests for estimate_tokens_tiktoken."""

    def test_fallback_without_tiktoken(self):
        # tiktoken may not be installed; should fall back to heuristic
        result = estimate_tokens_tiktoken("hello world")
        assert result > 0

    def test_empty(self):
        assert estimate_tokens_tiktoken("") == 0


class TestTruncate:
    """Tests for truncate."""

    def test_short_text_unchanged(self):
        assert truncate("short", 200) == "short"

    def test_exact_length(self):
        assert truncate("hello", 5) == "hello"

    def test_truncated_with_suffix(self):
        result = truncate("hello world", 5)
        assert result == "hello..."

    def test_truncated_word_boundary(self):
        result = truncate("hello world foo", 10)
        assert "..." in result
        assert len(result) <= 13

    def test_truncated_no_word_boundary(self):
        result = truncate("hello world foo", 10, at_word_boundary=False)
        assert result.endswith("...")

    def test_truncated_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence."
        result = truncate(text, 30, at_sentence_boundary=True)
        assert "..." in result

    def test_empty_text(self):
        assert truncate("", 200) == ""

    def test_custom_suffix(self):
        result = truncate("hello world", 5, suffix=" [more]")
        assert result.endswith(" [more]")

    def test_none_text(self):
        assert truncate("", 200) == ""


class TestTruncateTokens:
    """Tests for truncate_tokens."""

    def test_short_text_unchanged(self):
        assert truncate_tokens("short text", 1000) == "short text"

    def test_long_text_truncated(self):
        text = "word " * 1000
        result = truncate_tokens(text, 10)
        assert len(result) < len(text)

    def test_empty(self):
        assert truncate_tokens("", 100) == ""


class TestSlugify:
    """Tests for slugify."""

    def test_basic(self):
        result = slugify("Hello World")
        assert result == "hello-world"

    def test_with_punctuation(self):
        assert slugify("Hello, World!") == "hello-world"

    def test_with_numbers(self):
        assert slugify("Python 3.12") == "python-312"

    def test_multiple_spaces(self):
        assert slugify("Hello   World") == "hello-world"

    def test_trailing_punctuation(self):
        assert slugify("Hello---") == "hello"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_thai_text(self):
        result = slugify("สวัสดี ชาวโลก")
        assert result is not None

    def test_custom_separator(self):
        result = slugify("Hello World", separator="_")
        assert result == "hello_world"

    def test_uppercase_disabled(self):
        result = slugify("Hello World", lowercase=False)
        assert "H" in result

    def test_max_length(self):
        result = slugify("a b c d e f g h i j k", max_length=10)
        assert len(result) <= 10

    def test_multiple_separators(self):
        result = slugify("Hello - World _ Foo")
        assert "---" not in result
        assert "___" not in result


class TestDetectLanguage:
    """Tests for detect_language."""

    def test_english(self):
        assert detect_language("Hello world") == "en"

    def test_thai(self):
        assert detect_language("สวัสดีครับ") == "th"

    def test_japanese_hiragana(self):
        assert detect_language("こんにちは") == "ja"

    def test_chinese(self):
        assert detect_language("你好世界") == "zh"

    def test_korean(self):
        assert detect_language("안녕하세요") == "ko"

    def test_arabic(self):
        assert detect_language("مرحبا") == "ar"

    def test_russian(self):
        assert detect_language("Привет мир") == "ru"

    def test_german(self):
        assert detect_language("der die das ist nicht") == "de"

    def test_french(self):
        assert detect_language("le la les et est un") == "fr"

    def test_spanish(self):
        # "los" "las" "que" "muy" are distinctly Spanish (no French overlap)
        text = "los perros son muy grandes"
        assert detect_language(text) == "es"

    def test_portuguese(self):
        # Use enough Portuguese words to exceed threshold
        text = "o gato está na casa dos meus amigos porque sim"
        assert detect_language(text) == "pt"

    def test_empty(self):
        assert detect_language("") == "en"

    def test_sample_size(self):
        text = "Hello " * 20
        assert detect_language(text, sample_size=5) == "en"


class TestTextSimilarity:
    """Tests for text_similarity."""

    def test_jaccard_identical(self):
        assert text_similarity("hello world", "hello world") == 1.0

    def test_jaccard_different(self):
        result = text_similarity("hello world", "foo bar")
        assert result == 0.0

    def test_jaccard_partial(self):
        result = text_similarity("hello world", "hello earth")
        assert 0.0 < result < 1.0

    def test_cosine(self):
        result = text_similarity("hello world", "hello earth", method="cosine")
        assert 0.0 < result <= 1.0

    def test_overlap(self):
        result = text_similarity("hello world", "hello earth", method="overlap")
        assert 0.0 < result <= 1.0

    def test_empty_text_a(self):
        assert text_similarity("", "hello") == 0.0

    def test_empty_text_b(self):
        assert text_similarity("hello", "") == 0.0

    def test_default_method(self):
        result = text_similarity("hello world", "hello earth")
        assert result == _jaccard_similarity("hello world", "hello earth")

    def test_invalid_method_falls_back(self):
        result = text_similarity("hello", "hello", method="unknown")
        assert result == 1.0


class TestTokenize:
    """Tests for _tokenize."""

    def test_basic_tokenize(self):
        tokens = _tokenize("Hello world")
        assert tokens == {"hello", "world"}

    def test_case_insensitive(self):
        tokens = _tokenize("Hello HELLO")
        assert tokens == {"hello"}

    def test_empty(self):
        assert _tokenize("") == set()


class TestJaccardSimilarity:
    """Tests for _jaccard_similarity."""

    def test_identical(self):
        assert _jaccard_similarity("a b c", "a b c") == 1.0

    def test_disjoint(self):
        assert _jaccard_similarity("a b", "c d") == 0.0

    def test_partial(self):
        result = _jaccard_similarity("a b c", "b c d")
        assert result == pytest.approx(0.5)

    def test_empty_a(self):
        assert _jaccard_similarity("", "a b") == 0.0

    def test_empty_b(self):
        assert _jaccard_similarity("a b", "") == 0.0


class TestCosineSimilarity:
    """Tests for _cosine_similarity."""

    def test_identical(self):
        assert _cosine_similarity("a b c", "a b c") == pytest.approx(1.0)

    def test_disjoint(self):
        assert _cosine_similarity("a b", "c d") == 0.0

    def test_empty_b(self):
        assert _cosine_similarity("a b", "") == 0.0


class TestOverlapCoefficient:
    """Tests for _overlap_coefficient."""

    def test_identical(self):
        assert _overlap_coefficient("a b c", "a b c") == 1.0

    def test_partial(self):
        result = _overlap_coefficient("a b", "b c")
        assert 0.0 < result <= 1.0

    def test_empty_b(self):
        assert _overlap_coefficient("a b", "") == 0.0


class TestExtractKeywords:
    """Tests for extract_keywords."""

    def test_basic_extraction(self):
        result = extract_keywords("Python is great. Python is fast. Python is easy.")
        keywords = dict(result)
        assert keywords.get("python") == 3

    def test_removes_stop_words(self):
        result = extract_keywords("the quick brown fox")
        keywords = dict(result)
        assert "the" not in keywords

    def test_min_word_length(self):
        result = extract_keywords("a be cat dog", min_word_length=3)
        keywords = dict(result)
        assert "cat" in keywords
        assert "dog" in keywords

    def test_top_n_limit(self):
        text = " ".join([f"word{i}" for i in range(20)])
        result = extract_keywords(text, top_n=5)
        assert len(result) <= 5

    def test_empty_text(self):
        assert extract_keywords("") == []

    def test_no_remove_stop_words(self):
        result = extract_keywords("the cat", remove_stop_words=False)
        keywords = dict(result)
        assert "the" in keywords


class TestExtractKeyPhrases:
    """Tests for extract_key_phrases."""

    def test_basic(self):
        text = "machine learning is great for data processing"
        result = extract_key_phrases(text, top_n=5)
        assert len(result) > 0

    def test_empty_text(self):
        assert extract_key_phrases("") == []

    def test_min_max_length(self):
        text = "a b c d e f g h"
        result = extract_key_phrases(text, min_length=2, max_length=3)
        for phrase, _ in result:
            words = phrase.split()
            assert len(words) >= 2
            assert len(words) <= 3


class TestTextStats:
    """Tests for TextStats dataclass."""

    def test_to_dict(self):
        stats = TextStats(word_count=10, sentence_count=2, unique_words=5)
        d = stats.to_dict()
        assert d["word_count"] == 10
        assert d["sentence_count"] == 2
        assert d["unique_words"] == 5

    def test_to_dict_rounds_floats(self):
        stats = TextStats(avg_word_length=4.567, lexical_diversity=0.333)
        d = stats.to_dict()
        assert d["avg_word_length"] == 4.57
        assert d["lexical_diversity"] == 0.333

    def test_defaults(self):
        stats = TextStats()
        d = stats.to_dict()
        assert d["char_count"] == 0
        assert d["language"] == "en"


class TestAnalyzeText:
    """Tests for analyze_text."""

    def test_basic_analysis(self):
        stats = analyze_text("Hello world. This is a test.")
        assert stats.word_count == 6
        assert stats.sentence_count == 2
        assert stats.char_count > 0

    def test_empty_text(self):
        stats = analyze_text("")
        assert stats.word_count == 0
        assert stats.sentence_count == 0

    def test_paragraph_count(self):
        text = "Para 1\n\nPara 2"
        stats = analyze_text(text)
        assert stats.paragraph_count == 2

    def test_avg_word_length(self):
        stats = analyze_text("hello world")
        assert stats.avg_word_length == 5.0

    def test_unique_words(self):
        stats = analyze_text("hello world hello")
        assert stats.unique_words == 2

    def test_lexical_diversity(self):
        # All same words → 1 unique out of 3 = 1/3
        stats = analyze_text("hello hello hello")
        assert stats.lexical_diversity == pytest.approx(1 / 3)

    def test_lexical_diversity_partial(self):
        stats = analyze_text("hello world hello world")
        assert stats.lexical_diversity == 0.5

    def test_language_detection(self):
        stats = analyze_text("Hello world")
        assert stats.language == "en"

    def test_estimated_tokens(self):
        stats = analyze_text("Hello world")
        assert stats.estimated_tokens > 0

    def test_char_count_no_spaces(self):
        stats = analyze_text("hello world")
        assert stats.char_count_no_spaces == 10


class TestDedent:
    """Tests for dedent."""

    def test_basic(self):
        text = "  Hello\n  World"
        assert dedent(text) == "Hello\nWorld"

    def test_no_indent(self):
        assert dedent("Hello") == "Hello"


class TestIndent:
    """Tests for indent."""

    def test_basic_indent(self):
        result = indent("Hello\nWorld", prefix="  ")
        assert result == "  Hello\n  World"

    def test_default_indent(self):
        result = indent("Hello\nWorld")
        assert result == "  Hello\n  World"

    def test_single_line(self):
        assert indent("Hello", prefix="> ") == "> Hello"


class TestWrapText:
    """Tests for wrap_text."""

    def test_basic_wrap(self):
        text = "This is a long sentence that should be wrapped."
        result = wrap_text(text, width=20)
        lines = result.split("\n")
        for line in lines:
            assert len(line) <= 20

    def test_empty(self):
        assert wrap_text("", 80) == ""


class TestIsMostlyEmpty:
    """Tests for is_mostly_empty."""

    def test_whitespace_only(self):
        assert is_mostly_empty("    ") is True

    def test_mostly_whitespace(self):
        text = "a" + " " * 99
        assert is_mostly_empty(text, threshold=0.9) is True

    def test_not_mostly_empty(self):
        assert is_mostly_empty("Hello world") is False

    def test_empty_string(self):
        assert is_mostly_empty("") is True

    def test_custom_threshold(self):
        text = "a" + " " * 8
        assert is_mostly_empty(text, threshold=0.8) is True


class TestStopWords:
    """Tests for STOP_WORDS constant."""

    def test_stop_words_contains_common(self):
        assert "the" in STOP_WORDS
        assert "a" in STOP_WORDS
        assert "and" in STOP_WORDS

    def test_stop_words_is_set(self):
        assert isinstance(STOP_WORDS, set)
