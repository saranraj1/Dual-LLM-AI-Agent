"""
tests/test_compactor.py — Unit tests for context compactor and working memory ledger.
"""

from unittest.mock import MagicMock
from agent.compactor import (
    WorkingState,
    should_compact,
    compact_history,
    calculate_history_chars,
    cmd_compact
)


class TestCompactor:

    def test_working_state_ledger(self):
        ws = WorkingState(goal="Implement user authentication")
        ws.record_file("models/user.py")
        ws.record_file("models/user.py")  # Deduplication
        ws.record_decision("Use SQLite for zero-setup database")
        ws.record_test("tests/test_user.py passed")

        md = ws.to_markdown()
        assert "Implement user authentication" in md
        assert "`models/user.py`" in md
        assert "SQLite" in md
        assert "test_user.py" in md

    def test_should_compact_threshold_calculation(self):
        budget = 10000
        assert should_compact(5000, budget) is False
        assert should_compact(7500, budget) is True
        assert should_compact(9000, budget) is True

    def test_compact_history_reduces_chars(self):
        ws = WorkingState(goal="Refactor database schema")
        long_content = "some verbose intermediate step output " * 50
        history = [
            {"role": "user", "content": "Initial prompt: refactor database"},
            {"role": "assistant", "content": long_content},
            {"role": "assistant", "content": "Surgically edited: db/schema.py"},
            {"role": "assistant", "content": "Final step details here"}
        ]

        original_chars = calculate_history_chars(history)
        compacted, was_done, summary = compact_history(history, ws, force=True, budget_chars=2000)

        assert was_done is True
        new_chars = calculate_history_chars(compacted)
        assert new_chars < original_chars
        assert any("Active Working State" in t["content"] for t in compacted)
        assert "db/schema.py" in ws.modified_files

    def test_cmd_compact_clears_and_replaces_short_mem(self):
        agent = MagicMock()
        agent.short_mem.get_turns.return_value = [
            {"role": "user", "content": "Build feature X"},
            {"role": "assistant", "content": "Verbose turn " * 40},
            {"role": "assistant", "content": "Surgically edited: feature.py"}
        ]
        agent.working_state = WorkingState(goal="Build feature X")

        res = cmd_compact(agent, "")
        assert "Context compacted successfully" in res
        agent.short_mem.clear.assert_called_once()
        assert agent.short_mem.add.call_count >= 2
