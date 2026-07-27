"""
AgentCrawl — Pruning Content Filter (Extended)
==================================================

Extended pruning filter with advanced noise detection, multi-pass
scoring, content density analysis, and boilerplate removal.

This module extends the base PruningContentFilter from content_filter.py
with additional capabilities:

    - Multi-pass pruning (coarse → fine)
    - Content density analysis (text-to-markup ratio per region)
    - Boilerplate detection (cookie banners, popups, newsletters)
    - Positional scoring (header/footer/sidebar penalty)
    - Language-aware word counting
    - Readability scoring (Flesch-Kincaid approximation)

Usage:
    from agentcrawl.content.pruning_filter import (
        PruningContentFilter,       # Re-exported from content_filter
        AdvancedPruningFilter,      # Multi-pass with density analysis
        BoilerplateDetector,        # Detect and remove boilerplate
        ContentDensityAnalyzer,     # Analyze text density
    )

    # Standard pruning (same as content_filter.py)
    filter = PruningContentFilter(threshold=0.4)
    result = filter.apply(markdown_text)

    # Advanced multi-pass pruning
    filter = AdvancedPruningFilter(
        threshold=0.35,
        passes=2,
        density_weight=0.4,
        position_weight=0.2,
    )
    result = filter.apply(markdown_text)

    # Boilerplate detection
    detector = BoilerplateDetector()
    cleaned = detector.remove_boilerplate(markdown_text)

    # Density analysis
    analyzer = ContentDensityAnalyzer()
    report = analyzer.analyze(markdown_text)
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

# Re-export base classes for convenience
from agentcrawl.content.content_filter import (
    ContentBlock,
    ContentFilter,
    ContentFilterResult,
    PruningContentFilter,
    create_content_filter,
    create_content_filter_from_config,
)

logger = logging.getLogger("agentcrawl.content.pruning")


# ══════════════════════════════════════════════════════════════
# Boilerplate Patterns
# ══════════════════════════════════════════════════════════════

# Common boilerplate text patterns (case-insensitive)
BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
    # Cookie / consent
    re.compile(r"cookie\s*(policy|consent|notice|banner|settings|preferences)", re.I),
    re.compile(r"(accept|reject|manage)\s*(all\s*)?cookies", re.I),
    re.compile(r"we\s+use\s+cookies", re.I),
    re.compile(r"cookie\s+consent", re.I),
    re.compile(r"gdpr|general\s+data\s+protection", re.I),

    # Newsletter / subscription
    re.compile(r"subscribe\s+to\s+(our\s+)?newsletter", re.I),
    re.compile(r"(sign|subscribe)\s*(up)?\s*(for|to)\s*(our\s+)?(email|mailing)", re.I),
    re.compile(r"enter\s+your\s+email", re.I),
    re.compile(r"join\s+our\s+(mailing\s+)?list", re.I),
    re.compile(r"get\s+(the\s+)?latest\s+(news|updates)\s+(in\s+your\s+)?inbox", re.I),

    # Social media
    re.compile(r"(follow|share)\s+(us\s+)?(on|via)\s+(twitter|facebook|instagram|linkedin|youtube|tiktok)", re.I),
    re.compile(r"share\s+(this|on)\s+(social|twitter|facebook)", re.I),
    re.compile(r"connect\s+with\s+us", re.I),

    # Ads / promotions
    re.compile(r"(sponsored|advertisement|promoted)\s*(content|post|by)?", re.I),
    re.compile(r"(buy|shop|order|purchase)\s+now", re.I),
    re.compile(r"(limited|special)\s+(time\s+)?offer", re.I),
    re.compile(r"(discount|coupon|promo)\s+code", re.I),
    re.compile(r"free\s+trial|start\s+free", re.I),

    # Navigation / UI
    re.compile(r"skip\s+to\s+(main\s+)?content", re.I),
    re.compile(r"toggle\s+(navigation|menu|sidebar)", re.I),
    re.compile(r"(back|return)\s+to\s+(top|home|main)", re.I),
    re.compile(r"page\s+\d+\s+of\s+\d+", re.I),
    re.compile(r"(previous|next)\s+(page|post|article)", re.I),

    # Legal / footer
    re.compile(r"(all\s+)?rights?\s+reserved", re.I),
    re.compile(r"terms?\s+(of\s+)?(service|use|conditions)", re.I),
    re.compile(r"privacy\s+(policy|statement|notice)", re.I),
    re.compile(r"powered\s+by|built\s+with|made\s+with", re.I),
    re.compile(r"©\s*\d{4}", re.I),

    # App / download
    re.compile(r"download\s+(our\s+)?(app|application)", re.I),
    re.compile(r"(available|get\s+it)\s+on\s+(the\s+)?(app\s+store|google\s+play)", re.I),

    # Comments
    re.compile(r"(leave|post|write)\s+a\s+comment", re.I),
    re.compile(r"\d+\s+(comments?|replies|responses)", re.I),
    re.compile(r"comments?\s+are\s+(closed|disabled)", re.I),

    # Related content
    re.compile(r"(related|recommended|suggested)\s+(articles?|posts?|content|reading)", re.I),
    re.compile(r"you\s+may\s+also\s+(like|enjoy|want)", re.I),
    re.compile(r"(more|other)\s+(from|by)\s+(this|our)", re.I),
]

# CSS class/ID patterns for boilerplate containers
BOILERPLATE_CONTAINER_PATTERNS: list[str] = [
    r"cookie", r"consent", r"gdpr", r"banner",
    r"newsletter", r"subscribe", r"signup", r"sign-up",
    r"social", r"share", r"sharing",
    r"advert", r"ad-", r"ads-", r"sponsor",
    r"popup", r"modal", r"overlay", r"dialog",
    r"promo", r"promotion", r"deal",
    r"related", r"recommend", r"suggested",
    r"comment", r"disqus",
    r"footer", r"copyright", r"legal",
    r"sidebar", r"widget",
    r"nav", r"menu", r"breadcrumb",
    r"pagination", r"pager",
]


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class DensityReport:
    """
    Content density analysis report.

    Attributes:
        total_blocks: Total number of text blocks.
        content_blocks: Blocks classified as content.
        noise_blocks: Blocks classified as noise.
        boilerplate_blocks: Blocks classified as boilerplate.
        content_ratio: Ratio of content to total (0.0 - 1.0).
        noise_ratio: Ratio of noise to total.
        boilerplate_ratio: Ratio of boilerplate to total.
        avg_content_density: Average text density of content blocks.
        avg_noise_density: Average text density of noise blocks.
        readability_score: Approximate Flesch-Kincaid readability score.
        language_hint: Detected language hint.
    """
    total_blocks: int = 0
    content_blocks: int = 0
    noise_blocks: int = 0
    boilerplate_blocks: int = 0
    content_ratio: float = 0.0
    noise_ratio: float = 0.0
    boilerplate_ratio: float = 0.0
    avg_content_density: float = 0.0
    avg_noise_density: float = 0.0
    readability_score: float = 0.0
    language_hint: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_blocks": self.total_blocks,
            "content_blocks": self.content_blocks,
            "noise_blocks": self.noise_blocks,
            "boilerplate_blocks": self.boilerplate_blocks,
            "content_ratio": round(self.content_ratio, 3),
            "noise_ratio": round(self.noise_ratio, 3),
            "boilerplate_ratio": round(self.boilerplate_ratio, 3),
            "avg_content_density": round(self.avg_content_density, 3),
            "avg_noise_density": round(self.avg_noise_density, 3),
            "readability_score": round(self.readability_score, 1),
            "language_hint": self.language_hint,
        }


# ══════════════════════════════════════════════════════════════
# Boilerplate Detector
# ══════════════════════════════════════════════════════════════

class BoilerplateDetector:
    """
    Detects and removes boilerplate content from text.

    Identifies cookie banners, newsletter signups, social media
    widgets, ads, navigation elements, and other non-content text.

    Args:
        patterns: Custom regex patterns to match (in addition to defaults).
        min_match_length: Minimum text length to check for patterns.
        remove_matched: Whether to remove matched blocks (vs just flag).

    Example:
        >>> detector = BoilerplateDetector()
        >>> cleaned = detector.remove_boilerplate(markdown_text)
        >>> print(f"Removed {detector.last_removed_count} boilerplate blocks")
    """

    def __init__(
        self,
        patterns: list[str] | None = None,
        min_match_length: int = 10,
        remove_matched: bool = True,
    ):
        self._patterns = list(BOILERPLATE_PATTERNS)
        if patterns:
            for p in patterns:
                self._patterns.append(re.compile(p, re.IGNORECASE))
        self._min_match_length = min_match_length
        self._remove_matched = remove_matched
        self._last_removed_count = 0

    @property
    def last_removed_count(self) -> int:
        """Number of blocks removed in the last operation."""
        return self._last_removed_count

    def is_boilerplate(self, text: str) -> bool:
        """
        Check if a text block is boilerplate.

        Args:
            text: Text to check.

        Returns:
            True if the text matches boilerplate patterns.
        """
        if len(text) < self._min_match_length:
            return False

        for pattern in self._patterns:
            if pattern.search(text):
                return True

        return False

    def detect(self, text: str) -> list[dict[str, Any]]:
        """
        Detect boilerplate blocks in text.

        Args:
            text: Full document text.

        Returns:
            List of detected boilerplate blocks with positions.
        """
        blocks = self._split_blocks(text)
        detected: list[dict[str, Any]] = []

        for i, block in enumerate(blocks):
            if self.is_boilerplate(block):
                detected.append({
                    "index": i,
                    "text": block[:200],
                    "length": len(block),
                })

        return detected

    def remove_boilerplate(self, text: str) -> str:
        """
        Remove boilerplate blocks from text.

        Args:
            text: Full document text.

        Returns:
            Text with boilerplate removed.
        """
        blocks = self._split_blocks(text)
        kept: list[str] = []
        removed = 0

        for block in blocks:
            if self.is_boilerplate(block):
                removed += 1
            else:
                kept.append(block)

        self._last_removed_count = removed
        return "\n\n".join(kept)

    def flag_boilerplate(self, text: str) -> list[tuple[str, bool]]:
        """
        Split text into blocks and flag each as boilerplate or not.

        Args:
            text: Full document text.

        Returns:
            List of (block_text, is_boilerplate) tuples.
        """
        blocks = self._split_blocks(text)
        return [(block, self.is_boilerplate(block)) for block in blocks]

    @staticmethod
    def _split_blocks(text: str) -> list[str]:
        """Split text into blocks by double newlines."""
        blocks = re.split(r"\n{2,}", text)
        return [b.strip() for b in blocks if b.strip()]


# ══════════════════════════════════════════════════════════════
# Content Density Analyzer
# ══════════════════════════════════════════════════════════════

class ContentDensityAnalyzer:
    """
    Analyzes text density to distinguish content from noise.

    Computes text-to-markup ratios, link densities, and
    positional scores for each text block.

    Example:
        >>> analyzer = ContentDensityAnalyzer()
        >>> report = analyzer.analyze(markdown_text)
        >>> print(f"Content ratio: {report.content_ratio:.1%}")
        >>> print(f"Readability: {report.readability_score:.1f}")
    """

    def __init__(
        self,
        content_threshold: float = 0.4,
        noise_link_density: float = 0.5,
        min_content_words: int = 20,
    ):
        self._content_threshold = content_threshold
        self._noise_link_density = noise_link_density
        self._min_content_words = min_content_words

    def analyze(self, text: str) -> DensityReport:
        """
        Analyze content density of a document.

        Args:
            text: Full document text.

        Returns:
            DensityReport with analysis results.
        """
        blocks = self._split_blocks(text)
        if not blocks:
            return DensityReport()

        content_count = 0
        noise_count = 0
        boilerplate_count = 0
        content_densities: list[float] = []
        noise_densities: list[float] = []

        detector = BoilerplateDetector()

        for block in blocks:
            density = self._compute_density(block)
            link_density = self._compute_link_density(block)
            word_count = len(block.split())
            is_bp = detector.is_boilerplate(block)

            if is_bp:
                boilerplate_count += 1
            elif (
                density >= self._content_threshold
                and link_density < self._noise_link_density
                and word_count >= self._min_content_words
            ):
                content_count += 1
                content_densities.append(density)
            else:
                noise_count += 1
                noise_densities.append(density)

        total = len(blocks)
        readability = self._compute_readability(text)
        lang = self._detect_language(text)

        return DensityReport(
            total_blocks=total,
            content_blocks=content_count,
            noise_blocks=noise_count,
            boilerplate_blocks=boilerplate_count,
            content_ratio=content_count / max(total, 1),
            noise_ratio=noise_count / max(total, 1),
            boilerplate_ratio=boilerplate_count / max(total, 1),
            avg_content_density=sum(content_densities) / max(len(content_densities), 1),
            avg_noise_density=sum(noise_densities) / max(len(noise_densities), 1),
            readability_score=readability,
            language_hint=lang,
        )

    def _compute_density(self, text: str) -> float:
        """
        Compute text density score (0.0 - 1.0).

        Higher = more likely to be content.
        Based on word-to-character ratio and average word length.
        """
        if not text:
            return 0.0

        words = text.split()
        word_count = len(words)
        char_count = len(text)

        if char_count == 0:
            return 0.0

        # Word density: words per ~5 characters
        word_density = word_count / (char_count / 5.0)

        # Average word length (content tends to have 4-8 char words)
        avg_word_len = sum(len(w) for w in words) / max(word_count, 1)
        word_len_score = min(avg_word_len / 6.0, 1.0)

        # Sentence structure (content has periods, commas)
        sentence_markers = text.count(".") + text.count("!") + text.count("?")
        sentence_score = min(sentence_markers / max(word_count / 15, 1), 1.0)

        return (
            0.5 * min(word_density, 1.0)
            + 0.3 * word_len_score
            + 0.2 * sentence_score
        )

    @staticmethod
    def _compute_link_density(text: str) -> float:
        """Compute ratio of link text to total text."""
        link_text_len = sum(
            len(m.group(1))
            for m in re.finditer(r"\[([^\]]*)\]\([^)]+\)", text)
        )
        total_len = len(text)
        if total_len == 0:
            return 0.0
        return link_text_len / total_len

    @staticmethod
    def _compute_readability(text: str) -> float:
        """
        Approximate Flesch-Kincaid readability score.

        Returns a score roughly in the range 0-100.
        Higher = easier to read.
        """
        # Count sentences
        sentences = re.split(r"[.!?]+", text)
        sentence_count = max(len([s for s in sentences if s.strip()]), 1)

        # Count words
        words = text.split()
        word_count = max(len(words), 1)

        # Count syllables (rough approximation)
        syllable_count = 0
        for word in words:
            word = word.lower().strip(".,!?;:")
            if not word:
                continue
            # Count vowel groups
            vowels = re.findall(r"[aeiouy]+", word)
            syllables = max(len(vowels), 1)
            # Silent e
            if word.endswith("e") and syllables > 1:
                syllables -= 1
            syllable_count += max(syllables, 1)

        # Flesch-Kincaid formula
        try:
            score = (
                206.835
                - 1.015 * (word_count / sentence_count)
                - 84.6 * (syllable_count / word_count)
            )
            return max(0.0, min(100.0, score))
        except ZeroDivisionError:
            return 0.0

    @staticmethod
    def _detect_language(text: str) -> str:
        """Simple language detection based on character ranges."""
        # Check for Thai
        thai_chars = len(re.findall(r"[\u0e00-\u0e7f]", text))
        if thai_chars > len(text) * 0.1:
            return "th"

        # Check for CJK
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]", text))
        if cjk_chars > len(text) * 0.1:
            return "cjk"

        # Check for Arabic
        arabic_chars = len(re.findall(r"[\u0600-\u06ff]", text))
        if arabic_chars > len(text) * 0.1:
            return "ar"

        # Check for Cyrillic
        cyrillic_chars = len(re.findall(r"[\u0400-\u04ff]", text))
        if cyrillic_chars > len(text) * 0.1:
            return "ru"

        return "en"

    @staticmethod
    def _split_blocks(text: str) -> list[str]:
        """Split text into blocks."""
        blocks = re.split(r"\n{2,}", text)
        return [b.strip() for b in blocks if b.strip()]


# ══════════════════════════════════════════════════════════════
# Advanced Pruning Filter
# ══════════════════════════════════════════════════════════════

class AdvancedPruningFilter(ContentFilter):
    """
    Multi-pass pruning filter with density analysis and
    boilerplate detection.

    Performs two passes:
        Pass 1 (Coarse): Remove obvious noise (nav, footer, ads,
                         high link density, boilerplate patterns)
        Pass 2 (Fine):   Score remaining blocks by density, position,
                         and length; remove below threshold

    Args:
        threshold: Minimum score to keep a block (0.0 - 1.0).
        passes: Number of pruning passes (1 or 2).
        density_weight: Weight for text density in scoring.
        position_weight: Weight for positional score.
        length_weight: Weight for block length.
        link_penalty_weight: Weight for link density penalty.
        boilerplate_detection: Enable boilerplate pattern matching.
        remove_nav: Remove navigation blocks.
        remove_footer: Remove footer blocks.
        max_link_density: Maximum link density threshold.
        keep_headings: Always keep heading blocks.
        keep_code: Always keep code blocks.
        keep_tables: Always keep table blocks.
        keep_first_n: Always keep first N blocks.
        min_word_count: Minimum words for scoring.

    Example:
        >>> filter = AdvancedPruningFilter(
        ...     threshold=0.35,
        ...     passes=2,
        ...     boilerplate_detection=True,
        ... )
        >>> result = filter.apply(markdown_text)
        >>> print(f"Kept {len(result.kept_blocks)}/{len(result.blocks)} blocks")
        >>> print(f"Reduction: {result.reduction_ratio:.1%}")
    """

    filter_name = "advanced_pruning"

    def __init__(
        self,
        threshold: float = 0.35,
        passes: int = 2,
        density_weight: float = 0.4,
        position_weight: float = 0.2,
        length_weight: float = 0.2,
        link_penalty_weight: float = 0.2,
        boilerplate_detection: bool = True,
        remove_nav: bool = True,
        remove_footer: bool = True,
        max_link_density: float = 0.5,
        keep_headings: bool = True,
        keep_code: bool = True,
        keep_tables: bool = True,
        keep_first_n: int = 1,
        min_word_count: int = 10,
    ):
        super().__init__(threshold=threshold, min_word_count=min_word_count)
        self._passes = max(1, min(passes, 3))
        self._density_weight = density_weight
        self._position_weight = position_weight
        self._length_weight = length_weight
        self._link_penalty_weight = link_penalty_weight
        self._boilerplate_detection = boilerplate_detection
        self._remove_nav = remove_nav
        self._remove_footer = remove_footer
        self._max_link_density = max_link_density
        self._keep_headings = keep_headings
        self._keep_code = keep_code
        self._keep_tables = keep_tables
        self._keep_first_n = keep_first_n

        self._bp_detector = BoilerplateDetector() if boilerplate_detection else None
        self._density_analyzer = ContentDensityAnalyzer()

    # ──────────────────────────────────────────────────────────
    # Main API
    # ──────────────────────────────────────────────────────────

    def apply(self, text: str, **kwargs: Any) -> ContentFilterResult:
        """
        Apply multi-pass pruning to document text.

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

        total = len(blocks)
        max_wc = max(b.word_count for b in blocks) if blocks else 1
        noise_removed = 0

        # ── Pass 1: Coarse pruning ────────────────────────────
        for i, block in enumerate(blocks):
            # Always keep first N
            if i < self._keep_first_n:
                block.kept = True
                continue

            # Always keep headings
            if self._keep_headings and block.block_type == "heading":
                block.kept = True
                continue

            # Always keep code
            if self._keep_code and block.block_type == "code":
                block.kept = True
                continue

            # Always keep tables
            if self._keep_tables and block.block_type == "table":
                block.kept = True
                continue

            # Keep very short blocks
            if block.word_count < self._min_word_count:
                block.kept = True
                continue

            # Remove nav
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
            if block.link_density > self._max_link_density:
                block.kept = False
                noise_removed += 1
                continue

            # Boilerplate detection
            if self._bp_detector and self._bp_detector.is_boilerplate(block.text):
                block.kept = False
                noise_removed += 1
                continue

            # Mark for scoring in pass 2
            block.kept = True

        # ── Pass 2: Fine scoring ──────────────────────────────
        if self._passes >= 2:
            for i, block in enumerate(blocks):
                if not block.kept:
                    continue

                # Skip protected blocks
                if i < self._keep_first_n:
                    continue
                if self._keep_headings and block.block_type == "heading":
                    continue
                if self._keep_code and block.block_type == "code":
                    continue
                if self._keep_tables and block.block_type == "table":
                    continue
                if block.word_count < self._min_word_count:
                    continue

                # Compute multi-factor score
                block.score = self._compute_advanced_score(
                    block, i, total, max_wc
                )

                if block.score < self._threshold:
                    block.kept = False
                    noise_removed += 1

        # ── Pass 3: Context preservation ──────────────────────
        if self._passes >= 3:
            # Keep blocks adjacent to high-scoring content
            for i, block in enumerate(blocks):
                if block.kept:
                    continue
                # Check neighbors
                for offset in (-1, 1):
                    neighbor_idx = i + offset
                    if 0 <= neighbor_idx < total:
                        neighbor = blocks[neighbor_idx]
                        if neighbor.kept and neighbor.score > self._threshold * 1.5:
                            block.kept = True
                            block.score = neighbor.score * 0.5
                            noise_removed -= 1
                            break

        # Build result
        kept_blocks = [b for b in blocks if b.kept]
        removed_blocks = [b for b in blocks if not b.kept]
        filtered_text = self._join_blocks(kept_blocks)

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

    def _compute_advanced_score(
        self,
        block: ContentBlock,
        index: int,
        total: int,
        max_word_count: int,
    ) -> float:
        """
        Compute advanced multi-factor score for a block.

        Factors:
            - Text density (word-to-char ratio, sentence structure)
            - Position (penalize edges of document)
            - Length (longer blocks more likely content)
            - Link density penalty
        """
        # Density score
        density = self._density_analyzer._compute_density(block.text)

        # Position score (penalize first 5% and last 10% of document)
        position_ratio = index / max(total - 1, 1)
        if position_ratio < 0.05:
            position_score = 0.3  # Likely header/nav
        elif position_ratio > 0.90:
            position_score = 0.4  # Likely footer
        elif position_ratio > 0.80:
            position_score = 0.7
        else:
            position_score = 1.0

        # Length score
        length_score = min(block.word_count / max(max_word_count, 1), 1.0)

        # Link penalty
        link_penalty = 1.0 - min(
            block.link_density / max(self._max_link_density, 0.01),
            1.0,
        )

        # Block type multiplier
        type_mult = {
            "heading": 1.5,
            "code": 1.3,
            "table": 1.2,
            "blockquote": 1.1,
            "paragraph": 1.0,
            "list_item": 1.0,
            "nav": 0.2,
            "footer": 0.1,
            "other": 0.8,
        }.get(block.block_type, 0.8)

        # Weighted combination
        raw = (
            self._density_weight * density
            + self._position_weight * position_score
            + self._length_weight * length_score
            + self._link_penalty_weight * link_penalty
        )

        return min(raw * type_mult, 1.0)

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "passes": self._passes,
            "density_weight": self._density_weight,
            "position_weight": self._position_weight,
            "length_weight": self._length_weight,
            "link_penalty_weight": self._link_penalty_weight,
            "boilerplate_detection": self._boilerplate_detection,
            "remove_nav": self._remove_nav,
            "remove_footer": self._remove_footer,
            "max_link_density": self._max_link_density,
            "keep_headings": self._keep_headings,
            "keep_code": self._keep_code,
            "keep_tables": self._keep_tables,
            "keep_first_n": self._keep_first_n,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdvancedPruningFilter:
        return cls(
            threshold=data.get("threshold", 0.35),
            passes=data.get("passes", 2),
            density_weight=data.get("density_weight", 0.4),
            position_weight=data.get("position_weight", 0.2),
            length_weight=data.get("length_weight", 0.2),
            link_penalty_weight=data.get("link_penalty_weight", 0.2),
            boilerplate_detection=data.get("boilerplate_detection", True),
            remove_nav=data.get("remove_nav", True),
            remove_footer=data.get("remove_footer", True),
            max_link_density=data.get("max_link_density", 0.5),
            keep_headings=data.get("keep_headings", True),
            keep_code=data.get("keep_code", True),
            keep_tables=data.get("keep_tables", True),
            keep_first_n=data.get("keep_first_n", 1),
            min_word_count=data.get("min_word_count", 10),
        )

    def __repr__(self) -> str:
        return (
            f"AdvancedPruningFilter(threshold={self._threshold}, "
            f"passes={self._passes}, "
            f"boilerplate={self._boilerplate_detection})"
        )


