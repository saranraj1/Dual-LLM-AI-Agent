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
from typing import Optional, AsyncGenerator, List, Dict, Any
from functools import partial

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
    "tdd":        "tdd",
    "blast":      "blast",
    "qa":         "ask_user",
    "ask_user":   "ask_user",
    "refactor":   "refactor",
    "optimize":   "optimize",
    "security":   "security",
    "lint":       "lint",
    "format":     "format_file",
    "todo":       "todo",
    "explain":    "explain",
    "diff":       "diff",
    "undo":        "undo",
    "checkpoints": "checkpoints",
    "run_file":   "run_file",
    "run-file":   "run_file",
    "translate":  "translate",
    "docs":       "docs",
    "git":        "git",
    "scaffold":   "scaffold",
    "build":      "build",
    "diagram":    "diagram",
    "stats":      "stats",
    "deps":       "deps",
    "summarize":  "summarize",
    "changelog":  "changelog",
    "history":    "history",
    "compact":    "compact",
    "delegate":   "delegate",
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
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

from core.security import (
    sanitize_path,
    validate_workspace,
    is_sensitive_path,
    mask_secrets,
    get_allowed_cors_origins,
)

_BASE_WORKSPACE = os.path.abspath(os.environ.get("AGENT_WORKSPACE", os.getcwd()))

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
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
        workspace = os.environ.get("AGENT_WORKSPACE", _BASE_WORKSPACE)
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

