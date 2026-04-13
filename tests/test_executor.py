"""tests/test_executor.py — Verify file extraction and path clamping."""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from agent.executor import (
    _extract_file_blocks,
    _extract_pip_packages,
    _extract_shell_commands,
    _auto_write_files,
)


class TestExtractFileBlocks:
    def test_extracts_single_file_block(self):
        text = 'FILE: main.py\n```python\nprint("hello")\n```'
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["path"] == "main.py"
        assert 'print("hello")' in blocks[0]["content"]

    def test_extracts_multiple_file_blocks(self):
        text = (
            'FILE: a.py\n```python\nx = 1\n```\n\n'
            'FILE: b.py\n```python\ny = 2\n```'
        )
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["path"] == "a.py"
        assert blocks[1]["path"] == "b.py"

    def test_returns_empty_list_when_no_blocks(self):
        text = "Here is some text without any file blocks."
        blocks = _extract_file_blocks(text)
        assert blocks == []

    def test_handles_nested_path(self):
        text = 'FILE: src/utils/helper.py\n```python\ndef foo(): pass\n```'
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 1
        assert "src/utils/helper.py" in blocks[0]["path"]


class TestPathClamping:
    def test_absolute_windows_path_clamped_to_cwd(self):
        """LLM-hallucinated absolute Windows paths must be forced into cwd."""
        text = 'FILE: C:/project/main.py\n```python\nprint("hi")\n```'
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 1

        with tempfile.TemporaryDirectory() as tmpdir:
            written = _auto_write_files(blocks, tmpdir)
            assert len(written) == 1
            # File must be INSIDE tmpdir, not at C:\project\
            assert written[0].startswith(tmpdir)
            assert os.path.exists(written[0])

    def test_absolute_unix_path_clamped_to_cwd(self):
        """LLM-hallucinated /src/main.py must end up inside the cwd."""
        text = 'FILE: /src/main.py\n```python\nvalue = 42\n```'
        blocks = _extract_file_blocks(text)

        with tempfile.TemporaryDirectory() as tmpdir:
            written = _auto_write_files(blocks, tmpdir)
            assert len(written) == 1
            assert written[0].startswith(tmpdir)

    def test_relative_path_resolves_inside_cwd(self):
        """Relative paths stay inside the workspace."""
        text = 'FILE: scripts/test.py\n```python\npass\n```'
        blocks = _extract_file_blocks(text)

        with tempfile.TemporaryDirectory() as tmpdir:
            written = _auto_write_files(blocks, tmpdir)
            assert len(written) == 1
            assert written[0].startswith(tmpdir)


class TestExtractPipPackages:
    def test_finds_pip_install(self):
        text = "Run pip install requests to install it."
        pkgs = _extract_pip_packages(text)
        assert "requests" in pkgs

    def test_finds_multiple_packages(self):
        text = "pip install flask\npip install sqlalchemy"
        pkgs = _extract_pip_packages(text)
        assert "flask" in pkgs
        assert "sqlalchemy" in pkgs

    def test_returns_empty_when_none(self):
        text = "No packages here."
        pkgs = _extract_pip_packages(text)
        assert pkgs == []
