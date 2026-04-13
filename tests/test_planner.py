"""tests/test_planner.py — Verify the planner produces valid step lists."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch


class TestPlanner:
    def test_returns_list_of_steps(self):
        from agent.planner import plan
        fake_response = "1. Scan the codebase\n2. Write the function\n3. Run and test it"
        with patch("agent.planner.ask", return_value=fake_response):
            steps = plan("Create a hello world function")
        assert isinstance(steps, list)
        assert len(steps) >= 1

    def test_steps_are_non_empty_strings(self):
        from agent.planner import plan
        fake_response = "1. Step one\n2. Step two\n3. Step three"
        with patch("agent.planner.ask", return_value=fake_response):
            steps = plan("Build a REST API")
        for step in steps:
            assert isinstance(step, str)
            assert len(step.strip()) > 0

    def test_max_steps_not_exceeded(self):
        from agent.planner import plan
        from config.settings import MAX_PLAN_STEPS
        # Even if LLM returns many steps, planner should cap them
        long_response = "\n".join(f"{i}. Step {i}" for i in range(1, 20))
        with patch("agent.planner.ask", return_value=long_response):
            steps = plan("Very long task")
        assert len(steps) <= MAX_PLAN_STEPS

    def test_handles_llm_error_gracefully(self):
        from agent.planner import plan
        with patch("agent.planner.ask", return_value="[LLM ERROR] Connection refused"):
            steps = plan("Task that causes LLM error")
        # Should return at least one fallback step, not raise an exception
        assert isinstance(steps, list)
        assert len(steps) >= 1

    def test_strips_numbering_from_steps(self):
        from agent.planner import plan
        fake_response = "1. Read the file\n2. Analyze the code\n3. Write the fix"
        with patch("agent.planner.ask", return_value=fake_response):
            steps = plan("Fix the bug")
        # Steps should not start with "1." "2." etc.
        for step in steps:
            assert not step.strip()[0].isdigit() or "." not in step[:3]
