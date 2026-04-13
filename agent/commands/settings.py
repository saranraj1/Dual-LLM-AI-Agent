"""agent/commands/settings.py — /mode /export /config /benchmark"""

import os
import time
from pathlib import Path
from core.llm import ask, ask_stream
from core.prompt_builder import SYSTEM_PROMPT

MODES = {
    "debug": (
        "debug",
        "You are in DEBUG MODE. Focus exclusively on finding and fixing errors. "
        "Always ask: what could go wrong? Check edge cases, null values, type mismatches. "
        "Show exact error locations and fixes."
    ),
    "architect": (
        "architect",
        "You are in ARCHITECT MODE. Think at the system design level. "
        "Consider scalability, maintainability, separation of concerns. "
        "Suggest patterns, structures, and abstractions. Draw ASCII diagrams when helpful."
    ),
    "tutor": (
        "tutor",
        "You are in TUTOR MODE. Explain everything step by step as if teaching a beginner. "
        "Use simple language, analogies, and examples. Check understanding. Never skip steps."
    ),
    "fast": (
        "fast",
        "You are in FAST MODE. Give extremely concise answers. "
        "Code only — no explanations unless asked. One sentence max for non-code answers."
    ),
    "review": (
        "review",
        "You are in REVIEW MODE. For every piece of code you see, automatically "
        "provide a brief quality assessment: correctness, style, potential issues."
    ),
    "normal": (
        "normal",
        SYSTEM_PROMPT
    ),
}


# ── /mode ─────────────────────────────────────────────────────────────────────

def cmd_mode(agent, args: str) -> str:
    mode_name = args.strip().lower()
    if not mode_name or mode_name not in MODES:
        options = "\n".join(f"  /mode {k:<12} — {v[1][:60]}..." for k, v in MODES.items())
        return f"Available modes:\n{options}"

    name, system = MODES[mode_name]
    import core.prompt_builder as pb
    pb.SYSTEM_PROMPT = system
    agent._current_mode = name

    icons = {"debug": "🐛", "architect": "🏗️", "tutor": "📚",
             "fast": "⚡", "review": "🔍", "normal": "🤖"}
    return f"{icons.get(name, '🤖')} Switched to {name.upper()} mode."


# ── /export ───────────────────────────────────────────────────────────────────

def cmd_export(agent, args: str) -> str:
    filename = args.strip() or "chat_history.md"
    path = os.path.join(agent.workspace, filename)

    turns = agent.short_mem.get_turns(n=100)
    ltmem = agent.long_mem.get_context(max_chars=5000)

    lines = [
        f"# AI Agent Chat History",
        f"Exported: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Workspace: {agent.workspace}",
        f"",
        f"---",
        f"",
    ]
    if ltmem:
        lines += ["## Long-term Memory", ltmem, "", "---", ""]
    lines.append("## Session Transcript")
    for turn in turns:
        role = "🧑 **You**" if turn["role"] == "user" else "🤖 **Agent**"
        lines.append(f"\n### {role}\n{turn['content']}\n")

    content = "\n".join(lines)
    try:
        Path(path).write_text(content, encoding="utf-8")
        return f"✅ Exported {len(turns)} turns to: {filename}"
    except Exception as e:
        return f"❌ Export failed: {e}"


# ── /config ───────────────────────────────────────────────────────────────────

