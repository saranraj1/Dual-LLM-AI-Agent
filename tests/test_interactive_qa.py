"""
tests/test_interactive_qa.py — Unit tests for the Interactive QA & User Decision system.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from agent.interactive_qa import (
    extract_ask_user_blocks,
    ask_user,
    cmd_ask_user,
    set_question_handler,
    get_pending_questions,
    answer_pending_question,
)
from server.api import app


class TestExtractAskUserBlocks:
    def test_extract_single_block(self):
        text = """
Some initial reasoning here.
ASK_USER: Which caching backend should we install?
OPTION: Redis (Distributed)
OPTION: Memcached
OPTION: In-Memory Dict (Recommended)
DEFAULT: 3

Other text following.
"""
        blocks = extract_ask_user_blocks(text)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["question"] == "Which caching backend should we install?"
        assert len(b["options"]) == 3
        assert b["options"][0] == "Redis (Distributed)"
        assert b["options"][2] == "In-Memory Dict (Recommended)"
        assert b["default"] == "3"

    def test_extract_no_blocks(self):
        text = "def hello():\n    return 'world'\n"
        blocks = extract_ask_user_blocks(text)
        assert blocks == []

    def test_extract_multiple_blocks(self):
        text = """
ASK_USER: What port should we use?
OPTION: 3000
OPTION: 8080

ASK_USER: Enable debug logging?
OPTION: Yes
OPTION: No
DEFAULT: Yes
"""
        blocks = extract_ask_user_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["question"] == "What port should we use?"
        assert blocks[1]["question"] == "Enable debug logging?"


class TestAskUserFunction:
    def test_non_interactive_fallback(self):
        with patch.object(sys.stdin, "isatty", return_value=False):
            ans = ask_user("Choose color", options=["red", "blue"], default="blue")
            assert ans == "blue"

    def test_custom_handler_hook(self):
        def mock_handler(q_data):
            return f"Answered: {q_data['options'][0]}"

        set_question_handler(mock_handler)
        try:
            ans = ask_user("Select theme", options=["dark", "light"])
            assert ans == "Answered: dark"
        finally:
            set_question_handler(None)

    def test_interactive_choice_by_number(self):
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="2"):
                ans = ask_user("Pick framework", options=["Django", "FastAPI", "Flask"])
                assert ans == "FastAPI"

    def test_interactive_choice_custom_text(self):
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="Sanic"):
                ans = ask_user("Pick framework", options=["Django", "FastAPI"])
                assert ans == "Sanic"


class TestCmdAskUser:
    def test_cmd_ask_user_usage(self):
        agent = MagicMock()
        res = cmd_ask_user(agent, "")
        assert "Usage: /qa" in res

    def test_cmd_ask_user_execution(self):
        agent = MagicMock()
        agent.short_mem = MagicMock()

        with patch("agent.interactive_qa.ask_user", return_value="SQLite"):
            res = cmd_ask_user(agent, "Which database? | SQLite | PostgreSQL")
            assert "Question: Which database?" in res
            assert "User selected: SQLite" in res
            agent.short_mem.add.assert_called_once()


class TestExecutorIntegration:
    def test_executor_captures_ask_user_block(self, tmp_path):
        from agent.executor import execute_step

        sample_llm_response = """
ASK_USER: What table name should we use?
OPTION: users (Standard)
OPTION: accounts
DEFAULT: users

FILE: models.py
```
class User:
    pass
```
"""
        with patch("agent.executor.ask", return_value=sample_llm_response):
            with patch("agent.interactive_qa.ask_user", return_value="users (Standard)"):
                res = execute_step(
                    step="Create user model",
                    task="Setup database models",
                    cwd=str(tmp_path),
                )
                assert res["ok"] is True
                assert any("User Decision" in log for log in res["result"].splitlines())


class TestAPIQAEndpoints:
    @pytest.fixture
    def client(self, tmp_path):
        from server import api
        mock_agent = MagicMock()
        mock_agent.workspace = str(tmp_path)
        mock_agent.ask_user = MagicMock(return_value="Answer: SQLite")
        api._agent = mock_agent
        return TestClient(app)

    def test_qa_pending_and_answer(self):
        # Register a question manually
        q_id = "test-q-1"
        from agent.interactive_qa import _pending_questions, _question_lock
        with _question_lock:
            _pending_questions[q_id] = {
                "question": "Choose framework",
                "options": ["FastAPI", "Flask"],
                "default": "FastAPI",
                "timestamp": 12345.0,
                "event": MagicMock(),
            }

        client = TestClient(app)
        res = client.get("/qa/pending")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert any(q["id"] == q_id for q in data["questions"])

        # Answer question
        ans_res = client.post("/qa/answer", json={"id": q_id, "answer": "FastAPI"})
        assert ans_res.status_code == 200
        assert ans_res.json()["ok"] is True

        # Clean up
        with _question_lock:
            _pending_questions.pop(q_id, None)

    def test_qa_ask_endpoint(self, client):
        res = client.post("/qa/ask", json={
            "question": "Which database engine?",
            "options": ["SQLite", "Postgres"],
        })
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["question"] == "Which database engine?"
