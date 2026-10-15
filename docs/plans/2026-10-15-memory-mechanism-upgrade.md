# 4-Tier Hybrid Memory Subsystem Implementation Plan

> **Goal**: Upgrade the AI Agent memory subsystem from a naive recency FIFO buffer into a production-grade 4-tier hybrid memory engine (Working, Episodic, Procedural, and Semantic/ADR) with SQLite WAL, FTS5 full-text indexing, vector similarity, and workspace-scoped retrieval.
> **Architecture**: Tier 1 (WorkingState & Turn Compactor) -> Tier 2 (Episodic Trajectories & Checkpoint Links) -> Tier 3 (Procedural Fix & Reflex Rules) -> Tier 4 (Semantic Facts & FTS5/Vector Store).
> **Tech Stack**: Python 3.11+, SQLite (WAL mode, FTS5), sentence-transformers (optional vector fallback), dataclasses, pytest.

---

### Phase 1: Storage Engine & Workspace-Scoped Database
- **Files**:
  - Create: `memory/schema.py` (DDL for conversation_turns, episodic_tasks, knowledge_facts, procedural_rules)
  - Create: `memory/storage.py` (Thread-safe SQLite connection pool, WAL mode, pragmas)
  - Modify: `memory/long_memory.py` (Adapt to delegate to `memory/storage.py` with workspace isolation)
  - Test: `tests/test_hybrid_memory.py`

### Phase 2: Hybrid Retrieval & Ranking (FTS5 + Dense Embeddings)
- **Files**:
  - Create: `memory/retrieval.py` (Composite score: BM25 FTS5 + Dense Cosine Similarity + Recency Decay)
  - Test: `tests/test_hybrid_memory.py` (Test semantic relevance across 50+ interleaved turns)

### Phase 3: Episodic Task Trajectory Logger
- **Files**:
  - Create: `memory/episodic_memory.py` (Trajectory recorder for task goals, tool calls, checkpoints)
  - Modify: `agent/react_harness.py` (Record step trajectory events into episodic memory)
  - Modify: `agent/tdd_loop.py` (Record Red-Green-Heal cycles and test outcomes)
  - Test: `tests/test_hybrid_memory.py`

### Phase 4: Fact Extraction & Procedural Reflexes
- **Files**:
  - Create: `memory/fact_extractor.py` (Heuristic and structured extractor for ADRs, conventions, constraints)
  - Modify: `agent/tool_interceptor.py` (Intercept tool failures and query procedural rules for instant repair hints)
  - Test: `tests/test_hybrid_memory.py`

### Phase 5: Prompt Budgeting & Context Synthesizer Integration
- **Files**:
  - Modify: `core/prompt_builder.py` (Budget-aware memory injection: 40% working, 30% facts, 20% episodes, 10% safety)
  - Modify: `server/api.py` (Add `/api/memory/search`, `/api/memory/facts`, `/api/memory/episodes`)
  - Test: Full regression run (`pytest -q`, 194+ tests)
