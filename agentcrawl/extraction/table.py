"""
AgentCrawl — Table Extractor
================================

Extracts structured data from HTML tables with automatic header
detection, column type inference, and multiple output formats.

Features:
    - Automatic table detection in HTML
    - Header detection (thead, th, first row heuristics)
    - Row extraction as list of dictionaries
    - Column type inference (string, number, date, boolean, url)
    - Multiple table extraction
    - Colspan/rowspan handling
    - Output formats: JSON, CSV, Markdown, list of dicts
    - Table filtering by size, content, or selector

Usage:
    from agentcrawl.extraction.table import TableExtractor

    # Extract all tables
    extractor = TableExtractor()
    result = await extractor.extract(html=html_content)
    print(result.data)  # List of table data

    # Extract specific table
    extractor = TableExtractor(table_selector="table#pricing")
    result = await extractor.extract(html=html_content)

    # With options
    extractor = TableExtractor(
        output_format="csv",
        infer_types=True,
        min_rows=2,
    )
    result = await extractor.extract(html=html_content)

    # With CrawlerConfig
    from agentcrawl.config import CrawlerConfig
    config = CrawlerConfig(extraction=TableExtractor())
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agentcrawl.extraction.base import (
    ExtractionConfig,
    ExtractionResult,
    ExtractionStatus,
    ExtractionStrategy,
)

logger = logging.getLogger("agentcrawl.extraction.table")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class TableColumn:
    """
    Metadata about a table column.

    Attributes:
        name: Column header name.
        index: Column index (0-based).
        inferred_type: Inferred data type.
        sample_values: Sample values from the column.
        null_count: Number of empty/null cells.
    """
    name: str = ""
    index: int = 0
    inferred_type: str = "string"
    sample_values: list[str] = field(default_factory=list)
    null_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "inferred_type": self.inferred_type,
            "null_count": self.null_count,
            "sample_values": self.sample_values[:3],
        }


@dataclass
class TableData:
    """
    Extracted table data with metadata.

    Attributes:
        headers: Column header names.
        rows: List of row dictionaries (header → value).
        raw_rows: List of raw row lists (for CSV output).
        columns: Column metadata.
        row_count: Number of data rows.
        col_count: Number of columns.
        table_index: Index of the table in the document.
        table_id: HTML id attribute (if present).
        table_classes: HTML class attributes (if present).
        caption: Table caption (if present).
    """
    headers: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    raw_rows: list[list[str]] = field(default_factory=list)
    columns: list[TableColumn] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    table_index: int = 0
    table_id: str = ""
    table_classes: list[str] = field(default_factory=list)
    caption: str = ""

    def __post_init__(self) -> None:
        self.row_count = len(self.rows)
        self.col_count = len(self.headers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headers": self.headers,
            "rows": self.rows,
            "row_count": self.row_count,
            "col_count": self.col_count,
            "table_index": self.table_index,
            "table_id": self.table_id,
            "caption": self.caption,
            "columns": [c.to_dict() for c in self.columns],
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.rows, ensure_ascii=False, indent=2)

    def to_csv(self, delimiter: str = ",") -> str:
        """
        Convert to CSV string.

        Args:
            delimiter: CSV delimiter character.

        Returns:
            CSV string with headers.
        """
        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter)

        # Write headers
        writer.writerow(self.headers)

        # Write rows
        for row in self.raw_rows:
            writer.writerow(row)

        return output.getvalue()

    def to_markdown(self) -> str:
        """
        Convert to Markdown table (GFM format).

        Returns:
            Markdown table string.
        """
        if not self.headers:
            return ""

        lines: list[str] = []

        # Header row
        lines.append("| " + " | ".join(self.headers) + " |")

        # Separator row
        lines.append("| " + " | ".join(["---"] * len(self.headers)) + " |")

        # Data rows
        for row in self.raw_rows:
            # Pad row to match header count
            padded = row + [""] * (len(self.headers) - len(row))
            lines.append("| " + " | ".join(padded[:len(self.headers)]) + " |")

        return "\n".join(lines)

    def to_dataframe(self) -> Any:
        """
        Convert to a pandas DataFrame.

        Returns:
            pandas DataFrame.

        Raises:
            ImportError: If pandas is not installed.
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas is required for DataFrame conversion. "
                "Install with: pip install pandas"
            )

        return pd.DataFrame(self.rows)

    def __repr__(self) -> str:
        return (
            f"TableData(rows={self.row_count}, "
            f"cols={self.col_count}, "
            f"headers={self.headers[:3]}...)"
        )


