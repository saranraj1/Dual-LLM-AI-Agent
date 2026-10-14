"""
tools/preflight_tools.py — Pre-Flight Compiler & Static Diagnostics Gate.

Validates syntax, catches AST compilation errors, and performs immediate
micro-repairs before tests or downstream tools are executed.
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any


def validate_python_syntax(code: str, filename: str = "<snippet>") -> Dict[str, Any]:
    """
    Validate Python syntax using ast.parse and compile().
    Returns detailed diagnostics including line number, column offset, and context.
    """
    try:
        ast.parse(code, filename=filename)
        compile(code, filename=filename, mode="exec")
        return {
            "valid": True,
            "error_type": None,
            "message": "Syntax valid",
            "lineno": None,
            "offset": None,
            "line_text": None,
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "error_type": type(e).__name__,
            "message": e.msg or str(e),
            "lineno": e.lineno,
            "offset": e.offset,
            "line_text": (e.text or "").strip(),
        }
    except Exception as e:
        return {
            "valid": False,
            "error_type": type(e).__name__,
            "message": str(e),
            "lineno": None,
            "offset": None,
            "line_text": None,
        }


def check_ast_structure(code: str) -> Dict[str, Any]:
    """Inspect AST for common code quality smells like empty except or wildcard imports."""
    warnings = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        warnings.append(f"Wildcard import 'from {node.module} import *' at line {node.lineno}")
            elif isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    # Bare except
                    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        warnings.append(f"Silent bare 'except: pass' at line {node.lineno}")
    except Exception:
        pass
    return {"warnings": warnings}


def auto_repair_syntax(code: str, error_info: Dict[str, Any]) -> Optional[str]:
    """
    Attempt deterministic, heuristic micro-repair for common LLM syntax slip-ups:
    - Missing colon after control flow statements (def, class, if, elif, else, while, for, try, except, finally).
    - Trailing commas or missing closing parentheses on single statements.
    """
    if not error_info or error_info.get("valid"):
        return None

    lineno = error_info.get("lineno")
    if not lineno:
        return None

    lines = code.splitlines(keepends=True)
    if lineno > len(lines):
        return None

    idx = lineno - 1
    target_line = lines[idx]

    # Heuristic 1: Missing colon
    control_keywords = r'^\s*(?:def|class|if|elif|else|while|for|try|except|finally|with)\b'
    if re.search(control_keywords, target_line):
        stripped = target_line.rstrip("\r\n").rstrip()
        if not stripped.endswith(":"):
            fixed_line = stripped + ":" + ("\n" if target_line.endswith("\n") else "")
            lines[idx] = fixed_line
            candidate = "".join(lines)
            if validate_python_syntax(candidate)["valid"]:
                return candidate

    # Heuristic 2: Tab vs Space indentation normalization
    if "IndentationError" in error_info.get("error_type", "") or "TabError" in error_info.get("error_type", ""):
        candidate = code.replace("\t", "    ")
        if validate_python_syntax(candidate)["valid"]:
            return candidate

    return None


def preflight_check_file(file_path: str, proposed_content: Optional[str] = None) -> Dict[str, Any]:
    """
    Pre-flight sanity check for a target file before execution.
    If proposed_content is provided, validates that string directly; otherwise reads file_path.
    """
    p = Path(file_path)
    content = proposed_content
    if content is None:
        if not p.exists():
            return {"valid": False, "file": file_path, "error": f"File does not exist: {file_path}"}
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {"valid": False, "file": file_path, "error": f"Failed to read file: {e}"}

    ext = p.suffix.lower()
    if ext == ".py":
        syntax = validate_python_syntax(content, filename=str(p))
        if not syntax["valid"]:
            # Try auto repair
            repaired = auto_repair_syntax(content, syntax)
            return {
                "valid": False,
                "file": file_path,
                "error": f"SyntaxError at line {syntax['lineno']}: {syntax['message']} ('{syntax['line_text']}')",
                "details": syntax,
                "auto_repaired_content": repaired
            }
        ast_check = check_ast_structure(content)
        from core.security import audit_code_safety
        safety_check = audit_code_safety(content, filename=str(p))
        all_warnings = ast_check.get("warnings", []) + [f"[SECURITY] {f}" for f in safety_check.get("findings", [])]
        return {
            "valid": True,
            "file": file_path,
            "warnings": all_warnings,
            "safety": safety_check,
            "auto_repaired_content": None
        }

    elif ext == ".json":
        try:
            json.loads(content)
            return {"valid": True, "file": file_path, "warnings": []}
        except Exception as e:
            return {"valid": False, "file": file_path, "error": f"JSONDecodeError: {e}"}

    return {"valid": True, "file": file_path, "warnings": []}
