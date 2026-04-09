"""
tools/code_tools.py — Execute Python code in a subprocess sandbox.
Captures stdout, stderr, and exit code. Timeout protected.
"""

import subprocess
import sys
import tempfile
import os
from typing import Dict
from config.settings import SHELL_TIMEOUT


def run_python(code: str, timeout: int = SHELL_TIMEOUT, cwd: str = None) -> Dict:
    """
    Execute a Python snippet and return its output.
    Runs in a temp file to avoid polluting the current namespace.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )
        return {
            "ok":     result.returncode == 0,
            "stdout": result.stdout.strip()[:2000],
            "stderr": result.stderr.strip()[:500],
            "exit":   result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timed out after {timeout}s", "exit": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit": -1}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def run_python_file(path: str, args: list = None, timeout: int = SHELL_TIMEOUT) -> Dict:
    """Run an existing Python file."""
    cmd = [sys.executable, path] + (args or [])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "ok":     result.returncode == 0,
            "stdout": result.stdout.strip()[:2000],
            "stderr": result.stderr.strip()[:500],
            "exit":   result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timed out ({timeout}s)", "exit": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit": -1}


def install_package(package: str) -> Dict:
    """Install a Python package via pip."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package, "-q"],
            capture_output=True, text=True, timeout=60
        )
        return {
            "ok":     result.returncode == 0,
            "stdout": result.stdout.strip()[-500:],
            "stderr": result.stderr.strip()[-200:],
        }
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}


def lint_python(code: str) -> Dict:
    """
    Basic syntax check on a Python snippet using compile().
    No external dependencies needed.
    """
    try:
        compile(code, "<string>", "exec")
        return {"ok": True, "error": None}
    except SyntaxError as e:
        return {"ok": False, "error": f"SyntaxError at line {e.lineno}: {e.msg}"}
