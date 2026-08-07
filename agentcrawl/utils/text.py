"""
AgentCrawl — Text Utilities
===============================

Text processing utilities for cleaning, normalization, counting,
truncation, and analysis.

Features:
    - Text cleaning and normalization
    - Unicode normalization (NFC, NFKC)
    - Word, sentence, and paragraph counting
    - Smart text truncation
    - Slug generation
    - Basic language detection
    - Token estimation
    - Text similarity (Jaccard, cosine)
    - Keyword extraction

Usage:
    from agentcrawl.utils.text import (
        clean_text,
        normalize_unicode,
        count_words,
        count_sentences,
        truncate,
        slugify,
        detect_language,
        estimate_tokens,
        text_similarity,
        extract_keywords,
    )

    # Clean text
    clean = clean_text("Hello   world\\n\\n\\nNew para")

    # Count
    words = count_words(text)
    sentences = count_sentences(text)
    tokens = estimate_tokens(text)

    # Truncate
    short = truncate(text, max_length=200)

    # Slug
    slug = slugify("Hello World! Python 3.12")
    # → "hello-world-python-312"

    # Language detection
    lang = detect_language("สวัสดีครับ")  # → "th"

    # Similarity
    score = text_similarity("hello world", "hello earth")
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal, cast

# ══════════════════════════════════════════════════════════════
# Cleaning & Normalization
# ══════════════════════════════════════════════════════════════


def clean_text(text: str) -> str:
    """
    Clean and normalize text content.

    - Normalizes Unicode to NFC
    - Removes zero-width characters
    - Normalizes line endings
    - Collapses excessive whitespace
    - Strips leading/trailing whitespace

    Args:
        text: Input text.

    Returns:
        Cleaned text.

    Example:
        >>> clean_text("Hello\\u200b world\\r\\n\\r\\n\\r\\nNew")
        'Hello world\\n\\nNew'
    """
    if not text:
        return ""

    # Unicode normalization
    text = unicodedata.normalize("NFC", text)

    # Remove zero-width characters
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text)

    # Remove control characters (except newline, tab)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse horizontal whitespace
    text = re.sub(r"[ \t]+", " ", text)

    # Collapse vertical whitespace (3+ newlines → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip per-line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


_VALID_NORMALIZE_FORMS: tuple[Literal["NFC", "NFD", "NFKC", "NFKD"], ...] = (
    "NFC",
    "NFD",
    "NFKC",
    "NFKD",
)


def normalize_unicode(text: str, form: str = "NFC") -> str:
    """
    Normalize Unicode text to specified form.

    Args:
        text: Input text to normalize.
        form: Normalization form ('NFC', 'NFD', 'NFKC', 'NFKD').

    Returns:
        Normalized text.

    Raises:
        ValueError: If form is not one of the valid normalization forms.

    Example:
        >>> normalize_unicode("café", "NFC")  # Composed form
        >>> normalize_unicode("ﬁle", "NFKC")  # → "file"
    """
    # Runtime validation ensures form is valid before cast
    if form not in _VALID_NORMALIZE_FORMS:
        raise ValueError(
            f"Invalid normalization form: {form!r}. "
            f"Must be one of: {_VALID_NORMALIZE_FORMS}"
        )

    # cast is safe because runtime validation above ensures form is valid
    typed_form = cast("Literal['NFC', 'NFD', 'NFKC', 'NFKD']", form)
    return unicodedata.normalize(typed_form, text)


def remove_accents(text: str) -> str:
    """
    Remove diacritical marks (accents) from text.

    Args:
        text: Input text.

    Returns:
        Text without accents.

    Example:
        >>> remove_accents("café résumé")
        'cafe resume'
    """
    # Decompose to NFD, then remove combining marks
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def normalize_whitespace(text: str) -> str:
    """
    Normalize all whitespace to single spaces.

    Args:
        text: Input text.

    Returns:
        Text with normalized whitespace.
    """
    return re.sub(r"\s+", " ", text).strip()


# ══════════════════════════════════════════════════════════════
# Counting
# ══════════════════════════════════════════════════════════════


def count_words(text: str) -> int:
    """
    Count words in text.

    Handles multiple languages including CJK (counts characters
    as words for CJK text).

    Args:
        text: Input text.

    Returns:
        Word count.

    Example:
        >>> count_words("Hello world")
        2
        >>> count_words("สวัสดี ครับ")
        2
    """
    if not text:
        return 0

    # For CJK text, count characters
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]", text))
    if cjk_chars > len(text) * 0.3:
        # Mixed: count CJK chars + non-CJK words
        non_cjk = re.sub(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]", " ", text)
        non_cjk_words = len(non_cjk.split())
        return cjk_chars + non_cjk_words

    return len(text.split())


def count_sentences(text: str) -> int:
    """
    Count sentences in text.

    Args:
        text: Input text.

    Returns:
        Sentence count.

    Example:
        >>> count_sentences("Hello world. How are you? I'm fine!")
        3
    """
    if not text:
        return 0

    # Split on sentence-ending punctuation
    sentences = re.split(r"[.!?…]+", text)
    # Filter empty strings
    sentences = [s.strip() for s in sentences if s.strip()]
    return len(sentences)


def count_paragraphs(text: str) -> int:
    """
    Count paragraphs in text.

    Args:
        text: Input text.

    Returns:
        Paragraph count.
    """
    if not text:
        return 0

    paragraphs = re.split(r"\n{2,}", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    return len(paragraphs)


def count_characters(text: str, include_spaces: bool = True) -> int:
    """
    Count characters in text.

    Args:
        text: Input text.
        include_spaces: Whether to count spaces.

    Returns:
        Character count.
    """
    if include_spaces:
        return len(text)
    return len(text.replace(" ", "").replace("\t", "").replace("\n", ""))


# ══════════════════════════════════════════════════════════════
# Token Estimation
# ══════════════════════════════════════════════════════════════


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """
    Estimate the number of LLM tokens in text.

    Uses a heuristic of ~4 characters per token for English text.
    For CJK text, uses ~1.5 characters per token.

    Args:
        text: Input text.
        chars_per_token: Characters per token ratio.

    Returns:
        Estimated token count.

    Example:
        >>> estimate_tokens("Hello world, this is a test.")
        8
    """
    if not text:
        return 0

    # Check for CJK content
    cjk_ratio = len(
        re.findall(
            r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0e00-\u0e7f]",
            text,
        )
    ) / max(len(text), 1)

    if cjk_ratio > 0.3:
        # CJK text: ~1.5 chars per token
        return max(1, int(len(text) / 1.5))

    return max(1, int(len(text) / chars_per_token))


def estimate_tokens_tiktoken(text: str, model: str = "gpt-4o") -> int:
    """
    Estimate tokens using tiktoken (if available).

    Falls back to heuristic if tiktoken is not installed.

    Args:
        text: Input text.
        model: Model name for encoding selection.

    Returns:
        Token count.
    """
    try:
        import tiktoken

        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except Exception:
        return estimate_tokens(text)


# ══════════════════════════════════════════════════════════════
# Truncation
# ══════════════════════════════════════════════════════════════


def truncate(
    text: str,
    max_length: int = 200,
    suffix: str = "...",
    at_word_boundary: bool = True,
    at_sentence_boundary: bool = False,
) -> str:
    """
    Truncate text to a maximum length.

    Args:
        text: Input text.
        max_length: Maximum length in characters.
        suffix: Suffix to append when truncated.
        at_word_boundary: Break at word boundary.
        at_sentence_boundary: Break at sentence boundary.

    Returns:
        Truncated text.

    Example:
        >>> truncate("Hello world, this is a long text", max_length=15)
        'Hello world,...'
    """
    if not text or len(text) <= max_length:
        return text

    truncated = text[:max_length]

    if at_sentence_boundary:
        # Find last sentence boundary
        last_period = max(
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if last_period > max_length * 0.5:
            return truncated[: last_period + 1] + suffix

    if at_word_boundary:
        # Find last space
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.5:
            truncated = truncated[:last_space]

    return truncated.rstrip() + suffix


def truncate_tokens(
    text: str,
    max_tokens: int = 1000,
    suffix: str = "\n\n[... truncated]",
) -> str:
    """
    Truncate text to approximately max_tokens tokens.

    Args:
        text: Input text.
        max_tokens: Maximum token count.
        suffix: Suffix to append.

    Returns:
        Truncated text.
    """
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text

    # Estimate character limit
    ratio = max_tokens / max(estimated, 1)
    char_limit = int(len(text) * ratio * 0.95)

    return truncate(text, max_length=char_limit, suffix=suffix)


# ══════════════════════════════════════════════════════════════
# Slug Generation
# ══════════════════════════════════════════════════════════════


def slugify(
    text: str,
    max_length: int = 80,
    separator: str = "-",
    lowercase: bool = True,
) -> str:
    """
    Generate a URL-friendly slug from text.

    Args:
        text: Input text.
        max_length: Maximum slug length.
        separator: Word separator.
        lowercase: Convert to lowercase.

    Returns:
        URL-safe slug string.

    Example:
        >>> slugify("Hello World! Python 3.12")
        'hello-world-python-312'
        >>> slugify("สวัสดี ชาวโลก")
        'สวัสดี-ชาวโลก'
    """
    if not text:
        return ""

    # Normalize unicode
    text = unicodedata.normalize("NFKC", text)

    if lowercase:
        text = text.lower()

    # Replace non-alphanumeric (keeping Unicode letters/numbers) with separator
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)

    # Replace whitespace and multiple separators
    text = re.sub(r"[\s_]+", separator, text)
    text = re.sub(rf"{re.escape(separator)}+", separator, text)

    # Strip separators from ends
    text = text.strip(separator)

    # Truncate
    if len(text) > max_length:
        text = text[:max_length].rstrip(separator)

    return text


# ══════════════════════════════════════════════════════════════
# Language Detection
# ══════════════════════════════════════════════════════════════


def detect_language(text: str, sample_size: int = 1000) -> str:
    """
    Detect the primary language of text using Unicode ranges.

    Supports: English, Thai, Chinese, Japanese, Korean, Arabic,
    Russian (Cyrillic), and common European languages.

    Args:
        text: Input text.
        sample_size: Number of characters to analyze.

    Returns:
        ISO 639-1 language code (e.g., 'en', 'th', 'ja').

    Example:
        >>> detect_language("Hello world")
        'en'
        >>> detect_language("สวัสดีครับ")
        'th'
        >>> detect_language("こんにちは")
        'ja'
    """
    sample = text[:sample_size]
    if not sample:
        return "en"

    total = len(sample)
    threshold = total * 0.1

    # Count character ranges
    thai = len(re.findall(r"[\u0e00-\u0e7f]", sample))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", sample))
    hiragana = len(re.findall(r"[\u3040-\u309f]", sample))
    katakana = len(re.findall(r"[\u30a0-\u30ff]", sample))
    hangul = len(re.findall(r"[\uac00-\ud7af\u1100-\u11ff]", sample))
    arabic = len(re.findall(r"[\u0600-\u06ff\u0750-\u077f]", sample))
    cyrillic = len(re.findall(r"[\u0400-\u04ff]", sample))
    latin = len(re.findall(r"[a-zA-Z]", sample))

    if thai > threshold:
        return "th"
    if hiragana + katakana > threshold:
        return "ja"
    if cjk > threshold and hiragana + katakana == 0:
        return "zh"
    if hangul > threshold:
        return "ko"
    if arabic > threshold:
        return "ar"
    if cyrillic > threshold:
        return "ru"

    # Latin-based: try to distinguish
    if latin > threshold:
        lower = sample.lower()
        if re.search(r"\b(der|die|das|und|ist|nicht|ein|eine)\b", lower):
            return "de"
        if re.search(r"\b(le|la|les|et|est|un|une|des|du)\b", lower):
            return "fr"
        if re.search(r"\b(el|los|las|y|es|un|una|del|en)\b", lower):
            return "es"
        if re.search(r"\b(o|os|as|e|é|um|uma|de|do|da)\b", lower):
            return "pt"

    return "en"


# ══════════════════════════════════════════════════════════════
# Text Similarity
# ══════════════════════════════════════════════════════════════


def text_similarity(text_a: str, text_b: str, method: str = "jaccard") -> float:
    """
    Compute similarity between two texts.

    Args:
        text_a: First text.
        text_b: Second text.
        method: Similarity method ('jaccard', 'cosine', 'overlap').

    Returns:
        Similarity score (0.0 to 1.0).

    Example:
        >>> text_similarity("hello world", "hello earth")
        0.333...
        >>> text_similarity("hello world", "hello world")
        1.0
    """
    if not text_a or not text_b:
        return 0.0

    if method == "jaccard":
        return _jaccard_similarity(text_a, text_b)
    elif method == "cosine":
        return _cosine_similarity(text_a, text_b)
    elif method == "overlap":
        return _overlap_coefficient(text_a, text_b)
    else:
        return _jaccard_similarity(text_a, text_b)


def _tokenize(text: str) -> set[str]:
    """Tokenize text into a set of lowercase words."""
    return set(re.findall(r"\b\w+\b", text.lower()))


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Jaccard similarity coefficient."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    return len(intersection) / max(len(union), 1)


def _cosine_similarity(text_a: str, text_b: str) -> float:
    """Cosine similarity using term frequency vectors."""
    tokens_a = re.findall(r"\b\w+\b", text_a.lower())
    tokens_b = re.findall(r"\b\w+\b", text_b.lower())

    if not tokens_a or not tokens_b:
        return 0.0

    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)

    # All terms
    all_terms = set(counter_a.keys()) | set(counter_b.keys())

    # Dot product
    dot = sum(counter_a.get(t, 0) * counter_b.get(t, 0) for t in all_terms)

    # Magnitudes
    mag_a = math.sqrt(sum(v**2 for v in counter_a.values()))
    mag_b = math.sqrt(sum(v**2 for v in counter_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def _overlap_coefficient(text_a: str, text_b: str) -> float:
    """Overlap coefficient (Szymkiewicz-Simpson)."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    min_size = min(len(tokens_a), len(tokens_b))

    return len(intersection) / max(min_size, 1)


