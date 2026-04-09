"""
agent/commands_extended.py — Extended agent commands.
/review, /optimize, /docs, /git, /refactor, /security,
/summarize, /changelog, /stats, /deps, /diagram,
/run-file, /scaffold, /ask, /mode
"""

import os
import re
import sys
import json
import urllib.request
from pathlib import Path
from typing import Optional, List, Dict
from core.llm import ask, ask_stream
from core.prompt_builder import SYSTEM_PROMPT
from tools.file_tools import read_file, write_file, scan_codebase, build_context_string, list_dir
from tools.terminal_tools import run_command
from tools.code_tools import run_python, run_python_file, install_package
from config.settings import SKIP_DIRS, SUPPORTED_EXTENSIONS


# ── /review <file> ────────────────────────────────────────────────────────────

def cmd_review(agent, args: str) -> str:
    """
    Full code review with scores on readability, performance, security.
    Usage: /review main.py
           /review              → reviews entire project
    """
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


# ── /optimize <file> ──────────────────────────────────────────────────────────

def cmd_optimize(agent, args: str) -> str:
    """
    Performance-focused rewrite — better algorithms, caching, reduced complexity.
    Usage: /optimize main.py
    """
    target = args.strip()
    if not target:
        return "Usage: /optimize <filename>"

    path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
    r    = read_file(path)
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
    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    from agent.commands import _backup_file
    blocks = _extract_file_blocks(response)
    if blocks:
        _backup_file(path, agent.workspace)
        written = _auto_write_files(blocks, agent.workspace)
        agent._refresh_scan()
        print(f"   ✅ Optimized and saved: {written}")

    print(response)
    return response


# ── /docs <file> ──────────────────────────────────────────────────────────────

def cmd_docs(agent, args: str) -> str:
    """
    Auto-generate docstrings, README, and API documentation.
    Usage: /docs              → generate README for whole project
           /docs main.py      → add docstrings to a specific file
    """
    target = args.strip()

    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r    = read_file(path)
        if not r["ok"]:
            return f"❌ Cannot read {target}: {r['error']}"

        prompt = f"""Add complete docstrings to every function, class, and module in this file.
Use Google-style docstrings with Args, Returns, Raises, and Example sections.
Return the COMPLETE file with docstrings added using FILE: {target} format.

```python
{r['content'][:2500]}
```"""
        print("\n📝 Adding docstrings...")
        response = ask(prompt, system=SYSTEM_PROMPT)

        from agent.executor import _extract_file_blocks, _auto_write_files
        from agent.commands import _backup_file
        blocks = _extract_file_blocks(response)
        if blocks:
            _backup_file(path, agent.workspace)
            written = _auto_write_files(blocks, agent.workspace)
            print(f"   ✅ Documented: {written}")
        return response

    else:
        print("\n📚 Generating README.md...")
        scan    = scan_codebase(agent.workspace)
        context = build_context_string(scan, char_limit=2000) if scan["ok"] else agent.code_context
        tree    = list_dir(agent.workspace, depth=2)
        tree_str = "\n".join(e["path"] for e in tree["entries"][:30]) if tree["ok"] else ""

        prompt = f"""Generate a comprehensive README.md for this project.

Include:
1. Project title and description
2. Features list
3. Installation instructions
4. Usage examples with code
5. Project structure explanation
6. Configuration options
7. Contributing guidelines
8. License section

Use FILE: README.md format.

Project structure:
{tree_str}

Codebase:
{context[:2000]}"""

        response = ask(prompt, system=SYSTEM_PROMPT)

        from agent.executor import _extract_file_blocks, _auto_write_files
        blocks = _extract_file_blocks(response)
        if blocks:
            written = _auto_write_files(blocks, agent.workspace)
            print(f"   ✅ Created: {written}")
        return response


# ── /git <message> ────────────────────────────────────────────────────────────

