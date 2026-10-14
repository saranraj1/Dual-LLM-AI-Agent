"""
tests/test_subagent_pool.py — Unit tests for subagent pool and worker isolation.
"""

import tempfile
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from agent.subagent_pool import (
    WorkerRole,
    SubagentWorker,
    run_subagent,
    cmd_delegate
)
from fastapi.testclient import TestClient
from server.api import app


class TestSubagentPool:

    def test_researcher_finds_code_references(self):
        tmp = tempfile.mkdtemp(prefix="test_sub_")
        try:
            f = Path(tmp) / "auth.py"
            f.write_text("def authenticate_jwt(token: str):\n    return True\n", encoding="utf-8")

            res = run_subagent("researcher", "authenticate_jwt", workspace=tmp)
            assert res["ok"] is True
            assert "auth.py" in res["summary"]
            assert "authenticate_jwt" in res["summary"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_test_runner_worker_reports_status(self):
        worker = SubagentWorker(WorkerRole.TEST_RUNNER)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="==== 5 passed in 0.5s ====",
                stderr=""
            )
            res = worker.execute("tests/test_demo.py")
            assert res["ok"] is True
            assert "PASSED" in res["summary"]

    def test_reviewer_worker_analyzes_diff(self):
        worker = SubagentWorker(WorkerRole.REVIEWER)
        with patch("agent.subagent_pool.ask") as mock_ask:
            mock_ask.return_value = "- Clean minimal change\n- No extra dependencies added"
            res = worker.execute("diff --git a/app.py b/app.py")
            assert res["ok"] is True
            assert "Clean minimal change" in res["summary"]

    def test_cmd_delegate_cli_flow(self):
        agent = MagicMock()
        agent.workspace = "."
        with patch("agent.subagent_pool.run_subagent") as mock_sub:
            mock_sub.return_value = {
                "ok": True,
                "role": "researcher",
                "summary": "Found 2 matching functions in core/llm.py"
            }
            out = cmd_delegate(agent, "researcher find llm fallbacks")
            assert "RESEARCHER" in out
            assert "core/llm.py" in out


class TestNewPillarsAPIEndpoints:

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_compact_api(self, client):
        resp = client.post("/api/compact", json={"force": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_delegate_api(self, client):
        with patch("agent.subagent_pool.run_subagent") as mock_sub:
            mock_sub.return_value = {
                "ok": True,
                "role": "researcher",
                "summary": "Mock findings in database.py"
            }
            resp = client.post("/api/delegate", json={"role": "researcher", "task": "find db"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert "database.py" in data["summary"]

    def test_react_run_api(self, client):
        with patch("agent.react_harness.run_react_loop") as mock_react:
            mock_react.return_value = {
                "ok": True,
                "answer": "Task solved via ReAct loop",
                "turns": 1,
                "history": []
            }
            resp = client.post("/api/react/run", json={"task": "inspect code"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert "Task solved via ReAct loop" in data["answer"]
