"""
AgentCrawl — BM25 Content Filter
===================================

Okapi BM25-based relevance filtering for extracted web content.
Scores each text block (paragraph, section, heading) against a
query and removes blocks below a relevance threshold.

Ideal for RAG pipelines where only query-relevant content should
be passed to the LLM, reducing noise and token cost.

Algorithm:
    BM25(D, Q) = Σ IDF(qi) · (f(qi, D) · (k1 + 1)) / (f(qi, D) + k1 · (1 - b + b · |D| / avgdl))

    Where:
        f(qi, D) = term frequency of qi in document D
        |D|      = document length (in words)
        avgdl    = average document length across all blocks
        k1       = term frequency saturation parameter (default: 1.5)
        b        = length normalization parameter (default: 0.75)
        IDF(qi)  = log((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)

Usage:
    from agentcrawl.content.bm25_filter import BM25ContentFilter

    # Simple usage
    filter = BM25ContentFilter(query="machine learning fundamentals")
    result = filter.apply(markdown_text)
    print(result.filtered_text)

    # With custom parameters
    filter = BM25ContentFilter(
        query="python asyncio tutorial",
        threshold=1.5,
        k1=1.2,
        b=0.8,
        min_block_words=10,
    )
    result = filter.apply(markdown_text)

    # With CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(
        content_filter="bm25",
        content_filter_query="neural networks",
        content_filter_threshold=1.0,
    )
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.content.bm25")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class TextBlock:
    """
    A block of text extracted from the document.

    Attributes:
        text: The raw text content.
        block_type: Type of block ('heading', 'paragraph', 'list_item',
                    'code', 'table', 'blockquote', 'other').
        level: Heading level (1-6) for headings, 0 for others.
        index: Original position index in the document.
        word_count: Number of words in the block.
        score: BM25 relevance score (computed after filtering).
        kept: Whether this block passed the filter.
    """
    text: str
    block_type: str = "paragraph"
    level: int = 0
    index: int = 0
    word_count: int = 0
    score: float = 0.0
    kept: bool = True

    def __post_init__(self) -> None:
        if self.word_count == 0:
            self.word_count = len(self.text.split())


@dataclass
class FilterResult:
    """
    Result of BM25 content filtering.

    Attributes:
        filtered_text: The filtered document text (kept blocks joined).
        original_text: The original unfiltered text.
        blocks: All text blocks with scores and kept/removed status.
        kept_blocks: Only the blocks that passed the filter.
        removed_blocks: Blocks that were removed.
        query: The query used for filtering.
        threshold: The threshold used.
        original_word_count: Word count before filtering.
        filtered_word_count: Word count after filtering.
        reduction_ratio: Ratio of content removed (0.0 to 1.0).
        avg_score: Average BM25 score of kept blocks.
        max_score: Maximum BM25 score.
        min_score: Minimum BM25 score of kept blocks.
    """
    filtered_text: str
    original_text: str
    blocks: list[TextBlock] = field(default_factory=list)
    kept_blocks: list[TextBlock] = field(default_factory=list)
    removed_blocks: list[TextBlock] = field(default_factory=list)
    query: str = ""
    threshold: float = 1.0
    original_word_count: int = 0
    filtered_word_count: int = 0
    reduction_ratio: float = 0.0
    avg_score: float = 0.0
    max_score: float = 0.0
    min_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "threshold": self.threshold,
            "original_word_count": self.original_word_count,
            "filtered_word_count": self.filtered_word_count,
            "reduction_ratio": round(self.reduction_ratio, 3),
            "total_blocks": len(self.blocks),
            "kept_blocks": len(self.kept_blocks),
            "removed_blocks": len(self.removed_blocks),
            "avg_score": round(self.avg_score, 3),
            "max_score": round(self.max_score, 3),
            "min_score": round(self.min_score, 3),
        }


# ══════════════════════════════════════════════════════════════
# Tokenizer
# ══════════════════════════════════════════════════════════════

class BM25Tokenizer:
    """
    Simple tokenizer for BM25 scoring.

    Handles:
        - Lowercase normalization
        - Punctuation removal
        - Unicode word boundaries
        - Optional stop word removal
        - Optional stemming (suffix stripping)
    """

    # Common English stop words
    STOP_WORDS: frozenset[str] = frozenset({
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "shall",
        "can", "need", "dare", "ought", "used", "it", "its", "this",
        "that", "these", "those", "i", "me", "my", "myself", "we",
        "our", "ours", "you", "your", "he", "him", "his", "she", "her",
        "they", "them", "their", "what", "which", "who", "whom",
        "when", "where", "why", "how", "not", "no", "nor", "as",
        "if", "then", "than", "too", "very", "just", "about", "above",
        "after", "again", "all", "also", "am", "any", "because",
        "before", "between", "both", "each", "few", "more", "most",
        "other", "some", "such", "only", "own", "same", "so", "into",
        "over", "under", "until", "up", "out", "off", "down", "here",
        "there", "once", "during", "while", "through",
    })

    def __init__(
        self,
        remove_stop_words: bool = True,
        stem: bool = False,
        min_token_length: int = 2,
    ):
        self._remove_stop_words = remove_stop_words
        self._stem = stem
        self._min_token_length = min_token_length
        self._word_pattern = re.compile(r"\b\w+\b", re.UNICODE)

    def tokenize(self, text: str) -> list[str]:
        """
        Tokenize text into a list of normalized terms.

        Args:
            text: Input text.

        Returns:
            List of lowercase tokens.
        """
        text = text.lower()
        tokens = self._word_pattern.findall(text)

        # Filter by length
        tokens = [t for t in tokens if len(t) >= self._min_token_length]

        # Remove stop words
        if self._remove_stop_words:
            tokens = [t for t in tokens if t not in self.STOP_WORDS]

        # Simple suffix-stripping stemmer
        if self._stem:
            tokens = [self._simple_stem(t) for t in tokens]

        return tokens

    @staticmethod
    def _simple_stem(word: str) -> str:
        """Very basic suffix-stripping stemmer."""
        if len(word) <= 3:
            return word

        suffixes = [
            "ational", "tional", "encies", "ancies", "izers",
            "ations", "iveness", "fulness", "ousness", "iveness",
            "ing", "edly", "edly", "tion", "sion", "ment",
            "ness", "able", "ible", "ful", "less", "ous",
            "ive", "ize", "ise", "ity", "ly", "er", "ed",
            "es", "s",
        ]

        for suffix in suffixes:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: -len(suffix)]

        return word


# ══════════════════════════════════════════════════════════════
# BM25 Scorer
# ══════════════════════════════════════════════════════════════

class BM25Scorer:
    """
    Okapi BM25 scoring engine.

    Computes relevance scores for a collection of text blocks
    against a query.

    Args:
        k1: Term frequency saturation parameter (1.2 - 2.0).
        b: Length normalization parameter (0.0 - 1.0).
        epsilon: Floor value for IDF to avoid negative scores.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ):
        self._k1 = k1
        self._b = b
        self._epsilon = epsilon

        # Corpus statistics (computed on fit)
        self._doc_count: int = 0
        self._avg_doc_len: float = 0.0
        self._doc_freqs: dict[str, int] = {}  # term → number of docs containing it
        self._doc_lens: list[int] = []
        self._doc_term_freqs: list[dict[str, int]] = []  # per-doc term frequencies
        self._idf: dict[str, float] = {}
        self._fitted = False

    def fit(self, documents: list[list[str]]) -> None:
        """
        Compute corpus statistics from tokenized documents.

        Args:
            documents: List of tokenized documents (each is a list of terms).
        """
        self._doc_count = len(documents)
        self._doc_term_freqs = []
        self._doc_lens = []
        self._doc_freqs = {}

        total_len = 0

        for doc_tokens in documents:
            # Term frequencies for this document
            tf: dict[str, int] = {}
            for token in doc_tokens:
                tf[token] = tf.get(token, 0) + 1
            self._doc_term_freqs.append(tf)

            # Document length
            doc_len = len(doc_tokens)
            self._doc_lens.append(doc_len)
            total_len += doc_len

            # Document frequency (count each term once per doc)
            for term in tf:
                self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

        self._avg_doc_len = total_len / max(self._doc_count, 1)

        # Compute IDF for all terms
        self._idf = {}
        for term, df in self._doc_freqs.items():
            idf = math.log(
                (self._doc_count - df + 0.5) / (df + 0.5) + 1.0
            )
            self._idf[term] = max(idf, self._epsilon)

        self._fitted = True

    def score(self, query_tokens: list[str], doc_index: int) -> float:
        """
        Compute BM25 score for a document against a query.

        Args:
            query_tokens: Tokenized query terms.
            doc_index: Index of the document in the fitted corpus.

        Returns:
            BM25 relevance score.
        """
        if not self._fitted or doc_index >= len(self._doc_term_freqs):
            return 0.0

        tf = self._doc_term_freqs[doc_index]
        doc_len = self._doc_lens[doc_index]
        score = 0.0

        for term in query_tokens:
            if term not in tf:
                continue

            term_freq = tf[term]
            idf = self._idf.get(term, self._epsilon)

            # BM25 term score
            numerator = term_freq * (self._k1 + 1)
            denominator = term_freq + self._k1 * (
                1 - self._b + self._b * doc_len / max(self._avg_doc_len, 1)
            )
            score += idf * (numerator / denominator)

        return score

    def score_all(self, query_tokens: list[str]) -> list[float]:
        """
        Score all documents against a query.

        Args:
            query_tokens: Tokenized query terms.

        Returns:
            List of BM25 scores, one per document.
        """
        return [
            self.score(query_tokens, i)
            for i in range(self._doc_count)
        ]

    @property
    def vocabulary_size(self) -> int:
        """Number of unique terms in the corpus."""
        return len(self._doc_freqs)

    @property
    def is_fitted(self) -> bool:
        """Whether the scorer has been fitted to a corpus."""
        return self._fitted


