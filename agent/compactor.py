"""
agent/compactor.py — Context Compaction & Stateful Working Memory Engine (Pillar 3).

Monitors conversation token/character budget and automatically triggers
semantic context compaction at 75% capacity, or manually via /compact.
Maintains a persistent, structured WorkingState ledger so the agent can run
50+ turn sessions without forgetting goals or losing state.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any
from config.settings import CONTEXT_WINDOW


CHARS_PER_TOKEN = 4
COMPACT_THRESHOLD_RATIO = 0.75


@dataclass
class WorkingState:
    """Persistent structured working memory ledger."""
    goal: str = ""
    modified_files: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    test_invariants: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)

    def record_file(self, file_path: str):
        if file_path not in self.modified_files:
            self.modified_files.append(file_path)

    def record_decision(self, decision: str):
        if decision not in self.decisions:
            self.decisions.append(decision)

    def record_test(self, test_info: str):
        if test_info not in self.test_invariants:
            self.test_invariants.append(test_info)

    def to_markdown(self) -> str:
        """Render working state as structured markdown."""
        lines = ["### 🧠 Active Working State (Compacted Memory)"]
        if self.goal:
            lines.append(f"- **Primary Goal**: {self.goal}")
        if self.decisions:
            lines.append("- **Key Decisions & Constraints**:")
            for d in self.decisions[-6:]:
                lines.append(f"  * {d}")
        if self.modified_files:
            lines.append("- **Verified Modified Files**:")
            for f in self.modified_files[-10:]:
                lines.append(f"  * `{f}`")
        if self.test_invariants:
            lines.append("- **Test Status & Invariants**:")
            for t in self.test_invariants[-6:]:
                lines.append(f"  * {t}")
        if self.next_actions:
            lines.append("- **Pending Next Actions**:")
            for na in self.next_actions[-5:]:
                lines.append(f"  * {na}")
        return "\n".join(lines)


def calculate_history_chars(history: List[Dict[str, str]]) -> int:
    """Calculate total character weight of conversation turns."""
    return sum(len(turn.get("content", "")) for turn in history)


def should_compact(total_chars: int, budget_chars: Optional[int] = None) -> bool:
    """Check if conversation has reached 75% capacity threshold."""
    limit = budget_chars or int(CONTEXT_WINDOW * CHARS_PER_TOKEN * 0.65)
    return total_chars >= (limit * COMPACT_THRESHOLD_RATIO)


def compact_history(
    history: List[Dict[str, str]],
    working_state: WorkingState,
    force: bool = False,
    budget_chars: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], bool, str]:
    """
    Compact conversation history if over threshold or forced.
    Returns: (compacted_history, was_compacted, summary_message)
    """
    total_chars = calculate_history_chars(history)
    limit = budget_chars or int(CONTEXT_WINDOW * CHARS_PER_TOKEN * 0.65)

    if not force and not should_compact(total_chars, limit):
        return history, False, "Context within safe budget; compaction not required."

    if len(history) <= 2:
        return history, False, "Context too short to compact."

    # Extract any recent files or decisions mentioned in the turns
    for turn in history:
        content = turn.get("content", "")
        # Detect file writes or edits mentioned in turns
        for line in content.splitlines():
            if "Surgically edited:" in line or "Written:" in line:
                parts = line.split(":", 1)
                if len(parts) > 1:
                    working_state.record_file(parts[1].strip())
            elif "ASK_USER:" in line or "OPTION:" in line:
                working_state.record_decision(line.strip())

    # Build compacted prompt ledger
    compacted_ledger = working_state.to_markdown()

    # Retain the earliest user intent and the last 2 turns
    kept_turns = []
    if history:
        # Keep initial user prompt
        kept_turns.append(history[0])

    # Inject compacted state
    kept_turns.append({
        "role": "system",
        "content": f"## Context Compactor\n{compacted_ledger}"
    })

    # Keep last turn if exists
    if len(history) > 1:
        kept_turns.append(history[-1])

    new_chars = calculate_history_chars(kept_turns)
    saved = total_chars - new_chars
    summary = (
        f"Context compacted successfully. "
        f"Reduced from {total_chars} to {new_chars} chars (saved {saved} chars, ~{saved // 4} tokens)."
    )
    return kept_turns, True, summary


# ── /compact CLI Command ──────────────────────────────────────────────────────

def cmd_compact(agent, args: str = "") -> str:
    """Manually compact current conversation context to preserve working memory."""
    if not hasattr(agent, "short_mem"):
        return "❌ Agent does not have short-term memory initialized."

    turns = agent.short_mem.get_turns(100)
    if not turns:
        return "ℹ️ Conversation history is currently empty; nothing to compact."

    working_state = getattr(agent, "working_state", None)
    if not working_state:
        working_state = WorkingState(goal=getattr(agent, "code_context", "")[:120])
        agent.working_state = working_state

    # Compact turns
    compacted, was_done, summary = compact_history(turns, working_state, force=True)
    if was_done:
        agent.short_mem.clear()
        for t in compacted:
            agent.short_mem.add(t.get("role", "user"), t.get("content", ""))
        return f"🧹 {summary}\n\n{working_state.to_markdown()}"
    return f"ℹ️ {summary}"
