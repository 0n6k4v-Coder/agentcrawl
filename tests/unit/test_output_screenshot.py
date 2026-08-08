"""Tests for agentcrawl.output.screenshot module."""

import base64
import io
import os

import pytest

from agentcrawl.output.screenshot import (
    ScreenshotDiff,
    ScreenshotHandler,
    ScreenshotInfo,
)

# ─── Helpers ────────────────────────────────────────────────────


def make_png_bytes(width=100, height=100, color=(255, 0, 0)):
    """Generate minimal PNG bytes of given dimensions."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg_bytes(width=100, height=100, color=(0, 255, 0)):
    """Generate minimal JPEG bytes of given dimensions."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def sample_result():
    """Create a CrawlResult-like object with screenshot data."""

    class MockResult:
        def __init__(self):
            self.url = "https://example.com/page"
            self.screenshot = base64.b64encode(make_png_bytes(100, 100)).decode("ascii")

    return MockResult()


@pytest.fixture
def sample_png_b64():
    """Base64-encoded PNG bytes."""
    return base64.b64encode(make_png_bytes(100, 100)).decode("ascii")


@pytest.fixture
def sample_jpeg_b64():
    """Base64-encoded JPEG bytes."""
    return base64.b64encode(make_jpeg_bytes(80, 60)).decode("ascii")


# ─── ScreenshotInfo ──────────────────────────────────────────────────


class TestScreenshotInfo:
    """Tests for ScreenshotInfo dataclass."""

    def test_defaults(self):
        info = ScreenshotInfo()
        assert info.format == "png"
        assert info.width == 0
        assert info.height == 0
        assert info.size_bytes == 0
        assert info.base64_length == 0
        assert info.is_full_page is False

    def test_custom_values(self):
        info = ScreenshotInfo(
            format="jpeg",
            width=1920,
            height=1080,
            size_bytes=50000,
            base64_length=70000,
            is_full_page=True,
        )
        assert info.format == "jpeg"
        assert info.width == 1920
        assert info.height == 1080
        assert info.size_bytes == 50000

    def test_to_dict(self):
        info = ScreenshotInfo(
            format="png",
            width=100,
            height=200,
            size_bytes=1000,
            base64_length=5000,
            is_full_page=True,
        )
        d = info.to_dict()
        assert d["format"] == "png"
        assert d["width"] == 100
        assert d["height"] == 200
        assert d["size_bytes"] == 1000
        assert d["size_kb"] == 1.0  # 1000 / 1024 = 0.977... rounded to 1.0
        assert d["base64_length"] == 5000
        assert d["is_full_page"] is True


# ─── ScreenshotDiff ──────────────────────────────────────────────────


class TestScreenshotDiff:
    """Tests for ScreenshotDiff dataclass."""

    def test_defaults(self):
        diff = ScreenshotDiff()
        assert diff.similarity == 0.0
        assert diff.diff_percentage == 0.0
        assert diff.diff_image_base64 == ""
        assert diff.width == 0
        assert diff.height == 0

    def test_custom_values(self):
        diff = ScreenshotDiff(
            similarity=0.95,
            diff_percentage=5.0,
            diff_image_base64="base64data",
            width=100,
            height=200,
        )
        assert diff.similarity == 0.95
        assert diff.diff_percentage == 5.0

    def test_to_dict(self):
        diff = ScreenshotDiff(
            similarity=0.95,
            diff_percentage=5.0,
            diff_image_base64="base64data",
            width=100,
            height=200,
        )
        d = diff.to_dict()
        assert d["similarity"] == 0.95
        assert d["diff_percentage"] == 5.0
        assert d["width"] == 100
        assert d["height"] == 200
        assert d["has_diff_image"] is True

    def test_to_dict_no_diff_image(self):
        diff = ScreenshotDiff()
        d = diff.to_dict()
        assert d["has_diff_image"] is False


# ─── ScreenshotHandler Init ─────────────────────────────────────────


