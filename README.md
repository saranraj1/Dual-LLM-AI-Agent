# 🤖 Dual-LLM AI Agent

[![CI](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An **autonomous coding assistant** that lives entirely on your machine. It reads your project files, understands your codebase, plans multi-step tasks, writes code, runs tests, commits to git — all from a terminal chat interface.

**Dual LLM backends**: runs Ollama (local, private) first; instantly falls back to Groq cloud (300+ tok/s) if Ollama is busy or unavailable.

---

## ✨ Features

| Category | Commands |
|---|---|
| **Agent** | `/run`, `/scan`, `/watch` — plan + execute + auto-write + reflect |
| **Code Quality** | `/review`, `/fix`, `/optimize`, `/refactor`, `/security`, `/test`, `/lint`, `/format` |
| **Files** | `/explain`, `/diff`, `/undo`, `/run-file`, `/translate` |
| **Project** | `/docs`, `/scaffold`, `/diagram`, `/stats`, `/deps`, `/summarize`, `/changelog`, `/git` |
| **Web** | `/ask <url>`, `/search <query>` |
| **Knowledge Base** | `/kb add`, `/kb search`, `/kb list` — semantic vector search (optional) |
| **Settings** | `/mode`, `/config`, `/benchmark`, `/export`, `/time` |

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/saranraj1/Dual-LLM-AI-Agent.git
cd Dual-LLM-AI-Agent

# Create virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Or install as a package (enables `ai` command anywhere)
pip install -e .
```

### 2. Configure Secrets

```bash
cp .env.example .env
```

Edit `.env` and add your [Groq API key](https://console.groq.com/keys) (free):

```env
GROQ_API_KEY=gsk_your_key_here
OLLAMA_HOST=http://localhost:11434
```

### 3. Start Ollama (Optional but Recommended)

```bash
# Install from https://ollama.com
ollama pull phi3:mini   # 3.8B — fits GTX 1650 4GB VRAM
ollama serve
```

### 4. Launch the Agent

```bash
# From the project folder:
python main.py

# After pip install -e ., from anywhere:
ai

# Point at a specific project:
python main.py --project /path/to/your/project
```

---

## 💬 Usage Examples

```
You › /run add logging to all functions in utils.py
You › /review main.py
You › /refactor agent/executor.py
You › /docs                    ← generate README.md
You › /test agent/planner.py   ← generate + run tests
You › /git                     ← smart commit with AI message
You › /scaffold flask-api      ← create full project boilerplate
You › /kb add docs/            ← index your PDFs and notes
You › /kb search "how to deploy"
You › what does the executor do?  ← plain chat, no slash needed
```

---

## 🏗️ Architecture

```
main.py                   ← CLI entrypoint (also: 'ai' command via pyproject.toml)
├── agent/
│   ├── agent.py          ← main Agent class + chat loop
│   ├── planner.py        ← LLM-powered task → step list
│   ├── executor.py       ← step execution + file writing (path-clamped)
│   ├── reflection.py     ← post-task success/failure analysis
│   └── commands/         ← modular slash commands (Step 1)
│       ├── code_quality.py   /review /optimize /refactor /security /format /lint
│       ├── project.py        /docs /git /summarize /changelog /stats /deps /diagram
│       ├── files.py          /explain /diff /undo /run-file /translate
│       ├── web.py            /ask /search
│       ├── settings.py       /mode /export /config /benchmark
│       └── local.py          /kb /clip /digest /time
├── core/
│   ├── llm.py            ← dual-backend (Ollama + Groq), cache, streaming, fallback
│   ├── exceptions.py     ← typed error hierarchy (AgentError → LLMError → ...)
│   └── prompt_builder.py ← system prompt + context injection
├── memory/
│   ├── short_memory.py   ← in-session conversation turns
│   └── long_memory.py    ← SQLite persistent memory (auto-migrates from JSON)
├── tools/
│   ├── knowledge_base.py ← semantic vector search (sentence-transformers + SQLite)
│   ├── file_tools.py     ← read/write/scan/search
│   ├── terminal_tools.py ← cross-platform shell execution
│   └── notifications.py  ← cross-platform desktop notifications
├── config/settings.py    ← loads .env secrets via python-dotenv
└── tests/                ← pytest suite (33 tests, all passing)
```

---

## 🧪 Testing

```bash
pytest tests/ -v
pytest tests/ --cov=core --cov=agent --cov=tools --cov-report=term-missing
```

All 33 tests pass. CI runs automatically on every push via GitHub Actions.

---

## ⚙️ Configuration

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(from .env)* | Groq cloud API key |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `MODEL_NAME` | `phi3:mini` | Local Ollama model |
| `GPU_LAYERS` | `33` | GPU layers (set to 0 for CPU-only) |
| `MAX_TOKENS` | `512` | Max tokens per LLM response |
| `ALLOW_SHELL` | `True` | Set `False` for read-only/safe mode |

Live config changes: `/config gpu 0` · `/config ctx 4096` · `/model groq`

---

## 🔒 Security

- **Secrets in `.env`** — never committed to git (`.env` is in `.gitignore`)
- **Path clamping** — agent can only write files inside your project folder, even if the LLM hallucinates absolute paths like `C:\system\`
- **Shell blocklist** — dangerous commands (`rm -rf /`, `dd if=`, `shutdown`) are rejected before execution
- **Backup before edit** — every file the agent modifies is backed up to `.agent_backups/`

---

## 🗺️ Roadmap

| Step | Status | Description |
|---|---|---|
| 1 | ✅ | Modularize `commands_extended.py` into focused modules |
| 2 | ✅ | Pytest suite — 33 tests, executor/cache/fallback/planner/file_tools |
| 3 | ✅ | SQLite long-term memory (replaces JSON, auto-migrates) |
| 4 | ✅ | Cross-platform support (Windows / macOS / Linux) |
| 5 | ✅ | Semantic KB search with sentence-transformers |
| 6 | ✅ | Stream all commands (no more blocking waits) |
| 7 | ✅ | Typed exception hierarchy with actionable messages |
| 8 | ✅ | `.env` secret management via python-dotenv |
| 9 | ✅ | GitHub Actions CI (tests + lint, Python 3.11 & 3.12) |
| 10 | ✅ | `pyproject.toml` packaging — install with `pip install -e .` |

---

## 📄 License

MIT — see [LICENSE](LICENSE).
