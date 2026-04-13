"""
memory/fix_memory.py — Learn from past successful fixes.

Every time the agent successfully fixes a bug, it stores:
  - The error signature (normalised — line numbers stripped)
  - The fix description
  - The file type
  - How many times this pattern has been seen

On the next similar error, the agent loads the top matching past fixes
and injects them into the LLM prompt as "here's what worked before".

Storage: SQLite (~/.ai_agent/fix_memory.db)
"""

import re
import sqlite3
import hashlib
from pathlib import Path
from typing import List, Dict, Optional

# ── DB path ───────────────────────────────────────────────────────────────────
AGENT_HOME = Path.home() / ".ai_agent"
FIX_DB     = AGENT_HOME / "fix_memory.db"
AGENT_HOME.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fix_patterns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    error_sig   TEXT    NOT NULL,          -- normalised error signature (hash)
    error_text  TEXT    NOT NULL,          -- original error snippet
    fix_desc    TEXT    NOT NULL,          -- what the fix was
    file_type   TEXT    NOT NULL DEFAULT '.py',
    hits        INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_fix_sig  ON fix_patterns(error_sig);
CREATE INDEX IF NOT EXISTS idx_fix_hits ON fix_patterns(hits DESC);
"""


# ── Normalisation ─────────────────────────────────────────────────────────────

_LINE_PATTERN  = re.compile(r"\b(line|ln)\s+\d+", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"\b0x[0-9a-fA-F]+|\b\d+\b")
_PATH_PATTERN  = re.compile(r'["\']?(?:[A-Za-z]:)?(?:[/\\][^"\'>\s]+)+["\']?')


def _normalise_error(error: str) -> str:
    """
    Strip volatile parts (line numbers, paths, hex addresses) from an error
    message so similar errors produce the same signature.
    """
    s = error[:500]
    s = _LINE_PATTERN.sub("line N", s)
    s = _PATH_PATTERN.sub("<path>", s)
    s = _NUMBER_PATTERN.sub("N", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _sig(error: str) -> str:
    """SHA-1 of the normalised error — used as the lookup key."""
    return hashlib.sha1(_normalise_error(error).encode()).hexdigest()[:16]


# ── FixMemory class ───────────────────────────────────────────────────────────

class FixMemory:
    """
    Persistent store of successful fix patterns.

    Usage:
        fm = FixMemory()
        # After a successful fix:
        fm.record(error_text="NameError: name 'x' not defined",
                  fix_desc="Added 'x = []' before the loop", file_type=".py")

        # Before attempting a fix:
        hints = fm.get_hints("NameError: name 'y' not defined")
        # Returns past fixes for similar NameError patterns
    """

    def __init__(self):
        self._conn = self._init_db()

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(FIX_DB))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        error_text: str,
        fix_desc:   str,
        file_type:  str = ".py",
    ) -> None:
        """
        Store a successful fix pattern.

        Args:
            error_text: The raw error / traceback that was fixed.
            fix_desc:   A short description of the fix applied.
            file_type:  File extension of the file that was fixed.
        """
        if not error_text.strip() or not fix_desc.strip():
            return

        sig = _sig(error_text)
        existing = self._conn.execute(
            "SELECT id, hits FROM fix_patterns WHERE error_sig = ?", (sig,)
        ).fetchone()

        if existing:
            self._conn.execute(
                "UPDATE fix_patterns SET hits = hits + 1, fix_desc = ?, "
                "last_seen = strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id = ?",
                (fix_desc, existing["id"])
            )
        else:
            self._conn.execute(
                "INSERT INTO fix_patterns (error_sig, error_text, fix_desc, file_type) "
                "VALUES (?, ?, ?, ?)",
                (sig, error_text[:500], fix_desc[:1000], file_type)
            )
        self._conn.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_hints(self, error_text: str, limit: int = 3) -> List[Dict]:
        """
        Return past fixes for errors similar to error_text.

        Args:
            error_text: The new error to look up.
            limit:      Max number of hints to return (default 3).

        Returns:
            List of dicts with keys: error_text, fix_desc, hits, file_type
        """
        sig = _sig(error_text)

        # Exact signature match (normalised)
        rows = self._conn.execute(
            "SELECT error_text, fix_desc, hits, file_type FROM fix_patterns "
            "WHERE error_sig = ? ORDER BY hits DESC LIMIT ?",
            (sig, limit)
        ).fetchall()

        if not rows:
            # Fuzzy: look for keyword overlap in the error text (top-3 words)
            words = [w for w in re.findall(r'\b[A-Za-z]{4,}\b', error_text[:200])
                     if w.lower() not in {"error", "line", "file", "traceback"}][:3]
            if words:
                like = "%" + "%".join(words[:2]) + "%"
                rows = self._conn.execute(
                    "SELECT error_text, fix_desc, hits, file_type FROM fix_patterns "
                    "WHERE error_text LIKE ? ORDER BY hits DESC LIMIT ?",
                    (like, limit)
                ).fetchall()

        return [dict(r) for r in rows]

    def format_hints_for_prompt(self, error_text: str) -> str:
        """
        Return a formatted string to inject into an LLM prompt.

        Example output:
            💡 Similar errors I've fixed before:
            1. [3 times] NameError in .py → Added variable declaration before use
            2. [1 time]  IndentationError → Fixed mixed tabs/spaces
        """
        hints = self.get_hints(error_text)
        if not hints:
            return ""

        lines = ["💡 Similar errors fixed before (use these patterns if applicable):"]
        for i, h in enumerate(hints, 1):
            times = f"{h['hits']} time{'s' if h['hits'] != 1 else ''}"
            lines.append(f"  {i}. [{times}] {h['file_type']} → {h['fix_desc'][:120]}")
        return "\n".join(lines)

    def stats(self) -> Dict:
        """Return aggregate statistics about the fix memory."""
        count = self._conn.execute("SELECT COUNT(*) FROM fix_patterns").fetchone()[0]
        top = self._conn.execute(
            "SELECT error_text, fix_desc, hits FROM fix_patterns ORDER BY hits DESC LIMIT 3"
        ).fetchall()
        return {
            "total_patterns": count,
            "top_fixes": [dict(r) for r in top],
            "db_path": str(FIX_DB),
        }

    def clear(self) -> None:
        """Delete all stored fix patterns."""
        self._conn.execute("DELETE FROM fix_patterns")
        self._conn.commit()

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM fix_patterns").fetchone()[0]

    def __del__(self):
        try:
            self._conn.close()
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────
fix_memory = FixMemory()
