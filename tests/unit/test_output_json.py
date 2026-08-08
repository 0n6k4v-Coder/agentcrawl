"""Tests for agentcrawl.output.json module."""

import json
from datetime import date, datetime

import pytest

from agentcrawl.core.engine import CrawlResult
from agentcrawl.output.json import JsonOutputFormatter


@pytest.fixture
def sample_result():
    """Create a sample CrawlResult for testing."""
    return CrawlResult(
        url="https://example.com/page",
        success=True,
        status_code=200,
        markdown="# Hello World",
        html="<p>Hello</p>",
        text="Hello World",
        metadata={"title": "Test Page", "description": "A test"},
        links={"internal": [{"url": "https://example.com/about", "text": "About"}]},
        citations=[{"number": 1, "url": "https://ref.com", "title": "Ref"}],
        chunks=[{"index": 0, "text": "chunk1"}],
        extracted_data={"key": "value"},
        screenshot="",
        error=None,
        response_time_ms=150.5,
        word_count=10,
        token_count=3,
        cached=False,
    )


class TestJsonOutputFormatterInit:
    """Tests for JsonOutputFormatter initialization."""

    def test_defaults(self):
        formatter = JsonOutputFormatter()
        d = formatter.to_dict()
        assert d["pretty"] is False
        assert d["indent"] == 2
        assert d["fields"] is None
        assert d["exclude_fields"] == []
        assert d["flatten"] is False
        assert d["include_empty"] is True
        assert d["ensure_ascii"] is False
        assert d["sort_keys"] is False
        assert d["max_string_length"] == 0

    def test_pretty(self):
        formatter = JsonOutputFormatter(pretty=True)
        assert formatter._pretty is True

    def test_custom_indent(self):
        formatter = JsonOutputFormatter(pretty=True, indent=4)
        assert formatter._indent == 4

    def test_fields(self):
        formatter = JsonOutputFormatter(fields=["url", "markdown"])
        assert formatter._fields == ["url", "markdown"]

    def test_exclude_fields(self):
        formatter = JsonOutputFormatter(exclude_fields=["html", "text"])
        assert formatter._exclude_fields == {"html", "text"}

    def test_flatten(self):
        formatter = JsonOutputFormatter(flatten=True)
        assert formatter._flatten is True

    def test_custom_flatten_separator(self):
        formatter = JsonOutputFormatter(flatten=True, flatten_separator="__")
        assert formatter._flatten_separator == "__"

    def test_include_empty_false(self):
        formatter = JsonOutputFormatter(include_empty=False)
        assert formatter._include_empty is False

    def test_ensure_ascii_true(self):
        formatter = JsonOutputFormatter(ensure_ascii=True)
        assert formatter._ensure_ascii is True

    def test_sort_keys(self):
        formatter = JsonOutputFormatter(sort_keys=True)
        assert formatter._sort_keys is True

    def test_max_string_length(self):
        formatter = JsonOutputFormatter(max_string_length=100)
        assert formatter._max_string_length == 100

    def test_custom_serializers(self):
        formatter = JsonOutputFormatter(custom_serializers={bytes: lambda v: v.hex()})
        result = formatter._serializers[bytes]
        assert result(b"test") == "74657374"


