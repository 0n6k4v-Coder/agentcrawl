"""
AgentCrawl — Utilities Layer
===============================

Shared utility functions for cryptography, HTML processing,
logging, retry logic, text analysis, and URL manipulation.

Modules:
    crypto   — Encryption, hashing, token generation
    html     — HTML cleaning, tag stripping, text extraction
    logging  — Structured logging, formatters, context
    retry    — Retry with backoff, circuit breaker, rate limiter
    text     — Text cleaning, counting, similarity, keywords
    url      — URL normalization, validation, domain extraction

Quick Start:
    # Crypto
    from agentcrawl.utils import encrypt_api_key, hash_sha256, generate_token
    encrypted = encrypt_api_key("sk-abc123", "my-key")
    digest = hash_sha256("hello")
    token = generate_token(32)

    # HTML
    from agentcrawl.utils import strip_tags, extract_text, clean_html
    text = extract_text("<p>Hello <b>world</b></p>")

    # Logging
    from agentcrawl.utils import setup_logging, get_logger
    setup_logging(level="INFO")
    logger = get_logger(__name__)

    # Retry
    from agentcrawl.utils import retry, RetryConfig, CircuitBreaker
    @retry(max_retries=3, delay=1.0)
    async def fetch(): ...

    # Text
    from agentcrawl.utils import count_words, slugify, detect_language
    words = count_words("Hello world")
    slug = slugify("Hello World!")

    # URL
    from agentcrawl.utils import normalize_url, get_domain, is_valid_url
    url = normalize_url("HTTPS://Example.COM/page/#top")
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# Crypto
# ──────────────────────────────────────────────────────────────
from agentcrawl.utils.crypto import (
    CryptoManager,
    b64_decode,
    b64_decode_bytes,
    b64_encode,
    b64_encode_bytes,
    decrypt_api_key,
    derive_key,
    encrypt_api_key,
    generate_api_key,
    generate_job_id,
    generate_request_id,
    generate_session_id,
    generate_token,
    hash_md5,
    hash_sha256,
    hash_sha512,
    hash_url,
    hmac_sign,
    hmac_verify,
    mask_api_key,
    mask_email,
)

# ──────────────────────────────────────────────────────────────
# HTML
# ──────────────────────────────────────────────────────────────
from agentcrawl.utils.html import (
    clean_html,
    collapse_spaces,
    decode_entities,
    decode_html_bytes,
    detect_encoding,
    encode_entities,
    extract_canonical_url,
    extract_images,
    extract_links,
    extract_meta_tags,
    extract_text,
    extract_title,
    get_char_count,
    get_word_count,
    is_html,
    is_well_formed,
    normalize_whitespace,
    sanitize_html,
    strip_specific_tags,
    strip_tags,
)

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
from agentcrawl.utils.logging import (
    ColoredFormatter,
    ContextFilter,
    JsonFormatter,
    LoggingContext,
    PerformanceTimer,
    clear_log_context,
    enable_debug_logging,
    get_log_context,
    get_logger,
    log_performance,
    set_log_level,
    setup_logging,
    suppress_logging,
)

# ──────────────────────────────────────────────────────────────
# Retry
# ──────────────────────────────────────────────────────────────
from agentcrawl.utils.retry import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    RateLimiter,
    RetryConfig,
    retry,
    retry_with_backoff,
)

# ──────────────────────────────────────────────────────────────
# Text
# ──────────────────────────────────────────────────────────────
from agentcrawl.utils.text import (
    STOP_WORDS,
    TextStats,
    analyze_text,
    clean_text,
    count_characters,
    count_paragraphs,
    count_sentences,
    count_words,
    dedent,
    detect_language,
    estimate_tokens,
    estimate_tokens_tiktoken,
    extract_key_phrases,
    extract_keywords,
    indent,
    is_mostly_empty,
    normalize_unicode,
    normalize_whitespace,
    remove_accents,
    slugify,
    text_similarity,
    truncate,
    truncate_tokens,
    wrap_text,
)

# ──────────────────────────────────────────────────────────────
# URL
# ──────────────────────────────────────────────────────────────
from agentcrawl.utils.url import (
    TRACKING_PARAMS,
    add_query_params,
    decode_url,
    deduplicate_urls,
    encode_url,
    filter_urls,
    get_base_domain,
    get_domain,
    get_favicon_url,
    get_file_extension,
    get_origin,
    get_path,
    get_path_depth,
    get_path_segments,
    get_query_params,
    get_robots_url,
    get_sitemap_url,
    get_subdomain,
    get_tld,
    is_file_url,
    is_http_url,
    is_same_domain,
    is_valid_url,
    join_url,
    normalize_url,
    remove_fragment,
    remove_query_params,
    set_fragment,
    url_matches_pattern,
    url_matches_regex,
    urls_equal,
)

# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Crypto
    "CryptoManager",
    "hash_sha256",
    "hash_md5",
    "hash_sha512",
    "hash_url",
    "hmac_sign",
    "hmac_verify",
    "generate_token",
    "generate_api_key",
    "generate_request_id",
    "generate_job_id",
    "generate_session_id",
    "encrypt_api_key",
    "decrypt_api_key",
    "derive_key",
    "b64_encode",
    "b64_decode",
    "b64_encode_bytes",
    "b64_decode_bytes",
    "mask_api_key",
    "mask_email",
    # HTML
    "strip_tags",
    "strip_specific_tags",
    "extract_text",
    "extract_title",
    "clean_html",
    "sanitize_html",
    "decode_entities",
    "encode_entities",
    "normalize_whitespace",
    "collapse_spaces",
    "extract_links",
    "extract_images",
    "extract_meta_tags",
    "extract_canonical_url",
    "detect_encoding",
    "decode_html_bytes",
    "is_html",
    "is_well_formed",
    "get_word_count",
    "get_char_count",
    # Logging
    "setup_logging",
    "get_logger",
    "log_performance",
    "LoggingContext",
    "JsonFormatter",
    "ColoredFormatter",
    "ContextFilter",
    "PerformanceTimer",
    "set_log_level",
    "suppress_logging",
    "enable_debug_logging",
    "get_log_context",
    "clear_log_context",
    # Retry
    "retry",
    "RetryConfig",
    "CircuitBreaker",
    "CircuitBreakerError",
    "CircuitState",
    "RateLimiter",
    "retry_with_backoff",
    # Text
    "clean_text",
    "normalize_unicode",
    "remove_accents",
    "normalize_whitespace",
    "count_words",
    "count_sentences",
    "count_paragraphs",
    "count_characters",
    "estimate_tokens",
    "estimate_tokens_tiktoken",
    "truncate",
    "truncate_tokens",
    "slugify",
    "detect_language",
    "text_similarity",
    "extract_keywords",
    "extract_key_phrases",
    "analyze_text",
    "TextStats",
    "STOP_WORDS",
    "dedent",
    "indent",
    "wrap_text",
    "is_mostly_empty",
    # URL
    "normalize_url",
    "is_valid_url",
    "is_http_url",
    "is_same_domain",
    "get_domain",
    "get_base_domain",
    "get_subdomain",
    "get_tld",
    "join_url",
    "add_query_params",
    "remove_query_params",
    "get_query_params",
    "set_fragment",
    "remove_fragment",
    "url_matches_pattern",
    "url_matches_regex",
    "filter_urls",
    "get_robots_url",
    "get_sitemap_url",
    "get_favicon_url",
    "get_origin",
    "encode_url",
    "decode_url",
    "urls_equal",
    "deduplicate_urls",
    "get_path",
    "get_path_segments",
    "get_path_depth",
    "get_file_extension",
    "is_file_url",
    "TRACKING_PARAMS",
]
