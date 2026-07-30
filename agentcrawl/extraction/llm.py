"""
AgentCrawl — LLM Extractor
==============================

LLM-powered structured data extraction. Uses any LLM provider
(via litellm) to extract structured data from web content based
on a Pydantic schema or JSON schema definition.

Features:
    - Automatic schema → prompt conversion
    - Robust JSON output parsing (handles markdown fences, partial JSON)
    - Token management (truncates input to fit context window)
    - Retry logic for malformed outputs
    - Cost tracking
    - Multi-provider support (OpenAI, Anthropic, Google, local, etc.)

Usage:
    from agentcrawl.extraction.llm import LLMExtractor
    from pydantic import BaseModel

    class Product(BaseModel):
        name: str
        price: float
        description: str

    extractor = LLMExtractor(schema=Product)
    result = await extractor.extract(
        html=html_content,
        markdown=markdown_content,
    )
    print(result.data)  # Product instance

    # With custom LLM config
    from agentcrawl.config.llm_config import LLMConfig

    extractor = LLMExtractor(
        schema=Product,
        llm_config=LLMConfig(provider="anthropic/claude-sonnet-4-20250514"),
    )

    # With JSON schema dict
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "price": {"type": "number"},
        },
        "required": ["name", "price"],
    }
    extractor = LLMExtractor(schema=schema)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionStrategy,
    SchemaResolver,
)

logger = logging.getLogger("agentcrawl.extraction.llm")


# ══════════════════════════════════════════════════════════════
# Prompt Templates
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT_TEMPLATE = """\
You are a precise data extraction assistant. Your task is to extract \
structured data from web page content according to a given schema.

Rules:
1. Extract ONLY the data specified in the schema.
2. Return valid JSON that matches the schema exactly.
3. Do NOT include any explanation, commentary, or markdown formatting.
4. If a field is not found in the content, use null (or the appropriate default).
5. Preserve the original text values — do not summarize or paraphrase.
6. For numeric fields, extract the numeric value only (no currency symbols).
7. For list fields, extract all matching items.
8. Respond with ONLY the JSON object — no other text."""

USER_PROMPT_TEMPLATE = """\
Extract the following structured data from the web page content below.

## Schema
```json
{schema_json}
```

## Content
{content}

## Output
Return a JSON object matching the schema above. Respond with ONLY the JSON — no explanation, no markdown fences."""

USER_PROMPT_WITH_INSTRUCTIONS = """\
Extract the following structured data from the web page content below.

## Schema
```json
{schema_json}
```

## Additional Instructions
{instructions}

## Content
{content}

