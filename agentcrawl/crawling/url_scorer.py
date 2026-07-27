"""
AgentCrawl — URL Scorer (Extended)
======================================

Extended URL scoring with multi-factor analysis, configurable
weights, content-based signals, and scoring presets.

This module extends the base URLScorer from crawling/base.py with:

    - Multi-factor scoring (structure, keywords, depth, link text)
    - Configurable weight system
    - Content-based scoring (link text, surrounding context)
    - URL structure analysis (segment count, slug detection)
    - Freshness scoring (from sitemap lastmod)
    - Domain authority estimation
    - Scoring presets (docs, blog, api, ecommerce)
    - Batch scoring with caching

Usage:
    from agentcrawl.crawling.url_scorer import (
        URLScorer,              # Re-exported from base
        AdvancedURLScorer,      # Multi-factor scoring
        ScoringWeights,         # Weight configuration
        ScoringPreset,          # Pre-built scoring configs
    )

    # Standard scoring
    scorer = URLScorer()
    score = scorer.score("https://example.com/docs/guide")

    # Advanced multi-factor scoring
    scorer = AdvancedURLScorer(
        weights=ScoringWeights(
            keyword_weight=0.3,
            structure_weight=0.2,
            depth_weight=0.15,
            link_text_weight=0.2,
            freshness_weight=0.15,
        ),
    )
    score = scorer.score(
        url="https://example.com/docs/getting-started",
        depth=1,
        link_text="Getting Started Guide",
        lastmod="2025-01-15",
    )

    # Presets
    scorer = ScoringPreset.docs()
    scorer = ScoringPreset.blog()
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

# Re-export base URLScorer
from agentcrawl.crawling.base import URLScorer

logger = logging.getLogger("agentcrawl.crawling.url_scorer")


# ══════════════════════════════════════════════════════════════
# Scoring Weights
# ══════════════════════════════════════════════════════════════

@dataclass
class ScoringWeights:
    """
    Configurable weights for multi-factor URL scoring.

    All weights should sum to approximately 1.0 for normalized output.

    Attributes:
        keyword_weight: Weight for content/noise keyword matching.
        structure_weight: Weight for URL structure analysis.
        depth_weight: Weight for link depth penalty.
        link_text_weight: Weight for anchor text relevance.
        freshness_weight: Weight for content freshness (lastmod).
        domain_weight: Weight for domain authority estimation.
        query_penalty_weight: Weight for query string penalty.
        extension_weight: Weight for file extension signals.
    """
    keyword_weight: float = 0.30
    structure_weight: float = 0.20
    depth_weight: float = 0.15
    link_text_weight: float = 0.20
    freshness_weight: float = 0.10
    domain_weight: float = 0.05
    query_penalty_weight: float = 0.05
    extension_weight: float = 0.05

    def validate(self) -> list[str]:
        """Validate weights and return warnings."""
        warnings: list[str] = []
        total = (
            self.keyword_weight + self.structure_weight + self.depth_weight
            + self.link_text_weight + self.freshness_weight + self.domain_weight
            + self.query_penalty_weight + self.extension_weight
        )
        if abs(total - 1.0) > 0.1:
            warnings.append(
                f"Weights sum to {total:.2f}, expected ~1.0"
            )
        return warnings

    def to_dict(self) -> dict[str, float]:
        return {
            "keyword": self.keyword_weight,
            "structure": self.structure_weight,
            "depth": self.depth_weight,
            "link_text": self.link_text_weight,
            "freshness": self.freshness_weight,
            "domain": self.domain_weight,
            "query_penalty": self.query_penalty_weight,
            "extension": self.extension_weight,
        }


# ══════════════════════════════════════════════════════════════
# Score Breakdown
# ══════════════════════════════════════════════════════════════

@dataclass
class ScoreBreakdown:
    """
    Detailed breakdown of a URL score.

    Attributes:
        url: The scored URL.
        total_score: Final weighted score (0.0 - 1.0).
        keyword_score: Content keyword matching score.
        structure_score: URL structure analysis score.
        depth_score: Depth-based score.
        link_text_score: Anchor text relevance score.
        freshness_score: Content freshness score.
        domain_score: Domain authority score.
        query_penalty: Query string penalty.
        extension_score: File extension score.
        factors: Human-readable factor descriptions.
    """
    url: str = ""
    total_score: float = 0.0
    keyword_score: float = 0.0
    structure_score: float = 0.0
    depth_score: float = 0.0
    link_text_score: float = 0.0
    freshness_score: float = 0.0
    domain_score: float = 0.0
    query_penalty: float = 0.0
    extension_score: float = 0.0
    factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "total_score": round(self.total_score, 4),
            "breakdown": {
                "keyword": round(self.keyword_score, 4),
                "structure": round(self.structure_score, 4),
                "depth": round(self.depth_score, 4),
                "link_text": round(self.link_text_score, 4),
                "freshness": round(self.freshness_score, 4),
                "domain": round(self.domain_score, 4),
                "query_penalty": round(self.query_penalty, 4),
                "extension": round(self.extension_score, 4),
            },
            "factors": self.factors,
        }


# ══════════════════════════════════════════════════════════════
# Advanced URL Scorer
# ══════════════════════════════════════════════════════════════

class AdvancedURLScorer(URLScorer):
    """
    Multi-factor URL scorer with configurable weights.

    Computes a composite score from multiple signals:
        - Keyword matching (content vs noise indicators)
        - URL structure (segment count, slug detection, patterns)
        - Link depth (deeper = lower score)
        - Anchor text relevance
        - Content freshness (from lastmod dates)
        - Domain authority estimation
        - Query string penalty
        - File extension signals

    Args:
        weights: ScoringWeights configuration.
        content_keywords: Keywords indicating valuable content.
        noise_keywords: Keywords indicating noise/boilerplate.
        max_depth: Maximum expected depth (for normalization).
        freshness_half_life_days: Days for freshness score to halve.
        **kwargs: Passed to base URLScorer.

    Example:
        >>> scorer = AdvancedURLScorer()
        >>> score = scorer.score(
        ...     "https://example.com/docs/getting-started",
        ...     depth=1,
        ...     link_text="Getting Started Guide",
        ... )
        >>> print(f"Score: {score:.2f}")

        >>> # With breakdown
        >>> breakdown = scorer.score_with_breakdown(
        ...     "https://example.com/docs/guide",
        ...     depth=2,
        ...     link_text="Complete Guide",
        ... )
        >>> print(breakdown.to_dict())
    """

    # Content value keywords
    CONTENT_KEYWORDS: list[str] = [
        "guide", "tutorial", "docs", "documentation", "reference",
        "api", "manual", "help", "faq", "wiki", "blog", "post",
        "article", "news", "learn", "how-to", "howto", "getting-started",
        "quickstart", "overview", "introduction", "setup", "install",
        "installation", "configuration", "config", "examples", "sample",
        "demo", "walkthrough", "primer", "handbook", "spec",
        "specification", "changelog", "release", "migration",
        "troubleshooting", "debug", "best-practices", "patterns",
    ]

    # Noise keywords
    NOISE_KEYWORDS: list[str] = [
        "login", "signin", "signup", "register", "auth", "oauth",
        "cart", "checkout", "payment", "billing", "pricing", "subscribe",
        "search", "filter", "sort", "tag", "category", "archive",
        "page", "feed", "rss", "atom", "sitemap", "robots",
        "about", "contact", "privacy", "terms", "legal", "cookie",
        "careers", "jobs", "press", "media", "partners",
        "admin", "dashboard", "settings", "profile", "account",
        "wp-admin", "wp-login", "wp-content", "wp-includes",
    ]

    # Valuable file extensions
    CONTENT_EXTENSIONS: set[str] = {
        ".html", ".htm", ".xhtml", ".md", ".rst",
    }

    # Noise file extensions
    NOISE_EXTENSIONS: set[str] = {
        ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
        ".zip", ".tar", ".gz", ".mp3", ".mp4", ".avi",
        ".xml", ".json", ".csv", ".txt", ".rss",
    }

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        content_keywords: list[str] | None = None,
        noise_keywords: list[str] | None = None,
        max_depth: int = 10,
        freshness_half_life_days: int = 90,
        **kwargs: Any,
    ):
        super().__init__(
            content_keywords=content_keywords or self.CONTENT_KEYWORDS,
            noise_keywords=noise_keywords or self.NOISE_KEYWORDS,
            **kwargs,
        )

        self._weights = weights or ScoringWeights()
        self._max_depth = max_depth
        self._freshness_half_life = freshness_half_life_days

        # Pre-compile keyword sets
        self._content_set = {kw.lower() for kw in (content_keywords or self.CONTENT_KEYWORDS)}
        self._noise_set = {kw.lower() for kw in (noise_keywords or self.NOISE_KEYWORDS)}

        # Score cache
        self._cache: dict[str, float] = {}

    # ──────────────────────────────────────────────────────────
    # Scoring API
    # ──────────────────────────────────────────────────────────

    def score(
        self,
        url: str,
        depth: int = 0,
        link_text: str = "",
        lastmod: str = "",
        context: str = "",
    ) -> float:
        """
        Compute a composite score for a URL.

        Args:
            url: URL to score.
            depth: Link depth from start URL.
            link_text: Anchor text of the link.
            lastmod: Last modification date (ISO 8601).
            context: Surrounding text context.

        Returns:
            Score between 0.0 and 1.0.
        """
        breakdown = self.score_with_breakdown(
            url=url,
            depth=depth,
            link_text=link_text,
            lastmod=lastmod,
            context=context,
        )
        return breakdown.total_score

    def score_with_breakdown(
        self,
        url: str,
        depth: int = 0,
        link_text: str = "",
        lastmod: str = "",
        context: str = "",
    ) -> ScoreBreakdown:
        """
        Compute a score with detailed factor breakdown.

        Args:
            url: URL to score.
            depth: Link depth.
            link_text: Anchor text.
            lastmod: Last modification date.
            context: Surrounding context text.

        Returns:
            ScoreBreakdown with all factor scores.
        """
        w = self._weights
        factors: list[str] = []

        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            segments = [s for s in path.split("/") if s]
        except Exception:
            return ScoreBreakdown(url=url, total_score=0.0)

        # 1. Keyword score
        keyword_score = self._score_keywords(path, segments)
        if keyword_score > 0.6:
            factors.append("content keywords detected")
        elif keyword_score < 0.3:
            factors.append("noise keywords detected")

        # 2. Structure score
        structure_score = self._score_structure(path, segments, parsed)
        if structure_score > 0.7:
            factors.append("clean URL structure")

        # 3. Depth score
        depth_score = self._score_depth(depth)
        if depth > 4:
            factors.append(f"deep link (depth={depth})")

        # 4. Link text score
        link_text_score = self._score_link_text(link_text, context)
        if link_text_score > 0.7:
            factors.append("descriptive link text")

        # 5. Freshness score
        freshness_score = self._score_freshness(lastmod)
        if freshness_score > 0.8:
            factors.append("recently updated")

        # 6. Domain score
        domain_score = self._score_domain(parsed)

        # 7. Query penalty
        query_penalty = self._score_query_penalty(parsed)
        if query_penalty > 0:
            factors.append("query string penalty")

        # 8. Extension score
        extension_score = self._score_extension(path)

        # Weighted combination
        total = (
            w.keyword_weight * keyword_score
            + w.structure_weight * structure_score
            + w.depth_weight * depth_score
            + w.link_text_weight * link_text_score
            + w.freshness_weight * freshness_score
            + w.domain_weight * domain_score
            - w.query_penalty_weight * query_penalty
            + w.extension_weight * extension_score
        )

        # Clamp to [0, 1]
        total = max(0.0, min(1.0, total))

        return ScoreBreakdown(
            url=url,
            total_score=total,
            keyword_score=keyword_score,
            structure_score=structure_score,
            depth_score=depth_score,
            link_text_score=link_text_score,
            freshness_score=freshness_score,
            domain_score=domain_score,
            query_penalty=query_penalty,
            extension_score=extension_score,
            factors=factors,
        )

    def score_batch(
        self,
        urls: list[tuple[str, int, str]],
    ) -> list[float]:
        """
        Score multiple URLs with caching.

        Args:
            urls: List of (url, depth, link_text) tuples.

        Returns:
            List of scores.
        """
        results: list[float] = []
        for url, depth, link_text in urls:
            cache_key = f"{url}|{depth}|{link_text}"
            if cache_key in self._cache:
                results.append(self._cache[cache_key])
            else:
                score = self.score(url, depth, link_text)
                self._cache[cache_key] = score
                results.append(score)
        return results

    def clear_cache(self) -> None:
        """Clear the score cache."""
        self._cache.clear()

    # ──────────────────────────────────────────────────────────
    # Factor Scorers
    # ──────────────────────────────────────────────────────────

    def _score_keywords(self, path: str, segments: list[str]) -> float:
        """Score based on content/noise keyword matching."""
        score = 0.5  # Neutral

        # Content keywords
        content_hits = 0
        for kw in self._content_set:
            if kw in path:
                content_hits += 1

        if content_hits > 0:
            score += min(0.3, 0.1 * content_hits)

        # Noise keywords
        noise_hits = 0
        for kw in self._noise_set:
            if kw in path:
                noise_hits += 1

        if noise_hits > 0:
            score -= min(0.4, 0.15 * noise_hits)

        return max(0.0, min(1.0, score))

    def _score_structure(
        self,
        path: str,
        segments: list[str],
        parsed: Any,
    ) -> float:
        """Score based on URL structure analysis."""
        score = 0.5

        if not segments:
            return 0.3  # Root path — neutral

        # Slug-like segments (long, hyphenated) suggest content
        slug_count = sum(
            1 for seg in segments
            if len(seg) > 12 and "-" in seg and re.match(r"^[a-z0-9-]+$", seg, re.I)
        )
        if slug_count > 0:
            score += min(0.2, 0.1 * slug_count)

        # Numeric-only segments suggest pagination/IDs
        numeric_count = sum(1 for seg in segments if seg.isdigit())
        if numeric_count > 0:
            score -= min(0.2, 0.05 * numeric_count)

        # Very deep paths are less valuable
        if len(segments) > 6:
            score -= 0.1

        # Clean paths (no special chars) are better
        if re.match(r"^[/a-z0-9-]+$", path, re.I):
            score += 0.1

        # Date-based paths suggest articles
        if re.search(r"/\d{4}/\d{2}/", path):
            score += 0.1

        return max(0.0, min(1.0, score))

    def _score_depth(self, depth: int) -> float:
        """Score based on link depth (shallower = better)."""
        if depth <= 0:
            return 1.0
        if depth >= self._max_depth:
            return 0.0

        # Linear decay
        return 1.0 - (depth / self._max_depth)

    def _score_link_text(self, link_text: str, context: str = "") -> float:
        """Score based on anchor text and context relevance."""
        if not link_text:
            return 0.3  # No text — neutral-low

        score = 0.4
        text_lower = link_text.lower()

        # Content keywords in link text
        for kw in self._content_set:
            if kw in text_lower:
                score += 0.15
                break

        # Noise keywords in link text
        for kw in self._noise_set:
            if kw in text_lower:
                score -= 0.15
                break

        # Longer, descriptive text is better
        word_count = len(link_text.split())
        if word_count >= 3:
            score += 0.1
        if word_count >= 5:
            score += 0.05

        # Very short text (e.g., "here", "click") is low value
        if word_count == 1 and len(link_text) < 6:
            score -= 0.1

        # Context bonus
        if context:
            context_lower = context.lower()
            for kw in self._content_set:
                if kw in context_lower:
                    score += 0.05
                    break

        return max(0.0, min(1.0, score))

    def _score_freshness(self, lastmod: str) -> float:
        """Score based on content freshness."""
        if not lastmod:
            return 0.5  # Unknown — neutral

        try:
            # Parse ISO 8601 date
            if "T" in lastmod:
                dt = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(lastmod[:10], "%Y-%m-%d")
                dt = dt.replace(tzinfo=timezone.utc)

            age_days = (datetime.now(timezone.utc) - dt).days

            if age_days < 0:
                return 0.5  # Future date — suspicious

            # Exponential decay with half-life
            decay = math.exp(-0.693 * age_days / self._freshness_half_life)
            return max(0.0, min(1.0, decay))

        except (ValueError, TypeError):
            return 0.5

    def _score_domain(self, parsed: Any) -> float:
        """Estimate domain authority score."""
        hostname = (parsed.hostname or "").lower()

        if not hostname:
            return 0.0

        # Remove www
        if hostname.startswith("www."):
            hostname = hostname[4:]

        score = 0.5

        # Known high-authority domains
        high_authority = {
            "github.com", "stackoverflow.com", "wikipedia.org",
            "developer.mozilla.org", "docs.python.org",
            "docs.oracle.com", "learn.microsoft.com",
            "cloud.google.com", "aws.amazon.com",
        }

        if hostname in high_authority:
            score += 0.3

        # Subdomain penalty (docs.*, api.* are good; blog.*, news.* are neutral)
        parts = hostname.split(".")
        if len(parts) > 2:
            subdomain = parts[0]
            if subdomain in ("docs", "api", "developer", "dev"):
                score += 0.1
            elif subdomain in ("blog", "news", "media"):
                score -= 0.05

        # TLD signals
        tld = parts[-1] if parts else ""
        if tld in ("com", "org", "net", "io", "dev"):
            score += 0.05
        elif tld in ("xyz", "top", "click", "buzz"):
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _score_query_penalty(self, parsed: Any) -> float:
        """Penalty for query strings (often dynamic/filter pages)."""
        if not parsed.query:
            return 0.0

        params = parse_qs(parsed.query)
        param_count = len(params)

        # Small penalty for any query string
        penalty = 0.3

        # Additional penalty for many parameters
        if param_count > 3:
            penalty += 0.2

        # Penalty for tracking/session parameters
        tracking_params = {"utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid", "ref", "session"}
        if any(p.lower() in tracking_params for p in params):
            penalty += 0.2

        # Penalty for pagination parameters
        pagination_params = {"page", "p", "pg", "offset", "start", "limit"}
        if any(p.lower() in pagination_params for p in params):
            penalty += 0.1

        return min(1.0, penalty)

    def _score_extension(self, path: str) -> float:
        """Score based on file extension."""
        path_lower = path.lower()

        # Check content extensions
        for ext in self.CONTENT_EXTENSIONS:
            if path_lower.endswith(ext):
                return 0.8

        # No extension (clean URL) — good
        if "." not in path_lower.split("/")[-1]:
            return 0.7

        # Check noise extensions
        for ext in self.NOISE_EXTENSIONS:
            if path_lower.endswith(ext):
                return 0.0

        # Unknown extension
        return 0.3

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    @property
    def weights(self) -> ScoringWeights:
        """Current scoring weights."""
        return self._weights

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self._weights.to_dict(),
            "max_depth": self._max_depth,
            "freshness_half_life_days": self._freshness_half_life,
            "content_keywords": len(self._content_set),
            "noise_keywords": len(self._noise_set),
            "cache_size": len(self._cache),
        }

    def __repr__(self) -> str:
        return (
            f"AdvancedURLScorer(content_kw={len(self._content_set)}, "
            f"noise_kw={len(self._noise_set)}, "
            f"cache={len(self._cache)})"
        )


# ══════════════════════════════════════════════════════════════
# Scoring Presets
# ══════════════════════════════════════════════════════════════

class ScoringPreset:
    """
    Pre-built scoring configurations for common use cases.

    Example:
        >>> scorer = ScoringPreset.docs()
        >>> scorer = ScoringPreset.blog()
    """

    @classmethod
    def docs(cls) -> AdvancedURLScorer:
        """Optimized for documentation sites."""
        return AdvancedURLScorer(
            weights=ScoringWeights(
                keyword_weight=0.35,
                structure_weight=0.25,
                depth_weight=0.15,
                link_text_weight=0.15,
                freshness_weight=0.05,
                domain_weight=0.05,
                query_penalty_weight=0.05,
                extension_weight=0.05,
            ),
            content_keywords=[
                "docs", "documentation", "guide", "tutorial", "reference",
                "api", "manual", "help", "faq", "wiki", "setup", "install",
                "configuration", "getting-started", "quickstart", "overview",
                "examples", "spec", "specification", "handbook",
            ],
            noise_keywords=[
                "login", "signup", "cart", "checkout", "pricing",
                "search", "tag", "category", "blog", "news",
                "about", "contact", "careers", "press",
            ],
        )

    @classmethod
    def blog(cls) -> AdvancedURLScorer:
        """Optimized for blog/article content."""
        return AdvancedURLScorer(
            weights=ScoringWeights(
                keyword_weight=0.25,
                structure_weight=0.20,
                depth_weight=0.10,
                link_text_weight=0.25,
                freshness_weight=0.15,
                domain_weight=0.05,
                query_penalty_weight=0.05,
                extension_weight=0.05,
            ),
            content_keywords=[
                "blog", "post", "article", "news", "story",
                "opinion", "review", "analysis", "interview",
            ],
            noise_keywords=[
                "category", "tag", "archive", "page", "author",
                "login", "signup", "search", "feed", "rss",
            ],
        )

    @classmethod
    def api(cls) -> AdvancedURLScorer:
        """Optimized for API documentation."""
        return AdvancedURLScorer(
            weights=ScoringWeights(
                keyword_weight=0.35,
                structure_weight=0.30,
                depth_weight=0.10,
                link_text_weight=0.15,
                freshness_weight=0.05,
                domain_weight=0.05,
                query_penalty_weight=0.05,
                extension_weight=0.05,
            ),
            content_keywords=[
                "api", "endpoint", "reference", "docs", "documentation",
                "guide", "sdk", "client", "webhook", "authentication",
                "rate-limit", "error", "response", "request",
            ],
            noise_keywords=[
                "blog", "news", "pricing", "login", "signup",
                "status", "changelog", "about", "contact",
            ],
        )

    @classmethod
    def ecommerce(cls) -> AdvancedURLScorer:
        """Optimized for e-commerce product pages."""
        return AdvancedURLScorer(
            weights=ScoringWeights(
                keyword_weight=0.30,
                structure_weight=0.25,
                depth_weight=0.15,
                link_text_weight=0.15,
                freshness_weight=0.10,
                domain_weight=0.05,
                query_penalty_weight=0.05,
                extension_weight=0.05,
            ),
            content_keywords=[
                "product", "item", "shop", "buy", "detail",
                "review", "specification", "description",
            ],
            noise_keywords=[
                "cart", "checkout", "payment", "account", "login",
                "search", "filter", "sort", "wishlist", "compare",
            ],
        )

    @classmethod
    def balanced(cls) -> AdvancedURLScorer:
        """Balanced scoring for general use."""
        return AdvancedURLScorer()

    @classmethod
    def aggressive(cls) -> AdvancedURLScorer:
        """Aggressive scoring — strongly penalizes noise."""
        return AdvancedURLScorer(
            weights=ScoringWeights(
                keyword_weight=0.40,
                structure_weight=0.20,
                depth_weight=0.15,
                link_text_weight=0.10,
                freshness_weight=0.05,
                domain_weight=0.05,
                query_penalty_weight=0.10,
                extension_weight=0.05,
            ),
        )


# ══════════════════════════════════════════════════════════════
# Re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    "URLScorer",
    "AdvancedURLScorer",
    "ScoringWeights",
    "ScoreBreakdown",
    "ScoringPreset",
]