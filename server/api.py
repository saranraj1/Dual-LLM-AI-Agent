"""
server/api.py — FastAPI REST + SSE server for the AI Agent.

Endpoints:
  GET  /               → Web Chat UI (HTML)
  GET  /health         → Backend health check
  POST /chat           → Single-turn chat (streaming SSE)
  POST /run            → Execute a task (streaming SSE)
  POST /command        → Run a slash command (blocking)
  GET  /memory         → Session + long-term memory stats
  DELETE /memory       → Clear all memory
  GET  /stats          → LLM stats + cost tracker
  GET  /files          → List workspace files
  GET  /logs           → Last 50 log lines

Start with:
    python main.py --serve
    ai --serve
"""

import os
import sys
import asyncio
import json
import time
import traceback
from pathlib import Path
from typing import Optional, AsyncGenerator

# ── App root on sys.path ──────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.agent import Agent
from core.llm import get_backend, get_stats, is_running, is_groq_available
from core.logger import get_logger, tail_log
from core.prompt_builder import build as _build_prompt, SYSTEM_PROMPT

log = get_logger(__name__)

# ── Command name → agent method mapping ──────────────────────────────────────
# Slash command (without /) → Agent method name
_CMD_MAP = {
    "run":        "run",
    "review":     "review",
    "fix":        "fix",
    "test":       "test",
    "refactor":   "refactor",
    "optimize":   "optimize",
    "security":   "security",
    "lint":       "lint",
    "format":     "format_file",
    "todo":       "todo",
    "explain":    "explain",
    "diff":       "diff",
    "undo":       "undo",
    "run_file":   "run_file",
    "run-file":   "run_file",
    "translate":  "translate",
    "docs":       "docs",
    "git":        "git",
    "scaffold":   "scaffold",
    "diagram":    "diagram",
    "stats":      "stats",
    "deps":       "deps",
    "summarize":  "summarize",
    "changelog":  "changelog",
    "history":    "history",
    "memory":     "memory_stats",
    "clear":      "clear_memory",
    "time":       "session_time",
    "mode":       "mode",
    "model":      "rescan",        # handled separately
    "config":     "config",
    "benchmark":  "benchmark",
    "ask":        "ask_url",
    "search":     "search",
    "export":     "export",
    "kb":         "kb",
    "clip":       "clip",
    "digest":     "digest",
    "watch":      "watch",
    "scan":       "rescan",
}

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Agent API",
    description="Autonomous coding assistant — Dual LLM (Ollama + Groq)",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files (Web UI) ─────────────────────────────────────────────────────
_STATIC = Path(__file__).parent / "static"
_STATIC.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# ── Agent singleton ───────────────────────────────────────────────────────────
_agent: Optional[Agent] = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        workspace = os.environ.get("AGENT_WORKSPACE", os.getcwd())
        _agent = Agent(workspace=workspace)
        log.info("agent initialised — workspace: %s", workspace)
    return _agent


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:   str
    workspace: Optional[str] = None

class RunRequest(BaseModel):
    task:      str
    workspace: Optional[str] = None