## Output
Return a JSON object matching the schema above. Respond with ONLY the JSON — no explanation, no markdown fences."""


# ══════════════════════════════════════════════════════════════
# LLM Extractor
# ══════════════════════════════════════════════════════════════

class LLMExtractor(ExtractionStrategy):
    """
    LLM-powered structured data extraction.

    Uses a language model to extract structured data from web
    content based on a Pydantic schema or JSON schema.

    Args:
        schema: Pydantic model class or JSON schema dict.
        llm_config: LLM configuration (provider, model, temperature, etc.).
        prompt: Custom prompt override.
        instructions: Additional extraction instructions.
        max_content_tokens: Maximum content tokens to send to LLM.
        use_markdown: Prefer markdown over HTML for LLM input.
        config: Extraction configuration.

    Example:
        >>> from pydantic import BaseModel
        >>> class Product(BaseModel):
        ...     name: str
        ...     price: float
        ...
        >>> extractor = LLMExtractor(schema=Product)
        >>> result = await extractor.extract(markdown=md_content)
        >>> print(result.data)  # Product(name="...", price=99.99)
    """

    method_name = "llm"

    def __init__(
        self,
        schema: Any = None,
        llm_config: Any = None,
        prompt: str | None = None,
        instructions: str | None = None,
        max_content_tokens: int = 8000,
        use_markdown: bool = True,
        config: ExtractionConfig | None = None,
        **kwargs: Any,
    ):
        super().__init__(schema=schema, config=config, prompt=prompt)

        self._llm_config = llm_config
        self._instructions = instructions
        self._max_content_tokens = max_content_tokens
        self._use_markdown = use_markdown

        # Build JSON schema from the provided schema
        self._json_schema = SchemaResolver.to_json_schema(schema)
        self._schema_name = SchemaResolver.get_schema_name(schema)

        # Token usage tracking
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_calls: int = 0

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens used across all calls."""
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        """Total output tokens used across all calls."""
        return self._total_output_tokens

    @property
    def total_calls(self) -> int:
        """Total LLM API calls made."""
        return self._total_calls

    @property
    def estimated_cost(self) -> float:
        """Estimated total cost in USD."""
        if self._llm_config and hasattr(self._llm_config, "estimate_cost"):
            return self._llm_config.estimate_cost(
                self._total_input_tokens,
                self._total_output_tokens,
            )
        return 0.0

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
        Extract structured data using an LLM.

        Args:
            html: HTML content.
            markdown: Markdown content.
            url: Source URL.

        Returns:
            Extracted data (dict or Pydantic model instance).
        """
        # Choose content source
        content = markdown if (self._use_markdown and markdown) else html
        if not content.strip():
            return {}

        # Truncate content to fit token budget
        content = self._truncate_content(content)

        # Build prompt
        messages = self._build_messages(content)

        # Call LLM
        response_text, usage = await self._call_llm(messages)

        # Track usage
        self._total_calls += 1
        self._total_input_tokens += usage.get("input_tokens", 0)
        self._total_output_tokens += usage.get("output_tokens", 0)

        # Parse JSON response
        parsed = self._parse_json_response(response_text)

        return parsed

    # ──────────────────────────────────────────────────────────
    # Prompt Building
    # ──────────────────────────────────────────────────────────

    def _build_messages(self, content: str) -> list[dict[str, str]]:
        """
        Build the LLM message list.

        Args:
            content: Web page content.

        Returns:
            List of message dicts (role, content).
        """
        schema_json = json.dumps(
            self._json_schema,
            indent=2,
            ensure_ascii=False,
        )

        # System prompt
        system_prompt = self._prompt or SYSTEM_PROMPT_TEMPLATE

        # User prompt
        if self._instructions:
            user_prompt = USER_PROMPT_WITH_INSTRUCTIONS.format(
                schema_json=schema_json,
                instructions=self._instructions,
                content=content,
            )
        else:
            user_prompt = USER_PROMPT_TEMPLATE.format(
                schema_json=schema_json,
                content=content,
            )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    # ──────────────────────────────────────────────────────────
    # LLM Call
    # ──────────────────────────────────────────────────────────

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[str, dict[str, int]]:
        """
        Call the LLM and return the response text and token usage.

        Args:
            messages: Message list.

        Returns:
            Tuple of (response_text, usage_dict).
        """
        # Use LLMConfig if provided
        if self._llm_config and hasattr(self._llm_config, "complete"):
            response = await self._llm_config.complete(
                messages=messages,
                response_format={"type": "json_object"},
            )

            text = response.choices[0].message.content or ""
            usage = {
                "input_tokens": getattr(response.usage, "prompt_tokens", 0),
                "output_tokens": getattr(response.usage, "completion_tokens", 0),
            }
            return text, usage

        # Fallback: use litellm directly
        try:
            import litellm
        except ImportError as err:
            raise ImportError(
                "litellm is required for LLM extraction. "
                "Install with: pip install 'agentcrawl[llm]'"
            ) from err

        # Determine model
        model = "gpt-4o-mini"
        api_key = None
        temperature = 0.1
        max_tokens = 4096

        if self._llm_config:
            model = getattr(self._llm_config, "litellm_model", model)
            api_key = getattr(self._llm_config, "api_key", None)
            temperature = getattr(self._llm_config, "temperature", 0.1)
            max_tokens = getattr(self._llm_config, "max_tokens", 4096)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        if api_key:
            kwargs["api_key"] = api_key

        response = await litellm.acompletion(**kwargs)

        text = response.choices[0].message.content or ""
        usage = {
            "input_tokens": getattr(response.usage, "prompt_tokens", 0),
            "output_tokens": getattr(response.usage, "completion_tokens", 0),
        }

        return text, usage

    # ──────────────────────────────────────────────────────────
    # JSON Parsing
    # ──────────────────────────────────────────────────────────

    def _parse_json_response(self, text: str) -> Any:
        """
        Robustly parse JSON from LLM response.

        Handles:
            - Markdown code fences (```json ... ```)
            - Leading/trailing text
            - Partial JSON (attempts repair)
            - Single quotes → double quotes

        Args:
            text: Raw LLM response text.

        Returns:
            Parsed JSON data (dict or list).
        """
        if not text:
            return {}

        text = text.strip()

        # Attempt 1: Direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Attempt 2: Strip markdown code fences
        cleaned = self._strip_code_fences(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Attempt 3: Extract JSON object from text
        json_str = self._extract_json_from_text(cleaned)
        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # Attempt 4: Fix common issues
        fixed = self._fix_json(cleaned)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Attempt 5: Try to extract from fixed text
        json_str = self._extract_json_from_text(fixed)
        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to parse LLM response as JSON")
        return {"_raw": text[:500]}

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove markdown code fences from text."""
        # Remove ```json ... ``` or ``` ... ```
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        return text.strip()

    @staticmethod
    def _extract_json_from_text(text: str) -> str | None:
        """Extract the first JSON object or array from text."""
        # Find first { or [
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            if start == -1:
                continue

            # Find matching end bracket
            depth = 0
            in_string = False
            escape = False

            for i in range(start, len(text)):
                char = text[i]

                if escape:
                    escape = False
                    continue

                if char == "\\":
                    escape = True
                    continue

                if char == '"':
                    in_string = not in_string
                    continue

                if in_string:
                    continue

                if char == start_char:
                    depth += 1
                elif char == end_char:
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]

        return None

    @staticmethod
    def _fix_json(text: str) -> str:
        """Attempt to fix common JSON issues."""
        # Replace single quotes with double quotes (naive)
        # Only do this if there are no double quotes
        if '"' not in text and "'" in text:
            text = text.replace("'", '"')

        # Remove trailing commas before } or ]
        text = re.sub(r",\s*([}\]])", r"\1", text)

        # Remove comments
        text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)

        return text.strip()

    # ──────────────────────────────────────────────────────────
    # Content Management
    # ──────────────────────────────────────────────────────────

    def _truncate_content(self, content: str) -> str:
        """
        Truncate content to fit within the token budget.

        Args:
            content: Full content text.

        Returns:
            Truncated content.
        """
        # Estimate tokens (~4 chars per token)
        estimated_tokens = len(content) // 4

        if estimated_tokens <= self._max_content_tokens:
            return content

        # Calculate character limit
        ratio = self._max_content_tokens / max(estimated_tokens, 1)
        char_limit = int(len(content) * ratio * 0.95)  # 5% safety margin

        truncated = content[:char_limit]

        # Try to break at a paragraph boundary
        last_para = truncated.rfind("\n\n")
        if last_para > char_limit * 0.7:
            truncated = truncated[:last_para]

        truncated += "\n\n[... content truncated to fit token limit]"

        logger.debug(
            "Content truncated: %d → %d chars (est. %d → %d tokens)",
            len(content),
            len(truncated),
            estimated_tokens,
            self._max_content_tokens,
        )

        return truncated

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "schema_name": self._schema_name,
            "max_content_tokens": self._max_content_tokens,
            "use_markdown": self._use_markdown,
            "instructions": self._instructions[:100] if self._instructions else None,
            "total_calls": self._total_calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "estimated_cost": round(self.estimated_cost, 6),
        })
        if self._llm_config:
            d["llm_provider"] = getattr(self._llm_config, "provider", "unknown")
        return d

    def __repr__(self) -> str:
        provider = ""
        if self._llm_config:
            provider = getattr(self._llm_config, "provider", "")
        return (
            f"LLMExtractor(schema={self._schema_name!r}, "
            f"provider={provider!r}, "
            f"calls={self._total_calls})"
        )
