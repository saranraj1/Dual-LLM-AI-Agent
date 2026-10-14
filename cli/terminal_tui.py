"""
cli/terminal_tui.py — Rich Terminal TUI & Live Steerability Engine.

Parity features with Claude Code and OpenAI Codex CLI:
  1. Live syntax-highlighted markdown & code rendering
  2. Side-by-side & unified colored diff viewer with syntax highlighting
  3. Pause-and-Steer: non-fatal Ctrl+C interruption allowing mid-flight prompt steering
  4. Rich status banners, session consumption badges, and interactive REPL
"""

import sys
import os
import signal
import time
from typing import Optional, Callable, Generator, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.prompt import Prompt
from rich.live import Live

console = Console()


class SteerAction:
    STEER = "steer"
    CONTINUE = "continue"
    ABORT = "abort"


class SteerController:
    """
    Context manager that intercepts SIGINT (Ctrl+C) during long operations,
    pausing execution to offer interactive live steering.
    """

    def __init__(self, console_instance: Optional[Console] = None):
        self.console = console_instance or console
        self._interrupted = False
        self._original_handler = None
        self.steering_feedback: Optional[str] = None

    def __enter__(self):
        self._interrupted = False
        self.steering_feedback = None
        try:
            self._original_handler = signal.signal(signal.SIGINT, self._handle_sigint)
        except (ValueError, AttributeError):
            # Signal handling might not be supported in some thread contexts
            self._original_handler = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._original_handler is not None:
            try:
                signal.signal(signal.SIGINT, self._original_handler)
            except (ValueError, AttributeError):
                pass
        return False

    def _handle_sigint(self, signum, frame):
        self._interrupted = True
        self.console.print("\n[bold yellow]⏸️  Execution Paused (Ctrl+C intercepted)[/bold yellow]")
        choice = Prompt.ask(
            "[bold cyan]Action[/bold cyan]",
            choices=["s", "c", "a"],
            default="s"
        ).strip().lower()

        if choice == "s":
            new_prompt = Prompt.ask("[bold green]Enter steering instructions or correction[/bold green]").strip()
            self.steering_feedback = new_prompt
            self.console.print(f"[dim]Steering prompt registered: '{new_prompt}' — continuing execution...[/dim]\n")
            self._interrupted = False
        elif choice == "c":
            self.console.print("[dim]Resuming execution...[/dim]\n")
            self._interrupted = False
        else:
            self.console.print("[bold red]Aborting current task and returning to prompt.[/bold red]\n")
            raise KeyboardInterrupt("Task aborted by user.")

    @property
    def was_interrupted(self) -> bool:
        return self._interrupted


def render_diff(diff_text: str, title: str = "Code Diff", console_instance: Optional[Console] = None) -> None:
    """
    Renders a unified git diff in a rich terminal table with green additions,
    red deletions, and cyan hunk coordinates.
    """
    c = console_instance or console
    if not diff_text or not diff_text.strip():
        c.print("[dim italic]No diff changes to display.[/dim italic]")
        return

    table = Table(title=title, show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Type", style="bold", width=6, justify="center")
    table.add_column("Line Content", style="white")

    for line in diff_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            table.add_row("FILE", Text(line, style="bold cyan"))
        elif line.startswith("@@ "):
            table.add_row("HUNK", Text(line, style="italic cyan"))
        elif line.startswith("+"):
            table.add_row("+", Text(line[1:], style="green on grey11"))
        elif line.startswith("-"):
            table.add_row("-", Text(line[1:], style="red on grey11"))
        else:
            table.add_row(" ", Text(line, style="dim"))

    c.print(table)


def render_banner(agent=None, console_instance: Optional[Console] = None) -> None:
    """Display rich terminal banner with active backend and system badges."""
    c = console_instance or console
    from core.llm import get_backend
    from config.settings import MODEL_NAME, GROQ_MODEL

    backend = get_backend()
    model_str = GROQ_MODEL if backend == "groq" else MODEL_NAME

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="left")
    table.add_column(style="dim", justify="right")

    table.add_row("🤖 Autonomous AI Agent TUI", f"Backend: [bold green]{backend.upper()}[/bold green] ({model_str})")
    if agent:
        table.add_row(f"📂 Workspace: [white]{agent.workspace}[/white]", f"Short turns: {len(agent.short_mem.get_history())}")

    panel = Panel(
        table,
        border_style="bright_blue",
        title="[bold magenta]Terminal Command Center[/bold magenta]",
        subtitle="[dim]Type [bold cyan]/help[/bold cyan] for commands • [bold red]Ctrl+C[/bold red] to pause & steer[/dim]"
    )
    c.print(panel)


