"""
AgentCrawl — Topic Chunker (Extended)
=========================================

Extended topic/heading-based chunking with heading hierarchy tracking,
section merging/splitting, topic similarity detection, and
table-of-contents generation.

This module extends the base TopicChunker from chunker.py with:

    - Heading hierarchy tracking (breadcrumb paths)
    - Section merging (combine small sections under token budget)
    - Section splitting (break large sections at sub-headings)
    - Topic similarity detection (TF-IDF cosine similarity)
    - Table of contents generation
    - Section depth control
    - Parent-child chunk relationships

Usage:
    from agentcrawl.content.topic_chunker import (
        TopicChunker,               # Re-exported from chunker
        AdvancedTopicChunker,       # Hierarchy-aware, merge/split
        HeadingHierarchy,           # Heading tree structure
        TopicSimilarityDetector,    # TF-IDF topic similarity
        generate_toc,               # Table of contents generator
    )

    # Standard topic chunking
    chunker = TopicChunker(max_chunk_size=1000, overlap=200)
    result = chunker.chunk(markdown_text)

    # Advanced with hierarchy
    chunker = AdvancedTopicChunker(
        max_chunk_size=1000,
        overlap=200,
        merge_small_sections=True,
        min_section_tokens=50,
        max_heading_level=3,
    )
    result = chunker.chunk(markdown_text)

    # With topic similarity
    chunker = AdvancedTopicChunker(
        max_chunk_size=1000,
        detect_similar_topics=True,
        similarity_threshold=0.7,
    )
    result = chunker.chunk(markdown_text)

    # Generate table of contents
    toc = generate_toc(markdown_text)
    print(toc)
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Re-export base classes
from agentcrawl.content.chunker import (
    Chunk,
    Chunker,
    ChunkResult,
    TopicChunker,
    create_chunker,
    create_chunker_from_config,
)

logger = logging.getLogger("agentcrawl.content.topic_chunker")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class HeadingNode:
    """
    A node in the heading hierarchy tree.

    Attributes:
        text: Heading text.
        level: Heading level (1-6).
        index: Position index in the document.
        start_char: Start character offset.
        end_char: End character offset (end of section content).
        children: Child heading nodes.
        parent: Parent heading node.
        content_preview: First 100 chars of section content.
        word_count: Word count of section content.
        breadcrumb: Full heading path (e.g., "Guide > Setup > Installation").
    """
    text: str
    level: int
    index: int = 0
    start_char: int = 0
    end_char: int = 0
    children: list[HeadingNode] = field(default_factory=list)
    parent: HeadingNode | None = None
    content_preview: str = ""
    word_count: int = 0
    breadcrumb: str = ""

    @property
    def depth(self) -> int:
        """Depth in the heading tree (root = 0)."""
        d = 0
        node = self.parent
        while node is not None:
            d += 1
            node = node.parent
        return d

    @property
    def is_leaf(self) -> bool:
        """Whether this node has no children."""
        return len(self.children) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "level": self.level,
            "index": self.index,
            "breadcrumb": self.breadcrumb,
            "word_count": self.word_count,
            "children_count": len(self.children),
            "is_leaf": self.is_leaf,
            "depth": self.depth,
        }

    def __repr__(self) -> str:
        return f"HeadingNode(h{self.level}: {self.text!r}, children={len(self.children)})"


@dataclass
class TopicSection:
    """
    A topic section extracted from the document.

    Attributes:
        heading: Section heading text.
        heading_level: Heading level.
        breadcrumb: Full heading path.
        content: Section text content.
        start_char: Start offset in document.
        end_char: End offset in document.
        word_count: Number of words.
        token_count: Estimated token count.
        sub_sections: Child sections.
        similarity_score: Topic similarity to adjacent sections.
    """
    heading: str = ""
    heading_level: int = 0
    breadcrumb: str = ""
    content: str = ""
    start_char: int = 0
    end_char: int = 0
    word_count: int = 0
    token_count: int = 0
    sub_sections: list[TopicSection] = field(default_factory=list)
    similarity_score: float = 0.0

    def __post_init__(self) -> None:
        if self.word_count == 0 and self.content:
            self.word_count = len(self.content.split())
        if self.token_count == 0 and self.content:
            self.token_count = max(1, len(self.content) // 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "heading": self.heading,
            "heading_level": self.heading_level,
            "breadcrumb": self.breadcrumb,
            "word_count": self.word_count,
            "token_count": self.token_count,
            "sub_sections": len(self.sub_sections),
            "similarity_score": round(self.similarity_score, 3),
        }


# ══════════════════════════════════════════════════════════════
# Heading Hierarchy
# ══════════════════════════════════════════════════════════════

class HeadingHierarchy:
    """
    Builds and manages a heading hierarchy tree from Markdown text.

    Parses all headings and constructs a tree structure representing
    the document's section organization.

    Example:
        >>> hierarchy = HeadingHierarchy(markdown_text)
        >>> print(hierarchy.root.children)
        [HeadingNode(h1: 'Guide'), HeadingNode(h1: 'API')]
        >>> print(hierarchy.breadcrumbs)
        ['Guide', 'Guide > Setup', 'Guide > Setup > Installation']
    """

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def __init__(self, text: str):
        self._text = text
        self._headings: list[HeadingNode] = []
        self._root = HeadingNode(text="__root__", level=0)
        self._parse()

    def _parse(self) -> None:
        """Parse headings and build the tree."""
        matches = list(self._HEADING_RE.finditer(self._text))

        if not matches:
            return

        # Create heading nodes
        for i, match in enumerate(matches):
            level = len(match.group(1))
            text = match.group(2).strip()
            start = match.start()

            # Determine section end
            if i + 1 < len(matches):
                end = matches[i + 1].start()
            else:
                end = len(self._text)

            # Extract content preview
            content = self._text[match.end():end].strip()
            preview = content[:100] if content else ""
            wc = len(content.split())

            node = HeadingNode(
                text=text,
                level=level,
                index=i,
                start_char=start,
                end_char=end,
                content_preview=preview,
                word_count=wc,
            )
            self._headings.append(node)

        # Build tree
        stack: list[HeadingNode] = [self._root]

        for node in self._headings:
            # Pop stack until we find a parent with lower level
            while len(stack) > 1 and stack[-1].level >= node.level:
                stack.pop()

            parent = stack[-1]
            node.parent = parent
            parent.children.append(node)
            stack.append(node)

        # Compute breadcrumbs
        self._compute_breadcrumbs()

    def _compute_breadcrumbs(self) -> None:
        """Compute breadcrumb paths for all nodes."""
        def _walk(node: HeadingNode, path: list[str]) -> None:
            if node.level > 0:
                current_path = path + [node.text]
                node.breadcrumb = " > ".join(current_path)
            else:
                current_path = path

            for child in node.children:
                _walk(child, current_path)

        _walk(self._root, [])

    @property
    def root(self) -> HeadingNode:
        """Root node of the heading tree."""
        return self._root

    @property
    def headings(self) -> list[HeadingNode]:
        """All heading nodes in document order."""
        return list(self._headings)

    @property
    def breadcrumbs(self) -> list[str]:
        """All breadcrumb paths."""
        return [h.breadcrumb for h in self._headings if h.breadcrumb]

    @property
    def max_depth(self) -> int:
        """Maximum heading depth."""
        if not self._headings:
            return 0
        return max(h.level for h in self._headings)

    @property
    def heading_count(self) -> int:
        """Total number of headings."""
        return len(self._headings)

    def get_sections(self, max_level: int = 6) -> list[TopicSection]:
        """
        Extract topic sections from the hierarchy.

        Args:
            max_level: Maximum heading level to include.

        Returns:
            List of TopicSection objects.
        """
        sections: list[TopicSection] = []

        for node in self._headings:
            if node.level > max_level:
                continue

            # Extract section content
            content = self._text[node.start_char:node.end_char].strip()

            section = TopicSection(
                heading=node.text,
                heading_level=node.level,
                breadcrumb=node.breadcrumb,
                content=content,
                start_char=node.start_char,
                end_char=node.end_char,
                word_count=node.word_count,
            )
            sections.append(section)

        return sections

    def to_dict(self) -> dict[str, Any]:
        """Serialize the hierarchy."""
        def _node_to_dict(node: HeadingNode) -> dict[str, Any]:
            return {
                **node.to_dict(),
                "children": [_node_to_dict(c) for c in node.children],
            }

        return {
            "heading_count": self.heading_count,
            "max_depth": self.max_depth,
            "tree": _node_to_dict(self._root),
        }

    def __repr__(self) -> str:
        return (
            f"HeadingHierarchy(headings={self.heading_count}, "
            f"max_depth={self.max_depth})"
        )


# ══════════════════════════════════════════════════════════════
# Topic Similarity Detector
# ══════════════════════════════════════════════════════════════

class TopicSimilarityDetector:
    """
    Detects topic similarity between text sections using
    TF-IDF cosine similarity.

    Useful for identifying redundant sections or grouping
    related content.

    Args:
        min_words: Minimum words for meaningful comparison.
        top_n_terms: Number of top TF-IDF terms to use.

    Example:
        >>> detector = TopicSimilarityDetector()
        >>> score = detector.similarity("Python is great", "Python is awesome")
        >>> print(f"Similarity: {score:.2f}")
    """

    def __init__(
        self,
        min_words: int = 10,
        top_n_terms: int = 50,
    ):
        self._min_words = min_words
        self._top_n_terms = top_n_terms
        self._stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at",
            "to", "for", "of", "with", "by", "from", "is", "are",
            "was", "were", "be", "been", "it", "its", "this", "that",
            "these", "those", "i", "we", "you", "he", "she", "they",
            "not", "no", "do", "does", "did", "will", "would", "can",
            "could", "should", "may", "might", "has", "have", "had",
        }

    def tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase terms."""
        words = re.findall(r"\b\w+\b", text.lower())
        return [w for w in words if w not in self._stop_words and len(w) > 1]

    def compute_tfidf(
        self,
        documents: list[str],
    ) -> list[dict[str, float]]:
        """
        Compute TF-IDF vectors for a list of documents.

        Args:
            documents: List of document texts.

        Returns:
            List of TF-IDF dictionaries (term → weight).
        """
        n_docs = len(documents)
        if n_docs == 0:
            return []

        # Tokenize all documents
        tokenized = [self.tokenize(doc) for doc in documents]

        # Document frequency
        df: Counter[str] = Counter()
        for tokens in tokenized:
            unique_terms = set(tokens)
            for term in unique_terms:
                df[term] += 1

        # Compute TF-IDF for each document
        tfidf_vectors: list[dict[str, float]] = []

        for tokens in tokenized:
            if not tokens:
                tfidf_vectors.append({})
                continue

            # Term frequency
            tf = Counter(tokens)
            total = len(tokens)

            # TF-IDF
            vector: dict[str, float] = {}
            for term, count in tf.most_common(self._top_n_terms):
                tf_val = count / total
                idf_val = math.log((n_docs + 1) / (df[term] + 1)) + 1
                vector[term] = tf_val * idf_val

            tfidf_vectors.append(vector)

        return tfidf_vectors

    def cosine_similarity(
        self,
        vec_a: dict[str, float],
        vec_b: dict[str, float],
    ) -> float:
        """
        Compute cosine similarity between two TF-IDF vectors.

        Args:
            vec_a: First TF-IDF vector.
            vec_b: Second TF-IDF vector.

        Returns:
            Cosine similarity (0.0 to 1.0).
        """
        if not vec_a or not vec_b:
            return 0.0

        # Dot product
        common_terms = set(vec_a.keys()) & set(vec_b.keys())
        dot = sum(vec_a[t] * vec_b[t] for t in common_terms)

        # Magnitudes
        mag_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
        mag_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot / (mag_a * mag_b)

    def similarity(self, text_a: str, text_b: str) -> float:
        """
        Compute topic similarity between two texts.

        Args:
            text_a: First text.
            text_b: Second text.

        Returns:
            Similarity score (0.0 to 1.0).
        """
        vectors = self.compute_tfidf([text_a, text_b])
        if len(vectors) < 2:
            return 0.0
        return self.cosine_similarity(vectors[0], vectors[1])

    def similarity_matrix(self, texts: list[str]) -> list[list[float]]:
        """
        Compute pairwise similarity matrix for multiple texts.

        Args:
            texts: List of text strings.

        Returns:
            2D list of similarity scores.
        """
        vectors = self.compute_tfidf(texts)
        n = len(texts)
        matrix = [[0.0] * n for _ in range(n)]

        for i in range(n):
            matrix[i][i] = 1.0
            for j in range(i + 1, n):
                sim = self.cosine_similarity(vectors[i], vectors[j])
                matrix[i][j] = sim
                matrix[j][i] = sim

        return matrix

    def find_similar_pairs(
        self,
        texts: list[str],
        threshold: float = 0.7,
    ) -> list[tuple[int, int, float]]:
        """
        Find pairs of texts with similarity above threshold.

        Args:
            texts: List of text strings.
            threshold: Minimum similarity score.

        Returns:
            List of (index_a, index_b, score) tuples.
        """
        matrix = self.similarity_matrix(texts)
        pairs: list[tuple[int, int, float]] = []

        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                if matrix[i][j] >= threshold:
                    pairs.append((i, j, matrix[i][j]))

        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs


