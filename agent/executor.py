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
import sys
import difflib
from pathlib import Path
from typing import Dict, Optional, List
from core.llm import ask
from core.prompt_builder import build, SYSTEM_PROMPT
from core.ui import format_colored_diff, C
from tools import file_tools, code_tools, terminal_tools


# ── Autonomous write prompt ───────────────────────────────────────────────────
# Tell the LLM to output files in a parseable format
AUTO_WRITE_INSTRUCTION = """
When creating or editing code, choose the appropriate format:

1. For SURGICAL EDITS to existing files (preferred for modifying existing code):
FILE: path/to/filename.ext
<<<<<<< SEARCH
exact lines to be replaced
=======
new replacement lines
>>>>>>> REPLACE

2. For NEW FILES or complete file rewrites:
FILE: path/to/filename.ext
```
file contents here
```

3. To ASK the user an interactive question when design decisions or requirements need input:
ASK_USER: What database engine should we configure?
OPTION: SQLite (local file, zero setup)
OPTION: PostgreSQL (production grade)
DEFAULT: 1

Always use relative paths within the workspace. Never use placeholder code like '...rest of code...'.
"""

AUTONOMOUS_SYSTEM = SYSTEM_PROMPT + "\n" + AUTO_WRITE_INSTRUCTION


# ── Parsers ───────────────────────────────────────────────────────────────────

def _extract_edit_blocks(text: str) -> List[Dict]:
    """
    Find all surgical SEARCH/REPLACE blocks in LLM output.
    Returns list of {"path": path, "target": target, "replacement": replacement}.
    """
    blocks = []
    lines = text.splitlines(keepends=True)
    current_file = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        file_match = re.match(r'^\s*FILE:\s*[`"]?([^`"\r\n]+)[`"]?', line)
        if file_match:
            current_file = file_match.group(1).strip()
            i += 1
            continue

        stripped = line.strip()
        if re.match(r'^<{5,9}\s*SEARCH', stripped):
            i += 1
            search_lines = []
            while i < n and not re.match(r'^={5,9}$', lines[i].strip()):
                search_lines.append(lines[i])
                i += 1

            if i < n and re.match(r'^={5,9}$', lines[i].strip()):
                i += 1
                replace_lines = []
                while i < n and not re.match(r'^>{5,9}\s*REPLACE', lines[i].strip()):
                    replace_lines.append(lines[i])
                    i += 1

                if i < n and re.match(r'^>{5,9}\s*REPLACE', lines[i].strip()):
                    if current_file:
                        blocks.append({
                            "path": current_file,
                            "target": "".join(search_lines),
                            "replacement": "".join(replace_lines)
                        })
            i += 1
            continue

        i += 1

    return blocks


def _extract_file_blocks(text: str) -> List[Dict]:
    """
    Find all FILE: path\n``` ... ``` blocks in LLM output.
    Returns list of {path, content}.
    Accurately handles nested code blocks (e.g. ```mermaid or ```text) within markdown files.
    """
    blocks = []
    lines = text.splitlines(keepends=True)
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        file_match = re.match(r'^\s*FILE:\s*[`"]?([^`"\r\n]+)[`"]?', line)
        if file_match:
            file_path = file_match.group(1).strip()
            i += 1
            while i < n and not lines[i].strip():
                i += 1
            if i >= n:
                break
            fence_m = re.match(r'^(`{3,})', lines[i].strip())
            if fence_m:
                fence = fence_m.group(1)
                i += 1
                content_lines = []
                nested_fences = 0
                while i < n:
                    curr_line = lines[i]
                    stripped = curr_line.strip()
                    if re.match(r'^\s*FILE:\s*[`"]?[^`"\r\n]+[`"]?', curr_line):
                        break
                    if stripped.startswith("```") and len(stripped) > 3 and not stripped.startswith(fence + "`"):
                        nested_fences += 1
                        content_lines.append(curr_line)
                    elif stripped == "```" or (stripped.startswith(fence) and len(stripped) == len(fence)):
                        if nested_fences > 0:
                            nested_fences -= 1
                            content_lines.append(curr_line)
                        else:
                            i += 1
                            break
                    else:
                        content_lines.append(curr_line)
                    i += 1

                blocks.append({"path": file_path, "content": "".join(content_lines)})
                continue
        i += 1

    if not blocks:
        pattern = r'FILE:\s*([^\n]+)\n```[a-z]*\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)
        blocks = [{"path": m[0].strip(), "content": m[1]} for m in matches]

    return blocks


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

