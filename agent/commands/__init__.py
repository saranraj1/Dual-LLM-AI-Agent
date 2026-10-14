"""
agent/commands/__init__.py

Single import surface for all agent commands.
Exports every command cleanly so agent.py can do a single import.
"""

# ── Code-quality commands (agent/commands/code_quality.py) ────────────────────
from agent.commands.code_quality import (
    cmd_review,
    cmd_optimize,
    cmd_refactor,
    cmd_security,
    cmd_format,
    cmd_lint,
    cmd_test,
    cmd_fix,
    cmd_todo,
    cmd_tdd,
    cmd_blast,
)

# ── Project commands (agent/commands/project.py) ──────────────────────────────
from agent.commands.project import (
    cmd_docs,
    cmd_git,
    cmd_summarize,
    cmd_changelog,
    cmd_stats,
    cmd_deps,
    cmd_diagram,
    cmd_scaffold,
)

# ── File commands (agent/commands/files.py) ───────────────────────────────────
from agent.commands.files import (
    cmd_explain,
    cmd_diff,
    cmd_undo,
    cmd_run_file,
    cmd_translate,
)

# ── Web commands (agent/commands/web.py) ──────────────────────────────────────
from agent.commands.web import (
    cmd_ask_url,
    cmd_search,
)

# ── Settings commands (agent/commands/settings.py) ────────────────────────────
from agent.commands.settings import (
    cmd_mode,
    cmd_export,
    cmd_config,
    cmd_benchmark,
    cmd_history,
)

# ── Local machine commands (agent/commands/local.py) ──────────────────────────
from agent.commands.local import (
    cmd_kb,
    cmd_clip,
    cmd_digest,
    cmd_time,
)

__all__ = [
    # Core / files
    "cmd_diff", "cmd_history", "cmd_undo", "cmd_explain",
    # Code quality
    "cmd_review", "cmd_optimize", "cmd_refactor", "cmd_security",
    "cmd_format", "cmd_lint", "cmd_test", "cmd_fix", "cmd_todo",
    "cmd_tdd", "cmd_blast",
    # Project
    "cmd_docs", "cmd_git", "cmd_summarize", "cmd_changelog",
    "cmd_stats", "cmd_deps", "cmd_diagram", "cmd_scaffold",
    # Files
    "cmd_run_file", "cmd_translate",
    # Web
    "cmd_ask_url", "cmd_search",
    # Settings
    "cmd_mode", "cmd_export", "cmd_config", "cmd_benchmark",
    # Local
    "cmd_kb", "cmd_clip", "cmd_digest", "cmd_time",
]