# ══════════════════════════════════════════════════════════════
# Advanced Topic Chunker
# ══════════════════════════════════════════════════════════════

class AdvancedTopicChunker(Chunker):
    """
    Hierarchy-aware topic chunker with section merging/splitting.

    Extends the base TopicChunker with:
        - Heading hierarchy tracking (breadcrumb paths)
        - Section merging (combine small sections)
        - Section splitting (break large sections at sub-headings)
        - Topic similarity detection
        - Parent-child chunk relationships

    Args:
        min_heading_level: Minimum heading level to split on.
        max_heading_level: Maximum heading level to split on.
        merge_small_sections: Merge sections below min_section_tokens.
        min_section_tokens: Minimum tokens for a standalone section.
        split_large_sections: Split sections above max_section_tokens.
        max_section_tokens: Maximum tokens before splitting.
        detect_similar_topics: Enable topic similarity detection.
        similarity_threshold: Threshold for flagging similar topics.
        include_breadcrumb: Include breadcrumb in chunk metadata.
        **kwargs: Passed to Chunker base class.

    Example:
        >>> chunker = AdvancedTopicChunker(
        ...     max_chunk_size=1000,
        ...     merge_small_sections=True,
        ...     min_section_tokens=50,
        ...     detect_similar_topics=True,
        ... )
        >>> result = chunker.chunk(markdown_text)
        >>> for chunk in result.chunks:
        ...     print(f"[{chunk.heading}] {chunk.token_count} tokens")
    """

    strategy_name = "advanced_topic"

    def __init__(
        self,
        min_heading_level: int = 1,
        max_heading_level: int = 4,
        merge_small_sections: bool = True,
        min_section_tokens: int = 50,
        split_large_sections: bool = True,
        max_section_tokens: int = 2000,
        detect_similar_topics: bool = False,
        similarity_threshold: float = 0.7,
        include_breadcrumb: bool = True,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._min_heading_level = min_heading_level
        self._max_heading_level = max_heading_level
        self._merge_small_sections = merge_small_sections
        self._min_section_tokens = min_section_tokens
        self._split_large_sections = split_large_sections
        self._max_section_tokens = max_section_tokens
        self._detect_similar_topics = detect_similar_topics
        self._similarity_threshold = similarity_threshold
        self._include_breadcrumb = include_breadcrumb

        self._similarity_detector = (
            TopicSimilarityDetector() if detect_similar_topics else None
        )

    # ──────────────────────────────────────────────────────────
    # Chunker Implementation
    # ──────────────────────────────────────────────────────────

    def _split(self, text: str) -> list[dict[str, Any]]:
        """Split text into topic-based segments with hierarchy."""
        # Build heading hierarchy
        hierarchy = HeadingHierarchy(text)
        sections = hierarchy.get_sections(max_level=self._max_heading_level)

        if not sections:
            # No headings — treat as single segment
            return [{
                "text": text.strip(),
                "start": 0,
                "end": len(text),
                "heading": "",
                "heading_level": 0,
            }]

        # Convert sections to segments
        segments: list[dict[str, Any]] = []

        for section in sections:
            if section.heading_level < self._min_heading_level:
                continue

            # Check if section needs splitting
            if (
                self._split_large_sections
                and section.token_count > self._max_section_tokens
            ):
                sub_segments = self._split_section(section)
                segments.extend(sub_segments)
            else:
                segments.append({
                    "text": section.content,
                    "start": section.start_char,
                    "end": section.end_char,
                    "heading": section.breadcrumb if self._include_breadcrumb else section.heading,
                    "heading_level": section.heading_level,
                })

        # Merge small sections
        if self._merge_small_sections:
            segments = self._merge_small_segments(segments)

        # Detect similar topics
        if self._detect_similar_topics and self._similarity_detector:
            self._flag_similar_topics(segments)

        return segments

    def _split_section(self, section: TopicSection) -> list[dict[str, Any]]:
        """Split a large section at sub-heading boundaries."""
        content = section.content
        heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

        matches = list(heading_re.finditer(content))
        if len(matches) <= 1:
            # No sub-headings — split by paragraphs
            return self._split_by_paragraphs(section)

        segments: list[dict[str, Any]] = []

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            chunk_text = content[start:end].strip()

            if chunk_text:
                sub_heading = match.group(2).strip()
                breadcrumb = f"{section.breadcrumb} > {sub_heading}" if section.breadcrumb else sub_heading

                segments.append({
                    "text": chunk_text,
                    "start": section.start_char + start,
                    "end": section.start_char + end,
                    "heading": breadcrumb if self._include_breadcrumb else sub_heading,
                    "heading_level": len(match.group(1)),
                })

        return segments

    def _split_by_paragraphs(self, section: TopicSection) -> list[dict[str, Any]]:
        """Split a section by paragraphs when no sub-headings exist."""
        paragraphs = re.split(r"\n{2,}", section.content)
        segments: list[dict[str, Any]] = []
        current: list[str] = []
        current_tokens = 0
        pos = section.start_char

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_tokens = max(1, len(para) // 4)

            if current_tokens + para_tokens > self._max_section_tokens and current:
                chunk_text = "\n\n".join(current)
                segments.append({
                    "text": chunk_text,
                    "start": pos,
                    "end": pos + len(chunk_text),
                    "heading": section.breadcrumb if self._include_breadcrumb else section.heading,
                    "heading_level": section.heading_level,
                })
                current = []
                current_tokens = 0

            current.append(para)
            current_tokens += para_tokens

        if current:
            chunk_text = "\n\n".join(current)
            segments.append({
                "text": chunk_text,
                "start": pos,
                "end": pos + len(chunk_text),
                "heading": section.breadcrumb if self._include_breadcrumb else section.heading,
                "heading_level": section.heading_level,
            })

        return segments

    def _merge_small_segments(
        self,
        segments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge segments that are too small into adjacent sections."""
        if not segments:
            return segments

        merged: list[dict[str, Any]] = []
        buffer: dict[str, Any] | None = None

        for seg in segments:
            seg_tokens = max(1, len(seg["text"]) // 4)

            if buffer is None:
                buffer = dict(seg)
                continue

            buffer_tokens = max(1, len(buffer["text"]) // 4)

            # Merge if buffer is too small
            if buffer_tokens < self._min_section_tokens:
                combined = buffer["text"] + "\n\n" + seg["text"]
                combined_tokens = max(1, len(combined) // 4)

                if combined_tokens <= self._max_chunk_size // 4:
                    buffer["text"] = combined
                    buffer["end"] = seg["end"]
                    # Keep the more specific heading
                    if seg.get("heading_level", 0) > buffer.get("heading_level", 0):
                        buffer["heading"] = seg["heading"]
                        buffer["heading_level"] = seg["heading_level"]
                    continue

            merged.append(buffer)
            buffer = dict(seg)

        if buffer is not None:
            merged.append(buffer)

        return merged

    def _flag_similar_topics(self, segments: list[dict[str, Any]]) -> None:
        """Flag segments with similar topics."""
        if not self._similarity_detector or len(segments) < 2:
            return

        texts = [seg["text"] for seg in segments]
        pairs = self._similarity_detector.find_similar_pairs(
            texts, self._similarity_threshold
        )

        for i, j, score in pairs:
            segments[i]["similar_to"] = j
            segments[j]["similar_to"] = i
            segments[i]["similarity_score"] = score
            segments[j]["similarity_score"] = score
            logger.debug(
                "Similar topics detected: segment %d ↔ %d (score=%.2f)",
                i, j, score,
            )

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "min_heading_level": self._min_heading_level,
            "max_heading_level": self._max_heading_level,
            "merge_small_sections": self._merge_small_sections,
            "min_section_tokens": self._min_section_tokens,
            "split_large_sections": self._split_large_sections,
            "max_section_tokens": self._max_section_tokens,
            "detect_similar_topics": self._detect_similar_topics,
            "similarity_threshold": self._similarity_threshold,
            "include_breadcrumb": self._include_breadcrumb,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdvancedTopicChunker:
        return cls(
            min_heading_level=data.get("min_heading_level", 1),
            max_heading_level=data.get("max_heading_level", 4),
            merge_small_sections=data.get("merge_small_sections", True),
            min_section_tokens=data.get("min_section_tokens", 50),
            split_large_sections=data.get("split_large_sections", True),
            max_section_tokens=data.get("max_section_tokens", 2000),
            detect_similar_topics=data.get("detect_similar_topics", False),
            similarity_threshold=data.get("similarity_threshold", 0.7),
            include_breadcrumb=data.get("include_breadcrumb", True),
            max_chunk_size=data.get("max_chunk_size", 1000),
            overlap=data.get("overlap", 200),
            min_chunk_size=data.get("min_chunk_size", 50),
        )

    def __repr__(self) -> str:
        return (
            f"AdvancedTopicChunker(h{self._min_heading_level}-h{self._max_heading_level}, "
            f"merge={self._merge_small_sections}, "
            f"similarity={self._detect_similar_topics})"
        )


# ══════════════════════════════════════════════════════════════
# Table of Contents Generator
# ══════════════════════════════════════════════════════════════

def generate_toc(
    text: str,
    max_level: int = 3,
    style: str = "markdown",
    include_numbers: bool = False,
) -> str:
    """
    Generate a table of contents from Markdown text.

    Args:
        text: Markdown document text.
        max_level: Maximum heading level to include.
        style: Output style ('markdown', 'plain', 'html').
        include_numbers: Include section numbers (1, 1.1, 1.1.1).

    Returns:
        Table of contents string.

    Example:
        >>> toc = generate_toc(markdown_text, max_level=3)
        >>> print(toc)
        ## Table of Contents
        - [Introduction](#introduction)
        - [Setup](#setup)
          - [Installation](#installation)
          - [Configuration](#configuration)
    """
    hierarchy = HeadingHierarchy(text)
    headings = [
        h for h in hierarchy.headings
        if h.level <= max_level
    ]

    if not headings:
        return ""

    lines: list[str] = []

    if style == "markdown":
        lines.append("## Table of Contents\n")

    counters: dict[int, int] = {}

    for heading in headings:
        indent = "  " * (heading.level - 1)

        # Section numbering
        number = ""
        if include_numbers:
            counters[heading.level] = counters.get(heading.level, 0) + 1
            # Reset deeper counters
            for deeper in range(heading.level + 1, 7):
                counters[deeper] = 0
            # Build number string
            parts = []
            for lvl in range(1, heading.level + 1):
                parts.append(str(counters.get(lvl, 0)))
            number = ".".join(parts) + " "

        # Anchor
        anchor = re.sub(r"[^\w\s-]", "", heading.text.lower())
        anchor = re.sub(r"\s+", "-", anchor.strip())

        if style == "markdown":
            lines.append(f"{indent}- [{number}{heading.text}](#{anchor})")
        elif style == "html":
            lines.append(
                f'{indent}<li><a href="#{anchor}">{number}{heading.text}</a></li>'
            )
        else:  # plain
            lines.append(f"{indent}{number}{heading.text}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Convenience Functions
# ══════════════════════════════════════════════════════════════

def chunk_by_topics(
    text: str,
    max_chunk_size: int = 1000,
    overlap: int = 200,
    max_heading_level: int = 4,
    merge_small: bool = True,
    **kwargs: Any,
) -> ChunkResult:
    """
    Chunk text by topics/headings (convenience function).

    Args:
        text: Markdown document text.
        max_chunk_size: Maximum chunk size.
        overlap: Overlap between chunks.
        max_heading_level: Maximum heading level to split on.
        merge_small: Merge small sections.
        **kwargs: Additional chunker arguments.

    Returns:
        ChunkResult.

    Example:
        >>> result = chunk_by_topics(markdown_text, max_chunk_size=1000)
    """
    chunker = AdvancedTopicChunker(
        max_chunk_size=max_chunk_size,
        overlap=overlap,
        max_heading_level=max_heading_level,
        merge_small_sections=merge_small,
        **kwargs,
    )
    return chunker.chunk(text)


def extract_sections(
    text: str,
    max_level: int = 3,
) -> list[TopicSection]:
    """
    Extract topic sections from Markdown text.

    Args:
        text: Markdown document text.
        max_level: Maximum heading level.

    Returns:
        List of TopicSection objects.
    """
    hierarchy = HeadingHierarchy(text)
    return hierarchy.get_sections(max_level=max_level)


# ══════════════════════════════════════════════════════════════
# Re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    # Base (re-exported)
    "Chunk",
    "Chunker",
    "ChunkResult",
    "TopicChunker",
    "create_chunker",
    "create_chunker_from_config",
    # Extended
    "AdvancedTopicChunker",
    "HeadingHierarchy",
    "HeadingNode",
    "TopicSection",
    "TopicSimilarityDetector",
    "generate_toc",
    "chunk_by_topics",
    "extract_sections",
]
