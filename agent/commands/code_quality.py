"""agent/commands/code_quality.py — /review /optimize /refactor /security /format /lint"""

import os
from core.llm import ask, ask_stream
from core.prompt_builder import SYSTEM_PROMPT
from tools.file_tools import read_file, scan_codebase, build_context_string
from tools.terminal_tools import run_command
from config.settings import SKIP_DIRS


# ── /review ──────────────────────────────────────────────────────────────────

def cmd_review(agent, args: str) -> str:
    target = args.strip()
    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r = read_file(path)
        if not r["ok"]:
            return f"❌ Cannot read {target}: {r['error']}"
        context = f"File: {target}\n```\n{r['content'][:2500]}\n```"
    else:
        context = agent.code_context[:2500]

    prompt = f"""Perform a thorough code review. Score each category 1-10 and give specific feedback with line numbers where possible.

Categories to score:
1. Readability (naming, comments, structure)
2. Performance (algorithms, unnecessary work, caching)
3. Security (injection, secrets, validation, auth)
4. Maintainability (SOLID, coupling, duplication)
5. Error Handling (edge cases, exceptions, logging)

For each issue found: state the line/function, what the problem is, and show the fix.
End with an Overall Score and Top 3 Priority Fixes.

{context}"""

    print("\nAgent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /optimize ─────────────────────────────────────────────────────────────────

def cmd_optimize(agent, args: str) -> str:
    target = args.strip()
    if not target:
        return "Usage: /optimize <filename>"

    path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
    r = read_file(path)
    if not r["ok"]:
        return f"❌ Cannot read {target}: {r['error']}"

    prompt = f"""Optimize this code for maximum performance and readability.

Steps:
1. Identify bottlenecks and O(n) complexity issues
2. Add caching where beneficial
3. Replace slow patterns with faster alternatives
4. Improve memory usage
5. Return the COMPLETE optimized file using FILE: {target} format

Explain what you changed and why for each optimization.

Current code:
```
{r['content'][:2500]}
```"""

    print("\n🚀 Optimizing...")
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
        written = _auto_write_files(blocks, agent.workspace)
        agent._refresh_scan()
        print(f"   ✅ Optimized and saved: {written}")

    print(response)
    return response


# ── /refactor ─────────────────────────────────────────────────────────────────

def cmd_refactor(agent, args: str) -> str:
    target = args.strip()
    if not target:
        return "Usage: /refactor <filename>"

    path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
    r = read_file(path)
    if not r["ok"]:
        return f"❌ Cannot read {target}: {r['error']}"

    prompt = f"""Refactor this code applying software engineering best practices.

Apply:
1. Single Responsibility Principle — split large functions/classes
2. DRY — eliminate all code duplication
3. Better naming — variables, functions, classes should be self-documenting
4. Reduce nesting — flatten deeply nested logic
5. Extract constants — no magic numbers or strings
6. Improve function signatures — reduce parameter count

Return the COMPLETE refactored file using FILE: {target} format.
Then explain every significant change you made.

Original:
```
{r['content'][:2500]}
```"""

    print(f"\n🔨 Refactoring {target}...")
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
        written = _auto_write_files(blocks, agent.workspace)
        agent._refresh_scan()
        print(f"   ✅ Refactored: {written}")

    print(response)
    return response


# ── /security ─────────────────────────────────────────────────────────────────

def cmd_security(agent, args: str) -> str:
    target = args.strip()
    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r = read_file(path)
        if not r["ok"]:
            return f"❌ Cannot read {target}: {r['error']}"
        context = f"File: {target}\n```\n{r['content'][:2500]}\n```"
    else:
        context = agent.code_context[:2500]

    prompt = f"""Perform a security audit of this code. Be thorough and specific.

Check for:
1. SQL Injection vulnerabilities
2. Hardcoded secrets, API keys, passwords
3. Missing input validation / sanitization
4. Insecure authentication / authorization
5. Path traversal vulnerabilities
6. Insecure deserialization
7. Missing error handling that leaks info
8. Outdated or insecure dependencies

For each issue found:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- Location: file and line number
- Description: what the vulnerability is
- Fix: exact code to fix it

End with a Security Score (0-100) and summary.

{context}"""

    print("\n🔒 Running security audit...")
    print("Agent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /format ───────────────────────────────────────────────────────────────────

def cmd_format(agent, args: str) -> str:
    target = args.strip()
    cwd = agent.workspace

    if target:
        path = os.path.join(cwd, target) if not os.path.isabs(target) else target
        r = run_command(f'black "{path}"', cwd=cwd)
        if r["ok"]:
            return f"✅ Formatted: {target}\n{r['stdout'] or r['stderr']}"
        r2 = run_command(f'autopep8 --in-place "{path}"', cwd=cwd)
        if r2["ok"]:
            return f"✅ Formatted with autopep8: {target}"
        return f"❌ Could not format. Install black: pip install black\n{r['stderr']}"
    else:
        r = run_command("black .", cwd=cwd)
        if r["ok"]:
            agent._refresh_scan()
            return f"✅ Formatted all files:\n{r['stdout'] or r['stderr']}"
        return f"❌ {r['stderr']}\nInstall with: pip install black"


# ── /lint ─────────────────────────────────────────────────────────────────────

def cmd_lint(agent, args: str) -> str:
    target = args.strip()
    cwd = agent.workspace
    auto_fix = target.lower() == "fix"

    if auto_fix:
        target = ""

    path_arg = f'"{os.path.join(cwd, target)}"' if target else "."
    r = run_command(f"flake8 {path_arg} --max-line-length=120", cwd=cwd)
    issues = (r["stdout"] or r["stderr"]).strip()

    if not issues:
        return "✅ No lint issues found!"

    output = f"🔍 Lint results:\n{issues[:1500]}"
    print(output)

    if auto_fix or target:
        print("\n🔧 AI auto-fixing lint issues...")
        prompt = f"""Fix all these Python lint issues. For each fixed file, provide the complete
corrected code using FILE: <filename> format.

Lint errors:
{issues[:800]}

Relevant code:
{agent.code_context[:1200]}"""
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
            for b in blocks:
                p = os.path.join(cwd, b["path"])
                _backup_file(p, cwd)
            written = _auto_write_files(blocks, cwd)
            agent._refresh_scan()
            return f"✅ Fixed and saved: {written}\n\nOriginal issues:\n{issues[:500]}"

    return output