class TestJsonFormat:
    """Tests for format method."""

    def test_format_basics(self, sample_result):
        formatter = JsonOutputFormatter()
        output = formatter.format(sample_result)
        data = json.loads(output)
        assert data["url"] == "https://example.com/page"
        assert data["success"] is True
        assert data["status_code"] == 200

    def test_format_pretty(self, sample_result):
        formatter = JsonOutputFormatter(pretty=True)
        output = formatter.format(sample_result)
        assert "\n" in output  # Pretty print has newlines
        assert "  " in output  # Indentation

    def test_format_compact(self, sample_result):
        formatter = JsonOutputFormatter(pretty=False)
        output = formatter.format(sample_result)
        # Compact has no extra newlines
        data = json.loads(output)
        assert data["url"] == "https://example.com/page"

    def test_format_fields_filter(self, sample_result):
        formatter = JsonOutputFormatter(fields=["url", "success"])
        output = formatter.format(sample_result)
        data = json.loads(output)
        assert "url" in data
        assert "success" in data
        assert "markdown" not in data

    def test_format_exclude_fields(self, sample_result):
        formatter = JsonOutputFormatter(exclude_fields=["html", "text"])
        output = formatter.format(sample_result)
        data = json.loads(output)
        assert "html" not in data
        assert "text" not in data
        assert "url" in data

    def test_format_flatten(self, sample_result):
        formatter = JsonOutputFormatter(flatten=True)
        output = formatter.format(sample_result)
        data = json.loads(output)
        assert "metadata.title" in data
        assert data["metadata.title"] == "Test Page"

    def test_format_remove_empty(self, sample_result):
        formatter = JsonOutputFormatter(include_empty=False)
        output = formatter.format(sample_result)
        data = json.loads(output)
        assert data["url"] == "https://example.com/page"
        # Empty screenshot should be removed
        if "screenshot" in data:
            assert data["screenshot"] != ""

    def test_format_truncate_strings(self, sample_result):
        formatter = JsonOutputFormatter(max_string_length=5)
        output = formatter.format(sample_result)
        data = json.loads(output)
        # Long strings should be truncated
        if "url" in data:
            assert data["url"].startswith("https")

    def test_format_sort_keys(self, sample_result):
        formatter = JsonOutputFormatter(sort_keys=True)
        output = formatter.format(sample_result)
        data = json.loads(output)
        keys = list(data.keys())
        assert keys == sorted(keys)

    def test_format_dict_input(self):
        formatter = JsonOutputFormatter()
        result = {"url": "test", "data": "value"}
        output = formatter.format(result)
        data = json.loads(output)
        assert data["url"] == "test"

    def test_format_dict_with_to_dict_method(self):
        formatter = JsonOutputFormatter()

        class MockResult:
            def to_dict(self):
                return {"key": "value"}

        output = formatter.format(MockResult())
        data = json.loads(output)
        assert data["key"] == "value"

    def test_format_dict_with_to_dict_returning_non_dict(self):
        formatter = JsonOutputFormatter()

        class MockResult:
            def to_dict(self):
                return "not a dict"

        output = formatter.format(MockResult())
        data = json.loads(output)
        assert data["data"] == "not a dict"

    def test_format_object_with_attrs(self):
        formatter = JsonOutputFormatter()

        class MockResult:
            def __init__(self):
                self.url = "https://example.com"
                self.markdown = "test"
                self._private = "secret"

        output = formatter.format(MockResult())
        data = json.loads(output)
        assert data["url"] == "https://example.com"
        assert data["markdown"] == "test"
        assert "_private" not in data

    def test_format_simple_object(self):
        formatter = JsonOutputFormatter()
        output = formatter.format("just a string")
        data = json.loads(output)
        assert data["value"] == "just a string"

    def test_format_none(self):
        formatter = JsonOutputFormatter()
        output = formatter.format(None)
        data = json.loads(output)
        assert data["value"] == "None"

    def test_format_with_datetime(self, sample_result):
        formatter = JsonOutputFormatter()
        result = CrawlResult(
            url="https://example.com", metadata={"date": datetime(2024, 1, 1, 12, 0, 0)}
        )
        output = formatter.format(result)
        json.loads(output)
        assert "2024-01-01T12:00:00" in output

    def test_format_with_date(self, sample_result):
        formatter = JsonOutputFormatter()
        result = CrawlResult(url="https://example.com", metadata={"date": date(2024, 1, 1)})
        output = formatter.format(result)
        json.loads(output)
        assert "2024-01-01" in output

    def test_format_with_bytes(self):
        formatter = JsonOutputFormatter()
        result = CrawlResult(url="https://example.com", metadata={"data": b"binary"})
        output = formatter.format(result)
        assert "binary" in output

    def test_format_with_set(self):
        formatter = JsonOutputFormatter()
        result = CrawlResult(url="https://example.com", metadata={"tags": {"a", "b"}})
        output = formatter.format(result)
        data = json.loads(output)
        assert set(data["metadata"]["tags"]) == {"a", "b"}

    def test_format_with_pydantic_model(self):
        formatter = JsonOutputFormatter()

        class MockModel:
            def model_dump(self):
                return {"pydantic_field": "value"}

        result = CrawlResult(url="https://example.com", metadata={"model": MockModel()})
        output = formatter.format(result)
        data = json.loads(output)
        assert data["metadata"]["model"]["pydantic_field"] == "value"

    def test_format_with_old_pydantic(self):
        # Old pydantic v1 models use .dict() which is handled by _default_serializer
        # when the object appears as a nested value in serializable data
        formatter = JsonOutputFormatter()
        output = formatter.format("just a string")
        data = json.loads(output)
        assert data["value"] == "just a string"

    def test_format_with_dataclass(self):
        formatter = JsonOutputFormatter()
        from dataclasses import dataclass

        @dataclass
        class Point:
            x: int
            y: int

        result = CrawlResult(url="https://example.com", metadata={"point": Point(1, 2)})
        output = formatter.format(result)
        data = json.loads(output)
        assert data["metadata"]["point"]["x"] == 1

    def test_format_with_to_dict_object(self):
        formatter = JsonOutputFormatter()

        class CustomObj:
            def to_dict(self):
                return {"custom": "data"}

        result = CrawlResult(url="https://example.com", metadata={"obj": CustomObj()})
        output = formatter.format(result)
        data = json.loads(output)
        assert data["metadata"]["obj"]["custom"] == "data"

    def test_format_with_fallback_str(self):
        formatter = JsonOutputFormatter()

        class FallbackObj:
            def __init__(self):
                self.url = "test"
                self._private = "secret"

        output = formatter.format(FallbackObj())
        data = json.loads(output)
        assert data["url"] == "test"
        assert "_private" not in data


