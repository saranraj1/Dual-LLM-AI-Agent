# 🤖 Autonomous AI Agent

A fully autonomous coding assistant that runs **100% on your local machine** via Ollama, with optional Groq cloud fallback. It reads your entire codebase, plans multi-step tasks, writes files, installs packages, runs code, and self-corrects — all from a simple terminal chat.

> **What makes this different from cloud AI tools:** It has access to your filesystem, runs git hooks, monitors your clipboard, indexes your private docs, sends desktop notifications, and works completely offline.

---

## ✨ Features

### Core
- **Dual LLM backend** — Local `phi3:mini` (Ollama) + auto Groq cloud fallback
- **Autonomous loop** — Plan → Execute → Reflect → Auto-write files → Auto-install packages
- **Full codebase awareness** — Scans and indexes your entire project on startup
- **Multi-turn memory** — Remembers conversation across turns (session + long-term persistent)
- **Response caching** — Identical prompts reuse cached responses (120s TTL)
- **Spinner + ANSI colors** — Rich terminal UI with live progress indicators

### 🖥️ Local-Machine Exclusive Features
| Feature | Description |
|---------|-------------|
| **📋 Clipboard Monitor** | Watches clipboard — copy any code and get instant AI review |
| **🔔 Desktop Notifications** | Windows toast notification when long tasks finish |
| **🔗 Git Pre-commit Hook** | Auto-checks staged files for secrets + lint errors before every commit |
| **📅 Daily Digest** | Shows yesterday's git activity + file changes on startup every day |
| **📚 Local Knowledge Base** | Index your own PDFs, Word docs, notes — agent answers from them |

---

## 🚀 Quick Start

### Prerequisites
```powershell
# Python 3.11+ required
# Install Ollama → https://ollama.com

pip install black flake8    # optional: for /format and /lint
pip install pypdf           # optional: for indexing PDF files
pip install python-docx     # optional: for indexing Word files
```

### Step 1 — Pull the local model
```powershell
ollama pull phi3:mini
```

### Step 2 — Build the custom model
```powershell
cd C:\ai-agent
ollama create qwen-lite -f Modelfile
```

### Step 3 — Start Ollama (keep this running in a separate terminal)
```powershell
ollama serve
```

### Step 4 — Run the agent
```powershell
python -X utf8 C:\ai-agent\main.py
```

---

## 📁 Run from Any Folder

To use the agent on **any project** without navigating to `C:\ai-agent`:

### Option A — Use `--project` flag
```powershell
python -X utf8 C:\ai-agent\main.py --project C:\my-other-project
```

### Option B — PowerShell alias (recommended)
Open your PowerShell profile:
```powershell
notepad $PROFILE
```
Add this line:
```powershell
function ai { python -X utf8 C:\ai-agent\main.py --project $PWD @args }
```
Reload:
```powershell
. $PROFILE
```
Now from **any folder**:
```powershell
cd C:\my-project
ai
```

### Option C — Windows batch file
Create `C:\Windows\ai.bat`:
```batch
@echo off
python -X utf8 C:\ai-agent\main.py --project %CD% %*
```
Then anywhere:
```powershell
cd C:\my-project
ai
```

---

## 💬 All Commands

### 🤖 Agent
| Command | Description |
|---------|-------------|
| `/run <task>` | Autonomous: plan → execute → write files → reflect |
| `/scan [path]` | Re-scan workspace or switch to different project |
| `/watch` | Watch for file changes and auto-review on save |

```
/run create a FastAPI REST API with JWT authentication
/run add unit tests for all functions in utils.py
/run fix all the bugs in my project
```

---

### 🔍 Code Quality
| Command | Description |
|---------|-------------|
| `/review [file]` | Code review scored 1-10 on readability, perf, security |
| `/fix [file]` | Scan for errors and auto-fix them |
| `/optimize <file>` | Performance-focused rewrite |
| `/refactor <file>` | SOLID principles rewrite |
| `/security [file]` | Security audit with CRITICAL/HIGH/MEDIUM/LOW ratings |
| `/test [file]` | Generate comprehensive tests and run them |
| `/lint [file\|fix]` | Run flake8; use `fix` to auto-fix issues |
| `/format [file]` | Auto-format with black (autopep8 fallback) |
| `/todo [fix]` | List/fix all TODO/FIXME comments |

```
/review main.py
/security                 ← audit entire project
/lint fix                 ← AI auto-fixes all lint issues
/format                   ← format all .py files
```

---

### 📁 Files & Translation
| Command | Description |
|---------|-------------|
| `/explain <file>` | Deep explanation of a file |
| `/diff [file]` | Show changes vs git/backup |
| `/undo <file>` | Restore file to pre-agent backup |
| `/run-file <file>` | Run file; auto-fix if it crashes |
| `/translate <file> <lang>` | Rewrite code in another language |

