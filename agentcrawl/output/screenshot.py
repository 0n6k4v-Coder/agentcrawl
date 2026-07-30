"""
AgentCrawl — Screenshot Output Handler
==========================================

Handles screenshot capture, encoding, storage, and comparison
for crawl results.

Features:
    - Base64 encoding/decoding
    - Save to file (PNG, JPEG, WebP)
    - Full page and viewport screenshots
    - Element-specific screenshots
    - Screenshot comparison (pixel diff)
    - Screenshot metadata extraction
    - Thumbnail generation
    - Batch screenshot export

Usage:
    from agentcrawl.output.screenshot import ScreenshotHandler

    handler = ScreenshotHandler()

    # Save screenshot from result
    handler.save(result, "screenshot.png")

    # Decode base64 screenshot
    image_bytes = handler.decode(result.screenshot)

    # Get screenshot info
    info = handler.get_info(result.screenshot)
    print(f"Size: {info['width']}x{info['height']}")

    # Compare screenshots
    diff = handler.compare(screenshot_a, screenshot_b)
    print(f"Similarity: {diff['similarity']:.2%}")

    # Generate thumbnail
    thumb = handler.thumbnail(result.screenshot, max_width=200)
"""

from __future__ import annotations

import base64
import io
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("agentcrawl.output.screenshot")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════


@dataclass
class ScreenshotInfo:
    """
    Metadata about a screenshot.

    Attributes:
        format: Image format ('png', 'jpeg', 'webp').
        width: Image width in pixels.
        height: Image height in pixels.
        size_bytes: File size in bytes.
        base64_length: Length of base64 string.
        is_full_page: Whether this is a full-page screenshot.
    """

    format: str = "png"
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    base64_length: int = 0
    is_full_page: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "size_bytes": self.size_bytes,
            "size_kb": round(self.size_bytes / 1024, 1),
            "base64_length": self.base64_length,
            "is_full_page": self.is_full_page,
        }


@dataclass
class ScreenshotDiff:
    """
    Result of comparing two screenshots.

    Attributes:
        similarity: Similarity ratio (0.0 to 1.0).
        diff_percentage: Percentage of pixels that differ.
        diff_image_base64: Base64 of the diff image (if generated).
        width: Image width.
        height: Image height.
    """

    similarity: float = 0.0
    diff_percentage: float = 0.0
    diff_image_base64: str = ""
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "similarity": round(self.similarity, 4),
            "diff_percentage": round(self.diff_percentage, 2),
            "width": self.width,
            "height": self.height,
            "has_diff_image": bool(self.diff_image_base64),
        }


# ══════════════════════════════════════════════════════════════
# Screenshot Handler
# ══════════════════════════════════════════════════════════════


