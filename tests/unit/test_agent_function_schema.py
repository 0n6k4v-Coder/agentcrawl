"""Tests for agentcrawl.agent.function_schema module."""
import json

import pytest

from agentcrawl.agent.function_schema import (
    TOOL_DEFINITIONS,
    _filter_tools,
    _to_class_name,
    export_schemas_json,
    get_all_schemas,
    get_anthropic_tools_schema,
    get_crewai_tools,
    get_langchain_tools,
    get_mcp_tools_schema,
    get_openai_functions_schema,
    get_openai_tools_schema,
    get_tool_definition,
    get_tool_names,
)


EXPECTED_TOOL_NAMES = ["web_scrape", "web_crawl", "web_search", "web_map", "web_extract", "web_screenshot", "web_batch_scrape"]


class TestToolDefinitions:
    """Tests for TOOL_DEFINITIONS."""

    def test_definitions_count(self):
        assert len(TOOL_DEFINITIONS) == 7

    def test_all_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_all_names_present(self):
        names = [t["name"] for t in TOOL_DEFINITIONS]
        for expected in EXPECTED_TOOL_NAMES:
            assert expected in names

    def test_parameters_structure(self):
        for tool in TOOL_DEFINITIONS:
            params = tool["parameters"]
            assert "type" in params
            assert params["type"] == "object"
            assert "properties" in params
            assert "required" in params

    def test_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            for req in tool["parameters"]["required"]:
                assert req in tool["parameters"]["properties"]


