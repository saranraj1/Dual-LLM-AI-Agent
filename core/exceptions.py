"""
core/exceptions.py — Agent exception hierarchy (Step 7).

Replace bare `except Exception: pass` with these specific types
so errors produce actionable messages instead of disappearing silently.

Usage:
    from core.exceptions import LLMError, ToolError, AgentError
    raise LLMError("Ollama returned empty response")
"""


class AgentError(Exception):
    """Base exception for all agent errors."""


class LLMError(AgentError):
    """Raised when an LLM backend call fails."""


class BackendUnavailableError(LLMError):
    """Raised when both Ollama and Groq are unreachable."""


class ToolError(AgentError):
    """Raised when a tool (file, shell, code) fails."""


class FileToolError(ToolError):
    """Raised when reading or writing a file fails."""


class ShellToolError(ToolError):
    """Raised when a shell command fails unexpectedly."""


class MemoryError(AgentError):
    """Raised when reading or writing memory fails."""
    # Note: shadows built-in MemoryError — use as core.exceptions.MemoryError


class KnowledgeBaseError(AgentError):
    """Raised when indexing or searching the KB fails."""