class ScreenshotHandler:
    """
    Handles screenshot capture, encoding, storage, and comparison.

    Args:
        default_format: Default image format ('png', 'jpeg', 'webp').
        default_quality: Default JPEG/WebP quality (1-100).
        output_dir: Default output directory for saved screenshots.

    Example:
        >>> handler = ScreenshotHandler()
        >>> handler.save(crawl_result, "page.png")
        >>> info = handler.get_info(crawl_result.screenshot)
        >>> print(f"{info.width}x{info.height}")
    """

    # Supported formats
    SUPPORTED_FORMATS: tuple[str, ...] = ("png", "jpeg", "jpg", "webp")

    def __init__(
        self,
        default_format: str = "png",
        default_quality: int = 80,
        output_dir: str = ".agentcrawl/screenshots",
    ):
        self._default_format = default_format
        self._default_quality = default_quality
        self._output_dir = output_dir

    # ──────────────────────────────────────────────────────────
    # Encoding / Decoding
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def encode(image_bytes: bytes) -> str:
        """
        Encode image bytes to base64 string.

        Args:
            image_bytes: Raw image bytes.

        Returns:
            Base64 encoded string.
        """
        return base64.b64encode(image_bytes).decode("ascii")

    @staticmethod
    def decode(base64_str: str) -> bytes:
        """
        Decode base64 string to image bytes.

        Handles data URI prefix (data:image/png;base64,...).

        Args:
            base64_str: Base64 encoded string.

        Returns:
            Raw image bytes.
        """
        # Strip data URI prefix if present
        if base64_str.startswith("data:"):
            # Format: data:image/png;base64,<data>
            parts = base64_str.split(",", 1)
            if len(parts) == 2:
                base64_str = parts[1]

        return base64.b64decode(base64_str)

    @staticmethod
    def to_data_uri(base64_str: str, format_: str = "png") -> str:
        """
        Convert base64 to a data URI.

        Args:
            base64_str: Base64 encoded string.
            format_: Image format.

        Returns:
            Data URI string.
        """
        mime_map = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "webp": "image/webp",
        }
        mime = mime_map.get(format_, "image/png")
        return f"data:{mime};base64,{base64_str}"

    # ──────────────────────────────────────────────────────────
    # File Operations
    # ┐─────────────────────────────────────────────────────────

    def save(
        self,
        result: Any,
        filepath: str | None = None,
        format_: str | None = None,
    ) -> str:
        """
        Save a screenshot from a CrawlResult to a file.

        Args:
            result: CrawlResult with screenshot data.
            filepath: Output file path (auto-generated if None).
            format_: Image format (inferred from filepath if None).

        Returns:
            Path to the saved file.
        """
        screenshot_b64 = getattr(result, "screenshot", "")
        if not screenshot_b64:
            raise ValueError("No screenshot data in result")

        # Determine format
        if format_ is None and filepath:
            ext = os.path.splitext(filepath)[1].lower().lstrip(".")
            format_ = ext if ext in self.SUPPORTED_FORMATS else self._default_format
        format_resolved = format_ or self._default_format
        # Generate filepath if not provided
        if filepath is None:
            url = getattr(result, "url", "screenshot")
            slug = self._url_to_slug(url)
            os.makedirs(self._output_dir, exist_ok=True)
            filepath = os.path.join(
                self._output_dir,
                f"{slug}.{format_resolved}",
            )

        # Ensure directory exists
        dir_path = os.path.dirname(filepath)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        # Decode and save
        image_bytes = self.decode(screenshot_b64)
        with open(filepath, "wb") as f:
            f.write(image_bytes)

        logger.debug("Saved screenshot: %s (%d bytes)", filepath, len(image_bytes))
        return filepath

    def save_bytes(
        self,
        image_bytes: bytes,
        filepath: str,
    ) -> str:
        """
        Save raw image bytes to a file.

        Args:
            image_bytes: Raw image bytes.
            filepath: Output file path.

        Returns:
            Path to the saved file.
        """
        dir_path = os.path.dirname(filepath)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        return filepath

    def save_batch(
        self,
        results: list[Any],
        directory: str | None = None,
        format_: str = "png",
        filename_template: str = "{index:04d}_{url_slug}.{format}",
    ) -> list[str]:
        """
        Save screenshots from multiple results.

        Args:
            results: List of CrawlResult instances.
            directory: Output directory.
            format_: Image format.
            filename_template: Filename template.

        Returns:
            List of saved file paths.
        """
        directory = directory or self._output_dir
        os.makedirs(directory, exist_ok=True)

        paths: list[str] = []
        for i, result in enumerate(results):
            screenshot_b64 = getattr(result, "screenshot", "")
            if not screenshot_b64:
                continue

            url = getattr(result, "url", f"page_{i}")
            slug = self._url_to_slug(url)

            filename = filename_template.format(
                index=i,
                url_slug=slug,
                format=format_,
            )
            filepath = os.path.join(directory, filename)

            image_bytes = self.decode(screenshot_b64)
            with open(filepath, "wb") as f:
                f.write(image_bytes)

            paths.append(filepath)

        return paths

    # ──────────────────────────────────────────────────────────
    # Info & Metadata
    # ──────────────────────────────────────────────────────────

    def get_info(self, base64_str: str) -> ScreenshotInfo:
        """
        Get metadata about a screenshot.

        Args:
            base64_str: Base64 encoded screenshot.

        Returns:
            ScreenshotInfo with dimensions and format.
        """
        if not base64_str:
            return ScreenshotInfo()

        try:
            image_bytes = self.decode(base64_str)
        except Exception:
            return ScreenshotInfo(base64_length=len(base64_str))

        # Detect format from magic bytes
        fmt = self._detect_format(image_bytes)

        # Get dimensions
        width, height = self._get_dimensions(image_bytes, fmt)

        return ScreenshotInfo(
            format=fmt,
            width=width,
            height=height,
            size_bytes=len(image_bytes),
            base64_length=len(base64_str),
        )

    def get_info_from_result(self, result: Any) -> ScreenshotInfo:
        """Get screenshot info from a CrawlResult."""
        screenshot = getattr(result, "screenshot", "")
        return self.get_info(screenshot)

    @staticmethod
    def _detect_format(image_bytes: bytes) -> str:
        """Detect image format from magic bytes."""
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        elif image_bytes[:2] == b"\xff\xd8":
            return "jpeg"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "webp"
        elif image_bytes[:3] == b"GIF":
            return "gif"
        return "unknown"

    @staticmethod
    def _get_dimensions(image_bytes: bytes, fmt: str) -> tuple[int, int]:
        """Get image dimensions from raw bytes."""
        try:
            if fmt == "png":
                # PNG: width at bytes 16-20, height at 20-24 (big-endian)
                import struct

                width = struct.unpack(">I", image_bytes[16:20])[0]
                height = struct.unpack(">I", image_bytes[20:24])[0]
                return width, height

            elif fmt == "jpeg":
                # JPEG: parse SOF markers
                return ScreenshotHandler._get_jpeg_dimensions(image_bytes)

            elif fmt == "webp":
                # WebP: dimensions at bytes 26-30
                import struct

                if len(image_bytes) >= 30:
                    width = struct.unpack("<H", image_bytes[26:28])[0] & 0x3FFF
                    height = struct.unpack("<H", image_bytes[28:30])[0] & 0x3FFF
                    return width, height

        except Exception:
            logger.debug("Error parsing WebP dimensions")

        return 0, 0

    @staticmethod
    def _get_jpeg_dimensions(data: bytes) -> tuple[int, int]:
        """Parse JPEG dimensions from SOF markers."""
        import struct

        i = 2  # Skip SOI marker
        while i < len(data) - 1:
            if data[i] != 0xFF:
                i += 1
                continue

            marker = data[i + 1]

            # SOF markers (Start of Frame)
            if marker in (0xC0, 0xC1, 0xC2, 0xC3) and i + 9 < len(data):
                height = struct.unpack(">H", data[i + 5 : i + 7])[0]
                width = struct.unpack(">H", data[i + 7 : i + 9])[0]
                return width, height

            # Skip to next marker
            if marker in (0xD8, 0xD9):  # SOI, EOI
                i += 2
            elif marker == 0xDA:  # SOS — stop
                break
            else:
                if i + 3 < len(data):
                    length = struct.unpack(">H", data[i + 2 : i + 4])[0]
                    i += 2 + length
                else:
                    break

        return 0, 0

    # ──────────────────────────────────────────────────────────
    # Comparison
    # ──────────────────────────────────────────────────────────

    def compare(
        self,
        screenshot_a: str,
        screenshot_b: str,
        generate_diff_image: bool = False,
    ) -> ScreenshotDiff:
        """
        Compare two screenshots for visual differences.

        Uses pixel-by-pixel comparison. Requires Pillow for
        diff image generation.

        Args:
            screenshot_a: First screenshot (base64).
            screenshot_b: Second screenshot (base64).
            generate_diff_image: Whether to generate a diff image.

        Returns:
            ScreenshotDiff with similarity metrics.
        """
        try:
            from PIL import Image
        except ImportError:
            logger.warning(
                "Pillow not available for screenshot comparison. Install with: pip install Pillow"
            )
            return ScreenshotDiff()

        try:
            bytes_a = self.decode(screenshot_a)
            bytes_b = self.decode(screenshot_b)

            img_a = Image.open(io.BytesIO(bytes_a)).convert("RGB")
            img_b = Image.open(io.BytesIO(bytes_b)).convert("RGB")

            # Resize to same dimensions if needed
            if img_a.size != img_b.size:
                # Use the smaller dimensions
                min_w = min(img_a.width, img_b.width)
                min_h = min(img_a.height, img_b.height)
                img_a = img_a.resize((min_w, min_h))
                img_b = img_b.resize((min_w, min_h))

            width, height = img_a.size
            total_pixels = width * height

            # Pixel-by-pixel comparison
            pixels_a = list(img_a.getdata())
            pixels_b = list(img_b.getdata())

            diff_count = 0
            diff_pixels: list[tuple[int, int, int]] = []

            for pa, pb in zip(pixels_a, pixels_b, strict=True):
                # Calculate per-pixel difference
                diff = sum(abs(a - b) for a, b in zip(pa, pb, strict=True))
                if diff > 30:  # Threshold for "different"
                    diff_count += 1
                    diff_pixels.append((255, 0, 0))  # Red for diff
                else:
                    diff_pixels.append((0, 0, 0))  # Black for same

            diff_percentage = (diff_count / max(total_pixels, 1)) * 100
            similarity = 1.0 - (diff_count / max(total_pixels, 1))

            # Generate diff image
            diff_b64 = ""
            if generate_diff_image and diff_pixels:
                diff_img = Image.new("RGB", (width, height))
                diff_img.putdata(diff_pixels)
                buffer = io.BytesIO()
                diff_img.save(buffer, format="PNG")
                diff_b64 = self.encode(buffer.getvalue())

            return ScreenshotDiff(
                similarity=similarity,
                diff_percentage=diff_percentage,
                diff_image_base64=diff_b64,
                width=width,
                height=height,
            )

        except Exception as e:
            logger.warning("Screenshot comparison failed: %s", e)
            return ScreenshotDiff()

    # ──────────────────────────────────────────────────────────
    # Thumbnail
    # ──────────────────────────────────────────────────────────

    def thumbnail(
        self,
        base64_str: str,
        max_width: int = 200,
        max_height: int = 200,
        format_: str = "png",
    ) -> str:
        """
        Generate a thumbnail from a screenshot.

        Args:
            base64_str: Base64 encoded screenshot.
            max_width: Maximum thumbnail width.
            max_height: Maximum thumbnail height.
            format_: Output format.

        Returns:
            Base64 encoded thumbnail.
        """
        try:
            from PIL import Image
        except ImportError:
            logger.warning("Pillow not available for thumbnail generation")
            return base64_str

        try:
            image_bytes = self.decode(base64_str)
            img = Image.open(io.BytesIO(image_bytes))

            # Calculate thumbnail size (maintain aspect ratio)
            img.thumbnail((max_width, max_height), getattr(Image, "Resampling", Image).LANCZOS)

            # Save to buffer
            buffer = io.BytesIO()
            save_format = "PNG" if format_ == "png" else "JPEG"
            img.save(buffer, format=save_format)

            return self.encode(buffer.getvalue())

        except Exception as e:
            logger.warning("Thumbnail generation failed: %s", e)
            return base64_str

    # ──────────────────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _url_to_slug(url: str) -> str:
        """Convert a URL to a filesystem-safe slug."""
        import re
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            path = parsed.netloc + parsed.path
        except Exception:
            path = url

        slug = re.sub(r"[^\w.-]", "_", path)
        slug = slug.strip("_")[:80]
        return slug or "screenshot"

    def has_screenshot(self, result: Any) -> bool:
        """Check if a result has screenshot data."""
        screenshot = getattr(result, "screenshot", "")
        return bool(screenshot and len(screenshot) > 100)

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_format": self._default_format,
            "default_quality": self._default_quality,
            "output_dir": self._output_dir,
        }

    def __repr__(self) -> str:
        return (
            f"ScreenshotHandler(format={self._default_format!r}, output_dir={self._output_dir!r})"
        )
