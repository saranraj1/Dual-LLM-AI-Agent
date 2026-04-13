"""agent/commands/project.py — /docs /git /summarize /changelog /stats /deps /diagram /scaffold"""

import os
import re
import sys
import json
from pathlib import Path
from core.llm import ask, ask_stream
from core.prompt_builder import SYSTEM_PROMPT
from tools.file_tools import read_file, scan_codebase, build_context_string, list_dir
from tools.terminal_tools import run_command
from config.settings import SKIP_DIRS, SUPPORTED_EXTENSIONS

SCAFFOLD_TYPES = {
    "flask-api":   "Flask REST API with blueprints, SQLAlchemy, JWT auth, error handlers",
    "fastapi":     "FastAPI with Pydantic models, async routes, OpenAPI docs, SQLAlchemy",
    "react-app":   "React app with components, hooks, routing, API service layer",
    "cli-tool":    "Python CLI tool with argparse, config file, logging, tests",
    "discord-bot": "Discord.py bot with commands, events, cog structure",
    "scraper":     "Web scraper with requests/BeautifulSoup, rate limiting, data export",
    "ml-project":  "ML project with data loading, preprocessing, model training, evaluation",
}


# ── /docs ────────────────────────────────────────────────────────────────────

def cmd_docs(agent, args: str) -> str:
    target = args.strip()

    # ── /docs api — auto-generate API reference ───────────────────────────────
    if target.lower() == "api":
        return _cmd_docs_api(agent)

    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r = read_file(path)
        if not r["ok"]:
            return f"❌ Cannot read {target}: {r['error']}"
        prompt = f"""Add complete docstrings to every function, class, and module in this file.
Use Google-style docstrings with Args, Returns, Raises, and Example sections.
Return the COMPLETE file with docstrings added using FILE: {target} format.

```python
{r['content'][:2500]}
```"""
        print("\n📝 Adding docstrings...")
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
            print(f"   ✅ Documented: {written}")
        return response
    else:
        print("\n📚 Generating README.md...")
        scan = scan_codebase(agent.workspace)
        context = build_context_string(scan, char_limit=2000) if scan["ok"] else agent.code_context
        tree = list_dir(agent.workspace, depth=2)
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
            print(f"   ✅ Created: {written}")
        return response


# ── /docs api (Feature 12) ────────────────────────────────────────────────────

def _cmd_docs_api(agent) -> str:
    """
    Scan the workspace for Flask/FastAPI routes and generate:
      docs/api.md       — Markdown API reference with method badges
      docs/openapi.yaml — OpenAPI 3.0 YAML spec
    """
    from tools.api_doc_scanner import generate_api_docs

    print("\n🔍 Scanning for API routes (Flask / FastAPI / Django)...")
    result = generate_api_docs(agent.workspace, project_name=Path(agent.workspace).name.title())

    if result["endpoints_found"] == 0:
        return (
            "⚠️  No API routes detected.\n"
            "   Supported frameworks: Flask (@app.route), FastAPI (@app.get), Django (urlpatterns)\n"
            "   Make sure route decorators are used in your Python files."
        )

    print(result["summary"])

    # ── Write docs/api.md ─────────────────────────────────────────────────────
    docs_dir = Path(agent.workspace) / "docs"
    docs_dir.mkdir(exist_ok=True)

    md_path   = docs_dir / "api.md"
    yaml_path = docs_dir / "openapi.yaml"

    md_path.write_text(result["markdown"],    encoding="utf-8")
    yaml_path.write_text(result["openapi_yaml"], encoding="utf-8")

    print(f"   ✅ Written: docs/api.md")
    print(f"   ✅ Written: docs/openapi.yaml")

    # ── AI enhancement pass — add descriptions from codebase context ──────────
    print("\n🤖 Asking AI to enrich endpoint descriptions...")
    sample = result["markdown"][:1500]
    prompt = f"""You are a technical writer. Below is an auto-generated API reference.
Enhance the descriptions: explain what each endpoint does, what params mean, and what the response looks like.
Keep the exact Markdown format and table structure. Only improve the text — don't add new endpoints.

{sample}"""
    print("Agent › ", end="", flush=True)
    enriched = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        enriched += token
    print()

    # Replace the Markdown file with the enriched version
    if len(enriched) > 200:
        md_path.write_text(enriched, encoding="utf-8")
        print("   ✅ AI-enriched docs/api.md")

    return (
        f"\n✅ API docs generated!\n"
        f"{result['summary']}\n"
        f"\n   📄 docs/api.md       — Markdown reference\n"
        f"   📋 docs/openapi.yaml — OpenAPI 3.0 spec (import into Swagger UI, Postman, Insomnia)\n"
        f"\n   💡 Tip: serve Swagger UI with:\n"
        f"      npx swagger-ui-cli serve docs/openapi.yaml"
    )


# ── /git ─────────────────────────────────────────────────────────────────────