# ══════════════════════════════════════════════════════════════
# Extended Factory
# ══════════════════════════════════════════════════════════════

def create_pruning_filter(
    advanced: bool = False,
    **kwargs: Any,
) -> ContentFilter:
    """
    Create a pruning filter (standard or advanced).

    Args:
        advanced: Use AdvancedPruningFilter instead of standard.
        **kwargs: Filter arguments.

    Returns:
        ContentFilter instance.

    Example:
        >>> filter = create_pruning_filter(advanced=True, threshold=0.35)
        >>> filter = create_pruning_filter(advanced=False, threshold=0.4)
    """
    if advanced:
        return AdvancedPruningFilter(**kwargs)
    return PruningContentFilter(**kwargs)


# ══════════════════════════════════════════════════════════════
# Re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    # Base (re-exported)
    "ContentBlock",
    "ContentFilter",
    "ContentFilterResult",
    "PruningContentFilter",
    "create_content_filter",
    "create_content_filter_from_config",
    # Extended
    "AdvancedPruningFilter",
    "BoilerplateDetector",
    "ContentDensityAnalyzer",
    "DensityReport",
    "create_pruning_filter",
    # Constants
    "BOILERPLATE_PATTERNS",
    "BOILERPLATE_CONTAINER_PATTERNS",
]