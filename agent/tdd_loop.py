"""
agent/tdd_loop.py — Autonomous Self-Healing TDD (Test-Driven Development) Engine.

Executes closed-loop TDD cycles:
  1. RED: Synthesize a reproduction pytest test and confirm it fails.
  2. GREEN: Surgically patch code to make the test pass.
  3. SELF-HEALING: If tests fail, feed back tracebacks until green.
  4. ZERO-REGRESSION GATE: Run full test suite to guarantee no preexisting code broke.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from core.llm import ask
from core.prompt_builder import build, SYSTEM_PROMPT
from core.ui import C, ok, warn, err, info
from tools import file_tools, code_tools, graph_tools
from agent.executor import (
    _extract_edit_blocks, _auto_edit_files,
    _extract_file_blocks, _auto_write_files
)
from agent.commands_base import _backup_file


TDD_SYSTEM_PROMPT = SYSTEM_PROMPT + """
You are acting as an Autonomous TDD (Test-Driven Development) Engineer.
Always follow the Red-Green-Refactor principles strictly:
1. In RED phase: Write ONLY a focused, self-contained pytest file asserting expected behavior.
2. In GREEN phase: Write the minimal surgical code changes (using SEARCH/REPLACE blocks) to make tests pass.
3. In SELF-HEALING phase: Analyze the exact pytest traceback and provide precise surgical fixes.
Never output markdown prose without the required FILE or SEARCH/REPLACE blocks.
"""


def run_tdd_cycle(
    task: str,
    workspace: str = ".",
    confirm_edits: bool = False,
    max_heal_attempts: int = 3,
    target_test_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a closed-loop TDD cycle for the given task.
    Returns:
      {
        "ok": bool,
        "status": "SUCCESS" | "FAILED" | "REGRESSION_DETECTED",
        "test_file": str,
        "heal_attempts": int,
        "message": str
      }
    """
    workspace_path = Path(workspace).resolve()
    print(f"\n{C.BOLD}{C.CYAN}🧪 Starting Autonomous TDD Cycle:{C.RESET} {task}")

    # ── Step 0: Gather Context & Compute Blast Radius ─────────────────────────
    ranked = file_tools.rank_codebase_files(str(workspace_path), query=task, max_files=8)
    code_ctx = file_tools.build_context_string(ranked, char_limit=1800) if ranked.get("ok") else ""
    repo_map = file_tools.get_repo_map(str(workspace_path))

    # Look for symbols mentioned in task to calculate blast radius
    words = re.findall(r'[a-zA-Z0-9_]{3,}', task)
    blast_info = ""
    for w in words:
        blast = graph_tools.compute_blast_radius(w, root=str(workspace_path))
        if blast.get("ok") and blast.get("caller_count", 0) > 0:
            blast_info += f"\n• Blast Radius for `{w}`: {blast['summary']}"
            if blast["affected_files"]:
                blast_info += f"\n  Affected files: {', '.join(blast['affected_files'][:4])}"

    if blast_info:
        print(f"   {C.YELLOW}⚠️  Blast Radius Analysis:{C.RESET}{blast_info}")

    # ── Step 1: RED Phase (Write Failing Reproduction Test) ───────────────────
    print(f"\n{C.RED}{C.BOLD}🔴 Phase 1: RED (Synthesizing reproduction test)...{C.RESET}")

    red_prompt = (
        f"We are in the RED phase of TDD for this task:\n{task}\n\n"
        f"Codebase Context:\n{code_ctx}\n\n"
        f"Repository Symbols:\n{repo_map}\n\n"
        f"Instructions:\n"
        f"Write a self-contained pytest test file in tests/test_<name>.py that reproduces or asserts this feature.\n"
        f"The test MUST assert the new behavior and fail until implementation is written.\n"
        f"Output format:\n"
        f"FILE: tests/test_<name>.py\n"
        f"```python\n"
        f"# test code here\n"
        f"```\n"
    )

    red_resp = ask(red_prompt, system=TDD_SYSTEM_PROMPT)
    test_blocks = _extract_file_blocks(red_resp)
    if not test_blocks:
        return {"ok": False, "status": "FAILED", "message": "Model failed to generate test block in RED phase"}

    written_tests = _auto_write_files(test_blocks, str(workspace_path), confirm=confirm_edits)
    if not written_tests:
        return {"ok": False, "status": "FAILED", "message": "Failed to write reproduction test to disk"}

    test_file = written_tests[0]
    test_rel = str(Path(test_file).relative_to(workspace_path)).replace("\\", "/")
    print(f"   📝 Test written: {test_rel}")

    # Run test to confirm it fails (RED)
    test_res = code_tools.run_pytest(test_rel, cwd=str(workspace_path))
    if test_res["ok"]:
        print(f"   {C.YELLOW}ℹ️  Test passed immediately — verifying existing or complete spec.{C.RESET}")
    else:
        print(f"   {C.SUCCESS}✅ RED confirmed: Test fails as expected before implementation.{C.RESET}")

    # ── Step 2: GREEN Phase (Surgical Implementation) ─────────────────────────
    print(f"\n{C.GREEN}{C.BOLD}🟢 Phase 2: GREEN (Implementing solution)...{C.RESET}")

    test_content = file_tools.read_file(test_file).get("content", "")
    failure_output = test_res.get("stdout") or test_res.get("stderr") or "Initial failure expected"

    green_prompt = (
        f"We are in the GREEN phase of TDD for this task:\n{task}\n\n"
        f"Failing Test ({test_rel}):\n```python\n{test_content}\n```\n\n"
        f"Test Failure Output:\n```\n{failure_output[-1200:]}\n```\n\n"
        f"Codebase Context:\n{code_ctx}\n\n"
        f"Write the minimal surgical patch to make this test pass.\n"
        f"Prefer SEARCH/REPLACE blocks for existing files:\n"
        f"FILE: path/to/file.py\n"
        f"<<<<<<< SEARCH\n"
        f"exact lines to replace\n"
        f"=======\n"
        f"replacement lines\n"
        f">>>>>>> REPLACE\n"
        f"Or FILE: path/to/new_file.py if creating a new module."
    )

    green_resp = ask(green_prompt, system=TDD_SYSTEM_PROMPT)

    # Backup & apply edits
    edit_blocks = _extract_edit_blocks(green_resp)
    if edit_blocks:
        for eb in edit_blocks:
            abs_p = str((workspace_path / eb["path"]).resolve())
            _backup_file(abs_p, str(workspace_path))
        _auto_edit_files(edit_blocks, str(workspace_path), confirm=confirm_edits)

    file_blocks = _extract_file_blocks(green_resp)
    if file_blocks:
        for fb in file_blocks:
            abs_p = str((workspace_path / fb["path"]).resolve())
            _backup_file(abs_p, str(workspace_path))
        _auto_write_files(file_blocks, str(workspace_path), confirm=confirm_edits)

    # ── Step 3: Verify & Self-Healing Reflection Loop ──────────────────────────
    heal_attempts = 0
    test_run = code_tools.run_pytest(test_rel, cwd=str(workspace_path))

    while not test_run["ok"] and heal_attempts < max_heal_attempts:
        heal_attempts += 1
        print(f"\n{C.YELLOW}🔄 Phase 3: SELF-HEALING (Attempt {heal_attempts}/{max_heal_attempts})...{C.RESET}")
        tb = test_run.get("stdout") or test_run.get("stderr")
        print(f"   {C.RED}❌ Test failure detected:{C.RESET}\n{tb[-400:]}\n")

        heal_prompt = (
            f"The test {test_rel} is still FAILING.\n\n"
            f"Traceback / Failure Output:\n```\n{tb[-1500:]}\n```\n\n"
            f"Analyze the exact error (e.g. AssertionError, NameError, wrong return value).\n"
            f"Provide the exact surgical SEARCH/REPLACE block to fix the code."
        )

        heal_resp = ask(heal_prompt, system=TDD_SYSTEM_PROMPT)
        heal_edits = _extract_edit_blocks(heal_resp)
        if heal_edits:
            _auto_edit_files(heal_edits, str(workspace_path), confirm=confirm_edits)
        heal_files = _extract_file_blocks(heal_resp)
        if heal_files:
            _auto_write_files(heal_files, str(workspace_path), confirm=confirm_edits)

        test_run = code_tools.run_pytest(test_rel, cwd=str(workspace_path))

    if not test_run["ok"]:
        return {
            "ok": False,
            "status": "FAILED",
            "test_file": test_rel,
            "heal_attempts": heal_attempts,
            "message": f"Test {test_rel} failed to pass after {heal_attempts} healing attempts."
        }

    print(f"\n   {C.SUCCESS}🎉 GREEN Reached: {test_rel} PASSED!{C.RESET}")

    # ── Step 4: ZERO-REGRESSION GATE ──────────────────────────────────────────
    print(f"\n{C.CYAN}🛡️  Phase 4: ZERO-REGRESSION GATE (Running entire test suite)...{C.RESET}")
    full_run = code_tools.run_pytest(cwd=str(workspace_path))

    if not full_run["ok"]:
        print(f"   {C.WARN}⚠️  Regression detected in full test suite:{C.RESET}")
        print(full_run.get("stdout", "")[-400:])
        return {
            "ok": False,
            "status": "REGRESSION_DETECTED",
            "test_file": test_rel,
            "heal_attempts": heal_attempts,
            "message": "Feature test passed but existing project tests failed (regression detected)."
        }

    print(f"   {C.SUCCESS}✅ Zero regressions verified across all project tests!{C.RESET}")
    return {
        "ok": True,
        "status": "SUCCESS",
        "test_file": test_rel,
        "heal_attempts": heal_attempts,
        "message": f"TDD cycle successfully implemented and verified with zero regressions ({test_rel})."
    }