```
/undo main.py
/translate main.py typescript
/translate app.js python
/run-file scripts/process_data.py
```

---

### 📊 Project
| Command | Description |
|---------|-------------|
| `/docs [file]` | Generate README or add docstrings |
| `/scaffold <type>` | Create full project boilerplate |
| `/diagram` | ASCII + Mermaid architecture diagram |
| `/stats` | Lines of code, file counts, largest files |
| `/deps` | Dependency analysis + install status |
| `/summarize [file]` | Plain-English project summary |
| `/changelog` | Generate CHANGELOG.md from git history |
| `/git [message]` | Smart git commit with AI message |

**Scaffold types:**
```
/scaffold flask-api    /scaffold fastapi      /scaffold react-app
/scaffold cli-tool     /scaffold discord-bot  /scaffold ml-project
/scaffold scraper
```

---

### 🧠 Memory, Mode & Settings
| Command | Description |
|---------|-------------|
| `/history [n]` | Show last n conversation turns |
| `/memory` | Memory stats + cache hits + API call counts |
| `/clear` | Wipe session and long-term memory |
| `/mode <name>` | Switch agent personality |
| `/model [backend]` | Switch backend: auto / local / groq |
| `/config [key val]` | View/change settings live |
| `/benchmark` | Compare local Ollama vs Groq speed |

**Modes:**
```
/mode debug      ← find and fix errors
/mode architect  ← system design + patterns
/mode tutor      ← beginner-friendly explanations
/mode fast       ← code-only concise answers
/mode review     ← auto-review everything shown
/mode normal     ← default
```

**Config examples:**
```
/config                  ← show all settings
/config gpu 15           ← change GPU layers
/config ctx 1024         ← change context window
/config tokens 512       ← change max response length
/config backend groq     ← force Groq cloud
```

**Backend switching:**
```
/model               ← show current backend
/model auto          ← Ollama → Groq fallback (default)
/model local         ← local only (phi3:mini)
/model groq          ← cloud only (llama-3.3-70b) ⚡
```

---

### 🌐 Web & Export
| Command | Description |
|---------|-------------|
| `/ask <url> [q]` | Fetch a URL and ask about its content |
| `/search <query>` | DuckDuckGo search + AI answer |
| `/export [file]` | Save full chat history to markdown |

```
/ask https://docs.python.org/3/library/asyncio.html how to use gather?
/search how to implement rate limiting in FastAPI
/export session_log.md
```

---

### 🖥️ Local Machine Features

#### 📋 Clipboard Monitor
Auto-reviews any code you copy — from your browser, Stack Overflow, GitHub, etc.

| Command | Description |
|---------|-------------|
| `/clip on` | Start watching clipboard for code |
| `/clip off` | Stop watching |
| `/clip` | Show current status |

```
/clip on
# Now copy any code from anywhere — agent reviews it instantly
/clip off
```

#### 📚 Knowledge Base
Index your own private documents so the agent can answer from them.

| Command | Description |
|---------|-------------|
| `/kb add <file\|folder>` | Index documents into knowledge base |
| `/kb search <query>` | Search indexed knowledge |
| `/kb list` | List all indexed documents |
| `/kb clear` | Remove all indexed documents |
| `/kb` | Show KB status |

```
/kb add C:\my-notes\architecture.pdf
/kb add C:\docs\api-specs\
/kb list
/kb search authentication flow
```

**Supported formats:** `.txt` `.md` `.pdf` `.docx` `.py` `.js` `.json` `.csv` `.yaml`

#### 📅 Daily Digest
| Command | Description |
|---------|-------------|
| `/digest` | Show today's git activity, modified files, memory summary |

Shown automatically once per day on startup. Shows:
- Yesterday's git commits
- Files modified in last 24h
- Recent work from long-term memory
- Knowledge base stats + daily tip

#### ⏱️ Session Timer
| Command | Description |
|---------|-------------|
| `/time` | Session duration, tasks run, LLM calls, cache hits |

```
⏱️  Session Statistics
────────────────────────────────────────
  Duration    : 01h 23m 45s
  Tasks run   : 7
  Chat turns  : 24
  Backend     : auto
  LLM Calls:
    Ollama calls : 18
    Groq calls   : 3
    Cache hits   : 6 (avoided 6 API calls)
```

#### 🔗 Git Pre-commit Hook
Automatically check staged files for secrets + lint errors before every `git commit`.

**Install once per project:**
```powershell
# Standard install (warns only, allows commit)
python C:\ai-agent\scripts\install_git_hook.py --project C:\my-project

# Strict install (blocks commit if critical issues found)
python C:\ai-agent\scripts\install_git_hook.py --project C:\my-project --strict

# Remove hook
python C:\ai-agent\scripts\install_git_hook.py --project C:\my-project --remove
```

