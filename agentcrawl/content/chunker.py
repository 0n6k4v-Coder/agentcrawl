"""
AgentCrawl — Content Chunkers
================================

Text chunking strategies for RAG pipelines, vector stores, and
LLM context window management. Splits documents into semantically
meaningful chunks with configurable size, overlap, and metadata.

Strategies:
    FixedChunker    — Fixed character/token size with overlap
    SentenceChunker — Split at sentence boundaries
    RegexChunker    — Split by custom regex pattern
    TopicChunker    — Split at heading/topic changes (Markdown-aware)
    MarkdownChunker — Split by Markdown structure (headings, sections)

Usage:
    from agentcrawl.content.chunker import TopicChunker, FixedChunker

    # Topic-based chunking (best for structured documents)
    chunker = TopicChunker(max_chunk_size=1000, overlap=200)
    chunks = chunker.chunk(markdown_text)
    for chunk in chunks:
        print(f"[{chunk.index}] {chunk.heading} ({chunk.token_count} tokens)")
        print(chunk.text[:100])

    # Fixed-size chunking
    chunker = FixedChunker(max_chunk_size=500, overlap=50)
    chunks = chunker.chunk(text)

    # Sentence-based chunking
    chunker = SentenceChunker(max_sentences=5, overlap=1)
    chunks = chunker.chunk(text)

    # With CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(
        chunker="topic",
        chunk_max_size=1000,
        chunk_overlap=200,
    )
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.content.chunker")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class Chunk:
    """
    A single text chunk with metadata.

    Attributes:
        text: The chunk text content.
        index: Sequential index of this chunk in the document.
        heading: The nearest preceding heading (for context).
        heading_level: Heading level (1-6), 0 if no heading.
        start_char: Start character offset in the original document.
        end_char: End character offset in the original document.
        token_count: Estimated token count.
        word_count: Number of words.
        char_count: Number of characters.
        metadata: Arbitrary metadata (source URL, section path, etc.).
        prev_chunk_id: ID of the previous chunk (for linked retrieval).
        next_chunk_id: ID of the next chunk.
        chunk_id: Unique identifier for this chunk.
    """
    text: str
    index: int = 0
    heading: str = ""
    heading_level: int = 0
    start_char: int = 0
    end_char: int = 0
    token_count: int = 0
    word_count: int = 0
    char_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
    chunk_id: str = ""

    def __post_init__(self) -> None:
        if not self.chunk_id:
            self.chunk_id = f"chunk_{self.index:04d}"
        if self.char_count == 0:
            self.char_count = len(self.text)
        if self.word_count == 0:
            self.word_count = len(self.text.split())
        if self.token_count == 0:
            self.token_count = self._estimate_tokens(self.text)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count (~4 chars per token for English)."""
        return max(1, len(text) // 4)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "index": self.index,
            "text": self.text,
            "heading": self.heading,
            "heading_level": self.heading_level,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "token_count": self.token_count,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "metadata": self.metadata,
            "prev_chunk_id": self.prev_chunk_id,
            "next_chunk_id": self.next_chunk_id,
        }

    def to_context_text(self, include_heading: bool = True) -> str:
        """
        Get the chunk text with optional heading context prefix.

        Useful for embedding — the heading provides semantic context.

        Args:
            include_heading: Whether to prepend the heading.

        Returns:
            Text with optional heading prefix.
        """
        if include_heading and self.heading:
            prefix = "#" * max(self.heading_level, 1)
            return f"{prefix} {self.heading}\n\n{self.text}"
        return self.text

    def __repr__(self) -> str:
        return (
            f"Chunk(index={self.index}, heading={self.heading!r}, "
            f"tokens={self.token_count}, chars={self.char_count})"
        )


