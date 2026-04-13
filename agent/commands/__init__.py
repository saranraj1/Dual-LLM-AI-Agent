"""
agent/commands/__init__.py

Single import surface for all agent commands.
Exports every command so agent.py can do a single clean import.

Legacy commands (cmd_diff, cmd_history, cmd_undo, cmd_explain,
cmd_test, cmd_fix, cmd_todo) come from agent.cmd_legacy.
New modular commands come from the sub-modules in this package.
"""

# ── Legacy core commands (agent/cmd_legacy.py) ────────────────────────────────
from agent.cmd_legacy import (
    cmd_diff,
    cmd_history,
    cmd_undo,
    cmd_explain,
    cmd_test,
    cmd_fix,
    cmd_todo,
)

# ── Code-quality commands (agent/commands/code_quality.py) ────────────────────
from agent.commands.code_quality import (
    cmd_review,
    cmd_optimize,
    cmd_refactor,
    cmd_security,
    cmd_format,
    cmd_lint,
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
    cmd_explain as _cmd_explain_new,   # alias — cmd_explain above takes precedence
    cmd_diff    as _cmd_diff_new,
    cmd_undo    as _cmd_undo_new,
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
)

# ── Local machine commands (agent/commands/local.py) ──────────────────────────
from agent.commands.local import (
    cmd_kb,
    cmd_clip,
    cmd_digest,
    cmd_time,
)

__all__ = [
    # Legacy
    "cmd_diff", "cmd_history", "cmd_undo", "cmd_explain",
    "cmd_test", "cmd_fix", "cmd_todo",
    # Code quality
    "cmd_review", "cmd_optimize", "cmd_refactor", "cmd_security",
    "cmd_format", "cmd_lint",
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
