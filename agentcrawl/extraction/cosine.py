"""
AgentCrawl — Cosine Similarity Extractor
============================================

Similarity-based extraction using TF-IDF cosine similarity to
cluster and extract structured data from repeated HTML patterns.

Ideal for extracting lists of similar items (products, articles,
listings) without needing explicit CSS selectors or LLM calls.

Algorithm:
    1. Parse HTML into candidate elements (divs, articles, lis, etc.)
    2. Compute TF-IDF vectors for each element's text content
    3. Compute pairwise cosine similarity
    4. Cluster elements above a similarity threshold
    5. Extract structured fields from the largest cluster
    6. Return a list of extracted items

Usage:
    from agentcrawl.extraction.cosine import CosineExtractor

    # Basic usage — auto-detect repeated patterns
    extractor = CosineExtractor(
        threshold=0.7,
        min_cluster_size=3,
    )
    result = await extractor.extract(html=html_content)
    print(result.data)  # List of similar items

    # With schema hint
    extractor = CosineExtractor(
        schema={"type": "object", "properties": {
            "title": {"type": "string"},
            "price": {"type": "string"},
        }},
        threshold=0.6,
    )
    result = await extractor.extract(html=product_listing_html)

    # With CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(extraction=CosineExtractor(threshold=0.7))
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionStrategy,
)

logger = logging.getLogger("agentcrawl.extraction.cosine")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class ElementInfo:
    """
    Information about an HTML element candidate.

    Attributes:
        tag: HTML tag name.
        text: Text content.
        html: Inner HTML.
        classes: CSS classes.
        depth: Nesting depth in the DOM.
        index: Position index among siblings.
        parent_tag: Parent element tag.
        fields: Extracted field key-value pairs.
        cluster_id: Assigned cluster ID (-1 = unassigned).
    """

    tag: str = ""
    text: str = ""
    html: str = ""
    classes: list[str] = field(default_factory=list)
    depth: int = 0
    index: int = 0
    parent_tag: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    cluster_id: int = -1


@dataclass
class Cluster:
    """
    A cluster of similar elements.

    Attributes:
        cluster_id: Unique cluster identifier.
        elements: Element indices in this cluster.
        avg_similarity: Average pairwise similarity.
        pattern: Detected field pattern.
        sample_text: Sample text from the first element.
    """

    cluster_id: int
    elements: list[int] = field(default_factory=list)
    avg_similarity: float = 0.0
    pattern: dict[str, str] = field(default_factory=dict)
    sample_text: str = ""

    @property
    def size(self) -> int:
        return len(self.elements)


# ══════════════════════════════════════════════════════════════
# TF-IDF Vectorizer
# ══════════════════════════════════════════════════════════════


class TFIDFVectorizer:
    """
    Simple TF-IDF vectorizer for text similarity computation.

    Computes term frequency-inverse document frequency vectors
    for a collection of text documents.
    """

    def __init__(self, min_df: int = 1, max_df_ratio: float = 0.95):
        self._min_df = min_df
        self._max_df_ratio = max_df_ratio
        self._vocabulary: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._fitted = False

    def fit(self, documents: list[str]) -> None:
        """
        Compute IDF values from a document collection.

        Args:
            documents: List of text documents.
        """
        n_docs = len(documents)
        if n_docs == 0:
            return

        # Tokenize all documents
        tokenized = [self._tokenize(doc) for doc in documents]

        # Document frequency
        df: Counter[str] = Counter()
        for tokens in tokenized:
            unique = set(tokens)
            for term in unique:
                df[term] += 1

        # Filter by min_df and max_df
        max_df = int(n_docs * self._max_df_ratio)
        self._vocabulary = {}
        self._idf = {}

        idx = 0
        for term, freq in df.items():
            if freq >= self._min_df and freq <= max_df:
                self._vocabulary[term] = idx
                self._idf[term] = math.log((n_docs + 1) / (freq + 1)) + 1
                idx += 1

        self._fitted = True

    def transform(self, documents: list[str]) -> list[dict[str, float]]:
        """
        Transform documents to TF-IDF vectors.

        Args:
            documents: List of text documents.

        Returns:
            List of TF-IDF vectors (sparse dicts).
        """
        vectors: list[dict[str, float]] = []

        for doc in documents:
            tokens = self._tokenize(doc)
            if not tokens:
                vectors.append({})
                continue

            tf = Counter(tokens)
            total = len(tokens)

            vector: dict[str, float] = {}
            for term, count in tf.items():
                if term in self._idf:
                    tf_val = count / total
                    vector[term] = tf_val * self._idf[term]

            vectors.append(vector)

        return vectors

    def fit_transform(self, documents: list[str]) -> list[dict[str, float]]:
        """Fit and transform in one step."""
        self.fit(documents)
        return self.transform(documents)

    @staticmethod
    def cosine_similarity(
        vec_a: dict[str, float],
        vec_b: dict[str, float],
    ) -> float:
        """
        Compute cosine similarity between two sparse vectors.

        Args:
            vec_a: First vector.
            vec_b: Second vector.

        Returns:
            Cosine similarity (0.0 to 1.0).
        """
        if not vec_a or not vec_b:
            return 0.0

        # Dot product
        common = set(vec_a.keys()) & set(vec_b.keys())
        dot = sum(vec_a[t] * vec_b[t] for t in common)

        # Magnitudes
        mag_a = math.sqrt(sum(v**2 for v in vec_a.values()))
        mag_b = math.sqrt(sum(v**2 for v in vec_b.values()))

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot / (mag_a * mag_b)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text into lowercase terms."""
        words = re.findall(r"\b\w+\b", text.lower())
        return [w for w in words if len(w) > 1]

    @property
    def vocabulary_size(self) -> int:
        return len(self._vocabulary)


