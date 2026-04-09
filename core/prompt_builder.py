"""
core/prompt_builder.py — Assembles prompts from memory, code context, and task.
Respects token budget so we never overflow the context window.
"""

from typing import List, Optional
from config.settings import CONTEXT_WINDOW

# 1 token ≈ 4 characters (conservative estimate)
CHARS_PER_TOKEN = 4

SYSTEM_PROMPT = """You are a senior software engineer and autonomous AI coding agent.
You have access to the user's codebase, memory of past sessions, and can use tools.

Rules:
- Think step-by-step before acting
- Reference exact file names and line numbers when discussing code
- Always provide complete, runnable code when writing/editing
- After using a tool, reflect on whether it worked
- Be direct and concise — no filler
- If a task needs multiple steps, say so and proceed step by step"""


def _char_budget() -> int:
    """How many characters we can safely use in a prompt."""
    # Reserve 30% for response + system prompt overhead
    return int(CONTEXT_WINDOW * CHARS_PER_TOKEN * 0.65)


def build(
    task: str,
    memory_context: str  = "",
    code_context: str    = "",
    tool_results: str    = "",
    plan: List[str]      = None,
    current_step: str    = "",
) -> str:
    """
    Assemble the full prompt. Parts are trimmed if budget is tight.
    Order of priority (most important last = closest to the model's attention):
      memory → code → tool_results → plan → task
    """
    budget = _char_budget()
    parts  = []

    # 1. Memory (oldest, lowest priority — trim first)
    if memory_context:
        chunk = f"## Memory (past context)\n{memory_context}"
        parts.append(_trim(chunk, budget // 4))

    # 2. Code context
    if code_context:
        chunk = f"## Codebase Context\n{code_context}"
        parts.append(_trim(chunk, budget // 3))

    # 3. Tool output from previous step
    if tool_results:
        chunk = f"## Tool Output\n{tool_results}"
        parts.append(_trim(chunk, budget // 5))

    # 4. Plan overview
    if plan:
        steps_str = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan))
        chunk = f"## Current Plan\n{steps_str}"
        if current_step:
            chunk += f"\n\n▶ Now executing: {current_step}"
        parts.append(chunk)

    # 5. Task (always present, never trimmed)
    parts.append(f"## Task\n{task}")

    return "\n\n---\n\n".join(parts)


def build_plan_prompt(task: str) -> str:
    """Prompt for generating a step-by-step plan."""
    return (
        f"Break this task into clear, ordered steps. "
        f"Return ONLY a numbered list, one step per line, no explanation.\n\n"
        f"Task: {task}"
    )


def build_reflect_prompt(step: str, result: str, error: str) -> str:
    """Prompt for self-reflection after a step."""
    return (
        f"You just executed this step: {step}\n\n"
        f"Result:\n{result}\n\n"
        f"Error (if any): {error or 'None'}\n\n"
        f"Did this succeed? If not, what went wrong and how should it be fixed? "
        f"Reply with: STATUS: SUCCESS or STATUS: FAILED, then a brief explanation."
    )


def _trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n...[trimmed]...\n" + text[-half:]
