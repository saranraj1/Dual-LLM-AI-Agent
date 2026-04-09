"""
main.py — Entry point for the fully autonomous AI Agent.
"""

import sys
import os
import argparse

# Force UTF-8 output so emojis work on Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.agent  import Agent
from core.llm     import is_running, check_model_exists, is_groq_available, set_backend, get_backend
from core.ui      import C, bold, ok, warn, err
from config.settings import MODEL_NAME, GROQ_MODEL


def _banner():
    b = C.BLUE + C.BOLD
    m = C.MAGENTA + C.BOLD
    c = C.CYAN
    g = C.GRAY
    r = C.RESET
    W = 64
    def row(left, right=""):
        content = f" {left:<{W-4}} "
        return f"{b}║{r}{content}{b}║{r}"
    def sep(): return f"{b}╠{'═'*W}╣{r}"
    def top(): return f"{b}╔{'═'*W}╗{r}"
    def bot(): return f"{b}╚{'═'*W}╝{r}"
    def section(title):
        return row(f"{m}{title}{r}")
    def cmd(name, desc):
        return row(f"  {c}{name:<24}{r}{g}{desc}{r}")

    lines = [
        "",
        top(),
        row(f"{m}{bold('🤖  Autonomous AI Agent  •  phi3:mini + Groq'):^{W-4}}"),
        row(f"{g}{'Type anything to chat  (agent reads your files)':^{W-4}}"),
        sep(),
        section("AGENT"),
        cmd("/run <task>",        "plan + execute + auto-write + reflect"),
        cmd("/scan [path]",       "re-scan or switch project folder"),
        cmd("/watch",             "auto-review files as you save them"),
        sep(),
        section("CODE QUALITY"),
        cmd("/review [file]",     "code review with scores 1-10"),
        cmd("/fix [file]",        "scan and auto-fix all errors"),
        cmd("/optimize <file>",   "performance-focused rewrite"),
        cmd("/refactor <file>",   "SOLID principles rewrite"),
        cmd("/security [file]",   "security audit + severity levels"),
        cmd("/test [file]",       "generate + run tests"),
        cmd("/lint [file|fix]",   "run linter, auto-fix issues"),
        cmd("/format [file]",     "auto-format with black"),
        cmd("/todo [fix]",        "list/fix all TODO/FIXME comments"),
        sep(),
        section("FILES & TRANSLATION"),
        cmd("/explain <file>",    "deep explanation of a file"),
        cmd("/diff [file]",       "show changes vs git/backup"),
        cmd("/undo <file>",       "restore file to pre-agent version"),
        cmd("/run-file <file>",   "run file, auto-fix if it crashes"),
        cmd("/translate <f> <l>", "rewrite code in another language"),
        sep(),
        section("PROJECT"),
        cmd("/docs [file]",       "generate docs / README"),
        cmd("/scaffold <type>",   "create full project boilerplate"),
        cmd("/diagram",           "ASCII + Mermaid architecture diagram"),
        cmd("/stats",             "lines of code, file counts"),
        cmd("/deps",              "dependency analysis"),
        cmd("/summarize [file]",  "plain-English project summary"),
        cmd("/changelog",         "generate CHANGELOG from git"),
        cmd("/git [message]",     "smart git commit"),
        sep(),
        section("MEMORY, MODE & SETTINGS"),
        cmd("/history [n]",       "show last n interactions"),
        cmd("/memory",            "show memory + backend stats"),
        cmd("/clear",             "wipe all memory"),
        cmd("/mode <name>",       "debug/architect/tutor/fast/review"),
        cmd("/model [backend]",   "switch backend: auto/local/groq"),
        cmd("/config [key val]",  "view/change settings live"),
        cmd("/benchmark",         "compare local vs Groq speed"),
        sep(),
        section("WEB & EXPORT"),
        cmd("/ask <url> [q]",     "fetch URL and ask questions"),
        cmd("/search <query>",    "DuckDuckGo search + AI answer"),
        cmd("/export [file]",     "save full chat to markdown"),
        sep(),
        section("LOCAL MACHINE FEATURES"),
        cmd("/kb add <file>",      "index your own docs/PDFs/notes"),
        cmd("/kb search <query>",  "search your knowledge base"),
        cmd("/kb list",            "show indexed documents"),
        cmd("/clip on|off",        "auto-review code you copy"),
        cmd("/digest",             "show today's git + file activity"),
        cmd("/time",               "session duration + LLM stats"),
        sep(),
        row(f"  {c}/help{r}{'show this menu':>46}  "),
        row(f"  {c}/quit{r}{'exit':>46}  "),
        bot(),
        "",
    ]
    print("\n".join(lines))