# ══════════════════════════════════════════════════════════════
# Column Type Inference
# ══════════════════════════════════════════════════════════════

class ColumnTypeInferrer:
    """
    Infers column data types from cell values.

    Supported types:
        - integer: Whole numbers
        - float: Decimal numbers
        - boolean: true/false, yes/no, 0/1
        - date: Date-like strings
        - url: URL strings
        - email: Email addresses
        - string: Default fallback
    """

    # Patterns for type detection
    INTEGER_RE = re.compile(r"^-?\d{1,3}(,\d{3})*$|^-?\d+$")
    FLOAT_RE = re.compile(r"^-?\d+\.\d+$|^-?\d{1,3}(,\d{3})*\.\d+$")
    BOOLEAN_VALUES = {"true", "false", "yes", "no", "0", "1", "t", "f", "y", "n"}
    DATE_RE = re.compile(
        r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$|"
        r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$|"
        r"^\w+ \d{1,2},? \d{4}$|"
        r"^\d{1,2} \w+ \d{4}$"
    )
    URL_RE = re.compile(r"^https?://|^\w+\.\w{2,}")
    EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")
    CURRENCY_RE = re.compile(r"^[$€£¥]\s*-?[\d,]+\.?\d*$|^-?[\d,]+\.?\d*\s*[$€£¥]$")

    def infer(self, values: list[str]) -> str:
        """
        Infer the type of a column from its values.

        Args:
            values: List of cell values.

        Returns:
            Inferred type string.
        """
        # Filter empty values
        non_empty = [v.strip() for v in values if v.strip()]

        if not non_empty:
            return "string"

        # Check each type
        type_counts: dict[str, int] = {
            "integer": 0,
            "float": 0,
            "boolean": 0,
            "date": 0,
            "url": 0,
            "email": 0,
            "currency": 0,
        }

        for value in non_empty:
            # Remove common formatting
            clean = value.strip().lower()

            if self.INTEGER_RE.match(value.replace(",", "")):
                type_counts["integer"] += 1
            elif self.FLOAT_RE.match(value.replace(",", "")):
                type_counts["float"] += 1
            elif clean in self.BOOLEAN_VALUES:
                type_counts["boolean"] += 1
            elif self.DATE_RE.match(value):
                type_counts["date"] += 1
            elif self.URL_RE.match(value):
                type_counts["url"] += 1
            elif self.EMAIL_RE.match(value):
                type_counts["email"] += 1
            elif self.CURRENCY_RE.match(value):
                type_counts["currency"] += 1

        # Find the dominant type (> 60% of values)
        total = len(non_empty)
        threshold = total * 0.6

        for type_name, count in sorted(
            type_counts.items(), key=lambda x: x[1], reverse=True
        ):
            if count >= threshold:
                return type_name

        return "string"

    def infer_all(self, table: TableData) -> list[TableColumn]:
        """
        Infer types for all columns in a table.

        Args:
            table: TableData instance.

        Returns:
            List of TableColumn with inferred types.
        """
        columns: list[TableColumn] = []

        for col_idx, header in enumerate(table.headers):
            # Collect values for this column
            values: list[str] = []
            null_count = 0

            for row in table.raw_rows:
                if col_idx < len(row):
                    val = row[col_idx].strip()
                    values.append(val)
                    if not val:
                        null_count += 1
                else:
                    null_count += 1

            inferred_type = self.infer(values)

            columns.append(TableColumn(
                name=header,
                index=col_idx,
                inferred_type=inferred_type,
                sample_values=[v for v in values[:5] if v],
                null_count=null_count,
            ))

        return columns


# ══════════════════════════════════════════════════════════════
# Table Extractor
# ══════════════════════════════════════════════════════════════