**What it checks on every `git commit`:**
- Syntax errors in staged `.py` files (E9, F-class errors)
- Hardcoded secrets: API keys, passwords, tokens, AWS credentials
- To bypass: `git commit --no-verify`

#### 🔔 Desktop Notifications
Automatic — no setup needed. When a `/run` task takes more than 10 seconds, a Windows toast notification appears when it finishes, even if the terminal is minimized.

---

## ⚙️ Configuration

Edit `config/settings.py` for permanent changes:
```python
MODEL_NAME     = "phi3:mini"                  # local model
GROQ_MODEL     = "llama-3.3-70b-versatile"   # cloud model
AUTO_FALLBACK  = True                         # auto-switch to Groq if Ollama fails
GPU_LAYERS     = 33                           # 33 = full phi3:mini fits in 4GB VRAM
CONTEXT_WINDOW = 2048                         # tokens of context per request
MAX_TOKENS     = 512                          # max tokens in response
```

Or change live without restarting:
```
/config gpu 20
/config ctx 1536
/config backend groq
```

---

## 🔄 LLM Backends

| Backend | Model | Speed | Privacy | When to use |
|---------|-------|-------|---------|-------------|
| Local (Ollama) | phi3:mini 3.8B | ~25 tok/s on GTX 1650 | 100% local | Private code, offline |
| Groq (cloud) | llama-3.3-70b | ~300 tok/s | Cloud | Complex tasks, speed |

**Auto-fallback:** Ollama crashes → automatically switches to Groq + shows warning.

---

## 🏗️ Project Structure

```
ai-agent/
├── main.py                       ← entry point + REPL chat loop
├── Modelfile                     ← Ollama model config (phi3:mini)
│
├── config/
│   └── settings.py               ← all settings in one place
│
├── core/
│   ├── llm.py                    ← dual-backend LLM, cache, auto-restart
│   ├── prompt_builder.py         ← smart prompt with token budget
│   └── ui.py                     ← ANSI colors, spinner, formatted print
│
├── agent/
│   ├── agent.py                  ← main loop: Plan→Execute→Reflect→Memory
│   ├── planner.py                ← LLM breaks task into steps
│   ├── executor.py               ← routes each step to the right tool
│   ├── reflection.py             ← self-check: did this step succeed?
│   ├── daily_digest.py           ← startup daily digest (once/day)
│   ├── commands.py               ← /diff /history /undo /explain /test /fix /todo
│   ├── commands_extended.py      ← 30+ extended commands
│   └── watcher.py                ← file watcher for /watch
│
├── memory/
│   ├── short_memory.py           ← session memory (cleared on exit)
│   └── long_memory.py            ← persistent JSON (~/.ai_agent/)
│
├── tools/
│   ├── file_tools.py             ← file read/write/scan
│   ├── code_tools.py             ← run Python, install packages
│   ├── terminal_tools.py         ← run shell commands safely
│   ├── clipboard_monitor.py      ← background clipboard code detector
│   ├── knowledge_base.py         ← local doc indexer + search
│   └── notifications.py          ← Windows toast notifications
│
└── scripts/
    └── install_git_hook.py       ← installs git pre-commit hook
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---------|-----|
| `Ollama not running` | Run `ollama serve` in a separate terminal |
| `Model not found` | Run `ollama pull phi3:mini` then `ollama create qwen-lite -f Modelfile` |
| `HTTP 500 / OOM` | Out of memory — use `/model groq` or `/config gpu 0` |
| `Slow responses` | Use `/model groq` or `/config ctx 512` |
| `Emoji broken` | Run with `python -X utf8 main.py` |
| `Groq 403 error` | API key invalid — update `GROQ_API_KEY` in `config/settings.py` |
| `Notifications not showing` | Windows 10/11 only — check Focus Assist settings |
| `PDF indexing fails` | Run `pip install pypdf` |
| `DOCX indexing fails` | Run `pip install python-docx` |

---

## 📝 Tips & Tricks

- **Start with `/digest`** to see what changed since yesterday
- **`/clip on`** while reading Stack Overflow — instant reviews as you copy code
- **`/kb add C:\my-notes`** to give the agent context from your private docs
- **`/model groq`** for complex architecture questions (70B model is much smarter)
- **`/model local`** for quick edits, private code, or offline work
- **`/undo <file>`** always works — every file is backed up before agent edits it
- **`/benchmark`** to see actual speed difference between local and cloud
- **`/time`** to see how many API calls were saved by caching
- Run `/run` from **any folder** — the agent operates on `--project` path

---

## 📄 License

MIT License — free to use, modify, and extend.