class TestScreenshotHandlerInit:
    """Tests for ScreenshotHandler initialization."""

    def test_defaults(self):
        handler = ScreenshotHandler()
        assert handler._default_format == "png"
        assert handler._default_quality == 80
        assert handler._output_dir == ".agentcrawl/screenshots"

    def test_custom_format(self):
        handler = ScreenshotHandler(default_format="jpeg")
        assert handler._default_format == "jpeg"

    def test_custom_quality(self):
        handler = ScreenshotHandler(default_quality=95)
        assert handler._default_quality == 95

    def test_custom_output_dir(self):
        handler = ScreenshotHandler(output_dir="./screenshots")
        assert handler._output_dir == "./screenshots"

    def test_supported_formats(self):
        assert "png" in ScreenshotHandler.SUPPORTED_FORMATS
        assert "jpeg" in ScreenshotHandler.SUPPORTED_FORMATS
        assert "jpg" in ScreenshotHandler.SUPPORTED_FORMATS
        assert "webp" in ScreenshotHandler.SUPPORTED_FORMATS

    def test_to_dict(self):
        handler = ScreenshotHandler(default_format="jpeg", default_quality=90, output_dir="./shots")
        d = handler.to_dict()
        assert d["default_format"] == "jpeg"
        assert d["default_quality"] == 90
        assert d["output_dir"] == "./shots"

    def test_repr(self):
        handler = ScreenshotHandler()
        repr_str = repr(handler)
        assert "ScreenshotHandler" in repr_str
        assert "png" in repr_str


# ─── Encode/Decode ───────────────────────────────────────────────


class TestEncodeDecode:
    """Tests for encode/decode/to_data_uri methods."""

    def test_encode(self):
        handler = ScreenshotHandler()
        raw = b"hello"
        result = handler.encode(raw)
        assert result == base64.b64encode(raw).decode("ascii")

    def test_decode(self):
        handler = ScreenshotHandler()
        raw = b"hello world"
        encoded = base64.b64encode(raw).decode("ascii")
        result = handler.decode(encoded)
        assert result == raw

    def test_decode_with_data_uri(self):
        handler = ScreenshotHandler()
        raw = b"hello"
        encoded = base64.b64encode(raw).decode("ascii")
        data_uri = f"data:image/png;base64,{encoded}"
        result = handler.decode(data_uri)
        assert result == raw

    def test_decode_data_uri_no_comma(self):
        handler = ScreenshotHandler()
        # Data URI without comma - should return full b64decode
        result = handler.decode("aGVsbG8=")
        assert result == b"hello"

    def test_to_data_uri(self):
        handler = ScreenshotHandler()
        encoded = "abc123"
        result = handler.to_data_uri(encoded, format_="png")
        assert result == f"data:image/png;base64,{encoded}"

    def test_to_data_uri_jpeg(self):
        handler = ScreenshotHandler()
        result = handler.to_data_uri("abc", format_="jpeg")
        assert result == "data:image/jpeg;base64,abc"

    def test_to_data_uri_jpg(self):
        handler = ScreenshotHandler()
        result = handler.to_data_uri("abc", format_="jpg")
        assert result == "data:image/jpeg;base64,abc"

    def test_to_data_uri_webp(self):
        handler = ScreenshotHandler()
        result = handler.to_data_uri("abc", format_="webp")
        assert result == "data:image/webp;base64,abc"

    def test_to_data_uri_unknown_format(self):
        handler = ScreenshotHandler()
        result = handler.to_data_uri("abc", format_="gif")
        assert result == "data:image/png;base64,abc"


# ─── Save Methods ────────────────────────────────────────────────


