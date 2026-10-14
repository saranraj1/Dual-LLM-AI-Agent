"""tests/test_graph_tools.py — Verify AST Call-Graph and Blast-Radius Engine."""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.graph_tools import (
    CodeVisitor,
    build_call_graph,
    compute_blast_radius,
    export_graph_json,
)


class TestCodeVisitor:
    def test_extracts_classes_and_methods(self):
        code = (
            "class Greeter:\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
            "    def say_hello(self):\n"
            "        return f'Hello, {self.name}'\n"
        )
        import ast
        tree = ast.parse(code)
        visitor = CodeVisitor("sample.py")
        visitor.visit(tree)

        defs = {d["name"]: d for d in visitor.definitions}
        assert "Greeter" in defs
        assert defs["Greeter"]["type"] == "class"
        assert "say_hello" in defs
        assert defs["say_hello"]["type"] == "method"
        assert defs["say_hello"]["scope"] == "Greeter"

    def test_extracts_imports_and_calls(self):
        code = (
            "import os\n"
            "from math import sqrt as square_root\n"
            "\n"
            "def calculate(val):\n"
            "    res = square_root(val)\n"
            "    print(res)\n"
            "    return res\n"
        )
        import ast
        tree = ast.parse(code)
        visitor = CodeVisitor("calc.py")
        visitor.visit(tree)

        assert any(i["module"] == "os" for i in visitor.imports)
        assert any(i["name"] == "sqrt" and i["alias"] == "square_root" for i in visitor.imports)

        call_names = [c["callee"] for c in visitor.calls]
        assert "square_root" in call_names
        assert "print" in call_names


class TestBuildCallGraph:
    def test_builds_cross_file_relationships(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # File A: defines helper
            path_a = os.path.join(tmpdir, "helpers.py")
            with open(path_a, "w", encoding="utf-8") as f:
                f.write("def format_name(first, last):\n    return f'{first} {last}'\n")

            # File B: imports and calls helper
            path_b = os.path.join(tmpdir, "app.py")
            with open(path_b, "w", encoding="utf-8") as f:
                f.write(
                    "from helpers import format_name\n"
                    "def main():\n"
                    "    name = format_name('Alice', 'Smith')\n"
                    "    return name\n"
                )

            graph = build_call_graph(tmpdir)
            assert graph["ok"] is True
            assert "helpers.py" in graph["files"]
            assert "app.py" in graph["files"]
            assert "format_name" in graph["symbol_to_files"]
            assert "helpers.py" in graph["symbol_to_files"]["format_name"]

            # App should have caller of format_name
            callers = graph["callers_of"].get("format_name", [])
            assert len(callers) >= 1
            assert callers[0]["file"] == "app.py"
            assert callers[0]["caller"] == "main"

            # Check file dependencies
            assert "helpers.py" in graph["file_dependencies"].get("app.py", [])


class TestComputeBlastRadius:
    def test_computes_blast_radius_with_test_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Core module
            core_file = os.path.join(tmpdir, "core.py")
            with open(core_file, "w", encoding="utf-8") as f:
                f.write("def core_engine():\n    return 42\n")

            # Consumer module
            service_file = os.path.join(tmpdir, "service.py")
            with open(service_file, "w", encoding="utf-8") as f:
                f.write("from core import core_engine\ndef execute():\n    return core_engine()\n")

            # Test suite
            tests_dir = os.path.join(tmpdir, "tests")
            os.makedirs(tests_dir)
            test_file = os.path.join(tests_dir, "test_core.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("from core import core_engine\ndef test_engine():\n    assert core_engine() == 42\n")

            blast = compute_blast_radius("core_engine", root=tmpdir)
            assert blast["ok"] is True
            assert blast["caller_count"] >= 2
            assert "service.py" in blast["affected_files"]
            assert "tests/test_core.py" in blast["affected_files"]
            assert "tests/test_core.py" in blast["affected_tests"]
            assert blast["severity"] in ("MEDIUM", "HIGH")
            assert "core_engine has" in blast["summary"]

    def test_low_severity_for_private_unused_symbol(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            priv_file = os.path.join(tmpdir, "internal.py")
            with open(priv_file, "w", encoding="utf-8") as f:
                f.write("def _internal_helper():\n    pass\n")

            blast = compute_blast_radius("_internal_helper", root=tmpdir)
            assert blast["ok"] is True
            assert blast["severity"] == "LOW"


class TestExportGraphJson:
    def test_exports_valid_nodes_and_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = os.path.join(tmpdir, "a.py")
            f2 = os.path.join(tmpdir, "b.py")
            with open(f1, "w", encoding="utf-8") as f:
                f.write("def foo(): return 1\n")
            with open(f2, "w", encoding="utf-8") as f:
                f.write("from a import foo\ndef bar(): return foo()\n")

            data = export_graph_json(tmpdir)
            assert data["ok"] is True
            assert len(data["nodes"]) >= 2
            assert any(n["path"] == "a.py" for n in data["nodes"])
            assert any(n["path"] == "b.py" for n in data["nodes"])
            assert len(data["edges"]) >= 1
