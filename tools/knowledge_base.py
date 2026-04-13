"""
tools/knowledge_base.py — Semantic vector search knowledge base (Step 5).

Upgrades from keyword overlap scoring to true semantic embeddings using
sentence-transformers (all-MiniLM-L6-v2).

Embeddings are stored as BLOBs in SQLite for fast retrieval with no
external vector DB required.

Falls back to keyword search if sentence-transformers is not installed,
so the agent still works without the optional dependency.

Install for full semantic search:
    pip install sentence-transformers
"""

import os
import re
import json
import sqlite3
import hashlib
import struct
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from core.exceptions import KnowledgeBaseError

# ── Storage paths ─────────────────────────────────────────────────────────────

AGENT_HOME   = Path.home() / ".ai_agent"
KB_DB_PATH   = AGENT_HOME / "knowledge_base.db"
AGENT_HOME.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE   = 800
CHUNK_OVER   = 100
MAX_RESULTS  = 3
EMBED_MODEL  = "all-MiniLM-L6-v2"

# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT UNIQUE NOT NULL,
    file_hash TEXT NOT NULL,
    chunks    INTEGER DEFAULT 0,
    size      INTEGER DEFAULT 0,
    indexed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source    TEXT NOT NULL,
    text      TEXT NOT NULL,
    start_pos INTEGER DEFAULT 0,
    embedding BLOB    -- NULL when sentence-transformers not installed
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
"""


# ── DB connection ─────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(KB_DB_PATH))
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    c.executescript(_SCHEMA)
    c.commit()
    return c


# ── Embedding helpers ─────────────────────────────────────────────────────────

_model = None  # lazy-loaded

def _get_model():
    """Lazy-load the sentence-transformers model once."""
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
        return _model
    except ImportError:
        return None


def _embed(text: str) -> Optional[bytes]:
    """Return embedding as raw bytes, or None if model unavailable."""
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return struct.pack(f"{len(vec)}f", *vec)
    except Exception:
        return None


def _decode_embed(blob: bytes) -> Optional[list]:
    """Decode stored blob back to float list."""
    if blob is None:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a: list, b: list) -> float:
    """Cosine similarity between two normalised vectors."""
    return sum(x * y for x, y in zip(a, b))


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_text(path: Path) -> Optional[str]:
    """Extract plain text from supported file types."""
    ext = path.suffix.lower()

    if ext in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
               ".yaml", ".yml", ".toml", ".ini", ".sh", ".bat", ".rst"):
        return path.read_text(encoding="utf-8", errors="ignore")

    if ext == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(data, indent=2)[:5000]
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")

    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            return "[PDF] Install pypdf: pip install pypdf"

    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return "[DOCX] Install python-docx: pip install python-docx"

    if ext == ".csv":
        return path.read_text(encoding="utf-8", errors="ignore")[:5000]

    return None


def _chunk_text(text: str, source: str) -> List[Dict]:
    """Split text into overlapping chunks."""
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i : i + CHUNK_SIZE]
        if chunk.strip():
            chunks.append({"source": source, "text": chunk, "start": i})
        i += CHUNK_SIZE - CHUNK_OVER
    return chunks


# ── Public API ────────────────────────────────────────────────────────────────

def kb_add(path_str: str) -> str:
    """Index a file or folder into the knowledge base."""
    path = Path(path_str).expanduser().resolve()

    if path.is_dir():
        files = [
            f for f in path.rglob("*")
            if f.is_file() and f.suffix.lower() in (
                ".txt", ".md", ".pdf", ".docx", ".py", ".js",
                ".ts", ".yaml", ".yml", ".json", ".csv", ".sh", ".rst"
            )
        ]
    elif path.is_file():
        files = [path]
    else:
        return f"❌ Path not found: {path_str}"

    has_semantic = _get_model() is not None
    if has_semantic:
        mode = "🧠 semantic"
    else:
        mode = "🔤 keyword (pip install sentence-transformers for semantic)"

    added = []
    db = _conn()
    try:
        for f in files:
            try:
                text = _extract_text(f)
                if not text or not text.strip():
                    continue

                file_hash = hashlib.md5(text.encode()).hexdigest()
                rel = str(f)

                # Check if already indexed and unchanged
                row = db.execute(
                    "SELECT id, file_hash FROM documents WHERE path = ?", (rel,)
                ).fetchone()

                if row and row[1] == file_hash:
                    continue  # up to date

                # Delete old chunks
                if row:
                    db.execute("DELETE FROM chunks WHERE doc_id = ?", (row[0],))
                    db.execute("DELETE FROM documents WHERE id = ?", (row[0],))

                # Insert document
                db.execute(
                    "INSERT INTO documents (path, file_hash, chunks, size) VALUES (?, ?, ?, ?)",
                    (rel, file_hash, 0, len(text))
                )
                doc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                # Insert chunks
                chunks = _chunk_text(text, rel)
                for ch in chunks:
                    emb = _embed(ch["text"])
                    db.execute(
                        "INSERT INTO chunks (doc_id, source, text, start_pos, embedding) VALUES (?,?,?,?,?)",
                        (doc_id, rel, ch["text"], ch["start"], emb)
                    )
                db.execute(
                    "UPDATE documents SET chunks = ? WHERE id = ?",
                    (len(chunks), doc_id)
                )
                db.commit()
                added.append(f"  ✅ {f.name} ({len(chunks)} chunks, {len(text):,} chars)")

            except Exception as e:
                added.append(f"  ⚠️  {f.name}: {e}")
    finally:
        db.close()

    if not added:
        return "ℹ️  No new documents to index (all up to date)"
    return f"📚 Indexed {len(added)} documents [{mode}]:\n" + "\n".join(added)


def kb_search(query: str, max_results: int = MAX_RESULTS) -> List[Dict]:
    """
    Search the knowledge base.
    Uses semantic cosine similarity if embeddings are available,
    falls back to keyword overlap scoring otherwise.
    Returns list of {source, text, score} dicts.
    """
    db = _conn()
    try:
        rows = db.execute(
            "SELECT source, text, embedding FROM chunks"
        ).fetchall()
    finally:
        db.close()

    if not rows:
        return []

    query_emb = _embed(query)

    if query_emb is not None:
        # ── Semantic search ───────────────────────────────────────────────
        q_vec = _decode_embed(query_emb)
        scored = []
        for source, text, blob in rows:
            if blob is None:
                continue
            vec = _decode_embed(blob)
            if vec:
                score = _cosine(q_vec, vec)
                scored.append({"source": source, "text": text, "score": round(score, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
    else:
        # ── Keyword fallback ──────────────────────────────────────────────
        query_words = set(re.findall(r"\w+", query.lower()))
        scored = []
        for source, text, _ in rows:
            chunk_words = set(re.findall(r"\w+", text.lower()))
            overlap = len(query_words & chunk_words)
            if overlap > 0:
                scored.append({"source": source, "text": text, "score": overlap})
        scored.sort(key=lambda x: x["score"], reverse=True)

    return scored[:max_results]


def kb_context(query: str) -> str:
    """Build prompt-injection string from KB search results."""
    results = kb_search(query)
    if not results:
        return ""
    lines = ["## Knowledge Base Context"]
    for r in results:
        src = Path(r["source"]).name
        lines.append(f"\n### From: {src}\n{r['text']}\n")
    return "\n".join(lines)


def kb_list() -> str:
    """List all indexed documents."""
    db = _conn()
    try:
        docs = db.execute(
            "SELECT path, file_hash, chunks, size, indexed_at FROM documents ORDER BY indexed_at DESC"
        ).fetchall()
        total_chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        db.close()

    if not docs:
        return "📭 Knowledge base is empty. Use /kb add <file> to index documents."

    has_semantic = _get_model() is not None
    mode = "🧠 Semantic (sentence-transformers)" if has_semantic else "🔤 Keyword"

    lines = [
        f"\n📚 Knowledge Base — {len(docs)} docs, {total_chunks} chunks  [{mode}]",
        "─" * 55,
    ]
    for path, _, chunks, size, ts in docs:
        name = Path(path).name
        lines.append(f"  • {name:<30} {chunks:>3} chunks  {size:>8,} chars")
        lines.append(f"    {path}")
    lines.append(f"\n  DB: {KB_DB_PATH}")
    return "\n".join(lines)


def kb_clear() -> str:
    """Remove all indexed documents and chunks."""
    db = _conn()
    try:
        db.execute("DELETE FROM chunks")
        db.execute("DELETE FROM documents")
        db.commit()
    finally:
        db.close()
    return "🗑️  Knowledge base cleared."


def kb_stats() -> dict:
    db = _conn()
    try:
        docs   = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        has_emb = db.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0]
    finally:
        db.close()
    return {
        "docs":          docs,
        "chunks":        chunks,
        "semantic":      has_emb > 0,
        "model_loaded":  _get_model() is not None,
    }