class TestFilterTools:
    """Tests for _filter_tools."""

    def test_none_returns_all(self):
        result = _filter_tools(None)
        assert len(result) == 7
        assert result == TOOL_DEFINITIONS

    def test_filter_single(self):
        result = _filter_tools(["web_scrape"])
        assert len(result) == 1
        assert result[0]["name"] == "web_scrape"

    def test_filter_multiple(self):
        result = _filter_tools(["web_scrape", "web_crawl"])
        assert len(result) == 2
        names = [t["name"] for t in result]
        assert "web_scrape" in names
        assert "web_crawl" in names

    def test_filter_preserves_order(self):
        result = _filter_tools(["web_scrape", "web_crawl"])
        assert result[0]["name"] == "web_scrape"
        assert result[1]["name"] == "web_crawl"

    def test_filter_invalid_name(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            _filter_tools(["nonexistent_tool"])

    def test_filter_mixed_valid_invalid(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            _filter_tools(["web_scrape", "nonexistent"])


class TestOpenaiSchema:
    """Tests for get_openai_tools_schema and get_openai_functions_schema."""

    def test_openai_all_tools(self):
        result = get_openai_tools_schema()
        assert len(result) == 7
        for item in result:
            assert item["type"] == "function"
            assert "function" in item
            assert "name" in item["function"]
            assert "description" in item["function"]
            assert "parameters" in item["function"]

    def test_openai_filtered(self):
        result = get_openai_tools_schema(["web_scrape"])
        assert len(result) == 1
        assert result[0]["function"]["name"] == "web_scrape"

    def test_openai_legacy_all(self):
        result = get_openai_functions_schema()
        assert len(result) == 7
        for item in result:
            assert "name" in item
            assert "description" in item
            assert "parameters" in item
            # Legacy format doesn't have "type": "function" wrapper
            assert "type" not in item

    def test_openai_legacy_filtered(self):
        result = get_openai_functions_schema(["web_crawl"])
        assert len(result) == 1
        assert result[0]["name"] == "web_crawl"


class TestAnthropicSchema:
    """Tests for get_anthropic_tools_schema."""

    def test_anthropic_all(self):
        result = get_anthropic_tools_schema()
        assert len(result) == 7
        for item in result:
            assert "name" in item
            assert "description" in item
            assert "input_schema" in item

    def test_anthropic_filtered(self):
        result = get_anthropic_tools_schema(["web_search"])
        assert len(result) == 1
        assert result[0]["name"] == "web_search"


class TestLangchainSchema:
    """Tests for get_langchain_tools."""

    def test_langchain_all(self):
        result = get_langchain_tools()
        assert len(result) == 7
        for item in result:
            assert "name" in item
            assert "description" in item
            assert "args_schema" in item
            assert "metadata" in item
            assert item["metadata"]["tool_type"] == "agentcrawl"
            assert item["metadata"]["requires_browser"] is True

    def test_langchain_filtered(self):
        result = get_langchain_tools(["web_map"])
        assert len(result) == 1
        assert result[0]["name"] == "web_map"

    def test_langchain_args_schema_structure(self):
        result = get_langchain_tools(["web_scrape"])
        args_schema = result[0]["args_schema"]
        assert "type" in args_schema
        assert args_schema["type"] == "object"
        assert "properties" in args_schema
        assert "required" in args_schema
        assert "url" in args_schema["properties"]
        assert "url" in args_schema["required"]

    def test_langchain_args_schema_has_defaults(self):
        result = get_langchain_tools(["web_scrape"])
        props = result[0]["args_schema"]["properties"]
        assert props["output_format"]["default"] == "markdown"
        assert props["include_links"]["default"] is True
        assert props["stealth"]["default"] is True

    def test_langchain_args_schema_enum(self):
        result = get_langchain_tools(["web_scrape"])
        props = result[0]["args_schema"]["properties"]
        assert "enum" in props["output_format"]

    def test_langchain_args_schema_items(self):
        result = get_langchain_tools(["web_batch_scrape"])
        props = result[0]["args_schema"]["properties"]
        assert "items" in props["urls"]


class TestCrewaiSchema:
    """Tests for get_crewai_tools."""

    def test_crewai_all(self):
        result = get_crewai_tools()
        assert len(result) == 7
        for item in result:
            assert "name" in item
            assert "description" in item
            assert "parameters" in item
            assert "method" in item
            # Name should be PascalCase
            assert item["name"][0].isupper()

    def test_crewai_filtered(self):
        result = get_crewai_tools(["web_screenshot"])
        assert len(result) == 1
        assert result[0]["method"] == "web_screenshot"

    def test_crewai_class_names(self):
        result = get_crewai_tools()
        names = [item["name"] for item in result]
        assert "WebScrape" in names
        assert "WebCrawl" in names
        assert "WebSearch" in names
        assert "WebMap" in names
        assert "WebExtract" in names
        assert "WebScreenshot" in names
        assert "WebBatchScrape" in names


class TestMcpSchema:
    """Tests for get_mcp_tools_schema."""

    def test_mcp_all(self):
        result = get_mcp_tools_schema()
        assert len(result) == 7
        for item in result:
            assert "name" in item
            assert "description" in item
            assert "inputSchema" in item

    def test_mcp_filtered(self):
        result = get_mcp_tools_schema(["web_extract"])
        assert len(result) == 1
        assert result[0]["name"] == "web_extract"


class TestAllSchemas:
    """Tests for get_all_schemas."""

    def test_all_schemas(self):
        schemas = get_all_schemas()
        assert "openai" in schemas
        assert "openai_legacy" in schemas
        assert "anthropic" in schemas
        assert "langchain" in schemas
        assert "crewai" in schemas
        assert "mcp" in schemas
        assert len(schemas["openai"]) == 7

    def test_all_schemas_filtered(self):
        schemas = get_all_schemas(["web_scrape"])
        assert len(schemas["openai"]) == 1
        assert len(schemas["anthropic"]) == 1
        assert len(schemas["langchain"]) == 1
        assert len(schemas["crewai"]) == 1
        assert len(schemas["mcp"]) == 1


class TestToolNamesAndDefinition:
    """Tests for get_tool_names and get_tool_definition."""

    def test_get_tool_names(self):
        names = get_tool_names()
        assert len(names) == 7
        for expected in EXPECTED_TOOL_NAMES:
            assert expected in names

    def test_get_tool_definition_existing(self):
        result = get_tool_definition("web_scrape")
        assert result is not None
        assert result["name"] == "web_scrape"
        assert "description" in result
        assert "parameters" in result

    def test_get_tool_definition_not_found(self):
        result = get_tool_definition("nonexistent")
        assert result is None

    def test_get_tool_definition_all_present(self):
        for name in EXPECTED_TOOL_NAMES:
            result = get_tool_definition(name)
            assert result is not None
            assert result["name"] == name


class TestExportSchemasJson:
    """Tests for export_schemas_json."""

    def test_export_openai(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        export_schemas_json(filepath, fmt="openai")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 7
        assert data[0]["type"] == "function"

    def test_export_anthropic(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        export_schemas_json(filepath, fmt="anthropic")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 7
        assert "input_schema" in data[0]

    def test_export_langchain(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        export_schemas_json(filepath, fmt="langchain")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 7
        assert "args_schema" in data[0]

    def test_export_crewai(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        export_schemas_json(filepath, fmt="crewai")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 7
        assert "method" in data[0]

    def test_export_mcp(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        export_schemas_json(filepath, fmt="mcp")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 7
        assert "inputSchema" in data[0]

    def test_export_openai_legacy(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        export_schemas_json(filepath, fmt="openai_legacy")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 7
        assert "type" not in data[0]

    def test_export_filtered(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        export_schemas_json(filepath, ["web_scrape"], fmt="openai")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 1

    def test_export_invalid_format(self, tmp_path):
        filepath = str(tmp_path / "schemas.json")
        with pytest.raises(ValueError, match="Unknown format"):
            export_schemas_json(filepath, fmt="invalid")


class TestClassName:
    """Tests for _to_class_name."""

    def test_snake_case(self):
        assert _to_class_name("web_scrape") == "WebScrape"

    def test_multiple_underscores(self):
        assert _to_class_name("web_batch_scrape") == "WebBatchScrape"

    def test_single_word(self):
        assert _to_class_name("search") == "Search"

    def test_all_caps(self):
        assert _to_class_name("api") == "Api"
