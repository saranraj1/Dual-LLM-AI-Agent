"""
tests/test_react_harness.py — Unit tests for ReAct harness and tool execution.
"""

import tempfile
import shutil
import pytest
from pathlib import Path
from agent.react_harness import (
    ToolRegistry,
    SecurityTier,
    classify_command_security,
    parse_react_step,
    run_react_loop,
)


@pytest.fixture
def test_workspace():
    tmp = tempfile.mkdtemp(prefix="test_react_ws_")
    try:
        f = Path(tmp) / "demo.py"
        f.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class TestReActHarness:

    def test_classify_command_security_tiers(self):
        assert classify_command_security("git status") == SecurityTier.SAFE_READ
        assert classify_command_security("dir") == SecurityTier.SAFE_READ
        assert classify_command_security("python app.py") == SecurityTier.SAFE_MUTATION
        assert classify_command_security("rm -rf /") == SecurityTier.DESTRUCTIVE
        assert classify_command_security("git reset --hard") == SecurityTier.DESTRUCTIVE

    def test_tool_registry_read_and_edit_file(self, test_workspace):
        reg = ToolRegistry(workspace=test_workspace)

        # Read file
        content = reg.execute("read_file", {"path": "demo.py"})
        assert "def hello():" in content

        # Edit file
        res = reg.execute("edit_file", {"path": "demo.py", "target": "'world'", "replacement": "'react'"})
        assert "Successfully replaced target" in res
        updated = Path(test_workspace) / "demo.py"
        assert "'react'" in updated.read_text(encoding="utf-8")

    def test_parse_react_step_text_format(self):
        resp = """Thought: Need to read file
Action: read_file
Action Input: {"path": "app.py", "start_line": 1}"""
        step = parse_react_step(resp)
        assert step is not None
        assert step["action"] == "read_file"
        assert step["input"]["path"] == "app.py"

    def test_parse_react_step_json_format(self):
        resp = """```json
{
  "action": "shell_command",
  "input": {"command": "git status"}
}
```"""
        step = parse_react_step(resp)
        assert step is not None
        assert step["action"] == "shell_command"
        assert step["input"]["command"] == "git status"

    def test_run_react_loop_flow(self, test_workspace):
        reg = ToolRegistry(workspace=test_workspace)

        turns = [
            'Thought: I should check demo.py\nAction: read_file\nAction Input: {"path": "demo.py"}',
            'Thought: Everything is fine\nFinal Answer: demo.py returns world'
        ]
        it = iter(turns)

        def mock_llm(prompt, system):
            return next(it)

        result = run_react_loop("Inspect demo.py", registry=reg, llm_ask=mock_llm)
        assert result["ok"] is True
        assert "demo.py returns world" in result["answer"]
        assert result["turns"] == 2