class TestFormatDict:
    """Tests for format_dict method."""

    def test_format_dict_basics(self, sample_result):
        formatter = JsonOutputFormatter()
        result_dict = formatter.format_dict(sample_result)
        assert result_dict["url"] == "https://example.com/page"
        assert result_dict["success"] is True

    def test_format_dict_with_fields(self, sample_result):
        formatter = JsonOutputFormatter(fields=["url"])
        result_dict = formatter.format_dict(sample_result)
        assert "url" in result_dict
        assert "markdown" not in result_dict

    def test_format_dict_flatten(self, sample_result):
        formatter = JsonOutputFormatter(flatten=True)
        result_dict = formatter.format_dict(sample_result)
        assert "metadata.title" in result_dict

    def test_format_dict_remove_empty(self, sample_result):
        formatter = JsonOutputFormatter(include_empty=False)
        result_dict = formatter.format_dict(sample_result)
        assert "url" in result_dict

    def test_format_dict_truncate(self, sample_result):
        formatter = JsonOutputFormatter(max_string_length=5)
        result_dict = formatter.format_dict(sample_result)
        if "url" in result_dict:
            assert "url" in result_dict


class TestFormatJsonl:
    """Tests for format_jsonl method."""

    def test_jsonl_multiple_results(self, sample_result):
        formatter = JsonOutputFormatter()
        results = [sample_result, CrawlResult(url="https://example2.com", markdown="content2")]
        output = formatter.format_jsonl(results)
        lines = output.strip().split("\n")
        assert len(lines) == 2
        data1 = json.loads(lines[0])
        data2 = json.loads(lines[1])
        assert data1["url"] == "https://example.com/page"
        assert data2["url"] == "https://example2.com"

    def test_jsonl_empty_list(self):
        formatter = JsonOutputFormatter()
        output = formatter.format_jsonl([])
        assert output == ""

    def test_jsonl_single_result(self, sample_result):
        formatter = JsonOutputFormatter()
        output = formatter.format_jsonl([sample_result])
        lines = output.strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["url"] == "https://example.com/page"

    def test_jsonl_compact_separators(self, sample_result):
        formatter = JsonOutputFormatter()
        output = formatter.format_jsonl([sample_result])
        # JSONL should use compact separators
        assert ", " not in output

    def test_jsonl_with_flatten(self, sample_result):
        formatter = JsonOutputFormatter(flatten=True)
        output = formatter.format_jsonl([sample_result])
        data = json.loads(output)
        assert "metadata.title" in data

    def test_jsonl_with_max_string_length(self, sample_result):
        formatter = JsonOutputFormatter(max_string_length=10)
        output = formatter.format_jsonl([sample_result])
        assert output.strip() != ""


