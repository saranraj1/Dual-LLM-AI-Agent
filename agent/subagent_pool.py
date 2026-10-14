"""
agent/subagent_pool.py — Forked Subagent Pool & Ephemeral Workers (Pillar 5).

Spawns specialized child subagents for exploratory search, test runs, and
code review. Keeps intermediate multi-file reading and lengthy compiler logs
isolated in worker contexts so the parent conversation remains lean.
"""

import os
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
from core.llm import ask


class WorkerRole(str, Enum):
    RESEARCHER = "researcher"
    TEST_RUNNER = "test_runner"
    REVIEWER = "reviewer"


class SubagentWorker:
    """Lightweight, isolated worker for specialized subtasks."""

    def __init__(self, role: WorkerRole, workspace: str = "."):
        self.role = role
        self.workspace = os.path.abspath(workspace)

    def execute(self, task: str) -> Dict[str, Any]:
        """Dispatch task to role-specific isolated pipeline."""
        if self.role == WorkerRole.RESEARCHER:
            return self._run_researcher(task)
        elif self.role == WorkerRole.TEST_RUNNER:
            return self._run_test_runner(task)
        elif self.role == WorkerRole.REVIEWER:
            return self._run_reviewer(task)
        else:
            return {"ok": False, "role": self.role.value, "error": f"Unknown role: {self.role}"}

    def _run_researcher(self, query: str) -> Dict[str, Any]:
        """
        Deep grep and file ranking worker.
        Gathers candidate files, extracts matching lines, and returns a concise summary.
        """
        from tools.file_tools import rank_codebase_files, read_file
        ranked_res = rank_codebase_files(self.workspace, query=query, max_files=5)
        raw_files = ranked_res.get("files", {}) if ranked_res.get("ok") else {}
        if isinstance(raw_files, dict):
            file_items = [(p, c) for p, c in raw_files.items()]
        elif isinstance(raw_files, list):
            file_items = [(f.get("path", ""), f.get("content", "")) for f in raw_files if isinstance(f, dict)]
        else:
            file_items = []

        findings = []
        q_terms = [t.lower() for t in query.split() if len(t) > 2]

        for rel_path, content in file_items:
            if not content:
                abs_p = (Path(self.workspace) / rel_path).resolve()
                rf = read_file(str(abs_p))
                content = rf.get("content", "") if rf.get("ok") else ""

            if content:
                lines = content.splitlines()
                matching_lines = []
                for i, l in enumerate(lines, 1):
                    if any(term in l.lower() for term in q_terms):
                        matching_lines.append(f"  L{i}: {l.strip()[:100]}")
                        if len(matching_lines) >= 3:
                            break
                if matching_lines:
                    findings.append(f"📄 `{rel_path}`:\n" + "\n".join(matching_lines))

        summary = "\n".join(findings) if findings else f"No direct code references found matching query: '{query}'"
        return {
            "ok": True,
            "role": WorkerRole.RESEARCHER.value,
            "query": query,
            "summary": summary[:1200],
            "files_inspected": len(file_items)
        }

    def _run_test_runner(self, test_args: str) -> Dict[str, Any]:
        """
        Runs test suite in background subprocess, filtering output to key failures.
        """
        cmd = [sys.executable, "-m", "pytest", "-q"]
        if test_args.strip():
            cmd.extend(test_args.strip().split())

        try:
            res = subprocess.run(
                cmd,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=45
            )
            out = res.stdout.strip()
            err = res.stderr.strip()
            passed = res.returncode == 0

            # Distill output
            lines = out.splitlines()
            failure_lines = [l for l in lines if "FAILED" in l or "ERROR" in l]
            summary_line = lines[-1] if lines else "No test output"

            distilled = f"Test Result: {'PASSED' if passed else 'FAILED'}\nSummary: {summary_line}"
            if failure_lines:
                distilled += "\nFailures:\n" + "\n".join(failure_lines[:5])

            return {
                "ok": passed,
                "role": WorkerRole.TEST_RUNNER.value,
                "summary": distilled,
                "exit_code": res.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "role": WorkerRole.TEST_RUNNER.value, "summary": "Test run timed out after 45s"}
        except Exception as e:
            return {"ok": False, "role": WorkerRole.TEST_RUNNER.value, "summary": f"Failed to execute tests: {e}"}

    def _run_reviewer(self, diff_or_path: str) -> Dict[str, Any]:
        """
        Reviews git diff or specific file against clean code and ponytail rules.
        """
        from tools.terminal_tools import run_command
        diff_text = ""
        if not diff_or_path.strip():
            r = run_command("git diff HEAD", cwd=self.workspace)
            diff_text = r.get("stdout", "").strip() or "No uncommitted git changes detected."
        else:
            diff_text = diff_or_path

        prompt = f"""You are an elite code reviewer applying 'ponytail' (minimal diffs, YAGNI, deletion over addition) and clean craftsmanship.
Review this diff or code snippet in 3-5 concise bullet points:
```
{diff_text[:2000]}
```"""
        try:
            review_resp = ask(prompt, system="You are a strict, concise code reviewer. Max 4 bullet points.")
            return {
                "ok": True,
                "role": WorkerRole.REVIEWER.value,
                "summary": review_resp.strip()
            }
        except Exception as e:
            return {"ok": False, "role": WorkerRole.REVIEWER.value, "summary": f"Review failed: {e}"}


def run_subagent(role: str, task: str, workspace: str = ".") -> Dict[str, Any]:
    """Public helper to run an ephemeral subagent."""
    try:
        r_enum = WorkerRole(role.lower().strip())
    except ValueError:
        return {
            "ok": False,
            "error": f"Invalid worker role '{role}'. Available: {[r.value for r in WorkerRole]}"
        }
    worker = SubagentWorker(r_enum, workspace=workspace)
    return worker.execute(task)


# ── /delegate CLI Command ─────────────────────────────────────────────────────

def cmd_delegate(agent, args: str) -> str:
    """Delegate work to an isolated subagent worker without polluting chat context."""
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "Usage: /delegate <researcher|test_runner|reviewer> <task_or_query>"

    role_str, task = parts[0], parts[1]
    res = run_subagent(role_str, task, workspace=agent.workspace)
    if not res.get("ok", False) and "error" in res:
        return f"❌ Subagent error: {res['error']}"

    header = f"🤖 [Subagent: {res.get('role', role_str).upper()}] Result:"
    return f"{header}\n{res.get('summary', '')}"