class BuildRequest(BaseModel):
    prompt:    str
    workspace: Optional[str] = None


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse_event(data: str, event: str = "token") -> str:
    """Format a single SSE data frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_response(gen) -> AsyncGenerator[str, None]:
    """
    Convert a synchronous blocking generator into async SSE frames.

    Uses a threading.Queue (unbounded, never drops tokens) fed by a daemon
    thread, consumed via run_in_executor so the event loop stays responsive
    for health/stats during long LLM calls.
    """
    import queue as _tq, threading as _th

    q    = _tq.Queue()        # unbounded — never raises QueueFull
    DONE = object()            # sentinel
    ERR  = object()            # error sentinel

    def _feed():
        """Run synchronous generator in a background thread, pushing to queue."""
        try:
            for token in gen:
                q.put(token)
        except Exception as exc:
            q.put((ERR, exc))
        finally:
            q.put(DONE)

    _th.Thread(target=_feed, daemon=True).start()
    loop = asyncio.get_event_loop()

    try:
        while True:
            # Block-wait in executor → event loop stays free for other requests
            item = await loop.run_in_executor(None, q.get)
            if item is DONE:
                break
            if isinstance(item, tuple) and item[0] is ERR:
                log.error("stream error: %s", item[1])
                yield _sse_event(str(item[1]), "error")
                break
            if item:                          # skip empty tokens
                yield _sse_event(item, "token")
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
        try:
            agent.workspace = validate_workspace(req.workspace, _BASE_WORKSPACE)
        except PermissionError as pe:
            raise HTTPException(403, str(pe))

    log.info("chat: %s", req.message[:80])

    def _generate():
        try:
            from core.llm import ask_stream
            from tools.knowledge_base import kb_context

            # Build context
            kb   = kb_context(req.message)
            mem  = agent._get_memory_context() if hasattr(agent, "_get_memory_context") else ""
            code = getattr(agent, "code_context", "")
            convo_history = agent._get_conversation_history(max_turns=4) if hasattr(agent, "_get_conversation_history") else ""
            prompt_task = f"{convo_history}\n\nUser: {req.message}" if convo_history else req.message

            # Build prompt using the real signature:
            # build(task, memory_context, code_context, tool_results, plan, current_step)
            ctx_parts = []
            if kb:
                ctx_parts.append(f"[Knowledge Base]\n{kb}")
            if code:
                ctx_parts.append(f"[Codebase]\n{code[:1000]}")
            code_ctx = "\n\n".join(ctx_parts)

            prompt = _build_prompt(
                task=prompt_task,
                memory_context=mem,
                code_context=code_ctx,
            )

            from agent.tool_interceptor import resolve_tool_calls_stream
            from core.llm import get_backend
            from agent.executor import _extract_file_blocks, _auto_write_files, _extract_edit_blocks, _auto_edit_files

            backend = get_backend()
            full = ""
            for token in resolve_tool_calls_stream(prompt, system=SYSTEM_PROMPT, workspace=agent.workspace, backend=backend):
                full += token
                yield token

            # Auto-write files if generated in response
            try:
                f_blocks = _extract_file_blocks(full)
                if f_blocks:
                    _auto_write_files(f_blocks, agent.workspace, confirm=False)
                e_blocks = _extract_edit_blocks(full)
                if e_blocks:
                    _auto_edit_files(e_blocks, agent.workspace, confirm=False)
            except Exception as we:
                log.warning("auto-write in chat error: %s", we)

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
        try:
            agent.workspace = validate_workspace(req.workspace, _BASE_WORKSPACE)
        except PermissionError as pe:
            raise HTTPException(403, str(pe))

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


# ── Backend selector ──────────────────────────────────────────────────────────

class BackendRequest(BaseModel):
    backend: str   # "auto" | "local" | "groq"

_BACKEND_LABELS = {
    "auto":  "Auto (Ollama → Groq fallback)",
    "local": "Local (Ollama only)",
    "groq":  "Groq Cloud (fast)",
}

@app.get("/backend")
async def get_backend_route():
    """Return the current active LLM backend."""
    from core.llm import get_backend, is_running, is_groq_available
    current = get_backend()
    return {
        "backend":      current,
        "label":        _BACKEND_LABELS.get(current, current),
        "ollama_up":    is_running(),
        "groq_up":      is_groq_available(),
        "available":    list(_BACKEND_LABELS.keys()),
    }

@app.post("/backend")
async def set_backend_route(req: BackendRequest):
    """Switch the active LLM backend (auto / local / groq)."""
    from core.llm import set_backend, is_running, is_groq_available
    choice = req.backend.strip().lower()
    if choice not in _BACKEND_LABELS:
        raise HTTPException(400, f"Invalid backend '{choice}'. Choose: auto, local, groq")

    if choice == "local" and not is_running():
        raise HTTPException(503, "Ollama is offline — cannot switch to local backend")
    if choice == "groq" and not is_groq_available():
        raise HTTPException(503, "Groq is unavailable (check GROQ_API_KEY) — cannot switch to groq")

    set_backend(choice)
    log.info("backend switched to: %s", choice)
    return {
        "ok":      True,
        "backend": choice,
        "label":   _BACKEND_LABELS[choice],
        "message": f"Switched to {_BACKEND_LABELS[choice]}",
    }

@app.post("/command")
async def run_command_endpoint(req: CommandRequest):
    """
    Execute a slash command (blocking — returns the full result as JSON).

    Example: POST /command {"command": "/review main.py"}
    """
    agent = get_agent()
    if req.workspace:
        try:
            agent.workspace = validate_workspace(req.workspace, _BASE_WORKSPACE)
        except PermissionError as pe:
            raise HTTPException(403, str(pe))

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
        loop   = asyncio.get_event_loop()
        sig    = _inspect.signature(method)
        params = list(sig.parameters.keys())

        def _call():
            if params and params[0] not in ("self",):
                return method(args)
            elif len(params) > 1:
                return method(args)
            else:
                return method()

        result = await loop.run_in_executor(None, _call)
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
    """Return LLM call stats, token consumption, and estimated cost."""
    try:
        raw = get_stats()
    except Exception as e:
        raw = {"error": str(e)}

    cost_summary = ""
    session_data = {}
    try:
        from core.cost_tracker import tracker
        cost_summary = tracker.summary(verbose=True)
        s = tracker.session
        session_data = {
            "total_tokens": s.total_tokens,
            "prompt_tokens": s.prompt_tokens,
            "completion_tokens": s.completion_tokens,
            "cost_usd": round(s.cost_usd, 6),
            "ollama_calls": s.ollama_calls,
            "groq_calls": s.groq_calls,
            "elapsed_seconds": round(s.elapsed_seconds, 1),
        }
    except Exception:
        pass

    return {
        "llm": raw,
        "cost_summary": cost_summary,
        "session": session_data,
    }


@app.post("/stats/reset")
async def reset_stats():
    """Reset the current session token telemetry and LLM counters."""
    try:
        from core.cost_tracker import tracker
        tracker.session = tracker.session.__class__()
        import core.llm as _llm
        _llm._stats["ollama_calls"] = 0
        _llm._stats["groq_calls"] = 0
        _llm._stats["cache_hits"] = 0
        _llm._stats["total_calls"] = 0
        return {"ok": True, "message": "Telemetry session successfully reset"}
    except Exception as e:
        raise HTTPException(500, str(e))



@app.get("/files")
async def list_files(path: Optional[str] = None):
    """List workspace files (up to 200 entries), filtering sensitive secrets."""
    agent = get_agent()
    root  = Path(agent.workspace)
    try:
        base = sanitize_path(path, agent.workspace) if path else root
    except PermissionError as pe:
        raise HTTPException(403, str(pe))

    skip  = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".agent_backups"}
    entries = []
    try:
        for fp in sorted(base.rglob("*"))[:200]:
            if any(s in fp.parts for s in skip):
                continue
            if is_sensitive_path(str(fp)):
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
    """Return the last n lines of the structured agent log file with secrets scrubbed."""
    try:
        lines = tail_log(n)
        return {"lines": [mask_secrets(line) for line in lines]}
    except Exception as e:
        return {"lines": [f"(log unavailable: {e})"]}


@app.get("/graph")
async def get_dependency_graph(workspace: Optional[str] = None):
    """
    Export the AST call graph & dependency index for the workspace.
    Returns node-link format suitable for D3 / SVG graph visualizers.
    """
    agent = get_agent()
    try:
        root = validate_workspace(workspace, _BASE_WORKSPACE) if workspace else agent.workspace
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    try:
        from tools.graph_tools import export_graph_json
        data = export_graph_json(root)
        return {"ok": True, "workspace": root, "graph": data}
    except Exception as e:
        log.error("error exporting graph: %s", e)
        raise HTTPException(500, f"Failed to generate dependency graph: {e}")


@app.get("/blast")
async def get_blast_radius(symbol: str, file: Optional[str] = None, workspace: Optional[str] = None):
    """
    Calculate AST blast radius and caller impact for a target symbol.
    """
    agent = get_agent()
    try:
        root = validate_workspace(workspace, _BASE_WORKSPACE) if workspace else agent.workspace
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    try:
        from tools.graph_tools import compute_blast_radius
        blast = compute_blast_radius(symbol=symbol, target_file=file or "", root_dir=root)
        return {"ok": True, "workspace": root, "blast": blast}
    except Exception as e:
        log.error("error computing blast radius: %s", e)
        raise HTTPException(500, f"Failed to compute blast radius: {e}")


# ── Interactive QA Endpoints ──────────────────────────────────────────────────

class QAPromptRequest(BaseModel):
    question: str
    options: Optional[List[str]] = None
    default: Optional[str] = None

class QAAnswerRequest(BaseModel):
    id: str
    answer: str


@app.get("/qa/pending")
async def get_qa_pending():
    """Return all pending questions waiting for user response."""
    from agent.interactive_qa import get_pending_questions
    return {"ok": True, "questions": get_pending_questions()}


@app.post("/qa/answer")
async def submit_qa_answer(req: QAAnswerRequest):
    """Answer a pending interactive question."""
    from agent.interactive_qa import answer_pending_question
    answered = answer_pending_question(req.id, req.answer)
    if not answered:
        raise HTTPException(404, f"Question ID '{req.id}' not found or already answered")
    return {"ok": True, "id": req.id, "answer": req.answer}


@app.post("/qa/ask")
async def trigger_qa_ask(req: QAPromptRequest):
    """Trigger an interactive question."""
    agent = get_agent()
    formatted = req.question
    if req.options:
        formatted += " | " + " | ".join(req.options)
    result = agent.ask_user(formatted)
    return {"ok": True, "question": req.question, "result": result}


# ── Checkpoint & Pre-flight API Endpoints ─────────────────────────────────────

class UndoRequest(BaseModel):
    checkpoint_id: Optional[str] = None
    target_file: Optional[str] = None

class PreflightRequest(BaseModel):
    file_path: Optional[str] = "snippet.py"
    content: Optional[str] = None


@app.get("/checkpoints")
@app.get("/api/checkpoints")
async def get_checkpoints_endpoint(limit: int = 10):
    """List recent shadow git checkpoints available for rollback."""
    from tools.checkpoint_tools import list_checkpoints
    agent = get_agent()
    cps = list_checkpoints(limit=limit, root_dir=agent.workspace)
    return {"ok": True, "count": len(cps), "checkpoints": cps}


@app.post("/checkpoints/undo")
@app.post("/api/checkpoints/undo")
async def undo_checkpoint_endpoint(req: Optional[UndoRequest] = None):
    """Restore files to a previous checkpoint."""
    from tools.checkpoint_tools import restore_checkpoint
    agent = get_agent()
    cid = req.checkpoint_id if req else None
    tf = req.target_file if req else None
    res = restore_checkpoint(checkpoint_id_or_index=cid, target_file=tf, root_dir=agent.workspace)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "Undo failed"))
    return res


@app.post("/preflight")
@app.post("/api/preflight")
async def preflight_endpoint(req: PreflightRequest):
    """Run pre-flight compiler syntax diagnostics on code content or file."""
    from tools.preflight_tools import preflight_check_file
    res = preflight_check_file(req.file_path or "snippet.py", proposed_content=req.content)
    return res


# ── Compactor, Delegate & ReAct API Endpoints ─────────────────────────────────

class CompactRequest(BaseModel):
    force: Optional[bool] = True

class DelegateRequest(BaseModel):
    role: str
    task: str

class ReactRunRequest(BaseModel):
    task: str
    max_turns: Optional[int] = 5


@app.post("/compact")
@app.post("/api/compact")
async def compact_endpoint(req: Optional[CompactRequest] = None):
    """Compact agent working memory to reduce token footprint."""
    agent = get_agent()
    force = req.force if req else True
    res = agent.compact("force" if force else "")
    return {"ok": True, "result": res}


@app.post("/delegate")
@app.post("/api/delegate")
async def delegate_endpoint(req: DelegateRequest):
    """Delegate work to an isolated subagent worker (researcher, test_runner, reviewer)."""
    from agent.subagent_pool import run_subagent
    agent = get_agent()
    res = run_subagent(req.role, req.task, workspace=agent.workspace)
    if not res.get("ok", False) and "error" in res:
        raise HTTPException(400, res["error"])
    return res


@app.post("/react/run")
@app.post("/api/react/run")
async def react_run_endpoint(req: ReactRunRequest):
    """Execute task via the unified ReAct tool-calling harness."""
    from agent.react_harness import ToolRegistry, run_react_loop
    agent = get_agent()
    registry = ToolRegistry(workspace=agent.workspace)
    res = run_react_loop(req.task, registry=registry, max_turns=req.max_turns or 5)
    return res


@app.post("/react/stream")
@app.post("/api/react/stream")
async def react_stream_endpoint(req: ReactRunRequest):
    """Execute task via the unified ReAct tool-calling harness and stream live events as SSE."""
    from agent.react_harness import ToolRegistry, run_react_loop_stream
    agent = get_agent()
    registry = ToolRegistry(workspace=agent.workspace)

    def _event_generator():
        for event in run_react_loop_stream(req.task, registry=registry, max_turns=req.max_turns or 5):
            yield json.dumps(event)

    return StreamingResponse(
        _stream_response(_event_generator()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/build")
@app.post("/api/build")
async def build_endpoint(req: BuildRequest):
    """Execute autonomous prompt-to-project build synchronously."""
    from agent.project_builder import build_project
    agent = get_agent()
    try:
        ws = validate_workspace(req.workspace, _BASE_WORKSPACE) if req.workspace else agent.workspace
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    report = await asyncio.get_event_loop().run_in_executor(
        None, partial(build_project, req.prompt, workspace=ws)
    )
    return report


@app.post("/build/stream")
@app.post("/api/build/stream")
async def build_stream_endpoint(req: BuildRequest):
    """Execute autonomous prompt-to-project build and stream SSE events."""
    from agent.project_builder import build_project_stream
    agent = get_agent()
    try:
        ws = validate_workspace(req.workspace, _BASE_WORKSPACE) if req.workspace else agent.workspace
    except PermissionError as pe:
        raise HTTPException(403, str(pe))

    def _event_generator():
        for line in build_project_stream(req.prompt, workspace=ws):
            yield line

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/benchmark/swe")
@app.post("/api/benchmark/swe")
async def benchmark_swe_endpoint():
    """Execute SWE benchmark evaluation suite."""
    from eval.swe_benchmark import run_swe_benchmark
    res = await asyncio.get_event_loop().run_in_executor(
        None, run_swe_benchmark
    )
    return res




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
