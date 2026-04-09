"""
memory/short_memory.py — Session-scoped memory (lives only while agent is running).
Fast list of recent turns. Cleared when process exits.
"""

from typing import List, Dict
from config.settings import SHORT_MEMORY_MAX


class ShortMemory:
    def __init__(self):
        self._turns: List[Dict] = []

    def add(self, role: str, content: str):
        """Append a turn. Evicts oldest when over limit."""
        self._turns.append({"role": role, "content": content})
        if len(self._turns) > SHORT_MEMORY_MAX * 2:
            # Keep only recent half
            self._turns = self._turns[-SHORT_MEMORY_MAX:]

    def get_context(self, max_chars: int = 1200) -> str:
        """Return recent turns as a formatted string."""
        if not self._turns:
            return ""
        lines = []
        for t in self._turns[-SHORT_MEMORY_MAX:]:
            role    = t["role"].capitalize()
            content = t["content"][:300].replace("\n", " ")
            lines.append(f"{role}: {content}")
        result = "\n".join(lines)
        return result[-max_chars:] if len(result) > max_chars else result

    def get_turns(self, n: int = 8) -> List[Dict]:
        """Return the last n raw turn dicts for multi-turn context."""
        return self._turns[-n:] if self._turns else []

    def clear(self):
        self._turns.clear()

    def __len__(self):
        return len(self._turns)
