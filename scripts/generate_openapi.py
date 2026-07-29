"""
AgentCrawl — OpenAPI Schema Generator
=========================================

Generates OpenAPI 3.1 specification from the AgentCrawl FastAPI
application. Outputs JSON, YAML, and HTML documentation.

Usage:
    # Generate openapi.json
    python scripts/generate_openapi.py

    # Generate all formats
    python scripts/generate_openapi.py --format all

    # Custom output directory
    python scripts/generate_openapi.py --output-dir docs/api

    # Generate YAML only
    python scripts/generate_openapi.py --format yaml

    # Generate HTML docs
    python scripts/generate_openapi.py --format html

Output:
    openapi.json   — OpenAPI 3.1 specification (JSON)
    openapi.yaml   — OpenAPI 3.1 specification (YAML)
    openapi.html   — Swagger UI HTML documentation
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# ══════════════════════════════════════════════════════════════
# Schema Generation
# ══════════════════════════════════════════════════════════════

def get_app() -> Any:
    """
    Import and return the FastAPI application.

    Returns:
        FastAPI app instance.
    """
    try:
        from agentcrawl.server.app import create_app
        return create_app()
    except ImportError as e:
        print(f"Error: Could not import AgentCrawl server: {e}")
        print("Make sure agentcrawl is installed: pip install agentcrawl")
        sys.exit(1)


def generate_openapi_schema(app: Any) -> dict[str, Any]:
    """
    Generate the OpenAPI schema from a FastAPI app.

    Args:
        app: FastAPI application instance.

    Returns:
        OpenAPI schema dictionary.
    """
    schema = app.openapi()

    # Enhance schema with additional metadata
    schema["info"]["title"] = "AgentCrawl API"
    schema["info"]["version"] = _get_version()
    schema["info"]["description"] = (
        "Web Crawling & Scraping Framework for AI Agents.\n\n"
        "Convert any website into clean, LLM-ready Markdown or structured JSON.\n\n"
        "## Authentication\n\n"
        "Include your API key in the `Authorization` header:\n"
        "```\nAuthorization: Bearer your-api-key\n```\n\n"
        "## Endpoints\n\n"
        "- `POST /scrape` — Scrape a single page\n"
        "- `POST /crawl` — Start a crawl job\n"
        "- `GET /crawl/{job_id}` — Get crawl job status\n"
        "- `POST /map` — Discover URLs\n"
        "- `POST /search` — Web search\n"
        "- `POST /extract` — Structured extraction\n"
        "- `POST /batch/scrape` — Batch scrape\n"
        "- `GET /health` — Health check\n"
    )
    schema["info"]["contact"] = {
        "name": "AgentCrawl Team",
        "url": "https://github.com/agentcrawl/agentcrawl",
    }
    schema["info"]["license"] = {
        "name": "Apache-2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0",
    }

    # Add server URLs
    schema["servers"] = [
        {"url": "http://localhost:8000", "description": "Local development"},
        {"url": "https://api.agentcrawl.dev", "description": "Production"},
    ]

    # Add security scheme
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "API key authentication",
        },
    }

    # Add tags
    schema["tags"] = [
        {"name": "Scraping", "description": "Single page scraping operations"},
        {"name": "Crawling", "description": "Multi-page crawl operations"},
        {"name": "Discovery", "description": "URL discovery and mapping"},
        {"name": "Search", "description": "Web search operations"},
        {"name": "Extraction", "description": "Structured data extraction"},
        {"name": "Batch", "description": "Batch operations"},
        {"name": "System", "description": "Health and system endpoints"},
    ]

    return schema


def _get_version() -> str:
    """Get the AgentCrawl version."""
    try:
        import agentcrawl
        return agentcrawl.__version__
    except Exception:
        return "1.0.0"


# ══════════════════════════════════════════════════════════════
# Output Formatters
# ══════════════════════════════════════════════════════════════

def save_json(schema: dict[str, Any], filepath: str) -> None:
    """Save schema as JSON."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"  ✓ JSON: {filepath} ({os.path.getsize(filepath):,} bytes)")


