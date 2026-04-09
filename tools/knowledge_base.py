"""
tools/knowledge_base.py — Local document knowledge base.

Index your own PDFs, Word docs, text files, and Markdown notes.
The agent automatically searches relevant snippets into every prompt.

Commands:
    /kb add <file|folder>   → index document(s)
    /kb search <query>      → search indexed knowledge
    /kb list                → list all indexed documents
    /kb clear               → remove all indexed documents

Storage: ~/.ai_agent/knowledge_base.json
"""

import os
import re
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional

KB_PATH = Path.home() / ".ai_agent" / "knowledge_base.json"
KB_PATH.parent.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE  = 800   # chars per chunk
CHUNK_OVER  = 100   # overlap between chunks
MAX_RESULTS = 3     # max chunks returned per search


# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> Dict:
    if KB_PATH.exists():
        try:
            return json.loads(KB_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"docs": {}, "chunks": []}


def _save(db: Dict):
    KB_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_text(path: Path) -> Optional[str]:
    """Extract plaintext from .txt, .md, .py, .pdf, .docx, .csv, .json."""
    ext = path.suffix.lower()

    if ext in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
               ".yaml", ".yml", ".toml", ".ini", ".sh", ".bat"):
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
            try:
                import pdfplumber
                with pdfplumber.open(str(path)) as pdf:
                    return "\n".join(p.extract_text() or "" for p in pdf.pages)
            except ImportError:
                return f"[PDF] Install pypdf to index: pip install pypdf"

    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return f"[DOCX] Install python-docx to index: pip install python-docx"

    if ext == ".csv":
        return path.read_text(encoding="utf-8", errors="ignore")[:5000]

    return None


def _chunk(text: str, source: str) -> List[Dict]:
    """Split text into overlapping chunks with source metadata."""
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i:i + CHUNK_SIZE]
        if chunk.strip():
            chunks.append({
                "source": source,
                "text":   chunk,
                "start":  i,
            })
        i += CHUNK_SIZE - CHUNK_OVER
    return chunks


# ── Public API ────────────────────────────────────────────────────────────────

def kb_add(path_str: str) -> str:
    """Index a file or folder into the knowledge base."""
    db   = _load()
    path = Path(path_str).expanduser().resolve()
    added = []

    if path.is_dir():
        files = [f for f in path.rglob("*") if f.is_file()
                 and f.suffix.lower() in (
                     ".txt", ".md", ".pdf", ".docx", ".py", ".js",
                     ".ts", ".yaml", ".yml", ".json", ".csv", ".sh"
                 )]
    elif path.is_file():
        files = [path]
    else:
        return f"❌ Path not found: {path_str}"

    for f in files:
        text = _extract_text(f)
        if not text or not text.strip():
            continue

        file_hash = hashlib.md5(text.encode()).hexdigest()
        rel       = str(f)

        # Skip if already indexed and unchanged
        existing = db["docs"].get(rel, {})
        if existing.get("hash") == file_hash:
            continue

        # Remove old chunks for this doc
        db["chunks"] = [c for c in db["chunks"] if c["source"] != rel]

        # Add new chunks
        chunks = _chunk(text, rel)
        db["chunks"].extend(chunks)
        db["docs"][rel] = {
            "hash":   file_hash,
            "chunks": len(chunks),
            "size":   len(text),
        }
        added.append(f"  ✅ {f.name} ({len(chunks)} chunks, {len(text):,} chars)")

    _save(db)
    if not added:
        return "ℹ️  No new documents to index (all up to date)"
    return f"📚 Indexed {len(added)} documents:\n" + "\n".join(added)


def kb_search(query: str, max_results: int = MAX_RESULTS) -> List[Dict]:
    """Search knowledge base — returns list of {source, text, score} dicts."""
    db   = _load()
    if not db["chunks"]:
        return []

    query_words = set(re.findall(r'\w+', query.lower()))
    scored = []

    for chunk in db["chunks"]:
        chunk_words = set(re.findall(r'\w+', chunk["text"].lower()))
        overlap     = len(query_words & chunk_words)
        if overlap > 0:
            scored.append({**chunk, "score": overlap})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_results]


def kb_context(query: str) -> str:
    """Build a context string from KB search results for prompt injection."""
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
    db = _load()
    if not db["docs"]:
        return "📭 Knowledge base is empty. Use /kb add <file> to index documents."
    lines = [f"\n📚 Knowledge Base ({len(db['docs'])} documents, {len(db['chunks'])} chunks total)"]
    lines.append("─" * 50)
    for path, meta in db["docs"].items():
        name = Path(path).name
        lines.append(f"  • {name:<30} {meta['chunks']:>3} chunks  {meta['size']:>8,} chars")
        lines.append(f"    {path}")
    lines.append(f"\n  Storage: {KB_PATH}")
    return "\n".join(lines)


def kb_clear() -> str:
    """Clear all indexed documents."""
    _save({"docs": {}, "chunks": []})
    return "🗑️  Knowledge base cleared."


def kb_stats() -> dict:
    db = _load()
    return {"docs": len(db["docs"]), "chunks": len(db["chunks"])}