# ══════════════════════════════════════════════════════════════
# Keyword Extraction
# ══════════════════════════════════════════════════════════════

# Common English stop words
STOP_WORDS: set[str] = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "we",
    "you",
    "he",
    "she",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "his",
    "our",
    "their",
    "not",
    "no",
    "do",
    "does",
    "did",
    "will",
    "would",
    "can",
    "could",
    "should",
    "may",
    "might",
    "has",
    "have",
    "had",
    "if",
    "then",
    "else",
    "when",
    "where",
    "how",
    "what",
    "which",
    "who",
    "whom",
    "why",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "than",
    "too",
    "very",
    "just",
    "about",
    "above",
    "after",
    "again",
    "also",
    "am",
    "as",
    "because",
    "before",
    "below",
    "between",
    "during",
    "into",
    "through",
    "under",
    "until",
    "up",
    "down",
    "out",
    "off",
    "over",
    "once",
    "here",
    "there",
}


def extract_keywords(
    text: str,
    top_n: int = 10,
    min_word_length: int = 3,
    remove_stop_words: bool = True,
) -> list[tuple[str, int]]:
    """
    Extract top keywords from text by frequency.

    Args:
        text: Input text.
        top_n: Number of keywords to return.
        min_word_length: Minimum word length.
        remove_stop_words: Whether to remove stop words.

    Returns:
        List of (keyword, count) tuples, sorted by count.

    Example:
        >>> extract_keywords("Python is great. Python is fast. Python is easy.")
        [('python', 3), ('great', 1), ('fast', 1), ('easy', 1)]
    """
    if not text:
        return []

    # Tokenize
    words = re.findall(r"\b\w+\b", text.lower())

    # Filter
    filtered: list[str] = []
    for word in words:
        if len(word) < min_word_length:
            continue
        if remove_stop_words and word in STOP_WORDS:
            continue
        filtered.append(word)

    # Count
    counter = Counter(filtered)

    return counter.most_common(top_n)


