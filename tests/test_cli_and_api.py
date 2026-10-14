"""
tests/test_cli_and_api.py — Verification of Phase 3 CLI & Phase 4 API endpoints.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from agent.commands.code_quality import cmd_tdd, cmd_blast
from agent.executor import _check_blast_radius_advisory, _auto_edit_files
from server.api import app


class TestCLIAndCommands:
    def test_cmd_tdd_usage(self):
        agent = MagicMock()
        res = cmd_tdd(agent, "")
        assert "Usage: /tdd" in res

    def test_cmd_tdd_success(self):
        agent = MagicMock()
        agent.workspace = "."
        agent.confirm_edits = False
        agent.short_mem = MagicMock()
        agent.long_mem = MagicMock()

        mock_result = {
            "status": "COMPLETED",
            "test_file": "tests/test_calc.py",
            "patched_files": ["calc.py"],
            "heal_attempts": 0,
        }
        with patch("agent.tdd_loop.run_tdd_cycle", return_value=mock_result):
            res = cmd_tdd(agent, "Add multiply function")
            assert "✅ TDD Cycle Succeeded!" in res
            assert "tests/test_calc.py" in res

    def test_cmd_blast_usage(self):
        agent = MagicMock()
        res = cmd_blast(agent, "")
        assert "Usage: /blast" in res

    def test_cmd_blast_output(self, tmp_path):
        agent = MagicMock()
        agent.workspace = str(tmp_path)

        foo = tmp_path / "foo.py"
        foo.write_text("def target_fn():\n    return 42\n", encoding="utf-8")
        bar = tmp_path / "bar.py"
        bar.write_text("from foo import target_fn\ndef caller():\n    return target_fn()\n", encoding="utf-8")

        res = cmd_blast(agent, "target_fn")
        assert "target_fn" in res
        assert "Direct Callers:" in res
        assert "bar.py" in res

    def test_executor_blast_radius_advisory(self, tmp_path, capsys):
        foo = tmp_path / "foo.py"
        foo.write_text("def greet(name):\n    return f'hello {name}'\n", encoding="utf-8")
        bar = tmp_path / "bar.py"
        bar.write_text("from foo import greet\ndef run():\n    greet('world')\n", encoding="utf-8")

        # Test advisory helper
        _check_blast_radius_advisory("def greet(name):", "foo.py", str(tmp_path))
        captured = capsys.readouterr().out
        assert "Blast Radius" in captured
        assert "greet" in captured
        assert "bar.py" in captured


class TestAPIEndpoints:
    @pytest.fixture
    def client(self, tmp_path):
        from server import api
        mock_agent = MagicMock()
        mock_agent.workspace = str(tmp_path)
        api._agent = mock_agent

        # Create sample files in tmp_path
        app_file = tmp_path / "app.py"
        app_file.write_text("def start():\n    return 'started'\n", encoding="utf-8")
        test_file = tmp_path / "test_app.py"
        test_file.write_text("from app import start\ndef test_start():\n    assert start() == 'started'\n", encoding="utf-8")

        return TestClient(app)

    def test_get_graph_endpoint(self, client):
        response = client.get("/graph")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "graph" in data
        assert "nodes" in data["graph"]
        assert "links" in data["graph"]

    def test_get_blast_endpoint(self, client):
        response = client.get("/blast?symbol=start")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "blast" in data
        blast = data["blast"]
        assert blast["target_symbol"] == "start"
        assert blast["caller_count"] >= 1
        assert len(blast["affected_tests"]) >= 1

    def test_post_command_blast(self, client):
        response = client.post("/command", json={"command": "/blast start"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "command" in data
        assert data["command"] == "blast"
