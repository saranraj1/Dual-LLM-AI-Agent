"""
agent/daily_digest.py — Morning startup digest.

Shown once per day on agent startup. Includes:
  - Yesterday's git commits
  - Files modified in the last 24h
  - Long-term memory summary of recent work
  - Groq/Ollama backend status
  - Project stats snapshot
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from tools.terminal_tools import run_command
from core.ui import C


_DIGEST_STAMP = Path.home() / ".ai_agent" / "last_digest.txt"


def _already_shown_today() -> bool:
    if not _DIGEST_STAMP.exists():
        return False
    try:
        last = _DIGEST_STAMP.read_text().strip()
        return last == datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False


def _mark_shown():
    _DIGEST_STAMP.parent.mkdir(parents=True, exist_ok=True)
    _DIGEST_STAMP.write_text(datetime.now().strftime("%Y-%m-%d"))


def _git_yesterday(cwd: str) -> str:
    """Get git commits from the last 24 hours."""
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    r = run_command(
        f'git log --oneline --since="{since}" --no-merges',
        cwd=cwd
    )
    return (r.get("stdout") or "").strip()


def _recently_modified(cwd: str, hours: int = 24) -> list:
    """List files modified in the last N hours."""
    root  = Path(cwd)
    cutoff = datetime.now().timestamp() - hours * 3600
    files  = []
    skip   = {"__pycache__", ".git", "venv", ".venv", "node_modules"}
    for f in root.rglob("*"):
        if f.is_file() and not any(s in f.parts for s in skip):
            try:
                if f.stat().st_mtime > cutoff:
                    files.append(str(f.relative_to(root)))
            except Exception:
                pass
    return sorted(files)[:15]


def _long_mem_recent(agent) -> str:
    """Get recent summary from long-term memory."""
    try:
        return agent.long_mem.get_context(max_chars=300)
    except Exception:
        return ""


def show_digest(agent, force: bool = False) -> bool:
    """
    Show the daily digest. Returns True if digest was shown.
    Skips if already shown today (unless force=True).
    """
    if not force and _already_shown_today():
        return False

    cwd  = agent.workspace
    now  = datetime.now()
    hr   = now.hour
    greeting = (
        "Good morning" if 5 <= hr < 12 else
        "Good afternoon" if 12 <= hr < 17 else
        "Good evening"
    )

    lines = [
        f"\n{C.BOLD}{C.MAGENTA}{'━'*58}{C.RESET}",
        f"{C.BOLD}{C.MAGENTA}  📅  Daily Digest — {now.strftime('%A, %d %b %Y  %H:%M')}{C.RESET}",
        f"{C.BOLD}{C.MAGENTA}{'━'*58}{C.RESET}",
    ]

    # Greeting
    lines.append(f"\n  {C.CYAN}{greeting}! Here's what's happening:{C.RESET}\n")

    # Git activity
    commits = _git_yesterday(cwd)
    if commits:
        lines.append(f"  {C.YELLOW}📝 Git commits (last 24h):{C.RESET}")
        for line in commits.splitlines()[:8]:
            lines.append(f"     {C.GRAY}• {line}{C.RESET}")
    else:
        lines.append(f"  {C.GRAY}📝 No git commits in the last 24 hours{C.RESET}")

    # Modified files
    modified = _recently_modified(cwd)
    if modified:
        lines.append(f"\n  {C.YELLOW}🔧 Recently modified files:{C.RESET}")
        for f in modified[:8]:
            lines.append(f"     {C.GRAY}• {f}{C.RESET}")
        if len(modified) > 8:
            lines.append(f"     {C.GRAY}  ... and {len(modified)-8} more{C.RESET}")
    else:
        lines.append(f"\n  {C.GRAY}🔧 No files modified recently{C.RESET}")

    # Memory context
    mem = _long_mem_recent(agent)
    if mem:
        lines.append(f"\n  {C.YELLOW}🧠 Recent work (from memory):{C.RESET}")
        for ln in mem.splitlines()[:4]:
            lines.append(f"     {C.GRAY}{ln}{C.RESET}")

    # KB stats
    try:
        from tools.knowledge_base import kb_stats
        kbs = kb_stats()
        if kbs["docs"] > 0:
            lines.append(f"\n  {C.YELLOW}📚 Knowledge base:{C.RESET} {C.GRAY}{kbs['docs']} docs · {kbs['chunks']} chunks indexed{C.RESET}")
    except Exception:
        pass

    # Quick tips
    tip_pool = [
        "/benchmark  → compare local vs Groq speed",
        "/clip on    → auto-review any code you copy",
        "/kb add .   → index this project's docs",
        "/model groq → switch to 70B cloud model",
        "/export     → save this conversation",
        "/scaffold   → generate a full project",
    ]
    import random
    tip = random.choice(tip_pool)
    lines.append(f"\n  {C.DIM if hasattr(C, 'DIM') else ''}💡 Tip: {tip}{C.RESET}")

    lines.append(f"\n{C.BOLD}{C.MAGENTA}{'━'*58}{C.RESET}\n")

    print("\n".join(lines))
    _mark_shown()
    return True