class TableExtractor(ExtractionStrategy):
    """
    Extracts structured data from HTML tables.

    Detects tables in HTML, extracts headers and rows, infers
    column types, and outputs in multiple formats.

    Args:
        table_selector: CSS selector to target specific tables.
        output_format: Output format ('json', 'csv', 'markdown', 'dict').
        infer_types: Whether to infer column types.
        min_rows: Minimum rows for a table to be extracted.
        min_cols: Minimum columns for a table to be extracted.
        header_row: Row index to use as headers (0 = auto-detect).
        include_table_metadata: Include table ID, classes, caption.
        max_tables: Maximum number of tables to extract.
        config: Extraction configuration.

    Example:
        >>> extractor = TableExtractor(
        ...     output_format="json",
        ...     infer_types=True,
        ... )
        >>> result = await extractor.extract(html=html_with_tables)
        >>> for table in result.data:
        ...     print(f"Table: {table['row_count']} rows x {table['col_count']} cols")
    """

    method_name = "table"

    def __init__(
        self,
        table_selector: str = "table",
        output_format: str = "dict",
        infer_types: bool = True,
        min_rows: int = 1,
        min_cols: int = 1,
        header_row: int = -1,
        include_table_metadata: bool = True,
        max_tables: int = 50,
        config: ExtractionConfig | None = None,
        **kwargs: Any,
    ):
        super().__init__(config=config)

        self._table_selector = table_selector
        self._output_format = output_format
        self._infer_types = infer_types
        self._min_rows = min_rows
        self._min_cols = min_cols
        self._header_row = header_row
        self._include_table_metadata = include_table_metadata
        self._max_tables = max_tables

        self._type_inferrer = ColumnTypeInferrer()

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
        Extract tables from HTML content.

        Args:
            html: HTML content.
            markdown: Markdown content (unused).
            url: Source URL.

        Returns:
            List of table data (format depends on output_format).
        """
        if not html.strip():
            return []

        try:
            from lxml import html as lxml_html
        except ImportError:
            raise ImportError(
                "lxml is required for table extraction. "
                "Install with: pip install lxml"
            )

        try:
            tree = lxml_html.document_fromstring(html)
        except Exception as e:
            logger.error("HTML parse error: %s", e)
            return []

        # Find tables
        tables = self._find_tables(tree)

        if not tables:
            return []

        # Extract data from each table
        results: list[Any] = []

        for idx, table_el in enumerate(tables[:self._max_tables]):
            table_data = self._extract_table(table_el, idx)

            if table_data is None:
                continue

            # Apply minimum size filter
            if table_data.row_count < self._min_rows:
                continue
            if table_data.col_count < self._min_cols:
                continue

            # Infer types
            if self._infer_types:
                table_data.columns = self._type_inferrer.infer_all(table_data)

            # Convert to output format
            if self._output_format == "json":
                results.append(table_data.to_json())
            elif self._output_format == "csv":
                results.append(table_data.to_csv())
            elif self._output_format == "markdown":
                results.append(table_data.to_markdown())
            else:  # "dict"
                results.append(table_data.to_dict())

        return results

    # ──────────────────────────────────────────────────────────
    # Table Discovery
    # ──────────────────────────────────────────────────────────

    def _find_tables(self, tree: Any) -> list[Any]:
        """
        Find table elements in the HTML tree.

        Args:
            tree: lxml element tree.

        Returns:
            List of table elements.
        """
        try:
            from lxml.cssselect import CSSSelector
            css = CSSSelector(self._table_selector)
            return css(tree)
        except Exception as e:
            logger.debug("Table selector error: %s", e)
            # Fallback: find all tables
            return list(tree.iter("table"))

    # ──────────────────────────────────────────────────────────
    # Table Extraction
    # ──────────────────────────────────────────────────────────

    def _extract_table(self, table_el: Any, table_index: int) -> TableData | None:
        """
        Extract data from a single table element.

        Args:
            table_el: lxml table element.
            table_index: Index of the table in the document.

        Returns:
            TableData instance, or None if extraction fails.
        """
        # Extract metadata
        table_id = table_el.get("id", "")
        table_classes = table_el.get("class", "").split()

        caption_el = table_el.find(".//caption")
        caption = caption_el.text_content().strip() if caption_el is not None else ""

        # Extract all rows
        all_rows = self._extract_rows(table_el)

        if not all_rows:
            return None

        # Detect headers
        headers, data_rows = self._detect_headers(table_el, all_rows)

        if not headers:
            # Generate default headers
            max_cols = max(len(row) for row in all_rows) if all_rows else 0
            headers = [f"col_{i}" for i in range(max_cols)]
            data_rows = all_rows

        # Build row dictionaries
        row_dicts: list[dict[str, str]] = []
        for row in data_rows:
            row_dict: dict[str, str] = {}
            for col_idx, header in enumerate(headers):
                value = row[col_idx] if col_idx < len(row) else ""
                row_dict[header] = value
            row_dicts.append(row_dict)

        return TableData(
            headers=headers,
            rows=row_dicts,
            raw_rows=data_rows,
            table_index=table_index,
            table_id=table_id,
            table_classes=table_classes,
            caption=caption,
        )

    def _extract_rows(self, table_el: Any) -> list[list[str]]:
        """
        Extract all rows from a table, handling colspan/rowspan.

        Args:
            table_el: lxml table element.

        Returns:
            List of rows, each row is a list of cell texts.
        """
        rows: list[list[str]] = []

        # Track rowspan carry-over
        rowspan_carry: dict[int, str] = {}

        for tr in table_el.iter("tr"):
            row: list[str] = []
            col_idx = 0

            # Apply carried-over rowspan values
            while col_idx in rowspan_carry:
                row.append(rowspan_carry.pop(col_idx))
                col_idx += 1

            for cell in tr:
                cell_tag = cell.tag if isinstance(cell.tag, str) else ""
                if cell_tag not in ("td", "th"):
                    continue

                # Skip columns already filled by rowspan
                while col_idx in rowspan_carry:
                    row.append(rowspan_carry.pop(col_idx))
                    col_idx += 1

                text = cell.text_content().strip()
                # Normalize whitespace
                text = re.sub(r"\s+", " ", text)

                # Handle colspan
                colspan = int(cell.get("colspan", "1") or "1")
                rowspan = int(cell.get("rowspan", "1") or "1")

                # Add cell value (repeated for colspan)
                for _ in range(colspan):
                    row.append(text)

                    # Set rowspan carry for subsequent rows
                    if rowspan > 1:
                        for r in range(1, rowspan):
                            # Store for future rows
                            future_col = col_idx
                            rowspan_carry[future_col] = text

                    col_idx += 1

            # Apply any remaining carried values
            while col_idx in rowspan_carry:
                row.append(rowspan_carry.pop(col_idx))
                col_idx += 1

            if row:
                rows.append(row)

        return rows

    def _detect_headers(
        self,
        table_el: Any,
        all_rows: list[list[str]],
    ) -> tuple[list[str], list[list[str]]]:
        """
        Detect header row and separate from data rows.

        Strategy:
            1. Check for <thead> element
            2. Check for <th> elements in first row
            3. Use header_row config if set
            4. Heuristic: first row if it looks like headers

        Args:
            table_el: lxml table element.
            all_rows: All extracted rows.

        Returns:
            Tuple of (headers, data_rows).
        """
        if not all_rows:
            return [], []

        # Strategy 1: Check for thead
        thead = table_el.find(".//thead")
        if thead is not None:
            thead_rows = self._extract_rows(thead)
            if thead_rows:
                headers = thead_rows[0]
                # Data rows = all_rows minus thead rows
                thead_count = len(thead_rows)
                data_rows = all_rows[thead_count:]
                return headers, data_rows

        # Strategy 2: Check for th in first row
        first_tr = table_el.find(".//tr")
        if first_tr is not None:
            th_cells = first_tr.findall(".//th")
            if th_cells:
                headers = [
                    re.sub(r"\s+", " ", th.text_content().strip())
                    for th in th_cells
                ]
                return headers, all_rows[1:]

        # Strategy 3: Use configured header row
        if self._header_row >= 0 and self._header_row < len(all_rows):
            headers = all_rows[self._header_row]
            data_rows = all_rows[:self._header_row] + all_rows[self._header_row + 1:]
            return headers, data_rows

        # Strategy 4: Heuristic — first row looks like headers
        if len(all_rows) >= 2:
            first_row = all_rows[0]
            # Headers are usually short, non-numeric strings
            looks_like_header = all(
                not re.match(r"^-?\d+\.?\d*$", cell.strip())
                for cell in first_row
                if cell.strip()
            )
            if looks_like_header and any(cell.strip() for cell in first_row):
                return first_row, all_rows[1:]

        # No headers detected — use all rows as data
        return [], all_rows

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "table_selector": self._table_selector,
            "output_format": self._output_format,
            "infer_types": self._infer_types,
            "min_rows": self._min_rows,
            "min_cols": self._min_cols,
            "header_row": self._header_row,
            "include_table_metadata": self._include_table_metadata,
            "max_tables": self._max_tables,
        })
        return d

    def __repr__(self) -> str:
        return (
            f"TableExtractor(selector={self._table_selector!r}, "
            f"format={self._output_format!r}, "
            f"infer_types={self._infer_types})"
        )