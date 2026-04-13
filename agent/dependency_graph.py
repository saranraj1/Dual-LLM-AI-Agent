"""
agent/dependency_graph.py — Multi-file import dependency analysis.

Builds a directed graph of which Python files import which other files
within the project. Used by the executor to determine the optimal processing
order when a task touches multiple files (dependencies first).

Features:
- AST-based import parsing (no execution required)
- Cycle detection with Kahn's topological sort
- Strongly-connected component identification
- Impact analysis: "which files will break if I change X?"
"""

import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict, deque
from config.settings import SKIP_DIRS


# ── AST import extraction ─────────────────────────────────────────────────────

def _extract_imports(source: str) -> Set[str]:
    """
    Parse Python source and return all module names imported.
    Returns both 'import foo' and 'from foo import bar' styles.
    """
    imports: Set[str] = set()
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
                # Relative imports: from . import x  (node.level > 0)
                if node.level and node.level > 0:
                    imports.add("__relative__")
    except SyntaxError:
        pass
    return imports


def _module_name(filepath: str, root: str) -> str:
    """Convert a file path to a dotted module name relative to root."""
    rel  = os.path.relpath(filepath, root)
    name = rel.replace(os.sep, ".").replace("/", ".")
    if name.endswith(".py"):
        name = name[:-3]
    return name


# ── Graph builder ─────────────────────────────────────────────────────────────

class DependencyGraph:
    """
    Directed import dependency graph for a Python project.

    Nodes  = Python module names (dotted, relative to project root)
    Edges  = A → B means "module A imports module B"

    Usage:
        graph = DependencyGraph.build("c:/my-project")
        order = graph.topological_order(["agent/executor.py", "agent/planner.py"])
        impact = graph.impact_of("core/llm.py")
    """

    def __init__(self):
        # edges[a] = set of modules that 'a' imports
        self.edges:  Dict[str, Set[str]] = defaultdict(set)
        # rev[b]   = set of modules that import 'b'
        self.reverse: Dict[str, Set[str]] = defaultdict(set)
        self._modules: Dict[str, str] = {}  # module_name → filepath

    # ── Build ─────────────────────────────────────────────────────────────────

    @classmethod
    def build(cls, root: str) -> "DependencyGraph":
        """
        Scan an entire project directory and build the dependency graph.

        Args:
            root: Absolute path to the project root.

        Returns:
            A fully-built DependencyGraph instance.
        """
        graph = cls()
        root_path = Path(root).resolve()

        # Step 1: collect all Python files
        py_files: Dict[str, str] = {}  # module_name → abs path
        for fp in root_path.rglob("*.py"):
            if any(s in fp.parts for s in SKIP_DIRS):
                continue
            mod = _module_name(str(fp), str(root_path))
            py_files[mod] = str(fp)
            graph._modules[mod] = str(fp)

        known_mods = set(py_files.keys())

        # Step 2: extract imports and build edges
        for mod, filepath in py_files.items():
            try:
                source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
                imports = _extract_imports(source)
                for imp in imports:
                    # Only care about project-internal imports
                    matching = {k for k in known_mods if k.startswith(imp) or k == imp}
                    for dep in matching:
                        if dep != mod:
                            graph.edges[mod].add(dep)
                            graph.reverse[dep].add(mod)
            except Exception:
                continue

        return graph

    # ── Queries ───────────────────────────────────────────────────────────────

    def dependencies_of(self, filepath: str, root: str) -> List[str]:
        """
        Return all modules that filepath depends on (directly or transitively).

        Args:
            filepath: Absolute or relative path to a Python file.
            root:     Project root directory.

        Returns:
            List of module names (dependencies), deepest first.
        """
        mod = _module_name(os.path.abspath(filepath), os.path.abspath(root))
        visited: Set[str] = set()
        result:  List[str] = []

        def dfs(m: str):
            for dep in self.edges.get(m, []):
                if dep not in visited:
                    visited.add(dep)
                    dfs(dep)
                    result.append(dep)

        dfs(mod)
        return result

    def impact_of(self, filepath: str, root: str) -> List[str]:
        """
        Return all modules that would be affected if filepath changes.
        (i.e., all modules that directly or transitively import this one)

        Args:
            filepath: File to analyse impact for.
            root:     Project root directory.

        Returns:
            List of affected module names.
        """
        mod = _module_name(os.path.abspath(filepath), os.path.abspath(root))
        visited: Set[str] = set()
        result:  List[str] = []

        def dfs(m: str):
            for dep in self.reverse.get(m, []):
                if dep not in visited:
                    visited.add(dep)
                    result.append(dep)
                    dfs(dep)

        dfs(mod)
        return result

    def topological_order(self, filepaths: List[str], root: str) -> List[str]:
        """
        Given a list of files that need processing, return them in dependency order
        (dependencies always come before dependents).

        Uses Kahn's algorithm. If a cycle is detected, returns the files in the
        original order (safe fallback).

        Args:
            filepaths: List of file paths to sort.
            root:      Project root directory.

        Returns:
            Sorted list of file paths, safe to process in order.
        """
        mods = {}
        for fp in filepaths:
            mod = _module_name(os.path.abspath(fp), os.path.abspath(root))
            mods[mod] = fp

        mod_set = set(mods.keys())
        in_degree = {m: 0 for m in mod_set}

        for m in mod_set:
            for dep in self.edges.get(m, []):
                if dep in mod_set:
                    in_degree[m] += 1

        queue = deque([m for m, d in in_degree.items() if d == 0])
        sorted_mods: List[str] = []

        while queue:
            m = queue.popleft()
            sorted_mods.append(m)
            for dep in self.edges.get(m, []):
                if dep in mod_set:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)

        if len(sorted_mods) != len(mod_set):
            # Cycle detected — return original order as fallback
            return filepaths

        return [mods[m] for m in sorted_mods if m in mods]

    def find_cycles(self) -> List[List[str]]:
        """
        Detect circular import cycles in the project.

        Returns:
            List of cycles, each cycle is a list of module names.
        """
        visited:   Set[str] = set()
        rec_stack: Set[str] = set()
        cycles:    List[List[str]] = []
        path:      List[str] = []

        def dfs(node: str):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for dep in self.edges.get(node, []):
                if dep not in visited:
                    dfs(dep)
                elif dep in rec_stack:
                    # Found a cycle — extract it
                    idx   = path.index(dep)
                    cycle = path[idx:]
                    if cycle not in cycles:
                        cycles.append(cycle[:])

            path.pop()
            rec_stack.discard(node)

        for mod in list(self.edges.keys()):
            if mod not in visited:
                dfs(mod)

        return cycles

    def summary(self) -> str:
        """Return a human-readable summary of the dependency graph."""
        total_mods  = len(self._modules)
        total_edges = sum(len(v) for v in self.edges.values())
        cycles      = self.find_cycles()

        most_imported = sorted(
            self.reverse.items(), key=lambda x: len(x[1]), reverse=True
        )[:5]

        lines = [
            f"\n📊 Dependency Graph Summary",
            f"{'─'*40}",
            f"  Modules     : {total_mods}",
            f"  Import edges: {total_edges}",
            f"  Cycles      : {len(cycles)}",
            f"\n  Most-imported modules:",
        ]
        for mod, importers in most_imported:
            lines.append(f"    {mod:<35} ← {len(importers)} modules")

        if cycles:
            lines.append(f"\n  ⚠️  Circular imports detected:")
            for cycle in cycles[:3]:
                lines.append(f"    {' → '.join(cycle)} → (back to {cycle[0]})")

        return "\n".join(lines)
