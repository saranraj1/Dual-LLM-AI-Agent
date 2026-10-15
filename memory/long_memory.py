"""
memory/long_memory.py — Persistent long-term memory backed by SQLite WAL mode,
FTS5 full-text search, and workspace-scoped data isolation.
"""

from pathlib import Path
from typing import List, Dict, Optional, Any

from memory.storage import get_db, normalize_workspace, normalize_category, DB_PATH
from memory.retrieval import search_conversation_memory, search_knowledge_facts


class LongMemory:
    """
    Persistent long-term memory stored in SQLite with FTS5 search and workspace scoping.

    Usage:
        mem = LongMemory(workspace="/path/to/project")
        mem.add("user", "We are using Pydantic v2")
        mem.add("assistant", "Understood, will use model_dump().")
        context = mem.get_context(max_chars=500, query="Pydantic")
    """

    def __init__(self, workspace: str = "", storage: Optional[Any] = None):
        self.workspace = normalize_workspace(workspace)
        self.storage = storage

    def _get_db(self):
        if self.storage and hasattr(self.storage, "get_db"):
            return self.storage.get_db()
        return get_db()

    # ── Write Turns ────────────────────────────────────────────────────────────

    def add(self, role: str, content: str, session_id: str = "default") -> None:
        """Insert a new turn into conversation_turns."""
        if not content or not content.strip():
            return
        with self._get_db() as conn:
            conn.execute(
                """
                INSERT INTO conversation_turns (session_id, workspace, role, content, token_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, self.workspace, role, content[:2000], len(content) // 4)
            )
            conn.commit()

    def save(self) -> None:
        """No-op — kept for API compatibility. Commits happen immediately on write."""
        pass

    # ── Read Turns ─────────────────────────────────────────────────────────────

    def get_context(self, max_chars: int = 500, query: str = "") -> str:
        """
        Return the most relevant or recent turns as a formatted string, up to max_chars.
        If query is provided, utilizes FTS5 hybrid search with recency decay.
        """
        if query:
            if self.storage:
                from memory.retrieval import HybridRetrievalEngine
                engine = HybridRetrievalEngine(self.storage)
                items = engine.search_conversation_memory(query, workspace=self.workspace, limit=10)
            else:
                items = search_conversation_memory(query, workspace=self.workspace, limit=10)
        else:
            with self._get_db() as conn:
                rows = conn.execute(
                    """
                    SELECT role, content FROM conversation_turns
                    WHERE (? = '' OR workspace = ?)
                    ORDER BY id DESC LIMIT 20
                    """,
                    (self.workspace, self.workspace)
                ).fetchall()
                items = [{"role": r["role"], "content": r["content"]} for r in rows]

        # Reverse so older turns appear first in chronological order
        items_rev = list(reversed(items))
        lines = []
        total = 0
        for item in items_rev:
            line = f"[{item['role']}]: {item['content']}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)

    def get_turns(self, n: int = 20, limit: Optional[int] = None) -> List[Dict]:
        """Return the last n turns as list of dicts."""
        max_limit = limit or n
        with self._get_db() as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at as ts
                FROM conversation_turns
                WHERE (? = '' OR workspace = ?)
                ORDER BY id DESC LIMIT ?
                """,
                (self.workspace, self.workspace, max_limit)
            ).fetchall()
            rows_rev = list(reversed(rows))
            return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows_rev]

    def stats(self) -> Dict:
        """Return memory statistics."""
        with self._get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM conversation_turns WHERE (? = '' OR workspace = ?)",
                (self.workspace, self.workspace)
            ).fetchone()[0]
            oldest = conn.execute(
                "SELECT MIN(created_at) FROM conversation_turns WHERE (? = '' OR workspace = ?)",
                (self.workspace, self.workspace)
            ).fetchone()[0]
            newest = conn.execute(
                "SELECT MAX(created_at) FROM conversation_turns WHERE (? = '' OR workspace = ?)",
                (self.workspace, self.workspace)
            ).fetchone()[0]
            facts_count = conn.execute(
                "SELECT COUNT(*) FROM knowledge_facts WHERE (? = '' OR workspace = ?)",
                (self.workspace, self.workspace)
            ).fetchone()[0]

            db_target = str(getattr(self.storage, "db_path", DB_PATH))
            return {
                "total_turns": count,
                "facts_count": facts_count,
                "oldest": oldest or "—",
                "newest": newest or "—",
                "db_path": db_target,
                "workspace": self.workspace or "(global)",
            }

    def clear(self) -> None:
        """Delete stored turns and facts for the current workspace."""
        with self._get_db() as conn:
            if self.workspace:
                conn.execute("DELETE FROM conversation_turns WHERE workspace = ?", (self.workspace,))
                conn.execute("DELETE FROM knowledge_facts WHERE workspace = ?", (self.workspace,))
            else:
                conn.execute("DELETE FROM conversation_turns")
                conn.execute("DELETE FROM knowledge_facts")
            conn.commit()

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Search turns using SQLite FTS5."""
        if self.storage:
            from memory.retrieval import HybridRetrievalEngine
            engine = HybridRetrievalEngine(self.storage)
            res = engine.search_conversation_memory(query, workspace=self.workspace, limit=limit)
        else:
            res = search_conversation_memory(query, workspace=self.workspace, limit=limit)
        return [{"role": r["role"], "content": r["content"], "ts": r.get("created_at", "")} for r in res]

    # ── Structured Facts & ADRs ────────────────────────────────────────────────

    def add_fact(
        self,
        category: str,
        subject: str = "",
        predicate: str = "is",
        object_val: str = "",
        raw_content: str = "",
        confidence: float = 1.0,
        fact_key: Optional[str] = None,
        fact_value: Optional[str] = None,
    ) -> int:
        """Record a structured architectural decision or codebase convention."""
        subj = fact_key or subject
        obj = fact_value if fact_value is not None else (object_val if object_val else predicate)
        pred = predicate if (fact_key is None and object_val != "") else "is"
        raw = raw_content or f"{subj}: {obj}"
        norm_cat = normalize_category(category)
        with self._get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_facts (workspace, category, subject, predicate, object, raw_content, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (self.workspace, norm_cat, subj, pred, obj, raw, confidence)
            )
            conn.commit()
            return cursor.lastrowid

    def get_facts(
        self,
        query: str = "",
        category: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant structured facts."""
        if self.storage:
            from memory.retrieval import HybridRetrievalEngine
            engine = HybridRetrievalEngine(self.storage)
            return engine.search_knowledge_facts(query, workspace=self.workspace, category=category, limit=limit)
        return search_knowledge_facts(query, workspace=self.workspace, category=category, limit=limit)

    def __len__(self) -> int:
        with self._get_db() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM conversation_turns WHERE (? = '' OR workspace = ?)",
                (self.workspace, self.workspace)
            ).fetchone()[0]
