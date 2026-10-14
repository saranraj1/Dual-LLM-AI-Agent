# Architecture

This document captures the high-level architecture of the Autonomous AI Agent,
including the component data/call flow and the real import dependency graph.

## Component Architecture (Mermaid)

```mermaid
graph TD
    User["USER / CLI"] --> Main["main.py (entry point)"]

    Main --> Agent["agent/agent.py (Agent)"]
    Main --> ServerAPI["server/ (API)"]
    Main --> TDD["agent/tdd_loop.py"]

    Agent --> TDD
    Agent --> Retry["core/retry.py"]
    Agent --> DepGraph["agent/dependency_graph.py"]

    TDD --> Executor["agent/executor.py"]
    Executor --> TDD
    Executor --> DepGraph
    Executor --> Retry
    Executor --> Commands["agent/commands/ (local, review, fix, ...)"]
    Commands --> Executor

    Agent --> Compactor["agent/compactor.py"]
    Agent --> Digest["agent/daily_digest.py"]
    Agent --> QA["agent/interactive_qa.py"]
    Agent --> Planner["agent/planner.py"]

    Compactor --> Config["config/settings.py"]
    Digest --> Retry
    Digest --> Clipboard["tools/clipboard_monitor.py"]
    Digest --> Exceptions["core/exceptions.py"]
    DepGraph --> Config
    QA --> Logger["core/logger.py"]
    QA --> PromptBuilder["core/prompt_builder.py"]
    QA --> CostTracker["core/cost_tracker.py"]
    Planner --> Logger

    Agent --> LLM["core/llm.py (local/groq)"]
    Agent --> UI["core/ui.py"]
    Agent --> Memory["memory/ (state, history)"]
    Agent --> Tools["tools/ (kb, search, clipboard)"]
    Agent --> Tests["tests/"]

    %% CYCLE: agent.tdd_loop -> agent.executor
    %% CYCLE: agent.tdd_loop -> agent.executor -> agent.commands.local
```

## Import Dependency Graph

