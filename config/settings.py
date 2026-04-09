"""
config/settings.py — Central configuration for the AI Agent system.
Edit MODEL_NAME and GPU_LAYERS based on your hardware.
"""

from pathlib import Path
import os

# ── Local model (Ollama) ──────────────────────────────────────────────────────
MODEL_NAME      = "phi3:mini"          # Recommended: fits GTX 1650 4GB, fast & capable
OLLAMA_HOST     = "http://localhost:11434"
CONTEXT_WINDOW  = 2048                # phi3:mini handles 128k but we cap for speed
MAX_TOKENS      = 512                 # max tokens per response

# ── Groq API (cloud, free tier — 300+ tok/s) ─────────────────────────────────
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "YOUR_GROQ_API_KEY_HERE")
GROQ_MODEL      = "llama-3.3-70b-versatile"   # best free model on Groq
GROQ_HOST       = "https://api.groq.com/openai/v1"
AUTO_FALLBACK   = True                # auto-switch to Groq if Ollama fails/OOM

# ── Hardware (GTX 1650 + Ryzen 5660H) ────────────────────────────────────────
GPU_LAYERS      = 33                  # phi3:mini (3.8B) fits fully in 4GB VRAM
CPU_THREADS     = 6                   # Ryzen 5660H = 6 cores
NUM_BATCH       = 512                 # large batch = max GPU throughput

# ── Memory ────────────────────────────────────────────────────────────────────
AGENT_HOME       = Path.home() / ".ai_agent"
LONG_MEMORY_FILE = AGENT_HOME / "long_memory.json"
SHORT_MEMORY_MAX = 10                 # max recent turns in session

# ── Tool Safety ───────────────────────────────────────────────────────────────
ALLOW_SHELL     = True                # set False to disable terminal tool
ALLOW_WRITE     = True                # set False to make agent read-only
SHELL_TIMEOUT   = 15                  # seconds before shell command is killed

# ── Planner ───────────────────────────────────────────────────────────────────
MAX_PLAN_STEPS    = 6                 # cap steps to avoid infinite loops
MAX_REFLECT_LOOPS = 2                 # how many times agent can retry after failure

# ── Paths ─────────────────────────────────────────────────────────────────────
AGENT_HOME.mkdir(parents=True, exist_ok=True)

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c",
    ".cs", ".go", ".rs", ".rb", ".php", ".html", ".css", ".md",
    ".json", ".yaml", ".yml", ".sh", ".bat", ".sql", ".txt"
}
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", ".next", ".nuxt", ".mypy_cache", "coverage"
}
