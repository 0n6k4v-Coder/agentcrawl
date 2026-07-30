"""
AgentCrawl — Content Filter Base & Pruning Filter
=====================================================

Abstract base class for content filters and a heuristic-based
Pruning filter that removes noise (navigation, ads, boilerplate)
from extracted web content using text density analysis.

Filters:
    ContentFilter (ABC)     — Abstract interface for all filters
    PruningContentFilter    — Heuristic noise removal (no query needed)
    BM25ContentFilter       — Query-based relevance (see bm25_filter.py)

The Pruning filter scores each text block based on:
    - Word density (words / total characters)
    - Link density (link text / total text)
    - Tag density (HTML tags / total content)
    - Text length (very short blocks are likely noise)
    - Position bias (header/footer regions)

Usage:
    from agentcrawl.content.content_filter import (
        ContentFilter,
        PruningContentFilter,
        create_content_filter,
    )

    # Pruning filter (no query needed)
    filter = PruningContentFilter(
        threshold=0.4,
        min_word_count=20,
        remove_nav=True,
        remove_footer=True,
    )
    result = filter.apply(markdown_text)
    print(result.filtered_text)

    # BM25 filter (query-based)
    from agentcrawl.content.bm25_filter import BM25ContentFilter
    filter = BM25ContentFilter(query="machine learning", threshold=1.0)
    result = filter.apply(markdown_text)

    # Factory
    filter = create_content_filter("pruning", threshold=0.5)
    filter = create_content_filter("bm25", query="python tutorial")

    # With CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(
        content_filter="pruning",
        content_filter_threshold=0.4,
    )
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.content.filter")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class ContentBlock:
    """
    A block of content extracted from the document.

    Attributes:
        text: The text content.
        block_type: Type ('heading', 'paragraph', 'list_item', 'code',
                    'table', 'blockquote', 'nav', 'footer', 'other').
        level: Heading level (1-6), 0 for non-headings.
        index: Position index in the document.
        word_count: Number of words.
        char_count: Number of characters.
        link_text_length: Characters that are link text.
        link_density: Ratio of link text to total text (0.0 - 1.0).
        score: Computed relevance/quality score.
        kept: Whether this block passed the filter.
        tags: HTML tags associated with this block (if available).
    """

    text: str
    block_type: str = "paragraph"
    level: int = 0
    index: int = 0
    word_count: int = 0
    char_count: int = 0
    link_text_length: int = 0
    link_density: float = 0.0
    score: float = 0.0
    kept: bool = True
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.char_count == 0:
            self.char_count = len(self.text)
        if self.word_count == 0:
            self.word_count = len(self.text.split())
        if self.char_count > 0 and self.link_text_length > 0:
            self.link_density = self.link_text_length / self.char_count

    @property
    def word_density(self) -> float:
        """Ratio of words to characters (higher = more text, less markup)."""
        if self.char_count == 0:
            return 0.0
        return self.word_count / (self.char_count / 5.0)  # ~5 chars per word

    @property
    def is_noise(self) -> bool:
        """Heuristic: whether this block looks like noise."""
        return (
            self.link_density > 0.5 or self.word_count < 5 or self.block_type in ("nav", "footer")
        )


@dataclass
class ContentFilterResult:
    """
    Result of content filtering.

    Attributes:
        filtered_text: The filtered document text.
        original_text: The original unfiltered text.
        blocks: All content blocks with scores.
        kept_blocks: Blocks that passed the filter.
        removed_blocks: Blocks that were removed.
        filter_type: Name of the filter used.
        threshold: Threshold used for filtering.
        original_word_count: Words before filtering.
        filtered_word_count: Words after filtering.
        reduction_ratio: Fraction of content removed (0.0 - 1.0).
        noise_blocks_removed: Number of noise blocks removed.
    """

    filtered_text: str = ""
    original_text: str = ""
    blocks: list[ContentBlock] = field(default_factory=list)
    kept_blocks: list[ContentBlock] = field(default_factory=list)
    removed_blocks: list[ContentBlock] = field(default_factory=list)
    filter_type: str = ""
    threshold: float = 0.0
    original_word_count: int = 0
    filtered_word_count: int = 0
    reduction_ratio: float = 0.0
    noise_blocks_removed: int = 0

    def __post_init__(self) -> None:
        if self.original_word_count > 0:
            self.reduction_ratio = 1.0 - (self.filtered_word_count / self.original_word_count)
        else:
            self.reduction_ratio = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "filter_type": self.filter_type,
            "threshold": self.threshold,
            "original_word_count": self.original_word_count,
            "filtered_word_count": self.filtered_word_count,
            "reduction_ratio": round(self.reduction_ratio, 3),
            "total_blocks": len(self.blocks),
            "kept_blocks": len(self.kept_blocks),
            "removed_blocks": len(self.removed_blocks),
            "noise_blocks_removed": self.noise_blocks_removed,
        }


# ══════════════════════════════════════════════════════════════
# Abstract Base Filter
# ══════════════════════════════════════════════════════════════


class ContentFilter(ABC):
    """
    Abstract base class for content filters.

    Subclasses must implement the ``apply`` method which takes
    document text and returns a ContentFilterResult.

    Args:
        threshold: Filter threshold (interpretation varies by filter).
        min_word_count: Minimum words for a block to be considered.
    """

    filter_name: str = "base"

    def __init__(
        self,
        threshold: float = 0.5,
        min_word_count: int = 10,
    ):
        self._threshold = threshold
        self._min_word_count = min_word_count

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = value

    @abstractmethod
    def apply(self, text: str, **kwargs: Any) -> ContentFilterResult:
        """
        Apply the filter to document text.

        Args:
            text: The full document text (typically Markdown).
            **kwargs: Filter-specific parameters.

        Returns:
            ContentFilterResult with filtered text and block details.
        """
        ...

    def filter_blocks(self, blocks: list[ContentBlock]) -> list[ContentBlock]:
        """
        Filter a list of pre-parsed blocks.

        Default implementation scores and filters by threshold.
        Subclasses can override for custom logic.

        Args:
            blocks: List of ContentBlock instances.

        Returns:
            Filtered list of blocks.
        """
        for block in blocks:
            block.score = self._score_block(block)
            block.kept = block.score >= self._threshold

        return [b for b in blocks if b.kept]

    def _score_block(self, block: ContentBlock) -> float:
        """
        Score a single block. Override in subclasses.

        Default: simple word density score.
        """
        return block.word_density

    # ──────────────────────────────────────────────────────────
    # Shared Utilities
    # ──────────────────────────────────────────────────────────

    def _split_into_blocks(self, text: str) -> list[ContentBlock]:
        """
        Split text into content blocks.

        Splits on Markdown headings, double newlines, and
        preserves code blocks and tables as atomic units.
        """
        blocks: list[ContentBlock] = []
        lines = text.split("\n")
        current_lines: list[str] = []
        current_type = "paragraph"
        current_level = 0
        in_code = False
        in_table = False
        index = 0

        def _flush() -> None:
            nonlocal current_lines, current_type, current_level, index
            if current_lines:
                block_text = "\n".join(current_lines).strip()
                if block_text:
                    # Calculate link text length
                    link_text_len = sum(
                        len(m.group(1)) for m in re.finditer(r"\[([^\]]*)\]\([^)]+\)", block_text)
                    )
                    blocks.append(
                        ContentBlock(
                            text=block_text,
                            block_type=current_type,
                            level=current_level,
                            index=index,
                            link_text_length=link_text_len,
                        )
                    )
                    index += 1
                current_lines = []
                current_type = "paragraph"
                current_level = 0

        for line in lines:
            stripped = line.strip()

            # Code block
            if stripped.startswith("```"):
                if in_code:
                    current_lines.append(line)
                    in_code = False
                    current_type = "code"
                    _flush()
                    continue
                else:
                    _flush()
                    in_code = True
                    current_lines.append(line)
                    continue

            if in_code:
                current_lines.append(line)
                continue

            # Table
            if "|" in stripped and stripped.startswith("|"):
                if not in_table:
                    _flush()
                    in_table = True
                    current_type = "table"
                current_lines.append(line)
                continue
            elif in_table:
                in_table = False
                _flush()

            # Heading
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                _flush()
                level = len(heading_match.group(1))
                blocks.append(
                    ContentBlock(
                        text=stripped,
                        block_type="heading",
                        level=level,
                        index=index,
                    )
                )
                index += 1
                continue

            # Navigation indicators
            nav_keywords = [
                "navigation",
                "menu",
                "sidebar",
                "breadcrumb",
                "skip to",
                "toggle navigation",
                "hamburger",
                "cookie notice",
                "cookie banner",
                "cookie consent",
            ]
            if any(kw in stripped.lower() for kw in nav_keywords):
                _flush()
                blocks.append(
                    ContentBlock(
                        text=stripped,
                        block_type="nav",
                        index=index,
                    )
                )
                index += 1
                continue

            # Footer indicators
            footer_keywords = [
                "copyright",
                "all rights reserved",
                "privacy policy",
                "terms of service",
                "terms of use",
                "cookie policy",
                "cookie notice",
                "cookie consent",
                "powered by",
                "built with",
            ]
            if any(kw in stripped.lower() for kw in footer_keywords):
                _flush()
                blocks.append(
                    ContentBlock(
                        text=stripped,
                        block_type="footer",
                        index=index,
                    )
                )
                index += 1
                continue

            # List item
            if re.match(r"^(\s*[-*+]|\s*\d+\.)\s+", stripped):
                if current_type != "list_item":
                    _flush()
                    current_type = "list_item"
                current_lines.append(line)
                continue

            # Blockquote
            if stripped.startswith(">"):
                if current_type != "blockquote":
                    _flush()
                    current_type = "blockquote"
                current_lines.append(line)
                continue

            # Empty line
            if not stripped:
                _flush()
                continue

            # Regular text
            if current_type not in ("paragraph",):
                _flush()
                current_type = "paragraph"
            current_lines.append(line)

        _flush()
        return blocks

    @staticmethod
    def _join_blocks(blocks: list[ContentBlock]) -> str:
        """Join blocks back into text."""
        return "\n\n".join(b.text for b in blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filter_type": self.filter_name,
            "threshold": self._threshold,
            "min_word_count": self._min_word_count,
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(threshold={self._threshold}, "
            f"min_words={self._min_word_count})"
        )


# ══════════════════════════════════════════════════════════════
# Pruning Content Filter
# ══════════════════════════════════════════════════════════════


class PruningContentFilter(ContentFilter):
    """
    Heuristic-based content pruning filter.

    Removes noise (navigation, ads, boilerplate, footers) using
    text density analysis. Does NOT require a query — works purely
    on content structure and statistics.

    Scoring factors:
        - Word density: ratio of words to characters
        - Link density: ratio of link text to total text (high = noise)
        - Block length: very short blocks are likely noise
        - Block type: nav/footer blocks are penalized
        - Position: blocks at document edges are penalized

    Args:
        threshold: Minimum score to keep a block (0.0 - 1.0).
        min_word_count: Minimum words for scoring (shorter blocks kept as-is).
        remove_nav: Remove navigation blocks.
        remove_footer: Remove footer blocks.
        remove_high_link_density: Remove blocks with link_density > max_link_density.
        max_link_density: Maximum link density threshold.
        keep_headings: Always keep heading blocks.
        keep_code: Always keep code blocks.
        keep_tables: Always keep table blocks.
        keep_first_n: Always keep the first N blocks.
        keep_last_n: Always keep the last N blocks.
        length_weight: Weight for block length in scoring.
        density_weight: Weight for word density in scoring.
        link_penalty_weight: Weight for link density penalty.

    Example:
        >>> filter = PruningContentFilter(
        ...     threshold=0.4,
        ...     remove_nav=True,
        ...     remove_footer=True,
        ...     max_link_density=0.5,
        ... )
        >>> result = filter.apply(markdown_text)
        >>> print(f"Removed {result.noise_blocks_removed} noise blocks")
        >>> print(f"Reduction: {result.reduction_ratio:.1%}")
    """

    filter_name = "pruning"

    def __init__(
        self,
        threshold: float = 0.4,
        min_word_count: int = 10,
        remove_nav: bool = True,
        remove_footer: bool = True,
        remove_high_link_density: bool = True,
        max_link_density: float = 0.5,
        keep_headings: bool = True,
        keep_code: bool = True,
        keep_tables: bool = True,
        keep_first_n: int = 1,
        keep_last_n: int = 0,
        length_weight: float = 0.3,
        density_weight: float = 0.4,
        link_penalty_weight: float = 0.3,
    ):
        super().__init__(threshold=threshold, min_word_count=min_word_count)
        self._remove_nav = remove_nav
        self._remove_footer = remove_footer
        self._remove_high_link_density = remove_high_link_density
        self._max_link_density = max_link_density
        self._keep_headings = keep_headings
        self._keep_code = keep_code
        self._keep_tables = keep_tables
        self._keep_first_n = keep_first_n
        self._keep_last_n = keep_last_n
        self._length_weight = length_weight
        self._density_weight = density_weight
        self._link_penalty_weight = link_penalty_weight

    # ──────────────────────────────────────────────────────────
    # Main API
    # ──────────────────────────────────────────────────────────

    def apply(self, text: str, **kwargs: Any) -> ContentFilterResult:
        """
        Apply pruning filter to document text.

        Args:
            text: Full document text (Markdown).

        Returns:
            ContentFilterResult with filtered text and statistics.
        """
        if not text.strip():
            return ContentFilterResult(
                original_text=text,
                filtered_text="",
                filter_type=self.filter_name,
            )

        # Split into blocks
        blocks = self._split_into_blocks(text)

        if not blocks:
            return ContentFilterResult(
                original_text=text,
                filtered_text="",
                filter_type=self.filter_name,
            )

        # Score all blocks
        max_word_count = max(b.word_count for b in blocks) if blocks else 1
        for block in blocks:
            block.score = self._score_block_pruning(block, max_word_count)

        # Determine which blocks to keep
        total = len(blocks)
        noise_removed = 0

        for i, block in enumerate(blocks):
            # Always keep first N blocks
            if i < self._keep_first_n:
                block.kept = True
                continue

            # Always keep last N blocks
            if self._keep_last_n > 0 and i >= total - self._keep_last_n:
                block.kept = True
                continue

            # Always keep headings
            if self._keep_headings and block.block_type == "heading":
                block.kept = True
                continue

            # Always keep code blocks
            if self._keep_code and block.block_type == "code":
                block.kept = True
                continue

            # Always keep tables
            if self._keep_tables and block.block_type == "table":
                block.kept = True
                continue

            # Keep very short blocks (can't score reliably)
            if block.word_count < self._min_word_count:
                block.kept = True
                continue

            # Remove navigation
            if self._remove_nav and block.block_type == "nav":
                block.kept = False
                noise_removed += 1
                continue

            # Remove footer
            if self._remove_footer and block.block_type == "footer":
                block.kept = False
                noise_removed += 1
                continue

            # Remove high link density
            if self._remove_high_link_density and block.link_density > self._max_link_density:
                block.kept = False
                noise_removed += 1
                continue

            # Score-based filtering
            block.kept = block.score >= self._threshold

            if not block.kept:
                noise_removed += 1

        kept_blocks = [b for b in blocks if b.kept]
        removed_blocks = [b for b in blocks if not b.kept]

        # Build filtered text
        filtered_text = self._join_blocks(kept_blocks)

        # Stats
        original_wc = len(text.split())
        filtered_wc = len(filtered_text.split())

        return ContentFilterResult(
            filtered_text=filtered_text,
            original_text=text,
            blocks=blocks,
            kept_blocks=kept_blocks,
            removed_blocks=removed_blocks,
            filter_type=self.filter_name,
            threshold=self._threshold,
            original_word_count=original_wc,
            filtered_word_count=filtered_wc,
            reduction_ratio=1.0 - (filtered_wc / max(original_wc, 1)),
            noise_blocks_removed=noise_removed,
        )

    # ──────────────────────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────────────────────

    def _score_block_pruning(
        self,
        block: ContentBlock,
        max_word_count: int,
    ) -> float:
        """
        Compute a pruning score for a block (0.0 = noise, 1.0 = content).

        Combines:
            - Length score: normalized word count
            - Density score: word density
            - Link penalty: high link density reduces score
        """
        # Length score (0-1): longer blocks are more likely content
        length_score = min(block.word_count / max(max_word_count, 1), 1.0)

        # Density score (0-1): higher word density = more text, less markup
        density_score = min(block.word_density, 1.0)

        # Link penalty (0-1): high link density = likely navigation/ads
        link_penalty = 1.0 - min(block.link_density / max(self._max_link_density, 0.01), 1.0)

        # Block type bonus/penalty
        type_multiplier = 1.0
        if block.block_type == "heading":
            type_multiplier = 1.5
        elif block.block_type == "code":
            type_multiplier = 1.3
        elif block.block_type == "table":
            type_multiplier = 1.2
        elif block.block_type == "blockquote":
            type_multiplier = 1.1
        elif block.block_type == "nav":
            type_multiplier = 0.2
        elif block.block_type == "footer":
            type_multiplier = 0.1
        elif block.block_type == "list_item":
            type_multiplier = 1.0

        # Weighted combination
        raw_score = (
            self._length_weight * length_score
            + self._density_weight * density_score
            + self._link_penalty_weight * link_penalty
        )

        return min(raw_score * type_multiplier, 1.0)

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "remove_nav": self._remove_nav,
                "remove_footer": self._remove_footer,
                "remove_high_link_density": self._remove_high_link_density,
                "max_link_density": self._max_link_density,
                "keep_headings": self._keep_headings,
                "keep_code": self._keep_code,
                "keep_tables": self._keep_tables,
                "keep_first_n": self._keep_first_n,
                "keep_last_n": self._keep_last_n,
            }
        )
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PruningContentFilter:
        return cls(
            threshold=data.get("threshold", 0.4),
            min_word_count=data.get("min_word_count", 10),
            remove_nav=data.get("remove_nav", True),
            remove_footer=data.get("remove_footer", True),
            remove_high_link_density=data.get("remove_high_link_density", True),
            max_link_density=data.get("max_link_density", 0.5),
            keep_headings=data.get("keep_headings", True),
            keep_code=data.get("keep_code", True),
            keep_tables=data.get("keep_tables", True),
            keep_first_n=data.get("keep_first_n", 1),
            keep_last_n=data.get("keep_last_n", 0),
        )

    def __repr__(self) -> str:
        return (
            f"PruningContentFilter(threshold={self._threshold}, "
            f"remove_nav={self._remove_nav}, "
            f"max_link_density={self._max_link_density})"
        )


# ══════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════


def create_content_filter(
    filter_type: str = "pruning",
    **kwargs: Any,
) -> ContentFilter | Any:
    """
    Factory function to create a content filter by type.

    Args:
        filter_type: Filter type ('pruning', 'bm25', 'none').
        **kwargs: Filter-specific arguments.

    Returns:
        ContentFilter instance.

    Raises:
        ValueError: If filter_type is unknown.

    Example:
        >>> filter = create_content_filter("pruning", threshold=0.5)
        >>> filter = create_content_filter("bm25", query="python", threshold=1.0)
    """
    filter_lower = filter_type.lower().strip()

    if filter_lower == "none":
        return _NoOpFilter()

    if filter_lower == "pruning":
        return PruningContentFilter(**kwargs)

    if filter_lower == "bm25":
        from agentcrawl.content.bm25_filter import BM25ContentFilter

        return BM25ContentFilter(**kwargs)

    raise ValueError(f"Unknown content filter: '{filter_type}'. Available: none, pruning, bm25")


def create_content_filter_from_config(config: Any) -> ContentFilter | None:
    """
    Create a content filter from a CrawlerConfig instance.

    Args:
        config: CrawlerConfig with content_filter settings.

    Returns:
        ContentFilter instance, or None if filtering is disabled.
    """
    from agentcrawl.config.crawler_config import ContentFilterType

    filter_type = config.content_filter
    if isinstance(filter_type, str):
        try:
            filter_type = ContentFilterType(filter_type)
        except ValueError:
            return None

    if filter_type == ContentFilterType.NONE:
        return None

    kwargs: dict[str, Any] = {
        "threshold": config.content_filter_threshold,
    }

    if filter_type == ContentFilterType.BM25:
        kwargs["query"] = config.content_filter_query or ""

    return create_content_filter(
        filter_type=filter_type.value,
        **kwargs,
    )


# ══════════════════════════════════════════════════════════════
# No-Op Filter
# ══════════════════════════════════════════════════════════════


class _NoOpFilter(ContentFilter):
    """A filter that passes all content through unchanged."""

    filter_name = "none"

    def apply(self, text: str, **kwargs: Any) -> ContentFilterResult:
        blocks = self._split_into_blocks(text)
        return ContentFilterResult(
            filtered_text=text,
            original_text=text,
            blocks=blocks,
            kept_blocks=blocks,
            removed_blocks=[],
            filter_type=self.filter_name,
            original_word_count=len(text.split()),
            filtered_word_count=len(text.split()),
            reduction_ratio=0.0,
        )
