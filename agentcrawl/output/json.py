"""
AgentCrawl — JSON Output Formatter
======================================

Formats crawl results as structured JSON output with configurable
field selection, pretty printing, JSONL support, and custom
serialization.

Features:
    - Full CrawlResult → JSON serialization
    - Configurable field inclusion/exclusion
    - Pretty print and compact modes
    - JSON Lines (JSONL) for batch output
    - Schema-based field selection
    - Nested object flattening
    - Custom value serializers
    - Streaming JSON output

Usage:
    from agentcrawl.output.json import JsonOutputFormatter

    formatter = JsonOutputFormatter()
    json_str = formatter.format(result)
    print(json_str)

    # Pretty print
    formatter = JsonOutputFormatter(pretty=True)
    json_str = formatter.format(result)

    # Specific fields only
    formatter = JsonOutputFormatter(
        fields=["url", "markdown", "metadata"],
    )
    json_str = formatter.format(result)

    # JSONL for batch results
    formatter = JsonOutputFormatter()
    jsonl = formatter.format_jsonl(results)

    # Flatten nested metadata
    formatter = JsonOutputFormatter(flatten=True)
    json_str = formatter.format(result)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

logger = logging.getLogger("agentcrawl.output.json")


# ══════════════════════════════════════════════════════════════
# JSON Output Formatter
# ══════════════════════════════════════════════════════════════

class JsonOutputFormatter:
    """
    Formats crawl results as structured JSON output.

    Args:
        pretty: Pretty-print with indentation.
        indent: Indentation level (for pretty print).
        fields: List of fields to include (None = all).
        exclude_fields: List of fields to exclude.
        flatten: Flatten nested dictionaries.
        flatten_separator: Separator for flattened keys.
        include_empty: Include fields with empty/null values.
        ensure_ascii: Escape non-ASCII characters.
        sort_keys: Sort dictionary keys alphabetically.
        custom_serializers: Dict of type → serializer function.
        max_string_length: Truncate strings longer than this (0 = no limit).

    Example:
        >>> formatter = JsonOutputFormatter(
        ...     pretty=True,
        ...     fields=["url", "markdown", "metadata"],
        ... )
        >>> json_str = formatter.format(crawl_result)
        >>> print(json_str)
    """

    # Default fields to include in output
    DEFAULT_FIELDS: list[str] = [
        "url",
        "success",
        "status_code",
        "markdown",
        "html",
        "text",
        "json",
        "metadata",
        "links",
        "citations",
        "chunks",
        "extracted_data",
        "screenshot",
        "error",
        "response_time_ms",
        "word_count",
        "token_count",
        "cached",
        "request_id",
    ]

    def __init__(
        self,
        pretty: bool = False,
        indent: int = 2,
        fields: list[str] | None = None,
        exclude_fields: list[str] | None = None,
        flatten: bool = False,
        flatten_separator: str = ".",
        include_empty: bool = True,
        ensure_ascii: bool = False,
        sort_keys: bool = False,
        custom_serializers: dict[type, Callable[[Any], Any]] | None = None,
        max_string_length: int = 0,
    ):
        self._pretty = pretty
        self._indent = indent
        self._fields = fields
        self._exclude_fields = set(exclude_fields or [])
        self._flatten = flatten
        self._flatten_separator = flatten_separator
        self._include_empty = include_empty
        self._ensure_ascii = ensure_ascii
        self._sort_keys = sort_keys
        self._max_string_length = max_string_length

        # Default custom serializers
        self._serializers: dict[type, Callable[[Any], Any]] = {
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat(),
            bytes: lambda v: v.decode("utf-8", errors="replace"),
            set: lambda v: list(v),
        }
        if custom_serializers:
            self._serializers.update(custom_serializers)

    # ──────────────────────────────────────────────────────────
    # Formatting
    # ──────────────────────────────────────────────────────────

    def format(self, result: Any) -> str:
        """
        Format a CrawlResult as a JSON string.

        Args:
            result: CrawlResult instance or dict.

        Returns:
            JSON string.
        """
        data = self._to_dict(result)
        data = self._filter_fields(data)

        if self._flatten:
            data = self._flatten_dict(data)

        if not self._include_empty:
            data = self._remove_empty(data)

        if self._max_string_length > 0:
            data = self._truncate_strings(data)

        return self._serialize(data)

    def format_dict(self, result: Any) -> dict[str, Any]:
        """
        Format a CrawlResult as a dictionary.

        Args:
            result: CrawlResult instance or dict.

        Returns:
            Filtered dictionary.
        """
        data = self._to_dict(result)
        data = self._filter_fields(data)

        if self._flatten:
            data = self._flatten_dict(data)

        if not self._include_empty:
            data = self._remove_empty(data)

        if self._max_string_length > 0:
            data = self._truncate_strings(data)

        return data

    def format_jsonl(self, results: list[Any]) -> str:
        """
        Format multiple results as JSON Lines (JSONL).

        Each result is serialized as a single JSON line.

        Args:
            results: List of CrawlResult instances.

        Returns:
            JSONL string (one JSON object per line).
        """
        lines: list[str] = []

        for result in results:
            data = self._to_dict(result)
            data = self._filter_fields(data)

            if self._flatten:
                data = self._flatten_dict(data)

            if not self._include_empty:
                data = self._remove_empty(data)

            if self._max_string_length > 0:
                data = self._truncate_strings(data)

            # Compact serialization for JSONL
            line = json.dumps(
                data,
                ensure_ascii=self._ensure_ascii,
                default=self._default_serializer,
                separators=(",", ":"),
            )
            lines.append(line)

        return "\n".join(lines)

    def format_stream(self, results: list[Any]) -> Any:
        """
        Generator that yields JSON strings one at a time.

        Useful for streaming large result sets.

        Args:
            results: List of CrawlResult instances.

        Yields:
            JSON string for each result.
        """
        for result in results:
            yield self.format(result)

    # ──────────────────────────────────────────────────────────
    # Conversion
    # ──────────────────────────────────────────────────────────

    def _to_dict(self, result: Any) -> dict[str, Any]:
        """Convert a result object to a dictionary."""
        if isinstance(result, dict):
            return dict(result)

        if hasattr(result, "to_dict"):
            return result.to_dict()

        if hasattr(result, "__dict__"):
            return {
                k: v for k, v in result.__dict__.items()
                if not k.startswith("_")
            }

        return {"value": str(result)}

    def _filter_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Filter fields based on include/exclude configuration."""
        # Apply include filter
        if self._fields is not None:
            data = {k: v for k, v in data.items() if k in self._fields}

        # Apply exclude filter
        if self._exclude_fields:
            data = {
                k: v for k, v in data.items()
                if k not in self._exclude_fields
            }

        return data

    def _flatten_dict(
        self,
        data: dict[str, Any],
        prefix: str = "",
    ) -> dict[str, Any]:
        """
        Flatten a nested dictionary.

        Example:
            {"metadata": {"title": "Hello"}}
            → {"metadata.title": "Hello"}
        """
        result: dict[str, Any] = {}

        for key, value in data.items():
            full_key = f"{prefix}{self._flatten_separator}{key}" if prefix else key

            if isinstance(value, dict) and value:
                nested = self._flatten_dict(value, full_key)
                result.update(nested)
            else:
                result[full_key] = value

        return result

    @staticmethod
    def _remove_empty(data: dict[str, Any]) -> dict[str, Any]:
        """Remove fields with empty/null values."""
        return {
            k: v for k, v in data.items()
            if v is not None and v != "" and v != [] and v != {}
        }

    def _truncate_strings(self, data: Any) -> Any:
        """Truncate strings longer than max_string_length."""
        if isinstance(data, str):
            if len(data) > self._max_string_length:
                return data[:self._max_string_length] + "..."
            return data

        if isinstance(data, dict):
            return {
                k: self._truncate_strings(v)
                for k, v in data.items()
            }

        if isinstance(data, list):
            return [self._truncate_strings(item) for item in data]

        return data

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def _serialize(self, data: Any) -> str:
        """Serialize data to JSON string."""
        kwargs: dict[str, Any] = {
            "ensure_ascii": self._ensure_ascii,
            "default": self._default_serializer,
            "sort_keys": self._sort_keys,
        }

        if self._pretty:
            kwargs["indent"] = self._indent
        else:
            kwargs["separators"] = (",", ":")

        return json.dumps(data, **kwargs)

    def _default_serializer(self, obj: Any) -> Any:
        """
        Default serializer for non-JSON-serializable objects.

        Args:
            obj: Object to serialize.

        Returns:
            JSON-serializable representation.
        """
        # Check custom serializers
        for type_, serializer in self._serializers.items():
            if isinstance(obj, type_):
                return serializer(obj)

        # Pydantic models
        if hasattr(obj, "model_dump"):
            return obj.model_dump()

        if hasattr(obj, "dict"):
            return obj.dict()

        # Dataclasses
        if hasattr(obj, "__dataclass_fields__"):
            import dataclasses
            return dataclasses.asdict(obj)

        # Objects with to_dict
        if hasattr(obj, "to_dict"):
            return obj.to_dict()

        # Fallback
        return str(obj)

    # ──────────────────────────────────────────────────────────
    # File Output
    # ──────────────────────────────────────────────────────────

    def save(self, result: Any, filepath: str) -> None:
        """
        Save a formatted result to a JSON file.

        Args:
            result: CrawlResult instance.
            filepath: Output file path.
        """
        json_str = self.format(result)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json_str)

    def save_jsonl(self, results: list[Any], filepath: str) -> None:
        """
        Save multiple results to a JSONL file.

        Args:
            results: List of CrawlResult instances.
            filepath: Output file path.
        """
        jsonl = self.format_jsonl(results)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(jsonl)

    def save_batch(
        self,
        results: list[Any],
        filepath: str,
        format: str = "json",
    ) -> None:
        """
        Save results in the specified format.

        Args:
            results: List of CrawlResult instances.
            filepath: Output file path.
            format: Output format ('json' or 'jsonl').
        """
        if format == "jsonl":
            self.save_jsonl(results, filepath)
        else:
            # Save as JSON array
            data = [self.format_dict(r) for r in results]
            json_str = self._serialize(data)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_str)

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "pretty": self._pretty,
            "indent": self._indent,
            "fields": self._fields,
            "exclude_fields": list(self._exclude_fields),
            "flatten": self._flatten,
            "include_empty": self._include_empty,
            "ensure_ascii": self._ensure_ascii,
            "sort_keys": self._sort_keys,
            "max_string_length": self._max_string_length,
        }

    def __repr__(self) -> str:
        return (
            f"JsonOutputFormatter(pretty={self._pretty}, "
            f"fields={self._fields or 'all'}, "
            f"flatten={self._flatten})"
        )
