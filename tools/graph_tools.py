"""
tools/graph_tools.py — AST-based Codebase Call-Graph & Blast-Radius Engine.
Performs zero-dependency static analysis using Python's standard `ast` module:
  - Extracts definitions (classes, functions, methods, parameters)
  - Resolves cross-file imports and module bindings
  - Extracts call-sites (who calls what and where)
  - Computes the Blast Radius of modifying any function or class
  - Exports node-link graph data for web visualization
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from collections import defaultdict
from config.settings import SKIP_DIRS


class CodeVisitor(ast.NodeVisitor):
    """
    AST Visitor that extracts functions, classes, methods, imports, and call sites
    with exact line numbers and caller scoping.
    """

    def __init__(self, rel_path: str):
        self.rel_path = rel_path
        self.definitions: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []
        self._scope_stack: List[str] = []

    @property
    def current_scope(self) -> str:
        return "::".join(self._scope_stack) if self._scope_stack else "<module>"

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append({
                "module": alias.name,
                "name": alias.name,
                "alias": alias.asname,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        for alias in node.names:
            self.imports.append({
                "module": mod,
                "name": alias.name,
                "alias": alias.asname,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        class_name = node.name
        self.definitions.append({
            "name": class_name,
            "type": "class",
            "line": node.lineno,
            "scope": self.current_scope,
            "bases": [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else [],
        })
        self._scope_stack.append(class_name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record_func(node, is_async=True)

    def _record_func(self, node, is_async: bool):
        args = [a.arg for a in node.args.args]
        func_type = "method" if self._scope_stack else "function"
        self.definitions.append({
            "name": node.name,
            "type": func_type,
            "is_async": is_async,
            "line": node.lineno,
            "args": args,
            "scope": self.current_scope,
        })
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_Call(self, node: ast.Call):
        # Extract callee name
        callee_name = None
        if isinstance(node.func, ast.Name):
            callee_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            callee_name = node.func.attr

        if callee_name:
            self.calls.append({
                "caller": self.current_scope,
                "callee": callee_name,
                "line": node.lineno,
            })
        self.generic_visit(node)


def build_call_graph(root: str, max_files: int = 150) -> Dict[str, Any]:
    """
    Scan Python files in the workspace and construct a complete call graph index.
    Returns:
      {
        "ok": True,
        "files": {rel_path: {"definitions", "imports", "calls"}},
        "symbol_to_files": {symbol: [rel_paths]},
        "callers_of": {callee_name: [{"file", "caller", "line"}]},
        "file_dependencies": {file: set(imported_files)}
      }
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        return {"ok": False, "error": f"Path not found: {root}"}

    files_index: Dict[str, Dict[str, Any]] = {}
    symbol_to_files: Dict[str, List[str]] = defaultdict(list)
    callers_of: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    module_to_file: Dict[str, str] = {}

    # Gather Python files
    py_files = []
    for fp in sorted(root_path.rglob("*.py")):
        if any(skip in fp.parts for skip in SKIP_DIRS):
            continue
        py_files.append(fp)
        if len(py_files) >= max_files:
            break

    # First pass: Parse AST and extract symbols & calls
    for fp in py_files:
        try:
            rel = str(fp.relative_to(root_path)).replace("\\", "/")
            source = fp.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=str(fp))

            visitor = CodeVisitor(rel)
            visitor.visit(tree)

            files_index[rel] = {
                "definitions": visitor.definitions,
                "imports": visitor.imports,
                "calls": visitor.calls,
            }

            # Map Python dotted module path to file (e.g. tools.file_tools -> tools/file_tools.py)
            mod_dot = rel[:-3].replace("/", ".")
            module_to_file[mod_dot] = rel
            if mod_dot.endswith(".__init__"):
                module_to_file[mod_dot[:-9]] = rel

            for d in visitor.definitions:
                symbol_to_files[d["name"]].append(rel)

            for c in visitor.calls:
                callers_of[c["callee"]].append({
                    "file": rel,
                    "caller": c["caller"],
                    "line": c["line"],
                })

        except Exception:
            continue

    # Second pass: compute file-to-file dependency edges
    file_dependencies: Dict[str, List[str]] = defaultdict(list)
    for rel, data in files_index.items():
        deps: Set[str] = set()
        for imp in data["imports"]:
            mod = imp["module"]
            if mod in module_to_file:
                target_f = module_to_file[mod]
                if target_f != rel:
                    deps.add(target_f)
        file_dependencies[rel] = sorted(list(deps))

    return {
        "ok": True,
        "root": str(root_path),
        "files": files_index,
        "symbol_to_files": dict(symbol_to_files),
        "callers_of": dict(callers_of),
        "file_dependencies": dict(file_dependencies),
        "total_files": len(files_index),
        "total_definitions": sum(len(d["definitions"]) for d in files_index.values()),
        "total_calls": sum(len(d["calls"]) for d in files_index.values()),
    }


