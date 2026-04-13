"""agent/commands_base.py — Shared backup utility used by all command modules."""

import os
import shutil


def _backup_file(path: str, workspace: str) -> bool:
    """Back up a file before the agent overwrites it. Returns True if successful."""
    if not os.path.exists(path):
        return False
    backup_dir = os.path.join(workspace, ".agent_backups")
    os.makedirs(backup_dir, exist_ok=True)
    # Use relative path as backup filename to avoid collisions
    try:
        rel = os.path.relpath(path, workspace)
    except ValueError:
        rel = os.path.basename(path)
    safe_name = rel.replace(os.sep, "_") + ".bak"
    backup_path = os.path.join(backup_dir, safe_name)
    try:
        shutil.copy2(path, backup_path)
        return True
    except Exception:
        return False