def cmd_config(agent, args: str) -> str:
    import config.settings as S
    from core.llm import set_backend, get_backend

    parts = args.strip().split(maxsplit=1)
    if not parts:
        lines = [
            f"\n⚙️  Current Configuration",
            f"{'─'*40}",
            f"  Model (local) : {S.MODEL_NAME}",
            f"  Model (Groq)  : {S.GROQ_MODEL}",
            f"  Backend       : {get_backend()}",
            f"  Context window: {S.CONTEXT_WINDOW} tokens",
            f"  Max tokens    : {S.MAX_TOKENS}",
            f"  GPU layers    : {S.GPU_LAYERS}",
            f"  CPU threads   : {S.CPU_THREADS}",
            f"  Auto fallback : {S.AUTO_FALLBACK}",
            f"  Workspace     : {agent.workspace}",
        ]
        return "\n".join(lines)

    key = parts[0].lower()
    val = parts[1] if len(parts) > 1 else ""
    if not val:
        return f"Usage: /config {key} <value>"

    try:
        if key in ("gpu", "gpu_layers"):
            S.GPU_LAYERS = int(val)
            from core.llm import OLLAMA_OPTIONS
            OLLAMA_OPTIONS["num_gpu"] = int(val)
            return f"✅ GPU layers set to {val}"
        elif key in ("ctx", "context", "context_window"):
            S.CONTEXT_WINDOW = int(val)
            from core.llm import OLLAMA_OPTIONS
            OLLAMA_OPTIONS["num_ctx"] = int(val)
            return f"✅ Context window set to {val}"
        elif key in ("tokens", "max_tokens"):
            S.MAX_TOKENS = int(val)
            from core.llm import OLLAMA_OPTIONS
            OLLAMA_OPTIONS["num_predict"] = int(val)
            return f"✅ Max tokens set to {val}"
        elif key == "model":
            S.MODEL_NAME = val
            return f"✅ Local model set to {val}\n   Note: restart agent to apply model change"
        elif key == "backend":
            if val not in ("auto", "local", "groq"):
                return "❌ Backend must be: auto | local | groq"
            set_backend(val)
            return f"✅ Backend switched to {val}"
        else:
            return f"❌ Unknown setting: {key}\nTry: gpu, ctx, tokens, model, backend"
    except ValueError:
        return f"❌ Invalid value: {val}"


# ── /benchmark ────────────────────────────────────────────────────────────────

def cmd_benchmark(agent, args: str) -> str:
    from core.llm import _ollama_ask, _groq_ask, is_running, is_groq_available

    prompt = "Write a Python function that checks if a number is prime. Include a docstring."
    results = []
    print("\n⏱️  Benchmarking LLM backends (this may take a minute)...\n")

    if is_running():
        print("  Testing local Ollama...", end="", flush=True)
        try:
            t0 = time.time()
            resp = _ollama_ask(prompt)
            elapsed = time.time() - t0
            words = len(resp.split())
            results.append(("Local (Ollama)", elapsed, words, "✅", resp[:100]))
            print(f" {elapsed:.1f}s")
        except Exception as e:
            results.append(("Local (Ollama)", 0, 0, "❌", str(e)))
            print(" FAILED")
    else:
        results.append(("Local (Ollama)", 0, 0, "⚠️", "Not running"))

    if is_groq_available():
        print("  Testing Groq cloud...", end="", flush=True)
        try:
            t0 = time.time()
            resp = _groq_ask(prompt)
            elapsed = time.time() - t0
            words = len(resp.split())
            results.append(("Groq (cloud)", elapsed, words, "✅", resp[:100]))
            print(f" {elapsed:.1f}s")
        except Exception as e:
            results.append(("Groq (cloud)", 0, 0, "❌", str(e)))
            print(" FAILED")
    else:
        results.append(("Groq (cloud)", 0, 0, "⚠️", "No API key"))

    lines = [
        "",
        "📊 Benchmark Results",
        "─" * 50,
        f"  {'Backend':<20} {'Time':>8}  {'Words':>6}  Status",
        "─" * 50,
    ]
    for name, t, w, status, _ in results:
        t_str = f"{t:.1f}s" if t else "—"
        w_str = str(w) if w else "—"
        lines.append(f"  {name:<20} {t_str:>8}  {w_str:>6}  {status}")

    if len(results) == 2 and results[0][1] and results[1][1]:
        factor = results[0][1] / results[1][1]
        lines.append(f"\n  🏆 Groq is {factor:.1f}x faster than local")

    lines.append("\n  Tip: Use /model groq for speed, /model local for privacy")
    result = "\n".join(lines)
    print(result)
    return result
