"""
AgentCrawl — URL Utilities
==============================

URL processing utilities for normalization, validation, domain
extraction, pattern matching, and manipulation.

Features:
    - URL normalization and canonicalization
    - URL validation
    - Domain and subdomain extraction
    - URL joining and resolution
    - Query parameter manipulation
    - URL pattern matching (glob and regex)
    - URL comparison and deduplication
    - Encoding/decoding

Usage:
    from agentcrawl.utils.url import (
        normalize_url,
        is_valid_url,
        get_domain,
        get_base_domain,
        join_url,
        add_query_params,
        remove_query_params,
        url_matches_pattern,
        is_same_domain,
        get_robots_url,
        get_sitemap_url,
    )

    # Normalize
    url = normalize_url("HTTPS://Example.COM/page/?utm_source=tw#top")
    # → "https://example.com/page"

    # Validate
    is_valid_url("https://example.com")  # True
    is_valid_url("not-a-url")            # False

    # Domain
    get_domain("https://docs.example.com/page")  # "docs.example.com"
    get_base_domain("https://docs.example.com")  # "example.com"

    # Pattern matching
    url_matches_pattern("/docs/guide", "/docs/*")  # True
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any
from urllib.parse import (
    parse_qs,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)


# ══════════════════════════════════════════════════════════════
# Normalization
# ══════════════════════════════════════════════════════════════

# Tracking parameters to remove during normalization
TRACKING_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "utm_id", "utm_cid", "utm_reader",
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid",
    "mc_cid", "mc_eid", "yclid", "twclid",
    "ref", "referrer", "source",
    "_ga", "_gid", "_gl",
    "igshid", "s_kwcid",
}


def normalize_url(
    url: str,
    remove_fragment: bool = True,
    remove_tracking: bool = True,
    remove_trailing_slash: bool = True,
    lowercase_host: bool = True,
    sort_params: bool = True,
) -> str:
    """
    Normalize a URL to a canonical form.

    Args:
        url: URL to normalize.
        remove_fragment: Remove #fragment.
        remove_tracking: Remove tracking query parameters.
        remove_trailing_slash: Remove trailing slashes.
        lowercase_host: Lowercase the hostname.
        sort_params: Sort query parameters alphabetically.

    Returns:
        Normalized URL string.

    Example:
        >>> normalize_url("HTTPS://Example.COM/page/?utm_source=tw#top")
        'https://example.com/page'
    """
    if not url or not url.strip():
        return url

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    # Scheme
    scheme = parsed.scheme.lower()

    # Host
    host = parsed.hostname or ""
    if lowercase_host:
        host = host.lower()

    # Remove www prefix
    if host.startswith("www."):
        host = host[4:]

    # Port
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    # Reconstruct netloc
    netloc = host
    if port:
        netloc = f"{host}:{port}"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        netloc = f"{userinfo}@{netloc}"

    # Path
    path = parsed.path

    # Remove duplicate slashes
    path = re.sub(r"/{2,}", "/", path)

    # Remove trailing slash
    if remove_trailing_slash and path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Ensure leading slash
    if not path:
        path = "/"

    # Query
    query = parsed.query
    if query:
        query = _normalize_query(
            query,
            remove_tracking=remove_tracking,
            sort_params=sort_params,
        )

    # Fragment
    fragment = "" if remove_fragment else parsed.fragment

    return urlunparse((scheme, netloc, path, "", query, fragment))


def _normalize_query(
    query: str,
    remove_tracking: bool = True,
    sort_params: bool = True,
) -> str:
    """Normalize a query string."""
    params = parse_qs(query, keep_blank_values=True)

    if remove_tracking:
        params = {
            k: v for k, v in params.items()
            if k.lower() not in TRACKING_PARAMS
            and not any(
                k.lower().startswith(p)
                for p in ("utm_", "_ga", "fb")
            )
        }

    if not params:
        return ""

    if sort_params:
        sorted_params = sorted(params.items())
    else:
        sorted_params = list(params.items())

    return urlencode(sorted_params, doseq=True)


# ══════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════

def is_valid_url(url: str, require_http: bool = True) -> bool:
    """
    Check if a string is a valid URL.

    Args:
        url: URL string to validate.
        require_http: Require http/https scheme.

    Returns:
        True if the URL is valid.

    Example:
        >>> is_valid_url("https://example.com/page")
        True
        >>> is_valid_url("not-a-url")
        False
        >>> is_valid_url("ftp://files.example.com")
        False  # require_http=True
    """
    if not url or not url.strip():
        return False

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    # Must have a scheme
    if not parsed.scheme:
        return False

    if require_http and parsed.scheme not in ("http", "https"):
        return False

    # Must have a hostname
    if not parsed.hostname:
        return False

    # Hostname must have at least one dot (or be localhost)
    hostname = parsed.hostname
    if "." not in hostname and hostname not in ("localhost", "127.0.0.1"):
        return False

    return True


def is_http_url(url: str) -> bool:
    """Check if a URL uses HTTP or HTTPS."""
    try:
        return urlparse(url).scheme in ("http", "https")
    except Exception:
        return False


def is_same_domain(url_a: str, url_b: str) -> bool:
    """
    Check if two URLs are on the same domain.

    Args:
        url_a: First URL.
        url_b: Second URL.

    Returns:
        True if both URLs share the same base domain.

    Example:
        >>> is_same_domain("https://docs.example.com", "https://example.com")
        True
    """
    domain_a = get_base_domain(url_a)
    domain_b = get_base_domain(url_b)
    return domain_a == domain_b and domain_a != ""


# ══════════════════════════════════════════════════════════════
# Domain Extraction
# ══════════════════════════════════════════════════════════════

def get_domain(url: str) -> str:
    """
    Extract the full domain (including subdomain) from a URL.

    Args:
        url: URL string.

    Returns:
        Domain string (e.g., 'docs.example.com').

    Example:
        >>> get_domain("https://docs.example.com/page")
        'docs.example.com'
    """
    try:
        hostname = urlparse(url).hostname or ""
        return hostname.lower()
    except Exception:
        return ""


def get_base_domain(url: str) -> str:
    """
    Extract the base domain (without subdomain) from a URL.

    Handles common two-part TLDs (.co.uk, .com.au, etc.).

    Args:
        url: URL string.

    Returns:
        Base domain string (e.g., 'example.com').

    Example:
        >>> get_base_domain("https://docs.example.com/page")
        'example.com'
        >>> get_base_domain("https://site.co.uk/page")
        'site.co.uk'
    """
    domain = get_domain(url)
    if not domain:
        return ""

    # Remove www
    if domain.startswith("www."):
        domain = domain[4:]

    parts = domain.split(".")

    # Handle two-part TLDs
    two_part_tlds = {
        "co.uk", "co.jp", "co.kr", "co.in", "co.nz", "co.za",
        "com.au", "com.br", "com.cn", "com.mx", "com.sg",
        "com.tw", "com.hk", "com.ar", "com.co", "com.pe",
        "org.uk", "org.au", "net.au", "ac.uk", "gov.uk",
        "ne.jp", "or.jp", "go.jp", "ac.jp",
    }

    if len(parts) >= 3:
        last_two = ".".join(parts[-2:])
        if last_two in two_part_tlds:
            return ".".join(parts[-3:])

    # Standard: return last two parts
    if len(parts) >= 2:
        return ".".join(parts[-2:])

    return domain


def get_subdomain(url: str) -> str:
    """
    Extract the subdomain from a URL.

    Args:
        url: URL string.

    Returns:
        Subdomain string (e.g., 'docs'), or empty string.

    Example:
        >>> get_subdomain("https://docs.example.com/page")
        'docs'
        >>> get_subdomain("https://example.com/page")
        ''
    """
    domain = get_domain(url)
    base = get_base_domain(url)

    if not domain or not base:
        return ""

    if domain == base:
        return ""

    # Remove base domain from full domain
    subdomain = domain[: -(len(base) + 1)]  # +1 for the dot
    return subdomain


def get_tld(url: str) -> str:
    """
    Extract the top-level domain from a URL.

    Args:
        url: URL string.

    Returns:
        TLD string (e.g., 'com', 'co.uk').
    """
    domain = get_domain(url)
    if not domain:
        return ""

    parts = domain.split(".")
    if len(parts) >= 2:
        return parts[-1]
    return ""


# ══════════════════════════════════════════════════════════════
# URL Manipulation
# ══════════════════════════════════════════════════════════════

def join_url(base: str, path: str) -> str:
    """
    Join a base URL with a relative path.

    Args:
        base: Base URL.
        path: Relative path or absolute URL.

    Returns:
        Joined URL.

    Example:
        >>> join_url("https://example.com/docs", "guide")
        'https://example.com/docs/guide'
        >>> join_url("https://example.com", "/page")
        'https://example.com/page'
    """
    return urljoin(base, path)


def add_query_params(url: str, params: dict[str, str]) -> str:
    """
    Add or update query parameters in a URL.

    Args:
        url: Original URL.
        params: Parameters to add/update.

    Returns:
        URL with updated parameters.

    Example:
        >>> add_query_params("https://example.com/page", {"q": "test"})
        'https://example.com/page?q=test'
    """
    try:
        parsed = urlparse(url)
        existing = parse_qs(parsed.query, keep_blank_values=True)

        # Update with new params
        for key, value in params.items():
            existing[key] = [value]

        new_query = urlencode(existing, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    except Exception:
        return url


def remove_query_params(url: str, params: list[str]) -> str:
    """
    Remove query parameters from a URL.

    Args:
        url: Original URL.
        params: Parameter names to remove.

    Returns:
        URL with parameters removed.

    Example:
        >>> remove_query_params("https://example.com?a=1&b=2", ["a"])
        'https://example.com?b=2'
    """
    try:
        parsed = urlparse(url)
        existing = parse_qs(parsed.query, keep_blank_values=True)

        for param in params:
            existing.pop(param, None)

        new_query = urlencode(existing, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    except Exception:
        return url


def get_query_params(url: str) -> dict[str, list[str]]:
    """
    Extract query parameters from a URL.

    Args:
        url: URL string.

    Returns:
        Dictionary of parameter name → list of values.
    """
    try:
        parsed = urlparse(url)
        return parse_qs(parsed.query, keep_blank_values=True)
    except Exception:
        return {}


def set_fragment(url: str, fragment: str) -> str:
    """Set or update the URL fragment."""
    try:
        parsed = urlparse(url)
        return urlunparse(parsed._replace(fragment=fragment))
    except Exception:
        return url


def remove_fragment(url: str) -> str:
    """Remove the URL fragment."""
    try:
        parsed = urlparse(url)
        return urlunparse(parsed._replace(fragment=""))
    except Exception:
        return url


# ══════════════════════════════════════════════════════════════
# Pattern Matching
# ══════════════════════════════════════════════════════════════

def url_matches_pattern(url: str, pattern: str) -> bool:
    """
    Check if a URL matches a glob pattern.

    Args:
        url: URL or path to check.
        pattern: Glob pattern (e.g., '/docs/*', '*.pdf').

    Returns:
        True if the URL matches the pattern.

    Example:
        >>> url_matches_pattern("/docs/guide", "/docs/*")
        True
        >>> url_matches_pattern("https://example.com/file.pdf", "*.pdf")
        True
    """
    # Try matching against full URL
    if fnmatch.fnmatch(url, pattern):
        return True

    # Try matching against path only
    try:
        path = urlparse(url).path
        if fnmatch.fnmatch(path, pattern):
            return True
    except Exception:
        pass

    return False


def url_matches_regex(url: str, pattern: str) -> bool:
    """
    Check if a URL matches a regex pattern.

    Args:
        url: URL to check.
        pattern: Regex pattern.

    Returns:
        True if the URL matches.
    """
    try:
        return bool(re.search(pattern, url, re.IGNORECASE))
    except re.error:
        return False


def filter_urls(
    urls: list[str],
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    """
    Filter URLs by include/exclude glob patterns.

    Args:
        urls: List of URLs.
        include_patterns: Patterns to include (empty = include all).
        exclude_patterns: Patterns to exclude.

    Returns:
        Filtered list of URLs.
    """
    result: list[str] = []

    for url in urls:
        # Include check
        if include_patterns:
            if not any(url_matches_pattern(url, p) for p in include_patterns):
                continue

        # Exclude check
        if exclude_patterns:
            if any(url_matches_pattern(url, p) for p in exclude_patterns):
                continue

        result.append(url)

    return result


# ══════════════════════════════════════════════════════════════
# Special URLs
# ══════════════════════════════════════════════════════════════

def get_robots_url(url: str) -> str:
    """
    Get the robots.txt URL for a website.

    Args:
        url: Any URL on the website.

    Returns:
        robots.txt URL.

    Example:
        >>> get_robots_url("https://example.com/page")
        'https://example.com/robots.txt'
    """
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    except Exception:
        return ""


def get_sitemap_url(url: str) -> str:
    """
    Get the default sitemap.xml URL for a website.

    Args:
        url: Any URL on the website.

    Returns:
        sitemap.xml URL.

    Example:
        >>> get_sitemap_url("https://example.com/page")
        'https://example.com/sitemap.xml'
    """
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    except Exception:
        return ""


def get_favicon_url(url: str) -> str:
    """
    Get the default favicon URL for a website.

    Args:
        url: Any URL on the website.

    Returns:
        favicon.ico URL.
    """
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    except Exception:
        return ""


def get_origin(url: str) -> str:
    """
    Get the origin (scheme + host) of a URL.

    Args:
        url: URL string.

    Returns:
        Origin string (e.g., 'https://example.com').
    """
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════
# Encoding
# ══════════════════════════════════════════════════════════════

def encode_url(url: str) -> str:
    """
    Percent-encode special characters in a URL.

    Args:
        url: URL string.

    Returns:
        Encoded URL.
    """
    try:
        parsed = urlparse(url)
        # Encode path
        path = quote(parsed.path, safe="/:@!$&'()*+,;=")
        # Encode query
        query = quote(parsed.query, safe="=&")
        return urlunparse(parsed._replace(path=path, query=query))
    except Exception:
        return url


def decode_url(url: str) -> str:
    """
    Decode percent-encoded characters in a URL.

    Args:
        url: Encoded URL string.

    Returns:
        Decoded URL.
    """
    return unquote(url)


# ══════════════════════════════════════════════════════════════
# Comparison & Deduplication
# ══════════════════════════════════════════════════════════════

def urls_equal(url_a: str, url_b: str) -> bool:
    """
    Check if two URLs are equivalent after normalization.

    Args:
        url_a: First URL.
        url_b: Second URL.

    Returns:
        True if the URLs are equivalent.
    """
    return normalize_url(url_a) == normalize_url(url_b)


def deduplicate_urls(urls: list[str]) -> list[str]:
    """
    Remove duplicate URLs (after normalization), preserving order.

    Args:
        urls: List of URLs.

    Returns:
        Deduplicated list.
    """
    seen: set[str] = set()
    result: list[str] = []

    for url in urls:
        normalized = normalize_url(url)
        if normalized not in seen:
            seen.add(normalized)
            result.append(url)

    return result


# ══════════════════════════════════════════════════════════════
# Path Utilities
# ══════════════════════════════════════════════════════════════

def get_path(url: str) -> str:
    """
    Extract the path component from a URL.

    Args:
        url: URL string.

    Returns:
        Path string (e.g., '/docs/guide').
    """
    try:
        return urlparse(url).path or "/"
    except Exception:
        return "/"


def get_path_segments(url: str) -> list[str]:
    """
    Extract path segments from a URL.

    Args:
        url: URL string.

    Returns:
        List of path segments.

    Example:
        >>> get_path_segments("https://example.com/docs/guide/intro")
        ['docs', 'guide', 'intro']
    """
    path = get_path(url)
    return [seg for seg in path.split("/") if seg]


def get_path_depth(url: str) -> int:
    """
    Get the depth of a URL path.

    Args:
        url: URL string.

    Returns:
        Path depth (number of segments).

    Example:
        >>> get_path_depth("https://example.com/docs/guide")
        2
    """
    return len(get_path_segments(url))


def get_file_extension(url: str) -> str:
    """
    Extract the file extension from a URL path.

    Args:
        url: URL string.

    Returns:
        File extension (e.g., '.pdf'), or empty string.

    Example:
        >>> get_file_extension("https://example.com/file.pdf")
        '.pdf'
    """
    path = get_path(url)
    last_segment = path.split("/")[-1]

    if "." in last_segment:
        ext = "." + last_segment.rsplit(".", 1)[-1].lower()
        # Filter out very long "extensions" (likely not real)
        if len(ext) <= 10:
            return ext

    return ""


def is_file_url(url: str) -> bool:
    """
    Check if a URL points to a file (has a file extension).

    Args:
        url: URL string.

    Returns:
        True if the URL appears to point to a file.
    """
    ext = get_file_extension(url)
    file_extensions = {
        ".pdf", ".zip", ".tar", ".gz", ".doc", ".docx",
        ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
        ".mp3", ".mp4", ".avi", ".mov", ".webm",
        ".css", ".js", ".json", ".xml", ".txt",
        ".exe", ".dmg", ".iso", ".apk",
    }
    return ext in file_extensions