@dataclass
class ChunkResult:
    """
    Result of a chunking operation.

    Attributes:
        chunks: List of Chunk objects.
        original_text: The original unchunked text.
        total_chunks: Number of chunks produced.
        total_tokens: Total estimated tokens across all chunks.
        total_words: Total words across all chunks.
        avg_chunk_tokens: Average tokens per chunk.
        max_chunk_tokens: Largest chunk token count.
        min_chunk_tokens: Smallest chunk token count.
        strategy: Name of the chunking strategy used.
        metadata: Global metadata (source URL, etc.).
    """
    chunks: list[Chunk] = field(default_factory=list)
    original_text: str = ""
    total_chunks: int = 0
    total_tokens: int = 0
    total_words: int = 0
    avg_chunk_tokens: float = 0.0
    max_chunk_tokens: int = 0
    min_chunk_tokens: int = 0
    strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.chunks:
            self.total_chunks = len(self.chunks)
            token_counts = [c.token_count for c in self.chunks]
            self.total_tokens = sum(token_counts)
            self.total_words = sum(c.word_count for c in self.chunks)
            self.avg_chunk_tokens = self.total_tokens / max(self.total_chunks, 1)
            self.max_chunk_tokens = max(token_counts)
            self.min_chunk_tokens = min(token_counts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "total_chunks": self.total_chunks,
            "total_tokens": self.total_tokens,
            "total_words": self.total_words,
            "avg_chunk_tokens": round(self.avg_chunk_tokens, 1),
            "max_chunk_tokens": self.max_chunk_tokens,
            "min_chunk_tokens": self.min_chunk_tokens,
            "chunks": [c.to_dict() for c in self.chunks],
        }

    def get_texts(self) -> list[str]:
        """Get just the text content of all chunks."""
        return [c.text for c in self.chunks]

    def get_context_texts(self, include_heading: bool = True) -> list[str]:
        """Get chunk texts with heading context."""
        return [c.to_context_text(include_heading) for c in self.chunks]

    def __len__(self) -> int:
        return len(self.chunks)

    def __iter__(self):
        return iter(self.chunks)

    def __getitem__(self, index: int) -> Chunk:
        return self.chunks[index]


# ══════════════════════════════════════════════════════════════
# Abstract Base Chunker
# ══════════════════════════════════════════════════════════════

