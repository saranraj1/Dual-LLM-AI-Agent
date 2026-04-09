"""
scripts/install_git_hook.py — Install AI Agent git pre-commit hook.

Run once per project:
    python C:/ai-agent/scripts/install_git_hook.py

The hook will:
  1. Run flake8 on staged .py files
  2. Check for hardcoded secrets (API keys, passwords)
  3. Warn about CRITICAL issues (but still allow commit to proceed)
  4. Block ONLY if --strict flag was used during installation
"""

import os
import sys
import stat
import argparse
from pathlib import Path

HOOK_TEMPLATE = '''#!/usr/bin/env python3
"""
AI Agent pre-commit hook.
Auto-installed by: python C:/ai-agent/scripts/install_git_hook.py
"""
import sys
import os
import re
import subprocess

AGENT_DIR = r"{agent_dir}"
STRICT    = {strict}  # If True, block commit on critical issues

def get_staged_py_files():
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True
    )
    return [f for f in r.stdout.splitlines() if f.endswith(".py")]

def check_secrets(files):
    SECRET_PATTERNS = [
        (r'(?i)(api_key|apikey|secret|password|passwd|token)\\s*=\\s*["\\'`][^"\\'`]{{6,}}', "Hardcoded secret"),
        (r'sk-[A-Za-z0-9]{{32,}}',                          "OpenAI API key"),
        (r'gsk_[A-Za-z0-9]{{32,}}',                         "Groq API key"),
        (r'(?i)aws_(?:access|secret).*=\\s*["\\'`]\\w+',    "AWS credential"),
        (r'(?i)password\\s*=\\s*["\\'`]\\w{{6,}}',           "Hardcoded password"),
    ]
    issues = []
    for f in files:
        try:
            content = open(f, encoding="utf-8", errors="ignore").read()
            for pattern, label in SECRET_PATTERNS:
                if re.search(pattern, content):
                    issues.append(f"  [SECRET] {{f}}: {{label}}")
        except Exception:
            pass
    return issues

def run_flake8(files):
    if not files:
        return []
    r = subprocess.run(
        ["flake8", "--max-line-length=120", "--select=E9,F63,F7,F82"] + files,
        capture_output=True, text=True
    )
    lines = (r.stdout + r.stderr).strip().splitlines()
    return lines[:20] if lines else []

def main():
    files = get_staged_py_files()
    if not files:
        sys.exit(0)

    print(f"\\n🔍 AI Agent pre-commit check ({len(files)} Python files)...")
    all_issues = []

    # Syntax / serious errors
    lint = run_flake8(files)
    if lint:
        print("\\n  ⚠️  Lint issues:")
        for l in lint:
            print(f"     {{l}}")
        all_issues.extend(lint)

    # Secret detection
    secrets = check_secrets(files)
    if secrets:
        print("\\n  🔒 SECURITY - Possible secrets detected:")
        for s in secrets:
            print(f"     {{s}}")
        all_issues.extend(secrets)

    if not all_issues:
        print("  ✅ All checks passed!")
        sys.exit(0)

    print(f"\\n  Found {{len(all_issues)}} issue(s).")
    if STRICT:
        print("  ❌ STRICT MODE: Commit blocked. Fix issues or use: git commit --no-verify")
        sys.exit(1)
    else:
        print("  ⚠️  NON-STRICT: Commit allowed. Fix issues when possible.")
        sys.exit(0)

if __name__ == "__main__":
    main()
'''


def install_hook(project_dir: str, strict: bool = False):
    git_dir = Path(project_dir) / ".git"
    if not git_dir.exists():
        print(f"❌ No .git directory found in: {project_dir}")
        print("   Initialize git first: git init")
        return False

    hooks_dir  = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path  = hooks_dir / "pre-commit"
    agent_dir  = str(Path(__file__).parent.parent.resolve())

    content = HOOK_TEMPLATE.format(
        agent_dir=agent_dir.replace("\\", "\\\\"),
        strict=str(strict)
    )

    hook_path.write_text(content, encoding="utf-8")

    # Make executable on Unix/Mac
    current = hook_path.stat().st_mode
    hook_path.chmod(current | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    mode = "STRICT (blocks commits)" if strict else "NON-STRICT (warns only)"
    print(f"✅ Git pre-commit hook installed!")
    print(f"   Location : {hook_path}")
    print(f"   Mode     : {mode}")
    print(f"   Project  : {project_dir}")
    print(f"\n   Every git commit will now:")
    print(f"   • Run flake8 on staged .py files")
    print(f"   • Check for hardcoded secrets/API keys")
    print(f"\n   To bypass: git commit --no-verify")
    return True


def remove_hook(project_dir: str):
    hook_path = Path(project_dir) / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        hook_path.unlink()
        print(f"✅ Pre-commit hook removed from: {project_dir}")
    else:
        print(f"ℹ️  No hook found at: {hook_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install AI Agent git pre-commit hook")
    parser.add_argument("--project", default=os.getcwd(), help="Project directory (default: current)")
    parser.add_argument("--strict",  action="store_true",  help="Block commits on issues (default: warn only)")
    parser.add_argument("--remove",  action="store_true",  help="Remove installed hook")
    args = parser.parse_args()

    if args.remove:
        remove_hook(args.project)
    else:
        install_hook(args.project, strict=args.strict)
