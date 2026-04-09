"""
agent/commands.py — Core agent commands.
/diff, /history, /undo, /explain, /test, /fix, /todo
Each function takes the agent instance + optional args, returns a result string.
"""

import os
import re
import shutil
from pathlib import Path
from typing import Optional
from core.llm import ask, ask_stream
from core.prompt_builder import SYSTEM_PROMPT
from tools.file_tools import read_file, write_file, search_in_files
from tools.terminal_tools import run_command
from tools.code_tools import lint_python


# ── Backup helper (used by all commands that write files) ─────────────────────

def _backup_file(filepath: str, workspace: str = None):
    """Save a backup of a file before the agent edits it."""
    backup_dir = Path.home() / ".ai_agent" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    src = Path(filepath)
    if not src.exists():
        return
    if workspace:
        try:
            rel  = os.path.relpath(filepath, workspace)
            name = rel.replace("/", "_").replace("\\", "_")
        except ValueError:
            name = src.name
    else:
        name = src.name
    dest = backup_dir / name
    try:
        shutil.copy2(str(src), str(dest))
    except Exception:
        pass


# ── /diff <file> ──────────────────────────────────────────────────────────────

def cmd_diff(agent, args: str) -> str:
    """
    Show git diff for a file, or compare agent's backup vs current if no git.
    Usage: /diff           → git diff entire workspace
           /diff main.py   → git diff a specific file
    """
    target = args.strip() if args.strip() else ""
    cwd    = agent.workspace

    # Try git diff first
    if target:
        path = os.path.join(cwd, target) if not os.path.isabs(target) else target
        r = run_command(f"git diff {path}", cwd=cwd)
    else:
        r = run_command("git diff", cwd=cwd)

    if r["ok"] and r["stdout"]:
        return r["stdout"]

    if not r["stdout"] and r["ok"]:
        return "✅ No changes since last git commit."

    # Fallback: check agent backup store
    backup_dir = Path.home() / ".ai_agent" / "backups"
    if not target:
        return "⚠️  No git repo found. Use /diff <filename> to compare against agent backup."

    try:
        rel  = os.path.relpath(os.path.join(cwd, target), cwd)
        name = rel.replace("/", "_").replace("\\", "_")
    except ValueError:
        name = Path(target).name

    backup_path  = backup_dir / name
    current_path = os.path.join(cwd, target)

    if not backup_path.exists():
        return f"⚠️  No backup found for {target}. Git is not available either."

    old   = backup_path.read_text(encoding="utf-8", errors="ignore")
    new_r = read_file(current_path)
    if not new_r["ok"]:
        return f"❌ Cannot read {current_path}: {new_r['error']}"
    new = new_r["content"]

    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff_lines = []
    for i, (o, n) in enumerate(zip(old_lines, new_lines)):
        if o != n:
            diff_lines.append(f"  Line {i+1}:")
            diff_lines.append(f"  - {o}")
            diff_lines.append(f"  + {n}")
    for line in new_lines[len(old_lines):]:
        diff_lines.append(f"  + {line}  (new)")
    for line in old_lines[len(new_lines):]:
        diff_lines.append(f"  - {line}  (removed)")

    if not diff_lines:
        return f"✅ {target} is unchanged from backup."
    return f"📝 Diff for {target}:\n" + "\n".join(diff_lines[:80])


# ── /history ──────────────────────────────────────────────────────────────────

def cmd_history(agent, args: str) -> str:
    """
    Show past tasks and conversations from long-term memory.
    Usage: /history        → show last 10 interactions
           /history 20     → show last 20
    """
    try:
        n = int(args.strip()) if args.strip().isdigit() else 10
    except Exception:
        n = 10

    turns = agent.long_mem.data.get("turns", [])
    if not turns:
        return "📭 No history yet. Start chatting!"

    recent = turns[-n * 2:]
    lines  = []
    for t in recent:
        role    = "You" if t["role"] == "user" else "Agent"
        ts      = t.get("ts", "")[:16].replace("T", " ")
        content = t["content"][:120].replace("\n", " ")
        lines.append(f"[{ts}] {role}: {content}")

    return f"📜 Last {len(lines)} messages:\n\n" + "\n".join(lines)


