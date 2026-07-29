"""
AgentCrawl — Regex Chunker (Extended)
=========================================

Extended regex-based chunking with multi-pattern support,
pre-built patterns for common document structures, look-ahead
splitting, and pattern validation.

This module extends the base RegexChunker from chunker.py with:

    - Multi-pattern splitting (split on any of several patterns)
    - Pre-built patterns for Markdown, HTML, code, and documents
    - Look-ahead / look-behind aware splitting
    - Pattern validation and testing
    - Section-aware splitting (preserve section headers)
    - Delimiter preservation options

Usage:
    from agentcrawl.content.regex_chunker import (
        RegexChunker,               # Re-exported from chunker
        AdvancedRegexChunker,       # Multi-pattern, section-aware
        PrebuiltPatterns,           # Common pattern presets
        validate_pattern,           # Pattern validation
    )

    # Standard regex chunking
    chunker = RegexChunker(pattern=r"\\n\\n---\\n\\n", max_chunk_size=1000)
    chunks = chunker.chunk(text)

    # Advanced multi-pattern chunking
    chunker = AdvancedRegexChunker(
        patterns=[r"^#{1,3}\\s", r"^---+$", r"^\\*\\*\\*+$"],
        max_chunk_size=1000,
        overlap=100,
        keep_delimiter=True,
    )
    chunks = chunker.chunk(markdown_text)

    # Pre-built patterns
    chunker = AdvancedRegexChunker.from_preset("markdown_sections")
    chunker = AdvancedRegexChunker.from_preset("code_functions")
    chunker = AdvancedRegexChunker.from_preset("html_sections")

    # Validate a pattern before use
    is_valid, error = validate_pattern(r"^#{1,3}\\s")
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Re-export base classes
from agentcrawl.content.chunker import (
    Chunk,
    Chunker,
    ChunkResult,
    RegexChunker,
    create_chunker,
    create_chunker_from_config,
)

logger = logging.getLogger("agentcrawl.content.regex_chunker")


# ══════════════════════════════════════════════════════════════
# Pre-built Patterns
# ══════════════════════════════════════════════════════════════

class PrebuiltPatterns:
    """
    Pre-built regex patterns for common document structures.

    Each pattern is designed to split documents at natural
    structural boundaries.

    Available presets:
        markdown_sections   — Split at Markdown headings (h1-h3)
        markdown_all        — Split at any Markdown heading (h1-h6)
        markdown_paragraphs — Split at paragraph breaks
        markdown_code       — Split at code block boundaries
        html_sections       — Split at HTML section/article/div tags
        html_paragraphs     — Split at <p> tag boundaries
        code_functions      — Split at function/method definitions
        code_classes        — Split at class definitions
        text_paragraphs     — Split at double newlines
        text_sentences      — Split at sentence boundaries
        text_pages          — Split at page breaks / form feeds
        csv_rows            — Split at CSV row boundaries
        json_objects        — Split at top-level JSON object boundaries
        log_entries         — Split at log entry timestamps
        faq                 — Split at Q&A boundaries
    """

    MARKDOWN_SECTIONS: str = r"(?=^#{1,3}\s)"
    MARKDOWN_ALL_HEADINGS: str = r"(?=^#{1,6}\s)"
    MARKDOWN_PARAGRAPHS: str = r"\n{2,}"
    MARKDOWN_CODE_BLOCKS: str = r"(?=^```)"
    MARKDOWN_HRULES: str = r"^[-*_]{3,}\s*$"

    HTML_SECTIONS: str = r"(?=</?(?:section|article|div|main)\b)"
    HTML_PARAGRAPHS: str = r"(?=</?p\b)"
    HTML_HEADINGS: str = r"(?=</?h[1-6]\b)"

    CODE_FUNCTIONS_PYTHON: str = r"(?=^(?:def|async def|class)\s)"
    CODE_FUNCTIONS_JS: str = r"(?=^(?:function|const|let|var|class|export)\s)"
    CODE_FUNCTIONS_GENERIC: str = r"(?=^(?:def|function|func|fn|sub|procedure|class|struct|impl)\s)"

    TEXT_PARAGRAPHS: str = r"\n{2,}"
    TEXT_SENTENCES: str = r"(?<=[.!?])\s+(?=[A-Z\u0e01-\u0e5b])"
    TEXT_PAGES: str = r"\f|\n{3,}|^---+\s*$"

    CSV_ROWS: str = r"\n(?=[^,]+,)"
    JSON_OBJECTS: str = r"(?<=\})\s*(?=\{)"

    LOG_ENTRIES: str = r"(?=^\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2})"
    LOG_ENTRIES_SYSLOG: str = r"(?=^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"

    FAQ: str = r"(?=^(?:Q:|Q\.|Question:|\*\*Q)|^#{1,3}\s*(?:Q:|Question))"

    # Preset registry
    _PRESETS: dict[str, dict[str, Any]] = {
        "markdown_sections": {
            "patterns": [MARKDOWN_SECTIONS],
            "description": "Split at Markdown headings (h1-h3)",
            "flags": re.MULTILINE,
        },
        "markdown_all": {
            "patterns": [MARKDOWN_ALL_HEADINGS],
            "description": "Split at any Markdown heading (h1-h6)",
            "flags": re.MULTILINE,
        },
        "markdown_paragraphs": {
            "patterns": [MARKDOWN_PARAGRAPHS],
            "description": "Split at paragraph breaks",
            "flags": 0,
        },
        "markdown_code": {
            "patterns": [MARKDOWN_CODE_BLOCKS],
            "description": "Split at code block boundaries",
            "flags": re.MULTILINE,
        },
        "html_sections": {
            "patterns": [HTML_SECTIONS],
            "description": "Split at HTML section/article/div tags",
            "flags": re.IGNORECASE,
        },
        "html_paragraphs": {
            "patterns": [HTML_PARAGRAPHS],
            "description": "Split at <p> tag boundaries",
            "flags": re.IGNORECASE,
        },
        "code_functions": {
            "patterns": [CODE_FUNCTIONS_GENERIC],
            "description": "Split at function/method/class definitions",
            "flags": re.MULTILINE,
        },
        "code_functions_python": {
            "patterns": [CODE_FUNCTIONS_PYTHON],
            "description": "Split at Python def/class definitions",
            "flags": re.MULTILINE,
        },
        "code_functions_js": {
            "patterns": [CODE_FUNCTIONS_JS],
            "description": "Split at JavaScript function/class definitions",
            "flags": re.MULTILINE,
        },
        "text_paragraphs": {
            "patterns": [TEXT_PARAGRAPHS],
            "description": "Split at double newlines",
            "flags": 0,
        },
        "text_sentences": {
            "patterns": [TEXT_SENTENCES],
            "description": "Split at sentence boundaries",
            "flags": 0,
        },
        "text_pages": {
            "patterns": [TEXT_PAGES],
            "description": "Split at page breaks",
            "flags": re.MULTILINE,
        },
        "csv_rows": {
            "patterns": [CSV_ROWS],
            "description": "Split at CSV row boundaries",
            "flags": 0,
        },
        "json_objects": {
            "patterns": [JSON_OBJECTS],
            "description": "Split at top-level JSON objects",
            "flags": 0,
        },
        "log_entries": {
            "patterns": [LOG_ENTRIES, LOG_ENTRIES_SYSLOG],
            "description": "Split at log entry timestamps",
            "flags": re.MULTILINE,
        },
        "faq": {
            "patterns": [FAQ],
            "description": "Split at Q&A boundaries",
            "flags": re.MULTILINE | re.IGNORECASE,
        },
    }

    @classmethod
    def get_preset(cls, name: str) -> dict[str, Any]:
        """
        Get a preset configuration by name.

        Args:
            name: Preset name.

        Returns:
            Preset configuration dict.

        Raises:
            ValueError: If preset name is unknown.
        """
        preset = cls._PRESETS.get(name.lower().strip())
        if preset is None:
            available = ", ".join(sorted(cls._PRESETS.keys()))
            raise ValueError(
                f"Unknown pattern preset: '{name}'. Available: {available}"
            )
        return dict(preset)

    @classmethod
    def list_presets(cls) -> list[dict[str, str]]:
        """List all available presets with descriptions."""
        return [
            {"name": name, "description": cfg["description"]}
            for name, cfg in sorted(cls._PRESETS.items())
        ]

    @classmethod
    def has_preset(cls, name: str) -> bool:
        """Check if a preset exists."""
        return name.lower().strip() in cls._PRESETS


# ══════════════════════════════════════════════════════════════
# Pattern Validation
# ══════════════════════════════════════════════════════════════

def validate_pattern(pattern: str, flags: int = 0) -> tuple[bool, str | None]:
    """
    Validate a regex pattern.

    Args:
        pattern: Regex pattern string.
        flags: Regex flags.

    Returns:
        Tuple of (is_valid, error_message).
        error_message is None if valid.

    Example:
        >>> valid, error = validate_pattern(r"^#{1,3}\\s")
        >>> print(valid)  # True

        >>> valid, error = validate_pattern(r"[invalid")
        >>> print(valid, error)  # False, "unterminated character set..."
    """
    try:
        re.compile(pattern, flags)
        return True, None
    except re.error as e:
        return False, str(e)


def test_pattern(
    pattern: str,
    text: str,
    flags: int = re.MULTILINE,
    max_matches: int = 20,
) -> list[dict[str, Any]]:
    """
    Test a regex pattern against sample text.

    Args:
        pattern: Regex pattern string.
        text: Sample text to test against.
        flags: Regex flags.
        max_matches: Maximum matches to return.

    Returns:
        List of match info dicts (position, matched text, context).

    Example:
        >>> matches = test_pattern(r"^#{1,3}\\s", markdown_text)
        >>> for m in matches:
        ...     print(f"Position {m['start']}: {m['context'][:50]}")
    """
    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return [{"error": str(e)}]

    matches: list[dict[str, Any]] = []

    for i, match in enumerate(compiled.finditer(text)):
        if i >= max_matches:
            break

        start = match.start()
        end = match.end()

        # Context: 30 chars before and after
        ctx_start = max(0, start - 30)
        ctx_end = min(len(text), end + 30)
        context = text[ctx_start:ctx_end].replace("\n", "\\n")

        matches.append({
            "index": i,
            "start": start,
            "end": end,
            "matched": match.group()[:100],
            "context": context,
        })

    return matches


# ══════════════════════════════════════════════════════════════
# Advanced Regex Chunker
# ══════════════════════════════════════════════════════════════

class AdvancedRegexChunker(Chunker):
    """
    Multi-pattern regex chunker with section awareness.

    Extends the base RegexChunker with:
        - Multiple split patterns (split on ANY match)
        - Look-ahead aware splitting (don't consume the delimiter)
        - Delimiter preservation (keep delimiter at start/end of chunk)
        - Section header tracking (nearest heading per chunk)
        - Pre-built pattern presets

    Args:
        patterns: List of regex patterns to split on.
        flags: Regex flags applied to all patterns.
        keep_delimiter: Keep the delimiter text in the chunk.
        delimiter_position: Where to keep delimiter ('start', 'end', 'discard').
        track_headings: Track nearest heading for each chunk.
        heading_pattern: Pattern to detect headings (for tracking).
        **kwargs: Passed to Chunker base class.

    Example:
        >>> chunker = AdvancedRegexChunker(
        ...     patterns=[r"^#{1,3}\\s", r"^---+$"],
        ...     max_chunk_size=1000,
        ...     overlap=100,
        ...     keep_delimiter=True,
        ... )
        >>> result = chunker.chunk(markdown_text)
        >>> for chunk in result.chunks:
        ...     print(f"[{chunk.heading}] {chunk.token_count} tokens")
    """

    strategy_name = "advanced_regex"

    def __init__(
        self,
        patterns: list[str] | str | None = None,
        flags: int = re.MULTILINE,
        keep_delimiter: bool = False,
        delimiter_position: str = "start",
        track_headings: bool = True,
        heading_pattern: str = r"^(#{1,6})\s+(.+)$",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)

        # Normalize patterns
        if patterns is None:
            patterns = [r"\n{2,}"]
        elif isinstance(patterns, str):
            patterns = [patterns]

        self._pattern_strings = patterns
        self._flags = flags
        self._keep_delimiter = keep_delimiter
        self._delimiter_position = delimiter_position
        self._track_headings = track_headings

        # Compile patterns
        self._compiled_patterns: list[re.Pattern[str]] = []
        for p in patterns:
            try:
                self._compiled_patterns.append(re.compile(p, flags))
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{p}': {e}")

        # Heading pattern
        try:
            self._heading_re = re.compile(heading_pattern, re.MULTILINE)
        except re.error:
            self._heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

        # Combined pattern for splitting
        self._combined_pattern = self._build_combined_pattern()

    def _build_combined_pattern(self) -> re.Pattern[str]:
        """Build a combined pattern from all split patterns."""
        if len(self._compiled_patterns) == 1:
            return self._compiled_patterns[0]

        # Combine with alternation
        combined = "|".join(
            f"(?:{p.pattern})" for p in self._compiled_patterns
        )
        return re.compile(combined, self._flags)

    # ──────────────────────────────────────────────────────────
    # Factory Methods
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_preset(
        cls,
        preset_name: str,
        **kwargs: Any,
    ) -> AdvancedRegexChunker:
        """
        Create a chunker from a pre-built pattern preset.

        Args:
            preset_name: Name of the preset (see PrebuiltPatterns).
            **kwargs: Additional chunker arguments.

        Returns:
            AdvancedRegexChunker instance.

        Example:
            >>> chunker = AdvancedRegexChunker.from_preset("markdown_sections")
            >>> chunker = AdvancedRegexChunker.from_preset("code_functions")
        """
        preset = PrebuiltPatterns.get_preset(preset_name)
        return cls(
            patterns=preset["patterns"],
            flags=preset.get("flags", re.MULTILINE),
            **kwargs,
        )

    @classmethod
    def from_patterns(
        cls,
        patterns: list[str],
        flags: int = re.MULTILINE,
        **kwargs: Any,
    ) -> AdvancedRegexChunker:
        """Create from a list of pattern strings."""
        return cls(patterns=patterns, flags=flags, **kwargs)

    # ──────────────────────────────────────────────────────────
    # Chunker Implementation
    # ──────────────────────────────────────────────────────────

    def _split(self, text: str) -> list[dict[str, Any]]:
        """Split text using combined regex patterns."""
        segments: list[dict[str, Any]] = []

        # Find all split points
        split_points: list[tuple[int, int, str]] = []  # (start, end, matched)

        for match in self._combined_pattern.finditer(text):
            split_points.append((match.start(), match.end(), match.group()))

        if not split_points:
            # No splits — entire text is one segment
            heading, level = self._find_nearest_heading(text, 0)
            return [{
                "text": text.strip(),
                "start": 0,
                "end": len(text),
                "heading": heading,
                "heading_level": level,
            }]

        # Build segments between split points
        prev_end = 0

        for i, (split_start, split_end, matched) in enumerate(split_points):
            # Segment before this split point
            if split_start > prev_end:
                segment_text = text[prev_end:split_start]

                if self._keep_delimiter and self._delimiter_position == "end" and i > 0:
                    # Append previous delimiter to end of this segment
                    pass  # Handled below

                if segment_text.strip():
                    heading, level = self._find_nearest_heading(text, prev_end)
                    segments.append({
                        "text": segment_text.strip(),
                        "start": prev_end,
                        "end": split_start,
                        "heading": heading,
                        "heading_level": level,
                    })

            # Handle delimiter
            if self._keep_delimiter:
                delimiter_text = matched.strip()
                if self._delimiter_position == "start":
                    # Delimiter goes to the start of the NEXT segment
                    # Find next segment start
                    next_start = split_end
                    if next_start < len(text):
                        # Find end of next segment
                        if i + 1 < len(split_points):
                            next_end = split_points[i + 1][0]
                        else:
                            next_end = len(text)

                        next_text = delimiter_text + "\n" + text[next_start:next_end]
                        if next_text.strip():
                            heading, level = self._find_nearest_heading(text, split_start)
                            segments.append({
                                "text": next_text.strip(),
                                "start": split_start,
                                "end": next_end,
                                "heading": heading,
                                "heading_level": level,
                            })
                        # Skip the next iteration's segment creation
                        prev_end = next_end
                        continue

            prev_end = split_end

        # Remaining text after last split
        if prev_end < len(text):
            remaining = text[prev_end:]
            if remaining.strip():
                heading, level = self._find_nearest_heading(text, prev_end)
                segments.append({
                    "text": remaining.strip(),
                    "start": prev_end,
                    "end": len(text),
                    "heading": heading,
                    "heading_level": level,
                })

        return segments

    def _find_nearest_heading(self, text: str, position: int) -> tuple[str, int]:
        """
        Find the nearest heading before a given position.

        Args:
            text: Full document text.
            position: Character position to search from.

        Returns:
            Tuple of (heading_text, heading_level).
        """
        if not self._track_headings:
            return "", 0

        nearest_heading = ""
        nearest_level = 0

        for match in self._heading_re.finditer(text):
            if match.start() > position:
                break
            nearest_heading = match.group(2).strip()
            nearest_level = len(match.group(1))

        return nearest_heading, nearest_level

    # ──────────────────────────────────────────────────────────
    # Pattern Management
    # ──────────────────────────────────────────────────────────

    def add_pattern(self, pattern: str) -> None:
        """
        Add a split pattern.

        Args:
            pattern: Regex pattern string.

        Raises:
            ValueError: If pattern is invalid.
        """
        try:
            compiled = re.compile(pattern, self._flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{pattern}': {e}")

        self._compiled_patterns.append(compiled)
        self._pattern_strings.append(pattern)
        self._combined_pattern = self._build_combined_pattern()

    def remove_pattern(self, pattern: str) -> bool:
        """
        Remove a split pattern.

        Args:
            pattern: Pattern string to remove.

        Returns:
            True if the pattern was found and removed.
        """
        if pattern in self._pattern_strings:
            idx = self._pattern_strings.index(pattern)
            self._pattern_strings.pop(idx)
            self._compiled_patterns.pop(idx)
            self._combined_pattern = self._build_combined_pattern()
            return True
        return False

    @property
    def patterns(self) -> list[str]:
        """Current split patterns."""
        return list(self._pattern_strings)

    def test_patterns(self, text: str, max_matches: int = 10) -> dict[str, list[dict[str, Any]]]:
        """
        Test all patterns against sample text.

        Args:
            text: Sample text.
            max_matches: Max matches per pattern.

        Returns:
            Dictionary mapping pattern to match results.
        """
        results: dict[str, list[dict[str, Any]]] = {}
        for pattern_str in self._pattern_strings:
            results[pattern_str] = test_pattern(
                pattern_str, text, self._flags, max_matches
            )
        return results

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "patterns": self._pattern_strings,
            "flags": self._flags,
            "keep_delimiter": self._keep_delimiter,
            "delimiter_position": self._delimiter_position,
            "track_headings": self._track_headings,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdvancedRegexChunker:
        return cls(
            patterns=data.get("patterns", [r"\n{2,}"]),
            flags=data.get("flags", re.MULTILINE),
            keep_delimiter=data.get("keep_delimiter", False),
            delimiter_position=data.get("delimiter_position", "start"),
            track_headings=data.get("track_headings", True),
            max_chunk_size=data.get("max_chunk_size", 1000),
            overlap=data.get("overlap", 200),
            min_chunk_size=data.get("min_chunk_size", 50),
        )

    def __repr__(self) -> str:
        return (
            f"AdvancedRegexChunker(patterns={len(self._pattern_strings)}, "
            f"max_size={self._max_chunk_size}, "
            f"overlap={self._overlap}, "
            f"keep_delim={self._keep_delimiter})"
        )


# ══════════════════════════════════════════════════════════════
# Convenience Functions
# ══════════════════════════════════════════════════════════════

def chunk_by_regex(
    text: str,
    pattern: str = r"\n{2,}",
    max_chunk_size: int = 1000,
    overlap: int = 200,
    flags: int = re.MULTILINE,
    **kwargs: Any,
) -> ChunkResult:
    """
    Chunk text by a regex pattern (convenience function).

    Args:
        text: Document text.
        pattern: Regex pattern to split on.
        max_chunk_size: Maximum chunk size.
        overlap: Overlap between chunks.
        flags: Regex flags.
        **kwargs: Additional chunker arguments.

    Returns:
        ChunkResult.

    Example:
        >>> result = chunk_by_regex(text, r"^#{1,3}\\s", max_chunk_size=1000)
        >>> print(f"{result.total_chunks} chunks")
    """
    chunker = AdvancedRegexChunker(
        patterns=[pattern],
        flags=flags,
        max_chunk_size=max_chunk_size,
        overlap=overlap,
        **kwargs,
    )
    return chunker.chunk(text)


def chunk_by_preset(
    text: str,
    preset: str = "markdown_sections",
    max_chunk_size: int = 1000,
    overlap: int = 200,
    **kwargs: Any,
) -> ChunkResult:
    """
    Chunk text using a pre-built pattern preset.

    Args:
        text: Document text.
        preset: Preset name (see PrebuiltPatterns).
        max_chunk_size: Maximum chunk size.
        overlap: Overlap between chunks.
        **kwargs: Additional chunker arguments.

    Returns:
        ChunkResult.

    Example:
        >>> result = chunk_by_preset(text, "markdown_sections")
        >>> result = chunk_by_preset(text, "code_functions", max_chunk_size=2000)
    """
    chunker = AdvancedRegexChunker.from_preset(
        preset,
        max_chunk_size=max_chunk_size,
        overlap=overlap,
        **kwargs,
    )
    return chunker.chunk(text)


# ══════════════════════════════════════════════════════════════
# Re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    # Base (re-exported)
    "Chunk",
    "Chunker",
    "ChunkResult",
    "RegexChunker",
    "create_chunker",
    "create_chunker_from_config",
    # Extended
    "AdvancedRegexChunker",
    "PrebuiltPatterns",
    "validate_pattern",
    "test_pattern",
    "chunk_by_regex",
    "chunk_by_preset",
]
