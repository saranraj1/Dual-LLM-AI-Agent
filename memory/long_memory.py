"""
memory/long_memory.py — Persistent long-term memory backed by SQLite.

Replaces the old JSON flat-file approach. All data is stored in a proper
relational table with timestamps, enabling better querying and no corruption
on concurrent writes.

Migration: if a legacy long_memory.json file is found on first run,
its content is automatically imported into the database and the JSON file
is renamed to .migrated so it's not re-imported.
"""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


# ── DB path ────────────────────────────────────────────────────────────────────

AGENT_HOME    = Path.home() / ".ai_agent"
DB_PATH       = AGENT_HOME / "long_memory.db"
LEGACY_JSON   = AGENT_HOME / "long_memory.json"

AGENT_HOME.mkdir(parents=True, exist_ok=True)


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    role      TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
    content   TEXT    NOT NULL,
    workspace TEXT    DEFAULT '',
    ts        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_ts ON memory(ts);
"""


# ── Migration from legacy JSON ─────────────────────────────────────────────────

def _migrate_json_if_needed(conn: sqlite3.Connection) -> None:
    """Import legacy JSON long-term memory into SQLite (runs once)."""
    if not LEGACY_JSON.exists():
        return
    migrated_path = LEGACY_JSON.with_suffix(".json.migrated")
    if migrated_path.exists():
        return  # already migrated
    try:
        data = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
        turns = data if isinstance(data, list) else data.get("turns", [])
        cursor = conn.cursor()
        for t in turns:
            cursor.execute(
                "INSERT INTO memory (role, content) VALUES (?, ?)",
                (t.get("role", "user"), t.get("content", "")[:1000])
            )
        conn.commit()
        LEGACY_JSON.rename(migrated_path)
        print(f"   ✅ Migrated {len(turns)} turns from JSON → SQLite")
    except Exception as e:
        print(f"   ⚠️  Could not migrate legacy memory: {e}")


# ── Connection factory ─────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent access
    conn.executescript(_SCHEMA)
    conn.commit()
    _migrate_json_if_needed(conn)
    return conn


# ── LongMemory class ───────────────────────────────────────────────────────────

class LongMemory:
    """
    Persistent long-term memory stored in SQLite.

    Usage:
        mem = LongMemory()
        mem.add("user", "What does this function do?")
        mem.add("assistant", "It sorts a list using ...")
        context = mem.get_context(max_chars=500)
        mem.save()   # no-op — SQLite writes immediately but kept for API compat
    """

    def __init__(self, workspace: str = ""):
        self.workspace = workspace
        self._conn = _get_conn()

    # ── Write ──────────────────────────────────────────────────────────────────

    def add(self, role: str, content: str) -> None:
        """Insert a new turn into the database."""
        if not content or not content.strip():
            return
        self._conn.execute(
            "INSERT INTO memory (role, content, workspace) VALUES (?, ?, ?)",
            (role, content[:1000], self.workspace)
        )
        self._conn.commit()

    def save(self) -> None:
        """No-op — kept for API compatibility. SQLite commits immediately on add()."""
        pass

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_context(self, max_chars: int = 500) -> str:
        """Return the most recent turns as a formatted string, up to max_chars."""
        rows = self._conn.execute(
            "SELECT role, content FROM memory ORDER BY id DESC LIMIT 20"
        ).fetchall()
        rows.reverse()  # oldest first
        lines = []
        total = 0
        for row in rows:
            line = f"[{row['role']}]: {row['content']}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)

    def get_turns(self, n: int = 20) -> List[Dict]:
        """Return the last n turns as list of dicts."""
        rows = self._conn.execute(
            "SELECT role, content, ts FROM memory ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        rows.reverse()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    def stats(self) -> Dict:
        """Return memory statistics."""
        count  = self._conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        oldest = self._conn.execute("SELECT MIN(ts) FROM memory").fetchone()[0]
        newest = self._conn.execute("SELECT MAX(ts) FROM memory").fetchone()[0]
        return {
            "total_turns": count,
            "oldest":      oldest or "—",
            "newest":      newest or "—",
            "db_path":     str(DB_PATH),
        }

    def clear(self) -> None:
        """Delete all stored memory."""
        self._conn.execute("DELETE FROM memory")
        self._conn.commit()

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Simple keyword search through memory content."""
        rows = self._conn.execute(
            "SELECT role, content, ts FROM memory WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit)
        ).fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]

    def __del__(self):
        try:
            self._conn.close()
        except Exception:
            pass
