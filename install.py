"""
install.py — One-time global setup for the AI Agent.
Run this ONCE after placing the agent folder anywhere on your system.

Usage:
  python install.py

What it does:
  1. Detects your OS
  2. Writes shell aliases / PowerShell functions for global access
  3. Patches vscode/tasks.json with the correct absolute path
  4. Creates ~/.ai_agent/ memory directory
  5. Prints next steps
"""

import os
import sys
import platform
import subprocess
from pathlib import Path

AGENT_DIR  = Path(__file__).resolve().parent
VSCODE_TASKS = AGENT_DIR / "vscode" / "tasks.json"

def patch_tasks_json():
    text = VSCODE_TASKS.read_text(encoding="utf-8")
    patched = text.replace("AGENT_PATH", str(AGENT_DIR).replace("\\", "/"))
    VSCODE_TASKS.write_text(patched, encoding="utf-8")
    print(f"  ✅ Patched vscode/tasks.json with: {AGENT_DIR}")

def create_memory_dir():
    d = Path.home() / ".ai_agent"
    d.mkdir(parents=True, exist_ok=True)
    print(f"  ✅ Memory directory: {d}")

def setup_linux_mac():
    shell_rc = Path.home() / (
        ".zshrc" if os.path.exists(Path.home() / ".zshrc") else ".bashrc"
    )
    alias_block = f"""
# ── AI Agent (auto-added by install.py) ──────────────────────
export AI_AGENT_DIR="{AGENT_DIR}"
alias ai="python $AI_AGENT_DIR/main.py"
alias ai-chat="python $AI_AGENT_DIR/main.py --chat --project \\$(pwd)"
alias ai-task="python $AI_AGENT_DIR/main.py --task"
alias ai-mem="python $AI_AGENT_DIR/main.py --memory"
# ─────────────────────────────────────────────────────────────
"""
    existing = shell_rc.read_text(encoding="utf-8") if shell_rc.exists() else ""
    if "AI_AGENT_DIR" not in existing:
        with open(shell_rc, "a") as f:
            f.write(alias_block)
        print(f"  ✅ Aliases added to {shell_rc}")
        print(f"     Run: source {shell_rc}")
    else:
        print(f"  ℹ️  Aliases already in {shell_rc} — skipped.")

def setup_windows():
    profile_path = subprocess.run(
        ["powershell", "-Command", "echo $PROFILE"],
        capture_output=True, text=True
    ).stdout.strip()
    if not profile_path:
        profile_path = str(Path.home() / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1")

    profile = Path(profile_path)
    profile.parent.mkdir(parents=True, exist_ok=True)

    fn_block = f"""
# ── AI Agent (auto-added by install.py) ──────────────────────
$env:AI_AGENT_DIR = "{AGENT_DIR}"
function ai       {{ python "$env:AI_AGENT_DIR\\main.py" @args }}
function ai-chat  {{ python "$env:AI_AGENT_DIR\\main.py" --chat --project (Get-Location) @args }}
function ai-task  {{ param($t) python "$env:AI_AGENT_DIR\\main.py" --task $t }}
function ai-mem   {{ python "$env:AI_AGENT_DIR\\main.py" --memory }}
# ─────────────────────────────────────────────────────────────
"""
    existing = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if "AI_AGENT_DIR" not in existing:
        with open(profile, "a", encoding="utf-8") as f:
            f.write(fn_block)
        print(f"  ✅ PowerShell functions added to {profile}")
        print(f"     Restart PowerShell or run: . $PROFILE")
    else:
        print(f"  ℹ️  Functions already in {profile} — skipped.")

def print_vscode_instructions():
    tasks_src = VSCODE_TASKS
    print(f"""
  📌 VSCode Global Tasks Setup:
     1. Press Ctrl+Shift+P → "Open User Tasks"
     2. Replace the entire content with the contents of:
        {tasks_src}
     3. Save. Tasks will now work in ANY folder you open.
""")

def main():
    print("\n🚀 AI Agent — Global Install\n")
    create_memory_dir()
    patch_tasks_json()

    system = platform.system()
    print(f"\n  Detected OS: {system}")

    if system in ("Linux", "Darwin"):
        setup_linux_mac()
    elif system == "Windows":
        setup_windows()
    else:
        print(f"  ⚠️  Unknown OS ({system}). Add aliases manually.")

    print_vscode_instructions()

    print("  ✅ Done!\n")
    print("  Quick test (after reloading shell):")
    print("    ai --chat")
    print("    ai --task 'explain main.py' --project .")
    print()

if __name__ == "__main__":
    main()
