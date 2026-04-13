"""
tools/terminal_tools.py — Cross-platform shell command execution (Step 4).

- Uses `bash` on macOS/Linux, PowerShell-compatible `shell=True` on Windows
- All paths use pathlib.Path instead of hardcoded C:\\ strings
- Guards against dangerous commands
- Timeout protected
"""

import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional
from config.settings import ALLOW_SHELL, SHELL_TIMEOUT

# Commands that are never allowed regardless of settings
BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf ~", ":(){ :|:& };:",   # destructive
    "dd if=", "mkfs",                            # disk ops
    "shutdown", "reboot", "halt",                # system
    "curl | bash", "wget | bash",                # blind exec
}

WARN_PATTERNS = ["sudo", "chmod 777", "chown", "passwd", "rm -rf"]

_IS_WINDOWS = sys.platform == "win32"


def _is_blocked(cmd: str) -> bool:
    low = cmd.lower()
    return any(b in low for b in BLOCKED_COMMANDS)


def _has_warnings(cmd: str) -> List[str]:
    low = cmd.lower()
    return [w for w in WARN_PATTERNS if w in low]


def _resolve_cwd(cwd: Optional[str]) -> str:
    """Resolve cwd, always returning an absolute path string."""
    if cwd is None:
        return str(Path.cwd())
    return str(Path(cwd).expanduser().resolve())


def run_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = SHELL_TIMEOUT,
    env_extra: Optional[dict] = None,
) -> Dict:
    """
    Run a shell command safely. Returns:
        {ok, stdout, stderr, exit, warnings}

    On Windows: uses shell=True (cmd.exe / PowerShell compatible).
    On macOS/Linux: uses bash -c for consistent behaviour.
    """
    if not ALLOW_SHELL:
        return {
            "ok": False, "stdout": "", "exit": -1,
            "stderr": "Shell disabled (ALLOW_SHELL=False in settings.py)",
            "warnings": [],
        }

    if _is_blocked(command):
        return {
            "ok": False, "stdout": "", "exit": -1,
            "stderr": "Blocked: dangerous command pattern detected.",
            "warnings": [],
        }

    warnings = _has_warnings(command)
    resolved_cwd = _resolve_cwd(cwd)

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    try:
        if _IS_WINDOWS:
            # Windows — shell=True uses cmd.exe; handles git, pip, python fine
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=resolved_cwd,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
        else:
            # macOS / Linux — explicit bash for consistency
            proc = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=resolved_cwd,
                env=env,
                encoding="utf-8",
                errors="replace",
            )

        return {
            "ok":       proc.returncode == 0,
            "stdout":   proc.stdout.strip()[:2000],
            "stderr":   proc.stderr.strip()[:500],
            "exit":     proc.returncode,
            "warnings": warnings,
        }

    except subprocess.TimeoutExpired:
        return {
            "ok": False, "stdout": "", "exit": -1,
            "stderr": f"Command timed out after {timeout}s",
            "warnings": warnings,
        }
    except FileNotFoundError as e:
        return {
            "ok": False, "stdout": "", "exit": -1,
            "stderr": f"Command not found: {e}",
            "warnings": warnings,
        }
    except Exception as e:
        from core.exceptions import ShellToolError
        return {
            "ok": False, "stdout": "", "exit": -1,
            "stderr": f"Shell error: {e}",
            "warnings": warnings,
        }


def run_commands(commands: List[str], cwd: Optional[str] = None) -> List[Dict]:
    """Run multiple commands in sequence. Stops on first failure."""
    results = []
    for cmd in commands:
        r = run_command(cmd, cwd=cwd)
        results.append({"command": cmd, **r})
        if not r["ok"]:
            break
    return results


def get_git_status(cwd: str = ".") -> Dict:
    """Convenience: get git status of a directory."""
    return run_command("git status --short", cwd=cwd)


def get_python_version() -> str:
    cmd = "python --version" if _IS_WINDOWS else "python3 --version"
    r = run_command(cmd)
    return r.get("stdout") or r.get("stderr") or "unknown"
