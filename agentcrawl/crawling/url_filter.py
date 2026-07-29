r"""
AgentCrawl — URL Filter (Extended)
======================================

Extended URL filtering with regex support, robots.txt parsing,
URL normalization, validation, and pre-built filter presets.

This module extends the base URLFilter from crawling/base.py with:

    - Regex pattern support (in addition to glob)
    - Robots.txt rule parsing and enforcement
    - URL normalization and canonicalization
    - URL validation (scheme, domain, path)
    - Pre-built filter presets (docs, blog, api, etc.)
    - Pattern compilation and caching
    - Query parameter filtering
    - Fragment handling

Usage:
    from agentcrawl.crawling.url_filter import (
        URLFilter,              # Re-exported from base
        AdvancedURLFilter,      # Regex + glob + robots.txt
        URLNormalizer,          # URL canonicalization
        RobotsTxtParser,        # robots.txt parser
        URLValidator,           # URL validation
        FilterPreset,           # Pre-built presets
    )

    # Standard filtering
    filter = URLFilter(
        include_patterns=["/docs/*"],
        exclude_patterns=["/blog/*"],
        same_domain=True,
    )

    # Advanced with regex
    filter = AdvancedURLFilter(
        include_regex=[r"/docs/[\w-]+"],
        exclude_regex=[r"\.(pdf|zip|tar)$"],
        respect_robots=True,
    )
    filter.load_robots("https://example.com/robots.txt")

    # URL normalization
    normalizer = URLNormalizer()
    canonical = normalizer.normalize("https://example.com/page/?utm_source=twitter#section")
    # → "https://example.com/page"

    # Presets
    filter = FilterPreset.docs()
    filter = FilterPreset.api()
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import (
    parse_qs,
    urlencode,
    urlparse,
    urlunparse,
)

# Re-export base URLFilter
from agentcrawl.crawling.base import URLFilter

logger = logging.getLogger("agentcrawl.crawling.url_filter")


# ══════════════════════════════════════════════════════════════
# URL Normalizer
# ══════════════════════════════════════════════════════════════

class URLNormalizer:
    """
    Normalizes URLs to a canonical form for deduplication.

    Handles:
        - Lowercasing scheme and host
        - Removing default ports (80, 443)
        - Removing fragments (#)
        - Removing tracking query parameters (utm_*, fbclid, etc.)
        - Sorting query parameters
        - Removing trailing slashes
        - Decoding unreserved percent-encoded characters
        - Removing duplicate slashes in path

    Args:
        remove_fragment: Remove URL fragments.
        remove_tracking_params: Remove tracking query parameters.
        sort_query_params: Sort query parameters alphabetically.
        remove_trailing_slash: Remove trailing slashes.
        lowercase_host: Lowercase the hostname.
        remove_default_port: Remove default ports (80/443).
        custom_remove_params: Additional query params to remove.

    Example:
        >>> normalizer = URLNormalizer()
        >>> normalizer.normalize("HTTPS://Example.COM/page/?utm_source=tw#top")
        'https://example.com/page'
    """

    # Tracking parameters to remove by default
    TRACKING_PARAMS: set[str] = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term",
        "utm_content", "utm_id", "utm_cid", "utm_reader",
        "fbclid", "gclid", "gclsrc", "dclid", "msclkid",
        "mc_cid", "mc_eid", "yclid", "twclid",
        "ref", "referrer", "source",
        "_ga", "_gid", "_gl",
        "igshid", "s_kwcid",
    }

    def __init__(
        self,
        remove_fragment: bool = True,
        remove_tracking_params: bool = True,
        sort_query_params: bool = True,
        remove_trailing_slash: bool = True,
        lowercase_host: bool = True,
        remove_default_port: bool = True,
        custom_remove_params: list[str] | None = None,
    ):
        self._remove_fragment = remove_fragment
        self._remove_tracking_params = remove_tracking_params
        self._sort_query_params = sort_query_params
        self._remove_trailing_slash = remove_trailing_slash
        self._lowercase_host = lowercase_host
        self._remove_default_port = remove_default_port
        self._custom_remove_params = set(custom_remove_params or [])

    def normalize(self, url: str) -> str:
        """
        Normalize a URL to canonical form.

        Args:
            url: URL to normalize.

        Returns:
            Normalized URL string.
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
        if self._lowercase_host:
            host = host.lower()

        # Remove www prefix
        if host.startswith("www."):
            host = host[4:]

        # Port
        port = parsed.port
        if self._remove_default_port:
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
        if self._remove_trailing_slash and path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        # Ensure leading slash
        if not path:
            path = "/"

        # Query
        query = parsed.query
        if query:
            query = self._normalize_query(query)

        # Fragment
        fragment = "" if self._remove_fragment else parsed.fragment

        return urlunparse((scheme, netloc, path, "", query, fragment))

    def _normalize_query(self, query: str) -> str:
        """Normalize query string."""
        params = parse_qs(query, keep_blank_values=True)

        # Remove tracking params
        if self._remove_tracking_params or self._custom_remove_params:
            remove_set = self.TRACKING_PARAMS | self._custom_remove_params
            params = {
                k: v for k, v in params.items()
                if k.lower() not in remove_set
                and not any(k.lower().startswith(p) for p in ("utm_", "_ga", "fb"))
            }

        if not params:
            return ""

        # Sort params
        if self._sort_query_params:
            sorted_params = sorted(params.items())
        else:
            sorted_params = list(params.items())

        return urlencode(sorted_params, doseq=True)

    def normalize_batch(self, urls: list[str]) -> list[str]:
        """Normalize a batch of URLs."""
        return [self.normalize(u) for u in urls]

    def deduplicate(self, urls: list[str]) -> list[str]:
        """Normalize and deduplicate URLs, preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for url in urls:
            normalized = self.normalize(url)
            if normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def __repr__(self) -> str:
        return (
            f"URLNormalizer(fragment={self._remove_fragment}, "
            f"tracking={self._remove_tracking_params})"
        )


# ══════════════════════════════════════════════════════════════
# Robots.txt Parser
# ══════════════════════════════════════════════════════════════

@dataclass
class RobotsRule:
    """A single robots.txt rule."""
    path: str
    allowed: bool
    pattern: re.Pattern[str] | None = None

    def matches(self, path: str) -> bool:
        """Check if a path matches this rule."""
        if self.pattern:
            return bool(self.pattern.search(path))
        return path.startswith(self.path)


class RobotsTxtParser:
    """
    Parses robots.txt and provides URL allowance checking.

    Supports:
        - User-agent specific rules
        - Allow / Disallow directives
        - Wildcard patterns (* and $)
        - Sitemap references
        - Crawl-delay directive

    Args:
        user_agent: User-agent to match rules for.

    Example:
        >>> parser = RobotsTxtParser(user_agent="AgentCrawl")
        >>> await parser.fetch("https://example.com/robots.txt")
        >>> parser.is_allowed("/docs/guide")
        True
        >>> parser.is_allowed("/admin/panel")
        False
        >>> parser.sitemaps
        ['https://example.com/sitemap.xml']
    """

    def __init__(self, user_agent: str = "*"):
        self._user_agent = user_agent.lower()
        self._rules: list[RobotsRule] = []
        self._sitemaps: list[str] = []
        self._crawl_delay: float | None = None
        self._loaded = False

    @property
    def sitemaps(self) -> list[str]:
        """Sitemap URLs referenced in robots.txt."""
        return list(self._sitemaps)

    @property
    def crawl_delay(self) -> float | None:
        """Crawl-delay value (if specified)."""
        return self._crawl_delay

    @property
    def is_loaded(self) -> bool:
        """Whether robots.txt has been loaded."""
        return self._loaded

    async def fetch(self, robots_url: str) -> bool:
        """
        Fetch and parse robots.txt from a URL.

        Args:
            robots_url: Full URL to robots.txt.

        Returns:
            True if fetched and parsed successfully.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    self.parse(resp.text)
                    return True
                elif resp.status_code == 404:
                    # No robots.txt — everything allowed
                    self._loaded = True
                    return True
        except Exception as e:
            logger.debug("Robots.txt fetch failed: %s", e)

        return False

    def parse(self, content: str) -> None:
        """
        Parse robots.txt content.

        Args:
            content: Raw robots.txt text.
        """
        self._rules.clear()
        self._sitemaps.clear()
        self._crawl_delay = None

        current_agents: list[str] = []
        in_matching_group = False

        for line in content.splitlines():
            # Remove comments
            line = line.split("#", 1)[0].strip()
            if not line:
                continue

            # Parse directive
            if ":" not in line:
                continue

            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()

            if key == "user-agent":
                agent = value.lower()
                if not current_agents or (current_agents and self._rules):
                    # New group
                    current_agents = [agent]
                    in_matching_group = (
                        agent == "*" or agent == self._user_agent
                        or self._user_agent.startswith(agent)
                    )
                else:
                    current_agents.append(agent)
                    if agent == "*" or agent == self._user_agent:
                        in_matching_group = True

            elif key == "disallow" and in_matching_group:
                if value:
                    pattern = self._path_to_regex(value)
                    self._rules.append(RobotsRule(
                        path=value,
                        allowed=False,
                        pattern=pattern,
                    ))
                # Empty Disallow = allow all (no rule added)

            elif key == "allow" and in_matching_group:
                if value:
                    pattern = self._path_to_regex(value)
                    self._rules.append(RobotsRule(
                        path=value,
                        allowed=True,
                        pattern=pattern,
                    ))

            elif key == "sitemap":
                if value:
                    self._sitemaps.append(value)

            elif key == "crawl-delay" and in_matching_group:
                try:
                    self._crawl_delay = float(value)
                except ValueError:
                    pass

        self._loaded = True

    def is_allowed(self, path: str) -> bool:
        """
        Check if a path is allowed by robots.txt rules.

        Uses longest-match-wins strategy. If Allow and Disallow
        have the same length, Allow wins.

        Args:
            path: URL path to check (e.g., '/docs/guide').

        Returns:
            True if the path is allowed.
        """
        if not self._loaded:
            return True

        if not self._rules:
            return True

        # Find matching rules
        best_match: RobotsRule | None = None
        best_length = -1

        for rule in self._rules:
            if rule.matches(path):
                rule_length = len(rule.path)
                if rule_length > best_length or (
                    rule_length == best_length and rule.allowed
                ):
                    best_match = rule
                    best_length = rule_length

        if best_match is None:
            return True

        return best_match.allowed

    @staticmethod
    def _path_to_regex(path: str) -> re.Pattern[str] | None:
        """Convert a robots.txt path pattern to regex."""
        if "*" not in path and "$" not in path:
            return None

        # Escape regex special chars except * and $
        regex = ""
        for char in path:
            if char == "*":
                regex += ".*"
            elif char == "$":
                regex += "$"
            else:
                regex += re.escape(char)

        try:
            return re.compile(regex)
        except re.error:
            return None

    def __repr__(self) -> str:
        return (
            f"RobotsTxtParser(rules={len(self._rules)}, "
            f"sitemaps={len(self._sitemaps)}, "
            f"loaded={self._loaded})"
        )


# ══════════════════════════════════════════════════════════════
# URL Validator
# ══════════════════════════════════════════════════════════════

class URLValidator:
    """
    Validates URLs for crawlability.

    Checks scheme, domain, path, and extension validity.

    Args:
        allowed_schemes: Allowed URL schemes.
        blocked_domains: Domains to always block.
        blocked_extensions: File extensions to block.
        max_url_length: Maximum URL length.
        allow_localhost: Whether to allow localhost URLs.
        allow_ip_addresses: Whether to allow IP address URLs.

    Example:
        >>> validator = URLValidator()
        >>> validator.is_valid("https://example.com/page")
        True
        >>> validator.is_valid("ftp://example.com/file")
        False
        >>> validator.is_valid("https://example.com/image.png")
        False
    """

    DEFAULT_BLOCKED_EXTENSIONS: set[str] = {
        ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".ico", ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm",
        ".exe", ".dmg", ".iso", ".bin", ".apk",
        ".xml", ".json", ".csv", ".txt", ".rss", ".atom",
        ".map", ".webmanifest",
    }

    def __init__(
        self,
        allowed_schemes: set[str] | None = None,
        blocked_domains: set[str] | None = None,
        blocked_extensions: set[str] | None = None,
        max_url_length: int = 2048,
        allow_localhost: bool = False,
        allow_ip_addresses: bool = False,
    ):
        self._allowed_schemes = allowed_schemes or {"http", "https"}
        self._blocked_domains = blocked_domains or set()
        self._blocked_extensions = blocked_extensions or self.DEFAULT_BLOCKED_EXTENSIONS
        self._max_url_length = max_url_length
        self._allow_localhost = allow_localhost
        self._allow_ip_addresses = allow_ip_addresses

        # IP address pattern
        self._ip_pattern = re.compile(
            r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
        )

    def is_valid(self, url: str) -> tuple[bool, str]:
        """
        Validate a URL.

        Args:
            url: URL to validate.

        Returns:
            Tuple of (is_valid, reason).
        """
        if not url or not url.strip():
            return False, "Empty URL"

        if len(url) > self._max_url_length:
            return False, f"URL too long ({len(url)} > {self._max_url_length})"

        try:
            parsed = urlparse(url)
        except Exception:
            return False, "URL parse error"

        # Scheme
        if parsed.scheme not in self._allowed_schemes:
            return False, f"Scheme '{parsed.scheme}' not allowed"

        # Host
        if not parsed.hostname:
            return False, "No hostname"

        hostname = parsed.hostname.lower()

        # Localhost
        if not self._allow_localhost:
            if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                return False, "Localhost not allowed"

        # IP addresses
        if not self._allow_ip_addresses:
            if self._ip_pattern.match(hostname):
                return False, "IP address not allowed"

        # Blocked domains
        if hostname in self._blocked_domains:
            return False, f"Domain '{hostname}' is blocked"

        for blocked in self._blocked_domains:
            if hostname.endswith(f".{blocked}"):
                return False, f"Domain '{hostname}' is blocked"

        # Extension
        path_lower = parsed.path.lower()
        for ext in self._blocked_extensions:
            if path_lower.endswith(ext):
                return False, f"Extension '{ext}' is blocked"

        return True, "OK"

    def is_valid_simple(self, url: str) -> bool:
        """Simple validation check (returns bool only)."""
        valid, _ = self.is_valid(url)
        return valid

    def filter_urls(self, urls: list[str]) -> list[str]:
        """Filter a list of URLs, returning only valid ones."""
        return [u for u in urls if self.is_valid_simple(u)]

    def __repr__(self) -> str:
        return (
            f"URLValidator(schemes={self._allowed_schemes}, "
            f"blocked_ext={len(self._blocked_extensions)})"
        )


# ══════════════════════════════════════════════════════════════
# Advanced URL Filter
# ══════════════════════════════════════════════════════════════

class AdvancedURLFilter(URLFilter):
    r"""
    Extended URL filter with regex support and robots.txt integration.

    Adds regex pattern matching, robots.txt enforcement, and
    URL normalization on top of the base URLFilter.

    Args:
        include_regex: Regex patterns to include.
        exclude_regex: Regex patterns to exclude.
        respect_robots: Whether to enforce robots.txt rules.
        robots_user_agent: User-agent for robots.txt matching.
        normalizer: URLNormalizer instance.
        validator: URLValidator instance.
        **kwargs: Passed to base URLFilter.

    Example:
        >>> filter = AdvancedURLFilter(
        ...     include_regex=[r"/docs/[\w-]+"],
        ...     exclude_regex=[r"\.(pdf|zip)$"],
        ...     respect_robots=True,
        ... )
        >>> await filter.load_robots("https://example.com")
        >>> filter.is_allowed("https://example.com/docs/guide")
        True
    """

    def __init__(
        self,
        include_regex: list[str] | None = None,
        exclude_regex: list[str] | None = None,
        respect_robots: bool = False,
        robots_user_agent: str = "AgentCrawl",
        normalizer: URLNormalizer | None = None,
        validator: URLValidator | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)

        self._include_regex: list[re.Pattern[str]] = []
        self._exclude_regex: list[re.Pattern[str]] = []

        for pattern in (include_regex or []):
            try:
                self._include_regex.append(re.compile(pattern, re.I))
            except re.error as e:
                logger.warning("Invalid include regex '%s': %s", pattern, e)

        for pattern in (exclude_regex or []):
            try:
                self._exclude_regex.append(re.compile(pattern, re.I))
            except re.error as e:
                logger.warning("Invalid exclude regex '%s': %s", pattern, e)

        self._respect_robots = respect_robots
        self._robots = RobotsTxtParser(robots_user_agent) if respect_robots else None
        self._normalizer = normalizer or URLNormalizer()
        self._validator = validator or URLValidator()

    async def load_robots(self, base_url: str) -> bool:
        """
        Load robots.txt for a domain.

        Args:
            base_url: Website base URL.

        Returns:
            True if robots.txt was loaded.
        """
        if not self._robots:
            return False

        try:
            parsed = urlparse(base_url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            return await self._robots.fetch(robots_url)
        except Exception as e:
            logger.debug("Failed to load robots.txt: %s", e)
            return False

    def is_allowed(self, url: str, depth: int = 0) -> bool:
        """
        Check if a URL is allowed (extended with regex and robots).

        Args:
            url: URL to check.
            depth: Link depth.

        Returns:
            True if the URL passes all filters.
        """
        # Base filter check
        if not super().is_allowed(url, depth):
            return False

        # URL validation
        valid, _ = self._validator.is_valid(url)
        if not valid:
            return False

        # Regex include
        if self._include_regex:
            if not any(p.search(url) for p in self._include_regex):
                return False

        # Regex exclude
        if self._exclude_regex:
            if any(p.search(url) for p in self._exclude_regex):
                return False

        # Robots.txt
        if self._robots and self._robots.is_loaded:
            try:
                path = urlparse(url).path
                if not self._robots.is_allowed(path):
                    return False
            except Exception:
                pass

        return True

    def normalize(self, url: str) -> str:
        """Normalize a URL using the configured normalizer."""
        return self._normalizer.normalize(url)

    @property
    def robots(self) -> RobotsTxtParser | None:
        """Robots.txt parser (if enabled)."""
        return self._robots

    @property
    def crawl_delay(self) -> float | None:
        """Crawl-delay from robots.txt (if available)."""
        if self._robots:
            return self._robots.crawl_delay
        return None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "include_regex": [p.pattern for p in self._include_regex],
            "exclude_regex": [p.pattern for p in self._exclude_regex],
            "respect_robots": self._respect_robots,
            "robots_loaded": self._robots.is_loaded if self._robots else False,
        })
        return d

    def __repr__(self) -> str:
        return (
            f"AdvancedURLFilter(include_re={len(self._include_regex)}, "
            f"exclude_re={len(self._exclude_regex)}, "
            f"robots={self._respect_robots})"
        )


