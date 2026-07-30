"""
AgentCrawl — Sentence Chunker (Extended)
============================================

Extended sentence-based chunking with multilingual sentence detection,
token-aware sizing, sentence boundary disambiguation, and
paragraph-aware grouping.

This module extends the base SentenceChunker from chunker.py with:

    - Multilingual sentence boundary detection (EN, TH, CJK, AR, RU)
    - Token-aware chunk sizing (tiktoken or heuristic)
    - Sentence boundary disambiguation (abbreviations, decimals, etc.)
    - Paragraph-aware grouping (don't split mid-paragraph)
    - Configurable sentence joiners
    - Minimum/maximum sentence count per chunk

Usage:
    from agentcrawl.content.sentence_chunker import (
        SentenceChunker,            # Re-exported from chunker
        AdvancedSentenceChunker,    # Multilingual, token-aware
        SentenceTokenizer,          # Sentence boundary detection
        detect_language,            # Language detection
    )

    # Standard sentence chunking
    chunker = SentenceChunker(max_sentences=5, max_chunk_size=1000)
    chunks = chunker.chunk(text)

    # Advanced multilingual chunking
    chunker = AdvancedSentenceChunker(
        max_tokens=500,
        overlap_sentences=1,
        language="auto",
    )
    chunks = chunker.chunk(thai_text)

    # Token-aware chunking
    chunker = AdvancedSentenceChunker(
        max_tokens=1000,
        token_counter="tiktoken",
        model="gpt-4o",
    )
    chunks = chunker.chunk(text)

    # Sentence tokenization only
    tokenizer = SentenceTokenizer(language="en")
    sentences = tokenizer.tokenize(text)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

# Re-export base classes
from agentcrawl.content.chunker import (
    Chunk,
    Chunker,
    ChunkResult,
    SentenceChunker,
    create_chunker,
    create_chunker_from_config,
)

logger = logging.getLogger("agentcrawl.content.sentence_chunker")


# ══════════════════════════════════════════════════════════════
# Language Patterns
# ══════════════════════════════════════════════════════════════


@dataclass
class LanguagePattern:
    """
    Sentence boundary patterns for a specific language.

    Attributes:
        code: ISO 639-1 language code.
        name: Language name.
        sentence_endings: Regex pattern for sentence-ending punctuation.
        boundary_pattern: Full regex for sentence boundaries.
        abbreviations: Common abbreviations that don't end sentences.
    """

    code: str
    name: str
    sentence_endings: str
    boundary_pattern: str
    abbreviations: list[str] = field(default_factory=list)


LANGUAGE_PATTERNS: dict[str, LanguagePattern] = {
    "en": LanguagePattern(
        code="en",
        name="English",
        sentence_endings=r"[.!?]+",
        boundary_pattern=r"(?<=[.!?])\s+(?=[A-Z\"'\(\[])",
        abbreviations=[
            "mr",
            "mrs",
            "ms",
            "dr",
            "prof",
            "sr",
            "jr",
            "st",
            "vs",
            "etc",
            "inc",
            "ltd",
            "co",
            "corp",
            "jan",
            "feb",
            "mar",
            "apr",
            "jun",
            "jul",
            "aug",
            "sep",
            "sept",
            "oct",
            "nov",
            "dec",
            "mon",
            "tue",
            "wed",
            "thu",
            "fri",
            "sat",
            "sun",
            "ave",
            "blvd",
            "dept",
            "est",
            "fig",
            "govt",
            "approx",
            "appt",
            "apt",
            "dept",
            "dpt",
            "etc",
            "min",
            "max",
            "misc",
            "no",
            "vol",
            "rev",
        ],
    ),
    "th": LanguagePattern(
        code="th",
        name="Thai",
        sentence_endings=r"[.!?…]+|(?<=\S)\s+(?=\S)",
        boundary_pattern=r"(?<=[.!?…])\s+|(?<=[\u0e01-\u0e5b])\s{2,}(?=[\u0e01-\u0e5b])",
        abbreviations=[],
    ),
    "ja": LanguagePattern(
        code="ja",
        name="Japanese",
        sentence_endings=r"[。!?.!?\n]+",
        boundary_pattern=r"(?<=[。!?.!?])\s*(?=[^\s])",
        abbreviations=[],
    ),
    "zh": LanguagePattern(
        code="zh",
        name="Chinese",
        sentence_endings=r"[。!?.!?\n]+",
        boundary_pattern=r"(?<=[。!?.!?])\s*(?=[^\s])",
        abbreviations=[],
    ),
    "ko": LanguagePattern(
        code="ko",
        name="Korean",
        sentence_endings=r"[.!?。!?\n]+",
        boundary_pattern=r"(?<=[.!?。!?])\s*(?=[^\s])",
        abbreviations=[],
    ),
    "ar": LanguagePattern(
        code="ar",
        name="Arabic",
        sentence_endings=r"[.!?؟…]+",
        boundary_pattern=r"(?<=[.!?؟…])\s+(?=[^\s])",
        abbreviations=[],
    ),
    "ru": LanguagePattern(
        code="ru",
        name="Russian",
        sentence_endings=r"[.!?…]+",
        boundary_pattern=r"(?<=[.!?…])\s+(?=[A-Z\u0410-\u042f\u0401\"'])",
        abbreviations=[
            "\u0433",
            "\u0433\u0433",
            "\u0442",
            "\u0442\u0442",
            "\u0441\u0442\u0440",
            "\u0440\u0443\u0431",
            "\u043a\u043e\u043f",
        ],
    ),
    "de": LanguagePattern(
        code="de",
        name="German",
        sentence_endings=r"[.!?…]+",
        boundary_pattern=r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ\"'])",
        abbreviations=["z", "b", "usw", "bzw", "d", "h", "u", "a", "ca", "Nr"],
    ),
    "fr": LanguagePattern(
        code="fr",
        name="French",
        sentence_endings=r"[.!?…]+",
        boundary_pattern=r"(?<=[.!?…])\s+(?=[A-ZÀÂÄÇÉÈÊËÎÏÔÙÛÜ\"'])",
        abbreviations=["m", "mme", "mlle", "dr", "prof", "st", "ste"],
    ),
    "es": LanguagePattern(
        code="es",
        name="Spanish",
        sentence_endings=r"[.!?…¡¿]+",
        boundary_pattern=r"(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÑÜ\"'¿¡])",
        abbreviations=["sr", "sra", "srta", "dr", "d", "ud", "uds"],
    ),
}

# Fallback: generic pattern
GENERIC_PATTERN = LanguagePattern(
    code="generic",
    name="Generic",
    sentence_endings=r"[.!?…]+",
    boundary_pattern=r"(?<=[.!?…])\s+(?=[^\s])",
    abbreviations=[],
)


# ══════════════════════════════════════════════════════════════
# Language Detection
# ══════════════════════════════════════════════════════════════


def detect_language(text: str, sample_size: int = 2000) -> str:
    """
    Detect the primary language of a text sample.

    Uses Unicode character range analysis for fast detection.

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

    # Count character ranges
    thai = len(re.findall(r"[\u0e00-\u0e7f]", sample))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", sample))
    hiragana = len(re.findall(r"[\u3040-\u309f]", sample))
    katakana = len(re.findall(r"[\u30a0-\u30ff]", sample))
    hangul = len(re.findall(r"[\uac00-\ud7af\u1100-\u11ff]", sample))
    arabic = len(re.findall(r"[\u0600-\u06ff\u0750-\u077f]", sample))
    cyrillic = len(re.findall(r"[\u0400-\u04ff]", sample))
    latin = len(re.findall(r"[a-zA-Z]", sample))

    # Thresholds (10% of sample)
    threshold = total * 0.1

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

    # Latin-based: try to distinguish by common words
    if latin > threshold:
        lower = sample.lower()
        # Simple heuristic for common European languages
        if re.search(r"\b(der|die|das|und|ist|nicht|ein|eine)\b", lower):
            return "de"
        if re.search(r"\b(le|la|les|et|est|un|une|des|du)\b", lower):
            return "fr"
        if re.search(r"\b(el|los|las|y|es|un|una|del|en)\b", lower):
            return "es"

    return "en"


