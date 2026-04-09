"""
tools/file_tools.py — File system tools: read, write, scan, search.
These are what make the agent "file-aware".
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from config.settings import SUPPORTED_EXTENSIONS, SKIP_DIRS, ALLOW_WRITE


def read_file(path: str) -> Dict:
    """Read a file and return its content with metadata."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if not p.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}
        content = p.read_text(encoding="utf-8", errors="ignore")
        lines   = content.splitlines()
        return {
            "ok":      True,
            "path":    str(p),
            "content": content,
            "lines":   len(lines),
            "size":    p.stat().st_size
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def write_file(path: str, content: str) -> Dict:
    """Write content to a file. Creates directories if needed."""
    if not ALLOW_WRITE:
        return {"ok": False, "error": "Write disabled in settings.py (ALLOW_WRITE=False)"}
    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(p), "bytes": len(content.encode())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def append_file(path: str, content: str) -> Dict:
    """Append content to a file."""
    if not ALLOW_WRITE:
        return {"ok": False, "error": "Write disabled (ALLOW_WRITE=False)"}
    try:
        p = Path(path).resolve()
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_dir(root: str, depth: int = 2) -> Dict:
    """List files in a directory up to a given depth."""
    try:
        root_path = Path(root).resolve()
        if not root_path.exists():
            return {"ok": False, "error": f"Directory not found: {root}"}
        tree = []
        for fp in root_path.rglob("*"):
            # Skip unwanted dirs
            if any(skip in fp.parts for skip in SKIP_DIRS):
                continue
            # Depth check
            rel = fp.relative_to(root_path)
            if len(rel.parts) > depth:
                continue
            tree.append({
                "path": str(rel),
                "type": "dir" if fp.is_dir() else "file",
                "ext":  fp.suffix.lower()
            })
        return {"ok": True, "root": str(root_path), "entries": tree}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def scan_codebase(root: str, max_files: int = 25) -> Dict:
    """
    Index a project: return {relative_path: content} for all code files.
    Caps content per file at 2000 chars to stay within token budget.
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        return {"ok": False, "error": f"Not found: {root}"}

    index = {}
    for fp in root_path.rglob("*"):
        if not fp.is_file():
            continue
        if any(skip in fp.parts for skip in SKIP_DIRS):
            continue
        if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if len(index) >= max_files:
            break
        rel     = str(fp.relative_to(root_path))
        content = fp.read_text(encoding="utf-8", errors="ignore")
        index[rel] = content[:2000]

    return {"ok": True, "root": str(root_path), "files": index, "count": len(index)}


def search_in_files(root: str, pattern: str, max_results: int = 20) -> Dict:
    """
    Search for a regex pattern across all code files in a directory.
    Returns list of {file, line_no, line_content} matches.
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        return {"ok": False, "error": f"Not found: {root}"}
    try:
        regex   = re.compile(pattern, re.IGNORECASE)
        matches = []
        for fp in root_path.rglob("*"):
            if not fp.is_file():
                continue
            if any(skip in fp.parts for skip in SKIP_DIRS):
                continue
            if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        matches.append({
                            "file":    str(fp.relative_to(root_path)),
                            "line_no": i,
                            "content": line.strip()[:120]
                        })
                        if len(matches) >= max_results:
                            break
            except Exception:
                continue
            if len(matches) >= max_results:
                break
        return {"ok": True, "pattern": pattern, "matches": matches, "count": len(matches)}
    except re.error as e:
        return {"ok": False, "error": f"Bad regex: {e}"}


def build_context_string(scan_result: Dict, char_limit: int = 2500) -> str:
    """Convert scan_codebase result into a prompt-ready string."""
    if not scan_result.get("ok"):
        return ""
    parts = []
    total = 0
    for rel_path, content in scan_result["files"].items():
        chunk = f"### {rel_path}\n```\n{content}\n```"
        if total + len(chunk) > char_limit:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
