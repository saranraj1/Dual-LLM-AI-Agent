# Dual-LLM AI Agent

[![CI](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/saranraj1/Dual-LLM-AI-Agent/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-194%20passing-brightgreen.svg)](#testing-and-verification)
[![Version](https://img.shields.io/badge/version-1.2.0-blueviolet.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local-first autonomous software engineering runtime. It indexes repositories, computes AST dependency graphs and blast radii, runs self-healing test-driven development loops, executes multi-turn tool calling with time-travel checkpoints, and provides interfaces across terminal, REST API, Web UI, and VS Code.

The system uses a dual-backend LLM architecture: it prioritizes local inference via Ollama for offline privacy and transparently fails over to Groq Cloud (300+ tokens/sec) whenever local compute is unavailable or times out.

---

## What's New in v1.2.0

- **ReAct Autonomous Task Engine**: Multi-turn reasoning loop (`/react`, `POST /react/stream`) executing structured thought, tool action, and observation cycles with step-level rollback protection.
- **Multi-Subagent Delegation Pool**: Parallel task delegation (`/delegate`, `POST /api/delegate`) across specialized, sandboxed roles: `researcher` (codebase indexing), `test_runner` (isolated test execution), and `reviewer` (diff risk analysis).
- **AST Call Graph & Blast Radius Analysis**: Static AST inspection (`/blast`, `GET /blast`, `GET /graph`) identifying direct callers, downstream dependency chains, and impacted test suites before code modifications are committed.
- **Self-Healing TDD Engine**: Automated Red-Green-Heal cycle (`/tdd`, `run_tdd_cycle`) that generates failing test suites, writes implementations, and applies surgical search/replace patches until all assertions pass.
- **Time-Travel Checkpoint System**: Snapshot engine (`/checkpoint`, `POST /checkpoint`) tracking SHA-indexed workspace states, enabling instantaneous rollbacks, diff comparisons, and file recovery.
- **Context Compactor & Working Memory Ledger**: Automatic token compactor (`/compact`, `POST /api/compact`) preserving recent conversational turns while archiving older interactions to prevent context window degradation.
- **Web UI 2.0**:
  - Non-snapping scroll engine with manual-gesture decoupling and floating jump-to-bottom controls.
  - Stream-safe Mermaid visualizer: keeps incomplete streaming blocks inside safe syntax containers until generation completes, with automated edge-label quoting and subgraph balancing.
  - Live ReAct trace drawers with dedicated collapsible cards for thoughts, tool calls, and observations.
  - Interactive SVG radial token burn gauge, input/output token split meters, and micro-dollar cost tracking with instant session reset (`POST /stats/reset`).
- **SWE-Bench & Concurrency Benchmark Suite**: Built-in evaluation runner (`eval/swe_benchmark.py`) and live multi-threaded HTTP/SSE stress harness (`benchmarks/run_concurrency_bench.py`).
- **Comprehensive Test Coverage**: Expanded test suite from 33 to 194 passing tests with zero regressions.

---

## Benchmark & Performance Evaluation

### SWE-Bench Autonomous Challenge Suite

The autonomous problem-solving suite tests the agent on end-to-end implementation and debugging tasks across distinct software engineering domains. Each challenge executes inside an isolated sandbox with automated pytest verification.

```
SWE Benchmark & Evaluation Report (v1.2.0)
Backend     : Groq Cloud (Qwen 3.8 27B / LLaMA 3.3 70B)
Pass Rate   : 100.0% (4/4 passed)
Avg Latency : 11.04s per task
Total Time  : 60.39s
```

| Challenge | Category | Time | Status | Architectural Solution |
| :--- | :--- | :--- | :--- | :--- |
| **O(1) LRU Cache** | Algorithm | 2.0s | Passed | Dual HashMap + Doubly Linked List with $O(1)$ node eviction |
| **Exponential Backoff Retry** | System Patterns | 1.2s | Passed | Function decorator with jitter, exception filtering, and delay scaling |
| **Nested Key Path Extractor** | Data Access | 2.1s | Passed | Safe traversal supporting dot notation and array index brackets |
| **Token Bucket Rate Limiter** | Concurrency | 38.9s | Passed | Monotonic clock synchronization with automatic backoff recovery |

### Concurrency Stress Testing & Throughput

Measured using `benchmarks/run_concurrency_bench.py` against the running FastAPI daemon under multi-threaded load:

| Target Endpoint | Method | Concurrent Workers | Total Requests | Throughput | Latency (p50) | Latency (p95) | Error Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/stats` | GET | 4 | 12 | 1.25 req/s | 2058 ms | 2080 ms | 0.0% |
| `/files` | GET | 4 | 12 | 0.99 req/s | 2290 ms | 3980 ms | 0.0% |
| `/graph` | GET | 4 | 12 | 0.79 req/s | 3103 ms | 5777 ms | 0.0% |
| `/api/delegate` | POST | 4 | 4 | 0.59 req/s | 4811 ms | 5638 ms | 0.0% |
| `/chat` (SSE Stream) | POST | 4 | 4 streams | Continuous | 38.7 s | 208.5 s | 0.0% |

- **Database Concurrency**: Tested under 10 parallel threads executing 20 writes each across `ShortMemory`, `LongMemory`, `FixMemory`, and `CostTracker`. Zero SQLite lock errors (`SQLITE_BUSY`) observed under WAL mode.
- **Fallback Latency**: Configured `OLLAMA_TIMEOUT = 15s` and single-retry backoff in `core/llm.py`, preventing local GPU hang scenarios from stalling interactive chat sessions.

---

## Quickstart

### 1. Requirements & Installation

- Python 3.11 or higher
- Git
- (Optional) [Ollama](https://ollama.ai) for local offline execution

```bash
git clone https://github.com/saranraj1/Dual-LLM-AI-Agent.git
cd Dual-LLM-AI-Agent

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install with server, semantic search, and dev tools
pip install -e ".[all]"
```

### 2. Configure Environment

Copy the example environment template:

```bash
cp .env.example .env
```

Edit `.env` to configure backend settings and API keys:

```env
# Cloud fallback key (free tier available at https://console.groq.com/keys)
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=qwen/qwen3.8-27b

# Local Ollama settings
LOCAL_MODEL=phi3:mini
OLLAMA_HOST=http://localhost:11434
OLLAMA_TIMEOUT=15
GROQ_TIMEOUT=30

# Operational options
AUTO_FALLBACK=True
CONFIRM_EDITS=False
```

### 3. Local Model Setup (Optional)

To run fully offline on a local GPU or CPU:

```bash
ollama pull phi3:mini
ollama serve
```

If Ollama is stopped or unreachable, requests automatically route to Groq Cloud.

### 4. Running the Agent

**Interactive Terminal Session:**
```bash
python main.py
# Or using the global package binary:
ai
```

**Web UI & REST API Daemon:**
```bash
python main.py --serve
# Or:
ai --serve --port 8000
```
Open `http://localhost:8000` in your browser. Interactive OpenAPI documentation is served at `http://localhost:8000/docs`.

**One-Shot Command Line Execution:**
```bash
ai --task "Generate unit tests for core/security.py"
```

**Target a Specific Workspace:**
```bash
ai --project /path/to/another/repository
```

---

## Architecture

```
Dual-LLM-AI-Agent/                           v1.2.0
├── main.py                          CLI entry point, interactive loop, arg parser
│
├── agent/                           Autonomous reasoning & execution engines
│   ├── agent.py                     Core agent coordinator & prompt dispatcher
│   ├── react_harness.py             ReAct loop: Thought -> Action -> Observation
│   ├── subagent_pool.py             Worker pool: Researcher, Test Runner, Reviewer
│   ├── tdd_loop.py                  Autonomous Red-Green-Heal TDD engine
│   ├── checkpoints.py               Workspace snapshot and rollback coordinator
│   ├── compactor.py                 Context compactor & working memory ledger
│   ├── dependency_graph.py          AST call graph, topological sort, cycle detection
│   ├── interactive_qa.py            Ambiguity detection and user prompt resolution
│   ├── tool_interceptor.py          Structured tool registry and execution parser
│   ├── planner.py                   Multi-step execution planning engine
│   ├── executor.py                  Safe file writes, search/replace diff engine
│   ├── reflection.py                Automated error analysis and recovery
│   └── commands/                    Modular CLI command implementations
│
├── core/                            Core infrastructure
│   ├── llm.py                       Dual backend router (Ollama + Groq fallback)
│   ├── cost_tracker.py              Token usage accounting and USD cost accumulator
│   ├── security.py                  Path sandboxing, secret masking, safety blocklists
│   ├── retry.py                     Exponential backoff with jitter and retry headers
│   ├── logger.py                    Rotating structured JSON logger
│   └── prompt_builder.py            Dynamic system prompt and context budgeter
│
├── memory/                          State persistence
│   ├── short_memory.py              In-session working turn window
│   ├── long_memory.py               Persistent SQLite memory with WAL mode
│   └── fix_memory.py                Pattern recognition database for recurring bug fixes
│
├── server/                          HTTP & Web interface
│   ├── api.py                       FastAPI REST API with SSE endpoints
│   └── static/index.html            Single-page Web UI with live streaming telemetry
│
├── tools/                           Autonomous agent capabilities
│   ├── checkpoint_tools.py          File snapshotting and rollback primitives
│   ├── graph_tools.py               AST caller parsing and blast-radius calculator
│   ├── preflight_tools.py           Preflight Python AST syntax validator
│   ├── terminal_tools.py            Sandboxed process execution with timeout guards
│   ├── knowledge_base.py            Local document embeddings and semantic search
│   └── api_doc_scanner.py           Automated OpenAPI 3.0 route generator
│
├── eval/                            Automated evaluation benchmarks
│   └── swe_benchmark.py             SWE-bench challenge suite and report generator
│
├── benchmarks/                      Performance & load testing
│   └── run_concurrency_bench.py     Live multi-threaded HTTP/SSE stress benchmark
│
├── vscode-extension/                VS Code integration
│   ├── package.json                 Command contributions and keybindings
│   └── src/extension.js             Language server bridge to REST API
│
└── tests/                           194 passing pytest unit and integration tests
```

---

## Command Reference

The terminal interface supports plain English queries alongside specialized slash commands:

### Code Quality & TDD

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/tdd` | `<feature description>` | Run autonomous Red-Green-Heal cycle: writes tests, creates implementation, repairs failures |
| `/review` | `[file]` | Multi-metric code review scoring readability, maintainability, and security |
| `/fix` | `[file]` | Scan for syntax, runtime, and import errors; applies learned fix patterns |
| `/optimize` | `<file>` | Refactor code for algorithmic performance and reduced memory allocation |
| `/refactor` | `<file>` | Restructure code to improve modularity and adhere to SOLID principles |
| `/security` | `[file]` | Perform vulnerability audit scanning for OWASP top-10, leaks, and unsafe calls |
| `/test` | `[file]` | Generate pytest suites covering standard and edge-case execution paths |
| `/lint` | `[file\|fix]` | Run flake8 validation; `/lint fix` applies automatic formatting corrections |
| `/format` | `[file]` | Format Python source files using black conventions |

### Graph & Blast Radius

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/blast` | `<symbol>` | Calculate AST caller blast radius, identifying affected modules and test suites |
| `/diagram` | — | Generate ASCII and Mermaid architecture diagrams written to `docs/architecture.md` |
| `/deps` | — | Analyze project imports, detecting missing, unused, and circular dependencies |

### Checkpoints & State Management

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/checkpoint` | `[tag]` | Create an atomic snapshot of the current workspace state |
| `/checkpoints` | — | List all historical snapshots with timestamps and tracked file counts |
| `/undo` | `<file>` | Revert modifications made to a file back to its pre-agent state |
| `/compact` | — | Trigger context compaction to prune conversation turns and reduce prompt budget |
| `/history` | `[n]` | Query historical messages from the SQLite long-term memory store |
| `/memory` | — | Display current session state, cache performance, and learned fix patterns |
| `/time` | — | Output session duration, total tokens consumed, and accumulated inference cost |

### Multi-Agent & Project Execution

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/run` | `<task>` | Execute autonomous planning, multi-step execution, and verification |
| `/react` | `<task>` | Launch ReAct loop with real-time thought-action-observation traces |
| `/delegate` | `<role> <task>` | Delegate subtask to an isolated worker (`researcher`, `test_runner`, `reviewer`) |
| `/scaffold` | `<type>` | Generate a boilerplate project skeleton (fastapi, react, cli, ml) |
| `/docs` | `[api]` | Generate docstrings for source files or export OpenAPI 3.0 specifications |
| `/git` | `[message]` | Stage changes and generate a structured conventional commit message from git diff |
| `/watch` | — | Run background file watcher that automatically reviews and checks saved files |

---

## REST API Reference

The FastAPI server provides endpoints for programmatic integration, SSE streaming, and status monitoring.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Web Chat UI single-page interface |
| `GET` | `/health` | Health probe reporting Ollama and Groq availability |
| `GET` | `/stats` | Cumulative session token counts, model calls, and cost metrics |
| `POST` | `/stats/reset` | Reset current session telemetry counters |
| `POST` | `/chat` | Server-Sent Events (SSE) streaming chat endpoint |
| `POST` | `/run` | Autonomous task planning and execution stream |
| `POST` | `/react/stream` | Multi-turn ReAct execution with step-level trace events |
| `POST` | `/command` | Execute any terminal slash command over HTTP |
| `POST` | `/api/delegate` | Delegate task to a specific worker role in the subagent pool |
| `POST` | `/api/compact` | Trigger context window compaction |
| `GET` | `/checkpoint` | List historical workspace checkpoints |
| `POST` | `/checkpoint` | Create a new atomic workspace snapshot |
| `POST` | `/checkpoint/rollback` | Rollback workspace to a designated snapshot ID |
| `GET` | `/graph` | Export workspace AST dependency graph in node-link JSON format |
| `GET` | `/blast` | Query symbol blast radius, callers, and impacted test paths |
| `POST` | `/benchmark/swe` | Trigger SWE-bench autonomous challenge evaluation suite |
| `GET` | `/files` | List workspace files with path traversal and secret exclusion guards |
| `GET` | `/logs` | Return tail of structured JSON log file with masked sensitive data |

---

## Security & Sandboxing

The agent operates on local repositories with defense-in-depth safety controls:

- **Path Clamping**: All read, write, and append operations are validated through `core.security.sanitize_path` and `validate_workspace`. File access outside the active repository root is strictly forbidden.
- **Sensitive File Exclusion**: Access to `.env`, `.git`, SSH keys, private certificates, and credentials is blocked across API file listings, prompt context builders, and automated search tools.
- **Shell Blocklist**: Destructive terminal invocations (`rm -rf`, `mkfs`, fork bombs, system shutdown, unauthorized curl-to-shell pipes) are intercepted and rejected prior to process execution.
- **Atomic Edit Backups**: Before any source file is modified or patched, an original snapshot is archived in `.agent_backups/` and registered with the rollback engine.
- **Secret Scrubbing**: Prompts, terminal logs, and API outputs pass through `mask_secrets` to redact API keys and bearer tokens from logs and telemetry.

---

## Testing & Verification

The project enforces automated test verification using `pytest`:

```bash
# Run the complete test suite (194 tests)
pytest -q

# Run with verbose output and test coverage
pytest tests/ -v --cov=core --cov=agent --cov=tools --cov=memory

# Run concurrency stress test suite
pytest tests/test_concurrency_stress.py -v

# Run live server concurrency benchmark (requires 'python main.py --serve')
python benchmarks/run_concurrency_bench.py 4 3

# Run live SWE-bench evaluation suite
python -c "from eval.swe_benchmark import run_swe_benchmark, format_benchmark_report; print(format_benchmark_report(run_swe_benchmark(backend='groq')))"
```

Continuous integration runs across Python 3.11 and 3.12 via GitHub Actions.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