# ══════════════════════════════════════════════════════════════
# Filter Presets
# ══════════════════════════════════════════════════════════════

class FilterPreset:
    """
    Pre-built URL filter configurations for common use cases.

    Example:
        >>> filter = FilterPreset.docs()
        >>> filter = FilterPreset.api()
        >>> filter = FilterPreset.blog()
    """

    @classmethod
    def docs(cls, **kwargs: Any) -> AdvancedURLFilter:
        """Filter for documentation sites."""
        return AdvancedURLFilter(
            include_patterns=["/docs/*", "/documentation/*", "/guide/*", "/manual/*", "/reference/*", "/wiki/*"],
            exclude_patterns=["/blog/*", "/news/*", "/careers/*", "/about/*"],
            exclude_extensions=[".pdf", ".zip", ".mp4"],
            **kwargs,
        )

    @classmethod
    def api(cls, **kwargs: Any) -> AdvancedURLFilter:
        """Filter for API documentation."""
        return AdvancedURLFilter(
            include_patterns=["/api/*", "/docs/api/*", "/reference/*", "/endpoint/*"],
            exclude_patterns=["/blog/*", "/status/*", "/changelog/*"],
            **kwargs,
        )

    @classmethod
    def blog(cls, **kwargs: Any) -> AdvancedURLFilter:
        """Filter for blog/article content."""
        return AdvancedURLFilter(
            include_patterns=["/blog/*", "/post/*", "/article/*", "/news/*", r"/\d{4}/\d{2}/*"],
            exclude_patterns=["/category/*", "/tag/*", "/author/*", "/page/*"],
            **kwargs,
        )

    @classmethod
    def ecommerce(cls, **kwargs: Any) -> AdvancedURLFilter:
        """Filter for e-commerce product pages."""
        return AdvancedURLFilter(
            include_patterns=["/product/*", "/products/*", "/item/*", "/p/*"],
            exclude_patterns=["/cart/*", "/checkout/*", "/account/*", "/search/*", "/filter/*"],
            **kwargs,
        )

    @classmethod
    def strict(cls, **kwargs: Any) -> AdvancedURLFilter:
        """Strict filter — minimal content, no noise."""
        return AdvancedURLFilter(
            exclude_patterns=[
                "/tag/*", "/category/*", "/author/*", "/archive/*",
                "/page/*", "/search/*", "/feed/*", "/rss/*",
                "/login/*", "/signup/*", "/cart/*", "/checkout/*",
                "/admin/*", "/wp-admin/*", "/wp-content/*",
            ],
            exclude_extensions=[
                ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                ".ico", ".pdf", ".zip", ".mp3", ".mp4",
            ],
            **kwargs,
        )

    @classmethod
    def permissive(cls, **kwargs: Any) -> AdvancedURLFilter:
        """Permissive filter — allow almost everything."""
        return AdvancedURLFilter(
            exclude_extensions=[".css", ".js", ".png", ".jpg", ".gif", ".ico", ".svg"],
            **kwargs,
        )

    @classmethod
    def custom(
        cls,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        include_regex: list[str] | None = None,
        exclude_regex: list[str] | None = None,
        **kwargs: Any,
    ) -> AdvancedURLFilter:
        """Create a custom filter."""
        return AdvancedURLFilter(
            include_patterns=include or [],
            exclude_patterns=exclude or [],
            include_regex=include_regex or [],
            exclude_regex=exclude_regex or [],
            **kwargs,
        )


# ══════════════════════════════════════════════════════════════
# Re-exports
# ══════════════════════════════════════════════════════════════

__all__ = [
    "AdvancedURLFilter",
    "FilterPreset",
    "RobotsRule",
    "RobotsTxtParser",
    "URLFilter",
    "URLNormalizer",
    "URLValidator",
]
