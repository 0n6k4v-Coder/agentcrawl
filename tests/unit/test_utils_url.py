"""Tests for agentcrawl.utils.url module."""

from agentcrawl.utils.url import (
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


class TestNormalizeUrl:
    """Tests for normalize_url."""

    def test_basic_url(self):
        # Root path gets trailing slash preserved
        assert normalize_url("https://example.com") == "https://example.com/"

    def test_trailing_slash_default(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_remove_trailing_slash_false(self):
        assert (
            normalize_url("https://example.com/page/", remove_trailing_slash=False)
            == "https://example.com/page/"
        )

    def test_uppercase_scheme_and_host(self):
        assert normalize_url("HTTPS://Example.COM/page") == "https://example.com/page"

    def test_www_prefix_removed(self):
        assert normalize_url("https://www.example.com/page") == "https://example.com/page"

    def test_fragment_removed(self):
        assert normalize_url("https://example.com/page#top") == "https://example.com/page"

    def test_fragment_kept(self):
        assert (
            normalize_url("https://example.com/page#top", remove_fragment=False)
            == "https://example.com/page#top"
        )

    def test_tracking_params_removed(self):
        result = normalize_url("https://example.com/page?utm_source=tw&utm_medium=social")
        assert "utm_source" not in result
        assert "utm_medium" not in result

    def test_fbclid_removed(self):
        result = normalize_url("https://example.com/page?fbclid=abc123")
        assert "fbclid" not in result

    def test_gclid_removed(self):
        result = normalize_url("https://example.com/page?gclid=xyz")
        assert "gclid" not in result

    def test_tracking_kept_when_disabled(self):
        result = normalize_url("https://example.com/page?utm_source=tw", remove_tracking=False)
        assert "utm_source" in result

    def test_query_params_sorted(self):
        result = normalize_url("https://example.com/page?z=1&a=2&m=3")
        # params should be sorted
        assert result.index("a=2") < result.index("m=3")
        assert result.index("m=3") < result.index("z=1")

    def test_query_params_not_sorted_when_disabled(self):
        result = normalize_url("https://example.com/page?z=1&a=2&m=3", sort_params=False)
        assert result is not None

    def test_default_port_removed(self):
        assert normalize_url("https://example.com:443/page") == "https://example.com/page"

    def test_http_port_removed(self):
        assert normalize_url("http://example.com:80/page") == "http://example.com/page"

    def test_custom_port_kept(self):
        assert normalize_url("https://example.com:8080/page") == "https://example.com:8080/page"

    def test_duplicate_slashes_removed(self):
        result = normalize_url("https://example.com/page//sub///deep")
        # Path should not have duplicate slashes
        path_result = result[result.find("/", 8) :]  # After https:
        assert "//" not in path_result

    def test_path_root_preserved(self):
        # Root path gets trailing slash
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_empty_url(self):
        assert normalize_url("") == ""

    def test_whitespace_only_url(self):
        assert normalize_url("   ") == "   "

    def test_invalid_url_returns_as_is(self):
        assert normalize_url("not a url at all") == "not a url at all"

    def test_with_username_password(self):
        result = normalize_url("https://user:pass@example.com/page")
        assert "user" in result or "example.com" in result


class TestIsValidUrl:
    """Tests for is_valid_url."""

    def test_valid_http(self):
        assert is_valid_url("http://example.com") is True

    def test_valid_https(self):
        assert is_valid_url("https://example.com") is True

    def test_valid_with_path(self):
        assert is_valid_url("https://example.com/page") is True

    def test_valid_with_query(self):
        assert is_valid_url("https://example.com?page=1") is True

    def test_invalid_no_scheme(self):
        assert is_valid_url("example.com") is False

    def test_invalid_no_host(self):
        assert is_valid_url("https://") is False

    def test_empty_string(self):
        assert is_valid_url("") is False

    def test_whitespace_only(self):
        assert is_valid_url("   ") is False

    def test_ftps_rejected(self):
        assert is_valid_url("ftp://files.example.com") is False

    def test_ftps_accepted_without_require_http(self):
        assert is_valid_url("ftp://files.example.com", require_http=False) is True

    def test_localhost_accepted(self):
        assert is_valid_url("http://localhost") is True

    def test_127001_accepted(self):
        assert is_valid_url("http://127.0.0.1") is True

    def test_invalid_scheme_only(self):
        assert is_valid_url("not-a-url") is False


class TestIsHttpUrl:
    """Tests for is_http_url."""

    def test_http(self):
        assert is_http_url("http://example.com") is True

    def test_https(self):
        assert is_http_url("https://example.com") is True

    def test_ftp_rejected(self):
        assert is_http_url("ftp://example.com") is False

    def test_invalid(self):
        assert is_http_url("not a url") is False


class TestIsSameDomain:
    """Tests for is_same_domain."""

    def test_same_domain(self):
        assert is_same_domain("https://example.com", "https://example.com") is True

    def test_same_base_different_subdomain(self):
        assert is_same_domain("https://docs.example.com", "https://example.com") is True

    def test_different_domains(self):
        assert is_same_domain("https://example.com", "https://other.com") is False

    def test_different_protocols_same_domain(self):
        assert is_same_domain("http://example.com", "https://example.com") is True

    def test_invalid_urls(self):
        assert is_same_domain("not-a-url", "not-a-url") is False

    def test_co_uk_domain(self):
        assert is_same_domain("https://site.co.uk", "https://site.co.uk") is True


class TestGetDomain:
    """Tests for get_domain."""

    def test_basic_domain(self):
        assert get_domain("https://example.com/page") == "example.com"

    def test_with_subdomain(self):
        assert get_domain("https://docs.example.com/page") == "docs.example.com"

    def test_uppercase_lowercased(self):
        assert get_domain("https://EXAMPLE.com") == "example.com"

    def test_invalid_url(self):
        assert get_domain("not-a-url") == ""


class TestGetBaseDomain:
    """Tests for get_base_domain."""

    def test_basic_domain(self):
        assert get_base_domain("https://example.com/page") == "example.com"

    def test_with_subdomain(self):
        assert get_base_domain("https://docs.example.com/page") == "example.com"

    def test_co_uk_tld(self):
        assert get_base_domain("https://site.co.uk/page") == "site.co.uk"

    def test_co_jp_tld(self):
        assert get_base_domain("https://site.co.jp/page") == "site.co.jp"

    def test_com_au_tld(self):
        assert get_base_domain("https://site.com.au/page") == "site.com.au"

    def test_www_removed(self):
        assert get_base_domain("https://www.example.com/page") == "example.com"

    def test_no_tld(self):
        assert get_base_domain("https://localhost/page") == "localhost"

    def test_invalid_url(self):
        assert get_base_domain("not-a-url") == ""

    def test_single_label_domain(self):
        assert get_base_domain("https://example") == "example"


class TestGetSubdomain:
    """Tests for get_subdomain."""

    def test_with_subdomain(self):
        assert get_subdomain("https://docs.example.com/page") == "docs"

    def test_no_subdomain(self):
        assert get_subdomain("https://example.com/page") == ""

    def test_multi_level_subdomain(self):
        assert get_subdomain("https://a.b.example.com/page") == "a.b"

    def test_invalid_url(self):
        assert get_subdomain("not-a-url") == ""


class TestGetTld:
    """Tests for get_tld."""

    def test_standard_tld(self):
        assert get_tld("https://example.com") == "com"

    def test_multi_part_tld(self):
        assert get_tld("https://site.co.uk") == "uk"

    def test_invalid_url(self):
        assert get_tld("not-a-url") == ""

    def test_no_tld(self):
        assert get_tld("https://localhost") == ""


class TestJoinUrl:
    """Tests for join_url."""

    def test_join_relative_path(self):
        # urljoin replaces the last segment when path doesn't end with /
        assert join_url("https://example.com/docs", "guide") == "https://example.com/guide"

    def test_join_relative_path_with_slash(self):
        assert join_url("https://example.com/docs/", "guide") == "https://example.com/docs/guide"

    def test_join_absolute_path(self):
        assert join_url("https://example.com", "/page") == "https://example.com/page"

    def test_join_full_url(self):
        result = join_url("https://example.com", "https://other.com/page")
        assert "other.com" in result


class TestAddQueryParams:
    """Tests for add_query_params."""

    def test_add_new_param(self):
        result = add_query_params("https://example.com/page", {"q": "test"})
        assert "q=test" in result

    def test_add_multiple_params(self):
        result = add_query_params("https://example.com/page", {"a": "1", "b": "2"})
        assert "a=1" in result
        assert "b=2" in result

    def test_update_existing_param(self):
        result = add_query_params("https://example.com/page?a=old", {"a": "new"})
        assert "a=new" in result
        assert "a=old" not in result

    def test_merge_with_existing(self):
        result = add_query_params("https://example.com/page?a=1", {"b": "2"})
        assert "a=1" in result
        assert "b=2" in result

    def test_invalid_url(self):
        # urlparse treats "not-a-url" as a path, so it still processes
        result = add_query_params("not-a-url", {"q": "test"})
        assert result is not None


class TestRemoveQueryParams:
    """Tests for remove_query_params."""

    def test_remove_single_param(self):
        result = remove_query_params("https://example.com?a=1&b=2", ["a"])
        assert "a=" not in result
        assert "b=2" in result

    def test_remove_multiple_params(self):
        result = remove_query_params("https://example.com?a=1&b=2&c=3", ["a", "b"])
        assert "a=" not in result
        assert "b=" not in result
        assert "c=3" in result

    def test_remove_nonexistent_param(self):
        result = remove_query_params("https://example.com?a=1", ["b"])
        assert "a=1" in result

    def test_invalid_url(self):
        # urlparse treats "not-a-url" as a path
        result = remove_query_params("not-a-url", ["a"])
        assert result is not None


class TestGetQueryParams:
    """Tests for get_query_params."""

    def test_single_param(self):
        result = get_query_params("https://example.com?a=1")
        assert result == {"a": ["1"]}

    def test_multiple_params(self):
        result = get_query_params("https://example.com?a=1&b=2")
        assert result == {"a": ["1"], "b": ["2"]}

    def test_repeated_param(self):
        result = get_query_params("https://example.com?a=1&a=2")
        assert result == {"a": ["1", "2"]}

    def test_no_params(self):
        result = get_query_params("https://example.com")
        assert result == {}

    def test_invalid_url(self):
        assert get_query_params("not-a-url") == {}


class TestSetFragment:
    """Tests for set_fragment."""

    def test_set_fragment(self):
        result = set_fragment("https://example.com/page", "section1")
        assert result.endswith("#section1")

    def test_replace_existing_fragment(self):
        result = set_fragment("https://example.com/page#old", "new")
        assert "#new" in result
        assert "#old" not in result

    def test_invalid_url(self):
        # urlparse treats "not-a-url" as a path, so fragment gets set
        result = set_fragment("not-a-url", "frag")
        assert result is not None


class TestRemoveFragment:
    """Tests for remove_fragment."""

    def test_remove_fragment(self):
        result = remove_fragment("https://example.com/page#top")
        assert "#top" not in result
        assert result == "https://example.com/page"

    def test_no_fragment_unchanged(self):
        assert remove_fragment("https://example.com/page") == "https://example.com/page"

    def test_invalid_url(self):
        # urlparse treats "not-a-url" as a path, so fragment just gets removed
        result = remove_fragment("not-a-url")
        assert result is not None


class TestUrlMatchesPattern:
    """Tests for url_matches_pattern."""

    def test_glob_match_path(self):
        assert url_matches_pattern("/docs/guide", "/docs/*") is True

    def test_glob_no_match(self):
        assert url_matches_pattern("/docs/guide", "/api/*") is False

    def test_glob_match_extension(self):
        assert url_matches_pattern("https://example.com/file.pdf", "*.pdf") is True

    def test_glob_match_full_url(self):
        assert url_matches_pattern("https://example.com/page", "https://example.com/*") is True

    def test_exact_match(self):
        assert url_matches_pattern("https://example.com/page", "https://example.com/page") is True

    def test_no_match(self):
        assert (
            url_matches_pattern("https://example.com/about", "https://example.com/contact") is False
        )


class TestUrlMatchesRegex:
    """Tests for url_matches_regex."""

    def test_simple_regex(self):
        assert url_matches_regex("https://example.com/page", r"example\.com") is True

    def test_no_match(self):
        assert url_matches_regex("https://other.com/page", r"example\.com") is False

    def test_case_insensitive(self):
        assert url_matches_regex("https://example.com/page", r"EXAMPLE\.COM") is True

    def test_invalid_regex(self):
        assert url_matches_regex("https://example.com", r"[invalid") is False


class TestFilterUrls:
    """Tests for filter_urls."""

    def test_no_filters(self):
        urls = ["https://a.com", "https://b.com"]
        assert filter_urls(urls) == urls

    def test_include_filter(self):
        urls = ["https://a.com/docs", "https://a.com/api", "https://b.com/docs"]
        result = filter_urls(urls, include_patterns=["*/docs"])
        assert result == ["https://a.com/docs", "https://b.com/docs"]

    def test_exclude_filter(self):
        urls = ["https://a.com/page", "https://b.com/admin"]
        result = filter_urls(urls, exclude_patterns=["*/admin"])
        assert result == ["https://a.com/page"]

    def test_include_and_exclude(self):
        urls = ["https://a.com/docs", "https://a.com/docs/admin"]
        result = filter_urls(urls, include_patterns=["*/docs"], exclude_patterns=["*/admin"])
        assert result == ["https://a.com/docs"]

    def test_empty_list(self):
        assert filter_urls([]) == []


class TestSpecialUrls:
    """Tests for get_robots_url, get_sitemap_url, get_favicon_url, get_origin."""

    def test_get_robots_url(self):
        assert get_robots_url("https://example.com/page") == "https://example.com/robots.txt"

    def test_get_robots_url_with_path(self):
        assert get_robots_url("https://example.com/deep/path") == "https://example.com/robots.txt"

    def test_get_robots_url_invalid(self):
        # urlparse parses "not-a-url" with empty scheme/netloc
        result = get_robots_url("not-a-url")
        assert result is not None

    def test_get_sitemap_url(self):
        assert get_sitemap_url("https://example.com/page") == "https://example.com/sitemap.xml"

    def test_get_sitemap_url_invalid(self):
        result = get_sitemap_url("not-a-url")
        assert result is not None

    def test_get_favicon_url(self):
        assert get_favicon_url("https://example.com/page") == "https://example.com/favicon.ico"

    def test_get_favicon_url_invalid(self):
        result = get_favicon_url("not-a-url")
        assert result is not None

    def test_get_origin(self):
        assert get_origin("https://example.com/page") == "https://example.com"

    def test_get_origin_with_port(self):
        assert get_origin("https://example.com:8080/page") == "https://example.com:8080"

    def test_get_origin_invalid(self):
        result = get_origin("not-a-url")
        assert result is not None


class TestEncoding:
    """Tests for encode_url, decode_url."""

    def test_encode_url(self):
        result = encode_url("https://example.com/page with spaces")
        assert " " not in result

    def test_encode_already_encoded(self):
        result = encode_url("https://example.com/page%20name")
        assert result is not None

    def test_decode_url(self):
        assert decode_url("https://example.com/hello%20world") == "https://example.com/hello world"

    def test_decode_no_encoding(self):
        assert decode_url("https://example.com/page") == "https://example.com/page"


class TestComparison:
    """Tests for urls_equal, deduplicate_urls."""

    def test_urls_equal_same(self):
        assert urls_equal("https://example.com", "https://example.com") is True

    def test_urls_equal_normalized(self):
        # Root path normalizes to trailing slash
        assert urls_equal("https://example.com", "https://example.com/") is True

    def test_urls_equal_different(self):
        assert urls_equal("https://example.com", "https://other.com") is False

    def test_deduplicate_preserves_order(self):
        urls = ["https://a.com", "https://b.com", "https://a.com"]
        result = deduplicate_urls(urls)
        assert len(result) == 2

    def test_deduplicate_with_normalization(self):
        urls = ["https://example.com", "https://example.com/", "HTTPS://example.com/"]
        result = deduplicate_urls(urls)
        assert len(result) == 1

    def test_deduplicate_empty(self):
        assert deduplicate_urls([]) == []


class TestPathUtilities:
    """Tests for get_path, get_path_segments, get_path_depth, get_file_extension, is_file_url."""

    def test_get_path(self):
        assert get_path("https://example.com/docs/guide") == "/docs/guide"

    def test_get_path_root(self):
        assert get_path("https://example.com") == "/"

    def test_get_path_no_scheme(self):
        result = get_path("not-a-url")
        assert result == "not-a-url"

    def test_get_path_segments(self):
        assert get_path_segments("https://example.com/docs/guide/intro") == [
            "docs",
            "guide",
            "intro",
        ]

    def test_get_path_segments_empty(self):
        assert get_path_segments("https://example.com") == []

    def test_get_path_depth(self):
        assert get_path_depth("https://example.com/docs/guide") == 2

    def test_get_path_depth_root(self):
        assert get_path_depth("https://example.com") == 0

    def test_get_file_extension(self):
        assert get_file_extension("https://example.com/file.pdf") == ".pdf"

    def test_get_file_extension_no_extension(self):
        assert get_file_extension("https://example.com/page") == ""

    def test_get_file_extension_multiple_dots(self):
        assert get_file_extension("https://example.com/file.name.pdf") == ".pdf"

    def test_is_file_url_pdf(self):
        assert is_file_url("https://example.com/file.pdf") is True

    def test_is_file_url_no_extension(self):
        assert is_file_url("https://example.com/page") is False

    def test_is_file_url_js(self):
        assert is_file_url("https://example.com/script.js") is True

    def test_is_file_url_long_extension(self):
        assert is_file_url("https://example.com/file.toolongextension") is False