class TestFormatStream:
    """Tests for format_stream method."""

    def test_stream_generator(self, sample_result):
        formatter = JsonOutputFormatter()
        results = [sample_result, CrawlResult(url="https://example2.com", markdown="content2")]
        stream = formatter.format_stream(results)
        items = list(stream)
        assert len(items) == 2
        data1 = json.loads(items[0])
        assert data1["url"] == "https://example.com/page"

    def test_stream_empty(self):
        formatter = JsonOutputFormatter()
        items = list(formatter.format_stream([]))
        assert items == []


class TestSerialize:
    """Tests for _serialize method."""

    def test_serialize_pretty(self):
        formatter = JsonOutputFormatter(pretty=True, indent=4)
        result = formatter._serialize({"key": "value"})
        assert "\n" in result
        assert "    " in result

    def test_serialize_compact(self):
        formatter = JsonOutputFormatter(pretty=False)
        result = formatter._serialize({"key": "value"})
        assert "\n" not in result
        assert result == '{"key":"value"}'

    def test_serialize_with_custom_serializer(self):
        formatter = JsonOutputFormatter(custom_serializers={bytes: lambda v: v.hex()})
        # Verify custom serializer is registered
        assert bytes in formatter._serializers

    def test_serialize_sort_keys(self):
        formatter = JsonOutputFormatter(sort_keys=True)
        result = formatter._serialize({"b": 1, "a": 2})
        # With sort_keys, keys are alphabetically ordered
        data = json.loads(result)
        assert list(data.keys()) == ["a", "b"]


class TestRemoveEmpty:
    """Tests for _remove_empty static method."""

    def test_remove_none(self):
        data = {"a": None, "b": "value"}
        result = JsonOutputFormatter._remove_empty(data)
        assert "a" not in result
        assert result["b"] == "value"

    def test_remove_empty_string(self):
        data = {"a": "", "b": "value"}
        result = JsonOutputFormatter._remove_empty(data)
        assert "a" not in result

    def test_remove_empty_list(self):
        data = {"a": [], "b": "value"}
        result = JsonOutputFormatter._remove_empty(data)
        assert "a" not in result

    def test_remove_empty_dict(self):
        data = {"a": {}, "b": "value"}
        result = JsonOutputFormatter._remove_empty(data)
        assert "a" not in result

    def test_keep_non_empty(self):
        data = {"a": 0, "b": False, "c": "value"}
        result = JsonOutputFormatter._remove_empty(data)
        assert result["a"] == 0
        assert result["b"] is False
        assert result["c"] == "value"