def _parse_cmd(user_input: str):
    parts = user_input.split(" ", 1)
    cmd   = parts[0].lstrip("/").lower().replace("-", "_")
    args  = parts[1].strip() if len(parts) > 1 else ""
    return cmd, args


def chat_loop(agent: Agent):
    _banner()
    while True:
        try:
            prompt = f"\n{C.USER}{C.BOLD}You ›{C.RESET} "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.CYAN}👋 Goodbye.{C.RESET}")
            break

        if not user_input:
            continue

        cmd, args = _parse_cmd(user_input)

        # ── Dispatch table ─────────────────────────────────────────────────────
        dispatch = {
            # Agent
            "run":        lambda a: print(f"\n{C.SUCCESS}📌 Result:{C.RESET}\n{agent.run(a)}\n") if a else print(warn("Usage: /run <task description>")),
            "scan":       lambda a: agent.rescan(a if a else None),
            "watch":      lambda a: agent.watch(a),

            # Code quality
            "review":     lambda a: print(agent.review(a)),
            "fix":        lambda a: print(agent.fix(a)),
            "optimize":   lambda a: agent.optimize(a),
            "refactor":   lambda a: agent.refactor(a),
            "security":   lambda a: agent.security(a),
            "test":       lambda a: print(agent.test(a)),
            "lint":       lambda a: print(agent.lint(a)),
            "format":     lambda a: print(agent.format_file(a)),
            "todo":       lambda a: print(agent.todo(a)),

            # Files & translation
            "explain":    lambda a: agent.explain(a),
            "diff":       lambda a: print(agent.diff(a)),
            "undo":       lambda a: print(agent.undo(a)),
            "run_file":   lambda a: print(agent.run_file(a)),
            "translate":  lambda a: print(agent.translate(a)),

            # Project
            "docs":       lambda a: agent.docs(a),
            "scaffold":   lambda a: print(agent.scaffold(a)),
            "diagram":    lambda a: agent.diagram(a),
            "stats":      lambda a: print(agent.stats(a)),
            "deps":       lambda a: print(agent.deps(a)),
            "summarize":  lambda a: agent.summarize(a),
            "changelog":  lambda a: print(agent.changelog(a)),
            "git":        lambda a: print(agent.git(a)),

            # Memory & mode
            "history":    lambda a: print(agent.history(a)),
            "memory":     lambda a: _show_memory(agent),
            "clear":      lambda a: agent.clear_memory(),
            "mode":       lambda a: print(agent.mode(a)),
            "model":      lambda a: _select_backend(a),
            "config":     lambda a: print(agent.config(a)),
            "benchmark":  lambda a: agent.benchmark(a),

            # Web & export
            "ask":        lambda a: agent.ask_url(a),
            "search":     lambda a: print(agent.search(a)),
            "export":     lambda a: print(agent.export(a)),

            # Local machine features
            "kb":         lambda a: print(agent.kb(a)),
            "clip":       lambda a: print(agent.clip(a)),
            "digest":     lambda a: agent.digest(a),
            "time":       lambda a: print(agent.session_time(a)),

            # Meta
            "help":       lambda a: _banner(),
            "quit":       lambda a: sys.exit(0),
            "exit":       lambda a: sys.exit(0),
        }

        if user_input.startswith("/"):
            if cmd in dispatch:
                try:
                    result = dispatch[cmd](args)
                    if result and isinstance(result, str):
                        print(result)
                except SystemExit:
                    print(f"{C.CYAN}👋 Goodbye.{C.RESET}")
                    break
                except Exception as e:
                    print(err(f"Error in /{cmd}: {e}"))
                    import traceback; traceback.print_exc()
            else:
                print(f"{C.WARN}❓ Unknown command: /{cmd}  — type /help to see all commands.{C.RESET}")
        else:
            agent.chat(user_input)


