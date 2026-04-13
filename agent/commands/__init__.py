"""agent/commands/__init__.py — Re-exports every command so existing imports don't break."""

from agent.commands.code_quality import (
    cmd_review, cmd_optimize, cmd_refactor, cmd_security,
    cmd_format, cmd_lint,
)
from agent.commands.project import (
    cmd_docs, cmd_git, cmd_summarize, cmd_changelog,
    cmd_stats, cmd_deps, cmd_diagram, cmd_scaffold,
)
from agent.commands.files import (
    cmd_explain, cmd_diff, cmd_undo, cmd_run_file, cmd_translate,
)
from agent.commands.web import (
    cmd_ask_url, cmd_search,
)
from agent.commands.settings import (
    cmd_mode, cmd_export, cmd_config, cmd_benchmark,
)
from agent.commands.local import (
    cmd_kb, cmd_clip, cmd_digest, cmd_time,
)

__all__ = [
    "cmd_review", "cmd_optimize", "cmd_refactor", "cmd_security",
    "cmd_format", "cmd_lint",
    "cmd_docs", "cmd_git", "cmd_summarize", "cmd_changelog",
    "cmd_stats", "cmd_deps", "cmd_diagram", "cmd_scaffold",
    "cmd_explain", "cmd_diff", "cmd_undo", "cmd_run_file", "cmd_translate",
    "cmd_ask_url", "cmd_search",
    "cmd_mode", "cmd_export", "cmd_config", "cmd_benchmark",
    "cmd_kb", "cmd_clip", "cmd_digest", "cmd_time",
]
