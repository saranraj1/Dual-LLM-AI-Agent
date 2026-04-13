"""
core/logger.py — Structured logging for the AI Agent.

Provides:
- JSON-structured file logging with rotation (agent.log)
- Coloured human-readable console output (WARNING+ only, so it doesn't clutter the terminal)
- Module-level getLogger() helper
- Session ID on every log record for tracing across restarts

Usage:
    from core.logger import get_logger
    log = get_logger(__name__)
    log.info("Task started", extra={"task": "...", "workspace": "..."})
"""

import logging
import logging.handlers
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

# ── Constants ─────────────────────────────────────────────────────────────────
AGENT_HOME  = Path.home() / ".ai_agent"
LOG_DIR     = AGENT_HOME / "logs"
LOG_FILE    = LOG_DIR / "agent.log"
MAX_BYTES   = 5 * 1024 * 1024   # 5 MB per file
BACKUP_COUNT = 5                  # keep 5 rotated files

LOG_DIR.mkdir(parents=True, exist_ok=True)

# Unique ID for this session (appears on every log line for filtering)
SESSION_ID = str(uuid.uuid4())[:8]


# ── JSON formatter ────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Emits one JSON object per log line — machine-readable, grep-friendly."""

    def format(self, record: logging.LogRecord) -> str:
        doc: Dict[str, Any] = {
            "ts":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "session": SESSION_ID,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        # Include any extra= fields the caller passed
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and key not in doc and not key.startswith("_"):
                try:
                    json.dumps(val)   # only include JSON-serialisable values
                    doc[key] = val
                except TypeError:
                    doc[key] = str(val)

        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)

        return json.dumps(doc, ensure_ascii=False)


# ── Coloured console formatter ────────────────────────────────────────────────

_LEVEL_COLOURS = {
    "DEBUG":    "\033[37m",    # grey
    "INFO":     "\033[36m",    # cyan
    "WARNING":  "\033[33m",    # yellow
    "ERROR":    "\033[31m",    # red
    "CRITICAL": "\033[35m",    # magenta
}
_RESET = "\033[0m"


class ConsoleFormatter(logging.Formatter):
    """Human-readable, colour-coded console output."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelname, "")
        ts     = self.formatTime(record, "%H:%M:%S")
        msg    = record.getMessage()
        line   = f"{colour}[{ts}][{record.levelname[0]}][{record.name}]{_RESET} {msg}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# ── Root setup (called once) ──────────────────────────────────────────────────

_configured = False


def _setup_logging(level: int = logging.DEBUG) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("agent")
    root.setLevel(level)
    root.propagate = False

    # ── Rotating file handler (JSON) ──────────────────────────────────────────
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(JSONFormatter())
    root.addHandler(fh)

    # ── Console handler (human-readable, WARNING+ only to stay quiet) ─────────
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(ConsoleFormatter())
    root.addHandler(ch)

    root.info("Agent session started", extra={
        "session": SESSION_ID,
        "pid":     os.getpid(),
        "python":  sys.version.split()[0],
        "log_file": str(LOG_FILE),
    })


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger under the 'agent' hierarchy.

    Args:
        name: Usually __name__ of the calling module.

    Returns:
        A configured Logger instance.

    Example:
        log = get_logger(__name__)
        log.info("Starting task", extra={"task": task_name})
    """
    _setup_logging()
    # Prefix with 'agent.' so all module loggers inherit the root handler
    if not name.startswith("agent"):
        name = f"agent.{name}"
    return logging.getLogger(name)


def get_log_path() -> Path:
    """Return the path to the current log file."""
    return LOG_FILE


def tail_log(n: int = 50) -> str:
    """Return the last n lines of the log file as a string."""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-n:])
    except FileNotFoundError:
        return "(no log file yet)"
