"""
core/llm.py — Dual-backend LLM interface.

Priority:
  1. Try Ollama (local) first.
  2. If Ollama fails (OOM / HTTP 500 / timeout) AND AUTO_FALLBACK=True,
     transparently retry with Groq API (cloud).

Backend can be forced per-call via the `backend` argument:
  ask("...", backend="local")   → Ollama only
  ask("...", backend="groq")    → Groq only
  ask("...", backend="auto")    → Ollama → Groq fallback (default)

Features:
  - Response cache (TTL 120s) — avoids duplicate LLM calls
  - Auto-restart Ollama if it crashes
  - Token stats tracking
  - Streaming for both backends
"""

import json
import hashlib
import subprocess
import time
import urllib.request
import urllib.error
from typing import Generator, Optional
from config.settings import (
    MODEL_NAME, OLLAMA_HOST, CONTEXT_WINDOW, MAX_TOKENS,
    GPU_LAYERS, CPU_THREADS, NUM_BATCH,
    GROQ_API_KEY, GROQ_MODEL, GROQ_HOST, AUTO_FALLBACK,
)

# ── Active backend state ──────────────────────────────────────────────────────
_current_backend = "auto"

# ── Response cache (TTL=120s, max 100 entries) ────────────────────────────────
_cache: dict = {}
_CACHE_TTL   = 120
_cache_hits  = 0

# ── Stats ─────────────────────────────────────────────────────────────────────
_stats = {"ollama_calls": 0, "groq_calls": 0, "cache_hits": 0, "errors": 0}

# ── Ollama options ────────────────────────────────────────────────────────────
OLLAMA_OPTIONS = {
    "num_ctx":        CONTEXT_WINDOW,
    "num_predict":    MAX_TOKENS,
    "temperature":    0.2,
    "top_p":          0.85,
    "repeat_penalty": 1.1,
    "num_gpu":        GPU_LAYERS,
    "num_thread":     CPU_THREADS,
    "num_batch":      NUM_BATCH,
    "stop":           ["<|im_end|>", "</s>", "<|end|>"],
}

# ── Groq headers ──────────────────────────────────────────────────────────────
def _groq_headers() -> dict:
    return {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CACHE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _cache_key(backend: str, system: Optional[str], prompt: str) -> str:
    raw = f"{backend}:{system}:{prompt}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_get(key: str) -> Optional[str]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[1]) < _CACHE_TTL:
        return entry[0]
    return None


def _cache_set(key: str, value: str):
    # Evict oldest if over 100 entries
    if len(_cache) > 100:
        oldest = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest]
    _cache[key] = (value, time.time())


# ══════════════════════════════════════════════════════════════════════════════
#  OLLAMA BACKEND
# ══════════════════════════════════════════════════════════════════════════════

def _ollama_payload(prompt: str, system: Optional[str], stream: bool) -> dict:
    p = {"model": MODEL_NAME, "prompt": prompt, "stream": stream, "options": OLLAMA_OPTIONS}
    if system:
        p["system"] = system
    return p


def _ollama_ask(prompt: str, system: Optional[str] = None) -> str:
    data = json.dumps(_ollama_payload(prompt, system, stream=False)).encode()
    req  = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate", data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        _stats["ollama_calls"] += 1
        return json.loads(resp.read().decode()).get("response", "").strip()


def _ollama_stream(prompt: str, system: Optional[str] = None) -> Generator[str, None, None]:
    data = json.dumps(_ollama_payload(prompt, system, stream=True)).encode()
    req  = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate", data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        _stats["ollama_calls"] += 1
        for line in resp:
            if not line.strip():
                continue
            chunk = json.loads(line.decode())
            token = chunk.get("response", "")
            if token:
                yield token
            if chunk.get("done"):
                break


# ══════════════════════════════════════════════════════════════════════════════
#  GROQ BACKEND  (OpenAI-compatible endpoint)
# ══════════════════════════════════════════════════════════════════════════════

def _groq_payload(prompt: str, system: Optional[str], stream: bool) -> dict:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "stream":      stream,
        "max_tokens":  MAX_TOKENS,
        "temperature": 0.2,
        "top_p":       0.85,
    }