# ── /undo <file> ──────────────────────────────────────────────────────────────

def cmd_undo(agent, args: str) -> str:
    """
    Restore a file to its backup (saved before the agent last edited it).
    Usage: /undo main.py
    """
    target = args.strip()
    if not target:
        return "Usage: /undo <filename>"

    try:
        rel  = os.path.relpath(os.path.join(agent.workspace, target), agent.workspace)
        name = rel.replace("/", "_").replace("\\", "_")
    except ValueError:
        name = Path(target).name

    backup_dir  = Path.home() / ".ai_agent" / "backups"
    backup_path = backup_dir / name

    if not backup_path.exists():
        r = run_command(f"git checkout -- {target}", cwd=agent.workspace)
        if r["ok"]:
            return f"✅ Restored {target} via git checkout."
        return f"❌ No backup found for {target}. Try: git checkout -- {target}"

    dest = os.path.join(agent.workspace, target)
    shutil.copy2(str(backup_path), dest)
    agent._refresh_scan()
    return f"✅ Restored {target} from backup ({backup_path})"


# ── /explain <file> ───────────────────────────────────────────────────────────

def cmd_explain(agent, args: str) -> str:
    """
    Deep explanation of a specific file — what it does, how it works, gotchas.
    Usage: /explain main.py
    """
    target = args.strip()
    if not target:
        return "Usage: /explain <filename>"

    path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
    r    = read_file(path)
    if not r["ok"]:
        return f"❌ Cannot read {target}: {r['error']}"

    content = r["content"]
    prompt  = f"""Explain this file in detail. Cover:
1. What it does (purpose)
2. How it works (key logic, flow)
3. Important functions/classes and what they do
4. Any dependencies or assumptions
5. Potential issues or gotchas

File: {target}
```
{content[:2500]}
```"""

    print(f"\nAgent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /test ─────────────────────────────────────────────────────────────────────

def cmd_test(agent, args: str) -> str:
    """
    Auto-generate tests for a file, write them, and run them.
    Usage: /test              → test entire project
           /test main.py      → generate + run tests for a specific file
    """
    target = args.strip()

    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r    = read_file(path)
        if not r["ok"]:
            return f"❌ Cannot read {target}: {r['error']}"
        code    = r["content"][:2000]
        context = f"File: {target}\n```python\n{code}\n```"
        stem    = Path(target).stem
    else:
        context = agent.code_context[:2000]
        stem    = "project"

    prompt = f"""Write complete pytest unit tests for this code.
Use FILE: test_{stem}.py format so tests are saved automatically.
Cover: happy paths, edge cases, error handling.
Make tests runnable with: pytest

{context}"""

    print(f"\n🧪 Generating tests...")
    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    blocks = _extract_file_blocks(response)
    if blocks:
        written = _auto_write_files(blocks, agent.workspace)
        print(f"   📝 Written: {written}")

        print(f"   ▶ Running tests...")
        r = run_command("python -m pytest -v --tb=short 2>&1", cwd=agent.workspace)
        output = r["stdout"] or r["stderr"]
        print(output[:800])
        return f"Tests written and run.\n\n{output[:800]}"

    print(response)
    return response


# ── /fix ──────────────────────────────────────────────────────────────────────

def cmd_fix(agent, args: str) -> str:
    """
    Scan the codebase for errors, syntax issues, and broken imports — fix them.
    Usage: /fix              → scan and fix entire project
           /fix main.py      → fix a specific file
    """
    target = args.strip()

    if target:
        files_to_check = [os.path.join(agent.workspace, target)]
    else:
        from config.settings import SKIP_DIRS
        files_to_check = []
        for fp in Path(agent.workspace).rglob("*.py"):
            if not any(s in fp.parts for s in SKIP_DIRS):
                files_to_check.append(str(fp))

    print(f"🔍 Checking {len(files_to_check)} file(s)...")
    issues = []

    for fpath in files_to_check[:15]:
        r = read_file(fpath)
        if not r["ok"]:
            continue
        content = r["content"]
        rel     = os.path.relpath(fpath, agent.workspace)
        lint    = lint_python(content)
        if not lint["ok"]:
            issues.append({"file": rel, "issue": lint["error"], "content": content})
            print(f"   ❌ {rel}: {lint['error']}")
        else:
            print(f"   ✅ {rel}: OK")

    if not issues:
        return "✅ No syntax errors found in the project."

    fixed = []
    for issue in issues:
        print(f"\n🔧 Fixing {issue['file']}...")
        prompt = f"""Fix this Python file. It has this error: {issue['issue']}
Return the COMPLETE fixed file using FILE: {issue['file']} format.

Current code:
```python
{issue['content'][:2000]}
```"""
        response = ask(prompt, system=SYSTEM_PROMPT)

        from agent.executor import _extract_file_blocks, _auto_write_files
        blocks = _extract_file_blocks(response)
        if blocks:
            _backup_file(os.path.join(agent.workspace, issue["file"]), agent.workspace)
            written = _auto_write_files(blocks, agent.workspace)
            fixed.extend(written)
            print(f"   ✅ Fixed and saved: {written}")
        else:
            print(f"   ⚠️  Could not auto-fix {issue['file']}")

    agent._refresh_scan()
    if fixed:
        return f"✅ Fixed {len(fixed)} file(s): {', '.join(fixed)}"
    return f"⚠️  Found {len(issues)} issue(s) but could not auto-fix all of them."


# ── /todo ─────────────────────────────────────────────────────────────────────

def cmd_todo(agent, args: str) -> str:
    """
    Scan codebase for TODO/FIXME/HACK/BUG comments and action them.
    Usage: /todo             → list all TODOs
           /todo fix         → find TODOs and let agent fix them
    """
    action    = args.strip().lower()
    patterns  = ["TODO", "FIXME", "HACK", "BUG", "XXX"]
    all_hits  = []

    for pat in patterns:
        r = search_in_files(agent.workspace, pat)
        if r["ok"]:
            all_hits.extend(r["matches"])

    if not all_hits:
        return "✅ No TODO/FIXME/HACK/BUG comments found. Clean codebase!"

    seen  = set()
    dedup = []
    for h in all_hits:
        key = f"{h['file']}:{h['line_no']}"
        if key not in seen:
            seen.add(key)
            dedup.append(h)

    lines   = [f"  {h['file']}:{h['line_no']}  →  {h['content']}" for h in dedup[:30]]
    summary = f"📋 Found {len(dedup)} TODO/FIXME items:\n\n" + "\n".join(lines)

    if action != "fix":
        summary += "\n\nRun /todo fix to let the agent address these automatically."
        return summary

    print(f"\n🔧 Agent will now address {len(dedup)} TODO items...")
    by_file = {}
    for h in dedup:
        by_file.setdefault(h["file"], []).append(h)

    fixed_files = []
    for rel_path, hits in list(by_file.items())[:8]:
        abs_path = os.path.join(agent.workspace, rel_path)
        r = read_file(abs_path)
        if not r["ok"]:
            continue

        todo_list = "\n".join(f"  Line {h['line_no']}: {h['content']}" for h in hits)
        print(f"\n   📄 Fixing TODOs in {rel_path}...")

        prompt = f"""Address all TODO/FIXME/HACK comments in this file.
Replace each TODO comment with a real implementation.
Return the COMPLETE updated file using FILE: {rel_path} format.

TODOs to address:
{todo_list}

Current file:
```python
{r['content'][:2000]}
```"""
        response = ask(prompt, system=SYSTEM_PROMPT)

        from agent.executor import _extract_file_blocks, _auto_write_files
        blocks = _extract_file_blocks(response)
        if blocks:
            _backup_file(abs_path, agent.workspace)
            written = _auto_write_files(blocks, agent.workspace)
            fixed_files.extend(written)
            print(f"   ✅ Updated: {written}")

    agent._refresh_scan()
    return f"✅ Addressed TODOs in {len(fixed_files)} file(s).\n\n{summary}"