"""
AgentCrawl — Extraction Strategy Base
=========================================

Abstract base class and shared utilities for all extraction
strategies (LLM, CSS, XPath, Cosine, Regex). Defines the
interface for structured data extraction from web content.

Architecture:
    ExtractionStrategy (ABC)
    ├── LLMExtractor        — LLM-powered extraction (any schema)
    ├── JsonCssExtractor    — CSS selector-based extraction
    ├── JsonXPathExtractor  — XPath-based extraction
    ├── CosineExtractor     — Similarity-based extraction
    └── RegexExtractor      — Regex pattern extraction

Usage:
    from agentcrawl.extraction.base import (
        ExtractionStrategy,
        ExtractionResult,
        ExtractionConfig,
    )

    # Custom strategy
    class MyExtractor(ExtractionStrategy):
        async def _extract(self, html, markdown, url):
            # ... custom logic ...
            return {"title": "...", "price": 99.99}

    # Use with CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(extraction=MyExtractor(schema=MyModel))
    result = await engine.scrape("https://example.com", config)
    print(result.extracted_data)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("agentcrawl.extraction")


# ══════════════════════════════════════════════════════════════
# Types & Enums
# ══════════════════════════════════════════════════════════════

class ExtractionMethod(str, Enum):
    """Available extraction methods."""
    LLM = "llm"
    CSS = "css"
    XPATH = "xpath"
    COSINE = "cosine"
    REGEX = "regex"


class ExtractionStatus(str, Enum):
    """Status of an extraction operation."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    VALIDATION_ERROR = "validation_error"
    TIMEOUT = "timeout"


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class ExtractionConfig:
    """
    Configuration for an extraction operation.

    Attributes:
        method: Extraction method to use.
        schema: Pydantic model class or JSON schema dict.
        prompt: Custom prompt for LLM extraction.
        timeout: Extraction timeout in seconds.
        max_retries: Maximum retry attempts.
        retry_delay: Delay between retries in seconds.
        validate: Whether to validate output against schema.
        strict: Whether to raise on validation errors.
        temperature: LLM temperature (for LLM extraction).
        max_tokens: LLM max tokens (for LLM extraction).
        base_url: Base URL for resolving relative selectors.
        extra: Additional method-specific parameters.
    """
    method: ExtractionMethod | str = ExtractionMethod.LLM
    schema: Any = None
    prompt: str | None = None
    timeout: int = 60
    max_retries: int = 2
    retry_delay: float = 1.0
    validate: bool = True
    strict: bool = False
    temperature: float = 0.1
    max_tokens: int = 4096
    base_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.method, str):
            try:
                self.method = ExtractionMethod(self.method)
            except ValueError:
                self.method = ExtractionMethod.LLM

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value if isinstance(self.method, ExtractionMethod) else self.method,
            "schema": type(self.schema).__name__ if self.schema else None,
            "prompt": self.prompt[:100] if self.prompt else None,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "validate": self.validate,
            "strict": self.strict,
        }


