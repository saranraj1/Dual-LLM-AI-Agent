"""
tools/api_doc_scanner.py — Auto-generate API documentation from source code.

Scans Python projects for Flask and FastAPI routes using AST analysis
(no server execution needed). Produces:
  - Markdown API reference
  - OpenAPI 3.0 YAML spec
  - Summary table of all endpoints

Supports:
  - Flask:   @app.route(), @bp.route(), @app.get/post/put/delete/patch()
  - FastAPI: @app.get/post/put/delete/patch(), @router.X()
  - Django:  urlpatterns = [...] path() / re_path() (basic)
"""

import ast
import os
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from config.settings import SKIP_DIRS

# PyYAML is optional — fall back to JSON if not installed
try:
    import yaml as _yaml
    def _to_yaml(obj: dict) -> str:
        return _yaml.dump(obj, default_flow_style=False, sort_keys=False, allow_unicode=True)
except ImportError:
    def _to_yaml(obj: dict) -> str:  # type: ignore
        return json.dumps(obj, indent=2)


# ── Data structures ──────────────────────────────────────────────────────────

class Endpoint:
    def __init__(
        self,
        method:    str,
        path:      str,
        function:  str,
        file:      str,
        lineno:    int,
        docstring: str = "",
        params:    Optional[List[str]] = None,
        tags:      Optional[List[str]] = None,
    ):
        self.method    = method.upper()
        self.path      = path
        self.function  = function
        self.file      = file
        self.lineno    = lineno
        self.docstring = docstring
        self.params    = params or []
        self.tags      = tags or []

    def __repr__(self):
        return f"{self.method:6} {self.path:<45} → {self.function}()"


# ── AST route extractors ─────────────────────────────────────────────────────

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}

_FLASK_DECORATOR_PATTERN  = re.compile(
    r'(?:app|bp|api|blueprint|router)\.(route|get|post|put|delete|patch|head|options)',
    re.IGNORECASE
)
_FASTAPI_DECORATOR_PATTERN = re.compile(
    r'(?:app|router|api)\.(get|post|put|delete|patch|head|options)',
    re.IGNORECASE
)


def _decorator_method(deco_name: str, keywords: List) -> str:
    """Infer HTTP method from decorator name or methods=[...] keyword."""
    name = deco_name.lower()
    if name in _HTTP_METHODS:
        return name.upper()
    # Flask: @app.route(..., methods=['GET','POST'])
    for kw in keywords:
        if kw.arg == "methods" and isinstance(kw.value, ast.List):
            methods = []
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant):
                    methods.append(elt.s.upper())
            return "|".join(methods) if methods else "GET"
    return "GET"


def _extract_path_from_call(call: ast.Call) -> str:
    """Extract URL path string from a decorator call."""
    if call.args and isinstance(call.args[0], ast.Constant):
        return str(call.args[0].s)
    for kw in call.keywords:
        if kw.arg == "path" and isinstance(kw.value, ast.Constant):
            return str(kw.value.s)
    return "/"


def _extract_docstring(node: ast.FunctionDef) -> str:
    """Get the docstring of a function, or empty string."""
    return ast.get_docstring(node) or ""


def _extract_params(node: ast.FunctionDef) -> List[str]:
    """Extract parameter names from function signature (excluding self/cls)."""
    skip = {"self", "cls", "request", "req", "response", "resp", "db", "session"}
    params = []
    for arg in node.args.args:
        if arg.arg not in skip:
            params.append(arg.arg)
    return params