def _prompt_confirmation(action_desc: str) -> str:
    """Prompt user for confirmation [y/n/a/q]. Defaults to 'y' in non-interactive environments."""
    if not sys.stdin.isatty():
        return "y"
    try:
        ans = input(f"{C.BOLD}{C.YELLOW}❓ {action_desc} [y/n/a/q]? (yes, no, all, quit): {C.RESET}").strip().lower()
        return ans or "y"
    except (EOFError, KeyboardInterrupt):
        return "q"


def _check_blast_radius_advisory(target_code: str, file_rel_path: str, cwd: str):
    """Analyze and display AST blast radius advisory before modifying code."""
    if not file_rel_path.endswith(".py"):
        return
    try:
        from tools.graph_tools import compute_blast_radius
        symbols = re.findall(r'^\s*(?:def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)', target_code, re.MULTILINE)
        if not symbols:
            return
        for sym in symbols[:3]:
            blast = compute_blast_radius(sym, target_file=file_rel_path, root_dir=cwd)
            if blast.get("caller_count", 0) > 0:
                callers = [c["file"] for c in blast["callers"][:3]]
                extra = f" (+{blast['caller_count'] - len(callers)} more)" if blast["caller_count"] > len(callers) else ""
                print(f"   ⚠️  Blast Radius [{blast['severity']}]: '{sym}' has {blast['caller_count']} caller(s) in {', '.join(callers)}{extra}")
                if blast.get("affected_tests"):
                    print(f"   🧪  Impacted test suites: {', '.join(blast['affected_tests'][:3])}")
    except Exception:
        pass


def _auto_edit_files(edit_blocks: List[Dict], cwd: str, confirm: bool = False) -> List[str]:
    """Apply surgical search/replace edit blocks to files safely."""
    edited = []
    cwd_path = Path(cwd).resolve()
    accept_all = not confirm

    if edit_blocks:
        try:
            from tools.checkpoint_tools import create_checkpoint
            create_checkpoint(description=f"Auto-checkpoint before editing {len(edit_blocks)} block(s)", root_dir=cwd)
        except Exception:
            pass

    for eb in edit_blocks:
        path = eb["path"].strip().replace("\\", "/")
        if ":" in path:
            path = path.split(":", 1)[1]
        path = path.lstrip("/")

        target_path = (cwd_path / path).resolve()
        if not target_path.is_relative_to(cwd_path):
            print(f"   ⚠️  Blocked unsafe path escaping workspace: {eb['path']}")
            continue

        if not target_path.exists():
            print(f"   ⚠️  Cannot edit nonexistent file: {eb['path']}")
            continue

        orig_content = target_path.read_text(encoding="utf-8", errors="ignore")
        c_norm = orig_content.replace("\r\n", "\n")
        t_norm = eb["target"].replace("\r\n", "\n")
        r_norm = eb["replacement"].replace("\r\n", "\n")

        if t_norm not in c_norm:
            print(f"   ⚠️  Target content not found in {eb['path']}")
            continue

        _check_blast_radius_advisory(eb["target"], path, str(cwd_path))

        if not accept_all:
            simulated = c_norm.replace(t_norm, r_norm, 1)
            diff_lines = list(difflib.unified_diff(
                c_norm.splitlines(keepends=True),
                simulated.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3
            ))
            diff_text = "".join(diff_lines)
            if diff_text:
                print(f"\n{C.CYAN}--- Proposed edit for {path} ---{C.RESET}")
                print(format_colored_diff(diff_text))
                print(f"{C.CYAN}----------------------------------{C.RESET}")

            decision = _prompt_confirmation(f"Apply edit to {path}")
            if decision in ("q", "quit"):
                print("   🚫 Edit cancelled by user.")
                break
            elif decision in ("n", "no"):
                print(f"   ⏭️  Skipped edit for {path}.")
                continue
            elif decision in ("a", "all"):
                accept_all = True

        r = file_tools.replace_in_file(str(target_path), eb["target"], eb["replacement"])
        if r["ok"]:
            print(f"   ✏️  Surgically edited: {r['path']}")
            edited.append(r["path"])
            try:
                from tools.preflight_tools import preflight_check_file
                p_res = preflight_check_file(str(target_path))
                if not p_res.get("valid", True):
                    repaired = p_res.get("auto_repaired_content")
                    if repaired:
                        target_path.write_text(repaired, encoding="utf-8")
                        print(f"   🛠️  Pre-flight: auto-repaired syntax in {path}")
                    else:
                        print(f"   ⚠️  Pre-flight diagnostic: {p_res.get('error', 'Syntax error')}")
            except Exception:
                pass
        else:
            print(f"   ⚠️  Edit failed: {r['error']}")
    return edited