def _groq_ask(prompt: str, system: Optional[str] = None) -> str:
    data = json.dumps(_groq_payload(prompt, system, stream=False)).encode()
    req  = urllib.request.Request(
        f"{GROQ_HOST}/chat/completions", data=data,
        headers=_groq_headers(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        _stats["groq_calls"] += 1
        result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"].strip()


def _groq_stream(prompt: str, system: Optional[str] = None) -> Generator[str, None, None]:
    data = json.dumps(_groq_payload(prompt, system, stream=True)).encode()
    req  = urllib.request.Request(
        f"{GROQ_HOST}/chat/completions", data=data,
        headers=_groq_headers(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        _stats["groq_calls"] += 1
        for line in resp:
            line = line.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            line = line[5:].strip()
            if line == "[DONE]":
                break
            try:
                chunk = json.loads(line)
                delta = chunk["choices"][0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    yield token
            except Exception:
                continue


# ══════════════════════════════════════════════════════════════════════════════
#  AUTO-RESTART OLLAMA
# ══════════════════════════════════════════════════════════════════════════════

def restart_ollama() -> bool:
    """Attempt to restart the Ollama server. Returns True if successful."""
    try:
        print("\n🔄 Attempting to restart Ollama...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
        )
        time.sleep(3)  # Give it time to start
        if is_running():
            print("✅ Ollama restarted successfully.")
            return True
        print("⚠️  Ollama restart attempted but still not responding.")
        return False
    except Exception as e:
        print(f"❌ Could not restart Ollama: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API  — cache + auto-fallback aware
# ══════════════════════════════════════════════════════════════════════════════

def _is_ollama_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(x in msg for x in ["500", "timed out", "connection refused",
                                   "remote end closed", "oom", "memory"])


def ask(prompt: str, system: Optional[str] = None,
        backend: str = "auto", use_cache: bool = True) -> str:
    """
    Send a prompt, return full response string.
    backend: "auto" | "local" | "groq"
    """
    use = backend if backend != "auto" else _current_backend

    # ── Cache check ────────────────────────────────────────────────────────────
    key = _cache_key(use, system, prompt)
    if use_cache:
        cached = _cache_get(key)
        if cached:
            _stats["cache_hits"] += 1
            return cached

    def _do_ollama():
        try:
            result = _ollama_ask(prompt, system)
            if use_cache:
                _cache_set(key, result)
            return result
        except Exception as e:
            _stats["errors"] += 1
            raise e

    def _do_groq():
        try:
            result = _groq_ask(prompt, system)
            if use_cache:
                _cache_set(key, result)
            return result
        except Exception as e:
            _stats["errors"] += 1
            return f"[GROQ ERROR] {e}"

    if use == "groq":
        return _do_groq()

    if use == "local":
        try:
            return _do_ollama()
        except Exception as e:
            # Try auto-restart once
            if _is_ollama_error(e):
                if restart_ollama():
                    try:
                        return _do_ollama()
                    except Exception:
                        pass
            return f"[LLM ERROR] Cannot reach Ollama — is it running? ({e})"

    # Auto: Ollama → Groq fallback
    try:
        return _do_ollama()
    except Exception as e:
        if AUTO_FALLBACK and _is_ollama_error(e):
            print(f"\n⚠️  Ollama unavailable ({e.__class__.__name__}). Switching to Groq ⚡")
            return _do_groq()
        _stats["errors"] += 1
        return f"[LLM ERROR] Cannot reach Ollama — is it running? ({e})"


def ask_stream(prompt: str, system: Optional[str] = None,
               backend: str = "auto") -> Generator[str, None, None]:
    """Stream response tokens. Falls back to Groq stream on Ollama failure."""
    use = backend if backend != "auto" else _current_backend

    if use == "groq":
        try:
            yield from _groq_stream(prompt, system)
        except Exception as e:
            yield f"\n[GROQ ERROR] {e}"
        return

    if use == "local":
        try:
            yield from _ollama_stream(prompt, system)
        except Exception as e:
            yield f"\n[LLM ERROR] {e}"
        return

    # Auto
    try:
        yield from _ollama_stream(prompt, system)
    except Exception as e:
        if AUTO_FALLBACK and _is_ollama_error(e):
            print(f"\n⚠️  Ollama unavailable. Switching to Groq ⚡")
            try:
                yield from _groq_stream(prompt, system)
            except Exception as e2:
                yield f"\n[LLM ERROR] Both backends failed: {e2}"
        else:
            yield f"\n[LLM ERROR] {e}"


# ══════════════════════════════════════════════════════════════════════════════
#  BACKEND MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def set_backend(backend: str):
    global _current_backend
    assert backend in ("auto", "local", "groq"), f"Unknown backend: {backend}"
    _current_backend = backend


def get_backend() -> str:
    return _current_backend


def clear_cache():
    global _cache
    _cache = {}


def get_stats() -> dict:
    return {**_stats, "cache_size": len(_cache), "backend": _current_backend}


def is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def is_groq_available() -> bool:
    return bool(GROQ_API_KEY and GROQ_API_KEY.startswith("gsk_"))


def check_model_exists() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as r:
            tags  = json.loads(r.read())
            names = [m["name"] for m in tags.get("models", [])]
            return any(MODEL_NAME in n for n in names)
    except Exception:
        return False
