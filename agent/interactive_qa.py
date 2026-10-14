"""
agent/interactive_qa.py — Interactive QA & User Input Bridge for AI Agent.

Enables the autonomous agent to pause and ask the user questions when:
  - Requirements are ambiguous or underspecified
  - Choosing between architectural patterns or libraries
  - Confirming potentially breaking changes
  - Prompting for configuration, credentials, or custom preferences

Works across both Terminal CLI (stdin prompt with numbered choices)
and Web UI (async question queue with SSE notifications and answer endpoint).
"""

import sys
import re
import uuid
import threading
from typing import List, Dict, Optional, Any, Callable
from core.ui import C, bold, ok, warn, info


# ── Global Question Registry (for Web UI / Async pairing) ─────────────────────
_pending_questions: Dict[str, Dict[str, Any]] = {}
_question_lock = threading.Lock()
_custom_question_handler: Optional[Callable[[Dict[str, Any]], str]] = None


def set_question_handler(handler: Optional[Callable[[Dict[str, Any]], str]]):
    """Register a custom question handler (e.g. for Web UI or IDE extensions)."""
    global _custom_question_handler
    _custom_question_handler = handler


def get_pending_questions() -> List[Dict[str, Any]]:
    """Return all questions waiting for an answer."""
    with _question_lock:
        return [
            {
                "id": q_id,
                "question": q["question"],
                "options": q["options"],
                "default": q["default"],
                "timestamp": q["timestamp"],
            }
            for q_id, q in _pending_questions.items()
        ]


def answer_pending_question(q_id: str, answer: str) -> bool:
    """Provide an answer to a pending question, unblocking its waiter."""
    with _question_lock:
        q = _pending_questions.get(q_id)
        if not q:
            return False
        q["answer"] = answer
        q["event"].set()
        return True


# ── Parser for ASK_USER blocks in LLM output ──────────────────────────────────

def extract_ask_user_blocks(text: str) -> List[Dict[str, Any]]:
    """
    Parse ASK_USER blocks from LLM responses.
    Format:
        ASK_USER: Question prompt text
        OPTION: First choice (Recommended)
        OPTION: Second choice
        DEFAULT: 1
    """
    blocks = []
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()
        match = re.match(r"^ASK_USER:\s*(.+)$", line, re.IGNORECASE)
        if match:
            question = match.group(1).strip()
            options = []
            default = None
            i += 1
            while i < n:
                sub_line = lines[i].strip()
                opt_match = re.match(r"^OPTION:\s*(.+)$", sub_line, re.IGNORECASE)
                def_match = re.match(r"^DEFAULT:\s*(.+)$", sub_line, re.IGNORECASE)
                if opt_match:
                    options.append(opt_match.group(1).strip())
                    i += 1
                elif def_match:
                    default = def_match.group(1).strip()
                    i += 1
                elif not sub_line:
                    i += 1
                else:
                    break

            blocks.append({
                "question": question,
                "options": options,
                "default": default or (options[0] if options else None)
            })
            continue
        i += 1

    return blocks


# ── Interactive ask_user function ─────────────────────────────────────────────

def ask_user(
    question: str,
    options: Optional[List[str]] = None,
    default: Optional[str] = None,
    allow_custom: bool = True,
    timeout: Optional[float] = None
) -> str:
    """
    Prompt the user with an interactive question and return their response.
    
    If running via CLI:
      Renders colorized numbered choices and prompts stdin.
    If a custom handler is set (e.g. Web UI):
      Dispatches to the handler or waits for answer_pending_question.
    If non-interactive (CI / piped):
      Gracefully returns the default or first option.
    """
    options = options or []
    if default is None and options:
        default = options[0]

    # 1. Custom handler (Web UI / GUI / Test mocks)
    if _custom_question_handler is not None:
        try:
            return _custom_question_handler({
                "question": question,
                "options": options,
                "default": default,
                "allow_custom": allow_custom,
            })
        except Exception:
            pass

    # 2. Non-interactive fallback (CI, piped stdin, background daemon)
    if not sys.stdin.isatty():
        if default:
            return default
        return options[0] if options else "yes"

    # 3. Interactive Terminal Prompt
    print(f"\n{C.YELLOW}{C.BOLD}❓ Interactive Agent Inquiry:{C.RESET}")
    print(f"   {bold(question)}\n")

    if options:
        for idx, opt in enumerate(options, 1):
            is_def = " (default)" if (default and (default == opt or default == str(idx))) else ""
            print(f"   {C.CYAN}[{idx}]{C.RESET} {opt}{C.GRAY}{is_def}{C.RESET}")
        if allow_custom:
            print(f"   {C.GRAY}[or type your custom answer directly]{C.RESET}")

    default_hint = f" [{default}]" if default else ""
    prompt_str = f"\n{C.BOLD}{C.GREEN}Your choice{default_hint} › {C.RESET}"

    try:
        raw_input = input(prompt_str).strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n{C.GRAY}(Input skipped — using default: {default or 'None'}){C.RESET}")
        return default or (options[0] if options else "")

    if not raw_input:
        return default or (options[0] if options else "")

    # If user entered an index number (e.g. "1")
    if raw_input.isdigit() and options:
        choice_idx = int(raw_input) - 1
        if 0 <= choice_idx < len(options):
            return options[choice_idx]

    return raw_input


# ── Slash command handler ─────────────────────────────────────────────────────

def cmd_ask_user(agent, args: str) -> str:
    """
    Interactive QA command.
    Usage: /qa <question> [| option1 | option2 | option3]
    Example:
      /qa Which database do you want? | SQLite | PostgreSQL | In-Memory
    """
    parts = [p.strip() for p in args.split("|") if p.strip()]
    if not parts:
        return "Usage: /qa <question> [| option1 | option2 | option3]"

    question = parts[0]
    options = parts[1:] if len(parts) > 1 else []

    answer = ask_user(question, options=options)
    print(f"\n{ok('Answer received:')} {answer}")

    # Record into agent session memory
    if hasattr(agent, "short_mem"):
        agent.short_mem.add("user", f"[User Decision]: {question} → {answer}")

    return f"Question: {question}\nUser selected: {answer}"