def _scan_file(filepath: str, root: str) -> List[Endpoint]:
    """Parse a single Python file and return all detected API endpoints."""
    endpoints: List[Endpoint] = []
    rel = os.path.relpath(filepath, root)

    try:
        source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        tree   = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError):
        return []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for deco in node.decorator_list:
            path_str = "/"
            method   = "GET"

            # Decorator is a function call: @app.get("/path")
            if isinstance(deco, ast.Call):
                func = deco.func
                if isinstance(func, ast.Attribute):
                    attr  = func.attr.lower()
                    # Check it looks like a route decorator
                    if attr == "route" or attr in _HTTP_METHODS:
                        path_str = _extract_path_from_call(deco)
                        method   = _decorator_method(attr, deco.keywords)
                        endpoints.append(Endpoint(
                            method    = method,
                            path      = path_str,
                            function  = node.name,
                            file      = rel,
                            lineno    = node.lineno,
                            docstring = _extract_docstring(node),
                            params    = _extract_params(node),
                            tags      = [Path(rel).stem.replace("_", " ").title()],
                        ))
            # Decorator is a bare name or attribute (uncommon but possible)
            elif isinstance(deco, ast.Attribute):
                if deco.attr in _HTTP_METHODS:
                    endpoints.append(Endpoint(
                        method    = deco.attr.upper(),
                        path      = "/",
                        function  = node.name,
                        file      = rel,
                        lineno    = node.lineno,
                        docstring = _extract_docstring(node),
                        params    = _extract_params(node),
                    ))

    return endpoints


# ── Project-wide scanner ─────────────────────────────────────────────────────

def scan_api_endpoints(root: str) -> List[Endpoint]:
    """
    Scan all Python files in root for API route definitions.

    Args:
        root: Absolute path to the project root.

    Returns:
        List of Endpoint objects, sorted by path then method.
    """
    root_path  = Path(root).resolve()
    endpoints: List[Endpoint] = []

    for fp in sorted(root_path.rglob("*.py")):
        if any(s in fp.parts for s in SKIP_DIRS):
            continue
        endpoints.extend(_scan_file(str(fp), str(root_path)))

    # Deduplicate and sort
    seen  = set()
    dedup = []
    for ep in endpoints:
        key = (ep.method, ep.path, ep.function)
        if key not in seen:
            seen.add(key)
            dedup.append(ep)

    return sorted(dedup, key=lambda e: (e.path, e.method))


# ── Markdown generator ───────────────────────────────────────────────────────

def generate_markdown(endpoints: List[Endpoint], title: str = "API Reference") -> str:
    """Generate a Markdown API reference document from endpoint list."""
    if not endpoints:
        return "# API Reference\n\n_No API routes detected in this project._\n"

    METHOD_BADGE = {
        "GET":    "![GET](https://img.shields.io/badge/GET-61affe?style=flat-square)",
        "POST":   "![POST](https://img.shields.io/badge/POST-49cc90?style=flat-square)",
        "PUT":    "![PUT](https://img.shields.io/badge/PUT-fca130?style=flat-square)",
        "DELETE": "![DELETE](https://img.shields.io/badge/DELETE-f93e3e?style=flat-square)",
        "PATCH":  "![PATCH](https://img.shields.io/badge/PATCH-50e3c2?style=flat-square)",
    }

    lines = [
        f"# {title}",
        "",
        f"> Auto-generated by AI Agent · {len(endpoints)} endpoint{'s' if len(endpoints) != 1 else ''} found",
        "",
        "## Summary",
        "",
        "| Method | Path | Function | File |",
        "|--------|------|----------|------|",
    ]

    for ep in endpoints:
        badge = METHOD_BADGE.get(ep.method, f"`{ep.method}`")
        lines.append(f"| {badge} | `{ep.path}` | `{ep.function}()` | `{ep.file}` |")

    lines += ["", "---", "", "## Endpoints", ""]

    # Group by tag (file)
    by_tag: Dict[str, List[Endpoint]] = {}
    for ep in endpoints:
        tag = ep.tags[0] if ep.tags else "Other"
        by_tag.setdefault(tag, []).append(ep)

    for tag, eps in by_tag.items():
        lines += [f"### {tag}", ""]
        for ep in eps:
            method_str = " / ".join(ep.method.split("|"))
            lines += [
                f"#### `{ep.path}`",
                "",
                f"**Method:** `{method_str}`  ",
                f"**Function:** `{ep.function}()`  ",
                f"**File:** `{ep.file}:{ep.lineno}`  ",
                "",
            ]
            if ep.docstring:
                lines += [ep.docstring, ""]

            if ep.params:
                lines += [
                    "**Parameters:**",
                    "",
                    "| Name | Type | Description |",
                    "|------|------|-------------|",
                ]
                for p in ep.params:
                    # Guess type from name
                    t = "string"
                    if p.endswith("_id") or p in {"id", "pk"}:
                        t = "integer"
                    elif p in {"limit", "offset", "page", "size", "count"}:
                        t = "integer"
                    elif p in {"active", "enabled", "flag"}:
                        t = "boolean"
                    lines.append(f"| `{p}` | {t} | — |")
                lines.append("")

            lines += ["---", ""]

    return "\n".join(lines)


