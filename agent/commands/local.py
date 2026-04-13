"""agent/commands/local.py — /kb /clip /digest /time"""

import os
import time as _time


# ── /kb ───────────────────────────────────────────────────────────────────────

def cmd_kb(agent, args: str) -> str:
    from tools.knowledge_base import kb_add, kb_search, kb_list, kb_clear, kb_stats

    parts = args.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

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


# ── /clip ─────────────────────────────────────────────────────────────────────

def cmd_clip(agent, args: str) -> str:
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

    state = "ON 🟢" if agent._clip_monitor.is_enabled else "OFF 🔴"
    return (
        f"\n📋 Clipboard Monitor: {state}\n"
        f"   /clip on    → enable auto-review of copied code\n"
        f"   /clip off   → disable\n"
        f"\n   When ON: copy any code snippet from your browser, editor,\n"
        f"   or Stack Overflow — the agent reviews it instantly."
    )


# ── /digest ───────────────────────────────────────────────────────────────────

def cmd_digest(agent, args: str) -> str:
    from agent.daily_digest import show_digest
    shown = show_digest(agent, force=True)
    return "" if shown else "❌ Could not generate digest."


# ── /time ─────────────────────────────────────────────────────────────────────

def cmd_time(agent, args: str) -> str:
    from tools.terminal_tools import run_command

    elapsed = int(_time.time() - agent._session_start)
    h, rem = divmod(elapsed, 3600)
    m, s = divmod(rem, 60)

    r = run_command("git log --oneline -5 --since='8 hours ago'", cwd=agent.workspace)
    recent_commits = (r.get("stdout") or "").strip()

    from core.llm import get_backend, get_stats
    lines = [
        f"\n⏱️  Session Statistics",
        f"{'─'*40}",
        f"  Duration    : {h:02d}h {m:02d}m {s:02d}s",
        f"  Tasks run   : {agent._task_count}",
        f"  Chat turns  : {len(agent.short_mem)}",
        f"  Backend     : {get_backend()}",
        f"  Clip monitor: {'ON 🟢' if agent._clip_monitor.is_enabled else 'OFF 🔴'}",
    ]

    if recent_commits:
        lines.append(f"\n  Recent commits (this session):")
        for line in recent_commits.splitlines():
            lines.append(f"    • {line}")

    st = get_stats()
    lines += [
        f"\n  LLM Calls:",
        f"    Ollama calls : {st['ollama_calls']}",
        f"    Groq calls   : {st['groq_calls']}",
        f"    Cache hits   : {st['cache_hits']} (avoided {st['cache_hits']} API calls)",
    ]
    return "\n".join(lines)
