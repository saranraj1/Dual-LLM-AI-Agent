"""
memory/storage.py — Thread-safe connection management and storage driver
for the 4-tier hybrid memory subsystem.
"""

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Generator, Any, List, Dict
from contextlib import contextmanager

from memory.schema import SCHEMA_SQL

AGENT_HOME = Path.home() / ".ai_agent"
DB_PATH = AGENT_HOME / "agent_memory_v2.db"
DEFAULT_DB_PATH = DB_PATH
LEGACY_LONG_DB = AGENT_HOME / "long_memory.db"
LEGACY_FIX_DB = AGENT_HOME / "fix_memory.db"

AGENT_HOME.mkdir(parents=True, exist_ok=True)

VALID_CATEGORIES = {'adr', 'convention', 'constraint', 'stack', 'user_preference'}

def normalize_category(category: str) -> str:
    cat = (category or "").lower().strip()
    if cat in VALID_CATEGORIES:
        return cat
    if "adr" in cat or "decision" in cat:
        return "adr"
    if any(k in cat for k in ["stack", "tech", "lang", "db", "database", "framework"]):
        return "stack"
    if any(k in cat for k in ["limit", "constraint", "security", "never", "must", "rule"]):
        return "constraint"
    if any(k in cat for k in ["pref", "user", "style"]):
        return "user_preference"
    return "convention"

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False


def _migrate_legacy_data(conn: sqlite3.Connection):
    """Seamlessly migrate existing legacy long_memory and fix_memory into v2 schema."""
    # 1. Migrate long_memory.db
    if LEGACY_LONG_DB.exists():
        try:
            legacy_conn = sqlite3.connect(str(LEGACY_LONG_DB))
            legacy_conn.row_factory = sqlite3.Row
            cursor = legacy_conn.cursor()
            rows = cursor.execute("SELECT role, content, workspace, ts FROM memory").fetchall()
            for r in rows:
                conn.execute(
                    """
                    INSERT INTO conversation_turns (session_id, workspace, role, content, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("legacy", r["workspace"] or "", r["role"], r["content"], r["ts"] or "")
                )
            conn.commit()
            legacy_conn.close()
        except Exception:
            pass

    # 2. Migrate fix_memory.db
    if LEGACY_FIX_DB.exists():
        try:
            legacy_fix = sqlite3.connect(str(LEGACY_FIX_DB))
            legacy_fix.row_factory = sqlite3.Row
            rows = legacy_fix.execute("SELECT error_sig, error_text, fix_desc, file_type, hits, last_seen FROM fix_patterns").fetchall()
            for r in rows:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO procedural_rules (error_sig, error_pattern, repair_action, file_type, success_count, last_triggered)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (r["error_sig"], r["error_text"], r["fix_desc"], r["file_type"], r["hits"], r["last_seen"])
                )
            conn.commit()
            legacy_fix.close()
        except Exception:
            pass


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Get thread-local connection with WAL mode and foreign keys enabled.
    """
    global _initialized
    target_path = str(db_path or DB_PATH)

    # Initialize schema on first run
    if not _initialized:
        with _init_lock:
            if not _initialized:
                init_conn = sqlite3.connect(target_path, check_same_thread=False)
                init_conn.execute("PRAGMA journal_mode=WAL;")
                init_conn.execute("PRAGMA synchronous=NORMAL;")
                init_conn.executescript(SCHEMA_SQL)
                init_conn.commit()
                _migrate_legacy_data(init_conn)
                init_conn.close()
                _initialized = True

    if not hasattr(_local, "connection") or _local.target_path != target_path:
        conn = sqlite3.connect(target_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        _local.connection = conn
        _local.target_path = target_path

    return _local.connection


@contextmanager
def get_db(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for thread-safe database operations."""
    conn = get_connection(db_path)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise


def normalize_workspace(workspace: Optional[str]) -> str:
    """Normalize workspace directory path to absolute string."""
    if not workspace:
        return ""
    try:
        return os.path.abspath(workspace).replace("\\", "/")
    except Exception:
        return str(workspace).replace("\\", "/")


class MemoryStorage:
    """Instance-based storage driver for memory operations with optional custom DB path."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self._init_db()

    def _init_db(self):
        init_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        init_conn.execute("PRAGMA journal_mode=WAL;")
        init_conn.execute("PRAGMA synchronous=NORMAL;")
        init_conn.executescript(SCHEMA_SQL)
        init_conn.commit()
        init_conn.close()

    @contextmanager
    def get_db(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def add_turn(self, role: str, content: str, workspace: str = "", session_id: str = "default") -> int:
        norm_ws = normalize_workspace(workspace)
        with self.get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO conversation_turns (session_id, workspace, role, content, token_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, norm_ws, role, content[:2000], len(content) // 4)
            )
            conn.commit()
            return cur.lastrowid

    def get_turns(self, workspace: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        norm_ws = normalize_workspace(workspace)
        with self.get_db() as conn:
            if norm_ws:
                rows = conn.execute(
                    "SELECT id, session_id, workspace, role, content, created_at FROM conversation_turns WHERE workspace = ? ORDER BY created_at DESC LIMIT ?",
                    (norm_ws, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, session_id, workspace, role, content, created_at FROM conversation_turns ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def add_fact(self, category: str, fact_key: str, fact_value: str, workspace: str = "", confidence: float = 1.0) -> int:
        norm_ws = normalize_workspace(workspace)
        norm_cat = normalize_category(category)
        with self.get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_facts (workspace, category, subject, predicate, object, raw_content, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (norm_ws, norm_cat, fact_key, "is", fact_value, f"{fact_key}: {fact_value}", confidence)
            )
            conn.commit()
            return cur.lastrowid

    def get_facts(self, workspace: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        norm_ws = normalize_workspace(workspace)
        with self.get_db() as conn:
            if norm_ws:
                rows = conn.execute(
                    "SELECT id, workspace, category, subject as fact_key, object as fact_value, confidence, created_at FROM knowledge_facts WHERE workspace = ? ORDER BY hit_count DESC, created_at DESC LIMIT ?",
                    (norm_ws, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, workspace, category, subject as fact_key, object as fact_value, confidence, created_at FROM knowledge_facts ORDER BY hit_count DESC, created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def record_procedural_rule(self, error_sig: str, error_snippet: str, fix_action: str, file_type: str = ".py") -> int:
        with self.get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO procedural_rules (error_sig, error_pattern, repair_action, file_type)
                VALUES (?, ?, ?, ?)
                """,
                (error_sig, error_snippet, fix_action, file_type)
            )
            conn.commit()
            return cur.lastrowid

    def get_procedural_rules(self, error_sig: str) -> List[Dict[str, Any]]:
        with self.get_db() as conn:
            rows = conn.execute(
                "SELECT id, error_sig, error_pattern, repair_action as fix_action, file_type FROM procedural_rules WHERE error_sig = ?",
                (error_sig,)
            ).fetchall()
            return [dict(r) for r in rows]

    def clear(self, workspace: str = "") -> None:
        norm_ws = normalize_workspace(workspace)
        with self.get_db() as conn:
            if norm_ws:
                conn.execute("DELETE FROM conversation_turns WHERE workspace = ?", (norm_ws,))
                conn.execute("DELETE FROM knowledge_facts WHERE workspace = ?", (norm_ws,))
            else:
                conn.execute("DELETE FROM conversation_turns")
                conn.execute("DELETE FROM knowledge_facts")
            conn.commit()
