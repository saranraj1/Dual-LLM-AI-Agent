"""
core/ui.py — Terminal colors, spinner, and formatted output utilities.
All output in the agent goes through here for a consistent, rich UI.
"""

import sys
import time
import threading
import os

# ── ANSI colour codes ─────────────────────────────────────────────────────────
# Only emit codes when stdout is a real terminal (not piped/redirected)
_COLORS = os.environ.get("NO_COLOR") is None and sys.stdout.isatty()

class C:
    RESET   = "\033[0m"   if _COLORS else ""
    BOLD    = "\033[1m"   if _COLORS else ""
    DIM     = "\033[2m"   if _COLORS else ""
    # Foreground
    RED     = "\033[91m"  if _COLORS else ""
    GREEN   = "\033[92m"  if _COLORS else ""
    YELLOW  = "\033[93m"  if _COLORS else ""
    BLUE    = "\033[94m"  if _COLORS else ""
    MAGENTA = "\033[95m"  if _COLORS else ""
    CYAN    = "\033[96m"  if _COLORS else ""
    WHITE   = "\033[97m"  if _COLORS else ""
    GRAY    = "\033[90m"  if _COLORS else ""
    # Combined shortcuts
    SUCCESS = "\033[92m"  if _COLORS else ""
    WARN    = "\033[93m"  if _COLORS else ""
    ERROR   = "\033[91m"  if _COLORS else ""
    INFO    = "\033[96m"  if _COLORS else ""
    AGENT   = "\033[95m"  if _COLORS else ""
    USER    = "\033[94m"  if _COLORS else ""
    STEP    = "\033[93m"  if _COLORS else ""
    CODE    = "\033[36m"  if _COLORS else ""


def ok(msg: str)   -> str: return f"{C.SUCCESS}✅ {msg}{C.RESET}"
def warn(msg: str) -> str: return f"{C.WARN}⚠️  {msg}{C.RESET}"
def err(msg: str)  -> str: return f"{C.ERROR}❌ {msg}{C.RESET}"
def info(msg: str) -> str: return f"{C.INFO}ℹ️  {msg}{C.RESET}"
def step(msg: str) -> str: return f"{C.STEP}▶  {msg}{C.RESET}"
def dim(msg: str)  -> str: return f"{C.GRAY}{msg}{C.RESET}"
def bold(msg: str) -> str: return f"{C.BOLD}{msg}{C.RESET}"
def agent_label()  -> str: return f"{C.AGENT}{C.BOLD}Agent ›{C.RESET} "
def user_label()   -> str: return f"{C.USER}{C.BOLD}You ›{C.RESET} "


# ── Spinner ───────────────────────────────────────────────────────────────────

class Spinner:
    """
    Thread-based terminal spinner. Usage:

        with Spinner("Thinking"):
            result = do_slow_thing()
    """
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = "Thinking", color: str = ""):
        self.label   = label
        self.color   = color or C.CYAN
        self._stop   = threading.Event()
        self._thread = None

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = self._FRAMES[i % len(self._FRAMES)]
            sys.stdout.write(f"\r{self.color}{frame}{C.RESET} {C.DIM}{self.label}...{C.RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
        # Clear the spinner line
        sys.stdout.write("\r" + " " * (len(self.label) + 10) + "\r")
        sys.stdout.flush()

    def start(self):
        if sys.stdout.isatty():
            self._stop.clear()
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


# ── Formatted printers ────────────────────────────────────────────────────────

def print_separator(char: str = "─", width: int = 55, color: str = ""):
    c = color or C.GRAY
    print(f"{c}{char * width}{C.RESET}")


def print_header(title: str, width: int = 55):
    print(f"\n{C.BOLD}{C.MAGENTA}{'═' * width}{C.RESET}")
    padding = (width - len(title) - 2) // 2
    print(f"{C.BOLD}{C.MAGENTA}║{' ' * padding}{title}{' ' * (width - padding - len(title) - 2)}║{C.RESET}")
    print(f"{C.BOLD}{C.MAGENTA}{'═' * width}{C.RESET}\n")


def print_task_start(task: str, workspace: str):
    print(f"\n{C.BOLD}{C.BLUE}{'='*55}{C.RESET}")
    print(f"{C.BOLD}🤖 Task:{C.RESET} {task}")
    print(f"{C.GRAY}📁 Workspace: {workspace}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}{'='*55}{C.RESET}")


def print_step(i: int, total: int, desc: str):
    print(f"\n{C.GRAY}{'─'*50}{C.RESET}")
    print(f"{C.YELLOW}{C.BOLD}▶ Step {i}/{total}:{C.RESET} {desc}")


def print_reflection(msg: str):
    print(f"   {C.GRAY}{msg}{C.RESET}")


def stream_token(token: str):
    """Write a single streamed token — no newline, immediate flush."""
    sys.stdout.write(token)
    sys.stdout.flush()


def print_token_stats(prompt_tokens: int, gen_tokens: int, elapsed: float, backend: str):
    tps = gen_tokens / max(elapsed, 0.01)
    print(f"\n{C.GRAY}[{backend} · {gen_tokens} tokens · {tps:.0f} tok/s · {elapsed:.1f}s]{C.RESET}")
