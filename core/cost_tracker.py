"""
core/cost_tracker.py — Track LLM API usage and estimate cost per session.

Supports:
- Groq pricing (per 1M tokens, updated Dec 2024)
- Ollama (local = free)
- Per-session accumulation
- Persistent daily summary in SQLite

Usage:
    from core.cost_tracker import tracker
    tracker.record("groq", prompt_tokens=120, completion_tokens=80)
    summary = tracker.summary()
"""

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# ── Groq pricing (USD per 1M tokens, as of 2024) ─────────────────────────────
# Source: https://console.groq.com/docs/openai
GROQ_PRICING: Dict[str, Dict[str, float]] = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant":    {"input": 0.05, "output": 0.08},
    "llama-3.2-3b-preview":    {"input": 0.06, "output": 0.06},
    "mixtral-8x7b-32768":      {"input": 0.24, "output": 0.24},
    "gemma2-9b-it":            {"input": 0.20, "output": 0.20},
    "default":                 {"input": 0.59, "output": 0.79},  # safe fallback
}

# ── Persistent DB ─────────────────────────────────────────────────────────────
AGENT_HOME = Path.home() / ".ai_agent"
COST_DB    = AGENT_HOME / "cost_tracker.db"
AGENT_HOME.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    backend           TEXT    NOT NULL,
    model             TEXT    NOT NULL DEFAULT '',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL    NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_cost_ts ON cost_log(ts);
"""


@dataclass
class SessionStats:
    ollama_calls:      int   = 0
    groq_calls:        int   = 0
    prompt_tokens:     int   = 0
    completion_tokens: int   = 0
    total_tokens:      int   = 0
    cost_usd:          float = 0.0
    start_time:        float = field(default_factory=time.time)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def total_calls(self) -> int:
        return self.ollama_calls + self.groq_calls


class CostTracker:
    """
    Tracks LLM token usage and cost for the current session.

    Example:
        tracker.record("groq", "llama-3.3-70b-versatile", 500, 300)
        print(tracker.summary())
    """

    def __init__(self):
        self.session = SessionStats()
        self._conn   = self._init_db()

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(COST_DB))
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    # ── Pricing ───────────────────────────────────────────────────────────────

    @staticmethod
    def _price(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost in USD for a Groq call."""
        p = GROQ_PRICING.get(model, GROQ_PRICING["default"])
        return (prompt_tokens * p["input"] + completion_tokens * p["output"]) / 1_000_000

    # ── Record a call ─────────────────────────────────────────────────────────

    def record(
        self,
        backend:           str,
        model:             str   = "",
        prompt_tokens:     int   = 0,
        completion_tokens: int   = 0,
    ) -> None:
        """
        Record one LLM call.

        Args:
            backend:           "groq" | "local" | "ollama"
            model:             Model name (used for Groq pricing lookup)
            prompt_tokens:     Input tokens consumed
            completion_tokens: Output tokens generated
        """
        cost = 0.0
        if backend == "groq" and prompt_tokens > 0:
            cost = self._price(model, prompt_tokens, completion_tokens)

        # ── Session accumulators ──────────────────────────────────────────────
        if backend == "groq":
            self.session.groq_calls += 1
        else:
            self.session.ollama_calls += 1

        self.session.prompt_tokens     += prompt_tokens
        self.session.completion_tokens += completion_tokens
        self.session.total_tokens      += prompt_tokens + completion_tokens
        self.session.cost_usd          += cost

        # ── Persist to DB ─────────────────────────────────────────────────────
        try:
            self._conn.execute(
                "INSERT INTO cost_log (backend, model, prompt_tokens, completion_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                (backend, model, prompt_tokens, completion_tokens, cost)
            )
            self._conn.commit()
        except Exception:
            pass  # never let tracking break the agent

    def estimate_tokens(self, text: str) -> int:
        """Rough estimate: ~4 chars per token (GPT-style tokenisation)."""
        return max(1, len(text) // 4)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def summary(self, verbose: bool = False) -> str:
        """Return a formatted session summary string."""
        s   = self.session
        hrs = int(s.elapsed_seconds // 3600)
        mins = int((s.elapsed_seconds % 3600) // 60)
        secs = int(s.elapsed_seconds % 60)
        duration = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        lines = [
            "┌─ Session Usage ────────────────────────────────┐",
            f"│  Duration         : {duration}",
            f"│  Total LLM calls  : {s.total_calls}",
            f"│    ├ Ollama (local): {s.ollama_calls}",
            f"│    └ Groq (cloud)  : {s.groq_calls}",
            f"│  Tokens used      : {s.total_tokens:,}",
            f"│    ├ Prompt        : {s.prompt_tokens:,}",
            f"│    └ Completion    : {s.completion_tokens:,}",
            f"│  Estimated cost   : ${s.cost_usd:.4f} USD",
            "└────────────────────────────────────────────────┘",
        ]

        if verbose:
            # Show today's total from DB
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                row = self._conn.execute(
                    "SELECT SUM(cost_usd), SUM(prompt_tokens + completion_tokens) "
                    "FROM cost_log WHERE ts LIKE ?", (f"{today}%",)
                ).fetchone()
                if row and row[0]:
                    lines.insert(-1, f"│  Today's total    : ${row[0]:.4f}  ({int(row[1] or 0):,} tokens)")
            except Exception:
                pass

        return "\n".join(lines)

    def daily_report(self) -> str:
        """Return a breakdown of cost per day for the last 7 days."""
        try:
            rows = self._conn.execute(
                "SELECT DATE(ts) as day, SUM(cost_usd) as cost, "
                "SUM(prompt_tokens + completion_tokens) as tokens, COUNT(*) as calls "
                "FROM cost_log GROUP BY day ORDER BY day DESC LIMIT 7"
            ).fetchall()
            if not rows:
                return "No usage history yet."
            lines = ["📊 Daily usage (last 7 days):", "Day          Calls  Tokens    Cost"]
            for row in rows:
                lines.append(f"  {row[0]}   {row[2]:>5}  {row[3]:>7,}  ${row[1]:.4f}")
            return "\n".join(lines)
        except Exception as e:
            return f"(could not load daily report: {e})"

    def reset_session(self) -> None:
        """Start a fresh session counter (doesn't affect DB history)."""
        self.session = SessionStats()


# ── Singleton ─────────────────────────────────────────────────────────────────
tracker = CostTracker()
