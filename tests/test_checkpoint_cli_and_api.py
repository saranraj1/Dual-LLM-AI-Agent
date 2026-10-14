"""
tests/test_checkpoint_cli_and_api.py — Integration tests for checkpoint CLI commands and API endpoints.
"""

import os
import shutil
import tempfile
import subprocess
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from agent.commands.files import cmd_undo, cmd_checkpoints
from fastapi.testclient import TestClient
from server.api import app


@pytest.fixture
def agent_workspace():
    tmp = tempfile.mkdtemp(prefix="test_agent_cp_")
    try:
        subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp, check=True, capture_output=True)

        f = Path(tmp) / "main.py"
        f.write_text("print('v1')", encoding="utf-8")
        subprocess.run(["git", "add", "main.py"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "v1 commit"], cwd=tmp, check=True, capture_output=True)

        agent = MagicMock()
        agent.workspace = tmp
        yield agent
    finally:
        import stat
        def _on_err(func, p, _):
            try:
                os.chmod(p, stat.S_IWRITE)
                func(p)
            except Exception:
                pass
        shutil.rmtree(tmp, onerror=_on_err, ignore_errors=True)


class TestCheckpointCLI:

    def test_cmd_checkpoints_empty(self, agent_workspace):
        out = cmd_checkpoints(agent_workspace, "")
        assert "No checkpoints recorded" in out

    def test_cmd_undo_and_checkpoints_flow(self, agent_workspace):
        from tools.checkpoint_tools import create_checkpoint
        create_checkpoint(description="turn 1 test", root_dir=agent_workspace.workspace)

        # Checkpoints command shows turn 1
        cp_out = cmd_checkpoints(agent_workspace, "")
        assert "turn 1 test" in cp_out

        # Mutate main.py
        p = Path(agent_workspace.workspace) / "main.py"
        p.write_text("print('corrupted')", encoding="utf-8")

        # Run /undo
        undo_out = cmd_undo(agent_workspace, "")
        assert "Restored full workspace" in undo_out or "✅" in undo_out
        assert p.read_text(encoding="utf-8") == "print('v1')"


class TestCheckpointAndPreflightAPI:

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_get_checkpoints_api(self, client):
        resp = client.get("/api/checkpoints")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "checkpoints" in data

    def test_preflight_valid_api(self, client):
        payload = {
            "file_path": "test.py",
            "content": "def hello():\n    return 'world'\n"
        }
        resp = client.post("/api/preflight", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_preflight_invalid_api(self, client):
        payload = {
            "file_path": "test.py",
            "content": "def broken(\n"
        }
        resp = client.post("/api/preflight", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "SyntaxError" in data["error"]
