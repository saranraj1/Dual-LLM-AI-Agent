"""agent/commands/files.py — /explain /diff /undo /run-file /translate"""

import os
from core.llm import ask, ask_stream
from core.prompt_builder import SYSTEM_PROMPT
from tools.file_tools import read_file
from tools.code_tools import run_python_file


# ── /explain ─────────────────────────────────────────────────────────────────

def cmd_explain(agent, args: str) -> str:
    target = args.strip()
    if not target:
        return "Usage: /explain <filename>"

    path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
    r = read_file(path)
    if not r["ok"]:
        return f"❌ Cannot read {target}: {r['error']}"

    prompt = f"""Explain this code thoroughly for a developer who is new to the codebase.

Cover:
1. What this file does (purpose)
2. Key functions/classes and what each does
3. How it interacts with other parts of the system
4. Any tricky logic or design decisions
5. Potential issues or areas to watch out for

Use clear language. Include code snippets when helpful.

File: {target}
```
{r['content'][:3000]}
```"""

    print("\nAgent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /diff ─────────────────────────────────────────────────────────────────────

def cmd_diff(agent, args: str) -> str:
    target = args.strip()
    from tools.terminal_tools import run_command

    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r = run_command(f'git diff HEAD -- "{path}"', cwd=agent.workspace)
        if r["ok"] and r["stdout"]:
            return f"📋 Git diff for {target}:\n{r['stdout'][:3000]}"
        # Fall back to backup comparison
        backup_dir = os.path.join(agent.workspace, ".agent_backups")
        backup = os.path.join(backup_dir, target.replace(os.sep, "_") + ".bak")
        if os.path.exists(backup):
            r2 = run_command(f'diff "{backup}" "{path}"', cwd=agent.workspace)
            return f"📋 Diff vs backup:\n{r2['stdout'][:3000]}" if r2["stdout"] else "✅ No changes from backup."
        return "No git diff and no backup found."
    else:
        r = run_command("git diff --stat", cwd=agent.workspace)
        return r["stdout"] or r["stderr"] or "No changes."


# ── /undo and /checkpoints ────────────────────────────────────────────────────

def cmd_undo(agent, args: str) -> str:
    """
    Restore files to a previous checkpoint.
    Usage:
      /undo               - Restore whole workspace to the previous turn checkpoint
      /undo 2             - Restore to 2 checkpoints ago
      /undo <filename>    - Restore a specific file from the checkpoint or legacy backup
    """
    arg = args.strip()
    from tools.checkpoint_tools import restore_checkpoint

    # 1. Whole workspace rollback (if empty or numeric index)
    if not arg or arg.isdigit():
        res = restore_checkpoint(checkpoint_id_or_index=arg or "1", root_dir=agent.workspace)
        if res.get("ok"):
            cp = res.get("restored_checkpoint", {})
            return f"✅ {res.get('message', 'Workspace restored to checkpoint.')}\n(Commit: {cp.get('commit', '')[:7]} at {cp.get('timestamp', '')[:19]})"
        return f"❌ {res.get('error', 'Failed to restore checkpoint.')}"

    # 2. Specific file rollback via shadow checkpoint
    res = restore_checkpoint(checkpoint_id_or_index=None, target_file=arg, root_dir=agent.workspace)
    if res.get("ok"):
        return f"✅ {res.get('message', f'Restored {arg} from checkpoint.')}"

    # 3. Fallback to legacy backup if checkpoint failed
    path = os.path.join(agent.workspace, arg) if not os.path.isabs(arg) else arg
    backup_dir = os.path.join(agent.workspace, ".agent_backups")
    backup = os.path.join(backup_dir, arg.replace(os.sep, "_") + ".bak")

    if os.path.exists(backup):
        try:
            import shutil
            shutil.copy2(backup, path)
            return f"✅ {arg} restored from legacy backup."
        except Exception as e:
            return f"❌ Could not restore: {e}"

    return f"❌ No checkpoint or backup found for '{arg}'. Run /checkpoints to list available checkpoints."


def cmd_checkpoints(agent, args: str) -> str:
    """List recent shadow git checkpoints available for rollback."""
    from tools.checkpoint_tools import list_checkpoints
    limit = int(args.strip()) if args.strip().isdigit() else 10
    cps = list_checkpoints(limit=limit, root_dir=agent.workspace)
    if not cps:
        return "ℹ️ No checkpoints recorded yet in this workspace. Checkpoints are automatically generated before code edits."

    lines = [f"📌 Recent Workspace Checkpoints ({len(cps)} available):"]
    for i, cp in enumerate(cps, 1):
        ts = cp.get("timestamp", "")[:19].replace("T", " ")
        commit = cp.get("commit", "")[:7]
        desc = cp.get("description", "Checkpoint")
        lines.append(f"  {i}. [{commit}] {ts} — {desc}")
    lines.append("\nTip: Run '/undo' to revert the last action or '/undo <number>' to revert to a specific state.")
    return "\n".join(lines)


# ── /run-file ─────────────────────────────────────────────────────────────────

def cmd_run_file(agent, args: str) -> str:
    if not args.strip():
        return "Usage: /run-file <filename> [args...]"

    parts = args.strip().split()
    filename = parts[0]
    run_args = parts[1:] if len(parts) > 1 else []
    path = os.path.join(agent.workspace, filename) if not os.path.isabs(filename) else filename

    if not os.path.exists(path):
        return f"❌ File not found: {path}"

    print(f"\n▶ Running {filename}...")
    r = run_python_file(path, args=run_args)

    if r["ok"]:
        output = r["stdout"] or "(no output)"
        print(f"✅ Output:\n{output}")
        return output

    print(f"❌ Error:\n{r['stderr']}")

    file_r = read_file(path)
    content = file_r["content"] if file_r["ok"] else ""
    prompt = f"""This Python file crashed with this error:
{r['stderr'][:500]}

Fix the code and return the COMPLETE fixed file using FILE: {filename} format.

Current code:
```python
{content[:2000]}
```"""

    print(f"\n🔧 Agent is analyzing the error and fixing...")
    print("Agent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    response = full


    from agent.executor import _extract_file_blocks, _auto_write_files
    from agent.commands_base import _backup_file
    blocks = _extract_file_blocks(response)
    if blocks:
        _backup_file(path, agent.workspace)
        _auto_write_files(blocks, agent.workspace)
        print(f"   ✅ Fixed. Re-running...")
        r2 = run_python_file(path, args=run_args)
        output = r2["stdout"] or r2["stderr"]
        print(output[:500])
        return output
    return response


# ── /translate ────────────────────────────────────────────────────────────────

def cmd_translate(agent, args: str) -> str:
    parts = args.strip().split()
    if len(parts) < 2:
        return "Usage: /translate <file> <target_language>\nExample: /translate main.py typescript"

    filename = parts[0]
    target_lang = " ".join(parts[1:])
    path = os.path.join(agent.workspace, filename) if not os.path.isabs(filename) else filename

    r = read_file(path)
    if not r["ok"]:
        return f"❌ Cannot read {filename}: {r['error']}"

    ext_map = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
               ".java": "Java", ".cpp": "C++", ".cs": "C#", ".go": "Go",
               ".rb": "Ruby", ".php": "PHP", ".rs": "Rust"}
    src_ext = os.path.splitext(filename)[1].lower()
    src_lang = ext_map.get(src_ext, "the source language")
    rev_map = {v.lower(): k for k, v in ext_map.items()}
    tgt_ext = rev_map.get(target_lang.lower(), f".{target_lang.lower()[:3]}")
    tgt_file = os.path.splitext(filename)[0] + tgt_ext

    prompt = f"""Translate this {src_lang} code to {target_lang}.

Rules:
1. Use idiomatic {target_lang} patterns and conventions
2. Preserve all logic and functionality exactly
3. Convert libraries to their {target_lang} equivalents
4. Add appropriate type annotations if the target language supports them
5. Return the COMPLETE translated file using FILE: {tgt_file} format

{src_lang} source ({filename}):
```
{r['content'][:2500]}
```"""

    print(f"\n🔄 Translating {filename} → {target_lang}...")
    print("Agent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    response = full
    from agent.executor import _extract_file_blocks, _auto_write_files
    blocks = _extract_file_blocks(response)
    if blocks:
        written = _auto_write_files(blocks, agent.workspace)
        agent._refresh_scan()
        return f"✅ Translated to {target_lang}: {written}\n\n{response[:500]}"
    print(response)
    return response
