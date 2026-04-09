"""
tools/terminal_tools.py — Execute shell commands safely.
Guards against dangerous commands. Timeout protected.
"""

import subprocess
import shlex
import os
from typing import Dict, List
from config.settings import ALLOW_SHELL, SHELL_TIMEOUT

# Commands that are never allowed regardless of settings
BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf ~", ":(){ :|:& };:",   # destructive
    "dd if=", "mkfs",                            # disk ops
    "shutdown", "reboot", "halt",                # system
    "curl | bash", "wget | bash",                # blind exec
}

WARN_PATTERNS = ["sudo", "chmod 777", "chown", "passwd", "rm -rf"]


def _is_blocked(cmd: str) -> bool:
    low = cmd.lower()
    return any(b in low for b in BLOCKED_COMMANDS)


def _has_warnings(cmd: str) -> List[str]:
    low = cmd.lower()
    return [w for w in WARN_PATTERNS if w in low]


def run_command(
    command: str,
    cwd: str = None,
    timeout: int = SHELL_TIMEOUT,
    env_extra: dict = None
) -> Dict:
    """
    Run a shell command. Returns stdout, stderr, exit code.
    cwd defaults to current directory if None.
    """
    if not ALLOW_SHELL:
        return {"ok": False, "stdout": "", "stderr": "Shell disabled (ALLOW_SHELL=False in settings.py)"}

    if _is_blocked(command):
        return {"ok": False, "stdout": "", "stderr": f"Blocked: dangerous command pattern detected."}

    warnings = _has_warnings(command)

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or os.getcwd(),
            env=env
        )
        return {
            "ok":       result.returncode == 0,
            "stdout":   result.stdout.strip()[:2000],
            "stderr":   result.stderr.strip()[:500],
            "exit":     result.returncode,
            "warnings": warnings
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timed out after {timeout}s", "exit": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit": -1}


def run_commands(commands: List[str], cwd: str = None) -> List[Dict]:
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
    r = run_command("python --version")
    return r.get("stdout") or r.get("stderr") or "unknown"
