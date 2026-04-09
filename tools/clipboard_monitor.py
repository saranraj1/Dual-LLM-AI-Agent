"""
tools/clipboard_monitor.py — Real-time clipboard code detection.

Runs as a background daemon thread. When new code is detected in the
clipboard (based on code-like patterns), it optionally auto-reviews it.

Usage:
    monitor = ClipboardMonitor(agent)
    monitor.start()   # starts background thread
    monitor.stop()    # stops it
    monitor.toggle()  # toggle on/off
"""

import re
import sys
import time
import threading
import subprocess
from typing import Optional, Callable


# Code detection heuristics — if content matches 3+ patterns, it's likely code
_CODE_PATTERNS = [
    r'\bdef \w+\s*\(',          # Python function
    r'\bclass \w+[\(:]',        # Python/JS class
    r'\bimport \w+',            # import statement
    r'\bfrom \w+ import',       # from import
    r'\bfunction\s+\w+\s*\(',   # JS function
    r'\bconst |let |var ',      # JS vars
    r'^\s*(if|for|while|try)\b',# control flow
    r'#.*$|//.*$|/\*',         # comments
    r'\{[\s\S]*\}',             # braces block
    r'=>\s*\{|=>\s*\w+',        # arrow functions
    r':\s*(str|int|float|list|dict|bool)\b',  # Python type hints
    r'\bself\.',                # Python self
    r'print\(|console\.log\(',  # print/log
    r'return\s+\w+',            # return statement
    r'async\s+def |await ',     # async code
]

_MIN_LINES      = 3      # ignore single-line snippets
_MIN_CHARS      = 40     # ignore tiny clips
_MAX_CHARS      = 8000   # ignore huge blobs (not code)
_POLL_INTERVAL  = 1.0    # seconds between clipboard checks


def _get_clipboard() -> str:
    """Read current clipboard contents (Windows)."""
    if sys.platform != "win32":
        return ""
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=2,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _is_code(text: str) -> bool:
    """Heuristic: does this clipboard content look like code?"""
    if len(text) < _MIN_CHARS or len(text) > _MAX_CHARS:
        return False
    lines = text.splitlines()
    if len(lines) < _MIN_LINES:
        return False

    matches = sum(1 for p in _CODE_PATTERNS
                  if re.search(p, text, re.MULTILINE))
    return matches >= 3


class ClipboardMonitor:
    """Background thread that watches clipboard for code snippets."""

    def __init__(self, on_code_detected: Callable[[str], None]):
        """
        Args:
            on_code_detected: callback called with the code string when new code detected
        """
        self._callback  = on_code_detected
        self._last      = ""
        self._running   = False
        self._enabled   = True
        self._thread: Optional[threading.Thread] = None
        self._lock      = threading.Lock()

    def start(self):
        """Start the background monitor thread."""
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="ClipboardMonitor")
        self._thread.start()

    def stop(self):
        """Stop the background monitor thread."""
        self._running = False

    def toggle(self) -> bool:
        """Toggle on/off. Returns new state (True = enabled)."""
        with self._lock:
            self._enabled = not self._enabled
        return self._enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _loop(self):
        while self._running:
            try:
                if self._enabled:
                    current = _get_clipboard()
                    if current and current != self._last and _is_code(current):
                        self._last = current
                        # Small debounce — wait 0.5s then check it hasn't changed
                        time.sleep(0.5)
                        if _get_clipboard() == current:
                            self._callback(current)
                    elif current != self._last:
                        self._last = current
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL)
