"""
tests/test_checkpoint_tools.py — Unit tests for shadow git checkpoints and undo engine.
"""

import os
import shutil
import tempfile
import subprocess
import pytest
from pathlib import Path
from tools.checkpoint_tools import (
    create_checkpoint,
    list_checkpoints,
    restore_checkpoint,
    _get_git_root
)


@pytest.fixture
def git_repo_dir():
    """Create an isolated temporary git repository for testing."""
    tmp = tempfile.mkdtemp(prefix="test_git_repo_")
    try:
        subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp, check=True, capture_output=True)

        # Create initial file
        f1 = Path(tmp) / "file1.txt"
        f1.write_text("initial version", encoding="utf-8")
        subprocess.run(["git", "add", "file1.txt"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp, check=True, capture_output=True)

        yield tmp
    finally:
        import stat
        def _on_err(func, p, _):
            try:
                os.chmod(p, stat.S_IWRITE)
                func(p)
            except Exception:
                pass
        shutil.rmtree(tmp, onerror=_on_err, ignore_errors=True)


class TestCheckpointTools:

    def test_get_git_root_returns_path_for_git_repo(self, git_repo_dir):
        root = _get_git_root(git_repo_dir)
        assert root is not None
        assert Path(git_repo_dir).resolve() == root.resolve()

    def test_create_checkpoint_generates_commit_and_saves_history(self, git_repo_dir):
        # Modify file1
        f1 = Path(git_repo_dir) / "file1.txt"
        f1.write_text("turn 1 changes", encoding="utf-8")

        res = create_checkpoint(description="Test turn 1", root_dir=git_repo_dir)
        assert res["ok"] is True
        assert "checkpoint" in res
        cp = res["checkpoint"]
        assert cp["description"] == "Test turn 1"
        assert len(cp["commit"]) == 40

        history = list_checkpoints(limit=5, root_dir=git_repo_dir)
        assert len(history) >= 1
        assert history[0]["id"] == cp["id"]

    def test_restore_checkpoint_reverts_workspace_changes(self, git_repo_dir):
        f1 = Path(git_repo_dir) / "file1.txt"
        f1.write_text("clean state", encoding="utf-8")

        # Checkpoint clean state
        cp_res = create_checkpoint(description="Clean state", root_dir=git_repo_dir)
        assert cp_res["ok"] is True

        # Now corrupt/mutate file
        f1.write_text("broken state by hallucinating agent", encoding="utf-8")
        assert f1.read_text(encoding="utf-8") == "broken state by hallucinating agent"

        # Undo
        undo_res = restore_checkpoint(root_dir=git_repo_dir)
        assert undo_res["ok"] is True
        assert f1.read_text(encoding="utf-8") == "clean state"

    def test_restore_checkpoint_specific_file(self, git_repo_dir):
        f1 = Path(git_repo_dir) / "file1.txt"
        f2 = Path(git_repo_dir) / "file2.txt"
        f1.write_text("f1 original", encoding="utf-8")
        f2.write_text("f2 original", encoding="utf-8")

        create_checkpoint(description="Both original", root_dir=git_repo_dir)

        # Mutate both
        f1.write_text("f1 modified", encoding="utf-8")
        f2.write_text("f2 modified", encoding="utf-8")

        # Restore ONLY file1
        restore_res = restore_checkpoint(target_file="file1.txt", root_dir=git_repo_dir)
        assert restore_res["ok"] is True
        assert f1.read_text(encoding="utf-8") == "f1 original"
        assert f2.read_text(encoding="utf-8") == "f2 modified"

    def test_non_git_repo_graceful_failure(self):
        tmp = tempfile.mkdtemp(prefix="test_non_git_")
        try:
            res = create_checkpoint(root_dir=tmp)
            assert res["ok"] is False
            assert "Not a git repository" in res["error"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