def extract_key_phrases(
    text: str,
    top_n: int = 10,
    min_length: int = 2,
    max_length: int = 5,
) -> list[tuple[str, int]]:
    """
    Extract key phrases (n-grams) from text.

    Args:
        text: Input text.
        top_n: Number of phrases to return.
        min_length: Minimum phrase length (in words).
        max_length: Maximum phrase length (in words).

    Returns:
        List of (phrase, count) tuples.
    """
    if not text:
        return []

    words = re.findall(r"\b\w+\b", text.lower())

    # Remove stop words for phrase boundaries
    phrases: list[str] = []
    current_phrase: list[str] = []

    for word in words:
        if word in STOP_WORDS or len(word) < 2:
            if len(current_phrase) >= min_length:
                phrases.append(" ".join(current_phrase))
            current_phrase = []
        else:
            current_phrase.append(word)
            if len(current_phrase) >= max_length:
                phrases.append(" ".join(current_phrase))
                current_phrase = []

    if len(current_phrase) >= min_length:
        phrases.append(" ".join(current_phrase))

    counter = Counter(phrases)
    return counter.most_common(top_n)


# ══════════════════════════════════════════════════════════════
# Text Statistics
# ══════════════════════════════════════════════════════════════


@dataclass
class TextStats:
    """
    Comprehensive text statistics.

    Attributes:
        char_count: Total characters.
        char_count_no_spaces: Characters excluding spaces.
        word_count: Total words.
        sentence_count: Total sentences.
        paragraph_count: Total paragraphs.
        avg_word_length: Average word length.
        avg_sentence_length: Average words per sentence.
        estimated_tokens: Estimated LLM token count.
        language: Detected language.
        unique_words: Number of unique words.
        lexical_diversity: Unique words / total words.
    """

    char_count: int = 0
    char_count_no_spaces: int = 0
    word_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0
    avg_word_length: float = 0.0
    avg_sentence_length: float = 0.0
    estimated_tokens: int = 0
    language: str = "en"
    unique_words: int = 0
    lexical_diversity: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_count": self.char_count,
            "char_count_no_spaces": self.char_count_no_spaces,
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
            "paragraph_count": self.paragraph_count,
            "avg_word_length": round(self.avg_word_length, 2),
            "avg_sentence_length": round(self.avg_sentence_length, 2),
            "estimated_tokens": self.estimated_tokens,
            "language": self.language,
            "unique_words": self.unique_words,
            "lexical_diversity": round(self.lexical_diversity, 3),
        }


