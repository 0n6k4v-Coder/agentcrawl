"""
AgentCrawl — Extract API Routes
===================================

Handles structured data extraction via the REST API.

Endpoints:
    POST /extract — Extract structured data from a URL

Supports multiple extraction methods:
    - css: CSS selector-based extraction
    - xpath: XPath expression-based extraction
    - llm: LLM-powered extraction
    - regex: Regex pattern extraction

Usage:
    Registered automatically by server/app.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("agentcrawl.server.extract")


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════

class ExtractRequest(BaseModel):
    """Request body for POST /extract."""

    url: str = Field(..., description="URL to extract data from")
    method: str = Field(
        default="css",
        description="Extraction method: css, xpath, llm, regex",
    )
    schema_def: dict[str, Any] = Field(
        default_factory=dict,
        alias="schema",
        description="Extraction schema (format depends on method)",
    )
    fields: str = Field(
        default="",
        description="Comma-separated field names (for LLM dynamic schema)",
    )
    instructions: str = Field(
        default="",
        description="Additional instructions (for LLM method)",
    )
    output_format: str = Field(
        default="markdown",
        description="Page output format before extraction",
    )
    only_main_content: bool = Field(
        default=True,
        description="Extract only main content",
    )
    cache: bool = Field(
        default=True,
        description="Enable page caching",
    )
    timeout: int = Field(
        default=30,
        description="Page timeout in seconds",
    )

    class Config:
        populate_by_name = True


# ══════════════════════════════════════════════════════════════
# Handler
# ══════════════════════════════════════════════════════════════

async def handle_extract(
    engine: Any,
    body: dict[str, Any],
) -> JSONResponse:
    """
    Handle POST /extract.

    Scrapes a URL and extracts structured data using the
    specified method and schema.

    Args:
        engine: CrawlEngine instance.
        body: Request body dictionary.

    Returns:
        JSONResponse with extracted data.
    """
    # Validate request
    try:
        request = ExtractRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid request: {e}",
                }
            },
        )

    # Check engine
    if engine is None or not engine.is_started:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "Engine not started",
                }
            },
        )

    # Validate method
    valid_methods = {"css", "xpath", "llm", "regex"}
    if request.method not in valid_methods:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_METHOD",
                    "message": (
                        f"Invalid method: '{request.method}'. "
                        f"Must be one of: {', '.join(sorted(valid_methods))}"
                    ),
                }
            },
        )

    # Build schema
    schema = _build_schema(request)
    if schema is None:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_SCHEMA",
                    "message": "A valid schema or fields parameter is required",
                }
            },
        )

    # Execute extraction
    start = time.perf_counter()

    try:
        result = await engine.extract(
            request.url,
            schema=schema,
            method=request.method,
        )
    except Exception as e:
        logger.error("Extraction failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "EXTRACTION_FAILED",
                    "message": str(e),
                }
            },
        )

    elapsed = (time.perf_counter() - start) * 1000

    # Build response
    if not result.success:
        return JSONResponse(
            status_code=200,
            content={
                "url": request.url,
                "success": False,
                "method": request.method,
                "data": None,
                "error": result.error,
                "duration_ms": round(elapsed, 2),
            },
        )

    # Serialize extracted data
    extracted_data = _serialize_extracted(result.extracted_data)

    response_data = {
        "url": request.url,
        "success": True,
        "method": request.method,
        "data": extracted_data,
        "duration_ms": round(elapsed, 2),
        "word_count": result.word_count,
    }

    logger.info(
        "Extract: %s (%s) → %s (%.0fms)",
        request.url,
        request.method,
        "ok" if result.success else "fail",
        elapsed,
    )

    return JSONResponse(status_code=200, content=response_data)


# ══════════════════════════════════════════════════════════════
# Schema Building
# ══════════════════════════════════════════════════════════════

def _build_schema(request: ExtractRequest) -> Any:
    """
    Build an extraction schema from the request.

    For CSS/XPath: uses the schema_def dict directly.
    For LLM: builds a dynamic Pydantic model from fields or schema_def.
    For Regex: uses the schema_def dict directly.

    Args:
        request: Validated request.

    Returns:
        Schema object (dict or Pydantic model), or None if invalid.
    """
    # CSS / XPath / Regex: use schema dict directly
    if request.method in ("css", "xpath", "regex"):
        if request.schema_def:
            return request.schema_def

        # For regex, allow patterns shorthand
        if request.method == "regex" and request.fields:
            patterns = {}
            for field_name in request.fields.split(","):
                field_name = field_name.strip()
                if field_name:
                    patterns[field_name] = ""  # Empty pattern — user must provide
            return {"name": "RegexExtract", "fields": [
                {"name": k, "pattern": v, "type": "all"}
                for k, v in patterns.items()
            ]}

        return None

    # LLM: build dynamic Pydantic model
    if request.method == "llm":
        # If schema_def is a JSON Schema dict, use it
        if request.schema_def and "properties" in request.schema_def:
            return request.schema_def

        # If fields are provided, build a dynamic model
        if request.fields:
            return _build_dynamic_model(request.fields)

        # If schema_def has field names, build from those
        if request.schema_def and "fields" in request.schema_def:
            field_names = [
                f.get("name", "") for f in request.schema_def["fields"]
                if isinstance(f, dict)
            ]
            if field_names:
                return _build_dynamic_model(",".join(field_names))

        return None

    return None


def _build_dynamic_model(fields_str: str) -> Any:
    """
    Build a dynamic Pydantic model from comma-separated field names.

    Args:
        fields_str: Comma-separated field names.

    Returns:
        Pydantic BaseModel class.
    """
    from pydantic import create_model

    field_names = [f.strip() for f in fields_str.split(",") if f.strip()]

    if not field_names:
        return None

    field_definitions: dict[str, Any] = dict.fromkeys(field_names, (str, ""))

    return create_model("ExtractedData", **field_definitions)


# ══════════════════════════════════════════════════════════════
# Serialization
# ══════════════════════════════════════════════════════════════

def _serialize_extracted(data: Any) -> Any:
    """
    Serialize extracted data to JSON-compatible format.

    Handles Pydantic models, dicts, lists, and primitives.

    Args:
        data: Extracted data.

    Returns:
        JSON-serializable data.
    """
    if data is None:
        return None

    # Pydantic model
    if hasattr(data, "model_dump"):
        return data.model_dump()

    if hasattr(data, "dict"):
        return data.dict()

    # List of models
    if isinstance(data, list):
        return [_serialize_extracted(item) for item in data]

    # Dict
    if isinstance(data, dict):
        return {k: _serialize_extracted(v) for k, v in data.items()}

    # Primitive
    return data
