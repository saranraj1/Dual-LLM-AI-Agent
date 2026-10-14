"""
tests/test_tool_interceptor.py — Tests for Qwen tool call extraction and execution.
"""

import pytest
import os
from agent.tool_interceptor import (
    extract_qwen_tool_calls,
    execute_tool_call,
    resolve_tool_calls_text,
)


class TestToolInterceptor:

    def test_extract_qwen_xml_tool_calls(self):
        text = """
I will check the files.
<tool_call>
<function=list_files>
<parameter=path>
.
</parameter>
</function>
</tool_call>
<tool_call>
<function=read_file>
<parameter=path>
main.py
</parameter>
<parameter=limit>
50
</parameter>
<parameter=offset>
10
</parameter>
</function>
</tool_call>
"""
        calls = extract_qwen_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["function"] == "list_files"
        assert calls[0]["parameters"]["path"] == "."
        assert calls[1]["function"] == "read_file"
        assert calls[1]["parameters"]["path"] == "main.py"
        assert calls[1]["parameters"]["limit"] == 50
        assert calls[1]["parameters"]["offset"] == 10

    def test_extract_json_tool_calls(self):
        text = """
<tool_call>
{"name": "grep_search", "arguments": {"query": "def run"}}
</tool_call>
"""
        calls = extract_qwen_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["function"] == "grep_search"
        assert calls[0]["parameters"]["query"] == "def run"

    def test_execute_list_files(self, tmp_path):
        (tmp_path / "file1.py").write_text("print('hello')", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file2.py").write_text("print('world')", encoding="utf-8")

        res = execute_tool_call("list_files", {"path": "."}, workspace=str(tmp_path))
        assert "file1.py" in res

    def test_execute_read_file(self, tmp_path):
        target = tmp_path / "sample.txt"
        target.write_text("line 1\nline 2\nline 3\nline 4\nline 5", encoding="utf-8")

        res = execute_tool_call("read_file", {"path": "sample.txt", "offset": 2, "limit": 2}, workspace=str(tmp_path))
        lines = res.splitlines()
        assert len(lines) == 2
        assert "2: line 2" in lines[0]
        assert "3: line 3" in lines[1]

    def test_execute_grep_search(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def special_function():\n    return 42\n", encoding="utf-8")

        res = execute_tool_call("grep_search", {"query": "special_function"}, workspace=str(tmp_path))
        assert "special_function" in res

    def test_execute_unknown_tool(self):
        res = execute_tool_call("unknown_tool_xyz", {})
        assert "not supported" in res
