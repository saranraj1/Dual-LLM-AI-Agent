# 🤖 Dual-LLM AI Agent

[![CI](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-33%20passing-brightgreen.svg)](#-testing)
[![Version](https://img.shields.io/badge/version-1.1.0-blueviolet.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> An **autonomous coding assistant** that lives entirely on your machine.  
> It reads your project files, plans multi-step tasks, writes code, runs tests, and commits to git — all from a terminal chat interface **or a browser UI**.

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

# With Web UI + API server support
pip install -e ".[server]"
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
# Terminal chat
python main.py
ai                                       # after pip install -e .

# Web Chat UI + REST API
python main.py --serve                   # opens http://localhost:8000
ai --serve --port 8080                   # custom port

# One-shot task
python main.py --task "add unit tests"

# Point at a specific project
ai --project /path/to/my-project

# Git hook setup
ai --install-hook                        # install pre-commit hook
ai --strict-hook                         # strict mode (blocks commits on issues)
```

---

## 🌐 Web Chat UI

Start the agent server and open your browser:

```bash
python main.py --serve
# → http://localhost:8000
```

**Features:**
- Real-time streaming token output (SSE)
- Markdown rendering with syntax-highlighted code blocks
- Sidebar with one-click command buttons
- Live stats panel: backend status, tokens used, estimated cost, memory turns
- `⚡ Run` button for autonomous multi-step task mode
- `Ctrl+K` focus input · `Enter` to send · `Shift+Enter` for new lines

**REST API** (OpenAPI docs at `/docs`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web Chat UI |
| `GET` | `/health` | Backend health (Ollama + Groq status) |
| `POST` | `/chat` | Streaming SSE chat |
| `POST` | `/run` | Autonomous task execution (SSE) |
| `POST` | `/command` | Any `/slash command` via HTTP |
| `GET` | `/memory` | Session + long-term memory stats |
| `DELETE` | `/memory` | Clear all memory |
| `GET` | `/stats` | LLM call stats + cost summary |
| `GET` | `/files` | List workspace files |
| `GET` | `/logs` | Last 50 structured log lines |

---

## 🧩 VS Code Extension

The `vscode-extension/` folder contains a ready-to-install VS Code extension that calls all agent commands from inside the editor.

### Install

```bash
cd vscode-extension
npm install
npm run package                              # builds ai-agent-vscode-1.1.0.vsix
code --install-extension ai-agent-vscode-1.1.0.vsix
```

**Start the agent server first:**
```bash
ai --serve   # must be running at http://localhost:8000
```

### Commands Available Inside VS Code

| Command | Shortcut | Description |
|---------|----------|-------------|
| Review This File | `Ctrl+Shift+R` | Code review with scores |
| Fix Errors | — | Auto-detect and fix errors |
| Explain This File | — | Plain-English explanation |
| Refactor | — | Apply SOLID principles |
| Security Scan | — | CRITICAL/HIGH/MEDIUM/LOW findings |
| Generate Tests | — | Write + run pytest tests |
| Explain Selection | `Ctrl+Shift+E` | Explain highlighted code |
| Fix Selection | — | Fix code **inline** in the editor |
| Open Chat UI | `Ctrl+Shift+A` | Open browser chat |
| Run Task… | `Ctrl+Shift+T` | Type any autonomous task |
| Generate API Docs | — | Scan routes → `docs/api.md` + OpenAPI |
| Smart Git Commit | — | AI-generated commit message |

Right-click any Python/JS file for the **🤖 AI Agent** context menu.

**Status Bar:** Shows live Ollama + Groq health. Click to open chat.

**Settings (`settings.json`):**
```json
{
  "aiAgent.serverUrl": "http://localhost:8000",
  "aiAgent.autoConnect": true,
  "aiAgent.showStatusBar": true
}
```

---

## 💬 All Commands (Terminal)

> Type any command below in the chat. `<angle brackets>` = required, `[square brackets]` = optional.  
> You can also chat naturally — no slash needed for questions.

---

### 🤖 Agent Execution

| Command | Description |
|---|---|
| `/run <task>` | Main command — plan, execute, auto-write, reflect. Example: `/run add input validation to all API routes` |
| `/scan [path]` | Re-scan workspace or switch project. Example: `/scan ../other-project` |
| `/watch` | File watcher — auto-reviews any file you save |
| `/help` | Show full command menu |
| `/quit` / `/exit` | Exit |

---

### 🔍 Code Quality

| Command | Description |
|---|---|
| `/review [file]` | Deep review — scores 1–10 for readability, performance, security + suggestions. Omit filename for whole codebase |
| `/fix [file]` | Scan for errors, broken imports, exceptions — auto-fix. Learns from past successful fixes |
| `/optimize <file>` | Rewrite focused on performance — bottlenecks, algorithms, profiling hints |
| `/refactor <file>` | Apply SOLID: extract classes, reduce coupling, improve naming |
| `/security [file]` | Security audit — CRITICAL / HIGH / MEDIUM / LOW. Checks injection, secrets, deserialization |
| `/test [file]` | Generate pytest tests (happy paths + edge cases), writes `test_<name>.py`, runs immediately |
| `/lint [file\|fix]` | `flake8` on file or project. `/lint fix` auto-fixes issues |
| `/format [file]` | `black` formatting. Omit filename to format all Python files |
| `/todo [fix]` | Scan `TODO`, `FIXME`, `HACK`, `BUG`, `XXX` comments. `/todo fix` implements them |

---

### 📁 Files & Translation

| Command | Description |
|---|---|
| `/explain <file>` | Plain-English walkthrough — purpose, components, gotchas, onboarding guide |
| `/diff [file]` | Git diff, or compare against agent backup if git unavailable |
| `/undo <file>` | Restore file to pre-agent state (every edit is backed up first) |
| `/run-file <file> [args]` | Run Python file; if it crashes, agent reads error, fixes code, and reruns |
| `/translate <file> <lang>` | Translate to another language. Example: `/translate utils.py typescript` |

Supported target languages: Python, JavaScript, TypeScript, Java, C++, C#, Go, Ruby, PHP, Rust

---

### 🗂️ Project Management

| Command | Description |
|---|---|
| `/docs [file]` | File → add Google-style docstrings. No arg → generate `README.md` |
| `/docs api` | **Scan all routes (Flask/FastAPI) → `docs/api.md` + `docs/openapi.yaml` (OpenAPI 3.0)** |
| `/scaffold <type>` | Generate a complete project skeleton with real boilerplate |
| `/diagram` | ASCII + Mermaid architecture diagram → `docs/architecture.md` |
| `/stats` | Lines of code, file counts, extension breakdown, largest files |
| `/deps` | Import analysis — which packages are imported, installed, missing |
| `/summarize [file]` | Project summary: components, data flow, key deps, how to contribute |
| `/changelog` | Generate `CHANGELOG.md` from git history (Added / Changed / Fixed / Removed) |
| `/git [message]` | Smart commit. No message → AI-generates a conventional commit from diff |

**`/docs api` output:**
```
docs/
├── api.md          ← Markdown reference table with method badges
└── openapi.yaml    ← OpenAPI 3.0 spec (import into Swagger UI, Postman, Insomnia)
```

Quick preview:
```bash
npx swagger-ui-cli serve docs/openapi.yaml
```

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
| `/history [n]` | Last `n` messages from SQLite long-term memory (default: 10) |
| `/memory` | Session stats — turns, LLM calls, cache hits, backend, fix patterns learned |
| `/clear` | Wipe all memory (session + SQLite) |
| `/time` | Session duration, LLM calls, **cost tracker** ($0.0023 used · 4,200 tokens), log file path |

---

### ⚙️ Mode & Backend

| Command | Description |
|---|---|
| `/mode <name>` | Change thinking style. Modes: `normal` `debug` `architect` `tutor` `fast` `review` |
| `/model [backend]` | Switch backend. No arg = show current. Example: `/model groq` |
| `/config [key value]` | Change settings live. Example: `/config gpu 0` |
| `/benchmark` | Compare Ollama vs Groq speed (tokens/sec) |

**Backend options:**
```
/model auto    Ollama → Groq fallback (default)
/model local   Force Ollama only
/model groq    Force Groq cloud only
```

**Live config:**
```
/config gpu 0          CPU-only inference
/config ctx 4096       Larger context window
/config tokens 1024    Longer responses
```

---

### 🌐 Web & Search

| Command | Description |
|---|---|
| `/ask <url> [question]` | Fetch URL content, ask about it. Example: `/ask https://docs.python.org/3/library/asyncio.html how do I run a coroutine?` |
| `/search <query>` | DuckDuckGo search → AI synthesis with sources |
| `/export [filename]` | Save full conversation to Markdown. Default: `chat_history.md` |

---

### 📚 Knowledge Base

Index your own docs, PDFs, code, or notes. The agent uses them as context for every answer.

| Command | Description |
|---|---|
| `/kb add <file or folder>` | Index files. Examples: `/kb add docs/` · `/kb add architecture.pdf` |
| `/kb search <query>` | Semantic search. Example: `/kb search "how does auth work"` |
| `/kb list` | All indexed documents with chunk counts |

**Supported formats:** `.txt` `.md` `.py` `.js` `.ts` `.json` `.yaml` `.csv` `.pdf` `.docx`

**Enable semantic (vector) search:**
```bash
pip install -e ".[semantic]"     # installs sentence-transformers
```
Without it, fast keyword search is used as a fallback.

---

### 🖥️ Local Machine

| Command | Description |
|---|---|
| `/clip on` | Clipboard monitor — auto-review code you copy from anywhere |
| `/clip off` | Disable clipboard monitoring |
| `/digest` | Today's git activity, recently changed files, project health summary |

---

## 🏗️ Architecture

```
Dual-LLM-AI-Agent/                         v1.1.0
│
├── main.py                   Entry point + chat loop + dispatch
│                             Flags: --serve --project --task --install-hook
│
├── server/                   NEW — REST API + Web UI
│   ├── api.py                FastAPI: /chat /run /command /health /stats /logs
│   └── static/index.html     Web Chat UI (streaming, markdown, stats panel)
│
├── vscode-extension/         NEW — VS Code Extension
│   ├── package.json          12 commands, context menus, keybindings
│   └── src/extension.js      Calls agent REST API; status bar; inline fix
│
├── agent/
│   ├── agent.py              Agent class: scan, dispatch, run loop
│   ├── planner.py            LLM → ordered step list
│   ├── executor.py           Execute steps, write files (path-clamped)
│   ├── reflection.py         Analyse success/failure, retry
│   ├── dependency_graph.py   NEW — AST import graph, topo sort, cycle detect
│   ├── cmd_legacy.py         /diff /history /undo /fix (+ fix memory hints)
│   ├── commands_base.py      Backup utility
│   └── commands/
│       ├── code_quality.py   /review /optimize /refactor /security /lint /format
│       ├── project.py        /docs /docs api /git /scaffold /stats /diagram /deps
│       ├── files.py          /explain /diff /undo /run-file /translate
│       ├── web.py            /ask /search
│       ├── settings.py       /mode /export /config /benchmark
│       └── local.py          /kb /clip /digest /time (with cost tracker)
│
├── core/
│   ├── llm.py                Dual backend + cache + streaming + auto-fallback
│   ├── retry.py              NEW — Exponential backoff + jitter + Retry-After
│   ├── cost_tracker.py       NEW — Token counting, Groq pricing, daily history
│   ├── logger.py             NEW — JSON rotating log + coloured console
│   ├── exceptions.py         AgentError → LLMError → BackendUnavailableError
│   ├── prompt_builder.py     System prompt + context injection
│   └── ui.py                 Coloured terminal, spinner, stream_token
│
├── memory/
│   ├── long_memory.py        SQLite persistent memory (WAL, keyword search)
│   ├── short_memory.py       In-session turns (last 10)
│   └── fix_memory.py         NEW — SQLite fix pattern store; hint injection
│
├── tools/
│   ├── api_doc_scanner.py    NEW — AST route scanner, Markdown + OpenAPI gen
│   ├── knowledge_base.py     Semantic vector search + SQLite BLOBs
│   ├── file_tools.py         read / write / scan / search
│   ├── terminal_tools.py     Cross-platform shell (bash/cmd/pwsh)
│   ├── notifications.py      OS notifications (Win toast / macOS / Linux)
│   ├── clipboard_monitor.py  Background clipboard watcher
│   └── code_tools.py         lint_python(), run_python_file()
│
├── config/
│   └── settings.py           python-dotenv → typed constants
│
├── scripts/
│   ├── install_git_hook.py   Pre-commit hook installer
│   └── validate_features.py  Feature smoke-test script
│
├── tests/                    33 passing (pytest · GitHub Actions CI)
├── .env.example              Template — copy to .env
├── .github/workflows/ci.yml  Matrix: Python 3.11 & 3.12 + flake8
└── pyproject.toml            v1.1.0 — extras: server, semantic, dev, all
```

**56 Python files · 9,000+ lines**

---

## ⚙️ Configuration Reference

All settings live in `config/settings.py` and can be overridden via `.env`:

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(from .env)* | Groq cloud API key |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama server |
| `MODEL_NAME` | `phi3:mini` | Ollama model |
| `GPU_LAYERS` | `33` | GPU layers (0 = CPU-only) |
| `CPU_THREADS` | `6` | Inference CPU threads |
| `MAX_TOKENS` | `512` | Max tokens per response |
| `CONTEXT_WINDOW` | `2048` | Context window size |
| `AUTO_FALLBACK` | `True` | Auto-switch to Groq if Ollama fails |
| `ALLOW_SHELL` | `True` | `False` = disable shell commands |
| `ALLOW_WRITE` | `True` | `False` = read-only mode |
| `SHELL_TIMEOUT` | `15` | Kill shell after N seconds |
| `MAX_PLAN_STEPS` | `6` | Max steps per `/run` task |
| `MAX_REFLECT_LOOPS` | `2` | Retries after step failure |
| `SHORT_MEMORY_MAX` | `10` | In-session turns in context |

---

## 🔒 Security

| Mechanism | Protection |
|---|---|
| **`.env` isolation** | API keys never touch git — `.gitignore` enforced, `*.docx/*.pdf` also excluded |
| **Path clamping** | Agent can only write inside the project folder |
| **Shell blocklist** | `rm -rf /`, `dd if=`, `shutdown`, `curl \| bash` — rejected before execution |
| **Auto-backup** | Every agent edit backed up to `.agent_backups/` first |
| **`/undo <file>`** | Instantly restore any file to its pre-agent state |
| **Pre-commit hook** | `ai --install-hook` — blocks hardcoded secrets + linting errors before commit |
| **Structured logging** | All agent actions logged to `~/.ai_agent/logs/agent.log` (JSON rotating, 5 MB × 5) |

---

## 🧪 Testing

```bash
pytest tests/ -v                                          # all 33 tests
pytest tests/ --cov=core --cov=agent --cov=tools --cov=memory --cov-report=term-missing
pytest tests/test_executor.py -v                          # single module
```

CI runs on every push via GitHub Actions (Python 3.11 + 3.12 matrix).

---

## 📦 Package Install & CLI Flags

```bash
pip install -e .                     # standard install
pip install -e ".[server]"           # + FastAPI Web UI
pip install -e ".[semantic]"         # + sentence-transformers (vector KB)
pip install -e ".[dev]"              # + pytest + pytest-cov
pip install -e ".[all]"              # everything
```

```bash
ai                                           # interactive chat
ai --project ~/my-project                    # target a specific project
ai --task "write unit tests for utils.py"    # one-shot, no shell
ai --serve                                   # start Web UI + REST API
ai --serve --port 8080                       # custom port
ai --memory                                  # show stats and exit
ai --clear                                   # wipe memory and exit
ai --no-check                                # skip backend startup check
ai --install-hook                            # install git pre-commit hook
ai --strict-hook                             # hook in strict mode
ai --remove-hook                             # uninstall hook
```

---

## 🗺️ Full Feature History

### Original Roadmap (Steps 1–10)

| Step | Feature |
|---|---|
| 1 ✅ | Modularise `commands_extended.py` → 6 focused modules |
| 2 ✅ | pytest suite — 33 tests (cache, fallback, planner, executor, file tools) |
| 3 ✅ | SQLite long-term memory — replaces JSON, WAL mode, keyword search |
| 4 ✅ | Cross-platform — Windows, macOS, Linux |
| 5 ✅ | Semantic KB search — `sentence-transformers` + SQLite BLOB embeddings |
| 6 ✅ | Stream all commands — real-time tokens, no blocking |
| 7 ✅ | Typed exception hierarchy — `AgentError → LLMError → BackendUnavailableError` |
| 8 ✅ | `.env` secret management via `python-dotenv` |
| 9 ✅ | GitHub Actions CI — Python 3.11 & 3.12 matrix + flake8 |
| 10 ✅ | `pyproject.toml` packaging — `pip install -e .` + `ai` CLI |

### Extended Roadmap (v1.1.0)

| Feature | What Was Built |
|---|---|
| REST API Server | FastAPI with 10 endpoints, SSE streaming, CORS, OpenAPI auto-docs at `/docs` |
| Web Chat UI | Dark-theme browser UI — streaming, markdown, syntax highlight, stats panel |
| Dependency Graph | AST import parsing, topological sort (Kahn's), cycle detection, impact analysis |
| Fix Memory | SQLite fix patterns, error normalisation, ranked hint injection into `/fix` |
| Cost Tracker | Groq pricing table (8 models), real token counts from API, daily SQLite history |
| Structured Logging | JSON rotating file log + coloured console, session IDs, `/logs` API endpoint |
| Retry & Backoff | Exponential backoff + jitter, Retry-After header, `@retryable` decorator |
| Git Hooks | `ai --install-hook` / `--strict-hook` / `--remove-hook` |
| VS Code Extension | 12 commands, status bar, context menus, inline fix, task runner |
| API Doc Scanner | AST route scanner (Flask/FastAPI), Markdown + OpenAPI 3.0 YAML generator |

---

## 🛠️ Tested Hardware

- GPU: NVIDIA GTX 1650 (4 GB VRAM) — `phi3:mini` runs fully on GPU at ~30 tok/s
- CPU: AMD Ryzen 5 5660H (6 cores)
- RAM: 8 GB DDR4
- OS: Windows 11 + Ubuntu 22.04

For weaker hardware: `GPU_LAYERS=0` in `.env` or `/config gpu 0` live. Groq (free tier, 300+ tok/s) always available as fallback.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

*Python 3.11 · Ollama · Groq LLaMA 3.3 70B · FastAPI · sentence-transformers · SQLite · pytest · GitHub Actions*