# ══════════════════════════════════════════════════════════════
# Sentence Tokenizer
# ══════════════════════════════════════════════════════════════


class SentenceTokenizer:
    """
    Language-aware sentence boundary tokenizer.

    Splits text into sentences using language-specific patterns
    with abbreviation handling and boundary disambiguation.

    Args:
        language: Language code ('en', 'th', 'ja', etc.) or 'auto'.
        min_sentence_length: Minimum characters for a valid sentence.
        handle_abbreviations: Whether to handle abbreviations.
        split_on_newlines: Whether to treat newlines as boundaries.

    Example:
        >>> tokenizer = SentenceTokenizer(language="en")
        >>> sentences = tokenizer.tokenize("Hello world. How are you?")
        >>> print(sentences)
        ['Hello world.', 'How are you?']

        >>> tokenizer = SentenceTokenizer(language="auto")
        >>> sentences = tokenizer.tokenize(thai_text)
    """

    def __init__(
        self,
        language: str = "auto",
        min_sentence_length: int = 5,
        handle_abbreviations: bool = True,
        split_on_newlines: bool = True,
    ):
        self._language = language
        self._min_sentence_length = min_sentence_length
        self._handle_abbreviations = handle_abbreviations
        self._split_on_newlines = split_on_newlines

        # Resolve language pattern
        if language == "auto":
            self._lang_pattern: LanguagePattern | None = None  # Detect per call
        else:
            self._lang_pattern = LANGUAGE_PATTERNS.get(language, GENERIC_PATTERN)

        # Pre-compile abbreviation set
        self._abbreviations: set[str] = set()
        if self._lang_pattern and handle_abbreviations:
            self._abbreviations = {a.lower() for a in self._lang_pattern.abbreviations}

    def tokenize(self, text: str) -> list[str]:
        """
        Split text into sentences.

        Args:
            text: Input text.

        Returns:
            List of sentence strings.
        """
        if not text.strip():
            return []

        # Resolve language pattern
        pattern = self._lang_pattern
        if pattern is None:
            lang = detect_language(text)
            pattern = LANGUAGE_PATTERNS.get(lang, GENERIC_PATTERN)

        # Split using boundary pattern
        try:
            boundary_re = re.compile(pattern.boundary_pattern)
            raw_sentences = boundary_re.split(text)
        except re.error:
            # Fallback: split on sentence-ending punctuation
            raw_sentences = re.split(r"(?<=[.!?…])\s+", text)

        # Post-process
        sentences: list[str] = []
        for sent in raw_sentences:
            sent = sent.strip()
            if not sent:
                continue

            # Check abbreviation false positives
            if self._handle_abbreviations and self._is_abbreviation_end(sent) and sentences:
                sentences[-1] = sentences[-1] + " " + sent
                continue

            # Filter by minimum length
            if len(sent) >= self._min_sentence_length:
                sentences.append(sent)
            elif sentences:
                # Append short fragments to previous sentence
                sentences[-1] = sentences[-1] + " " + sent

        return sentences

    def tokenize_with_spans(self, text: str) -> list[tuple[str, int, int]]:
        """
        Split text into sentences with character offsets.

        Args:
            text: Input text.

        Returns:
            List of (sentence, start_offset, end_offset) tuples.
        """
        sentences = self.tokenize(text)
        spans: list[tuple[str, int, int]] = []
        pos = 0

        for sent in sentences:
            start = text.find(sent, pos)
            if start == -1:
                start = pos
            end = start + len(sent)
            spans.append((sent, start, end))
            pos = end

        return spans

    def count_sentences(self, text: str) -> int:
        """Count the number of sentences in text."""
        return len(self.tokenize(text))

    def _is_abbreviation_end(self, text: str) -> bool:
        """Check if text ends with an abbreviation."""
        if not self._abbreviations:
            return False

        # Get last word
        words = text.rstrip(".!?…").split()
        if not words:
            return False

        last_word = words[-1].lower().rstrip(".")
        return last_word in self._abbreviations

    @property
    def language(self) -> str:
        return self._language

    def __repr__(self) -> str:
        return f"SentenceTokenizer(language={self._language!r})"


