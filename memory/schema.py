"""
memory/schema.py — DDL specifications, indices, and FTS5 virtual tables
for the 4-tier hybrid memory subsystem.
"""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 1. Conversation Turns (Workspace & Session Scoped)
CREATE TABLE IF NOT EXISTS conversation_turns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    workspace     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content       TEXT NOT NULL,
    token_count   INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_turns_ws_session ON conversation_turns(workspace, session_id);
CREATE INDEX IF NOT EXISTS idx_turns_ws_created ON conversation_turns(workspace, created_at DESC);

-- FTS5 Virtual Table for Conversation Turn Full-Text Search
CREATE VIRTUAL TABLE IF NOT EXISTS conversation_turns_fts USING fts5(
    content,
    content='conversation_turns',
    content_rowid='id'
);

-- Triggers to sync conversation_turns with FTS5 table
CREATE TRIGGER IF NOT EXISTS trg_turns_ai AFTER INSERT ON conversation_turns BEGIN
    INSERT INTO conversation_turns_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS trg_turns_ad AFTER DELETE ON conversation_turns BEGIN
    INSERT INTO conversation_turns_fts(conversation_turns_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS trg_turns_au AFTER UPDATE ON conversation_turns BEGIN
    INSERT INTO conversation_turns_fts(conversation_turns_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO conversation_turns_fts(rowid, content) VALUES (new.id, new.content);
END;


-- 2. Episodic Task Memory (Multi-Step Trajectories & Checkpoint Links)
CREATE TABLE IF NOT EXISTS episodic_tasks (
    id             TEXT PRIMARY KEY,
    workspace      TEXT NOT NULL,
    task_goal      TEXT NOT NULL,
    trajectory     TEXT NOT NULL,                     -- JSON array of steps
    files_touched  TEXT NOT NULL DEFAULT '[]',        -- JSON array of file paths
    blast_radius   TEXT DEFAULT '{}',                 -- JSON call graph impact
    checkpoint_id  TEXT DEFAULT NULL,                 -- Linked snapshot SHA
    status         TEXT NOT NULL CHECK(status IN ('SUCCESS', 'FAILED', 'PARTIAL', 'REVERTED')),
    error_summary  TEXT DEFAULT NULL,
    turns_count    INTEGER DEFAULT 1,
    duration_sec   REAL DEFAULT 0.0,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_episodes_ws ON episodic_tasks(workspace, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodic_tasks(workspace, status);


-- 3. Structured Facts & Architectural Decisions (ADR)
CREATE TABLE IF NOT EXISTS knowledge_facts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace      TEXT NOT NULL,
    category       TEXT NOT NULL CHECK(category IN ('adr', 'convention', 'constraint', 'stack', 'user_preference')),
    subject        TEXT NOT NULL,
    predicate      TEXT NOT NULL,
    object         TEXT NOT NULL,
    raw_content    TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 1.0,
    embedding      BLOB DEFAULT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_accessed  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    hit_count      INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_facts_ws_cat ON knowledge_facts(workspace, category);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON knowledge_facts(workspace, subject);
CREATE INDEX IF NOT EXISTS idx_facts_hits ON knowledge_facts(workspace, hit_count DESC);

-- FTS5 Virtual Table for Structured Facts
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_facts_fts USING fts5(
    subject,
    predicate,
    object,
    raw_content,
    content='knowledge_facts',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS trg_facts_ai AFTER INSERT ON knowledge_facts BEGIN
    INSERT INTO knowledge_facts_fts(rowid, subject, predicate, object, raw_content)
    VALUES (new.id, new.subject, new.predicate, new.object, new.raw_content);
END;

CREATE TRIGGER IF NOT EXISTS trg_facts_ad AFTER DELETE ON knowledge_facts BEGIN
    INSERT INTO knowledge_facts_fts(knowledge_facts_fts, rowid, subject, predicate, object, raw_content)
    VALUES('delete', old.id, old.subject, old.predicate, old.object, old.raw_content);
END;

CREATE TRIGGER IF NOT EXISTS trg_facts_au AFTER UPDATE ON knowledge_facts BEGIN
    INSERT INTO knowledge_facts_fts(knowledge_facts_fts, rowid, subject, predicate, object, raw_content)
    VALUES('delete', old.id, old.subject, old.predicate, old.object, old.raw_content);
    INSERT INTO knowledge_facts_fts(rowid, subject, predicate, object, raw_content)
    VALUES (new.id, new.subject, new.predicate, new.object, new.raw_content);
END;


-- 4. Unified Procedural Reflexes (Expanded FixMemory)
CREATE TABLE IF NOT EXISTS procedural_rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace      TEXT DEFAULT '',
    error_sig      TEXT NOT NULL,
    error_pattern  TEXT NOT NULL,
    repair_action  TEXT NOT NULL,
    file_type      TEXT NOT NULL DEFAULT '.py',
    success_count  INTEGER DEFAULT 1,
    failure_count  INTEGER DEFAULT 0,
    last_triggered TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_proc_sig ON procedural_rules(error_sig);
CREATE INDEX IF NOT EXISTS idx_proc_ws ON procedural_rules(workspace);
"""


def init_memory_db(db_path: str):
    """Initialize a SQLite database with the hybrid memory schema."""
    import sqlite3
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
