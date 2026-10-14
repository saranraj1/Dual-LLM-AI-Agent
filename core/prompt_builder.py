"""
core/prompt_builder.py — Assembles prompts from memory, code context, and task.
Respects token budget so we never overflow the context window.
"""

from typing import List, Optional
from config.settings import CONTEXT_WINDOW

# 1 token ≈ 4 characters (conservative estimate)
CHARS_PER_TOKEN = 4

SYSTEM_PROMPT = """You are a principal software engineer and autonomous AI coding agent.
You have access to the codebase, AST call graphs, past session memory, and execution tools.

Core Operating Heuristics:
1. MINIMALIST DIFFS & YAGNI (Ponytail):
   - The best code is code never written. Produce the shortest working diff that completely solves the problem.
   - Reuse existing repository patterns -> stdlib -> installed dependencies before adding abstractions or packages.
   - Favor deletion and simplification over accumulation. Never cut security, error boundaries, or validation.

2. SYSTEMATIC ROOT-CAUSE REASONING:
   - Always find the root cause before patching. Never apply superficial symptom fixes.
   - Inspect full stack traces, assess AST blast radius across callers/tests, and fix at the shared root.

3. CLEAN CRAFTSMANSHIP:
   - Write intention-revealing names, single-responsibility functions, and self-documenting code.
   - Never output placeholder comments (e.g., '// rest of code') or dead imports. Provide complete, runnable code.

4. OBJECTIVE TECHNICAL RIGOR (Anti-Sycophancy):
   - Evidence before deference. State engineering tradeoffs, failure modes, and performance risks plainly.

5. VERIFICATION & INTERACTIVE ALIGNMENT:
   - Reflect on tool outputs and verify against tests before declaring completion.
   - If requirements are ambiguous or key architectural trade-offs exist, ask explicitly:
     ASK_USER: Clear question explaining the decision?
     OPTION: Choice 1 (Recommended)
     OPTION: Choice 2
     DEFAULT: 1"""


def _char_budget() -> int:
    """How many characters we can safely use in a prompt."""
    # Reserve 30% for response + system prompt overhead
    return int(CONTEXT_WINDOW * CHARS_PER_TOKEN * 0.65)


def build(
    task: str,
    memory_context: str  = "",
    code_context: str    = "",
    repo_map: str        = "",
    tool_results: str    = "",
    plan: List[str]      = None,
    current_step: str    = "",
) -> str:
    """
    Assemble the full prompt. Parts are trimmed if budget is tight.
    Order of priority (most important last = closest to the model's attention):
      memory → repo_map → code → tool_results → plan → task
    """
    budget = _char_budget()
    parts  = []

    # 1. Memory (oldest, lowest priority — trim first)
    if memory_context:
        chunk = f"## Memory (past context)\n{memory_context}"
        parts.append(_trim(chunk, budget // 5))

    # 2. Workspace Symbol Map (AST-level structural outline)
    if repo_map:
        chunk = f"## Workspace Symbol Map\n{repo_map}"
        parts.append(_trim(chunk, budget // 4))

    # 3. Code context
    if code_context:
        chunk = f"## Codebase Context\n{code_context}"
        parts.append(_trim(chunk, budget // 3))

    # 4. Tool output from previous step
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
