"""
AgentCrawl — LLM Configuration
=================================

Configuration for LLM providers used in extraction, summarization,
and content processing. Supports any provider via litellm, with
dedicated presets for OpenAI, Anthropic, Google, Azure, and local models.

Usage:
    from agentcrawl.config.llm_config import LLMConfig

    # Default (OpenAI gpt-4o-mini)
    config = LLMConfig()

    # Specific provider/model
    config = LLMConfig(provider="anthropic/claude-sonnet-4-20250514")

    # Full configuration
    config = LLMConfig(
        provider="openai/gpt-4o",
        temperature=0.1,
        max_tokens=4096,
        api_key="sk-...",
        timeout=60,
        max_retries=3,
    )

    # From environment
    config = LLMConfig.from_env()

    # Presets
    config = LLMConfig.preset_fast()
    config = LLMConfig.preset_accurate()
    config = LLMConfig.preset_local()

    # Use with LLMExtractor
    from agentcrawl.extraction import LLMExtractor
    extractor = LLMExtractor(schema=MyModel, llm_config=config)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("agentcrawl.config.llm_config")

# ══════════════════════════════════════════════════════════════
# Provider Registry
# ══════════════════════════════════════════════════════════════

# Known provider prefixes for litellm routing
KNOWN_PROVIDERS: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini",
    "gemini": "Google Gemini",
    "azure": "Azure OpenAI",
    "azure_ai": "Azure AI",
    "cohere": "Cohere",
    "mistral": "Mistral AI",
    "groq": "Groq",
    "perplexity": "Perplexity",
    "together_ai": "Together AI",
    "replicate": "Replicate",
    "ollama": "Ollama (local)",
    "vllm": "vLLM (local)",
    "huggingface": "Hugging Face",
    "bedrock": "AWS Bedrock",
    "vertex_ai": "Google Vertex AI",
    "deepseek": "DeepSeek",
    "xai": "xAI (Grok)",
}

# Environment variable names for API keys per provider
API_KEY_ENV_VARS: dict[str, list[str]] = {
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "azure": ["AZURE_API_KEY", "AZURE_OPENAI_API_KEY"],
    "cohere": ["COHERE_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "perplexity": ["PERPLEXITY_API_KEY"],
    "together_ai": ["TOGETHER_API_KEY"],
    "replicate": ["REPLICATE_API_KEY"],
    "ollama": [],  # No key needed
    "vllm": [],  # No key needed
    "huggingface": ["HUGGINGFACE_API_KEY", "HF_TOKEN"],
    "bedrock": ["AWS_ACCESS_KEY_ID"],
    "vertex_ai": ["GOOGLE_APPLICATION_CREDENTIALS"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "xai": ["XAI_API_KEY"],
}

# Default models per provider
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "google": "gemini-2.0-flash",
    "gemini": "gemini-2.0-flash",
    "azure": "gpt-4o-mini",
    "cohere": "command-r-plus",
    "mistral": "mistral-large-latest",
    "groq": "llama-3.3-70b-versatile",
    "perplexity": "sonar",
    "together_ai": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "deepseek": "deepseek-chat",
    "xai": "grok-3-mini",
    "ollama": "llama3.2",
    "vllm": "meta-llama/Llama-3.2-3B-Instruct",
}


# ══════════════════════════════════════════════════════════════
# LLM Settings (Pydantic)
# ══════════════════════════════════════════════════════════════


class LLMConfig(BaseSettings):
    """
    Configuration for LLM providers used in extraction and processing.

    Uses litellm for provider-agnostic routing. The ``provider`` field
    accepts the litellm model string format: ``{provider}/{model}``.

    All fields can be set via environment variables with the
    ``AGENTCRAWL_LLM_`` prefix, or via provider-specific env vars
    (e.g., ``OPENAI_API_KEY``).

    Attributes:
        provider: Model identifier in litellm format (e.g., 'openai/gpt-4o-mini').
        api_key: API key (auto-detected from env if not set).
        api_base: Custom API base URL (for Azure, local models, proxies).
        api_version: API version (for Azure).
        temperature: Sampling temperature (0.0 = deterministic, 2.0 = creative).
        max_tokens: Maximum tokens in the response.
        top_p: Nucleus sampling parameter.
        top_k: Top-k sampling parameter.
        frequency_penalty: Frequency penalty (-2.0 to 2.0).
        presence_penalty: Presence penalty (-2.0 to 2.0).
        stop: Stop sequences.
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts on failure.
        retry_delay: Delay between retries in seconds.
        seed: Random seed for reproducibility.
        response_format: Response format ('text', 'json', 'json_schema').
        system_prompt: Custom system prompt override.
        max_input_tokens: Maximum input tokens (for cost control).
        cost_per_1k_input: Cost per 1K input tokens (for tracking).
        cost_per_1k_output: Cost per 1K output tokens (for tracking).
        extra_headers: Additional HTTP headers.
        extra_body: Additional request body parameters.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTCRAWL_LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Provider ──────────────────────────────────────────────
    provider: str = Field(
        default="openai/gpt-4o-mini",
        description="Model in litellm format: {provider}/{model}",
    )
    api_key: str | None = Field(
        default=None,
        description="API key (auto-detected from env if not set)",
    )
    api_base: str | None = Field(
        default=None,
        description="Custom API base URL",
    )
    api_version: str | None = Field(
        default=None,
        description="API version (for Azure)",
    )

    # ── Generation Parameters ─────────────────────────────────
    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    max_tokens: int = Field(
        default=4096,
        ge=1,
        le=1_000_000,
        description="Maximum response tokens",
    )
    top_p: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling parameter",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        description="Top-k sampling parameter",
    )
    frequency_penalty: float = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="Frequency penalty",
    )
    presence_penalty: float = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="Presence penalty",
    )
    stop: list[str] | None = Field(
        default=None,
        description="Stop sequences",
    )
    seed: int | None = Field(
        default=None,
        description="Random seed for reproducibility",
    )

    # ── Response Format ───────────────────────────────────────
    response_format: str = Field(
        default="json",
        description="Response format: text, json, json_schema",
    )

    # ── Prompt ────────────────────────────────────────────────
    system_prompt: str | None = Field(
        default=None,
        description="Custom system prompt override",
    )

    # ── Reliability ───────────────────────────────────────────
    timeout: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Request timeout in seconds",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts",
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0.0,
        le=60.0,
        description="Delay between retries in seconds",
    )

    # ── Cost Control ──────────────────────────────────────────
    max_input_tokens: int = Field(
        default=100_000,
        ge=100,
        le=10_000_000,
        description="Maximum input tokens (truncate if exceeded)",
    )
    cost_per_1k_input: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost per 1K input tokens (for tracking)",
    )
    cost_per_1k_output: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost per 1K output tokens (for tracking)",
    )

    # ── Advanced ──────────────────────────────────────────────
    extra_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers",
    )
    extra_body: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional request body parameters",
    )

    # ──────────────────────────────────────────────────────────
    # Validators
    # ──────────────────────────────────────────────────────────

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v = v.strip()
        if "/" not in v:
            # Assume openai if no provider prefix
            v = f"openai/{v}"
        return v

    @field_validator("response_format")
    @classmethod
    def validate_response_format(cls, v: str) -> str:
        v = v.lower().strip()
        allowed = {"text", "json", "json_schema"}
        if v not in allowed:
            raise ValueError(
                f"Invalid response_format '{v}'. Must be one of: {', '.join(sorted(allowed))}"
            )
        return v

    @model_validator(mode="after")
    def auto_detect_api_key(self) -> LLMConfig:
        """Auto-detect API key from environment if not explicitly set."""
        if self.api_key is not None:
            return self

        provider_name = self.provider_name
        env_vars = API_KEY_ENV_VARS.get(provider_name, [])

        for env_var in env_vars:
            value = os.environ.get(env_var)
            if value:
                object.__setattr__(self, "api_key", value)
                break

        return self

    @model_validator(mode="after")
    def auto_set_costs(self) -> LLMConfig:
        """Auto-set cost estimates for known models if not set."""
        if self.cost_per_1k_input > 0 or self.cost_per_1k_output > 0:
            return self

        model = self.model_name.lower()
        costs = _KNOWN_COSTS.get(model)
        if costs:
            object.__setattr__(self, "cost_per_1k_input", costs[0])
            object.__setattr__(self, "cost_per_1k_output", costs[1])

        return self

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        """Extract the provider name from the provider string."""
        return self.provider.split("/")[0].lower()

    @property
    def model_name(self) -> str:
        """Extract the model name from the provider string."""
        parts = self.provider.split("/", 1)
        return parts[1] if len(parts) > 1 else parts[0]

    @property
    def litellm_model(self) -> str:
        """Full model string for litellm."""
        return self.provider

    @property
    def provider_display_name(self) -> str:
        """Human-readable provider name."""
        return KNOWN_PROVIDERS.get(self.provider_name, self.provider_name.title())

    @property
    def is_local(self) -> bool:
        """Whether this is a local model (no API key needed)."""
        return self.provider_name in ("ollama", "vllm")

    @property
    def requires_api_key(self) -> bool:
        """Whether this provider requires an API key."""
        return not self.is_local

    @property
    def has_api_key(self) -> bool:
        """Whether an API key is configured."""
        return self.api_key is not None and len(self.api_key) > 0

    @property
    def is_ready(self) -> bool:
        """Whether the config is ready to make API calls."""
        if self.is_local:
            return True
        return self.has_api_key

    # ──────────────────────────────────────────────────────────
    # litellm Integration
    # ──────────────────────────────────────────────────────────

    def to_litellm_kwargs(self) -> dict[str, Any]:
        """
        Convert to keyword arguments for litellm.acompletion().

        Returns:
            Dictionary of litellm-compatible parameters.
        """
        kwargs: dict[str, Any] = {
            "model": self.litellm_model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "timeout": self.timeout,
            "num_retries": self.max_retries,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        if self.api_base:
            kwargs["api_base"] = self.api_base

        if self.api_version:
            kwargs["api_version"] = self.api_version

        if self.top_k is not None:
            kwargs["top_k"] = self.top_k

        if self.stop:
            kwargs["stop"] = self.stop

        if self.seed is not None:
            kwargs["seed"] = self.seed

        if self.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        if self.extra_body:
            kwargs["extra_body"] = self.extra_body

        return kwargs

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Any:
        """
        Make a completion call via litellm.

        Args:
            messages: List of message dicts (role, content).
            **kwargs: Additional litellm parameters.

        Returns:
            litellm response object.

        Raises:
            ImportError: If litellm is not installed.
            RuntimeError: If API key is missing.
        """
        try:
            import litellm
        except ImportError as err:
            raise ImportError(
                "litellm required for LLM operations. Install with: pip install 'agentcrawl[llm]'"
            ) from err

        if self.requires_api_key and not self.has_api_key:
            raise RuntimeError(
                f"API key required for {self.provider_display_name}. "
                f"Set via LLMConfig(api_key='...') or environment variable."
            )

        call_kwargs = self.to_litellm_kwargs()
        call_kwargs.update(kwargs)

        response = await litellm.acompletion(
            messages=messages,
            **call_kwargs,
        )

        return response

    async def complete_text(
        self,
        prompt: str,
        system: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Simple text completion.

        Args:
            prompt: User prompt.
            system: Optional system prompt.
            **kwargs: Additional litellm parameters.

        Returns:
            Response text string.
        """
        messages = []
        if system or self.system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system or self.system_prompt or "",
                }
            )
        messages.append({"role": "user", "content": prompt})

        response = await self.complete(messages, **kwargs)
        return response.choices[0].message.content or ""

    async def complete_json(
        self,
        prompt: str,
        system: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        JSON completion with automatic parsing.

        Args:
            prompt: User prompt.
            system: Optional system prompt.
            **kwargs: Additional litellm parameters.

        Returns:
            Parsed JSON dictionary.
        """
        import json

        text = await self.complete_text(prompt, system, **kwargs)

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)

        return dict(json.loads(text))

    # ──────────────────────────────────────────────────────────
    # Token Counting
    # ──────────────────────────────────────────────────────────

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for a text string.

        Uses tiktoken for OpenAI models, heuristic for others.

        Args:
            text: Input text.

        Returns:
            Estimated token count.
        """
        if self.provider_name in ("openai", "azure"):
            try:
                import tiktoken

                encoding = tiktoken.encoding_for_model(self.model_name)
                return len(encoding.encode(text))
            except Exception:
                logger.debug("tiktoken not available, using heuristic")

        # Heuristic: ~4 chars per token for English
        return len(text) // 4

    def truncate_to_tokens(self, text: str, max_tokens: int | None = None) -> str:
        """
        Truncate text to fit within a token limit.

        Args:
            text: Input text.
            max_tokens: Maximum tokens (default: self.max_input_tokens).

        Returns:
            Truncated text.
        """
        limit = max_tokens or self.max_input_tokens
        estimated = self.count_tokens(text)

        if estimated <= limit:
            return text

        # Approximate character limit
        ratio = limit / estimated
        char_limit = int(len(text) * ratio * 0.95)  # 5% safety margin
        return text[:char_limit] + "\n\n[... content truncated to fit token limit]"

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Estimate the cost of an API call.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            Estimated cost in USD.
        """
        input_cost = (input_tokens / 1000) * self.cost_per_1k_input
        output_cost = (output_tokens / 1000) * self.cost_per_1k_output
        return input_cost + output_cost

    # ──────────────────────────────────────────────────────────
    # Factory Methods
    # ──────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, prefix: str = "AGENTCRAWL_LLM") -> LLMConfig:
        """Create config from environment variables."""
        return cls(_env_prefix=f"{prefix}_")  # type: ignore[call-arg]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMConfig:
        """Create config from a dictionary."""
        return cls(**data)

    @classmethod
    def from_provider(cls, provider: str, **kwargs: Any) -> LLMConfig:
        """
        Create config for a specific provider with its default model.

        Args:
            provider: Provider name (e.g., 'openai', 'anthropic').
            **kwargs: Additional configuration overrides.

        Returns:
            LLMConfig instance.
        """
        model = DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        return cls(provider=f"{provider}/{model}", **kwargs)

    # ──────────────────────────────────────────────────────────
    # Presets
    # ──────────────────────────────────────────────────────────

    @classmethod
    def preset_default(cls) -> LLMConfig:
        """Default: OpenAI gpt-4o-mini, balanced speed/quality."""
        return cls(provider="openai/gpt-4o-mini", temperature=0.1)

    @classmethod
    def preset_fast(cls) -> LLMConfig:
        """Fastest: cheapest model, low tokens."""
        return cls(
            provider="openai/gpt-4o-mini",
            temperature=0.0,
            max_tokens=2048,
            timeout=30,
        )

    @classmethod
    def preset_accurate(cls) -> LLMConfig:
        """Most accurate: best model, higher tokens."""
        return cls(
            provider="openai/gpt-4o",
            temperature=0.0,
            max_tokens=8192,
            timeout=120,
        )

    @classmethod
    def preset_anthropic(cls) -> LLMConfig:
        """Anthropic Claude Sonnet."""
        return cls(
            provider="anthropic/claude-sonnet-4-20250514",
            temperature=0.1,
            max_tokens=4096,
        )

    @classmethod
    def preset_gemini(cls) -> LLMConfig:
        """Google Gemini Flash."""
        return cls(
            provider="google/gemini-2.0-flash",
            temperature=0.1,
            max_tokens=4096,
        )

    @classmethod
    def preset_local(cls, model: str = "llama3.2") -> LLMConfig:
        """Local model via Ollama."""
        return cls(
            provider=f"ollama/{model}",
            temperature=0.1,
            max_tokens=4096,
            api_base="http://localhost:11434",
            timeout=120,
        )

    @classmethod
    def preset_deepseek(cls) -> LLMConfig:
        """DeepSeek Chat."""
        return cls(
            provider="deepseek/deepseek-chat",
            temperature=0.1,
            max_tokens=4096,
        )

    @classmethod
    def preset_groq(cls) -> LLMConfig:
        """Groq (fast inference)."""
        return cls(
            provider="groq/llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=4096,
        )

    # ──────────────────────────────────────────────────────────
    # Serialization
    # ──────────────────────────────────────────────────────────

    def to_dict(self, exclude_none: bool = True, mask_key: bool = True) -> dict[str, Any]:
        """
        Convert to a plain dictionary.

        Args:
            exclude_none: Exclude None values.
            mask_key: Mask the API key in output.

        Returns:
            Configuration dictionary.
        """
        data = self.model_dump(exclude_none=exclude_none)

        if mask_key and "api_key" in data and data["api_key"]:
            key = data["api_key"]
            if len(key) > 8:
                data["api_key"] = f"{key[:4]}...{key[-4:]}"
            else:
                data["api_key"] = "********"

        return data

    def to_json(self, mask_key: bool = True) -> str:
        """Serialize to JSON string."""
        import json

        return json.dumps(self.to_dict(mask_key=mask_key), ensure_ascii=False, default=str)

    # ──────────────────────────────────────────────────────────
    # Merge / Override
    # ──────────────────────────────────────────────────────────

    def merge(self, overrides: dict[str, Any]) -> LLMConfig:
        """Create a new config with overridden values."""
        current = self.model_dump()
        current.update(overrides)
        return LLMConfig(**current)

    def with_model(self, model: str) -> LLMConfig:
        """Return a copy with a different model."""
        provider_name = self.provider_name
        return self.merge({"provider": f"{provider_name}/{model}"})

    def with_temperature(self, temp: float) -> LLMConfig:
        """Return a copy with a different temperature."""
        return self.merge({"temperature": temp})

    def with_max_tokens(self, tokens: int) -> LLMConfig:
        """Return a copy with a different max_tokens."""
        return self.merge({"max_tokens": tokens})

    # ──────────────────────────────────────────────────────────
    # Validation
    # ──────────────────────────────────────────────────────────

    def validate_config(self) -> list[str]:
        """
        Validate the configuration and return warnings.

        Returns:
            List of warning messages.
        """
        warnings: list[str] = []

        if self.requires_api_key and not self.has_api_key:
            env_vars = API_KEY_ENV_VARS.get(self.provider_name, [])
            env_hint = f" Set via: {', '.join(env_vars)}" if env_vars else ""
            warnings.append(f"API key not configured for {self.provider_display_name}.{env_hint}")

        if self.temperature > 1.0:
            warnings.append("Temperature > 1.0 may produce inconsistent extraction results")

        if self.max_tokens < 256:
            warnings.append("max_tokens < 256 may truncate structured extraction output")

        if self.timeout < 10:
            warnings.append("Timeout < 10s may cause failures for complex extractions")

        return warnings

    # ──────────────────────────────────────────────────────────
    # Representation
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"LLMConfig(provider={self.provider!r}, "
            f"temp={self.temperature}, max_tokens={self.max_tokens}, "
            f"ready={self.is_ready})"
        )


# ══════════════════════════════════════════════════════════════
# Known Model Costs (per 1K tokens, USD)
# ══════════════════════════════════════════════════════════════

_KNOWN_COSTS: dict[str, tuple[float, float]] = {
    # (input_cost, output_cost) per 1K tokens
    "gpt-4o": (0.0025, 0.010),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.010, 0.030),
    "gpt-4.1": (0.002, 0.008),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-4.1-nano": (0.0001, 0.0004),
    "o3": (0.010, 0.040),
    "o3-mini": (0.0011, 0.0044),
    "o4-mini": (0.0011, 0.0044),
    "claude-sonnet-4-20250514": (0.003, 0.015),
    "claude-opus-4-20250514": (0.015, 0.075),
    "claude-3-5-haiku-20241022": (0.0008, 0.004),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-2.5-pro": (0.00125, 0.010),
    "gemini-2.5-flash": (0.00015, 0.0006),
    "deepseek-chat": (0.00027, 0.0011),
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
}