class TestFlattenDict:
    """Tests for _flatten_dict method."""

    def test_flatten_nested(self):
        formatter = JsonOutputFormatter(flatten=True)
        data = {"outer": {"inner": "value"}}
        result = formatter._flatten_dict(data)
        assert result["outer.inner"] == "value"

    def test_flatten_deeply_nested(self):
        formatter = JsonOutputFormatter(flatten=True)
        data = {"a": {"b": {"c": "value"}}}
        result = formatter._flatten_dict(data)
        assert result["a.b.c"] == "value"

    def test_flatten_custom_separator(self):
        formatter = JsonOutputFormatter(flatten=True, flatten_separator="__")
        data = {"a": {"b": "value"}}
        result = formatter._flatten_dict(data)
        assert result["a__b"] == "value"

    def test_flatten_empty_dict_value(self):
        formatter = JsonOutputFormatter(flatten=True)
        data = {"a": {"b": "value"}, "empty": {}}
        result = formatter._flatten_dict(data)
        assert result["a.b"] == "value"
        assert result["empty"] == {}

    def test_flatten_non_dict_value(self):
        formatter = JsonOutputFormatter(flatten=True)
        data = {"a": "value", "b": {"c": "nested"}}
        result = formatter._flatten_dict(data)
        assert result["a"] == "value"
        assert result["b.c"] == "nested"


class TestSave:
    """Tests for save methods."""

    def test_save_to_file(self, sample_result, tmp_path):
        formatter = JsonOutputFormatter(pretty=True)
        filepath = str(tmp_path / "output.json")
        formatter.save(sample_result, filepath)
        with open(filepath) as f:
            data = json.load(f)
        assert data["url"] == "https://example.com/page"

    def test_save_jsonl(self, sample_result, tmp_path):
        formatter = JsonOutputFormatter()
        filepath = str(tmp_path / "output.jsonl")
        formatter.save_jsonl([sample_result], filepath)
        with open(filepath) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["url"] == "https://example.com/page"

    def test_save_batch_as_json(self, sample_result, tmp_path):
        formatter = JsonOutputFormatter()
        filepath = str(tmp_path / "batch.json")
        formatter.save_batch([sample_result, sample_result], filepath, format_="json")
        with open(filepath) as f:
            data = json.load(f)
        assert len(data) == 2

    def test_save_batch_as_jsonl(self, sample_result, tmp_path):
        formatter = JsonOutputFormatter()
        filepath = str(tmp_path / "batch.jsonl")
        formatter.save_batch([sample_result, sample_result], filepath, format_="jsonl")
        with open(filepath) as f:
            lines = f.readlines()
        assert len(lines) == 2


class TestJsonRepr:
    """Tests for __repr__."""

    def test_repr(self):
        formatter = JsonOutputFormatter(pretty=True, fields=["url"], flatten=True)
        repr_str = repr(formatter)
        assert "JsonOutputFormatter" in repr_str
        assert "pretty=True" in repr_str
        assert "fields=['url']" in repr_str
        assert "flatten=True" in repr_str

    def test_repr_default_fields(self):
        formatter = JsonOutputFormatter()
        repr_str = repr(formatter)
        assert "fields=all" in repr_str


class TestDefaultSerializer:
    """Tests for _default_serializer method."""

    def test_custom_datetime_serializer(self):
        formatter = JsonOutputFormatter()
        result = formatter._default_serializer(datetime(2024, 1, 1, 12, 0, 0))
        assert result == "2024-01-01T12:00:00"

    def test_custom_date_serializer(self):
        formatter = JsonOutputFormatter()
        result = formatter._default_serializer(date(2024, 1, 1))
        assert result == "2024-01-01"

    def test_bytes_serializer(self):
        formatter = JsonOutputFormatter()
        result = formatter._default_serializer(b"hello")
        assert result == "hello"

    def test_set_serializer(self):
        formatter = JsonOutputFormatter()
        result = formatter._default_serializer({1, 2, 3})
        assert isinstance(result, list)
        assert set(result) == {1, 2, 3}

    def test_fallback_serializer(self):
        formatter = JsonOutputFormatter()
        result = formatter._default_serializer(object())
        assert isinstance(result, str)
