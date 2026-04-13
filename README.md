# 🤖 Dual-LLM AI Agent

[![CI](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-33%20passing-brightgreen.svg)](#testing)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> An **autonomous coding assistant** that lives entirely on your machine.  
> It reads your project, plans multi-step tasks, writes code, runs tests, commits to git — all from a terminal chat.

**Dual LLM backends** — runs **Ollama locally** (private, offline) first; transparently falls back to **Groq cloud** (300+ tok/s) when Ollama is unavailable. You get the best of both worlds automatically.

---

## ✨ What It Can Do

| Category | Commands | Description |
|---|---|---|
| **Agent** | `/run`, `/scan`, `/watch` | Plan → Execute → Reflect → Write files |
| **Code Quality** | `/review`, `/fix`, `/optimize`, `/refactor`, `/security`, `/test`, `/lint`, `/format`, `/todo` | Full code analysis and automated fixes |
| **Files** | `/explain`, `/diff`, `/undo`, `/run-file`, `/translate` | File inspection and language translation |
| **Project** | `/docs`, `/scaffold`, `/diagram`, `/stats`, `/deps`, `/summarize`, `/changelog`, `/git` | Project-level intelligence |
| **Web** | `/ask <url>`, `/search <query>` | Fetch, read, and reason about any URL |
| **Knowledge Base** | `/kb add`, `/kb search`, `/kb list` | Index your own PDFs, docs, notes — semantic search |
| **Settings** | `/mode`, `/config`, `/benchmark`, `/export`, `/time` | Live config and session management |

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/saranraj1/Dual-LLM-AI-Agent.git
cd Dual-LLM-AI-Agent

# Recommended: create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate      # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Or install as a system package (enables the `ai` command globally)
pip install -e .
```

### 2. Configure Your API Key

```bash
cp .env.example .env
```

Open `.env` and paste your free [Groq API key](https://console.groq.com/keys):

```env
GROQ_API_KEY=gsk_your_key_here
OLLAMA_HOST=http://localhost:11434   # default, no change needed
```

> ⚠️ `.env` is in `.gitignore` — it is **never committed**. Your key stays private.

### 3. (Optional) Start Ollama for Local Mode

```bash
# Install Ollama from https://ollama.com
ollama pull phi3:mini       # 3.8B — fits GTX 1650 4GB VRAM
ollama serve
```

If Ollama is offline, the agent automatically uses Groq cloud. You don't need to configure anything.

### 4. Launch the Agent

```bash
# From the project folder:
python main.py

# After pip install -e ., from ANY folder:
ai

# Point at a specific project:
python main.py --project /path/to/your/project

# One-shot task (no interactive shell):
python main.py --task "add input validation to all API routes"
```

---

## 💬 Example Session

```
You › /run add docstrings to all functions in tools/file_tools.py
You › /review agent/executor.py
You › /refactor agent/planner.py
You › /test tools/knowledge_base.py
You › /git                          ← AI generates a commit message and commits
You › /docs                         ← generates README.md
You › /scaffold fastapi             ← creates a full FastAPI project skeleton
You › /translate main.py typescript ← rewrites Python as TypeScript
You › /kb add docs/                 ← indexes your PDFs and Markdown notes
You › /kb search "how to deploy"
You › /diagram                      ← ASCII + Mermaid architecture diagram
You › what does the executor do?    ← plain chat, context-aware
```

---

## 🏗️ Architecture

```
Dual-LLM-AI-Agent/
│
├── main.py                       ← CLI entry point  (also: 'ai' command)
│
├── agent/
│   ├── agent.py                  ← Agent class: startup, dispatch, chat loop
│   ├── planner.py                ← LLM → ordered step list
│   ├── executor.py               ← step execution + sandboxed file writing
│   ├── reflection.py             ← success/failure analysis per step
│   ├── cmd_legacy.py             ← /diff /history /undo /explain /test /fix /todo
│   ├── commands_base.py          ← shared _backup_file() utility
│   └── commands/                 ← modular slash-command package
│       ├── __init__.py           ← unified re-export of all 25 commands
│       ├── code_quality.py       ← /review /optimize /refactor /security /format /lint
│       ├── project.py            ← /docs /git /summarize /changelog /stats /deps /diagram /scaffold
│       ├── files.py              ← /explain /diff /undo /run-file /translate
│       ├── web.py                ← /ask /search
│       ├── settings.py           ← /mode /export /config /benchmark
│       └── local.py              ← /kb /clip /digest /time
│
├── core/
│   ├── llm.py                    ← dual backend: Ollama + Groq, cache, streaming, fallback
│   ├── exceptions.py             ← typed hierarchy: AgentError → LLMError → ...
│   ├── prompt_builder.py         ← system prompt + context injection
│   └── ui.py                     ← coloured terminal output + spinner
│
├── memory/
│   ├── long_memory.py            ← SQLite persistent memory (auto-migrates from JSON)
│   └── short_memory.py           ← in-session conversation turns
│
├── tools/
│   ├── knowledge_base.py         ← semantic vector search (sentence-transformers + SQLite)
│   ├── file_tools.py             ← read / write / scan / search
│   ├── terminal_tools.py         ← cross-platform shell (bash on Linux/Mac, cmd on Windows)
│   ├── notifications.py          ← desktop notifications (Windows / macOS / Linux)
│   ├── clipboard_monitor.py      ← auto-review code you copy from anywhere
│   └── code_tools.py             ← lint, syntax-check, run Python files
│
├── config/
│   └── settings.py               ← loads .env via python-dotenv, all tunable constants
│
├── tests/                        ← pytest suite — 33 tests, 100% passing
│   ├── test_cache.py             ← LLM response caching
│   ├── test_executor.py          ← file extraction + path-clamping security
│   ├── test_file_tools.py        ← read / write / scan
│   ├── test_llm_fallback.py      ← Ollama → Groq failover
│   └── test_planner.py           ← step planning logic
│
├── .env.example                  ← copy to .env and add your Groq key
├── .github/workflows/ci.yml      ← GitHub Actions: test on Python 3.11 & 3.12
├── pyproject.toml                ← package config, extras, linter config
└── requirements.txt              ← pinned dependencies
```

**44 Python files · 7,400+ lines of code**

---

## ⚙️ Configuration

All settings live in `config/settings.py` and can be overridden in `.env`:

| Setting | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(from .env)* | Groq cloud API key — get free at console.groq.com |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama server URL |
| `MODEL_NAME` | `phi3:mini` | Ollama model — any model you've pulled |
| `GPU_LAYERS` | `33` | GPU layers offloaded (0 = CPU-only) |
| `MAX_TOKENS` | `512` | Max tokens per response |
| `CONTEXT_WINDOW` | `2048` | Context window size |
| `ALLOW_SHELL` | `True` | Set `False` for read-only / sandboxed mode |
| `ALLOW_WRITE` | `True` | Set `False` to prevent any file writes |
| `MAX_PLAN_STEPS` | `6` | Max steps per autonomous task |

**Live changes** — no restart needed:

```
/config gpu 0          ← switch to CPU-only
/config ctx 4096       ← larger context window
/model groq            ← force Groq cloud
/model local           ← force local Ollama
/model auto            ← back to automatic fallback
/mode debug            ← focus on error-finding
/mode architect        ← system-design thinking
/mode tutor            ← step-by-step explanations
```

---

## 🧠 Knowledge Base (Semantic Search)

Index your own documentation, PDFs, Markdown notes, or any codebase:

```bash
# Full semantic search (recommended)
pip install sentence-transformers

# Or with the package extras
pip install -e ".[semantic]"
```

```
/kb add docs/                  ← index a folder of files
/kb add architecture.pdf       ← index a PDF
/kb search "authentication flow"
/kb list                       ← show all indexed documents
```

Supported formats: `.txt` `.md` `.py` `.js` `.pdf` `.docx` `.json` `.csv` `.yaml`

Without `sentence-transformers`, falls back to keyword search automatically.

---

## 🔒 Security

| Mechanism | What it protects |
|---|---|
| `.env` secrets | API keys never touch git — `.env` is in `.gitignore` |
| **Path clamping** | Agent can only write files inside your project — LLM-hallucinated absolute paths like `C:\windows\` are stripped |
| **Shell blocklist** | `rm -rf /`, `dd if=`, `shutdown`, `curl \| bash` — rejected before execution |
| **Backup on edit** | Every file modified by the agent is backed up to `.agent_backups/` first |
| **`/undo <file>`** | Instantly restore any file to its pre-agent state |

---

## 🧪 Testing

```bash
# Run full test suite
pytest tests/ -v

# With coverage report
pytest tests/ --cov=core --cov=agent --cov=tools --cov=memory --cov-report=term-missing

# Single module
pytest tests/test_executor.py -v
```

**33 tests across 5 modules** — all passing on Python 3.11 and 3.12.  
CI runs automatically on every push via GitHub Actions.

---

## 📦 Installing as a Package

```bash
pip install -e .                    # standard install
pip install -e ".[semantic]"        # + sentence-transformers for vector KB search
pip install -e ".[dev]"             # + pytest + pytest-cov
pip install -e ".[all]"             # everything
```

After installation, the `ai` command is available system-wide:

```bash
ai                                  # start agent in current folder
ai --project ~/my-project           # point at another project
ai --task "write unit tests for utils.py"  # one-shot mode
ai --memory                         # show memory stats and exit
ai --clear                          # wipe all memory and exit
```

---

## 🗺️ Improvement Roadmap

| Step | Status | Feature |
|---|---|---|
| 1 | ✅ | Split monolithic `commands_extended.py` (1300 lines) into 6 focused modules |
| 2 | ✅ | Pytest suite — 33 tests covering cache, fallback, planner, executor, file tools |
| 3 | ✅ | SQLite long-term memory — replaces JSON, auto-migrates, WAL mode |
| 4 | ✅ | Cross-platform support — Windows, macOS, Linux (notifications + shell) |
| 5 | ✅ | Semantic KB search — `sentence-transformers` + SQLite BLOB embeddings |
| 6 | ✅ | Streaming all commands — real-time token output, no blocking waits |
| 7 | ✅ | Typed exceptions — `AgentError → LLMError → BackendUnavailableError` |
| 8 | ✅ | `.env` secret management via `python-dotenv` — no hardcoded keys |
| 9 | ✅ | GitHub Actions CI — test matrix Python 3.11 & 3.12 + flake8 lint |
| 10 | ✅ | `pyproject.toml` packaging — `pip install -e .` + `ai` CLI entrypoint |

---

## 🛠️ Hardware Tested On

- **GPU**: NVIDIA GTX 1650 (4GB VRAM) — `phi3:mini` runs fully on GPU
- **CPU**: AMD Ryzen 5 5660H (6 cores)
- **RAM**: 16GB DDR4
- **OS**: Windows 11 (also tested on Ubuntu 22.04)

For weaker hardware: set `GPU_LAYERS=0` in `.env` or use `/config gpu 0` for CPU-only inference. Groq cloud is always available as a free fallback.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

*Built with Python 3.11 · Ollama · Groq · sentence-transformers · SQLite · pytest · GitHub Actions*