class Chunker(ABC):
    """
    Abstract base class for all chunking strategies.

    Subclasses must implement the ``_split`` method which returns
    a list of raw text segments. The base class handles metadata,
    token counting, overlap, and Chunk object construction.

    Args:
        max_chunk_size: Maximum chunk size in characters.
        overlap: Overlap between consecutive chunks in characters.
        min_chunk_size: Minimum chunk size (smaller chunks are merged).
        metadata: Global metadata to attach to all chunks.
    """

    strategy_name: str = "base"

    def __init__(
        self,
        max_chunk_size: int = 1000,
        overlap: int = 200,
        min_chunk_size: int = 50,
        metadata: dict[str, Any] | None = None,
    ):
        self._max_chunk_size = max_chunk_size
        self._overlap = min(overlap, max_chunk_size // 2)  # Cap overlap at 50%
        self._min_chunk_size = min_chunk_size
        self._metadata = metadata or {}

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def chunk(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> ChunkResult:
        """
        Split text into chunks.

        Args:
            text: The document text to chunk.
            metadata: Additional metadata for this specific call.

        Returns:
            ChunkResult with all chunks and statistics.
        """
        if not text.strip():
            return ChunkResult(
                chunks=[],
                original_text=text,
                strategy=self.strategy_name,
            )

        # Merge metadata
        effective_meta = {**self._metadata, **(metadata or {})}

        # Split into raw segments
        segments = self._split(text)

        # Apply size constraints and overlap
        raw_chunks = self._apply_size_constraints(segments, text)

        # Build Chunk objects
        chunks = self._build_chunks(raw_chunks, text, effective_meta)

        # Link chunks
        self._link_chunks(chunks)

        return ChunkResult(
            chunks=chunks,
            original_text=text,
            strategy=self.strategy_name,
            metadata=effective_meta,
        )

    def chunk_to_texts(
        self,
        text: str,
        include_heading: bool = False,
    ) -> list[str]:
        """
        Convenience method: chunk and return just the texts.

        Args:
            text: Document text.
            include_heading: Prepend heading context.

        Returns:
            List of chunk text strings.
        """
        result = self.chunk(text)
        if include_heading:
            return result.get_context_texts(include_heading=True)
        return result.get_texts()

    # ──────────────────────────────────────────────────────────
    # Abstract Method
    # ──────────────────────────────────────────────────────────

    @abstractmethod
    def _split(self, text: str) -> list[dict[str, Any]]:
        """
        Split text into raw segments.

        Each segment is a dict with:
            - text: str
            - start: int (char offset)
            - end: int (char offset)
            - heading: str (nearest heading, optional)
            - heading_level: int (optional)

        Args:
            text: Full document text.

        Returns:
            List of segment dictionaries.
        """
        ...

    # ──────────────────────────────────────────────────────────
    # Internal Processing
    # ──────────────────────────────────────────────────────────

    def _apply_size_constraints(
        self,
        segments: list[dict[str, Any]],
        full_text: str,
    ) -> list[dict[str, Any]]:
        """
        Apply max/min size constraints and overlap to segments.

        - Segments larger than max_chunk_size are split further.
        - Segments smaller than min_chunk_size are merged with neighbors.
        - Overlap is added between consecutive chunks.
        """
        if not segments:
            return []

        # Step 1: Split oversized segments
        split_segments: list[dict[str, Any]] = []
        for seg in segments:
            if len(seg["text"]) > self._max_chunk_size:
                sub_segs = self._split_oversized(seg)
                split_segments.extend(sub_segs)
            else:
                split_segments.append(seg)

        # Step 2: Merge undersized segments
        merged: list[dict[str, Any]] = []
        buffer: dict[str, Any] | None = None

        for seg in split_segments:
            if buffer is None:
                buffer = dict(seg)
                continue

            combined_len = len(buffer["text"]) + len(seg["text"]) + 2  # +2 for \n\n

            if combined_len <= self._max_chunk_size and len(buffer["text"]) < self._min_chunk_size:
                # Merge into buffer
                buffer["text"] = buffer["text"] + "\n\n" + seg["text"]
                buffer["end"] = seg["end"]
            else:
                merged.append(buffer)
                buffer = dict(seg)

        if buffer is not None:
            merged.append(buffer)

        # Step 3: Add overlap
        if self._overlap > 0 and len(merged) > 1:
            overlapped: list[dict[str, Any]] = [merged[0]]
            for i in range(1, len(merged)):
                prev_text = merged[i - 1]["text"]
                overlap_text = prev_text[-self._overlap:] if len(prev_text) > self._overlap else prev_text

                seg = dict(merged[i])
                seg["text"] = overlap_text + "\n" + seg["text"]
                seg["start"] = max(0, seg["start"] - len(overlap_text))
                overlapped.append(seg)
            merged = overlapped

        return merged

    def _split_oversized(self, segment: dict[str, Any]) -> list[dict[str, Any]]:
        """Split a segment that exceeds max_chunk_size."""
        text = segment["text"]
        heading = segment.get("heading", "")
        heading_level = segment.get("heading_level", 0)
        start = segment.get("start", 0)

        sub_segments: list[dict[str, Any]] = []
        pos = 0

        while pos < len(text):
            end = min(pos + self._max_chunk_size, len(text))

            # Try to break at a paragraph boundary
            if end < len(text):
                # Look for last double newline within the chunk
                break_point = text.rfind("\n\n", pos, end)
                if break_point > pos + self._min_chunk_size:
                    end = break_point
                else:
                    # Try single newline
                    break_point = text.rfind("\n", pos, end)
                    if break_point > pos + self._min_chunk_size:
                        end = break_point
                    else:
                        # Try space
                        break_point = text.rfind(" ", pos, end)
                        if break_point > pos + self._min_chunk_size:
                            end = break_point

            chunk_text = text[pos:end].strip()
            if chunk_text:
                sub_segments.append({
                    "text": chunk_text,
                    "start": start + pos,
                    "end": start + end,
                    "heading": heading,
                    "heading_level": heading_level,
                })

            # Move position with overlap
            pos = end - self._overlap if self._overlap > 0 else end
            if pos <= (end - self._max_chunk_size):
                pos = end  # Prevent infinite loop

        return sub_segments

    def _build_chunks(
        self,
        segments: list[dict[str, Any]],
        full_text: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Build Chunk objects from processed segments."""
        chunks: list[Chunk] = []

        for i, seg in enumerate(segments):
            chunk = Chunk(
                text=seg["text"],
                index=i,
                heading=seg.get("heading", ""),
                heading_level=seg.get("heading_level", 0),
                start_char=seg.get("start", 0),
                end_char=seg.get("end", 0),
                metadata=dict(metadata),
            )
            chunks.append(chunk)

        return chunks

    @staticmethod
    def _link_chunks(chunks: list[Chunk]) -> None:
        """Set prev/next chunk IDs for linked retrieval."""
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk.prev_chunk_id = chunks[i - 1].chunk_id
            if i < len(chunks) - 1:
                chunk.next_chunk_id = chunks[i + 1].chunk_id

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy_name,
            "max_chunk_size": self._max_chunk_size,
            "overlap": self._overlap,
            "min_chunk_size": self._min_chunk_size,
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(max_size={self._max_chunk_size}, "
            f"overlap={self._overlap})"
        )


# ══════════════════════════════════════════════════════════════
# Fixed Chunker
# ══════════════════════════════════════════════════════════════

class FixedChunker(Chunker):
    """
    Fixed-size chunker with character-based splitting.

    Splits text into chunks of approximately max_chunk_size characters,
    breaking at paragraph, sentence, or word boundaries when possible.

    Example:
        >>> chunker = FixedChunker(max_chunk_size=500, overlap=50)
        >>> result = chunker.chunk(long_text)
        >>> print(f"{result.total_chunks} chunks, avg {result.avg_chunk_tokens:.0f} tokens")
    """

    strategy_name = "fixed"

    def _split(self, text: str) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        paragraphs = re.split(r"\n{2,}", text)
        pos = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                pos += 2  # Account for \n\n
                continue

            start = text.find(para, pos)
            if start == -1:
                start = pos
            end = start + len(para)

            segments.append({
                "text": para,
                "start": start,
                "end": end,
                "heading": "",
                "heading_level": 0,
            })
            pos = end

        return segments


# ══════════════════════════════════════════════════════════════
# Sentence Chunker
# ══════════════════════════════════════════════════════════════

class SentenceChunker(Chunker):
    """
    Sentence-boundary chunker.

    Groups sentences into chunks up to max_chunk_size characters
    or max_sentences sentences, whichever comes first.

    Args:
        max_sentences: Maximum sentences per chunk.
        **kwargs: Passed to Chunker base class.

    Example:
        >>> chunker = SentenceChunker(max_sentences=5, overlap=1)
        >>> chunks = chunker.chunk(text)
    """

    strategy_name = "sentence"

    def __init__(
        self,
        max_sentences: int = 5,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._max_sentences = max_sentences
        # Sentence boundary pattern
        self._sentence_pattern = re.compile(
            r"(?<=[.!?])\s+(?=[A-Z\u0e01-\u0e5b])"  # English + Thai
        )

    def _split(self, text: str) -> list[dict[str, Any]]:
        sentences = self._sentence_pattern.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        segments: list[dict[str, Any]] = []
        current_sentences: list[str] = []
        current_start = 0
        pos = 0

        for sentence in sentences:
            start = text.find(sentence, pos)
            if start == -1:
                start = pos

            current_sentences.append(sentence)

            if len(current_sentences) >= self._max_sentences:
                chunk_text = " ".join(current_sentences)
                segments.append({
                    "text": chunk_text,
                    "start": current_start,
                    "end": start + len(sentence),
                    "heading": "",
                    "heading_level": 0,
                })
                current_sentences = []
                current_start = start + len(sentence)

            pos = start + len(sentence)

        # Remaining sentences
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            segments.append({
                "text": chunk_text,
                "start": current_start,
                "end": len(text),
                "heading": "",
                "heading_level": 0,
            })

        return segments


# ══════════════════════════════════════════════════════════════
# Regex Chunker
# ══════════════════════════════════════════════════════════════

class RegexChunker(Chunker):
    """
    Regex-pattern-based chunker.

    Splits text at positions matching a regex pattern.

    Args:
        pattern: Regex pattern to split on.
        keep_separator: Whether to keep the separator in the chunk.
        **kwargs: Passed to Chunker base class.

    Example:
        >>> # Split at section markers
        >>> chunker = RegexChunker(pattern=r"^---+$", flags=re.MULTILINE)
        >>> chunks = chunker.chunk(text)

        >>> # Split at custom delimiters
        >>> chunker = RegexChunker(pattern=r"\\n\\n###\\s")
        >>> chunks = chunker.chunk(text)
    """

    strategy_name = "regex"

    def __init__(
        self,
        pattern: str = r"\n{2,}",
        flags: int = re.MULTILINE,
        keep_separator: bool = False,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._pattern = re.compile(pattern, flags)
        self._keep_separator = keep_separator

    def _split(self, text: str) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []

        if self._keep_separator:
            parts = self._pattern.split(text)
        else:
            parts = self._pattern.split(text)

        pos = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue

            start = text.find(part, pos)
            if start == -1:
                start = pos
            end = start + len(part)

            segments.append({
                "text": part,
                "start": start,
                "end": end,
                "heading": "",
                "heading_level": 0,
            })
            pos = end

        return segments

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["pattern"] = self._pattern.pattern
        return d


# ══════════════════════════════════════════════════════════════
# Topic Chunker
# ══════════════════════════════════════════════════════════════

class TopicChunker(Chunker):
    """
    Topic/heading-based chunker for Markdown documents.

    Splits at heading boundaries and groups content under each
    heading into chunks. Preserves heading hierarchy as context
    metadata for each chunk.

    This is the recommended chunker for structured documents
    (documentation, articles, reports).

    Args:
        min_heading_level: Minimum heading level to split on (1 = h1 only).
        max_heading_level: Maximum heading level to split on (6 = h6).
        **kwargs: Passed to Chunker base class.

    Example:
        >>> chunker = TopicChunker(
        ...     max_chunk_size=1000,
        ...     overlap=200,
        ...     min_heading_level=1,
        ...     max_heading_level=3,
        ... )
        >>> result = chunker.chunk(markdown_text)
        >>> for chunk in result.chunks:
        ...     print(f"[{chunk.heading}] {chunk.token_count} tokens")
    """

    strategy_name = "topic"

    def __init__(
        self,
        min_heading_level: int = 1,
        max_heading_level: int = 4,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._min_heading_level = min_heading_level
        self._max_heading_level = max_heading_level
        self._heading_pattern = re.compile(
            r"^(#{1,6})\s+(.+)$",
            re.MULTILINE,
        )

    def _split(self, text: str) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []

        # Find all headings
        headings: list[tuple[int, int, int, str]] = []  # (start, end, level, title)
        for match in self._heading_pattern.finditer(text):
            level = len(match.group(1))
            title = match.group(2).strip()
            if self._min_heading_level <= level <= self._max_heading_level:
                headings.append((match.start(), match.end(), level, title))

        if not headings:
            # No headings — treat entire text as one segment
            return [{
                "text": text.strip(),
                "start": 0,
                "end": len(text),
                "heading": "",
                "heading_level": 0,
            }]

        # Build heading stack for hierarchy tracking
        heading_stack: list[tuple[int, str]] = []  # (level, title)

        # Content before first heading
        if headings[0][0] > 0:
            pre_text = text[:headings[0][0]].strip()
            if pre_text:
                segments.append({
                    "text": pre_text,
                    "start": 0,
                    "end": headings[0][0],
                    "heading": "",
                    "heading_level": 0,
                })

        # Process each heading section
        for i, (h_start, h_end, h_level, h_title) in enumerate(headings):
            # Update heading stack
            while heading_stack and heading_stack[-1][0] >= h_level:
                heading_stack.pop()
            heading_stack.append((h_level, h_title))

            # Section content: from end of heading to start of next heading
            section_start = h_end
            if i + 1 < len(headings):
                section_end = headings[i + 1][0]
            else:
                section_end = len(text)

            section_text = text[section_start:section_end].strip()

            # Build heading context path
            heading_path = " > ".join(title for _, title in heading_stack)

            # Include heading line in the segment
            full_text = text[h_start:section_end].strip()

            if full_text:
                segments.append({
                    "text": full_text,
                    "start": h_start,
                    "end": section_end,
                    "heading": heading_path,
                    "heading_level": h_level,
                })

        return segments

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["min_heading_level"] = self._min_heading_level
        d["max_heading_level"] = self._max_heading_level
        return d


# ══════════════════════════════════════════════════════════════
# Markdown Chunker
# ══════════════════════════════════════════════════════════════

class MarkdownChunker(Chunker):
    """
    Markdown-structure-aware chunker.

    Splits at headings, code blocks, tables, and list boundaries.
    Preserves Markdown formatting within chunks and tracks the
    section hierarchy.

    Similar to TopicChunker but also handles code blocks, tables,
    and lists as atomic units.

    Example:
        >>> chunker = MarkdownChunker(max_chunk_size=1500, overlap=100)
        >>> result = chunker.chunk(markdown_text)
    """

    strategy_name = "markdown"

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def _split(self, text: str) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        lines = text.split("\n")

        current_lines: list[str] = []
        current_heading = ""
        current_level = 0
        current_start = 0
        in_code_block = False
        in_table = False
        pos = 0

        def _flush() -> None:
            nonlocal current_lines, current_start
            if current_lines:
                block_text = "\n".join(current_lines).strip()
                if block_text:
                    segments.append({
                        "text": block_text,
                        "start": current_start,
                        "end": pos,
                        "heading": current_heading,
                        "heading_level": current_level,
                    })
                current_lines = []

        for line in lines:
            stripped = line.strip()

            # Code block boundaries
            if stripped.startswith("```"):
                if in_code_block:
                    current_lines.append(line)
                    in_code_block = False
                    _flush()
                    pos += len(line) + 1
                    continue
                else:
                    _flush()
                    in_code_block = True
                    current_start = pos
                    current_lines.append(line)
                    pos += len(line) + 1
                    continue

            if in_code_block:
                current_lines.append(line)
                pos += len(line) + 1
                continue

            # Table detection
            if "|" in stripped and stripped.startswith("|"):
                if not in_table:
                    _flush()
                    in_table = True
                    current_start = pos
                current_lines.append(line)
                pos += len(line) + 1
                continue
            elif in_table:
                in_table = False
                _flush()

            # Heading detection
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                _flush()
                level = len(heading_match.group(1))
                current_heading = heading_match.group(2).strip()
                current_level = level
                current_start = pos
                current_lines.append(line)
                pos += len(line) + 1
                continue

            # Empty line — potential paragraph break
            if not stripped:
                if current_lines and len("\n".join(current_lines)) > self._max_chunk_size:
                    _flush()
                    current_start = pos
                current_lines.append(line)
                pos += len(line) + 1
                continue

            # Regular content
            current_lines.append(line)
            pos += len(line) + 1

            # Check if current block is getting too large
            current_text = "\n".join(current_lines)
            if len(current_text) > self._max_chunk_size * 1.5:
                _flush()
                current_start = pos

        _flush()
        return segments


# ══════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════

def create_chunker(
    strategy: str = "topic",
    max_chunk_size: int = 1000,
    overlap: int = 200,
    **kwargs: Any,
) -> Chunker:
    """
    Factory function to create a chunker by strategy name.

    Args:
        strategy: Strategy name ('fixed', 'sentence', 'regex', 'topic', 'markdown').
        max_chunk_size: Maximum chunk size in characters.
        overlap: Overlap between chunks.
        **kwargs: Additional strategy-specific arguments.

    Returns:
        Chunker instance.

    Raises:
        ValueError: If strategy is unknown.

    Example:
        >>> chunker = create_chunker("topic", max_chunk_size=1000, overlap=200)
        >>> chunker = create_chunker("regex", pattern=r"\\n\\n---\\n\\n")
    """
    strategies: dict[str, type[Chunker]] = {
        "fixed": FixedChunker,
        "sentence": SentenceChunker,
        "regex": RegexChunker,
        "topic": TopicChunker,
        "markdown": MarkdownChunker,
    }

    strategy_lower = strategy.lower().strip()
    chunker_cls = strategies.get(strategy_lower)

    if chunker_cls is None:
        raise ValueError(
            f"Unknown chunking strategy: '{strategy}'. "
            f"Available: {', '.join(sorted(strategies.keys()))}"
        )

    return chunker_cls(
        max_chunk_size=max_chunk_size,
        overlap=overlap,
        **kwargs,
    )


def create_chunker_from_config(config: Any) -> Chunker | None:
    """
    Create a chunker from a CrawlerConfig instance.

    Args:
        config: CrawlerConfig with chunker settings.

    Returns:
        Chunker instance, or None if chunking is disabled.
    """
    from agentcrawl.config.crawler_config import ChunkerType

    chunker_type = config.chunker
    if isinstance(chunker_type, str):
        try:
            chunker_type = ChunkerType(chunker_type)
        except ValueError:
            return None

    if chunker_type == ChunkerType.NONE:
        return None

    kwargs: dict[str, Any] = {}

    if chunker_type == ChunkerType.REGEX and config.chunk_pattern:
        kwargs["pattern"] = config.chunk_pattern

    if chunker_type == ChunkerType.SENTENCE:
        kwargs["max_sentences"] = max(1, config.chunk_max_size // 200)

    return create_chunker(
        strategy=chunker_type.value,
        max_chunk_size=config.chunk_max_size,
        overlap=config.chunk_overlap,
        **kwargs,
    )