def cmd_git(agent, args: str) -> str:
    action = args.strip()
    cwd = agent.workspace
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

    if not action or action_lower == "auto":
        diff_r = run_command("git diff --stat HEAD", cwd=cwd)
        status_r = run_command("git status --short", cwd=cwd)
        changed = (diff_r["stdout"] or "") + "\n" + (status_r["stdout"] or "")
        if not changed.strip():
            return "Nothing to commit."
        msg_prompt = f"""Write a concise, conventional git commit message for these changes.
Format: <type>(<scope>): <description>
Types: feat, fix, docs, refactor, test, chore
Keep it under 72 characters. Just output the message, nothing else.

Changes:
{changed[:800]}"""
        print("🤖 Generating commit message...")
        print("Agent › ", end="", flush=True)
        full = ""
        for token in ask_stream(msg_prompt):
            print(token, end="", flush=True)
            full += token
        print()
        commit_msg = full.strip().strip('"').strip("'")
        print(f"   Message: {commit_msg}")
    else:
        commit_msg = action

    results = []
    r1 = run_command("git add -A", cwd=cwd)
    results.append(f"git add: {'ok' if r1['ok'] else r1['stderr']}")
    r2 = run_command(f'git commit -m "{commit_msg}"', cwd=cwd)
    results.append(f"git commit: {r2['stdout'][:100] if r2['ok'] else r2['stderr'][:100]}")
    return "\n".join(results)


# ── /summarize ────────────────────────────────────────────────────────────────

def cmd_summarize(agent, args: str) -> str:
    target = args.strip()
    if target:
        path = os.path.join(agent.workspace, target) if not os.path.isabs(target) else target
        r = read_file(path)
        if not r["ok"]:
            return f"❌ Cannot read {target}: {r['error']}"
        context = f"File: {target}\n```\n{r['content'][:2500]}\n```"
        scope = f"the file {target}"
    else:
        tree = list_dir(agent.workspace, depth=2)
        tree_str = "\n".join(e["path"] for e in tree["entries"][:30]) if tree["ok"] else ""
        context = f"Structure:\n{tree_str}\n\nCode:\n{agent.code_context[:2000]}"
        scope = "this entire project"

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
    r = run_command("git log --oneline --no-merges -50", cwd=agent.workspace)
    if not r["ok"] or not r["stdout"]:
        return "❌ No git history found. Initialize git first with: git init"
    prompt = f"""Generate a professional CHANGELOG.md from these git commits.

Group changes by type: Added, Changed, Fixed, Removed, Security.
Use semantic versioning sections if you can detect version bumps.
Use FILE: CHANGELOG.md format.

Git log:
{r['stdout']}"""
    print("\n📋 Generating CHANGELOG...")
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
        print(f"   ✅ Created: {written}")
    return response


# ── /stats ────────────────────────────────────────────────────────────────────

def cmd_stats(agent, args: str) -> str:
    root = Path(agent.workspace)
    stats = {"total_files": 0, "total_lines": 0, "total_chars": 0, "by_extension": {}, "empty_files": 0}
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
            lines = content.count("\n") + 1
            chars = len(content)
            ext = fp.suffix.lower() or ".txt"
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
    root = Path(agent.workspace)
    imports = {}
    stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()

    for fp in root.rglob("*.py"):
        if any(s in fp.parts for s in SKIP_DIRS):
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            found = re.findall(r'^(?:import|from)\s+([\w.]+)', content, re.MULTILINE)
            rel = str(fp.relative_to(root))
            for imp in found:
                top = imp.split(".")[0]
                if top not in imports:
                    imports[top] = []
                imports[top].append(rel)
        except Exception:
            continue

    third_party = {k: v for k, v in imports.items() if k not in stdlib and k not in ("__future__", "")}
    pkg_list = ", ".join(third_party.keys())
    r = run_command("pip list --format=json", cwd=agent.workspace)
    installed = {}
    if r["ok"]:
        try:
            pkgs = json.loads(r["stdout"])
            installed = {p["name"].lower(): p["version"] for p in pkgs}
        except Exception:
            pass

    out = [f"\n📦 Dependency Analysis", f"{'─'*40}", f"\n  Third-party imports ({len(third_party)}):"]
    for pkg, files in sorted(third_party.items()):
        ver = installed.get(pkg.lower(), "not installed")
        status = "✅" if pkg.lower() in installed else "❌"
        out.append(f"  {status} {pkg:<20} {ver}  (used in {len(files)} file(s))")

    print("Agent › ", end="", flush=True)
    suggestion = ""
    for token in ask_stream(
        f"Given these Python dependencies: {pkg_list}\n"
        f"List any outdated/deprecated packages with modern replacements. Be brief."
    ):
        print(token, end="", flush=True)
        suggestion += token
    print()
    out.append(f"\n  💡 Suggestions:\n{suggestion[:400]}")
    return "\n".join(out)


# ── /diagram ──────────────────────────────────────────────────────────────────

def cmd_diagram(agent, args: str) -> str:
    tree = list_dir(agent.workspace, depth=3)
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
        os.makedirs(os.path.join(agent.workspace, "docs"), exist_ok=True)
        written = _auto_write_files(blocks, agent.workspace)
        print(f"   ✅ Saved: {written}")
    print(response)
    return response


# ── /scaffold ─────────────────────────────────────────────────────────────────

def cmd_scaffold(agent, args: str) -> str:
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
