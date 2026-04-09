"""
agent/watcher.py — /watch command.
Monitors your project for file changes and automatically
reviews/suggests improvements as you save files.
Run with: /watch
Stop with: Ctrl+C
"""

import os
import time
import threading
from pathlib import Path
from typing import Dict
from config.settings import SUPPORTED_EXTENSIONS, SKIP_DIRS
from tools.file_tools import read_file
from core.llm import ask
from core.prompt_builder import SYSTEM_PROMPT


def _get_mtimes(root: str) -> Dict[str, float]:
    """Return {filepath: mtime} for all tracked files."""
    mtimes = {}
    for fp in Path(root).rglob("*"):
        if not fp.is_file():
            continue
        if any(s in fp.parts for s in SKIP_DIRS):
            continue
        if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            mtimes[str(fp)] = fp.stat().st_mtime
        except Exception:
            pass
    return mtimes


def _review_file(filepath: str, workspace: str):
    """Quick review of a changed file."""
    r = read_file(filepath)
    if not r["ok"]:
        return

    rel     = os.path.relpath(filepath, workspace)
    content = r["content"][:2000]

    prompt = f"""A file was just saved: {rel}
Do a quick 3-point review:
1. Any bugs or errors?
2. Any obvious improvements?
3. Any security issues?

If everything looks fine, just say "✅ Looks good."
Keep it under 5 lines total.

```
{content}
```"""

    response = ask(prompt, system=SYSTEM_PROMPT)
    print(f"\n👁️  [{rel}] changed")
    print(f"   {response.strip()}\n")


def cmd_watch(agent, args: str) -> str:
    """
    Watch workspace for file changes and auto-review on save.
    Usage: /watch
    Stop with Ctrl+C
    """
    root = agent.workspace
    print(f"\n👁️  Watching: {root}")
    print("   Agent will review files as you save them.")
    print("   Press Ctrl+C to stop.\n")

    try:
        mtimes = _get_mtimes(root)
        while True:
            time.sleep(2)
            new_mtimes = _get_mtimes(root)

            # Detect changed or new files
            for fpath, mtime in new_mtimes.items():
                old_mtime = mtimes.get(fpath, 0)
                if mtime > old_mtime:
                    # File was modified or is new
                    _review_file(fpath, root)

            mtimes = new_mtimes

    except KeyboardInterrupt:
        print("\n👁️  Watch mode stopped.")
        return "Watch stopped."