def _auto_write_files(file_blocks: List[Dict], cwd: str, confirm: bool = False) -> List[str]:
    """Write all detected file blocks to disk safely. Returns list of written paths."""
    written = []
    cwd_path = Path(cwd).resolve()
    accept_all = not confirm

    if file_blocks:
        try:
            from tools.checkpoint_tools import create_checkpoint
            create_checkpoint(description=f"Auto-checkpoint before writing {len(file_blocks)} file(s)", root_dir=cwd)
        except Exception:
            pass

    for fb in file_blocks:
        path = fb["path"].strip().replace("\\", "/")
        if ":" in path:
            path = path.split(":", 1)[1]
        path = path.lstrip("/")

        target_path = (cwd_path / path).resolve()
        if not target_path.is_relative_to(cwd_path):
            print(f"   ⚠️  Blocked unsafe path escaping workspace: {fb['path']}")
            continue

        if target_path.exists():
            _check_blast_radius_advisory(fb["content"], path, str(cwd_path))

        if not accept_all:
            action_name = "Overwrite" if target_path.exists() else "Create"
            decision = _prompt_confirmation(f"{action_name} file {path} ({len(fb['content'])} chars)")
            if decision in ("q", "quit"):
                print("   🚫 File write cancelled by user.")
                break
            elif decision in ("n", "no"):
                print(f"   ⏭️  Skipped write for {path}.")
                continue
            elif decision in ("a", "all"):
                accept_all = True

        r = file_tools.write_file(str(target_path), fb["content"])
        if r["ok"]:
            print(f"   📝 Written: {r['path']}")
            written.append(r["path"])
            try:
                from tools.preflight_tools import preflight_check_file
                p_res = preflight_check_file(str(target_path))
                if not p_res.get("valid", True):
                    repaired = p_res.get("auto_repaired_content")
                    if repaired:
                        target_path.write_text(repaired, encoding="utf-8")
                        print(f"   🛠️  Pre-flight: auto-repaired syntax in {path}")
                    else:
                        print(f"   ⚠️  Pre-flight diagnostic: {p_res.get('error', 'Syntax error')}")
            except Exception:
                pass
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
    repo_map: str        = "",
    cwd: str             = ".",
    previous_result: str = "",
    confirm_edits: bool  = False
) -> Dict:
    """
    Fully autonomous step execution:
    1. Ask LLM with enriched prompt (including repo map and ranked code context)
    2. Parse response for surgical edit blocks → apply them (with optional diff confirmation)
    3. Parse response for file blocks → write them (with optional confirmation)
    4. Parse for pip/npm → install them
    5. Parse for code → run it (if step requests execution or standalone runnable)
    6. Return everything that happened
    """

    # Always inject codebase scan and repo map into every step if not provided
    if not code_context:
        query = f"{step} {task}".strip()
        ranked = file_tools.rank_codebase_files(cwd, query=query, max_files=15)
        if ranked.get("ok") and ranked.get("files"):
            code_context = file_tools.build_context_string(ranked, char_limit=1800)
        else:
            scan = file_tools.scan_codebase(cwd)
            if scan.get("ok"):
                code_context = file_tools.build_context_string(scan, char_limit=1800)

    if not repo_map:
        repo_map = file_tools.get_repo_map(cwd)

    prompt = build(
        task           = step,
        memory_context = memory_context,
        code_context   = code_context,
        repo_map       = repo_map,
        tool_results   = previous_result[-600:] if previous_result else ""
    )

    # Get LLM response
    response = ask(prompt, system=AUTONOMOUS_SYSTEM)

    if response.startswith("[LLM ERROR]"):
        return _wrap(step, "llm", response, ok=False, error=response)

    actions_log = []
    all_ok      = True

    # ── 0. Interactive QA / User Decisions ───────────────────────────────────
    from agent.interactive_qa import extract_ask_user_blocks, ask_user
    qa_blocks = extract_ask_user_blocks(response)
    if qa_blocks:
        for qb in qa_blocks:
            user_choice = ask_user(qb["question"], options=qb["options"], default=qb.get("default"))
            actions_log.append(f"User Decision: '{qb['question']}' -> '{user_choice}'")

    # ── 1. Surgical SEARCH/REPLACE edits ──────────────────────────────────────
    edit_blocks = _extract_edit_blocks(response)
    if edit_blocks:
        edited = _auto_edit_files(edit_blocks, cwd, confirm=confirm_edits)
        if edited:
            actions_log.append(f"Files edited: {', '.join(edited)}")

    # ── 2. Auto-write any new or full FILE: blocks ────────────────────────────
    file_blocks = _extract_file_blocks(response)
    if file_blocks:
        written = _auto_write_files(file_blocks, cwd, confirm=confirm_edits)
        if written:
            actions_log.append(f"Files written: {', '.join(written)}")

    # Refresh code context and repo map if files were modified
    if edit_blocks or file_blocks:
        query = f"{step} {task}".strip()
        ranked = file_tools.rank_codebase_files(cwd, query=query, max_files=15)
        if ranked.get("ok") and ranked.get("files"):
            code_context = file_tools.build_context_string(ranked, char_limit=1800)
        else:
            scan = file_tools.scan_codebase(cwd)
            if scan.get("ok"):
                code_context = file_tools.build_context_string(scan, char_limit=1800)
        repo_map = file_tools.get_repo_map(cwd)

    # ── 3. Auto-install pip packages ──────────────────────────────────────────
    pip_pkgs = _extract_pip_packages(response)
    if pip_pkgs:
        results = _auto_install(pip_pkgs, "pip")
        actions_log.extend(results)

    # ── 4. Auto-install npm packages ──────────────────────────────────────────
    npm_pkgs = _extract_npm_packages(response)
    if npm_pkgs:
        results = _auto_install(npm_pkgs, "npm")
        actions_log.extend(results)

    # ── 5. Auto-run Python code blocks (Gated for safety) ─────────────────────
    step_lower = step.lower()
    is_execution_step = any(kw in step_lower for kw in ['run', 'test', 'verify', 'execut', 'benchmark', 'check', 'assert'])

    code_blocks = _extract_code_blocks(response)
    run_output  = ""
    # Only execute code blocks if explicitly requested by step, or if no files were touched and code is runnable
    if is_execution_step or not (file_blocks or edit_blocks):
        for code in code_blocks:
            # Only run if it looks executable (has function calls, not just definitions)
            if any(kw in code for kw in ['print(', 'if __name__', 'run(', 'main(', 'test(']):
                if (file_blocks or edit_blocks) and not is_execution_step:
                    continue
                print(f"   ▶ Auto-running code block...")
                result = _auto_run_code(code, cwd)
                run_output = result["output"]
                status = "✅" if result["ok"] else "❌"
                print(f"   {status} Output: {run_output[:150]}")
                if not result["ok"]:
                    all_ok = False
                actions_log.append(f"Code run: {'ok' if result['ok'] else 'failed'} — {run_output[:100]}")
                break  # run only first executable block per step

    # ── 6. Auto-run shell commands (git, mkdir, etc.) ─────────────────────────
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