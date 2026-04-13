# 🤖 Dual-LLM AI Agent

[![CI](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-33%20passing-brightgreen.svg)](#-testing)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> An **autonomous coding assistant** that lives entirely on your machine.  
> It reads your project files, plans multi-step tasks, writes code, runs tests, and commits to git — all from a terminal chat interface.

**Dual LLM backends** — runs **Ollama locally** (private, offline) first; transparently falls back to **Groq cloud** (300+ tok/s) when unavailable. No manual switching needed.

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/saranraj1/Dual-LLM-AI-Agent.git
cd Dual-LLM-AI-Agent

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # macOS / Linux

pip install -r requirements.txt

# Or install as a package — enables the `ai` command globally
pip install -e .
```

### 2. Configure Secrets

```bash
cp .env.example .env
# Edit .env and add your free Groq key from https://console.groq.com/keys
```

```env
GROQ_API_KEY=gsk_your_key_here
OLLAMA_HOST=http://localhost:11434
```

### 3. (Optional) Start Local Ollama

```bash
ollama pull phi3:mini     # 3.8B — fits GTX 1650 4GB VRAM
ollama serve
```

If Ollama is offline, the agent automatically switches to Groq. Nothing to configure.

### 4. Launch

```bash
python main.py                         # interactive chat
ai                                     # same, after pip install -e .
python main.py --project /path/to/proj # point at another folder
python main.py --task "add tests"      # one-shot mode, no shell
```

---

## 💬 All Commands

> Type any command below in the chat. Arguments in `<angle brackets>` are required, `[square brackets]` are optional.  
> You can also just chat naturally — no slash needed for questions.

---

### 🤖 Agent Execution

| Command | Description |
|---|---|
| `/run <task>` | The main command. Breaks your task into steps, executes each one, writes files, reflects on results. Example: `/run add input validation to all API routes` |
| `/scan [path]` | Re-scan the workspace to pick up new files. Pass a path to switch projects mid-session. Example: `/scan ../other-project` |
| `/watch` | File watcher — monitors the workspace and auto-reviews any file you save |
| `/help` | Show the full command menu |
| `/quit` / `/exit` | Exit the agent |

---

### 🔍 Code Quality

| Command | Description |
|---|---|
| `/review [file]` | Deep code review with scores 1–10 for readability, performance, security, + specific suggestions. Omit filename to review the whole codebase. |
| `/fix [file]` | Scans for syntax errors, broken imports, and exceptions — then auto-fixes them. Omit filename to check all `.py` files. |
| `/optimize <file>` | Rewrites a file focused on performance — removes bottlenecks, suggests better algorithms, adds profiling hints |
| `/refactor <file>` | Applies SOLID principles: extracts classes, reduces coupling, improves naming, removes duplication |
| `/security [file]` | Security audit with severity levels (CRITICAL / HIGH / MEDIUM / LOW) — checks for injection, hardcoded secrets, insecure deserialization, and more |
| `/test [file]` | Generates pytest unit tests (happy paths, edge cases, error handling), writes them to `test_<name>.py`, and runs them immediately |
| `/lint [file\|fix]` | Runs `flake8` on a file or the whole project. Add `fix` at the end to auto-fix all issues: `/lint fix` |
| `/format [file]` | Auto-formats with `black`. Omit filename to format all Python files |
| `/todo [fix]` | Scans for `TODO`, `FIXME`, `HACK`, `BUG`, `XXX` comments and lists them. Add `fix` to have the agent implement them: `/todo fix` |

---

### 📁 Files & Translation

| Command | Description |
|---|---|
| `/explain <file>` | Deep plain-English explanation — what it does, how it works, key components, gotchas, and what a new developer needs to know |
| `/diff [file]` | Shows git diff for a file. Falls back to comparing the current file against the agent's backup if git is unavailable |
| `/undo <file>` | Instantly restores a file to its state before the agent last edited it. Every agent edit creates a backup automatically |
| `/run-file <file> [args]` | Runs a Python file. If it crashes, the agent reads the error, fixes the code, and runs it again automatically |
| `/translate <file> <language>` | Translates a file to another programming language using idiomatic patterns. Example: `/translate utils.py typescript` |

Supported target languages: Python, JavaScript, TypeScript, Java, C++, C#, Go, Ruby, PHP, Rust

---

### 🗂️ Project Management

| Command | Description |
|---|---|
| `/docs [file]` | With a filename: adds Google-style docstrings to every function and class. Without: generates a full `README.md` for your project |
| `/scaffold <type>` | Creates a complete, runnable project skeleton with real boilerplate. See scaffold types below |
| `/diagram` | Generates an ASCII architecture diagram + a Mermaid diagram saved to `docs/architecture.md` |
| `/stats` | Lines of code, file counts, breakdown by extension, largest files |
| `/deps` | Dependency analysis — which third-party packages are imported, which are installed, which are missing. AI suggests outdated packages |
| `/summarize [file]` | Plain-English project summary covering components, data flow, key dependencies, and how to start contributing |
| `/changelog` | Generates a professional `CHANGELOG.md` from your git history, grouped by Added / Changed / Fixed / Removed |
| `/git [message]` | Smart git commit. Omit message to auto-generate a conventional commit message from the diff. Or pass your own: `/git fix auth bug` |

**Scaffold types:**

```
/scaffold flask-api      Flask REST API with blueprints, SQLAlchemy, JWT auth
/scaffold fastapi        FastAPI with Pydantic, async routes, OpenAPI docs
/scaffold react-app      React app with components, hooks, routing, API layer
/scaffold cli-tool       Python CLI with argparse, config file, logging, tests
/scaffold discord-bot    Discord.py bot with commands, events, cog structure
/scaffold scraper        Web scraper with rate limiting, data export
/scaffold ml-project     ML project with data pipeline, training, evaluation
```

Or describe your own: `/scaffold a REST API that tracks gym workouts`

---

### 🧠 Memory & Session

| Command | Description |
|---|---|
| `/history [n]` | Shows last `n` messages from persistent SQLite memory (default: 10). Example: `/history 20` |
| `/memory` | Shows memory stats — session turns, long-term turn count, LLM call stats, cache hits, backend info |
| `/clear` | Wipes all memory (both session and SQLite long-term store) |
| `/time` | Session duration, total LLM calls, cache hits, Ollama vs Groq call ratio |

---

### ⚙️ Mode & Backend

| Command | Description |
|---|---|
| `/mode <name>` | Changes the agent's thinking style. See modes below |
| `/model [backend]` | Switch LLM backend. No argument = show current. Example: `/model groq` |
| `/config [key value]` | View or change settings live without restarting. Example: `/config gpu 0` |
| `/benchmark` | Runs the same prompt on both backends and compares speed (tokens/sec) |

**Modes:**

| Mode | Focus |
|---|---|
| `normal` | Default — balanced reasoning |
| `debug` | Error-finding, root-cause analysis, tracing |
| `architect` | System design, structure, scalability |
| `tutor` | Step-by-step explanations, beginner-friendly |
| `fast` | Short, direct answers — minimal explanation |
| `review` | Critical code review, finds problems aggressively |

**Live config examples:**

```
/config gpu 0          CPU-only inference (set GPU_LAYERS to 0)
/config ctx 4096       Larger context window
/config tokens 1024    Longer responses
```

**Backend switching:**

```
/model auto            Ollama → Groq fallback (default)
/model local           Force local Ollama only
/model groq            Force Groq cloud only
```

---

### 🌐 Web & Search

| Command | Description |
|---|---|
| `/ask <url> [question]` | Fetches the content of any URL and lets you ask questions about it. Example: `/ask https://docs.python.org/3/library/asyncio.html how do I run a coroutine?` |
| `/search <query>` | DuckDuckGo search → AI synthesised answer with sources. Example: `/search best Python async libraries 2024` |
| `/export [filename]` | Saves the full conversation to a Markdown file. Default: `chat_history.md` |

---

### 📚 Knowledge Base

Index your own documentation, PDFs, code, or notes. The agent uses them as context when answering questions.

| Command | Description |
|---|---|
| `/kb add <file or folder>` | Index a file or entire folder. Example: `/kb add docs/` or `/kb add architecture.pdf` |
| `/kb search <query>` | Semantic search across your indexed documents. Example: `/kb search "how does authentication work"` |
| `/kb list` | Show all indexed documents with entry counts |

**Supported formats:** `.txt` `.md` `.py` `.js` `.ts` `.json` `.yaml` `.csv` `.pdf` `.docx`

**Enable semantic (vector) search:**

```bash
pip install sentence-transformers
# or
pip install -e ".[semantic]"
```

Without `sentence-transformers`, keyword search is used automatically as a fallback.

---

### 🖥️ Local Machine Features

| Command | Description |
|---|---|
| `/clip on` | Enables clipboard monitor — automatically reviews any code you copy from anywhere |
| `/clip off` | Disables clipboard monitoring |
| `/digest` | Shows today's git activity, recently modified files, and a project health summary |

---

## 🏗️ Architecture

```
Dual-LLM-AI-Agent/
│
├── main.py                        Entry point + chat loop + command dispatch
│
├── agent/
│   ├── agent.py                   Agent class: startup scan, method dispatch, run loop
│   ├── planner.py                 LLM → ordered step list for a task
│   ├── executor.py                Executes steps, writes files (path-clamped sandbox)
│   ├── reflection.py              Analyses success/failure after each step
│   ├── cmd_legacy.py              /diff /history /undo /explain /test /fix /todo
│   ├── commands_base.py           Shared backup utility
│   └── commands/
│       ├── __init__.py            Unified export of all 25+ commands
│       ├── code_quality.py        /review /optimize /refactor /security /format /lint
│       ├── project.py             /docs /git /summarize /changelog /stats /deps /diagram /scaffold
│       ├── files.py               /explain /diff /undo /run-file /translate
│       ├── web.py                 /ask /search
│       ├── settings.py            /mode /export /config /benchmark
│       └── local.py               /kb /clip /digest /time
│
├── core/
│   ├── llm.py                     Dual backend: Ollama + Groq, cache, streaming, auto-fallback
│   ├── exceptions.py              Typed exception hierarchy (AgentError → LLMError → ...)
│   ├── prompt_builder.py          System prompt + context injection
│   └── ui.py                      Coloured terminal output, spinner, stream_token
│
├── memory/
│   ├── long_memory.py             SQLite persistent memory (auto-migrates from JSON, WAL mode)
│   └── short_memory.py            In-session conversation turns (last 10)
│
├── tools/
│   ├── knowledge_base.py          Semantic vector search (sentence-transformers + SQLite BLOBs)
│   ├── file_tools.py              read / write / scan / search
│   ├── terminal_tools.py          Cross-platform shell (bash on Linux/Mac, cmd on Windows)
│   ├── notifications.py           Desktop notifications (Windows toast / macOS / Linux notify-send)
│   ├── clipboard_monitor.py       Background thread, detects code in clipboard
│   └── code_tools.py              lint_python(), run_python_file(), syntax check
│
├── config/
│   └── settings.py                Loads .env via python-dotenv, all tunable constants
│
├── tests/                         pytest — 33 tests, all passing
│   ├── test_cache.py
│   ├── test_executor.py
│   ├── test_file_tools.py
│   ├── test_llm_fallback.py
│   └── test_planner.py
│
├── .env.example                   Copy to .env and fill in GROQ_API_KEY
├── .github/workflows/ci.yml       GitHub Actions: test matrix Python 3.11 & 3.12 + flake8
├── pyproject.toml                 Package config, extras, pytest + flake8 config
└── requirements.txt               Pinned dependencies
```

**44 Python files · 7,400+ lines**

---

## ⚙️ Configuration Reference

All settings are in `config/settings.py` and can be overridden via `.env`:

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(from .env)* | Groq cloud API key |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama server |
| `MODEL_NAME` | `phi3:mini` | Ollama model name |
| `GPU_LAYERS` | `33` | GPU layers offloaded (0 = CPU-only) |
| `CPU_THREADS` | `6` | CPU threads for inference |
| `MAX_TOKENS` | `512` | Max tokens per LLM response |
| `CONTEXT_WINDOW` | `2048` | Context window size |
| `AUTO_FALLBACK` | `True` | Auto-switch to Groq if Ollama fails |
| `ALLOW_SHELL` | `True` | `False` = disable all shell commands |
| `ALLOW_WRITE` | `True` | `False` = agent becomes read-only |
| `SHELL_TIMEOUT` | `15` | Seconds before killing a shell command |
| `MAX_PLAN_STEPS` | `6` | Max steps per `/run` task |
| `MAX_REFLECT_LOOPS` | `2` | Max retries after a step fails |
| `SHORT_MEMORY_MAX` | `10` | In-session turns to keep in context |

---

## 🔒 Security

| Mechanism | Protection |
|---|---|
| **`.env` isolation** | API keys never touch git — `.env` is in `.gitignore`, only `.env.example` is committed |
| **Path clamping** | Agent can only write inside your project folder — LLM-hallucinated absolute paths are stripped |
| **Shell blocklist** | `rm -rf /`, `dd if=`, `shutdown`, `curl \| bash` — rejected before execution |
| **Auto-backup** | Every file the agent edits is backed up to `.agent_backups/` first |
| **`/undo <file>`** | Instantly restore any file to its pre-agent state |

---

## 🧪 Testing

```bash
pytest tests/ -v                                          # all 33 tests
pytest tests/ --cov=core --cov=agent --cov=tools --cov=memory --cov-report=term-missing
pytest tests/test_executor.py -v                          # single module
```

CI runs on every push via GitHub Actions (Python 3.11 + 3.12).

---

## 📦 Package Install & CLI Flags

```bash
pip install -e .                    # standard
pip install -e ".[semantic]"        # + sentence-transformers for vector KB
pip install -e ".[dev]"             # + pytest + pytest-cov
pip install -e ".[all]"             # everything
```

```bash
ai                                           # interactive chat in current folder
ai --project ~/my-project                    # point at a specific project
ai --task "write unit tests for utils.py"    # one-shot, no interactive shell
ai --memory                                  # show memory stats and exit
ai --clear                                   # wipe all memory and exit
ai --no-check                                # skip backend check on startup
```

---

## 🗺️ Improvement Roadmap

| Step | Status | Feature |
|---|---|---|
| 1 | ✅ Done | Modularise monolithic 1300-line `commands_extended.py` into 6 focused modules |
| 2 | ✅ Done | pytest suite — 33 tests covering cache, fallback, planner, executor, file tools |
| 3 | ✅ Done | SQLite long-term memory — replaces JSON, auto-migrates, WAL mode, keyword search |
| 4 | ✅ Done | Cross-platform — Windows, macOS, Linux (shell execution + desktop notifications) |
| 5 | ✅ Done | Semantic KB search — `sentence-transformers` + SQLite BLOB embeddings, keyword fallback |
| 6 | ✅ Done | Stream all commands — real-time token output, no blocking waits anywhere |
| 7 | ✅ Done | Typed exception hierarchy — `AgentError → LLMError → BackendUnavailableError` |
| 8 | ✅ Done | `.env` secret management via `python-dotenv` — zero hardcoded keys in source |
| 9 | ✅ Done | GitHub Actions CI — matrix Python 3.11 & 3.12 + flake8 lint job |
| 10 | ✅ Done | `pyproject.toml` packaging — `pip install -e .` + `ai` CLI entrypoint |

---

## 🛠️ Tested Hardware

- GPU: NVIDIA GTX 1650 (4 GB VRAM) — `phi3:mini` runs fully on GPU at ~30 tok/s
- CPU: AMD Ryzen 5 5660H (6 cores)
- RAM: 16 GB DDR4
- OS: Windows 11 + Ubuntu 22.04

For weaker hardware: put `GPU_LAYERS=0` in `.env` or run `/config gpu 0` live. Groq cloud (free tier, 300+ tok/s) is always available as a fallback.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

*Python 3.11 · Ollama · Groq LLaMA 3.3 70B · sentence-transformers · SQLite · pytest · GitHub Actions*
