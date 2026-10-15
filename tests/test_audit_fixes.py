"""
tests/test_audit_fixes.py — Rigorous regression tests for critical codebase audit fixes.
"""

import os
import sys
import threading
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.cost_tracker import CostTracker
from memory.fix_memory import FixMemory
from tools.file_tools import replace_in_file, append_file
from agent.executor import _auto_write_files, _auto_edit_files
from agent.project_builder import heal_failing_tests, ProjectSpec
from core.prompt_builder import build as build_prompt
from tools.terminal_tools import run_command
from agent.watcher import cmd_watch
from agent.react_harness import run_react_loop, ToolRegistry
from agent.tool_interceptor import get_registry_for_workspace, execute_tool_call


class TestMemoryCleanliness:
    def test_chat_does_not_compound_history(self, tmp_path):
        from agent.agent import Agent
        agent = Agent(workspace=str(tmp_path))
        # Mock resolve_tool_calls_stream
        with patch("agent.tool_interceptor.resolve_tool_calls_stream", return_value=iter(["Hello there!"])):
            agent.chat("First question")
            agent.chat("Second question")

        turns = agent.short_mem.get_turns(10)
        user_turns = [t["content"] for t in turns if t["role"] == "user"]
        assert len(user_turns) == 2
        assert user_turns[0] == "First question"
        assert user_turns[1] == "Second question"
        assert "First question" not in user_turns[1]


class TestDatabaseConcurrency:
    def test_cost_tracker_multithreading(self, tmp_path):
        tracker = CostTracker()
        errors = []

        def worker(idx):
            try:
                for _ in range(10):
                    tracker.record("local", "llama", prompt_tokens=50, completion_tokens=25)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert tracker.session.ollama_calls >= 50

    def test_fix_memory_multithreading(self, tmp_path):
        fm = FixMemory()
        errors = []

        def worker(idx):
            try:
                for i in range(5):
                    fm.record(f"SyntaxError: invalid syntax {idx}_{i}", f"Fix {idx}_{i}")
                    hints = fm.get_hints(f"SyntaxError: invalid syntax {idx}_{i}")
                    assert len(hints) > 0
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestSensitiveFileProtectionInEditAndAppend:
    def test_append_file_blocks_sensitive(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=123", encoding="utf-8")
        res = append_file(str(env_file), "\nNEW_KEY=456")
        assert not res["ok"]
        assert "Access Denied" in res["error"]

    def test_replace_in_file_blocks_sensitive(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=123", encoding="utf-8")
        res = replace_in_file(str(env_file), "123", "999")
        assert not res["ok"]
        assert "Access Denied" in res["error"]


class TestExecutorPathSanitization:
    def test_auto_write_preserves_proper_path(self, tmp_path):
        file_blocks = [
            {"path": "nested/script.py", "content": "print('hello')\n"}
        ]
        written = _auto_write_files(file_blocks, str(tmp_path), confirm=False)
        assert len(written) == 1
        expected = tmp_path / "nested" / "script.py"
        assert expected.exists()
        assert expected.read_text(encoding="utf-8") == "print('hello')\n"

    def test_auto_write_blocks_escape(self, tmp_path):
        file_blocks = [
            {"path": "../../escape.py", "content": "print('danger')\n"}
        ]
        written = _auto_write_files(file_blocks, str(tmp_path), confirm=False)
        assert len(written) == 0
        assert not (tmp_path.parent / "escape.py").exists()


class TestToolInterceptorRegistryCaching:
    def test_registry_is_cached(self, tmp_path):
        reg1 = get_registry_for_workspace(str(tmp_path))
        reg2 = get_registry_for_workspace(str(tmp_path))
        assert reg1 is reg2

    def test_execute_tool_call_uses_cached(self, tmp_path):
        (tmp_path / "sample.txt").write_text("sample content", encoding="utf-8")
        out = execute_tool_call("read_file", {"path": "sample.txt"}, workspace=str(tmp_path))
        assert "sample content" in out


class TestNonPythonHealingInProjectBuilder:
    def test_healing_allows_non_python_fixes(self, tmp_path):
        spec = ProjectSpec(
            name="test_proj",
            description="Testing healing",
            files=[]
        )
        fake_llm = lambda prompt, system=None: (
            "FILE: requirements.txt\n"
            "```\n"
            "pytest>=8.0.0\n"
            "```\n"
        )
        with patch("agent.project_builder.run_project_tests", return_value={"passed": True, "output": "1 passed"}):
            res = heal_failing_tests("ModuleNotFoundError: No module named 'pytest'", spec, str(tmp_path), llm_fn=fake_llm)
            assert res["ok"] is True
            req_file = tmp_path / "requirements.txt"
            assert req_file.exists()
            assert "pytest>=8.0.0" in req_file.read_text(encoding="utf-8")


class TestPromptBudgetingAndWatcher:
    def test_dynamic_code_budget_expands_when_no_memory(self):
        long_code = "print('line')\n" * 500  # ~7000 chars
        prompt = build_prompt(
            task="Optimize this code",
            memory_context="",
            code_context=long_code,
            repo_map="",
            tool_results=""
        )
        assert "print('line')" in prompt
        # Ensure code is not prematurely trimmed when there is ample budget
        assert "...[trimmed]..." not in prompt

    def test_watcher_blocks_headless_infinite_loop(self):
        agent = MagicMock()
        agent.workspace = "."
        with patch("sys.stdin.isatty", return_value=False):
            res = cmd_watch(agent, "")
            assert "interactive terminal" in res


class TestReActHistoryAndTerminalTools:
    def test_react_loop_records_history(self):
        registry = ToolRegistry(".")
        # Mock LLM stream to emit Thought -> Final Answer
        fake_stream = [
            {"type": "thought", "turn": 1, "content": "I should answer directly"},
            {"type": "final_answer", "turn": 1, "content": "The result is 42"}
        ]
        with patch("agent.react_harness.run_react_loop_stream", return_value=iter(fake_stream)):
            res = run_react_loop("What is the meaning of life?", registry)
            assert res["ok"] is True
            assert len(res["history"]) >= 3
            assert any("Thought: I should answer directly" in h for h in res["history"])
            assert any("Final Answer: The result is 42" in h for h in res["history"])

    def test_run_command_configurable_limits(self):
        res = run_command("python -c \"print('X' * 5000)\"", max_stdout_chars=3000)
        assert res["ok"] is True
        assert len(res["stdout"]) == 3000
