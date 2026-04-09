"""
agent/executor.py — Fully autonomous executor.
Every LLM response is parsed for:
  - code blocks  → written to disk automatically
  - pip/npm      → installed automatically
  - shell cmds   → run automatically
  - file paths   → read automatically
No manual approval needed.
"""

import re
import os
from pathlib import Path
from typing import Dict, Optional, List
from core.llm import ask
from core.prompt_builder import build, SYSTEM_PROMPT
from tools import file_tools, code_tools, terminal_tools


# ── Autonomous write prompt ───────────────────────────────────────────────────
# Tell the LLM to always output files in a parseable format
AUTO_WRITE_INSTRUCTION = """
When creating or editing files, ALWAYS use this exact format:
FILE: path/to/filename.ext
```
file contents here
```
You can output multiple files this way. Always use real file paths.
"""

AUTONOMOUS_SYSTEM = SYSTEM_PROMPT + "\n" + AUTO_WRITE_INSTRUCTION


# ── Parsers ───────────────────────────────────────────────────────────────────

def _extract_file_blocks(text: str) -> List[Dict]:
    """
    Find all FILE: path\\n``` ... ``` blocks in LLM output.
    Returns list of {path, content}.
    """
    pattern = r'FILE:\s*([^\n]+)\n```[a-z]*\n(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    return [{"path": m[0].strip(), "content": m[1]} for m in matches]


def _extract_code_blocks(text: str) -> List[str]:
    """Extract all ``` code blocks regardless of language."""
    return re.findall(r'```(?:\w+)?\n(.*?)```', text, re.DOTALL)


def _extract_pip_packages(text: str) -> List[str]:
    """Find pip install commands anywhere in text."""
    return re.findall(r'pip install\s+([\w\-\[\],>=<.]+)', text)


def _extract_npm_packages(text: str) -> List[str]:
    return re.findall(r'npm install\s+([\w\-@/.]+)', text)


def _extract_shell_commands(text: str) -> List[str]:
    """Extract shell commands from backtick or $ prefixed lines."""
    cmds = []
    # Lines starting with $ (common in docs)
    dollar = re.findall(r'^\$\s+(.+)$', text, re.MULTILINE)
    cmds.extend(dollar)
    # Single backtick commands
    backtick = re.findall(r'`([^`\n]{5,80})`', text)
    # Filter to things that look like shell commands
    shell_starts = ('python', 'pip', 'npm', 'node', 'git', 'mkdir',
                    'cd ', 'ls', 'dir', 'echo', 'touch', 'cp ', 'mv ')
    for b in backtick:
        if any(b.strip().lower().startswith(s) for s in shell_starts):
            cmds.append(b.strip())
    return cmds


def _detect_missing_module(stderr: str) -> Optional[str]:
    """If Python fails with ModuleNotFoundError, return the module name."""
    match = re.search(r"No module named '([^']+)'", stderr)
    return match.group(1) if match else None


# ── Auto-actions ──────────────────────────────────────────────────────────────

def _auto_write_files(file_blocks: List[Dict], cwd: str) -> List[str]:
    """Write all detected file blocks to disk. Returns list of written paths."""
    written = []
    for fb in file_blocks:
        path = fb["path"]
        # Make relative paths absolute to cwd
        if not os.path.isabs(path):
            path = os.path.join(cwd, path)
        r = file_tools.write_file(path, fb["content"])
        if r["ok"]:
            print(f"   📝 Written: {r['path']}")
            written.append(r["path"])
        else:
            print(f"   ⚠️  Write failed: {r['error']}")
    return written


def _auto_install(packages: List[str], pkg_type: str = "pip") -> List[str]:
    """Auto-install missing packages. Returns install results."""
    results = []
    for pkg in packages:
        pkg = pkg.strip().split()[0]  # take first word only
        if not pkg:
            continue
        print(f"   📦 Auto-installing {pkg_type}: {pkg}")
        if pkg_type == "pip":
            r = code_tools.install_package(pkg)
        else:
            r = terminal_tools.run_command(f"npm install {pkg}")
        status = "✅" if r["ok"] else "❌"
        print(f"   {status} {pkg}: {'done' if r['ok'] else r.get('stderr','failed')[:80]}")
        results.append(f"{pkg}: {'ok' if r['ok'] else 'failed'}")
    return results