class CommandRequest(BaseModel):
    command:   str          # e.g. "/review main.py"
    workspace: Optional[str] = None


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse_event(data: str, event: str = "token") -> str:
    """Format a single SSE data frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_response(gen) -> AsyncGenerator[str, None]:
    """Convert a synchronous str generator into async SSE frames."""
    try:
        for token in gen:
            yield _sse_event(token, "token")
            await asyncio.sleep(0)
    except Exception as e:
        log.error("stream error: %s", e)
        yield _sse_event(str(e), "error")
    finally:
        yield _sse_event("", "done")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    """Serve the Web Chat UI."""
    ui_file = _STATIC / "index.html"
    if ui_file.exists():
        return HTMLResponse(ui_file.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>AI Agent API</h1>"
        "<p>See <a href='/docs'>/docs</a> for API reference.</p>"
        "<p>Web UI not found — check <code>server/static/index.html</code>.</p>"
    )


@app.get("/health")
async def health():
    """Health check — returns Ollama + Groq availability."""
    try:
        ollama_ok = is_running()
    except Exception:
        ollama_ok = False
    try:
        groq_ok = is_groq_available()
    except Exception:
        groq_ok = False
    return {
        "status":    "ok",
        "ollama":    ollama_ok,
        "groq":      groq_ok,
        "backend":   get_backend(),
        "timestamp": time.time(),
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Stream a chat response as Server-Sent Events.

    Events:
      event: token  data: "<token>"
      event: done   data: ""
      event: error  data: "<message>"
    """
    agent = get_agent()
    if req.workspace:
        agent.workspace = os.path.abspath(req.workspace)

    log.info("chat: %s", req.message[:80])

    def _generate():
        try:
            from core.llm import ask_stream
            from tools.knowledge_base import kb_context

            # Build context
            kb   = kb_context(req.message)
            mem  = agent._get_memory_context() if hasattr(agent, "_get_memory_context") else ""
            code = getattr(agent, "code_context", "")

            # Build prompt using the real signature:
            # build(task, memory_context, code_context, tool_results, plan, current_step)
            ctx_parts = []
            if kb:
                ctx_parts.append(f"[Knowledge Base]\n{kb}")
            if code:
                ctx_parts.append(f"[Codebase]\n{code[:1000]}")
            code_ctx = "\n\n".join(ctx_parts)

            prompt = _build_prompt(
                task=req.message,
                memory_context=mem,
                code_context=code_ctx,
            )

            full = ""
            for token in ask_stream(prompt, system=SYSTEM_PROMPT):
                full += token
                yield token

            # Persist to memory
            try:
                agent.short_mem.add("user",      req.message)
                agent.short_mem.add("assistant", full)
                agent.long_mem.add("user",       req.message)
                agent.long_mem.add("assistant",  full[:500])
            except Exception:
                pass

        except Exception as e:
            log.error("chat error: %s\n%s", e, traceback.format_exc())
            yield f"\n\n❌ Error: {e}"

    return StreamingResponse(
        _stream_response(_generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/run")
async def run_task(req: RunRequest):
    """
    Execute an autonomous task and stream step results as SSE.
    The agent plans, executes, writes files, and reflects — all streamed live.
    """
    agent = get_agent()
    if req.workspace:
        agent.workspace = os.path.abspath(req.workspace)

    log.info("run: %s", req.task[:80])

    def _generate():
        try:
            yield f"🚀 Starting task: {req.task}\n\n"
            result = agent.run(req.task)
            yield result or "(completed)"
        except Exception as e:
            log.error("run error: %s", e)
            yield f"\n\n❌ Error: {e}"

    return StreamingResponse(
        _stream_response(_generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/command")
async def run_command_endpoint(req: CommandRequest):
    """
    Execute a slash command (blocking — returns the full result as JSON).

    Example: POST /command {"command": "/review main.py"}
    """
    agent = get_agent()
    if req.workspace:
        agent.workspace = os.path.abspath(req.workspace)

    cmd_str = req.command.strip()
    if not cmd_str.startswith("/"):
        raise HTTPException(400, "Command must start with / (e.g. '/review main.py')")

    # Parse: "/review main.py" → cmd="review", args="main.py"
    parts = cmd_str.lstrip("/").split(" ", 1)
    raw_cmd = parts[0].lower()
    args    = parts[1].strip() if len(parts) > 1 else ""

    # Map to agent method name
    method_name = _CMD_MAP.get(raw_cmd) or raw_cmd.replace("-", "_")
    method      = getattr(agent, method_name, None)

    if method is None:
        raise HTTPException(
            404,
            f"Unknown command: /{raw_cmd}. "
            f"Try: {', '.join('/' + k for k in list(_CMD_MAP.keys())[:10])}…"
        )

    log.info("command /%s %s", raw_cmd, args[:60])

    try:
        import inspect as _inspect
        sig    = _inspect.signature(method)
        params = list(sig.parameters.keys())
        # Call with args only if method accepts a parameter (excluding 'self')
        if params and params[0] not in ("self",):
            result = method(args)
        elif len(params) > 1:
            result = method(args)
        else:
            result = method()
        return {"ok": True, "command": raw_cmd, "result": result or ""}
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        log.error("command error cmd=%s: %s\n%s", raw_cmd, e, tb)
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.get("/memory")
async def memory_stats():
    """Return current memory statistics."""
    agent = get_agent()
    try:
        lm_stats = agent.long_mem.stats()
        # stats() returns: total_turns, oldest, newest, db_path
        fm_count = 0
        try:
            from memory.fix_memory import fix_memory
            fm_count = fix_memory.stats().get("total_patterns", 0)
        except Exception:
            pass
        return {
            "short_turns":   len(agent.short_mem),
            "long_memory":   lm_stats,          # keys: total_turns, oldest, newest, db_path
            "fix_patterns":  fm_count,
            "workspace":     agent.workspace,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/memory")
async def clear_memory():
    """Clear all agent memory (session + SQLite)."""
    agent = get_agent()
    try:
        agent.clear_memory()
        return {"ok": True, "message": "Memory cleared"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/stats")
async def llm_stats():
    """Return LLM call stats and estimated cost."""
    try:
        raw = get_stats()
    except Exception as e:
        raw = {"error": str(e)}

    cost_summary = ""
    try:
        from core.cost_tracker import tracker
        cost_summary = tracker.summary(verbose=True)
    except Exception:
        pass

    return {"llm": raw, "cost_summary": cost_summary}


@app.get("/files")
async def list_files(path: Optional[str] = None):
    """List workspace files (up to 200 entries)."""
    agent = get_agent()
    root  = Path(agent.workspace)
    base  = root / path if path else root
    skip  = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".agent_backups"}
    entries = []
    try:
        for fp in sorted(base.rglob("*"))[:200]:
            if any(s in fp.parts for s in skip):
                continue
            try:
                entries.append({
                    "path": str(fp.relative_to(root)),
                    "type": "dir" if fp.is_dir() else "file",
                    "size": fp.stat().st_size if fp.is_file() else 0,
                })
            except Exception:
                pass
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"root": str(root), "entries": entries}


@app.get("/logs")
async def get_logs(n: int = 50):
    """Return the last n lines of the structured agent log file."""
    try:
        return {"lines": tail_log(n)}
    except Exception as e:
        return {"lines": f"(log unavailable: {e})"}


# ── Runner ────────────────────────────────────────────────────────────────────

def serve(host: str = "0.0.0.0", port: int = 8000, workspace: str = "."):
    """Start the API server. Called from main.py --serve."""
    import uvicorn
    os.environ["AGENT_WORKSPACE"] = os.path.abspath(workspace)
    print(f"\n🌐 AI Agent API server starting...")
    print(f"   URL       : http://localhost:{port}")
    print(f"   Web UI    : http://localhost:{port}/")
    print(f"   API Docs  : http://localhost:{port}/docs")
    print(f"   Workspace : {os.path.abspath(workspace)}\n")
    uvicorn.run(
        "server.api:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    serve()