class TestSaveMethods:
    """Tests for save, save_bytes, save_batch methods."""

    def test_save_to_file(self, sample_result, tmp_path):
        handler = ScreenshotHandler()
        filepath = str(tmp_path / "screenshot.png")
        result = handler.save(sample_result, filepath)
        assert result == filepath
        assert os.path.exists(filepath)
        with open(filepath, "rb") as f:
            content = f.read()
        assert content == make_png_bytes(100, 100)

    def test_save_auto_filepath(self, sample_result, tmp_path):
        handler = ScreenshotHandler(output_dir=str(tmp_path))
        filepath = handler.save(sample_result)
        assert os.path.exists(filepath)
        assert filepath.endswith(".png")

    def test_save_with_format(self, sample_result, tmp_path):
        handler = ScreenshotHandler()
        filepath = str(tmp_path / "screenshot.jpeg")
        handler.save(sample_result, filepath)
        assert os.path.exists(filepath)

    def test_save_no_screenshot_raises(self, tmp_path):
        handler = ScreenshotHandler()
        result = simple_result_mock()
        filepath = str(tmp_path / "screenshot.png")
        with pytest.raises(ValueError, match="No screenshot"):
            handler.save(result, filepath)

    def test_save_bytes(self, tmp_path):
        handler = ScreenshotHandler()
        filepath = str(tmp_path / "image.png")
        raw = make_png_bytes(50, 50)
        result = handler.save_bytes(raw, filepath)
        assert result == filepath
        assert os.path.exists(filepath)
        with open(filepath, "rb") as f:
            assert f.read() == raw

    def test_save_bytes_nested_dir(self, tmp_path):
        handler = ScreenshotHandler()
        filepath = str(tmp_path / "nested" / "dir" / "image.png")
        raw = make_png_bytes(50, 50)
        handler.save_bytes(raw, filepath)
        assert os.path.exists(filepath)

    def test_save_batch(self, tmp_path):
        handler = ScreenshotHandler()
        results = [
            sample_result_for_url("https://example.com/1"),
            sample_result_for_url("https://example.com/2"),
        ]
        directory = str(tmp_path / "batch")
        paths = handler.save_batch(results, directory)
        assert len(paths) == 2
        for p in paths:
            assert os.path.exists(p)

    def test_save_batch_default_dir(self, sample_result, tmp_path):
        handler = ScreenshotHandler(output_dir=str(tmp_path))
        paths = handler.save_batch([sample_result])
        assert len(paths) == 1
        assert os.path.exists(paths[0])

    def test_save_batch_skips_no_screenshot(self, tmp_path):
        handler = ScreenshotHandler()
        result_no_shot = simple_result_mock()
        result_no_shot.screenshot = ""
        paths = handler.save_batch([result_no_shot], str(tmp_path / "batch"))
        assert len(paths) == 0

    def test_save_batch_custom_template(self, tmp_path):
        handler = ScreenshotHandler()
        results = [sample_result_for_url("https://example.com/1")]
        paths = handler.save_batch(
            results,
            str(tmp_path),
            filename_template="{index:02d}_{url_slug}.png",
        )
        assert len(paths) == 1
        assert "00_" in paths[0]


def sample_result_for_url(url):
    """Helper to create a mock CrawlResult with screenshot at given URL."""

    class MockResult:
        def __init__(self, url):
            self.url = url
            self.screenshot = base64.b64encode(make_png_bytes(50, 50)).decode("ascii")

    return MockResult(url)


def simple_result_mock():
    """Helper to create a simple mock CrawlResult."""

    class MockResult:
        def __init__(self):
            self.url = "https://example.com"
            self.screenshot = ""

    return MockResult()


# ─── Get Info ──────────────────────────────────────────────────