def cmd_git(agent, args: str) -> str:
    """
    Smart git operations.
    Usage: /git                → auto-commit with AI-generated message
           /git <message>      → commit with custom message
           /git status         → show git status
           /git log            → show recent commits
           /git push           → push to remote
    """
    action = args.strip()
    cwd    = agent.workspace
    action_lower = action.lower()

    if action_lower == "status":
        r = run_command("git status", cwd=cwd)
        return r["stdout"] or r["stderr"]

    if action_lower == "log":
        r = run_command("git log --oneline -15", cwd=cwd)
        return r["stdout"] or r["stderr"]

    if action_lower == "push":
        r = run_command("git push", cwd=cwd)
        return r["stdout"] or r["stderr"]

    # Auto-generate commit message if none given
    if not action or action_lower == "auto":
        diff_r  = run_command("git diff --stat HEAD", cwd=cwd)
        status_r = run_command("git status --short",  cwd=cwd)
        changed  = (diff_r["stdout"] or "") + "\n" + (status_r["stdout"] or "")

        if not changed.strip():
            return "Nothing to commit."

        print("🤖 Generating commit message...")
        msg_prompt = f"""Write a concise, conventional git commit message for these changes.
Format: <type>(<scope>): <description>
Types: feat, fix, docs, refactor, test, chore
Keep it under 72 characters. Just output the message, nothing else.

Changes:
{changed[:800]}"""
        commit_msg = ask(msg_prompt).strip().strip('"').strip("'")
        print(f"   Message: {commit_msg}")
    else:
        commit_msg = action

    results = []
    r1 = run_command("git add -A", cwd=cwd)
    results.append(f"git add: {'ok' if r1['ok'] else r1['stderr']}")

    r2 = run_command(f'git commit -m "{commit_msg}"', cwd=cwd)
    results.append(f"git commit: {r2['stdout'][:100] if r2['ok'] else r2['stderr'][:100]}")

    return "\n".join(results)


# ── /refactor <file> ──────────────────────────────────────────────────────────

def cmd_refactor(agent, args: str) -> str:
    """
    Apply SOLID principles, remove duplication, improve naming and structure.
    Usage: /refactor main.py
    """
    target = args.strip()
    if not target:
        return "Usage: /refactor <filename>"

    path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
    r    = read_file(path)
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
    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    from agent.commands import _backup_file
    blocks = _extract_file_blocks(response)
    if blocks:
        _backup_file(path, agent.workspace)
        written = _auto_write_files(blocks, agent.workspace)
        agent._refresh_scan()
        print(f"   ✅ Refactored: {written}")

    print(response)
    return response


# ── /security <file> ──────────────────────────────────────────────────────────

def cmd_security(agent, args: str) -> str:
    """
    Security audit — SQL injection, secrets, validation, auth issues.
    Usage: /security              → audit entire project
           /security main.py      → audit specific file
    """
    target = args.strip()
    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r    = read_file(path)
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


# ── /summarize ────────────────────────────────────────────────────────────────

