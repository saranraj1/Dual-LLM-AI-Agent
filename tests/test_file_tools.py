"""tests/test_file_tools.py — Verify file read/write/scan tools."""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from tools.file_tools import read_file, write_file, scan_codebase


class TestReadFile:
    def test_reads_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                         delete=False, encoding="utf-8") as f:
            f.write("x = 42\n")
            path = f.name
        try:
            result = read_file(path)
            assert result["ok"] is True
            assert "x = 42" in result["content"]
        finally:
            os.unlink(path)

    def test_returns_error_for_missing_file(self):
        result = read_file("/nonexistent/path/file.py")
        assert result["ok"] is False
        assert "error" in result

    def test_reads_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False, encoding="utf-8") as f:
            path = f.name
        try:
            result = read_file(path)
            assert result["ok"] is True
            assert result["content"] == ""
        finally:
            os.unlink(path)


class TestWriteFile:
    def test_creates_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "new_file.py")
            result = write_file(path, "print('hello')\n")
            assert result["ok"] is True
            assert os.path.exists(path)
            assert "hello" in open(path).read()

    def test_overwrites_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                         delete=False, encoding="utf-8") as f:
            f.write("old content")
            path = f.name
        try:
            write_file(path, "new content")
            assert open(path).read() == "new content"
        finally:
            os.unlink(path)

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "deep", "nested", "file.txt")
            result = write_file(path, "data")
            assert result["ok"] is True
            assert os.path.exists(path)


class TestScanCodebase:
    def test_scans_python_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a couple of Python files
            for name in ["a.py", "b.py"]:
                open(os.path.join(tmpdir, name), "w").write("x = 1")
            result = scan_codebase(tmpdir)
            assert result["ok"] is True
            assert result["count"] >= 2

    def test_skips_pycache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "__pycache__")
            os.makedirs(cache_dir)
            open(os.path.join(cache_dir, "module.pyc"), "w").write("junk")
            open(os.path.join(tmpdir, "main.py"), "w").write("x = 1")
            result = scan_codebase(tmpdir)
            paths = [f for f in result.get("paths", [])]
            assert not any("__pycache__" in p for p in paths)

    def test_empty_directory_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_codebase(tmpdir)
            assert result["ok"] is True
            assert result["count"] == 0


class TestReplaceInFile:
    def test_replaces_single_exact_block(self):
        from tools.file_tools import replace_in_file
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "calc.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("def add(a, b):\n    return a - b\n")

            res = replace_in_file(p, "return a - b", "return a + b")
            assert res["ok"] is True
            assert res["occurrences"] == 1
            with open(p, "r", encoding="utf-8") as f:
                assert "return a + b" in f.read()

    def test_returns_error_when_target_not_found(self):
        from tools.file_tools import replace_in_file
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "calc.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("def foo():\n    pass\n")

            res = replace_in_file(p, "def non_existent():", "something")
            assert res["ok"] is False
            assert "Target content not found" in res["error"]

    def test_returns_error_when_target_occurs_multiple_times(self):
        from tools.file_tools import replace_in_file
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "dups.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("x = 1\nx = 1\n")

            res = replace_in_file(p, "x = 1", "x = 2")
            assert res["ok"] is False
            assert "found 2 times" in res["error"]

    def test_replaces_with_crlf_normalization(self):
        from tools.file_tools import replace_in_file
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "crlf.py")
            # Write with explicit Windows CRLF
            with open(p, "wb") as f:
                f.write(b"def greet():\r\n    return 'hi'\r\n")

            # Target uses standard LF
            res = replace_in_file(p, "return 'hi'", "return 'hello'")
            assert res["ok"] is True
            content = open(p, "r", encoding="utf-8").read()
            assert "return 'hello'" in content


class TestGetRepoMap:
    def test_generates_symbols_for_classes_and_functions(self):
        from tools.file_tools import get_repo_map
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "sample.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(
                    "class Calculator:\n"
                    "    def add(self, a, b):\n"
                    "        return a + b\n"
                    "\n"
                    "def helper_func():\n"
                    "    pass\n"
                    "\n"
                    "def _private_func():\n"
                    "    pass\n"
                )

            repo_map = get_repo_map(tmpdir)
            assert "sample.py:" in repo_map
            assert "class Calculator:" in repo_map
            assert "def add()" in repo_map
            assert "def helper_func()" in repo_map
            assert "_private_func" not in repo_map


class TestRankCodebaseFiles:
    def test_ranks_relevant_files_higher_by_bm25(self):
        from tools.file_tools import rank_codebase_files
        with tempfile.TemporaryDirectory() as tmpdir:
            math_file = os.path.join(tmpdir, "math_ops.py")
            with open(math_file, "w", encoding="utf-8") as f:
                f.write("def fibonacci(n):\n    # sequence algorithm calculation\n    return n\n")

            text_file = os.path.join(tmpdir, "text_ops.py")
            with open(text_file, "w", encoding="utf-8") as f:
                f.write("def uppercase(s):\n    return s.upper()\n")

            res = rank_codebase_files(tmpdir, query="fibonacci calculation")
            assert res["ok"] is True
            assert len(res["files"]) > 0
            file_keys = list(res["files"].keys())
            assert "math_ops.py" == file_keys[0]
            assert res["scores"]["math_ops.py"] > res["scores"].get("text_ops.py", 0)

    def test_boosts_matching_filename(self):
        from tools.file_tools import rank_codebase_files
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "database.py")
            with open(db_file, "w", encoding="utf-8") as f:
                f.write("# connection pool\n")

            other_file = os.path.join(tmpdir, "other.py")
            with open(other_file, "w", encoding="utf-8") as f:
                f.write("# general code\n")

            res = rank_codebase_files(tmpdir, query="database pool")
            assert res["ok"] is True
            file_keys = list(res["files"].keys())
            assert "database.py" == file_keys[0]

    def test_fallback_to_scan_when_empty_query(self):
        from tools.file_tools import rank_codebase_files
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "dummy.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("val = 123\n")

            res = rank_codebase_files(tmpdir, query="")
            assert res["ok"] is True
            assert "dummy.py" in res["files"]