# ══════════════════════════════════════════════════════════════
# BM25 Content Filter
# ══════════════════════════════════════════════════════════════

class BM25ContentFilter:
    """
    BM25-based content relevance filter.

    Splits a document into text blocks, scores each block against
    a query using Okapi BM25, and removes blocks below a relevance
    threshold.

    Args:
        query: Search query for relevance scoring.
        threshold: Minimum BM25 score to keep a block.
        k1: BM25 term frequency saturation parameter.
        b: BM25 length normalization parameter.
        min_block_words: Minimum word count for a block to be scored.
        keep_headings: Always keep heading blocks regardless of score.
        keep_first_n: Always keep the first N blocks.
        remove_stop_words: Remove stop words during tokenization.
        stem: Apply simple stemming during tokenization.
        context_window: Number of adjacent blocks to keep around high-scoring blocks.

    Example:
        >>> filter = BM25ContentFilter(
        ...     query="python asyncio programming",
        ...     threshold=1.0,
        ... )
        >>> result = filter.apply(markdown_text)
        >>> print(result.filtered_text)
        >>> print(f"Kept {len(result.kept_blocks)}/{len(result.blocks)} blocks")
        >>> print(f"Reduction: {result.reduction_ratio:.1%}")
    """

    def __init__(
        self,
        query: str = "",
        threshold: float = 1.0,
        k1: float = 1.5,
        b: float = 0.75,
        min_block_words: int = 5,
        keep_headings: bool = True,
        keep_first_n: int = 1,
        remove_stop_words: bool = True,
        stem: bool = False,
        context_window: int = 0,
    ):
        self._query = query
        self._threshold = threshold
        self._min_block_words = min_block_words
        self._keep_headings = keep_headings
        self._keep_first_n = keep_first_n
        self._context_window = context_window

        self._tokenizer = BM25Tokenizer(
            remove_stop_words=remove_stop_words,
            stem=stem,
        )
        self._scorer = BM25Scorer(k1=k1, b=b)

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def query(self) -> str:
        """The current query."""
        return self._query

    @query.setter
    def query(self, value: str) -> None:
        self._query = value

    @property
    def threshold(self) -> float:
        """The current threshold."""
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = value

    # ──────────────────────────────────────────────────────────
    # Main API
    # ──────────────────────────────────────────────────────────

    def apply(self, text: str, query: str | None = None) -> FilterResult:
        """
        Filter content by BM25 relevance.

        Args:
            text: The full document text (typically Markdown).
            query: Override query (uses self.query if None).

        Returns:
            FilterResult with filtered text and block details.
        """
        effective_query = query or self._query

        # If no query, return everything
        if not effective_query.strip():
            blocks = self._split_into_blocks(text)
            return FilterResult(
                filtered_text=text,
                original_text=text,
                blocks=blocks,
                kept_blocks=blocks,
                removed_blocks=[],
                query=effective_query,
                threshold=self._threshold,
                original_word_count=len(text.split()),
                filtered_word_count=len(text.split()),
                reduction_ratio=0.0,
            )

        # Split into blocks
        blocks = self._split_into_blocks(text)

        if not blocks:
            return FilterResult(
                filtered_text="",
                original_text=text,
                blocks=[],
                kept_blocks=[],
                removed_blocks=[],
                query=effective_query,
                threshold=self._threshold,
                original_word_count=len(text.split()),
                filtered_word_count=0,
                reduction_ratio=1.0,
            )

        # Tokenize all blocks
        tokenized_blocks = [
            self._tokenizer.tokenize(block.text) for block in blocks
        ]

        # Fit BM25 scorer on all blocks
        self._scorer.fit(tokenized_blocks)

        # Tokenize query
        query_tokens = self._tokenizer.tokenize(effective_query)

        # Score all blocks
        scores = self._scorer.score_all(query_tokens)

        # Assign scores to blocks
        for block, score in zip(blocks, scores, strict=True):
            block.score = score

        # Determine which blocks to keep
        kept_indices = self._select_blocks(blocks)

        # Apply context window
        if self._context_window > 0:
            kept_indices = self._apply_context_window(kept_indices, len(blocks))

        # Mark blocks
        for i, block in enumerate(blocks):
            block.kept = i in kept_indices

        kept_blocks = [b for b in blocks if b.kept]
        removed_blocks = [b for b in blocks if not b.kept]

        # Build filtered text
        filtered_text = self._join_blocks(kept_blocks)

        # Compute stats
        original_wc = len(text.split())
        filtered_wc = len(filtered_text.split())
        kept_scores = [b.score for b in kept_blocks if b.score > 0]

        return FilterResult(
            filtered_text=filtered_text,
            original_text=text,
            blocks=blocks,
            kept_blocks=kept_blocks,
            removed_blocks=removed_blocks,
            query=effective_query,
            threshold=self._threshold,
            original_word_count=original_wc,
            filtered_word_count=filtered_wc,
            reduction_ratio=1.0 - (filtered_wc / max(original_wc, 1)),
            avg_score=sum(kept_scores) / max(len(kept_scores), 1),
            max_score=max(kept_scores) if kept_scores else 0.0,
            min_score=min(kept_scores) if kept_scores else 0.0,
        )

    def score_blocks(self, text: str, query: str | None = None) -> list[TextBlock]:
        """
        Score all blocks without filtering.

        Useful for inspecting relevance scores before choosing a threshold.

        Args:
            text: Document text.
            query: Override query.

        Returns:
            List of TextBlock with scores populated.
        """
        result = self.apply(text, query)
        return result.blocks

    def top_blocks(
        self,
        text: str,
        n: int = 5,
        query: str | None = None,
    ) -> list[TextBlock]:
        """
        Get the top-N most relevant blocks.

        Args:
            text: Document text.
            n: Number of top blocks to return.
            query: Override query.

        Returns:
            List of top-N TextBlock sorted by score descending.
        """
        blocks = self.score_blocks(text, query)
        scored = [b for b in blocks if b.score > 0]
        scored.sort(key=lambda b: b.score, reverse=True)
        return scored[:n]

    # ──────────────────────────────────────────────────────────
    # Block Splitting
    # ──────────────────────────────────────────────────────────

    def _split_into_blocks(self, text: str) -> list[TextBlock]:
        """
        Split text into semantic blocks.

        Splits on:
            - Markdown headings (# ## ### etc.)
            - Double newlines (paragraph breaks)
            - Preserves code blocks and tables as single blocks

        Args:
            text: Full document text.

        Returns:
            List of TextBlock instances.
        """
        blocks: list[TextBlock] = []
        lines = text.split("\n")
        current_block: list[str] = []
        current_type = "paragraph"
        current_level = 0
        in_code_block = False
        in_table = False
        index = 0

        def _flush() -> None:
            nonlocal current_block, current_type, current_level, index
            if current_block:
                block_text = "\n".join(current_block).strip()
                if block_text:
                    blocks.append(TextBlock(
                        text=block_text,
                        block_type=current_type,
                        level=current_level,
                        index=index,
                    ))
                    index += 1
                current_block = []
                current_type = "paragraph"
                current_level = 0

        for line in lines:
            stripped = line.strip()

            # Code block boundaries
            if stripped.startswith("```"):
                if in_code_block:
                    current_block.append(line)
                    in_code_block = False
                    current_type = "code"
                    _flush()
                    continue
                else:
                    _flush()
                    in_code_block = True
                    current_block.append(line)
                    continue

            if in_code_block:
                current_block.append(line)
                continue

            # Table detection
            if "|" in stripped and stripped.startswith("|"):
                if not in_table:
                    _flush()
                    in_table = True
                    current_type = "table"
                current_block.append(line)
                continue
            elif in_table:
                in_table = False
                current_type = "table"
                _flush()

            # Heading detection
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                _flush()
                level = len(heading_match.group(1))
                blocks.append(TextBlock(
                    text=stripped,
                    block_type="heading",
                    level=level,
                    index=index,
                ))
                index += 1
                continue

            # List item
            list_match = re.match(r"^(\s*[-*+]|\s*\d+\.)\s+", stripped)
            if list_match:
                if current_type != "list_item":
                    _flush()
                    current_type = "list_item"
                current_block.append(line)
                continue

            # Blockquote
            if stripped.startswith(">"):
                if current_type != "blockquote":
                    _flush()
                    current_type = "blockquote"
                current_block.append(line)
                continue

            # Empty line = paragraph break
            if not stripped:
                _flush()
                continue

            # Regular text
            if current_type not in ("paragraph",):
                _flush()
                current_type = "paragraph"
            current_block.append(line)

        # Flush remaining
        _flush()

        return blocks

    # ──────────────────────────────────────────────────────────
    # Block Selection
    # ──────────────────────────────────────────────────────────

    def _select_blocks(self, blocks: list[TextBlock]) -> set[int]:
        """
        Determine which block indices to keep.

        Rules:
            1. Always keep headings (if keep_headings=True)
            2. Always keep first N blocks
            3. Keep blocks with score >= threshold
            4. Keep blocks with word_count < min_block_words (too short to score reliably)

        Args:
            blocks: List of scored TextBlock instances.

        Returns:
            Set of block indices to keep.
        """
        kept: set[int] = set()

        for i, block in enumerate(blocks):
            # Always keep first N blocks
            if i < self._keep_first_n:
                kept.add(i)
                continue

            # Always keep headings
            if self._keep_headings and block.block_type == "heading":
                kept.add(i)
                continue

            # Keep very short blocks (can't score reliably)
            if block.word_count < self._min_block_words:
                kept.add(i)
                continue

            # Keep code blocks (usually important)
            if block.block_type == "code":
                kept.add(i)
                continue

            # Score-based filtering
            if block.score >= self._threshold:
                kept.add(i)

        return kept

    def _apply_context_window(
        self,
        kept_indices: set[int],
        total_blocks: int,
    ) -> set[int]:
        """
        Expand kept indices to include adjacent blocks for context.

        Args:
            kept_indices: Set of kept block indices.
            total_blocks: Total number of blocks.

        Returns:
            Expanded set of indices.
        """
        expanded = set(kept_indices)

        for idx in kept_indices:
            for offset in range(1, self._context_window + 1):
                before = idx - offset
                after = idx + offset
                if 0 <= before < total_blocks:
                    expanded.add(before)
                if 0 <= after < total_blocks:
                    expanded.add(after)

        return expanded

    # ──────────────────────────────────────────────────────────
    # Block Joining
    # ──────────────────────────────────────────────────────────

    def _join_blocks(self, blocks: list[TextBlock]) -> str:
        """
        Join kept blocks back into a document.

        Preserves heading structure and adds appropriate spacing.

        Args:
            blocks: List of kept TextBlock instances (in order).

        Returns:
            Joined document text.
        """
        if not blocks:
            return ""

        parts: list[str] = []

        for block in blocks:
            parts.append(block.text)

        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize filter configuration."""
        return {
            "type": "bm25",
            "query": self._query,
            "threshold": self._threshold,
            "k1": self._scorer._k1,
            "b": self._scorer._b,
            "min_block_words": self._min_block_words,
            "keep_headings": self._keep_headings,
            "keep_first_n": self._keep_first_n,
            "context_window": self._context_window,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BM25ContentFilter:
        """Create from a dictionary."""
        return cls(
            query=data.get("query", ""),
            threshold=data.get("threshold", 1.0),
            k1=data.get("k1", 1.5),
            b=data.get("b", 0.75),
            min_block_words=data.get("min_block_words", 5),
            keep_headings=data.get("keep_headings", True),
            keep_first_n=data.get("keep_first_n", 1),
            remove_stop_words=data.get("remove_stop_words", True),
            stem=data.get("stem", False),
            context_window=data.get("context_window", 0),
        )

    def __repr__(self) -> str:
        return (
            f"BM25ContentFilter(query={self._query!r}, "
            f"threshold={self._threshold}, "
            f"k1={self._scorer._k1}, b={self._scorer._b})"
        )
