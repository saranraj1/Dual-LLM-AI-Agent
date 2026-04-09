"""
memory/long_memory.py — Persistent memory saved to ~/.ai_agent/long_memory.json.
Survives across sessions. Auto-compresses old turns into a summary.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from config.settings import LONG_MEMORY_FILE

MAX_VERBATIM_TURNS = 15
MAX_SUMMARY_CHARS  = 1500
MAX_TOTAL_TURNS    = 150


class LongMemory:
    def __init__(self):
        self.path = Path(LONG_MEMORY_FILE)
        self.data = self._load()

    def _load(self) -> Dict:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "created": datetime.now().isoformat(),
            "summary": "",
            "turns":   [],
            "file_notes": {}
        }

    def save(self):
        if len(self.data["turns"]) > MAX_TOTAL_TURNS:
            self._compress()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # ── Public API ────────────────────────────────────────────────────────────

    def add(self, role: str, content: str):
        self.data["turns"].append({
            "role":    role,
            "content": content,
            "ts":      datetime.now().isoformat()
        })

    def get_context(self, max_chars: int = 800) -> str:
        parts = []
        if self.data.get("summary"):
            parts.append(f"[Earlier summary]\n{self.data['summary'][:400]}")
        recent = self.data["turns"][-MAX_VERBATIM_TURNS:]
        if recent:
            lines = []
            for t in recent:
                c = t["content"][:200].replace("\n", " ")
                lines.append(f"{t['role'].capitalize()}: {c}")
            parts.append("\n".join(lines))
        full = "\n\n".join(parts)
        return full[-max_chars:] if len(full) > max_chars else full

    def note_file(self, path: str, note: str):
        """Remember something about a specific file."""
        self.data["file_notes"][path] = {
            "note": note, "ts": datetime.now().isoformat()
        }
        self.save()

    def get_file_note(self, path: str) -> Optional[str]:
        entry = self.data.get("file_notes", {}).get(path)
        return entry["note"] if entry else None

    def clear(self):
        self.data["summary"]    = ""
        self.data["turns"]      = []
        self.data["file_notes"] = {}
        self.save()

    def stats(self) -> Dict:
        return {
            "turns":       len(self.data["turns"]),
            "summary_len": len(self.data.get("summary", "")),
            "file_notes":  len(self.data.get("file_notes", {})),
            "file":        str(self.path)
        }

    # ── Compression ───────────────────────────────────────────────────────────

    def _compress(self):
        turns    = self.data["turns"]
        cutoff   = len(turns) - MAX_VERBATIM_TURNS
        old      = turns[:cutoff]
        keep     = turns[cutoff:]
        lines    = [
            f"{t['role'].capitalize()}: {t['content'][:150].replace(chr(10),' ')}"
            for t in old
        ]
        new_block = "\n".join(lines)
        combined  = (self.data.get("summary", "") + "\n" + new_block).strip()
        if len(combined) > MAX_SUMMARY_CHARS:
            combined = combined[-MAX_SUMMARY_CHARS:]
        self.data["summary"] = combined
        self.data["turns"]   = keep
