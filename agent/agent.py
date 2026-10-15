"""
agent/agent.py — Fully autonomous agent loop.
On startup: auto-scans workspace + shows daily digest.
On every task: Plan → Execute → Reflect → Memory → Desktop Notification.

Features:
  - Spinner during LLM calls
  - Coloured output via core/ui
  - Multi-turn conversation context (last 4 turns)
  - Response caching in core/llm
  - Clipboard monitor (auto-review pasted code)
  - Desktop notifications on task completion
  - Knowledge base context injection
  - Daily digest on startup
"""

import os
import time
from agent.planner    import plan, format_plan
from agent.executor   import execute_step
from agent.reflection import reflect, format_reflection, ReflectionResult
from agent.commands import (
    # Legacy core
    cmd_diff, cmd_history, cmd_undo, cmd_checkpoints, cmd_explain,
    cmd_test, cmd_fix, cmd_todo,
    # Code quality
    cmd_review, cmd_optimize, cmd_refactor, cmd_security, cmd_format, cmd_lint,
    cmd_tdd, cmd_blast, cmd_ask_user, cmd_compact, cmd_delegate,
    # Project
    cmd_docs, cmd_git, cmd_summarize, cmd_changelog,
    cmd_stats, cmd_deps, cmd_diagram, cmd_scaffold, cmd_build,
    # Files
    cmd_run_file, cmd_translate,
    # Web
    cmd_ask_url, cmd_search,
    # Settings
    cmd_mode, cmd_export, cmd_config, cmd_benchmark,
    # Local
    cmd_kb, cmd_clip, cmd_digest, cmd_time,
)
from agent.commands_base import _backup_file

from agent.watcher      import cmd_watch
from agent.daily_digest import show_digest
from memory.short_memory import ShortMemory
from memory.long_memory  import LongMemory
from tools.file_tools    import scan_codebase, build_context_string, list_dir, get_repo_map, rank_codebase_files
from tools.clipboard_monitor import ClipboardMonitor
from tools.notifications  import notify_task_done, notify_info
from tools.knowledge_base import kb_context
from core.llm             import ask, ask_stream, get_backend
from core.prompt_builder  import build, SYSTEM_PROMPT
from core.exceptions      import BackendUnavailableError, AgentError
from config.settings      import CONFIRM_EDITS
from core.ui              import (
    C, Spinner, ok, warn, err, info, step, dim, bold,
    agent_label, print_separator, print_task_start, print_step,
    print_reflection, stream_token,
)


def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except (UnicodeEncodeError, OSError):
        try:
            enc = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
            cleaned = [
                a.encode(enc, errors="replace").decode(enc) if isinstance(a, str) else a
                for a in args
            ]
            print(*cleaned, **kwargs)
        except Exception:
            pass