def _auto_run_code(code: str, cwd: str, retry: bool = True) -> Dict:
    """
    Run Python code. If it fails with ModuleNotFoundError,
    auto-install the missing package and retry once.
    """
    lint = code_tools.lint_python(code)
    if not lint["ok"]:
        return {"ok": False, "output": f"Syntax error: {lint['error']}"}

    r = code_tools.run_python(code, cwd=cwd)
    output = r["stdout"] or r["stderr"]

    # Auto-fix missing module
    if not r["ok"] and retry:
        missing = _detect_missing_module(r.get("stderr", ""))
        if missing:
            print(f"   📦 Missing module detected: {missing} — installing...")
            _auto_install([missing], "pip")
            r2 = code_tools.run_python(code, cwd=cwd)
            output = r2["stdout"] or r2["stderr"]
            return {"ok": r2["ok"], "output": output}

    return {"ok": r["ok"], "output": output}


# ── Main executor ──────────────────────────────────────────────────────────────

def execute_step(
    step: str,
    task: str,
    memory_context: str  = "",
    code_context: str    = "",
    cwd: str             = ".",
    previous_result: str = ""
) -> Dict:
    """
    Fully autonomous step execution:
    1. Ask LLM with enriched prompt
    2. Parse response for file blocks → write them
    3. Parse for pip/npm → install them
    4. Parse for code → run it
    5. Return everything that happened
    """

    # Always inject codebase scan into every step
    if not code_context:
        scan = file_tools.scan_codebase(cwd)
        if scan["ok"]:
            code_context = file_tools.build_context_string(scan, char_limit=1800)

    prompt = build(
        task           = step,
        memory_context = memory_context,
        code_context   = code_context,
        tool_results   = previous_result[-600:] if previous_result else ""
    )

    # Get LLM response
    response = ask(prompt, system=AUTONOMOUS_SYSTEM)

    if response.startswith("[LLM ERROR]"):
        return _wrap(step, "llm", response, ok=False, error=response)

    actions_log = []
    all_ok      = True

    # ── 1. Auto-write any FILE: blocks ────────────────────────────────────────
    file_blocks = _extract_file_blocks(response)
    if file_blocks:
        written = _auto_write_files(file_blocks, cwd)
        if written:
            actions_log.append(f"Files written: {', '.join(written)}")
        # Refresh code context after writing
        scan = file_tools.scan_codebase(cwd)
        if scan["ok"]:
            code_context = file_tools.build_context_string(scan, char_limit=1800)

    # ── 2. Auto-install pip packages ──────────────────────────────────────────
    pip_pkgs = _extract_pip_packages(response)
    if pip_pkgs:
        results = _auto_install(pip_pkgs, "pip")
        actions_log.extend(results)

    # ── 3. Auto-install npm packages ──────────────────────────────────────────
    npm_pkgs = _extract_npm_packages(response)
    if npm_pkgs:
        results = _auto_install(npm_pkgs, "npm")
        actions_log.extend(results)

    # ── 4. Auto-run Python code blocks ────────────────────────────────────────
    code_blocks = _extract_code_blocks(response)
    run_output  = ""
    for code in code_blocks:
        # Only run if it looks executable (has function calls, not just definitions)
        if any(kw in code for kw in ['print(', 'if __name__', 'run(', 'main(', 'test(']):
            print(f"   ▶ Auto-running code block...")
            result = _auto_run_code(code, cwd)
            run_output = result["output"]
            status = "✅" if result["ok"] else "❌"
            print(f"   {status} Output: {run_output[:150]}")
            if not result["ok"]:
                all_ok = False
            actions_log.append(f"Code run: {'ok' if result['ok'] else 'failed'} — {run_output[:100]}")
            break  # run only first executable block per step

    # ── 5. Auto-run shell commands (git, mkdir, etc.) ─────────────────────────
    shell_cmds = _extract_shell_commands(response)
    SAFE_AUTO_RUN = ('mkdir', 'git init', 'git add', 'git status',
                     'npm init', 'python -m', 'pip list')
    for cmd in shell_cmds[:3]:  # cap at 3 auto-commands per step
        if any(cmd.strip().lower().startswith(s) for s in SAFE_AUTO_RUN):
            print(f"   🖥️  Auto-running: {cmd}")
            r = terminal_tools.run_command(cmd, cwd=cwd)
            out = (r["stdout"] or r["stderr"])[:100]
            print(f"   {'✅' if r['ok'] else '❌'} {out}")
            actions_log.append(f"Shell `{cmd}`: {'ok' if r['ok'] else out}")

    # ── Build final result ────────────────────────────────────────────────────
    final = response
    if actions_log:
        final += "\n\n[Auto-actions taken]\n" + "\n".join(f"• {a}" for a in actions_log)
    if run_output:
        final += f"\n\n[Code output]\n{run_output}"

    return _wrap(step, "autonomous", final, ok=all_ok, code_context=code_context)


def _wrap(step, tool, result, ok=True, error=None, code_context=None) -> Dict:
    return {
        "step":         step,
        "tool_used":    tool,
        "result":       result,
        "ok":           ok,
        "error":        error,
        "code_context": code_context
    }