def analyze_text(text: str) -> TextStats:
    """
    Compute comprehensive text statistics.

    Args:
        text: Input text.

    Returns:
        TextStats dataclass.

    Example:
        >>> stats = analyze_text("Hello world. This is a test.")
        >>> print(stats.word_count)
        6
        >>> print(stats.to_dict())
    """
    if not text:
        return TextStats()

    words = text.split()
    word_count = len(words)
    sentence_count = count_sentences(text)
    paragraph_count = count_paragraphs(text)

    # Average word length
    avg_word_length = sum(len(w) for w in words) / max(word_count, 1)

    # Average sentence length
    avg_sentence_length = word_count / max(sentence_count, 1)

    # Unique words
    unique = {w.lower().strip(".,!?;:") for w in words}
    unique_words = len(unique)

    # Lexical diversity
    lexical_diversity = unique_words / max(word_count, 1)

    return TextStats(
        char_count=len(text),
        char_count_no_spaces=count_characters(text, include_spaces=False),
        word_count=word_count,
        sentence_count=sentence_count,
        paragraph_count=paragraph_count,
        avg_word_length=avg_word_length,
        avg_sentence_length=avg_sentence_length,
        estimated_tokens=estimate_tokens(text),
        language=detect_language(text),
        unique_words=unique_words,
        lexical_diversity=lexical_diversity,
    )