# ══════════════════════════════════════════════════════════════
# Token Counter
# ══════════════════════════════════════════════════════════════


class TokenCounter:
    """
    Token counting with tiktoken or heuristic fallback.

    Args:
        method: Counting method ('tiktoken', 'heuristic').
        model: Model name for tiktoken encoding.
        chars_per_token: Characters per token for heuristic method.

    Example:
        >>> counter = TokenCounter(method="tiktoken", model="gpt-4o")
        >>> count = counter.count("Hello world")

        >>> counter = TokenCounter(method="heuristic")
        >>> count = counter.count("Hello world")
    """

    def __init__(
        self,
        method: str = "heuristic",
        model: str = "gpt-4o",
        chars_per_token: float = 4.0,
    ):
        self._method = method
        self._model = model
        self._chars_per_token = chars_per_token
        self._encoding: Any = None

        if method == "tiktoken":
            try:
                import tiktoken

                self._encoding = tiktoken.encoding_for_model(model)
            except Exception:
                try:
                    import tiktoken

                    self._encoding = tiktoken.get_encoding("cl100k_base")
                except ImportError:
                    logger.warning(
                        "tiktoken not available, falling back to heuristic. "
                        "Install with: pip install tiktoken"
                    )
                    self._method = "heuristic"

    def count(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Input text.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0

        if self._method == "tiktoken" and self._encoding:
            return len(self._encoding.encode(text))

        # Heuristic
        return max(1, int(len(text) / self._chars_per_token))

    def count_sentences(self, sentences: list[str]) -> list[int]:
        """Count tokens for each sentence."""
        return [self.count(s) for s in sentences]

    @property
    def method(self) -> str:
        return self._method

    def __repr__(self) -> str:
        return f"TokenCounter(method={self._method!r})"


# ══════════════════════════════════════════════════════════════
# Advanced Sentence Chunker
# ══════════════════════════════════════════════════════════════


class AdvancedSentenceChunker(Chunker):
    """
    Multilingual, token-aware sentence chunker.

    Groups sentences into chunks based on token count or sentence
    count, with language-aware boundary detection and optional
    paragraph preservation.

    Args:
        max_tokens: Maximum tokens per chunk (0 = use max_chunk_size chars).
        max_sentences: Maximum sentences per chunk (0 = unlimited).
        overlap_sentences: Number of sentences to overlap between chunks.
        language: Language code or 'auto' for detection.
        token_counter: Token counting method ('tiktoken', 'heuristic').
        model: Model name for tiktoken.
        respect_paragraphs: Don't split mid-paragraph.
        min_chunk_sentences: Minimum sentences per chunk.
        **kwargs: Passed to Chunker base class.

    Example:
        >>> chunker = AdvancedSentenceChunker(
        ...     max_tokens=500,
        ...     overlap_sentences=1,
        ...     language="auto",
        ... )
        >>> result = chunker.chunk(text)
        >>> for chunk in result.chunks:
        ...     print(f"{chunk.token_count} tokens, {chunk.word_count} words")
    """

    strategy_name = "advanced_sentence"

    def __init__(
        self,
        max_tokens: int = 0,
        max_sentences: int = 5,
        overlap_sentences: int = 1,
        language: str = "auto",
        counter_method: str = "heuristic",
        model: str = "gpt-4o",
        respect_paragraphs: bool = True,
        min_chunk_sentences: int = 1,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._max_tokens = max_tokens
        self._max_sentences = max_sentences
        self._overlap_sentences = overlap_sentences
        self._language = language
        self._respect_paragraphs = respect_paragraphs
        self._min_chunk_sentences = min_chunk_sentences

        self._tokenizer = SentenceTokenizer(
            language=language,
            handle_abbreviations=True,
        )
        self._token_counter = TokenCounter(
            method=counter_method,
            model=model,
        )

    # ──────────────────────────────────────────────────────────
    # Chunker Implementation
    # ──────────────────────────────────────────────────────────

    def _split(self, text: str) -> list[dict[str, Any]]:
        """Split text into sentence-based segments."""
        # Split into paragraphs first (if respecting paragraphs)
        if self._respect_paragraphs:
            paragraphs = re.split(r"\n{2,}", text)
            paragraphs = [p.strip() for p in paragraphs if p.strip()]
        else:
            paragraphs = [text]

        # Tokenize all paragraphs into sentences
        all_sentences: list[tuple[str, int, int]] = []  # (text, para_idx, sent_idx)
        para_offset = 0

        for para_idx, para in enumerate(paragraphs):
            sentences = self._tokenizer.tokenize(para)
            for sent_idx, sent in enumerate(sentences):
                start = text.find(sent, para_offset)
                if start == -1:
                    start = para_offset
                all_sentences.append((sent, para_idx, sent_idx))
                para_offset = start + len(sent)

        if not all_sentences:
            return [
                {
                    "text": text.strip(),
                    "start": 0,
                    "end": len(text),
                    "heading": "",
                    "heading_level": 0,
                }
            ]

        # Group sentences into chunks
        segments: list[dict[str, Any]] = []
        current_sentences: list[str] = []
        current_tokens = 0
        current_start = 0
        current_para = -1

        for i, (sent, para_idx, _sent_idx) in enumerate(all_sentences):
            sent_tokens = self._token_counter.count(sent)

            # Check if adding this sentence would exceed limits
            would_exceed = False

            if self._max_tokens > 0 and current_tokens + sent_tokens > self._max_tokens:
                would_exceed = True

            if self._max_sentences > 0 and len(current_sentences) >= self._max_sentences:
                would_exceed = True

            # Paragraph boundary
            if (
                self._respect_paragraphs
                and current_para >= 0
                and para_idx != current_para
                and current_sentences
            ):
                would_exceed = True

            if would_exceed and current_sentences:
                # Flush current chunk
                chunk_text = " ".join(current_sentences)
                segments.append(
                    {
                        "text": chunk_text,
                        "start": current_start,
                        "end": current_start + len(chunk_text),
                        "heading": "",
                        "heading_level": 0,
                    }
                )

                # Overlap: keep last N sentences
                if self._overlap_sentences > 0 and len(current_sentences) > self._overlap_sentences:
                    overlap_sents = current_sentences[-self._overlap_sentences :]
                    current_sentences = list(overlap_sents)
                    current_tokens = sum(self._token_counter.count(s) for s in current_sentences)
                else:
                    current_sentences = []
                    current_tokens = 0

                current_start = text.find(sent, current_start)
                if current_start == -1:
                    current_start = 0

            current_sentences.append(sent)
            current_tokens += sent_tokens
            current_para = para_idx

            if current_start == 0 and i == 0:
                current_start = text.find(sent)
                if current_start == -1:
                    current_start = 0

        # Flush remaining
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            segments.append(
                {
                    "text": chunk_text,
                    "start": current_start,
                    "end": current_start + len(chunk_text),
                    "heading": "",
                    "heading_level": 0,
                }
            )

        # Merge undersized chunks
        segments = self._merge_small_segments(segments)

        return segments

    def _merge_small_segments(
        self,
        segments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge segments that are too small."""
        if not segments:
            return segments

        merged: list[dict[str, Any]] = []
        buffer: dict[str, Any] | None = None

        for seg in segments:
            if buffer is None:
                buffer = dict(seg)
                continue

            combined_text = buffer["text"] + " " + seg["text"]
            combined_tokens = self._token_counter.count(combined_text)

            if (
                self._max_tokens > 0
                and combined_tokens <= self._max_tokens
                and len(buffer["text"]) < self._min_chunk_size
            ):
                buffer["text"] = combined_text
                buffer["end"] = seg["end"]
            else:
                merged.append(buffer)
                buffer = dict(seg)

        if buffer is not None:
            merged.append(buffer)

        return merged

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def language(self) -> str:
        return self._language

    @property
    def token_counter(self) -> TokenCounter:
        return self._token_counter

    @property
    def sentence_tokenizer(self) -> SentenceTokenizer:
        return self._tokenizer

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "max_tokens": self._max_tokens,
                "max_sentences": self._max_sentences,
                "overlap_sentences": self._overlap_sentences,
                "language": self._language,
                "token_counter": self._token_counter.method,
                "respect_paragraphs": self._respect_paragraphs,
                "min_chunk_sentences": self._min_chunk_sentences,
            }
        )
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdvancedSentenceChunker:
        return cls(
            max_tokens=data.get("max_tokens", 0),
            max_sentences=data.get("max_sentences", 5),
            overlap_sentences=data.get("overlap_sentences", 1),
            language=data.get("language", "auto"),
            token_counter=data.get("token_counter", "heuristic"),
            model=data.get("model", "gpt-4o"),
            respect_paragraphs=data.get("respect_paragraphs", True),
            min_chunk_sentences=data.get("min_chunk_sentences", 1),
            max_chunk_size=data.get("max_chunk_size", 1000),
            overlap=data.get("overlap", 200),
            min_chunk_size=data.get("min_chunk_size", 50),
        )

    def __repr__(self) -> str:
        return (
            f"AdvancedSentenceChunker(lang={self._language!r}, "
            f"max_tokens={self._max_tokens}, "
            f"max_sentences={self._max_sentences}, "
            f"overlap_sent={self._overlap_sentences})"
        )


# ══════════════════════════════════════════════════════════════
# Convenience Functions
# ══════════════════════════════════════════════════════════════


def chunk_by_sentences(
    text: str,
    max_sentences: int = 5,
    max_tokens: int = 0,
    overlap_sentences: int = 1,
    language: str = "auto",
    **kwargs: Any,
) -> ChunkResult:
    """
    Chunk text by sentences (convenience function).

    Args:
        text: Document text.
        max_sentences: Max sentences per chunk.
        max_tokens: Max tokens per chunk (0 = unlimited).
        overlap_sentences: Sentence overlap between chunks.
        language: Language code or 'auto'.
        **kwargs: Additional chunker arguments.

    Returns:
        ChunkResult.

    Example:
        >>> result = chunk_by_sentences(text, max_sentences=5)
        >>> result = chunk_by_sentences(thai_text, language="th", max_tokens=500)
    """
    chunker = AdvancedSentenceChunker(
        max_sentences=max_sentences,
        max_tokens=max_tokens,
        overlap_sentences=overlap_sentences,
        language=language,
        **kwargs,
    )
    return chunker.chunk(text)


def split_sentences(
    text: str,
    language: str = "auto",
) -> list[str]:
    """
    Split text into sentences (convenience function).

    Args:
        text: Input text.
        language: Language code or 'auto'.

    Returns:
        List of sentence strings.

    Example:
        >>> sentences = split_sentences("Hello world. How are you?")
        >>> print(sentences)
        ['Hello world.', 'How are you?']
    """
    tokenizer = SentenceTokenizer(language=language)
    return tokenizer.tokenize(text)


def count_tokens(
    text: str,
    method: str = "heuristic",
    model: str = "gpt-4o",
) -> int:
    """
    Count tokens in text (convenience function).

    Args:
        text: Input text.
        method: Counting method ('tiktoken', 'heuristic').
        model: Model name for tiktoken.

    Returns:
        Token count.
    """
    counter = TokenCounter(method=method, model=model)
    return counter.count(text)


# ══════════════════════════════════════════════════════════════
# Re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    "LANGUAGE_PATTERNS",
    # Extended
    "AdvancedSentenceChunker",
    # Base (re-exported)
    "Chunk",
    "ChunkResult",
    "Chunker",
    "LanguagePattern",
    "SentenceChunker",
    "SentenceTokenizer",
    "TokenCounter",
    "chunk_by_sentences",
    "count_tokens",
    "create_chunker",
    "create_chunker_from_config",
    "detect_language",
    "split_sentences",
]
