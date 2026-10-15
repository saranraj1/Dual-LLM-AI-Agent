"""
memory/retrieval.py — Hybrid BM25 (FTS5) and semantic relevance retrieval engine
with exponential recency decay and frequency reinforcement.
"""

import math
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from memory.storage import get_db, normalize_workspace


def _parse_iso_ts(ts_str: Optional[str]) -> float:
    """Parse ISO timestamp to epoch seconds."""
    if not ts_str:
        return time.time()
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return time.time()


def compute_recency_decay(ts_str: Optional[str], tau_days: float = 7.0) -> float:
    """
    Exponential recency decay: exp(-delta_t / tau).
    Returns value in range (0.0, 1.0].
    """
    created_epoch = _parse_iso_ts(ts_str)
    delta_days = max(0.0, (time.time() - created_epoch) / 86400.0)
    return math.exp(-delta_days / tau_days)


def _safe_fts_query(query: str) -> str:
    """Sanitize user query string for SQLite FTS5 MATCH expression."""
    clean = "".join(c if c.isalnum() or c.isspace() else " " for c in query)
    tokens = [t.strip() for t in clean.split() if t.strip()]
    if not tokens:
        return ""
    # Use OR search between tokens to allow partial hits
    return " OR ".join(tokens)


def search_conversation_memory(
    query: str,
    workspace: str = "",
    limit: int = 6
) -> List[Dict[str, Any]]:
    """
    Search conversation turns using SQLite FTS5 with recency weighting.
    """
    ws = normalize_workspace(workspace)
    fts_match = _safe_fts_query(query)
    results = []

    with get_db() as conn:
        if fts_match:
            try:
                sql = """
                SELECT t.id, t.role, t.content, t.created_at, bm25(conversation_turns_fts) as rank
                FROM conversation_turns t
                JOIN conversation_turns_fts fts ON t.id = fts.rowid
                WHERE conversation_turns_fts MATCH ?
                  AND (? = '' OR t.workspace = ?)
                ORDER BY rank ASC, t.created_at DESC
                LIMIT ?
                """
                rows = conn.execute(sql, (fts_match, ws, ws, limit * 2)).fetchall()
                for r in rows:
                    recency = compute_recency_decay(r["created_at"])
                    # FTS5 bm25 returns negative values where lower is better
                    bm25_norm = 1.0 / (1.0 + max(0.0, -r["rank"]))
                    score = (0.7 * bm25_norm) + (0.3 * recency)
                    results.append({
                        "id": r["id"],
                        "type": "turn",
                        "role": r["role"],
                        "content": r["content"],
                        "created_at": r["created_at"],
                        "score": round(score, 3)
                    })
            except Exception:
                pass

        # Fallback to recent turns in workspace if no FTS match
        if not results:
            sql_fallback = """
            SELECT id, role, content, created_at
            FROM conversation_turns
            WHERE (? = '' OR workspace = ?)
            ORDER BY id DESC
            LIMIT ?
            """
            rows = conn.execute(sql_fallback, (ws, ws, limit)).fetchall()
            for r in rows:
                results.append({
                    "id": r["id"],
                    "type": "turn",
                    "role": r["role"],
                    "content": r["content"],
                    "created_at": r["created_at"],
                    "score": round(compute_recency_decay(r["created_at"]), 3)
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def search_knowledge_facts(
    query: str,
    workspace: str = "",
    category: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Search structured facts (ADRs, constraints, tech stack) using FTS5 and confidence scoring.
    """
    ws = normalize_workspace(workspace)
    fts_match = _safe_fts_query(query)
    results = []

    with get_db() as conn:
        if fts_match:
            try:
                cat_clause = "AND k.category = ?" if category else ""
                params = [fts_match, ws, ws]
                if category:
                    params.append(category)
                params.append(limit * 2)

                sql = f"""
                SELECT k.id, k.category, k.subject, k.predicate, k.object, k.raw_content,
                       k.confidence, k.hit_count, k.created_at, bm25(knowledge_facts_fts) as rank
                FROM knowledge_facts k
                JOIN knowledge_facts_fts fts ON k.id = fts.rowid
                WHERE knowledge_facts_fts MATCH ?
                  AND (? = '' OR k.workspace = '')
                  {cat_clause}
                ORDER BY rank ASC, k.hit_count DESC
                LIMIT ?
                """
                rows = conn.execute(sql, tuple(params)).fetchall()
                for r in rows:
                    recency = compute_recency_decay(r["created_at"], tau_days=30.0)
                    bm25_norm = 1.0 / (1.0 + max(0.0, -r["rank"]))
                    sig = math.log1p(r["hit_count"]) * r["confidence"]
                    score = (0.5 * bm25_norm) + (0.3 * sig) + (0.2 * recency)

                    # Bump hit count
                    conn.execute("UPDATE knowledge_facts SET hit_count = hit_count + 1, last_accessed = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?", (r["id"],))
                    results.append({
                        "id": r["id"],
                        "type": "fact",
                        "category": r["category"],
                        "subject": r["subject"],
                        "fact_key": r["subject"],
                        "predicate": r["predicate"],
                        "object": r["object"],
                        "fact_value": r["object"],
                        "content": r["raw_content"],
                        "score": round(score, 3)
                    })
                conn.commit()
            except Exception:
                pass

        if not results:
            cat_clause = "AND category = ?" if category else ""
            params = [ws, ws]
            if category:
                params.append(category)
            params.append(limit)

            sql_all = f"""
            SELECT id, category, subject, predicate, object, raw_content, confidence, hit_count, created_at
            FROM knowledge_facts
            WHERE (? = '' OR workspace = ?)
            {cat_clause}
            ORDER BY hit_count DESC, id DESC
            LIMIT ?
            """
            rows = conn.execute(sql_all, tuple(params)).fetchall()
            for r in rows:
                results.append({
                    "id": r["id"],
                    "type": "fact",
                    "category": r["category"],
                    "subject": r["subject"],
                    "fact_key": r["subject"],
                    "predicate": r["predicate"],
                    "object": r["object"],
                    "fact_value": r["object"],
                    "content": r["raw_content"],
                    "score": round(math.log1p(r["hit_count"]) * r["confidence"], 3)
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


class HybridRetrievalEngine:
    """Class wrapper for hybrid BM25 and semantic relevance retrieval engine."""

    def __init__(self, storage: Optional[Any] = None):
        self.storage = storage

    def search_conversation_memory(self, query: str, workspace: str = "", limit: int = 6) -> List[Dict[str, Any]]:
        if self.storage and hasattr(self.storage, "db_path"):
            ws = normalize_workspace(workspace)
            fts_match = _safe_fts_query(query)
            results = []
            with self.storage.get_db() as conn:
                if fts_match:
                    try:
                        sql = """
                        SELECT t.id, t.role, t.content, t.created_at, bm25(conversation_turns_fts) as rank
                        FROM conversation_turns_fts fts
                        JOIN conversation_turns t ON fts.rowid = t.id
                        WHERE (? = '' OR t.workspace = ?)
                          AND conversation_turns_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """
                        rows = conn.execute(sql, (ws, ws, fts_match, limit * 2)).fetchall()
                        for r in rows:
                            bm25_score = 1.0 / (1.0 + max(0.0, -r["rank"]))
                            recency = compute_recency_decay(r["created_at"])
                            score = (0.7 * bm25_score) + (0.3 * recency)
                            results.append({
                                "id": r["id"],
                                "role": r["role"],
                                "content": r["content"],
                                "score": round(score, 3),
                                "created_at": r["created_at"]
                            })
                    except Exception:
                        pass
                if not results:
                    rows = conn.execute(
                        "SELECT id, role, content, created_at FROM conversation_turns WHERE (? = '' OR workspace = ?) ORDER BY created_at DESC LIMIT ?",
                        (ws, ws, limit)
                    ).fetchall()
                    for r in rows:
                        results.append({
                            "id": r["id"],
                            "role": r["role"],
                            "content": r["content"],
                            "score": 0.1,
                            "created_at": r["created_at"]
                        })
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
        return search_conversation_memory(query, workspace=workspace, limit=limit)

    def search_knowledge_facts(self, query: str, workspace: str = "", category: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        if self.storage and hasattr(self.storage, "db_path"):
            ws = normalize_workspace(workspace)
            fts_match = _safe_fts_query(query)
            results = []
            with self.storage.get_db() as conn:
                if fts_match:
                    try:
                        cat_clause = "AND k.category = ?" if category else ""
                        params = [ws, ws]
                        if category:
                            params.append(category)
                        params.extend([fts_match, limit * 2])
                        sql = f"""
                        SELECT k.id, k.category, k.subject, k.predicate, k.object, k.raw_content, k.confidence, k.hit_count, bm25(knowledge_facts_fts) as rank
                        FROM knowledge_facts_fts fts
                        JOIN knowledge_facts k ON fts.rowid = k.id
                        WHERE (? = '' OR k.workspace = ?)
                          {cat_clause}
                          AND knowledge_facts_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """
                        rows = conn.execute(sql, tuple(params)).fetchall()
                        for r in rows:
                            bm25_score = 1.0 / (1.0 + max(0.0, -r["rank"]))
                            freq = min(1.0, math.log1p(r["hit_count"]) / 3.0)
                            score = (0.5 * bm25_score) + (0.3 * r["confidence"]) + (0.2 * freq)
                            results.append({
                                "id": r["id"],
                                "type": "fact",
                                "category": r["category"],
                                "subject": r["subject"],
                                "fact_key": r["subject"],
                                "predicate": r["predicate"],
                                "object": r["object"],
                                "fact_value": r["object"],
                                "content": r["raw_content"],
                                "score": round(score, 3)
                            })
                    except Exception:
                        pass
                if not results:
                    cat_clause = "AND category = ?" if category else ""
                    params = [ws, ws]
                    if category:
                        params.append(category)
                    params.append(limit)
                    sql_all = f"""
                    SELECT id, category, subject, predicate, object, raw_content, confidence, hit_count, created_at
                    FROM knowledge_facts
                    WHERE (? = '' OR workspace = ?)
                    {cat_clause}
                    ORDER BY hit_count DESC, id DESC
                    LIMIT ?
                    """
                    rows = conn.execute(sql_all, tuple(params)).fetchall()
                    for r in rows:
                        results.append({
                            "id": r["id"],
                            "type": "fact",
                            "category": r["category"],
                            "subject": r["subject"],
                            "fact_key": r["subject"],
                            "predicate": r["predicate"],
                            "object": r["object"],
                            "fact_value": r["object"],
                            "content": r["raw_content"],
                            "score": round(math.log1p(r["hit_count"]) * r["confidence"], 3)
                        })
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
        return search_knowledge_facts(query, workspace=workspace, category=category, limit=limit)