@dataclass
class ExtractionResult:
    """
    Result of a structured extraction operation.

    Attributes:
        data: Extracted data (dict, list, or Pydantic model).
        status: Extraction status.
        method: Method used for extraction.
        schema_name: Name of the schema used.
        raw_output: Raw output from the extractor (before parsing).
        validation_errors: Validation error messages.
        duration_ms: Extraction time in milliseconds.
        token_usage: Token usage (for LLM extraction).
        confidence: Extraction confidence score (0.0 - 1.0).
        error: Error message (if failed).
        metadata: Additional metadata.
    """
    data: Any = None
    status: ExtractionStatus = ExtractionStatus.SUCCESS
    method: str = ""
    schema_name: str = ""
    raw_output: str = ""
    validation_errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    confidence: float = 1.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Whether extraction was successful."""
        return self.status == ExtractionStatus.SUCCESS

    @property
    def is_valid(self) -> bool:
        """Whether the extracted data passed validation."""
        return self.status in (ExtractionStatus.SUCCESS, ExtractionStatus.PARTIAL)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "method": self.method,
            "schema_name": self.schema_name,
            "duration_ms": round(self.duration_ms, 2),
            "confidence": round(self.confidence, 3),
        }

        if self.data is not None:
            if hasattr(self.data, "model_dump"):
                result["data"] = self.data.model_dump()
            elif hasattr(self.data, "dict"):
                result["data"] = self.data.dict()
            else:
                result["data"] = self.data

        if self.validation_errors:
            result["validation_errors"] = self.validation_errors

        if self.token_usage:
            result["token_usage"] = self.token_usage

        if self.error:
            result["error"] = self.error

        return result

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def __repr__(self) -> str:
        status_icon = "✓" if self.success else "✗"
        return (
            f"ExtractionResult({status_icon} {self.status.value}, "
            f"method={self.method!r}, "
            f"time={self.duration_ms:.0f}ms"
            f"{f', errors={len(self.validation_errors)}' if self.validation_errors else ''})"
        )


# ══════════════════════════════════════════════════════════════
# Schema Utilities
# ══════════════════════════════════════════════════════════════

class SchemaResolver:
    """
    Resolves and validates extraction schemas.

    Supports:
        - Pydantic BaseModel classes
        - JSON Schema dictionaries
        - TypedDict classes
        - Plain dictionaries (treated as JSON schema)

    Example:
        >>> resolver = SchemaResolver()
        >>> json_schema = resolver.to_json_schema(MyPydanticModel)
        >>> is_valid = resolver.validate_data(data, MyPydanticModel)
    """

    @staticmethod
    def to_json_schema(schema: Any) -> dict[str, Any]:
        """
        Convert a schema to JSON Schema format.

        Args:
            schema: Pydantic model, JSON schema dict, or TypedDict.

        Returns:
            JSON Schema dictionary.
        """
        if schema is None:
            return {}

        # Already a dict — assume JSON schema
        if isinstance(schema, dict):
            return schema

        # Pydantic model
        if hasattr(schema, "model_json_schema"):
            return schema.model_json_schema()

        if hasattr(schema, "schema"):
            return schema.schema()

        # TypedDict
        if hasattr(schema, "__annotations__"):
            properties = {}
            required = []
            for name, type_hint in schema.__annotations__.items():
                properties[name] = {"type": SchemaResolver._type_to_json(type_hint)}
                required.append(name)
            return {
                "type": "object",
                "properties": properties,
                "required": required,
            }

        return {}

    @staticmethod
    def _type_to_json(type_hint: Any) -> str:
        """Convert a Python type hint to JSON Schema type."""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        return type_map.get(type_hint, "string")

    @staticmethod
    def validate_data(data: Any, schema: Any) -> tuple[bool, list[str]]:
        """
        Validate extracted data against a schema.

        Args:
            data: Extracted data (dict or Pydantic model).
            schema: Schema to validate against.

        Returns:
            Tuple of (is_valid, error_messages).
        """
        if schema is None:
            return True, []

        errors: list[str] = []

        # Pydantic validation
        if hasattr(schema, "model_validate"):
            try:
                if isinstance(data, dict):
                    schema.model_validate(data)
                return True, []
            except Exception as e:
                errors.append(str(e))
                return False, errors

        if hasattr(schema, "parse_obj"):
            try:
                if isinstance(data, dict):
                    schema.parse_obj(data)
                return True, []
            except Exception as e:
                errors.append(str(e))
                return False, errors

        # JSON Schema validation (basic)
        if isinstance(schema, dict) and isinstance(data, dict):
            required = schema.get("required", [])
            properties = schema.get("properties", {})

            for field_name in required:
                if field_name not in data:
                    errors.append(f"Missing required field: {field_name}")

            for field_name, value in data.items():
                if field_name in properties:
                    expected_type = properties[field_name].get("type")
                    if expected_type and not SchemaResolver._check_type(value, expected_type):
                        errors.append(
                            f"Field '{field_name}': expected {expected_type}, "
                            f"got {type(value).__name__}"
                        )

        return len(errors) == 0, errors

    @staticmethod
    def _check_type(value: Any, expected: str) -> bool:
        """Check if a value matches a JSON Schema type."""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected_type = type_map.get(expected)
        if expected_type is None:
            return True
        return isinstance(value, expected_type)

    @staticmethod
    def get_schema_name(schema: Any) -> str:
        """Get a human-readable name for a schema."""
        if schema is None:
            return "none"
        if hasattr(schema, "__name__"):
            return schema.__name__
        if isinstance(schema, dict):
            return schema.get("title", "json_schema")
        return type(schema).__name__

    @staticmethod
    def parse_to_model(data: dict[str, Any], schema: Any) -> Any:
        """
        Parse a dictionary into a Pydantic model instance.

        Args:
            data: Data dictionary.
            schema: Pydantic model class.

        Returns:
            Pydantic model instance, or original data if not a model.
        """
        if hasattr(schema, "model_validate"):
            return schema.model_validate(data)
        if hasattr(schema, "parse_obj"):
            return schema.parse_obj(data)
        return data


# ══════════════════════════════════════════════════════════════
# Extraction Strategy ABC
# ══════════════════════════════════════════════════════════════

class ExtractionStrategy(ABC):
    """
    Abstract base class for all extraction strategies.

    Subclasses must implement:
        - method_name: Strategy identifier.
        - _extract: Core extraction logic.

    The base class provides:
        - Schema resolution and validation
        - Retry logic with exponential backoff
        - Timeout handling
        - Result construction
        - Pydantic model parsing

    Args:
        schema: Pydantic model class or JSON schema dict.
        config: Extraction configuration.
        prompt: Custom prompt (for LLM extraction).

    Example:
        >>> class MyExtractor(ExtractionStrategy):
        ...     method_name = "my_method"
        ...     async def _extract(self, html, markdown, url):
        ...         return {"title": "...", "price": 99.99}
        ...
        >>> extractor = MyExtractor(schema=ProductModel)
        >>> result = await extractor.extract(html=html, markdown=md)
        >>> print(result.data)
    """

    method_name: str = "base"

    def __init__(
        self,
        schema: Any = None,
        config: ExtractionConfig | None = None,
        prompt: str | None = None,
    ):
        self._schema = schema
        self._config = config or ExtractionConfig()
        self._prompt = prompt
        self._schema_resolver = SchemaResolver()
        self._json_schema = self._schema_resolver.to_json_schema(schema)
        self._schema_name = self._schema_resolver.get_schema_name(schema)

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def schema(self) -> Any:
        """The extraction schema."""
        return self._schema

    @property
    def json_schema(self) -> dict[str, Any]:
        """JSON Schema representation."""
        return self._json_schema

    @property
    def schema_name(self) -> str:
        """Human-readable schema name."""
        return self._schema_name

    @property
    def config(self) -> ExtractionConfig:
        """Extraction configuration."""
        return self._config

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    async def extract(
        self,
        html: str = "",
        markdown: str = "",
        url: str = "",
        **kwargs: Any,
    ) -> ExtractionResult:
        """
        Extract structured data from web content.

        Handles retry logic, timeout, validation, and result
        construction around the core _extract method.

        Args:
            html: Raw or cleaned HTML content.
            markdown: Markdown content.
            url: Source URL.
            **kwargs: Additional method-specific parameters.

        Returns:
            ExtractionResult with extracted data.
        """
        start_time = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                # Execute with timeout
                raw_data = await asyncio.wait_for(
                    self._extract(
                        html=html,
                        markdown=markdown,
                        url=url,
                        **kwargs,
                    ),
                    timeout=self._config.timeout,
                )

                duration = (time.perf_counter() - start_time) * 1000

                # Parse to Pydantic model if applicable
                data = self._parse_output(raw_data)

                # Validate
                validation_errors: list[str] = []
                status = ExtractionStatus.SUCCESS

                if self._config.validate and self._schema:
                    is_valid, errors = self._schema_resolver.validate_data(
                        data if isinstance(data, dict) else raw_data,
                        self._schema,
                    )
                    if not is_valid:
                        validation_errors = errors
                        if self._config.strict:
                            status = ExtractionStatus.VALIDATION_ERROR
                        else:
                            status = ExtractionStatus.PARTIAL

                return ExtractionResult(
                    data=data,
                    status=status,
                    method=self.method_name,
                    schema_name=self._schema_name,
                    raw_output=str(raw_data)[:500] if raw_data else "",
                    validation_errors=validation_errors,
                    duration_ms=duration,
                )

            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"Extraction timed out after {self._config.timeout}s"
                )
                logger.warning(
                    "Extraction timeout (attempt %d/%d)",
                    attempt + 1,
                    self._config.max_retries + 1,
                )

            except Exception as e:
                last_error = e
                logger.warning(
                    "Extraction error (attempt %d/%d): %s",
                    attempt + 1,
                    self._config.max_retries + 1,
                    e,
                )

            # Retry delay with exponential backoff
            if attempt < self._config.max_retries:
                delay = self._config.retry_delay * (2 ** attempt)
                await asyncio.sleep(delay)

        # All retries exhausted
        duration = (time.perf_counter() - start_time) * 1000
        status = (
            ExtractionStatus.TIMEOUT
            if isinstance(last_error, TimeoutError)
            else ExtractionStatus.FAILED
        )

        return ExtractionResult(
            data=None,
            status=status,
            method=self.method_name,
            schema_name=self._schema_name,
            duration_ms=duration,
            error=str(last_error) if last_error else "Unknown error",
        )

    async def extract_many(
        self,
        items: list[dict[str, str]],
        max_concurrent: int = 5,
    ) -> list[ExtractionResult]:
        """
        Extract from multiple content items concurrently.

        Args:
            items: List of dicts with 'html', 'markdown', 'url' keys.
            max_concurrent: Maximum concurrent extractions.

        Returns:
            List of ExtractionResult objects.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _extract_one(item: dict[str, str]) -> ExtractionResult:
            async with semaphore:
                return await self.extract(
                    html=item.get("html", ""),
                    markdown=item.get("markdown", ""),
                    url=item.get("url", ""),
                )

        tasks = [_extract_one(item) for item in items]
        return list(await asyncio.gather(*tasks))

    # ──────────────────────────────────────────────────────────
    # Abstract Method
    # ──────────────────────────────────────────────────────────

    @abstractmethod
    async def _extract(
        self,
        html: str = "",
        markdown: str = "",
        url: str = "",
        **kwargs: Any,
    ) -> Any:
        """
        Core extraction logic. Must be implemented by subclasses.

        Args:
            html: HTML content.
            markdown: Markdown content.
            url: Source URL.
            **kwargs: Additional parameters.

        Returns:
            Extracted data (dict, list, or raw value).
        """
        ...

    # ──────────────────────────────────────────────────────────
    # Output Parsing
    # ──────────────────────────────────────────────────────────

    def _parse_output(self, raw_data: Any) -> Any:
        """
        Parse raw extraction output into the target schema.

        Handles:
            - JSON string parsing
            - Pydantic model instantiation
            - Markdown code fence stripping

        Args:
            raw_data: Raw output from _extract.

        Returns:
            Parsed data.
        """
        if raw_data is None:
            return None

        # Already a dict or list
        if isinstance(raw_data, (dict, list)):
            return self._try_parse_to_model(raw_data)

        # String — try JSON parsing
        if isinstance(raw_data, str):
            text = raw_data.strip()

            # Strip markdown code fences
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [line for line in lines if not line.strip().startswith("```")]
                text = "\n".join(lines).strip()

            try:
                parsed = json.loads(text)
                return self._try_parse_to_model(parsed)
            except json.JSONDecodeError:
                pass

        return raw_data

    def _try_parse_to_model(self, data: Any) -> Any:
        """Try to parse data into the schema's Pydantic model."""
        if self._schema is None:
            return data

        if isinstance(data, dict):
            try:
                return self._schema_resolver.parse_to_model(data, self._schema)
            except Exception as e:
                logger.debug("Model parsing failed: %s", e)
                return data

        if isinstance(data, list):
            # Try to parse each item
            try:
                return [
                    self._schema_resolver.parse_to_model(item, self._schema)
                    if isinstance(item, dict) else item
                    for item in data
                ]
            except Exception:
                return data

        return data

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize extractor configuration."""
        return {
            "method": self.method_name,
            "schema": self._schema_name,
            "config": self._config.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(schema={self._schema_name!r}, "
            f"method={self.method_name!r})"
        )


# ══════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════

def create_extractor(
    method: str | ExtractionMethod = ExtractionMethod.LLM,
    schema: Any = None,
    **kwargs: Any,
) -> ExtractionStrategy:
    """
    Factory function to create an extractor by method name.

    Args:
        method: Extraction method ('llm', 'css', 'xpath', 'cosine', 'regex').
        schema: Extraction schema.
        **kwargs: Additional arguments for the extractor.

    Returns:
        ExtractionStrategy instance.

    Raises:
        ValueError: If method is unknown.

    Example:
        >>> extractor = create_extractor("llm", schema=ProductModel)
        >>> extractor = create_extractor("css", schema=css_schema_dict)
    """
    if isinstance(method, str):
        try:
            method = ExtractionMethod(method)
        except ValueError as err:
            raise ValueError(
                f"Unknown extraction method: '{method}'. "
                f"Available: {', '.join(m.value for m in ExtractionMethod)}"
            ) from err

    if method == ExtractionMethod.LLM:
        from agentcrawl.extraction.llm import LLMExtractor
        return LLMExtractor(schema=schema, **kwargs)

    if method == ExtractionMethod.CSS:
        from agentcrawl.extraction.json_css import JsonCssExtractor
        return JsonCssExtractor(schema=schema, **kwargs)

    if method == ExtractionMethod.XPATH:
        from agentcrawl.extraction.json_xpath import JsonXPathExtractor
        return JsonXPathExtractor(schema=schema, **kwargs)

    if method == ExtractionMethod.COSINE:
        from agentcrawl.extraction.cosine import CosineExtractor
        return CosineExtractor(schema=schema, **kwargs)

    if method == ExtractionMethod.REGEX:
        from agentcrawl.extraction.regex import RegexExtractor
        return RegexExtractor(schema=schema, **kwargs)

    raise ValueError(f"Unknown extraction method: {method}")


def create_extractor_from_config(config: Any) -> ExtractionStrategy | None:
    """
    Create an extractor from a CrawlerConfig instance.

    Args:
        config: CrawlerConfig with extraction settings.

    Returns:
        ExtractionStrategy instance, or None if no extraction configured.
    """
    extraction = getattr(config, "extraction", None)
    if extraction is None:
        return None

    # Already an extractor instance
    if isinstance(extraction, ExtractionStrategy):
        return extraction

    return None