def cmd_summarize(agent, args: str) -> str:
    """
    Summarize entire codebase in plain English.
    Usage: /summarize
           /summarize main.py   → summarize a specific file
    """
    target = args.strip()
    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r    = read_file(path)
        if not r["ok"]:
            return f"❌ Cannot read {target}: {r['error']}"
        context = f"File: {target}\n```\n{r['content'][:2500]}\n```"
        scope   = f"the file {target}"
    else:
        tree     = list_dir(agent.workspace, depth=2)
        tree_str = "\n".join(e["path"] for e in tree["entries"][:30]) if tree["ok"] else ""
        context  = f"Structure:\n{tree_str}\n\nCode:\n{agent.code_context[:2000]}"
        scope    = "this entire project"

    prompt = f"""Summarize {scope} in plain English for someone new to the codebase.

Cover:
1. What this project/file does (1-2 sentences)
2. The main components and what each does
3. How data flows through the system
4. Key dependencies and why they're used
5. What a developer would need to know to start contributing

Write clearly, avoid jargon, use analogies if helpful.

{context}"""

    print("\nAgent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /changelog ────────────────────────────────────────────────────────────────

def cmd_changelog(agent, args: str) -> str:
    """
    Generate CHANGELOG.md from git history.
    Usage: /changelog
    """
    cwd = agent.workspace
    r   = run_command("git log --oneline --no-merges -50", cwd=cwd)
    if not r["ok"] or not r["stdout"]:
        return "❌ No git history found. Initialize git first with: git init"

    prompt = f"""Generate a professional CHANGELOG.md from these git commits.

Group changes by type: Added, Changed, Fixed, Removed, Security.
Use semantic versioning sections if you can detect version bumps.
Use FILE: CHANGELOG.md format.

Git log:
{r['stdout']}"""

    print("\n📋 Generating CHANGELOG...")
    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    blocks = _extract_file_blocks(response)
    if blocks:
        written = _auto_write_files(blocks, agent.workspace)
        print(f"   ✅ Created: {written}")
    return response


# ── /stats ────────────────────────────────────────────────────────────────────

def cmd_stats(agent, args: str) -> str:
    """
    Project statistics — lines of code, file count, complexity, etc.
    Usage: /stats
    """
    root  = Path(agent.workspace)
    stats = {
        "total_files": 0,
        "total_lines": 0,
        "total_chars": 0,
        "by_extension": {},
        "empty_files": 0,
    }
    file_sizes = []

    for fp in root.rglob("*"):
        if not fp.is_file():
            continue
        if any(s in fp.parts for s in SKIP_DIRS):
            continue
        if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            lines   = content.count("\n") + 1
            chars   = len(content)
            ext     = fp.suffix.lower() or ".txt"

            stats["total_files"] += 1
            stats["total_lines"] += lines
            stats["total_chars"] += chars
            stats["by_extension"][ext] = stats["by_extension"].get(ext, 0) + 1

            if chars == 0:
                stats["empty_files"] += 1

            rel = str(fp.relative_to(root))
            file_sizes.append((lines, rel))
        except Exception:
            continue

    file_sizes.sort(reverse=True)
    largest = file_sizes[:5]

    out = [
        f"\n📊 Project Statistics — {agent.workspace}",
        f"{'─'*45}",
        f"  Total files     : {stats['total_files']}",
        f"  Total lines     : {stats['total_lines']:,}",
        f"  Total chars     : {stats['total_chars']:,}",
        f"  Empty files     : {stats['empty_files']}",
        f"\n  By extension:",
    ]
    for ext, count in sorted(stats["by_extension"].items(), key=lambda x: -x[1]):
        out.append(f"    {ext:<12} {count} files")

    out.append(f"\n  Largest files (by lines):")
    for ln, fname in largest:
        out.append(f"    {ln:>5} lines  {fname}")

    return "\n".join(out)


# ── /deps ─────────────────────────────────────────────────────────────────────

def cmd_deps(agent, args: str) -> str:
    """
    Dependency analysis — find all imports, installed status.
    Usage: /deps
    """
    root    = Path(agent.workspace)
    imports = {}
    stdlib  = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()

    for fp in root.rglob("*.py"):
        if any(s in fp.parts for s in SKIP_DIRS):
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            found   = re.findall(r'^(?:import|from)\s+([\w.]+)', content, re.MULTILINE)
            rel     = str(fp.relative_to(root))
            for imp in found:
                top = imp.split(".")[0]
                if top not in imports:
                    imports[top] = []
                imports[top].append(rel)
        except Exception:
            continue

    third_party = {k: v for k, v in imports.items()
                   if k not in stdlib and k not in ("__future__", "")}

    # Check installed packages
    r = run_command("pip list --format=json", cwd=agent.workspace)
    installed = {}
    if r["ok"]:
        try:
            pkgs      = json.loads(r["stdout"])
            installed = {p["name"].lower(): p["version"] for p in pkgs}
        except Exception:
            pass

    out = [f"\n📦 Dependency Analysis", f"{'─'*40}",
           f"\n  Third-party imports ({len(third_party)}):"]
    for pkg, files in sorted(third_party.items()):
        ver    = installed.get(pkg.lower(), "not installed")
        status = "✅" if pkg.lower() in installed else "❌"
        out.append(f"  {status} {pkg:<20} {ver}  (used in {len(files)} file(s))")

    pkg_list   = ", ".join(third_party.keys())
    suggestion = ask(
        f"Given these Python dependencies: {pkg_list}\n"
        f"List any outdated/deprecated packages with modern replacements. Be brief."
    )
    out.append(f"\n  💡 Suggestions:\n{suggestion[:400]}")
    return "\n".join(out)


# ── /diagram ──────────────────────────────────────────────────────────────────

def cmd_diagram(agent, args: str) -> str:
    """
    Generate ASCII architecture diagram of the project.
    Usage: /diagram
    """
    tree     = list_dir(agent.workspace, depth=3)
    tree_str = "\n".join(e["path"] for e in tree["entries"][:40]) if tree["ok"] else ""

    prompt = f"""Generate two things:

1. An ASCII architecture diagram showing how the main components connect
   (use arrows → to show data/call flow)

2. A Mermaid diagram (graph TD format) of the same architecture
   Save it as FILE: docs/architecture.md

Project structure:
{tree_str}

Code context:
{agent.code_context[:1500]}"""

    print("\n📐 Generating architecture diagram...")
    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    blocks = _extract_file_blocks(response)
    if blocks:
        os.makedirs(os.path.join(agent.workspace, "docs"), exist_ok=True)
        written = _auto_write_files(blocks, agent.workspace)
        print(f"   ✅ Saved: {written}")

    print(response)
    return response


# ── /run-file <file> ──────────────────────────────────────────────────────────

def cmd_run_file(agent, args: str) -> str:
    """
    Run a file directly. If it crashes, agent reads the error and auto-fixes.
    Usage: /run-file main.py
           /run-file script.py arg1 arg2
    """
    if not args.strip():
        return "Usage: /run-file <filename> [args...]"

    parts    = args.strip().split()
    filename = parts[0]
    run_args = parts[1:] if len(parts) > 1 else []
    path     = os.path.join(agent.workspace, filename) if not os.path.isabs(filename) else filename

    if not os.path.exists(path):
        return f"❌ File not found: {path}"

    print(f"\n▶ Running {filename}...")
    r = run_python_file(path, args=run_args)

    if r["ok"]:
        output = r["stdout"] or "(no output)"
        print(f"✅ Output:\n{output}")
        return output

    # Auto-fix on failure
    print(f"❌ Error:\n{r['stderr']}")
    print(f"\n🔧 Agent is analyzing the error and fixing...")

    file_r  = read_file(path)
    content = file_r["content"] if file_r["ok"] else ""

    prompt = f"""This Python file crashed with this error:
{r['stderr'][:500]}

Fix the code and return the COMPLETE fixed file using FILE: {filename} format.

Current code:
```python
{content[:2000]}
```"""

    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    from agent.commands import _backup_file
    blocks = _extract_file_blocks(response)
    if blocks:
        _backup_file(path, agent.workspace)
        _auto_write_files(blocks, agent.workspace)
        print(f"   ✅ Fixed. Re-running...")
        r2     = run_python_file(path, args=run_args)
        output = r2["stdout"] or r2["stderr"]
        print(output[:500])
        return output

    return response


# ── /scaffold <type> ──────────────────────────────────────────────────────────

SCAFFOLD_TYPES = {
    "flask-api":   "Flask REST API with blueprints, SQLAlchemy, JWT auth, error handlers",
    "fastapi":     "FastAPI with Pydantic models, async routes, OpenAPI docs, SQLAlchemy",
    "react-app":   "React app with components, hooks, routing, API service layer",
    "cli-tool":    "Python CLI tool with argparse, config file, logging, tests",
    "discord-bot": "Discord.py bot with commands, events, cog structure",
    "scraper":     "Web scraper with requests/BeautifulSoup, rate limiting, data export",
    "ml-project":  "ML project with data loading, preprocessing, model training, evaluation",
}


def cmd_scaffold(agent, args: str) -> str:
    """
    Scaffold a complete project structure with boilerplate.
    Usage: /scaffold flask-api | fastapi | react-app | cli-tool | discord-bot | scraper | ml-project
           /scaffold <describe your own>
    """
    scaffold_type = args.strip().lower()

    if not scaffold_type:
        options = "\n".join(f"  /scaffold {k:<15} — {v[:50]}" for k, v in SCAFFOLD_TYPES.items())
        return f"Available scaffolds:\n{options}\n\nOr describe your own: /scaffold my custom project"

    description = SCAFFOLD_TYPES.get(scaffold_type, scaffold_type)

    print(f"\n🏗️  Scaffolding: {scaffold_type}...")
    print("   This will create multiple files — please wait...\n")

    prompt = f"""Create a complete, production-ready project scaffold for: {description}

Requirements:
1. Create ALL necessary files using FILE: path/filename.ext format
2. Write real, working boilerplate code (not placeholder comments)
3. Include requirements.txt with all dependencies
4. Include a basic README.md
5. Include at least one working example/test
6. Add proper error handling from the start
7. Include a .gitignore

Create every file the project needs to run immediately after pip install -r requirements.txt"""

    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    blocks = _extract_file_blocks(response)
    if blocks:
        written = _auto_write_files(blocks, agent.workspace)
        agent._refresh_scan()
        print(f"\n✅ Created {len(written)} files:")
        for w in written:
            print(f"   {w}")

        req_file = os.path.join(agent.workspace, "requirements.txt")
        if os.path.exists(req_file):
            print("\n📦 Installing dependencies...")
            r = run_command("pip install -r requirements.txt", cwd=agent.workspace)
            print(r["stdout"][-300:] if r["ok"] else r["stderr"][:300])
        return f"Scaffold complete. {len(written)} files created."

    return "⚠️  No files were generated. Try being more specific in your description."


# ── /ask <url> ────────────────────────────────────────────────────────────────

def cmd_ask_url(agent, args: str) -> str:
    """
    Fetch a URL and use it as context — read docs, Stack Overflow, etc.
    Usage: /ask https://docs.python.org/3/library/pathlib.html
           /ask https://example.com What does this page say about X?
    """
    parts    = args.strip().split(" ", 1)
    url      = parts[0]
    question = parts[1] if len(parts) > 1 else "Summarize this page and extract the key information."

    if not url.startswith("http"):
        return "Usage: /ask <url> [optional question]"

    print(f"\n🌐 Fetching: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"❌ Could not fetch URL: {e}"

    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', ' ', raw)
    clean = re.sub(r'\s+', ' ', clean).strip()[:3000]

    prompt = f"""{question}

Page content from {url}:
{clean}"""

    print("Agent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /mode <mode> ──────────────────────────────────────────────────────────────

MODES = {
    "debug": (
        "debug",
        "You are in DEBUG MODE. Focus exclusively on finding and fixing errors. "
        "Always ask: what could go wrong? Check edge cases, null values, type mismatches. "
        "Show exact error locations and fixes."
    ),
    "architect": (
        "architect",
        "You are in ARCHITECT MODE. Think at the system design level. "
        "Consider scalability, maintainability, separation of concerns. "
        "Suggest patterns, structures, and abstractions. Draw ASCII diagrams when helpful."
    ),
    "tutor": (
        "tutor",
        "You are in TUTOR MODE. Explain everything step by step as if teaching a beginner. "
        "Use simple language, analogies, and examples. Check understanding. Never skip steps."
    ),
    "fast": (
        "fast",
        "You are in FAST MODE. Give extremely concise answers. "
        "Code only — no explanations unless asked. One sentence max for non-code answers."
    ),
    "review": (
        "review",
        "You are in REVIEW MODE. For every piece of code you see, automatically "
        "provide a brief quality assessment: correctness, style, potential issues."
    ),
    "normal": (
        "normal",
        SYSTEM_PROMPT
    ),
}


def cmd_mode(agent, args: str) -> str:
    """
    Switch agent personality/focus mode.
    Usage: /mode debug | architect | tutor | fast | review | normal
    """
    mode_name = args.strip().lower()

    if not mode_name or mode_name not in MODES:
        options = "\n".join(f"  /mode {k:<12} — {v[1][:60]}..." for k, v in MODES.items())
        return f"Available modes:\n{options}"

    name, system = MODES[mode_name]
    import core.prompt_builder as pb
    pb.SYSTEM_PROMPT = system
    agent._current_mode = name

    icons = {"debug": "🐛", "architect": "🏗️", "tutor": "📚",
             "fast": "⚡", "review": "🔍", "normal": "🤖"}
    return f"{icons.get(name, '🤖')} Switched to {name.upper()} mode."


# ── /format <file> ────────────────────────────────────────────────────────────

def cmd_format(agent, args: str) -> str:
    """
    Auto-format Python files using black (or autopep8 as fallback).
    Usage: /format main.py
           /format          → format all .py files in workspace
    """
    target = args.strip()
    cwd    = agent.workspace

    if target:
        path = os.path.join(cwd, target) if not os.path.isabs(target) else target
        r = run_command(f"black \"{path}\"", cwd=cwd)
        if r["ok"]:
            return f"✅ Formatted: {target}\n{r['stdout'] or r['stderr']}"
        # Try autopep8 as fallback
        r2 = run_command(f"autopep8 --in-place \"{path}\"", cwd=cwd)
        if r2["ok"]:
            return f"✅ Formatted with autopep8: {target}"
        return f"❌ Could not format. Install black: pip install black\n{r['stderr']}"
    else:
        r = run_command("black .", cwd=cwd)
        if r["ok"]:
            agent._refresh_scan()
            return f"✅ Formatted all files:\n{r['stdout'] or r['stderr']}"
        return f"❌ {r['stderr']}\nInstall with: pip install black"


# ── /lint <file> ──────────────────────────────────────────────────────────────

def cmd_lint(agent, args: str) -> str:
    """
    Run linter on file(s) and auto-fix issues with AI.
    Usage: /lint main.py
           /lint          → lint entire project
           /lint fix      → auto-fix all lint issues
    """
    target   = args.strip()
    cwd      = agent.workspace
    auto_fix = target.lower() == "fix"

    if auto_fix:
        target = ""

    path_arg = f"\"{os.path.join(cwd, target)}\"" if target else "."

    # Try flake8
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
        response = ask(prompt, system=SYSTEM_PROMPT)
        from agent.executor import _extract_file_blocks, _auto_write_files
        from agent.commands import _backup_file
        blocks = _extract_file_blocks(response)
        if blocks:
            for b in blocks:
                p = os.path.join(cwd, b["path"])
                _backup_file(p, cwd)
            written = _auto_write_files(blocks, cwd)
            agent._refresh_scan()
            return f"✅ Fixed and saved: {written}\n\nOriginal issues:\n{issues[:500]}"

    return output


# ── /translate <file> <language> ─────────────────────────────────────────────

def cmd_translate(agent, args: str) -> str:
    """
    Translate code from one language to another.
    Usage: /translate main.py typescript
           /translate app.js python
    """
    parts = args.strip().split()
    if len(parts) < 2:
        return "Usage: /translate <file> <target_language>\nExample: /translate main.py typescript"

    filename    = parts[0]
    target_lang = " ".join(parts[1:])
    path        = os.path.join(agent.workspace, filename) if not os.path.isabs(filename) else filename

    r = read_file(path)
    if not r["ok"]:
        return f"❌ Cannot read {filename}: {r['error']}"

    # Detect source language from extension
    ext_map = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
               ".java": "Java", ".cpp": "C++", ".cs": "C#", ".go": "Go",
               ".rb": "Ruby", ".php": "PHP", ".rs": "Rust"}
    src_ext  = os.path.splitext(filename)[1].lower()
    src_lang = ext_map.get(src_ext, "the source language")

    # Target file extension
    rev_map  = {v.lower(): k for k, v in ext_map.items()}
    tgt_ext  = rev_map.get(target_lang.lower(), f".{target_lang.lower()[:3]}")
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
    response = ask(prompt, system=SYSTEM_PROMPT)

    from agent.executor import _extract_file_blocks, _auto_write_files
    blocks = _extract_file_blocks(response)
    if blocks:
        written = _auto_write_files(blocks, agent.workspace)
        agent._refresh_scan()
        return f"✅ Translated to {target_lang}: {written}\n\n{response[:500]}"

    print(response)
    return response


# ── /search <query> ───────────────────────────────────────────────────────────

def cmd_search(agent, args: str) -> str:
    """
    Search the web (DuckDuckGo) and summarize results.
    Usage: /search how to implement JWT auth in Python
           /search <topic> and apply to my project
    """
    query = args.strip()
    if not query:
        return "Usage: /search <your question>"

    print(f"\n🔎 Searching: {query}")

    # DuckDuckGo instant answer API (no key needed)
    encoded = urllib.parse.quote_plus(query) if hasattr(urllib, 'parse') else query.replace(' ', '+')
    try:
        import urllib.parse
        encoded = urllib.parse.quote_plus(query)
        url     = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        req     = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data    = json.loads(resp.read().decode())
            abstract = data.get("Abstract", "")
            answer   = data.get("Answer", "")
            related  = [r["Text"] for r in data.get("RelatedTopics", [])[:5] if "Text" in r]
    except Exception as e:
        return f"❌ Search failed: {e}"

    context = f"Query: {query}\n"
    if answer:
        context += f"Answer: {answer}\n"
    if abstract:
        context += f"Summary: {abstract}\n"
    if related:
        context += "Related:\n" + "\n".join(f"- {r}" for r in related)

    if not (answer or abstract or related):
        context += "(No direct results found)\n"

    prompt = f"""Based on this web search result, help the user with their question in the context of their codebase.

{context}

Workspace context:
{agent.code_context[:800]}"""

    print(f"\nAgent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /export ───────────────────────────────────────────────────────────────────

def cmd_export(agent, args: str) -> str:
    """
    Export the full conversation history to a markdown file.
    Usage: /export
           /export chat_log.md
    """
    filename = args.strip() or "chat_history.md"
    path     = os.path.join(agent.workspace, filename)

    turns  = agent.short_mem.get_turns(n=100)
    ltmem  = agent.long_mem.get_context(max_chars=5000)

    lines = [
        f"# AI Agent Chat History",
        f"Exported: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Workspace: {agent.workspace}",
        f"",
        f"---",
        f"",
    ]

    if ltmem:
        lines += ["## Long-term Memory", ltmem, "", "---", ""]

    lines.append("## Session Transcript")
    for i, turn in enumerate(turns):
        role    = "🧑 **You**" if turn["role"] == "user" else "🤖 **Agent**"
        content = turn["content"]
        lines.append(f"\n### {role}\n{content}\n")

    content = "\n".join(lines)
    try:
        Path(path).write_text(content, encoding="utf-8")
        return f"✅ Exported {len(turns)} turns to: {filename}"
    except Exception as e:
        return f"❌ Export failed: {e}"


# ── /config <key> <value> ─────────────────────────────────────────────────────

def cmd_config(agent, args: str) -> str:
    """
    View or change live settings without editing files.
    Usage: /config                    → show current settings
           /config gpu 15             → change GPU layers
           /config ctx 1024           → change context window
           /config model phi3:mini    → change local model
           /config tokens 256         → change max tokens
           /config backend groq       → switch backend (auto/local/groq)
    """
    import config.settings as S
    from core.llm import set_backend, get_backend

    parts = args.strip().split(maxsplit=1)

    if not parts:
        lines = [
            f"\n⚙️  Current Configuration",
            f"{'─'*40}",
            f"  Model (local) : {S.MODEL_NAME}",
            f"  Model (Groq)  : {S.GROQ_MODEL}",
            f"  Backend       : {get_backend()}",
            f"  Context window: {S.CONTEXT_WINDOW} tokens",
            f"  Max tokens    : {S.MAX_TOKENS}",
            f"  GPU layers    : {S.GPU_LAYERS}",
            f"  CPU threads   : {S.CPU_THREADS}",
            f"  Auto fallback : {S.AUTO_FALLBACK}",
            f"  Workspace     : {agent.workspace}",
        ]
        return "\n".join(lines)

    key = parts[0].lower()
    val = parts[1] if len(parts) > 1 else ""

    if not val:
        return f"Usage: /config {key} <value>"

    try:
        if key in ("gpu", "gpu_layers"):
            S.GPU_LAYERS = int(val)
            # Update Ollama options live
            from core.llm import OLLAMA_OPTIONS
            OLLAMA_OPTIONS["num_gpu"] = int(val)
            return f"✅ GPU layers set to {val}"
        elif key in ("ctx", "context", "context_window"):
            S.CONTEXT_WINDOW = int(val)
            from core.llm import OLLAMA_OPTIONS
            OLLAMA_OPTIONS["num_ctx"] = int(val)
            return f"✅ Context window set to {val}"
        elif key in ("tokens", "max_tokens"):
            S.MAX_TOKENS = int(val)
            from core.llm import OLLAMA_OPTIONS
            OLLAMA_OPTIONS["num_predict"] = int(val)
            return f"✅ Max tokens set to {val}"
        elif key == "model":
            S.MODEL_NAME = val
            return f"✅ Local model set to {val}\n   Note: restart agent to apply model change"
        elif key == "backend":
            if val not in ("auto", "local", "groq"):
                return "❌ Backend must be: auto | local | groq"
            set_backend(val)
            return f"✅ Backend switched to {val}"
        else:
            return f"❌ Unknown setting: {key}\nTry: gpu, ctx, tokens, model, backend"
    except ValueError:
        return f"❌ Invalid value: {val}"


# ── /benchmark ────────────────────────────────────────────────────────────────

def cmd_benchmark(agent, args: str) -> str:
    """
    Benchmark local vs Groq response speed side by side.
    Usage: /benchmark
    """
    import time
    from core.llm import _ollama_ask, _groq_ask, is_running, is_groq_available

    prompt  = "Write a Python function that checks if a number is prime. Include a docstring."
    results = []

    print("\n⏱️  Benchmarking LLM backends (this may take a minute)...\n")

    # Benchmark Ollama
    if is_running():
        print("  Testing local Ollama...", end="", flush=True)
        try:
            t0     = time.time()
            resp   = _ollama_ask(prompt)
            elapsed = time.time() - t0
            words  = len(resp.split())
            results.append(("Local (Ollama)", elapsed, words,
                            "✅", resp[:100]))
            print(f" {elapsed:.1f}s")
        except Exception as e:
            results.append(("Local (Ollama)", 0, 0, "❌", str(e)))
            print(f" FAILED")
    else:
        results.append(("Local (Ollama)", 0, 0, "⚠️", "Not running"))

    # Benchmark Groq
    if is_groq_available():
        print("  Testing Groq cloud...", end="", flush=True)
        try:
            t0      = time.time()
            resp    = _groq_ask(prompt)
            elapsed = time.time() - t0
            words   = len(resp.split())
            results.append(("Groq (cloud)", elapsed, words,
                            "✅", resp[:100]))
            print(f" {elapsed:.1f}s")
        except Exception as e:
            results.append(("Groq (cloud)", 0, 0, "❌", str(e)))
            print(f" FAILED")
    else:
        results.append(("Groq (cloud)", 0, 0, "⚠️", "No API key"))

    lines = [
        "",
        "📊 Benchmark Results",
        "─" * 50,
        f"  {'Backend':<20} {'Time':>8}  {'Words':>6}  Status",
        "─" * 50,
    ]
    for name, t, w, status, _ in results:
        t_str = f"{t:.1f}s" if t else "—"
        w_str = str(w) if w else "—"
        lines.append(f"  {name:<20} {t_str:>8}  {w_str:>6}  {status}")

    if len(results) == 2 and results[0][1] and results[1][1]:
        factor = results[0][1] / results[1][1]
        lines.append(f"\n  🏆 Groq is {factor:.1f}x faster than local")

    lines.append("\n  Tip: Use /model groq for speed, /model local for privacy")
    result = "\n".join(lines)
    print(result)
    return result


# ── /kb <subcommand> ──────────────────────────────────────────────────────────

def cmd_kb(agent, args: str) -> str:
    """
    Local knowledge base — index your own docs/PDFs/notes for the agent.
    Usage:
        /kb add <file|folder>   index document(s)
        /kb search <query>      search the knowledge base
        /kb list                list all indexed documents
        /kb clear               remove all indexed documents
        /kb                     show status
    """
    from tools.knowledge_base import kb_add, kb_search, kb_list, kb_clear, kb_stats

    parts  = args.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else ""
    rest   = parts[1] if len(parts) > 1 else ""

    if not subcmd:
        s = kb_stats()
        return (
            f"\n📚 Knowledge Base Status\n"
            f"{'─'*35}\n"
            f"  Indexed docs  : {s['docs']}\n"
            f"  Total chunks  : {s['chunks']}\n"
            f"\n  Commands:\n"
            f"  /kb add <file|folder>   → index documents\n"
            f"  /kb search <query>      → find relevant content\n"
            f"  /kb list                → show all indexed docs\n"
            f"  /kb clear               → clear all\n"
            f"\n  Supported: .txt .md .py .js .pdf .docx .json .csv .yaml"
        )

    if subcmd == "add":
        if not rest:
            return "Usage: /kb add <file or folder path>"
        path = os.path.join(agent.workspace, rest) if not os.path.isabs(rest) else rest
        return kb_add(path)

    if subcmd == "search":
        if not rest:
            return "Usage: /kb search <query>"
        results = kb_search(rest, max_results=5)
        if not results:
            return "🔍 No results found in knowledge base."
        lines = [f"\n🔍 Knowledge Base Search: '{rest}'\n{'─'*40}"]
        for i, r in enumerate(results, 1):
            src = os.path.basename(r["source"])
            lines.append(f"\n[{i}] From: {src}  (score: {r['score']})")
            lines.append(f"{r['text'][:300]}...")
        return "\n".join(lines)

    if subcmd == "list":
        return kb_list()

    if subcmd == "clear":
        return kb_clear()

    return f"❓ Unknown /kb subcommand: {subcmd}\nTry: add | search | list | clear"


# ── /clip <on|off|status> ─────────────────────────────────────────────────────

def cmd_clip(agent, args: str) -> str:
    """
    Clipboard monitor — auto-review any code you copy.
    Usage:
        /clip on      start monitoring clipboard
        /clip off     stop monitoring
        /clip         show current status
    """
    action = args.strip().lower()

    if action == "on":
        if not agent._clip_monitor.is_enabled:
            agent._clip_monitor.toggle()
        return (
            "📋 Clipboard monitor ON\n"
            "   Copy any code snippet and the agent will auto-review it.\n"
            "   Type /clip off to disable."
        )

    if action == "off":
        if agent._clip_monitor.is_enabled:
            agent._clip_monitor.toggle()
        return "📋 Clipboard monitor OFF"

    # Status
    state  = "ON 🟢" if agent._clip_monitor.is_enabled else "OFF 🔴"
    return (
        f"\n📋 Clipboard Monitor: {state}\n"
        f"   /clip on    → enable auto-review of copied code\n"
        f"   /clip off   → disable\n"
        f"\n   When ON: copy any code snippet from your browser, editor,\n"
        f"   or Stack Overflow — the agent reviews it instantly."
    )


# ── /digest ───────────────────────────────────────────────────────────────────

def cmd_digest(agent, args: str) -> str:
    """
    Show the daily digest (git activity, modified files, memory summary).
    Usage: /digest
    """
    from agent.daily_digest import show_digest
    shown = show_digest(agent, force=True)
    return "" if shown else "❌ Could not generate digest."


# ── /time ─────────────────────────────────────────────────────────────────────

def cmd_time(agent, args: str) -> str:
    """
    Show session duration and task statistics.
    Usage: /time
    """
    import time as _time
    from tools.terminal_tools import run_command

    elapsed = int(_time.time() - agent._session_start)
    h, rem  = divmod(elapsed, 3600)
    m, s    = divmod(rem, 60)

    # Git activity in this session
    r = run_command("git log --oneline -5 --since='8 hours ago'", cwd=agent.workspace)
    recent_commits = (r.get("stdout") or "").strip()

    lines = [
        f"\n⏱️  Session Statistics",
        f"{'─'*40}",
        f"  Duration    : {h:02d}h {m:02d}m {s:02d}s",
        f"  Tasks run   : {agent._task_count}",
        f"  Chat turns  : {len(agent.short_mem)}",
        f"  Backend     : {__import__('core.llm', fromlist=['get_backend']).get_backend()}",
        f"  Clip monitor: {'ON 🟢' if agent._clip_monitor.is_enabled else 'OFF 🔴'}",
    ]

    if recent_commits:
        lines.append(f"\n  Recent commits (this session):")
        for line in recent_commits.splitlines():
            lines.append(f"    • {line}")

    from core.llm import get_stats
    st = get_stats()
    lines += [
        f"\n  LLM Calls:",
        f"    Ollama calls : {st['ollama_calls']}",
        f"    Groq calls   : {st['groq_calls']}",
        f"    Cache hits   : {st['cache_hits']} (avoided {st['cache_hits']} API calls)",
    ]

    return "\n".join(lines)