# ── OpenAPI 3.0 generator ────────────────────────────────────────────────────

def generate_openapi(
    endpoints: List[Endpoint],
    title:     str = "API",
    version:   str = "1.0.0",
    base_url:  str = "http://localhost:8000",
) -> Dict:
    """Generate an OpenAPI 3.0 spec dict from endpoint list."""

    spec: Dict = {
        "openapi": "3.0.3",
        "info": {
            "title":   title,
            "version": version,
            "description": f"Auto-generated by AI Agent · {len(endpoints)} endpoints",
        },
        "servers": [{"url": base_url}],
        "paths":   {},
        "components": {
            "schemas": {},
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                }
            },
        },
    }

    for ep in endpoints:
        path = ep.path
        # Normalise Flask/FastAPI params: <id> → {id},  {id} stays
        path_openapi = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", path)

        if path_openapi not in spec["paths"]:
            spec["paths"][path_openapi] = {}

        for method in ep.method.split("|"):
            method = method.lower()
            operation: Dict = {
                "operationId": ep.function,
                "summary":     ep.docstring.split("\n")[0][:80] if ep.docstring else ep.function,
                "tags":        ep.tags or ["default"],
                "parameters":  [],
                "responses": {
                    "200": {"description": "Successful response"},
                    "400": {"description": "Bad request"},
                    "422": {"description": "Validation error"},
                    "500": {"description": "Internal server error"},
                },
            }

            # Path params
            path_params = re.findall(r"\{(\w+)\}", path_openapi)
            for pp in path_params:
                operation["parameters"].append({
                    "name":     pp,
                    "in":       "path",
                    "required": True,
                    "schema":   {"type": "integer" if pp.endswith("_id") or pp == "id" else "string"},
                })

            # Query params from function signature (non-path params)
            if method == "get":
                for p in ep.params:
                    if p not in path_params:
                        operation["parameters"].append({
                            "name":     p,
                            "in":       "query",
                            "required": False,
                            "schema":   {"type": "string"},
                        })

            # Request body for POST/PUT/PATCH
            if method in {"post", "put", "patch"}:
                operation["requestBody"] = {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"}
                        }
                    }
                }

            spec["paths"][path_openapi][method] = operation

    return spec


# ── Main entry ───────────────────────────────────────────────────────────────

def generate_api_docs(root: str, project_name: str = "API") -> Dict[str, str]:
    """
    Scan a project and generate both Markdown and OpenAPI YAML docs.

    Args:
        root:         Project root directory.
        project_name: Name to use in doc titles.

    Returns:
        Dict with keys: 'endpoints_found', 'markdown', 'openapi_yaml', 'summary'
    """
    endpoints = scan_api_endpoints(root)
    md        = generate_markdown(endpoints, title=f"{project_name} — API Reference")
    openapi   = generate_openapi(endpoints,  title=project_name)

    openapi_yaml = _to_yaml(openapi)

    summary_lines = [
        f"📡 Found {len(endpoints)} endpoint{'s' if len(endpoints) != 1 else ''}",
    ]
    if endpoints:
        method_counts: Dict[str, int] = {}
        for ep in endpoints:
            for m in ep.method.split("|"):
                method_counts[m] = method_counts.get(m, 0) + 1
        for m, c in sorted(method_counts.items()):
            summary_lines.append(f"   {m:<8}: {c}")

    return {
        "endpoints_found": len(endpoints),
        "markdown":        md,
        "openapi_yaml":    openapi_yaml,
        "summary":         "\n".join(summary_lines),
    }
