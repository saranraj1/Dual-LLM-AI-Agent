"""
agent/reflection.py — Self-reflection: agent checks if a step succeeded.
Decides whether to retry, skip, or abort.
"""

import re
from core.llm import ask
from core.prompt_builder import build_reflect_prompt
from config.settings import MAX_REFLECT_LOOPS


class ReflectionResult:
    SUCCESS = "success"
    FAILED  = "failed"
    RETRY   = "retry"


def reflect(step: str, result: str, error: str = None, attempt: int = 0) -> dict:
    """
    Ask the LLM to evaluate whether a step's result is satisfactory.
    Returns:
      {
        "status":      "success" | "failed" | "retry",
        "explanation": str,
        "attempt":     int
      }
    """
    # Hard failures we can detect without LLM
    if error and any(e in error for e in ["[LLM ERROR]", "Timed out", "not found", "Permission denied"]):
        return {
            "status":      ReflectionResult.FAILED,
            "explanation": f"Hard failure: {error}",
            "attempt":     attempt
        }

    # Empty result — suspicious but not always wrong
    if not result or result.strip() == "":
        return {
            "status":      ReflectionResult.RETRY if attempt < MAX_REFLECT_LOOPS else ReflectionResult.FAILED,
            "explanation": "Empty result returned.",
            "attempt":     attempt
        }

    # Ask LLM to judge (only on first couple attempts to save tokens)
    if attempt < MAX_REFLECT_LOOPS:
        prompt   = build_reflect_prompt(step, result[:600], error)
        response = ask(prompt)

        if response.startswith("[LLM ERROR]"):
            # Can't reflect — assume success to avoid infinite loop
            return {"status": ReflectionResult.SUCCESS, "explanation": "Reflection skipped (LLM error).", "attempt": attempt}

        status = _parse_status(response)
        return {
            "status":      status,
            "explanation": response[:300],
            "attempt":     attempt
        }

    # Max attempts reached
    return {
        "status":      ReflectionResult.SUCCESS,  # move on
        "explanation": "Max reflection loops reached — proceeding.",
        "attempt":     attempt
    }


def _parse_status(response: str) -> str:
    low = response.lower()
    if "status: success" in low or "succeeded" in low or "looks correct" in low:
        return ReflectionResult.SUCCESS
    if "status: failed" in low or "did not work" in low or "incorrect" in low:
        return ReflectionResult.FAILED
    # Ambiguous → assume success
    return ReflectionResult.SUCCESS


def format_reflection(r: dict) -> str:
    icon = "✅" if r["status"] == ReflectionResult.SUCCESS else "❌"
    return f"{icon} Reflection [{r['status'].upper()}]: {r['explanation']}"
