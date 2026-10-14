"""tests/test_tdd_loop.py — Verify Autonomous Self-Healing TDD Engine."""

import os
import sys
import tempfile
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tdd_loop import run_tdd_cycle


class TestTDDLoop:
    def test_tdd_cycle_success_flow(self, monkeypatch):
        # Prepare simulated LLM responses for RED and GREEN phases
        responses = [
            # RED phase response (write test)
            (
                "FILE: tests/test_simple_math.py\n"
                "```python\n"
                "from simple_math import multiply\n"
                "def test_multiply():\n"
                "    assert multiply(3, 4) == 12\n"
                "```\n"
            ),
            # GREEN phase response (write implementation)
            (
                "FILE: simple_math.py\n"
                "```python\n"
                "def multiply(a, b):\n"
                "    return a * b\n"
                "```\n"
            )
        ]

        def mock_ask(prompt, system=None, backend=None):
            return responses.pop(0)

        monkeypatch.setattr("agent.tdd_loop.ask", mock_ask)

        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = os.path.join(tmpdir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            res = run_tdd_cycle(
                task="Implement multiply function",
                workspace=tmpdir,
                confirm_edits=False
            )

            assert res["ok"] is True
            assert res["status"] == "SUCCESS"
            assert "test_simple_math.py" in res["test_file"]
            assert os.path.exists(os.path.join(tmpdir, "simple_math.py"))

    def test_tdd_cycle_self_healing_flow(self, monkeypatch):
        # 1. RED phase: write test
        # 2. GREEN phase: write buggy implementation (fails test)
        # 3. HEAL phase: surgical SEARCH/REPLACE diff to fix bug
        responses = [
            # RED
            (
                "FILE: tests/test_calc.py\n"
                "```python\n"
                "from calc_engine import double\n"
                "def test_double():\n"
                "    assert double(5) == 10\n"
                "```\n"
            ),
            # GREEN (buggy: returns 15 instead of 10)
            (
                "FILE: calc_engine.py\n"
                "```python\n"
                "def double(x):\n"
                "    return x * 3\n"
                "```\n"
            ),
            # HEAL (surgical fix)
            (
                "FILE: calc_engine.py\n"
                "<<<<<<< SEARCH\n"
                "    return x * 3\n"
                "=======\n"
                "    return x * 2\n"
                ">>>>>>> REPLACE\n"
            )
        ]

        def mock_ask(prompt, system=None, backend=None):
            return responses.pop(0)

        monkeypatch.setattr("agent.tdd_loop.ask", mock_ask)

        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = os.path.join(tmpdir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            res = run_tdd_cycle(
                task="Implement double function",
                workspace=tmpdir,
                confirm_edits=False
            )

            assert res["ok"] is True
            assert res["status"] == "SUCCESS"
            assert res["heal_attempts"] == 1
            content = open(os.path.join(tmpdir, "calc_engine.py")).read()
            assert "return x * 2" in content

    def test_handles_model_failure_gracefully(self, monkeypatch):
        monkeypatch.setattr("agent.tdd_loop.ask", lambda prompt, system=None, backend=None: "No code here.")
        with tempfile.TemporaryDirectory() as tmpdir:
            res = run_tdd_cycle(task="Broken task", workspace=tmpdir)
            assert res["ok"] is False
            assert res["status"] == "FAILED"