def compute_blast_radius(
    symbol: str,
    target_file: Optional[str] = None,
    root: str = ".",
    root_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculate the impact / blast radius of modifying `symbol`.
    Returns all direct callers, importing files, associated tests, and risk severity.
    """
    if root_dir is not None:
        root = root_dir
    graph = build_call_graph(root)
    if not graph.get("ok"):
        return {"ok": False, "error": graph.get("error", "Failed to build call graph")}

    callers_list = graph["callers_of"].get(symbol, [])
    def_files = graph["symbol_to_files"].get(symbol, [])

    # If target_file is provided, normalize it
    if target_file:
        target_file = target_file.replace("\\", "/").lstrip("./")

    # Filter callers if target_file is known, or keep all
    affected_files_set: Set[str] = set()
    filtered_callers: List[Dict[str, Any]] = []

    for c in callers_list:
        file_rel = c["file"]
        # Skip calls inside the target function/class itself
        if target_file and file_rel == target_file and c["caller"] == symbol:
            continue
        filtered_callers.append(c)
        affected_files_set.add(file_rel)

    # Check which modules import the file containing this symbol
    imported_by_files: Set[str] = set()
    for def_file in def_files:
        for f, deps in graph["file_dependencies"].items():
            if def_file in deps and f != def_file:
                imported_by_files.add(f)
                affected_files_set.add(f)

    # Identify tests in affected files
    affected_tests: List[str] = []
    for f in affected_files_set:
        if "test" in f.lower() or f.startswith("tests/"):
            affected_tests.append(f)

    # Compute impact severity
    total_impacted = len(affected_files_set)
    caller_count = len(filtered_callers)

    if symbol.startswith("_") and total_impacted <= 1:
        severity = "LOW"
    elif total_impacted <= 2 and caller_count <= 4:
        severity = "MEDIUM"
    else:
        severity = "HIGH"

    summary = (
        f"{symbol} has {caller_count} callsite(s) across {total_impacted} file(s) "
        f"({len(affected_tests)} test suite(s)). Impact: {severity}"
    )

    return {
        "ok": True,
        "symbol": symbol,
        "target_symbol": symbol,
        "target_file": target_file or (def_files[0] if def_files else None),
        "definition_files": def_files,
        "severity": severity,
        "caller_count": caller_count,
        "callers": filtered_callers,
        "affected_files": sorted(list(affected_files_set)),
        "affected_tests": sorted(affected_tests),
        "imported_by": sorted(list(imported_by_files)),
        "summary": summary,
    }


def export_graph_json(root: str) -> Dict[str, Any]:
    """
    Export node-link data structure for frontend graph visualization (D3 / Canvas / Vis).
    Nodes represent files and symbols; edges represent imports, containment, and calls.
    """
    graph = build_call_graph(root)
    if not graph.get("ok"):
        return {"ok": False, "nodes": [], "edges": [], "links": []}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    node_ids: Set[str] = set()

    for file_path, data in graph["files"].items():
        file_id = f"file::{file_path}"
        if file_id not in node_ids:
            nodes.append({
                "id": file_id,
                "label": Path(file_path).name,
                "name": Path(file_path).name,
                "file": file_path,
                "kind": "module",
                "path": file_path,
                "type": "module",
                "symbols_count": len(data["definitions"]),
            })
            node_ids.add(file_id)

        # Symbol nodes
        for item in data["definitions"]:
            sym_id = f"sym::{file_path}::{item['name']}"
            if sym_id not in node_ids:
                item_kind = item.get("kind") or item.get("type", "function")
                nodes.append({
                    "id": sym_id,
                    "label": item["name"],
                    "name": item["name"],
                    "file": file_path,
                    "path": file_path,
                    "kind": item_kind,
                    "type": item_kind,
                    "line": item["line"],
                    "args": item.get("args", []),
                })
                node_ids.add(sym_id)
                edges.append({
                    "source": file_id,
                    "target": sym_id,
                    "type": "contains",
                })

        # File-to-file import edges
        for dep in graph["file_dependencies"].get(file_path, []):
            edges.append({
                "source": file_id,
                "target": f"file::{dep}",
                "type": "imports",
            })

    # Cross-file call edges
    for callee, callers in graph["callers_of"].items():
        def_files = graph["symbol_to_files"].get(callee, [])
        for def_f in def_files:
            for c in callers:
                if c["file"] != def_f:
                    edges.append({
                        "source": f"file::{c['file']}",
                        "target": f"file::{def_f}",
                        "type": "calls",
                        "symbol": callee,
                    })

    return {"ok": True, "nodes": nodes, "edges": edges, "links": edges}