class Agent:
    def __init__(self, workspace: str = ".", confirm_edits: bool = False):
        self.workspace       = os.path.abspath(workspace)
        self.confirm_edits   = confirm_edits or CONFIRM_EDITS
        self.short_mem       = ShortMemory()
        self.long_mem        = LongMemory()
        self.code_context    = ""
        self.repo_map        = ""
        self.dir_tree        = ""
        self._current_mode   = "normal"
        self._print          = _safe_print
        self._session_start  = time.time()
        self._task_count     = 0

        # Clipboard monitor (started on demand via /clip on)
        self._clip_monitor   = ClipboardMonitor(self._on_clipboard_code)
        self._clip_monitor.start()   # starts thread but polling is disabled by default

        self._auto_scan()
        show_digest(self)  # shows once per day

    # ── Startup ───────────────────────────────────────────────────────────────

    def _auto_scan(self):
        self._print(f"\n{C.CYAN}🔍 Auto-scanning workspace:{C.RESET} {self.workspace}")
        tree = list_dir(self.workspace, depth=3)
        if tree["ok"]:
            entries = tree["entries"]
            lines   = [
                f"{'  ' * (len(e['path'].split(os.sep))-1)}{e['path']} {'/' if e['type']=='dir' else ''}"
                for e in entries
            ]
            self.dir_tree = "\n".join(lines[:60])
            self._print(f"   {C.GRAY}📂 Directory: {len(entries)} entries{C.RESET}")

        scan = scan_codebase(self.workspace)
        if scan["ok"]:
            self.code_context = build_context_string(scan, char_limit=800)
            self._print(f"   {C.GRAY}📄 Indexed: {scan['count']} code files{C.RESET}")
        else:
            self._print(warn(f"Scan failed: {scan.get('error')}"))

        self.repo_map = get_repo_map(self.workspace)
        if self.repo_map:
            symbols_count = len(self.repo_map.splitlines())
            self._print(f"   {C.GRAY}🗺️  Symbol map: {symbols_count} lines{C.RESET}")

        self._print(f"   {C.SUCCESS}✅ Workspace loaded — agent is ready.{C.RESET}\n")

    def _refresh_scan(self, query: str = ""):
        if query:
            ranked = rank_codebase_files(self.workspace, query=query, max_files=15)
            if ranked.get("ok") and ranked.get("files"):
                self.code_context = build_context_string(ranked, char_limit=800)
                self.repo_map = get_repo_map(self.workspace)
                return
        scan = scan_codebase(self.workspace)
        if scan.get("ok"):
            self.code_context = build_context_string(scan, char_limit=800)
        self.repo_map = get_repo_map(self.workspace)

    # ── Clipboard callback ─────────────────────────────────────────────────────

    def _on_clipboard_code(self, code: str):
        """Called by ClipboardMonitor when code-like content is detected."""
        print(f"\n{C.YELLOW}📋 Code detected in clipboard — quick review:{C.RESET}")
        print(f"{C.GRAY}{'─'*50}{C.RESET}")
        from core.security import sanitize_untrusted_input
        safe_code = sanitize_untrusted_input(code[:1500], source="clipboard")
        prompt = (
            f"Briefly review this code snippet (2-4 sentences max). "
            f"Note any bugs, style issues, or improvements. Be concise.\n\n{safe_code}"
        )
        print(f"{agent_label()}", end="", flush=True)
        full = ""
        for token in ask_stream(prompt, system=SYSTEM_PROMPT):
            stream_token(token)
            full += token
        print(f"\n{C.GRAY}{'─'*50}{C.RESET}")
        print(f"{C.GRAY}💡 Tip: /clip off to disable auto-review{C.RESET}\n")
        # Re-print input prompt
        print(f"{C.USER}{C.BOLD}You › {C.RESET}", end="", flush=True)

    # ── Command dispatch ──────────────────────────────────────────────────────

    def diff(self, args):         return cmd_diff(self, args)
    def history(self, args):      return cmd_history(self, args)
    def undo(self, args):         return cmd_undo(self, args)
    def checkpoints(self, args):  return cmd_checkpoints(self, args)
    def explain(self, args):      return cmd_explain(self, args)
    def test(self, args):         return cmd_test(self, args)
    def fix(self, args):          return cmd_fix(self, args)
    def todo(self, args):         return cmd_todo(self, args)
    def tdd(self, args):          return cmd_tdd(self, args)
    def blast(self, args):        return cmd_blast(self, args)
    def ask_user(self, args):     return cmd_ask_user(self, args)
    def compact(self, args=""):   return cmd_compact(self, args)
    def delegate(self, args=""):  return cmd_delegate(self, args)

    def review(self, args):       return cmd_review(self, args)
    def optimize(self, args):     return cmd_optimize(self, args)
    def docs(self, args):         return cmd_docs(self, args)
    def git(self, args):          return cmd_git(self, args)
    def refactor(self, args):     return cmd_refactor(self, args)
    def security(self, args):     return cmd_security(self, args)
    def summarize(self, args):    return cmd_summarize(self, args)
    def changelog(self, args):    return cmd_changelog(self, args)
    def stats(self, args):        return cmd_stats(self, args)
    def deps(self, args):         return cmd_deps(self, args)
    def diagram(self, args):      return cmd_diagram(self, args)
    def run_file(self, args):     return cmd_run_file(self, args)
    def scaffold(self, args):     return cmd_scaffold(self, args)
    def build(self, args):        return cmd_build(self, args)
    def ask_url(self, args):      return cmd_ask_url(self, args)
    def mode(self, args):         return cmd_mode(self, args)
    def watch(self, args):        return cmd_watch(self, args)

    def format_file(self, args):  return cmd_format(self, args)
    def lint(self, args):         return cmd_lint(self, args)
    def translate(self, args):    return cmd_translate(self, args)
    def search(self, args):       return cmd_search(self, args)
    def export(self, args):       return cmd_export(self, args)
    def config(self, args):       return cmd_config(self, args)
    def benchmark(self, args):    return cmd_benchmark(self, args)
    def confirm(self, args: str = ""):
        val = args.strip().lower()
        if val in ("on", "true", "1", "yes"):
            self.confirm_edits = True
            return ok("Interactive edit confirmation enabled.")
        elif val in ("off", "false", "0", "no"):
            self.confirm_edits = False
            return ok("Interactive edit confirmation disabled.")
        elif not val:
            state = "ENABLED" if self.confirm_edits else "DISABLED"
            return f"{C.CYAN}Interactive edit confirmation:{C.RESET} {state} (/confirm on | off)"
        else:
            return warn("Usage: /confirm [on|off]")

    # New local-machine features
    def kb(self, args):           return cmd_kb(self, args)
    def clip(self, args):         return cmd_clip(self, args)
    def digest(self, args):       return cmd_digest(self, args)
    def session_time(self, args): return cmd_time(self, args)

    # ── Core agent loop ───────────────────────────────────────────────────────

    def run(self, task: str) -> str:
        self._task_count += 1
        t_start = time.time()

        print_task_start(task, self.workspace)
        self._refresh_scan(query=task)

        print(f"\n{C.CYAN}📋 Planning steps...{C.RESET}")
        with Spinner("Planning"):
            steps = plan(task)
        print(format_plan(steps))

        accumulated  = ""
        code_context = self.code_context

        for i, step_desc in enumerate(steps):
            print_step(i + 1, len(steps), step_desc)

            attempt = 0
            while attempt <= 1:
                with Spinner(f"Executing step {i+1}"):
                    result_obj = execute_step(
                        step            = step_desc,
                        task            = task,
                        memory_context  = self._get_memory_context(query=task),
                        code_context    = code_context,
                        repo_map        = self.repo_map,
                        cwd             = self.workspace,
                        previous_result = accumulated[-600:] if accumulated else "",
                        confirm_edits   = self.confirm_edits,
                    )

                if result_obj.get("code_context"):
                    code_context      = result_obj["code_context"]
                    self.code_context = code_context

                step_result = result_obj["result"] or ""
                error       = result_obj.get("error")

                reflection = reflect(step_desc, step_result, error, attempt=attempt)
                print_reflection(format_reflection(reflection))

                if reflection["status"] == ReflectionResult.SUCCESS:
                    break
                elif reflection["status"] == ReflectionResult.RETRY and attempt == 0:
                    print(f"   {C.YELLOW}🔄 Retrying step...{C.RESET}")
                    attempt += 1
                else:
                    print(f"   {C.GRAY}⏭️  Moving on.{C.RESET}")
                    break

            accumulated += f"\n[Step {i+1}]\n{step_result[:400]}"
            self._refresh_scan()

        print_separator()
        print(f"{C.CYAN}🧠 Synthesizing final answer...{C.RESET}")
        with Spinner("Synthesizing"):
            summary = self._synthesize(task, accumulated)

        elapsed = time.time() - t_start
        print(f"\n{C.SUCCESS}📌 Done.{C.RESET} {C.GRAY}({elapsed:.1f}s){C.RESET}\n")

        self.short_mem.add("user",      task)
        self.short_mem.add("assistant", summary)
        self.long_mem.add("user",       task)
        self.long_mem.add("assistant",  summary[:500])
        self.long_mem.save()

        # Desktop notification for long tasks (>10s)
        if elapsed > 10:
            notify_task_done(f"Task: {task[:80]}", success=True)

        return summary

    def chat(self, message: str) -> str:
        self._refresh_scan(query=message)
        mem           = self._get_memory_context(query=message)
        tree_ctx      = f"## Directory Structure\n{self.dir_tree}" if self.dir_tree else ""
        full_code_ctx = (tree_ctx + "\n\n" + self.code_context).strip()

        # Inject knowledge base context if relevant content found
        kb_ctx = kb_context(message)
        if kb_ctx:
            full_code_ctx = kb_ctx + "\n\n" + full_code_ctx

        raw_message = message

        # Multi-turn: prepend last 4 turns to the prompt for coherence
        convo_history = self._get_conversation_history(max_turns=4)
        prompt_task = f"{convo_history}\n\nUser: {raw_message}" if convo_history else raw_message

        prompt = build(
            task           = prompt_task,
            memory_context = mem,
            code_context   = full_code_ctx,
            repo_map       = self.repo_map,
        )

        print(f"\n{agent_label()}", end="", flush=True)
        full    = ""
        backend = get_backend()

        from agent.executor import AUTONOMOUS_SYSTEM
        from agent.tool_interceptor import resolve_tool_calls_stream
        for token in resolve_tool_calls_stream(prompt, system=AUTONOMOUS_SYSTEM, workspace=self.workspace, backend=backend):
            stream_token(token)
            full += token
        print()

        # Save clean user prompt (without duplicated historical turns) to memory
        self.short_mem.add("user",      raw_message)
        self.short_mem.add("assistant", full)
        self.long_mem.add("user",       raw_message)
        self.long_mem.add("assistant",  full[:400])
        self.long_mem.save()

        try:
            from memory.fact_extractor import auto_record_turn_facts
            auto_record_turn_facts(self.workspace, raw_message)
        except Exception:
            pass

        from agent.executor import (
            _extract_edit_blocks, _auto_edit_files,
            _extract_file_blocks, _auto_write_files,
            _extract_pip_packages, _auto_install
        )
        from agent.interactive_qa import extract_ask_user_blocks, ask_user

        qa_blocks = extract_ask_user_blocks(full)
        if qa_blocks:
            for qb in qa_blocks:
                user_choice = ask_user(qb["question"], options=qb["options"], default=qb.get("default"))
                self.short_mem.add("user", f"[User Decision]: {qb['question']} -> {user_choice}")

        edit_blocks = _extract_edit_blocks(full)
        if edit_blocks:
            print(f"\n{C.CYAN}✏️  Auto-editing files from response...{C.RESET}")
            from core.security import sanitize_path
            for eb in edit_blocks:
                try:
                    abs_path = str(sanitize_path(eb["path"], self.workspace))
                    _backup_file(abs_path, self.workspace)
                except Exception:
                    pass
            _auto_edit_files(edit_blocks, self.workspace, confirm=self.confirm_edits)
            self._refresh_scan(query=raw_message)

        file_blocks = _extract_file_blocks(full)
        if file_blocks:
            print(f"\n{C.CYAN}📝 Auto-writing files from response...{C.RESET}")
            from core.security import sanitize_path
            for fb in file_blocks:
                try:
                    abs_path = str(sanitize_path(fb["path"], self.workspace))
                    _backup_file(abs_path, self.workspace)
                except Exception:
                    pass
            _auto_write_files(file_blocks, self.workspace, confirm=self.confirm_edits)
            self._refresh_scan(query=raw_message)

        pkgs = _extract_pip_packages(full)
        if pkgs:
            print(f"\n{C.CYAN}📦 Auto-installing packages...{C.RESET}")
            _auto_install(pkgs, "pip")

        return full

    def clear_memory(self):
        self.short_mem.clear()
        self.long_mem.clear()
        print(ok("Memory cleared."))

    def memory_stats(self) -> dict:
        stats = {
            "short_turns":   len(self.short_mem),
            "long_memory":   self.long_mem.stats(),
            "workspace":     self.workspace,
            "indexed_chars": len(self.code_context),
            "mode":          self._current_mode,
            "session_secs":  int(time.time() - self._session_start),
            "task_count":    self._task_count,
            "clip_enabled":  self._clip_monitor.is_enabled,
        }
        try:
            from memory.episodic_memory import EpisodicMemory
            episodes = EpisodicMemory().get_episodes(workspace=self.workspace, limit=1)
            stats["episodic_tracked"] = len(episodes) > 0
        except Exception:
            pass
        return stats

    def rescan(self, path: str = None):
        if path:
            self.workspace = os.path.abspath(path)
        self._auto_scan()

    def _get_memory_context(self, query: str = "") -> str:
        short = self.short_mem.get_context(max_chars=400)
        long_ctx = self.long_mem.get_context(query=query, max_chars=400)
        parts = []
        try:
            facts = self.long_mem.get_facts(query=query, limit=5)
            if facts:
                fact_lines = [f"- [{f['category'].upper()}] {f['fact_key']}: {f['fact_value']}" for f in facts]
                parts.append("[Knowledge & Architecture Rules]\n" + "\n".join(fact_lines))
        except Exception:
            pass
        if long_ctx:
            parts.append(f"[Long-term Context]\n{long_ctx}")
        if short:
            parts.append(f"[Session]\n{short}")
        return "\n\n".join(parts)

    def _get_conversation_history(self, max_turns: int = 4) -> str:
        """Return the last N turns as a formatted conversation string."""
        turns = self.short_mem.get_turns(max_turns * 2)
        if not turns:
            return ""
        lines = []
        for t in turns:
            role    = "User" if t["role"] == "user" else "Assistant"
            content = t["content"][:300]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _synthesize(self, task: str, step_outputs: str) -> str:
        prompt = (
            f"Task: {task}\n\n"
            f"What was done:\n{step_outputs[-1200:]}\n\n"
            f"Write a clear summary of what was completed and any files created."
        )
        return ask(prompt, system=SYSTEM_PROMPT)