"""
agent/planner.py — Breaks a high-level task into ordered steps using the LLM.
Falls back to a sensible default plan if the LLM fails or is offline.
"""

import re
from typing import List
from core.llm import ask
from core.prompt_builder import build_plan_prompt
from config.settings import MAX_PLAN_STEPS


DEFAULT_PLAN = [
    "Understand the task and gather context",
    "Analyze relevant files or codebase",
    "Implement the solution",
    "Verify the result",
]


def plan(task: str) -> List[str]:
    """
    Ask the LLM to break `task` into numbered steps.
    Returns a list of step strings.
    """
    prompt   = build_plan_prompt(task)
    response = ask(prompt)

    if response.startswith("[LLM ERROR]"):
        return DEFAULT_PLAN

    steps = _parse_steps(response)

    if not steps:
        return DEFAULT_PLAN

    return steps[:MAX_PLAN_STEPS]


def _parse_steps(text: str) -> List[str]:
    """
    Extract numbered list items from LLM output.
    Handles formats like:
      1. Do thing
      1) Do thing
      - Do thing  (fallback)
    """
    steps = []

    # Try numbered list first
    numbered = re.findall(r"^\s*\d+[\.\)]\s+(.+)$", text, re.MULTILINE)
    if numbered:
        return [s.strip() for s in numbered if s.strip()]

    # Fallback: bullet points
    bulleted = re.findall(r"^\s*[-*•]\s+(.+)$", text, re.MULTILINE)
    if bulleted:
        return [s.strip() for s in bulleted if s.strip()]

    # Last resort: split by newlines
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[:MAX_PLAN_STEPS]


def format_plan(steps: List[str]) -> str:
    """Pretty-print a plan for display."""
    return "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