class TestGetInfo:
    """Tests for get_info and get_info_from_result methods."""

    def test_get_info_png(self, sample_png_b64):
        handler = ScreenshotHandler()
        info = handler.get_info(sample_png_b64)
        assert info.format == "png"
        assert info.width == 100
        assert info.height == 100
        assert info.size_bytes > 0
        assert info.base64_length == len(sample_png_b64)

    def test_get_info_empty(self):
        handler = ScreenshotHandler()
        info = handler.get_info("")
        assert info.format == "png"
        assert info.width == 0
        assert info.base64_length == 0

    def test_get_info_invalid_base64(self):
        handler = ScreenshotHandler()
        info = handler.get_info("not_valid_base64!!!")
        assert info.base64_length == len("not_valid_base64!!!")
        assert info.width == 0
        assert info.height == 0

    def test_get_info_from_result(self, sample_result):
        handler = ScreenshotHandler()
        info = handler.get_info_from_result(sample_result)
        assert info.format == "png"
        assert info.width == 100

    def test_get_info_from_result_no_screenshot(self):
        handler = ScreenshotHandler()
        result = simple_result_mock()
        info = handler.get_info_from_result(result)
        assert info.base64_length == 0

    def test_get_info_jpeg(self, sample_jpeg_b64):
        handler = ScreenshotHandler()
        info = handler.get_info(sample_jpeg_b64)
        assert info.format == "jpeg"

    def test_get_info_webp(self):
        from PIL import Image

        img = Image.new("RGB", (50, 50), color=(0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="WEBP")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")

        handler = ScreenshotHandler()
        info = handler.get_info(encoded)
        assert info.format == "webp"

    def test_get_info_gif(self):
        from PIL import Image

        img = Image.new("RGB", (50, 50), color=(0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format="GIF")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")

        handler = ScreenshotHandler()
        info = handler.get_info(encoded)
        assert info.format == "gif"

    def test_get_info_unknown_format(self):
        handler = ScreenshotHandler()
        # Random bytes that don't match any format
        raw = b"\x00\x00\x00\x00\x00"
        encoded = base64.b64encode(raw).decode("ascii")
        info = handler.get_info(encoded)
        assert info.format == "unknown"

    def test_get_info_truncated_png(self):
        handler = ScreenshotHandler()
        # PNG with truncated dimension bytes - format detected but dims are 0
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        encoded = base64.b64encode(raw).decode("ascii")
        info = handler.get_info(encoded)
        assert info.format == "png"
        assert info.width == 0
        assert info.height == 0


# ─── Format Detection ──────────────────────────────────────────


class TestDetectFormat:
    """Tests for _detect_format method."""

    def test_detect_png(self):
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        assert ScreenshotHandler._detect_format(raw) == "png"

    def test_detect_jpeg(self):
        raw = b"\xff\xd8" + b"\x00" * 10
        assert ScreenshotHandler._detect_format(raw) == "jpeg"

    def test_detect_webp(self):
        raw = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 20
        assert ScreenshotHandler._detect_format(raw) == "webp"

    def test_detect_gif(self):
        raw = b"GIF87a" + b"\x00" * 10
        assert ScreenshotHandler._detect_format(raw) == "gif"

    def test_detect_unknown(self):
        raw = b"\x00\x01\x02\x03\x04"
        assert ScreenshotHandler._detect_format(raw) == "unknown"

    def test_detect_empty(self):
        assert ScreenshotHandler._detect_format(b"") == "unknown"


# ─── Dimensions ────────────────────────────────────────────────


class TestDimensions:
    """Tests for _get_dimensions method."""

    def test_get_png_dimensions(self):
        raw = make_png_bytes(200, 150)
        width, height = ScreenshotHandler._get_dimensions(raw, "png")
        assert width == 200
        assert height == 150

    def test_get_jpeg_dimensions(self):
        from PIL import Image

        img = Image.new("RGB", (320, 240), color=(255, 128, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw = buf.getvalue()
        width, height = ScreenshotHandler._get_dimensions(raw, "jpeg")
        assert width == 320
        assert height == 240

    def test_get_webp_dimensions(self):
        from PIL import Image

        img = Image.new("RGB", (400, 300), color=(0, 128, 255))
        buf = io.BytesIO()
        img.save(buf, format="WEBP")
        raw = buf.getvalue()
        width, height = ScreenshotHandler._get_dimensions(raw, "webp")
        assert width == 400
        assert height == 300

    def test_get_dimensions_unknown_format(self):
        width, height = ScreenshotHandler._get_dimensions(b"\x00" * 20, "unknown")
        assert width == 0
        assert height == 0

    def test_get_dimensions_truncated_png(self):
        raw = b"\x89PNG\r\n\x1a\n"  # PNG signature but no dimension data
        width, height = ScreenshotHandler._get_dimensions(raw, "png")
        assert width == 0
        assert height == 0

    def test_get_jpeg_dimensions_invalid(self):
        raw = b"\xff\xd8" + b"\x00" * 20  # Not valid JPEG structure
        width, height = ScreenshotHandler._get_dimensions(raw, "jpeg")
        assert width == 0
        assert height == 0

    def test_webp_too_short(self):
        raw = b"RIFF" + b"\x00" * 5  # Less than 30 bytes
        width, height = ScreenshotHandler._get_dimensions(raw, "webp")
        assert width == 0
        assert height == 0


# ─── JPEG Dimensions ───────────────────────────────────────────


class TestJpegDimensions:
    """Tests for _get_jpeg_dimensions method."""

    def test_get_jpeg_dimensions_valid(self):
        from PIL import Image

        img = Image.new("RGB", (640, 480), color=(128, 64, 32))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        width, height = ScreenshotHandler._get_jpeg_dimensions(buf.getvalue())
        assert width == 640
        assert height == 480

    def test_get_jpeg_dimensions_no_sof(self):
        # Bytes with SOI marker but no SOF
        raw = b"\xff\xd8\x00\x00\x00\x00"
        width, height = ScreenshotHandler._get_jpeg_dimensions(raw)
        assert width == 0
        assert height == 0

    def test_get_jpeg_dimensions_short_data(self):
        raw = b"\xff"
        width, height = ScreenshotHandler._get_jpeg_dimensions(raw)
        assert width == 0
        assert height == 0


# ─── Compare ──────────────────────────────────────────────────


class TestCompare:
    """Tests for compare method."""

    def test_compare_identical_images(self, sample_png_b64):
        handler = ScreenshotHandler()
        diff = handler.compare(sample_png_b64, sample_png_b64)
        assert diff.similarity == 1.0
        assert diff.diff_percentage == 0.0
        assert diff.width == 100
        assert diff.height == 100

    def test_compare_different_images(self):
        handler = ScreenshotHandler()
        png_a = base64.b64encode(make_png_bytes(100, 100, (255, 0, 0))).decode("ascii")
        png_b = base64.b64encode(make_png_bytes(100, 100, (0, 0, 255))).decode("ascii")
        diff = handler.compare(png_a, png_b)
        assert diff.similarity < 1.0
        assert diff.diff_percentage > 0.0

    def test_compare_with_diff_image(self, sample_png_b64):
        handler = ScreenshotHandler()
        png_a = base64.b64encode(make_png_bytes(100, 100, (255, 0, 0))).decode("ascii")
        png_b = base64.b64encode(make_png_bytes(100, 100, (0, 0, 255))).decode("ascii")
        diff = handler.compare(png_a, png_b, generate_diff_image=True)
        assert diff.diff_image_base64 != ""

    def test_compare_no_diff_image_when_identical(self, sample_png_b64):
        handler = ScreenshotHandler()
        diff = handler.compare(sample_png_b64, sample_png_b64, generate_diff_image=True)
        # For identical images, all pixels match, diff_pixels has all black pixels
        assert diff.similarity == 1.0
        assert diff.diff_percentage == 0.0

    def test_compare_different_dimensions(self):
        handler = ScreenshotHandler()
        png_a = base64.b64encode(make_png_bytes(100, 100, (255, 0, 0))).decode("ascii")
        png_b = base64.b64encode(make_png_bytes(50, 50, (0, 0, 255))).decode("ascii")
        diff = handler.compare(png_a, png_b)
        # Should resize to smaller dimensions
        assert diff.width == 50
        assert diff.height == 50

    def test_compare_invalid_base64(self):
        handler = ScreenshotHandler()
        diff = handler.compare("invalid!!!", "also_invalid!!!")
        assert diff.similarity == 0.0
        assert diff.diff_percentage == 0.0
        assert diff.diff_image_base64 == ""

    def test_compare_no_pillow(self, monkeypatch):
        """Test compare when Pillow is not available."""
        import sys

        original_pil = sys.modules.get("PIL", None)
        if original_pil:
            monkeypatch.setitem(sys.modules, "PIL", None)
        handler = ScreenshotHandler()
        diff = handler.compare("a", "b")
        # Should return empty ScreenshotDiff
        assert diff.similarity == 0.0
        if original_pil:
            monkeypatch.undo()


# ─── Thumbnail ────────────────────────────────────────────────


class TestThumbnail:
    """Tests for thumbnail method."""

    def test_thumbnail(self, sample_png_b64):
        handler = ScreenshotHandler()
        thumb_b64 = handler.thumbnail(sample_png_b64, max_width=50, max_height=50)
        assert thumb_b64 != ""
        assert len(thumb_b64) > 0
        # Thumbnail should be smaller than original
        assert len(thumb_b64) < len(sample_png_b64)

    def test_thumbnail_jpeg_output(self, sample_png_b64):
        handler = ScreenshotHandler()
        thumb = handler.thumbnail(sample_png_b64, max_width=50, max_height=50, format_="jpeg")
        assert thumb != ""

    def test_thumbnail_no_pillow(self, monkeypatch, sample_png_b64):
        """Test thumbnail when Pillow is not available."""
        import sys

        original_pil = sys.modules.get("PIL", None)
        if original_pil:
            monkeypatch.setitem(sys.modules, "PIL", None)
        handler = ScreenshotHandler()
        result = handler.thumbnail(sample_png_b64, max_width=50)
        # Should return original input
        assert result == sample_png_b64
        if original_pil:
            monkeypatch.undo()

    def test_thumbnail_invalid_data(self):
        handler = ScreenshotHandler()
        result = handler.thumbnail("invalid_base64!!!", max_width=50)
        assert result == "invalid_base64!!!"


# ─── Has Screenshot ───────────────────────────────────────────


class TestHasScreenshot:
    """Tests for has_screenshot method."""

    def test_has_screenshot(self, sample_result):
        handler = ScreenshotHandler()
        assert handler.has_screenshot(sample_result) is True

    def test_no_screenshot_empty(self):
        handler = ScreenshotHandler()
        result = simple_result_mock()
        result.screenshot = ""
        assert handler.has_screenshot(result) is False

    def test_no_screenshot_short(self):
        handler = ScreenshotHandler()
        result = simple_result_mock()
        result.screenshot = "short"  # < 100 chars
        assert handler.has_screenshot(result) is False


# ─── URL Slug ──────────────────────────────────────────────────


class TestUrlToSlug:
    """Tests for _url_to_slug method."""

    def test_url_to_slug_normal(self):
        slug = ScreenshotHandler._url_to_slug("https://example.com/page")
        assert "example.com" in slug
        assert "/" not in slug

    def test_url_to_slug_simple(self):
        slug = ScreenshotHandler._url_to_slug("example.com/page")
        assert "example.com" in slug

    def test_url_to_slug_invalid(self):
        slug = ScreenshotHandler._url_to_slug("not_a_url")
        assert slug == "not_a_url"

    def test_url_to_slug_truncation(self):
        long_url = "https://example.com/" + "a" * 100
        slug = ScreenshotHandler._url_to_slug(long_url)
        assert len(slug) <= 80

    def test_url_to_slug_empty(self):
        slug = ScreenshotHandler._url_to_slug("")
        assert slug == "screenshot"

    def test_url_to_slug_strips_underscores(self):
        slug = ScreenshotHandler._url_to_slug("https://example.com/path?query=1")
        assert slug.startswith("example.com")