def _show_memory(agent):
    from core.llm import get_stats
    s    = agent.memory_stats()
    st   = get_stats()
    lines = [
        f"\n{C.CYAN}📊 Memory & Stats:{C.RESET}",
        f"   {C.GRAY}Mode           : {s.get('mode','normal')}{C.RESET}",
        f"   {C.GRAY}Backend        : {C.CYAN}{get_backend()}{C.RESET}",
        f"   {C.GRAY}Session turns  : {s['short_turns']}{C.RESET}",
        f"   {C.GRAY}Long-term turns: {s['long_memory']['turns']}{C.RESET}",
        f"   {C.GRAY}Cache hits     : {st['cache_hits']}{C.RESET}",
        f"   {C.GRAY}Ollama calls   : {st['ollama_calls']}{C.RESET}",
        f"   {C.GRAY}Groq calls     : {st['groq_calls']}{C.RESET}",
        f"   {C.GRAY}Workspace      : {s['workspace']}{C.RESET}",
        f"   {C.GRAY}Indexed chars  : {s['indexed_chars']}{C.RESET}",
        f"   {C.GRAY}Storage file   : {s['long_memory']['file']}{C.RESET}\n",
    ]
    print("\n".join(lines))


def _select_backend(args: str):
    choice = args.strip().lower()
    labels = {
        "auto":  f"auto  (Ollama → Groq fallback)",
        "local": f"local ({MODEL_NAME} via Ollama)",
        "groq":  f"groq  ({GROQ_MODEL} via Groq cloud ⚡)",
    }
    if not choice:
        current = get_backend()
        print(f"\n{C.CYAN}🔀 Current backend:{C.RESET} {labels.get(current, current)}")
        print(f"\n  {C.GRAY}Available:{C.RESET}")
        for k, v in labels.items():
            mark = f"{C.GREEN}→{C.RESET}" if k == current else " "
            print(f"  {mark} /model {v}")
        return
    if choice not in ("auto", "local", "groq"):
        print(warn(f"Unknown backend '{choice}'. Use: /model auto | local | groq"))
        return
    set_backend(choice)
    print(ok(f"Backend switched to: {labels[choice]}"))


def main():
    parser = argparse.ArgumentParser(description="Autonomous Local AI Agent")
    parser.add_argument("--project",  type=str)
    parser.add_argument("--task",     type=str)
    parser.add_argument("--memory",   action="store_true")
    parser.add_argument("--clear",    action="store_true")
    parser.add_argument("--no-check", action="store_true")
    args = parser.parse_args()

    if not args.no_check:
        print(f"\n{C.CYAN}⏳ Checking backends...{C.RESET}")
        ollama_ok = is_running() and check_model_exists()
        groq_ok   = is_groq_available()
        if ollama_ok:
            print(ok(f"Ollama OK  •  Local model : {C.CYAN}{MODEL_NAME}{C.RESET}"))
        else:
            print(warn(f"Ollama not available (model not loaded or not running)"))
        if groq_ok:
            print(ok(f"Groq OK    •  Cloud model : {C.CYAN}{GROQ_MODEL}{C.RESET}"))
        if not ollama_ok and not groq_ok:
            print(err("No LLM backends available. Run: ollama serve"))
            sys.exit(1)
        if not ollama_ok and groq_ok:
            print(warn("Ollama offline — using Groq cloud automatically."))
            set_backend("groq")
        print()

    workspace = os.path.abspath(args.project or os.getcwd())
    agent     = Agent(workspace=workspace)

    if args.memory:
        _show_memory(agent)
        return
    if args.clear:
        agent.clear_memory()
        return
    if args.task:
        result = agent.run(args.task)
        print(f"\n{C.SUCCESS}📌 Result:{C.RESET}\n{result}")
        return

    chat_loop(agent)


if __name__ == "__main__":
    main()