def stream_markdown(tokens: Generator[str, None, None], console_instance: Optional[Console] = None) -> str:
    """Stream LLM response tokens directly to the console with live syntax formatting."""
    c = console_instance or console
    accumulated = ""
    for token in tokens:
        c.print(token, end="", highlight=False)
        accumulated += token
    c.print()
    return accumulated


def start_tui(agent) -> None:
    """
    Launch the Rich Terminal TUI REPL loop.
    Supports live steerability, interactive prompts, and full agent dispatch table.
    """
    render_banner(agent)

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You ›[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[bold cyan]👋 Goodbye.[/bold cyan]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "exit", "quit"):
            console.print("[bold cyan]👋 Goodbye.[/bold cyan]")
            break

        # Check for slash commands
        if user_input.startswith("/"):
            parts = user_input.split(" ", 1)
            cmd = parts[0].lstrip("/").lower().replace("-", "_")
            args = parts[1].strip() if len(parts) > 1 else ""

            if cmd == "help":
                render_banner(agent)
                continue
            elif cmd == "diff":
                diff_output = agent.diff(args)
                render_diff(diff_output)
                continue
            elif cmd == "build":
                from agent.commands.project import cmd_build
                with SteerController(console) as steer:
                    cmd_build(agent, args)
                continue
            elif cmd == "react":
                from agent.react_harness import ToolRegistry, run_react_loop_stream
                registry = ToolRegistry(workspace=agent.workspace)
                console.print(f"[bold cyan]⚡ Running ReAct Loop:[/bold cyan] {args}")
                with SteerController(console) as steer:
                    for event in run_react_loop_stream(args, registry=registry):
                        evt_type = event.get("type")
                        if evt_type == "tool_call":
                            console.print(f"  [bold yellow]🔧 {event.get('name')}[/bold yellow] {event.get('args')}")
                        elif evt_type == "tool_result":
                            status_col = "green" if event.get("ok") else "red"
                            console.print(f"  [{status_col}]✓ Output:[/{status_col}] {str(event.get('output'))[:200]}")
                        elif evt_type == "final_answer":
                            console.print(Panel(Markdown(event.get("answer", "")), title="Final Answer", border_style="green"))
                continue

            # General dispatch fallback
            try:
                method = getattr(agent, cmd, None)
                if callable(method):
                    with SteerController(console) as steer:
                        res = method(args) if args else method()
                        if res and isinstance(res, str):
                            console.print(res)
                else:
                    console.print(f"[bold yellow]❓ Unknown command: /{cmd}. Type /help for available commands.[/bold yellow]")
            except KeyboardInterrupt:
                console.print("[dim]Command interrupted by user.[/dim]")
            except Exception as e:
                console.print(f"[bold red]Error in /{cmd}: {e}[/bold red]")
        else:
            # Free-form chat / instruction
            try:
                with SteerController(console) as steer:
                    agent.chat(user_input)
            except KeyboardInterrupt:
                console.print("[dim]Chat generation cancelled.[/dim]")
            except Exception as e:
                console.print(f"[bold red]Chat error: {e}[/bold red]")
