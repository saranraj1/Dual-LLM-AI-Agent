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