def save_yaml(schema: dict[str, Any], filepath: str) -> None:
    """Save schema as YAML."""
    try:
        import yaml
    except ImportError:
        print("  ⚠ PyYAML not installed. Skipping YAML output.")
        print("    Install with: pip install pyyaml")
        return

    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(
            schema,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
    print(f"  ✓ YAML: {filepath} ({os.path.getsize(filepath):,} bytes)")


def save_html(schema: dict[str, Any], filepath: str) -> None:
    """Save schema as Swagger UI HTML."""
    schema_json = json.dumps(schema, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AgentCrawl API Documentation</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <style>
        body {{ margin: 0; padding: 0; }}
        .swagger-ui .topbar {{ display: none; }}
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        const spec = {schema_json};
        SwaggerUIBundle({{
            spec: spec,
            dom_id: '#swagger-ui',
            presets: [
                SwaggerUIBundle.presets.apis,
                SwaggerUIBundle.SwaggerUIStandalonePreset,
            ],
            layout: "BaseLayout",
            deepLinking: true,
            displayOperationId: true,
            defaultModelsExpandDepth: 2,
            defaultModelExpandDepth: 2,
        }});
    </script>
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ HTML: {filepath} ({os.path.getsize(filepath):,} bytes)")


def save_markdown(schema: dict[str, Any], filepath: str) -> None:
    """Save schema as Markdown documentation."""
    lines: list[str] = []

    info = schema.get("info", {})
    lines.append(f"# {info.get('title', 'API')}")
    lines.append("")
    lines.append(f"**Version:** {info.get('version', '1.0.0')}")
    lines.append("")
    lines.append(info.get("description", ""))
    lines.append("")

    # Endpoints
    paths = schema.get("paths", {})
    lines.append("## Endpoints")
    lines.append("")

    for path, methods in sorted(paths.items()):
        for method, details in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                summary = details.get("summary", "")
                lines.append(f"### `{method.upper()} {path}`")
                lines.append("")
                if summary:
                    lines.append(f"{summary}")
                    lines.append("")

                # Parameters
                params = details.get("parameters", [])
                if params:
                    lines.append("**Parameters:**")
                    lines.append("")
                    lines.append("| Name | In | Type | Required | Description |")
                    lines.append("|------|-----|------|----------|-------------|")
                    for p in params:
                        name = p.get("name", "")
                        loc = p.get("in", "")
                        ptype = p.get("schema", {}).get("type", "string")
                        required = "Yes" if p.get("required") else "No"
                        desc = p.get("description", "")
                        lines.append(f"| {name} | {loc} | {ptype} | {required} | {desc} |")
                    lines.append("")

                # Request body
                req_body = details.get("requestBody", {})
                if req_body:
                    lines.append("**Request Body:** `application/json`")
                    lines.append("")

                # Responses
                responses = details.get("responses", {})
                if responses:
                    lines.append("**Responses:**")
                    lines.append("")
                    for code, resp in responses.items():
                        desc = resp.get("description", "")
                        lines.append(f"- `{code}` — {desc}")
                    lines.append("")

                lines.append("---")
                lines.append("")

    # Schemas
    schemas = schema.get("components", {}).get("schemas", {})
    if schemas:
        lines.append("## Schemas")
        lines.append("")

        for name, schema_def in sorted(schemas.items()):
            lines.append(f"### {name}")
            lines.append("")

            properties = schema_def.get("properties", {})
            required_fields = set(schema_def.get("required", []))

            if properties:
                lines.append("| Field | Type | Required | Description |")
                lines.append("|-------|------|----------|-------------|")
                for field_name, field_def in properties.items():
                    ftype = field_def.get("type", "object")
                    if "anyOf" in field_def:
                        types = [t.get("type", "null") for t in field_def["anyOf"]]
                        ftype = " \\| ".join(types)
                    req = "Yes" if field_name in required_fields else "No"
                    desc = field_def.get("description", "")
                    lines.append(f"| {field_name} | {ftype} | {req} | {desc} |")
                lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  ✓ Markdown: {filepath} ({os.path.getsize(filepath):,} bytes)")


# ══════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════

def validate_schema(schema: dict[str, Any]) -> list[str]:
    """
    Basic validation of the OpenAPI schema.

    Returns:
        List of warning messages.
    """
    warnings: list[str] = []

    # Check required fields
    if "openapi" not in schema:
        warnings.append("Missing 'openapi' version field")

    if "info" not in schema:
        warnings.append("Missing 'info' section")
    else:
        if "title" not in schema["info"]:
            warnings.append("Missing 'info.title'")
        if "version" not in schema["info"]:
            warnings.append("Missing 'info.version'")

    if "paths" not in schema:
        warnings.append("Missing 'paths' section")
    elif not schema["paths"]:
        warnings.append("'paths' section is empty")

    # Check paths
    for path, methods in schema.get("paths", {}).items():
        for method, details in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                if "responses" not in details:
                    warnings.append(f"{method.upper()} {path}: missing 'responses'")
                if "summary" not in details and "description" not in details:
                    warnings.append(f"{method.upper()} {path}: missing summary/description")

    return warnings


# ══════════════════════════════════════════════════════════════
# Statistics
# ══════════════════════════════════════════════════════════════

def print_stats(schema: dict[str, Any]) -> None:
    """Print schema statistics."""
    paths = schema.get("paths", {})
    schemas = schema.get("components", {}).get("schemas", {})

    total_endpoints = 0
    methods_count: dict[str, int] = {}

    for path, methods in paths.items():
        for method in methods:
            if method in ("get", "post", "put", "delete", "patch"):
                total_endpoints += 1
                methods_count[method.upper()] = methods_count.get(method.upper(), 0) + 1

    print("\n  Schema Statistics:")
    print(f"    OpenAPI version: {schema.get('openapi', 'unknown')}")
    print(f"    Endpoints: {total_endpoints}")
    for method, count in sorted(methods_count.items()):
        print(f"      {method}: {count}")
    print(f"    Schemas: {len(schemas)}")
    print(f"    Paths: {len(paths)}")


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate OpenAPI specification for AgentCrawl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/generate_openapi.py
  python scripts/generate_openapi.py --format all
  python scripts/generate_openapi.py --format yaml --output-dir docs/api
  python scripts/generate_openapi.py --format html
        """,
    )

    parser.add_argument(
        "--format",
        choices=["json", "yaml", "html", "markdown", "all"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the generated schema",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print schema statistics",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output messages",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.quiet:
        print("\nAgentCrawl — OpenAPI Schema Generator")
        print("=" * 50)

    # Get app and generate schema
    if not args.quiet:
        print("\n  Loading FastAPI application...")

    app = get_app()

    if not args.quiet:
        print("  Generating OpenAPI schema...")

    schema = generate_openapi_schema(app)

    # Validate
    if args.validate:
        warnings = validate_schema(schema)
        if warnings:
            print(f"\n  ⚠ Validation warnings ({len(warnings)}):")
            for w in warnings:
                print(f"    - {w}")
        else:
            print("\n  ✓ Schema validation passed")

    # Stats
    if args.stats:
        print_stats(schema)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save outputs
    if not args.quiet:
        print(f"\n  Generating output (format: {args.format})...")

    formats = ["json", "yaml", "html", "markdown"] if args.format == "all" else [args.format]

    for fmt in formats:
        if fmt == "json":
            save_json(schema, str(output_dir / "openapi.json"))
        elif fmt == "yaml":
            save_yaml(schema, str(output_dir / "openapi.yaml"))
        elif fmt == "html":
            save_html(schema, str(output_dir / "openapi.html"))
        elif fmt == "markdown":
            save_markdown(schema, str(output_dir / "openapi.md"))

    if not args.quiet:
        print("\n  Done!")


if __name__ == "__main__":
    main()
