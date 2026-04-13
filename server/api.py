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
  POST /ask            → Ask a question about the workspace
  GET  /logs           → Last 50 log lines

Start with:
    python -m server.api
    ai --serve
"""

import os
import sys
import asyncio
import json
import time
from pathlib import Path
from typing import Optional, AsyncGenerator

# ── App root on sys.path ──────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.agent import Agent
from core.llm import get_backend, get_stats, is_running, is_groq_available
from core.logger import get_logger, tail_log

log = get_logger(__name__)

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Agent API",
    description="Autonomous coding assistant — Dual LLM (Ollama + Groq)",
    version="1.0.0",
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
    return _agent


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:   str
    workspace: Optional[str] = None

class RunRequest(BaseModel):
    task:      str
    workspace: Optional[str] = None

class CommandRequest(BaseModel):
    command:   str             # e.g. "/review main.py"
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
            await asyncio.sleep(0)  # give event loop a chance to flush
    except Exception as e:
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
    return HTMLResponse("<h1>AI Agent API</h1><p>See <a href='/docs'>/docs</a></p>")


@app.get("/health")
async def health():
    """Health check — returns backend availability."""
    return {
        "status":        "ok",
        "ollama":        is_running(),
        "groq":          is_groq_available(),
        "backend":       get_backend(),
        "timestamp":     time.time(),
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Stream a chat response as Server-Sent Events.
    Each event is: event: token\\ndata: "<token>"\\n\\n
    Final event is: event: done\\ndata: ""\\n\\n
    """
    agent = get_agent()
    if req.workspace:
        agent.workspace = os.path.abspath(req.workspace)

    log.info("chat request", extra={"message": req.message[:80]})

    def _generate():
        """Run agent.chat() but yield tokens as the LLM streams."""
        from core.llm import ask_stream
        from core.prompt_builder import build, SYSTEM_PROMPT
        from tools.knowledge_base import kb_context

        kb = kb_context(req.message)
        mem = agent._get_memory_context() if hasattr(agent, "_get_memory_context") else ""
        prompt = build(
            user_input=req.message,
            memory_context=mem,
            code_context=agent.code_context,
            kb_context=kb,
            dir_tree=agent.dir_tree,
        )
        full = ""
        for token in ask_stream(prompt, system=SYSTEM_PROMPT):
            full += token
            yield token
        # Save to memory
        agent.short_mem.add("user", req.message)
        agent.short_mem.add("assistant", full)
        agent.long_mem.add("user", req.message)
        agent.long_mem.add("assistant", full[:500])

    return StreamingResponse(
        _stream_response(_generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/run")
async def run_task(req: RunRequest):
    """
    Execute an autonomous task and stream step results as SSE.
    """
    agent = get_agent()
    if req.workspace:
        agent.workspace = os.path.abspath(req.workspace)

    log.info("run task", extra={"task": req.task[:80]})

    def _generate():
        yield f"🚀 Starting task: {req.task}\n"
        result = agent.run(req.task)
        yield result or "(done)"

    return StreamingResponse(
        _stream_response(_generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/command")
async def run_command_endpoint(req: CommandRequest):
    """
    Execute a slash command (blocking — returns the full result).
    Example: POST /command {"command": "/review main.py"}
    """
    agent = get_agent()
    if req.workspace:
        agent.workspace = os.path.abspath(req.workspace)

    cmd_str = req.command.strip()
    if not cmd_str.startswith("/"):
        raise HTTPException(400, "Command must start with /")

    parts   = cmd_str.split(" ", 1)
    cmd     = parts[0].lstrip("/").lower().replace("-", "_")
    args    = parts[1] if len(parts) > 1 else ""

    log.info("command", extra={"cmd": cmd, "args": args[:60]})

    try:
        method = getattr(agent, cmd, None)
        if method is None:
            raise HTTPException(404, f"Unknown command: /{cmd}")
        result = method(args)
        return {"ok": True, "command": cmd, "result": result or ""}
    except HTTPException:
        raise
    except Exception as e:
        log.error("command error", extra={"cmd": cmd, "error": str(e)})
        raise HTTPException(500, str(e))


@app.get("/memory")
async def memory_stats():
    """Return current memory statistics."""
    agent = get_agent()
    try:
        lm_stats  = agent.long_mem.stats()
        fm_stats  = {}
        try:
            from memory.fix_memory import fix_memory
            fm_stats = fix_memory.stats()
        except Exception:
            pass
        return {
            "short_turns":  len(agent.short_mem),
            "long_memory":  lm_stats,
            "fix_patterns": fm_stats.get("total_patterns", 0),
            "workspace":    agent.workspace,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/memory")
async def clear_memory():
    """Clear all agent memory."""
    agent = get_agent()
    agent.clear_memory()
    return {"ok": True, "message": "Memory cleared"}


@app.get("/stats")
async def llm_stats():
    """Return LLM call stats and cost summary."""
    raw = get_stats()
    cost_summary = ""
    try:
        from core.cost_tracker import tracker
        cost_summary = tracker.summary(verbose=True)
    except Exception:
        pass
    return {
        "llm": raw,
        "cost_summary": cost_summary,
    }


@app.get("/files")
async def list_files(path: Optional[str] = None):
    """List workspace files (up to 200 entries)."""
    agent   = get_agent()
    root    = Path(agent.workspace)
    base    = root / path if path else root
    skip    = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".agent_backups"}
    entries = []
    try:
        for fp in sorted(base.rglob("*"))[:200]:
            if any(s in fp.parts for s in skip):
                continue
            entries.append({
                "path":     str(fp.relative_to(root)),
                "type":     "dir" if fp.is_dir() else "file",
                "size":     fp.stat().st_size if fp.is_file() else 0,
            })
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"root": str(root), "entries": entries}


@app.get("/logs")
async def get_logs(n: int = 50):
    """Return the last n lines of the agent log file."""
    return {"lines": tail_log(n)}


# ── Runner ────────────────────────────────────────────────────────────────────

def serve(host: str = "0.0.0.0", port: int = 8000, workspace: str = "."):
    """Start the API server (call from main.py --serve)."""
    import uvicorn
    os.environ["AGENT_WORKSPACE"] = os.path.abspath(workspace)
    print(f"\n🌐 AI Agent API server starting...")
    print(f"   URL       : http://localhost:{port}")
    print(f"   Web UI    : http://localhost:{port}/")
    print(f"   API Docs  : http://localhost:{port}/docs")
    print(f"   Workspace : {os.path.abspath(workspace)}\n")
    uvicorn.run("server.api:app", host=host, port=port, reload=False, log_level="warning")


if __name__ == "__main__":
    serve()