# ══════════════════════════════════════════════════════════════
# HTML Element Parser
# ══════════════════════════════════════════════════════════════


class HTMLElementParser:
    """
    Parses HTML into candidate elements for similarity analysis.

    Extracts repeated structural elements (divs, articles, lis, etc.)
    that are likely to represent list items.
    """

    # Tags that commonly contain repeated items
    CANDIDATE_TAGS: frozenset[str] = frozenset(
        {
            "div",
            "article",
            "section",
            "li",
            "tr",
            "td",
            "span",
            "p",
            "a",
            "figure",
            "aside",
        }
    )

    # Minimum text length for a candidate
    MIN_TEXT_LENGTH: int = 10

    def parse(self, html: str) -> list[ElementInfo]:
        """
        Parse HTML and extract candidate elements.

        Args:
            html: Raw HTML string.

        Returns:
            List of ElementInfo objects.
        """
        try:
            from lxml import html as lxml_html
        except ImportError:
            logger.warning("lxml not available, using regex fallback")
            return self._parse_with_regex(html)

        try:
            tree = lxml_html.document_fromstring(html)
        except Exception as e:
            logger.debug("HTML parse error: %s", e)
            return []

        elements: list[ElementInfo] = []
        self._walk_tree(tree, elements, depth=0)

        return elements

    def _walk_tree(
        self,
        element: Any,
        results: list[ElementInfo],
        depth: int,
    ) -> None:
        """Recursively walk the element tree."""
        tag = element.tag if isinstance(element.tag, str) else ""

        if tag in self.CANDIDATE_TAGS:
            text = element.text_content().strip()

            if len(text) >= self.MIN_TEXT_LENGTH:
                # Get inner HTML
                try:
                    from lxml.html import tostring

                    inner_html = tostring(element, encoding="unicode", method="html")
                except Exception:
                    inner_html = text

                # Get classes
                classes = element.get("class", "").split()

                # Get parent tag
                parent = element.getparent()
                parent_tag = (
                    parent.tag if parent is not None and isinstance(parent.tag, str) else ""
                )

                # Get sibling index
                index = 0
                if parent is not None:
                    for i, sibling in enumerate(parent):
                        if sibling is element:
                            index = i
                            break

                # Extract fields from child elements
                fields = self._extract_fields(element)

                results.append(
                    ElementInfo(
                        tag=tag,
                        text=text,
                        html=inner_html,
                        classes=classes,
                        depth=depth,
                        index=index,
                        parent_tag=parent_tag,
                        fields=fields,
                    )
                )

        # Recurse into children
        for child in element:
            self._walk_tree(child, results, depth + 1)

    def _extract_fields(self, element: Any) -> dict[str, str]:
        """
        Extract key-value fields from an element's children.

        Looks for common patterns:
            - Heading + text pairs
            - Label + value pairs
            - Link text + href
            - Image alt + src
        """
        fields: dict[str, str] = {}

        # Extract headings
        for level in range(1, 7):
            heading = element.find(f".//h{level}")
            if heading is not None:
                fields[f"h{level}"] = heading.text_content().strip()
                break

        # Extract links
        link = element.find(".//a")
        if link is not None:
            fields["link_text"] = link.text_content().strip()
            href = link.get("href", "")
            if href:
                fields["link_href"] = href

        # Extract images
        img = element.find(".//img")
        if img is not None:
            alt = img.get("alt", "")
            src = img.get("src", "")
            if alt:
                fields["image_alt"] = alt
            if src:
                fields["image_src"] = src

        # Extract spans with class-based labels
        for span in element.iter("span"):
            cls = span.get("class", "")
            text = span.text_content().strip()
            if cls and text:
                # Use first class as field name
                field_name = cls.split()[0]
                if field_name not in fields:
                    fields[field_name] = text

        # Extract paragraphs
        p = element.find(".//p")
        if p is not None:
            fields["paragraph"] = p.text_content().strip()

        return fields

    def _parse_with_regex(self, html: str) -> list[ElementInfo]:
        """Fallback regex-based parsing when lxml is unavailable."""
        elements: list[ElementInfo] = []

        # Simple pattern for div/article/li blocks
        pattern = re.compile(
            r"<(div|article|li|section)\b[^>]*>(.*?)</\1>",
            re.DOTALL | re.IGNORECASE,
        )

        for match in pattern.finditer(html):
            tag = match.group(1).lower()
            content = match.group(2)

            # Strip HTML tags for text
            text = re.sub(r"<[^>]+>", " ", content).strip()
            text = re.sub(r"\s+", " ", text)

            if len(text) >= self.MIN_TEXT_LENGTH:
                # Extract classes
                class_match = re.search(r'class="([^"]*)"', match.group(0))
                classes = class_match.group(1).split() if class_match else []

                elements.append(
                    ElementInfo(
                        tag=tag,
                        text=text,
                        html=match.group(0),
                        classes=classes,
                    )
                )

        return elements


