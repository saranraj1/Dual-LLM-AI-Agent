"""
config/settings.py — Central configuration for the AI Agent system.

Secrets (GROQ_API_KEY) are loaded from a .env file via python-dotenv.
Edit MODEL_NAME and GPU_LAYERS based on your hardware.

Setup:
    cp .env.example .env
    # then edit .env with your real Groq API key
"""

from pathlib import Path
import os

# ── Load .env file (Step 8) ───────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    # Walk up from this file's directory to find .env in the project root
    _root = Path(__file__).parent.parent
    load_dotenv(_root / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed — fall back to os.environ or hardcoded values

# ── Local model (Ollama) ──────────────────────────────────────────────────────
MODEL_NAME      = "phi3:mini"          # Recommended: fits GTX 1650 4GB, fast & capable
OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "http://localhost:11434")
CONTEXT_WINDOW  = 2048                # phi3:mini handles 128k but we cap for speed
MAX_TOKENS      = 512                 # max tokens per response

# ── Groq API (cloud, free tier — 300+ tok/s) ─────────────────────────────────
# Key is read from .env file — NEVER hardcode it here
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
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