# ══════════════════════════════════════════════════════════════
# Miscellaneous
# ══════════════════════════════════════════════════════════════


def dedent(text: str) -> str:
    """
    Remove common leading whitespace from all lines.

    Args:
        text: Input text.

    Returns:
        Dedented text.
    """
    import textwrap

    return textwrap.dedent(text)


def indent(text: str, prefix: str = "  ") -> str:
    """
    Add a prefix to the beginning of each line.

    Args:
        text: Input text.
        prefix: Prefix string.

    Returns:
        Indented text.
    """
    lines = text.split("\n")
    return "\n".join(prefix + line for line in lines)


def wrap_text(text: str, width: int = 80) -> str:
    """
    Wrap text to a maximum line width.

    Args:
        text: Input text.
        width: Maximum line width.

    Returns:
        Wrapped text.
    """
    import textwrap

    return textwrap.fill(text, width=width)


def is_mostly_empty(text: str, threshold: float = 0.9) -> bool:
    """
    Check if text is mostly whitespace/empty.

    Args:
        text: Input text.
        threshold: Ratio of whitespace to consider "mostly empty".

    Returns:
        True if text is mostly empty.
    """
    if not text:
        return True

    non_space = len(text.strip())
    total = len(text)

    if total == 0:
        return True

    return (non_space / total) < (1.0 - threshold)