# ══════════════════════════════════════════════════════════════
# Cosine Extractor
# ══════════════════════════════════════════════════════════════


class CosineExtractor(ExtractionStrategy):
    """
    Similarity-based extraction using TF-IDF cosine similarity.

    Clusters similar HTML elements and extracts structured data
    from the largest cluster. Ideal for repeated item patterns
    (product listings, article cards, search results).

    Args:
        schema: Optional schema hint for field extraction.
        threshold: Cosine similarity threshold for clustering (0.0 - 1.0).
        min_cluster_size: Minimum elements for a valid cluster.
        max_elements: Maximum candidate elements to analyze.
        candidate_tags: HTML tags to consider as candidates.
        min_text_length: Minimum text length for candidates.
        top_k_clusters: Number of top clusters to return.
        include_html: Include inner HTML in extracted items.
        config: Extraction configuration.

    Example:
        >>> extractor = CosineExtractor(threshold=0.7, min_cluster_size=3)
        >>> result = await extractor.extract(html=product_listing_html)
        >>> for item in result.data:
        ...     print(item)
    """

    method_name = "cosine"

    def __init__(
        self,
        schema: Any = None,
        threshold: float = 0.7,
        min_cluster_size: int = 3,
        max_elements: int = 500,
        candidate_tags: list[str] | None = None,
        min_text_length: int = 10,
        top_k_clusters: int = 3,
        include_html: bool = False,
        config: ExtractionConfig | None = None,
        **kwargs: Any,
    ):
        super().__init__(schema=schema, config=config)

        self._threshold = threshold
        self._min_cluster_size = min_cluster_size
        self._max_elements = max_elements
        self._min_text_length = min_text_length
        self._top_k_clusters = top_k_clusters
        self._include_html = include_html

        if candidate_tags:
            HTMLElementParser.CANDIDATE_TAGS = frozenset(candidate_tags)
        HTMLElementParser.MIN_TEXT_LENGTH = min_text_length

        self._parser = HTMLElementParser()
        self._vectorizer = TFIDFVectorizer()

    # ──────────────────────────────────────────────────────────
    # Core Extraction
    # ──────────────────────────────────────────────────────────

    async def _extract(
        self,
        html: str = "",
        markdown: str = "",
        url: str = "",
        **kwargs: Any,
    ) -> Any:
        """
        Extract structured data using cosine similarity clustering.

        Args:
            html: HTML content.
            markdown: Markdown content (unused).
            url: Source URL.

        Returns:
            List of extracted items from the largest cluster.
        """
        if not html.strip():
            return []

        # Step 1: Parse HTML into candidate elements
        elements = self._parser.parse(html)

        if not elements:
            logger.debug("No candidate elements found")
            return []

        # Limit elements
        if len(elements) > self._max_elements:
            elements = elements[: self._max_elements]

        # Step 2: Compute TF-IDF vectors
        texts = [el.text for el in elements]
        vectors = self._vectorizer.fit_transform(texts)

        # Step 3: Compute pairwise similarity and cluster
        clusters = self._cluster_elements(elements, vectors)

        if not clusters:
            logger.debug("No clusters found above threshold %.2f", self._threshold)
            return []

        # Step 4: Sort clusters by size and similarity
        clusters.sort(key=lambda c: (c.size, c.avg_similarity), reverse=True)

        # Step 5: Extract data from top clusters
        results: list[dict[str, Any]] = []

        for cluster in clusters[: self._top_k_clusters]:
            if cluster.size < self._min_cluster_size:
                continue

            items = self._extract_cluster_data(elements, cluster)
            results.extend(items)

        return results

    # ──────────────────────────────────────────────────────────
    # Clustering
    # ──────────────────────────────────────────────────────────

    def _cluster_elements(
        self,
        elements: list[ElementInfo],
        vectors: list[dict[str, float]],
    ) -> list[Cluster]:
        """
        Cluster elements by cosine similarity.

        Uses a greedy agglomerative approach:
            1. Start with each element as its own cluster.
            2. Merge the most similar pair of clusters.
            3. Repeat until no pair exceeds the threshold.

        Args:
            elements: Candidate elements.
            vectors: TF-IDF vectors.

        Returns:
            List of Cluster objects.
        """
        n = len(elements)
        if n == 0:
            return []

        # Initialize: each element is its own cluster
        cluster_map: dict[int, list[int]] = {i: [i] for i in range(n)}
        element_cluster: dict[int, int] = {i: i for i in range(n)}

        # Compute similarity matrix (sparse — only above threshold)
        similar_pairs: list[tuple[int, int, float]] = []

        for i in range(n):
            for j in range(i + 1, n):
                sim = TFIDFVectorizer.cosine_similarity(vectors[i], vectors[j])
                if sim >= self._threshold:
                    similar_pairs.append((i, j, sim))

        # Sort by similarity descending
        similar_pairs.sort(key=lambda x: x[2], reverse=True)

        # Greedy merging
        for i, j, _sim in similar_pairs:
            ci = element_cluster[i]
            cj = element_cluster[j]

            if ci == cj:
                continue  # Already in same cluster

            # Merge smaller into larger
            if len(cluster_map[ci]) < len(cluster_map[cj]):
                ci, cj = cj, ci

            # Merge cj into ci
            for elem_idx in cluster_map[cj]:
                element_cluster[elem_idx] = ci
                cluster_map[ci].append(elem_idx)

            del cluster_map[cj]

        # Build Cluster objects
        clusters: list[Cluster] = []
        cluster_id = 0

        for _root_idx, member_indices in cluster_map.items():
            if len(member_indices) < self._min_cluster_size:
                continue

            # Compute average pairwise similarity
            sims: list[float] = []
            for a in range(len(member_indices)):
                for b in range(a + 1, len(member_indices)):
                    idx_a = member_indices[a]
                    idx_b = member_indices[b]
                    sim = TFIDFVectorizer.cosine_similarity(vectors[idx_a], vectors[idx_b])
                    sims.append(sim)

            avg_sim = sum(sims) / max(len(sims), 1)

            # Assign cluster IDs to elements
            for idx in member_indices:
                elements[idx].cluster_id = cluster_id

            cluster = Cluster(
                cluster_id=cluster_id,
                elements=member_indices,
                avg_similarity=avg_sim,
                sample_text=elements[member_indices[0]].text[:200],
            )

            # Detect field pattern
            cluster.pattern = self._detect_pattern(elements, member_indices)

            clusters.append(cluster)
            cluster_id += 1

        return clusters

    def _detect_pattern(
        self,
        elements: list[ElementInfo],
        indices: list[int],
    ) -> dict[str, str]:
        """
        Detect the common field pattern across cluster elements.

        Args:
            elements: All elements.
            indices: Indices of elements in the cluster.

        Returns:
            Dictionary of field_name → example_value.
        """
        field_counts: Counter[str] = Counter()
        field_examples: dict[str, str] = {}

        for idx in indices:
            el = elements[idx]
            for field_name, value in el.fields.items():
                field_counts[field_name] += 1
                if field_name not in field_examples and value:
                    field_examples[field_name] = value[:100]

        # Keep fields that appear in > 50% of cluster elements
        threshold = len(indices) * 0.5
        pattern: dict[str, str] = {}

        for field_name, count in field_counts.most_common():
            if count >= threshold:
                pattern[field_name] = field_examples.get(field_name, "")

        return pattern

    # ──────────────────────────────────────────────────────────
    # Data Extraction
    # ──────────────────────────────────────────────────────────

    def _extract_cluster_data(
        self,
        elements: list[ElementInfo],
        cluster: Cluster,
    ) -> list[dict[str, Any]]:
        """
        Extract structured data from a cluster's elements.

        Args:
            elements: All elements.
            cluster: Cluster to extract from.

        Returns:
            List of extracted item dictionaries.
        """
        items: list[dict[str, Any]] = []

        for idx in cluster.elements:
            el = elements[idx]
            item: dict[str, Any] = {}

            # Extract fields based on detected pattern
            if cluster.pattern:
                for field_name in cluster.pattern:
                    item[field_name] = el.fields.get(field_name, "")
            else:
                # Use all available fields
                item.update(el.fields)

            # Always include text content
            if not item:
                item["text"] = el.text

            # Include HTML if requested
            if self._include_html:
                item["_html"] = el.html

            # Include metadata
            item["_tag"] = el.tag
            item["_classes"] = el.classes
            item["_cluster_id"] = cluster.cluster_id
            item["_similarity"] = round(cluster.avg_similarity, 3)

            items.append(item)

        return items

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "threshold": self._threshold,
                "min_cluster_size": self._min_cluster_size,
                "max_elements": self._max_elements,
                "top_k_clusters": self._top_k_clusters,
                "include_html": self._include_html,
            }
        )
        return d

    def __repr__(self) -> str:
        return (
            f"CosineExtractor(threshold={self._threshold}, "
            f"min_cluster={self._min_cluster_size}, "
            f"schema={self._schema_name!r})"
        )
