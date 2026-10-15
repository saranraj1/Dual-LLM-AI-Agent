"""
tests/test_hybrid_memory.py — Test suite for 4-tier hybrid memory engine.
"""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from memory.schema import init_memory_db
from memory.storage import MemoryStorage, normalize_workspace
from memory.retrieval import HybridRetrievalEngine
from memory.long_memory import LongMemory
from memory.episodic_memory import EpisodicMemory, Episode
from memory.fact_extractor import extract_facts_from_text, auto_record_turn_facts
from server.api import app


@pytest.fixture
def test_db_path(tmp_path):
    """Provide an isolated database path in a temp directory."""
    db_file = tmp_path / "test_memory.db"
    return str(db_file)


class TestMemorySchemaAndStorage:
    def test_schema_init(self, test_db_path):
        conn = init_memory_db(test_db_path)
        cursor = conn.cursor()
        
        # Verify base tables exist
        tables = [
            r[0] for r in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "conversation_turns" in tables
        assert "episodic_tasks" in tables
        assert "knowledge_facts" in tables
        assert "procedural_rules" in tables
        assert "conversation_turns_fts" in tables
        assert "knowledge_facts_fts" in tables
        conn.close()

    def test_storage_turns_and_workspace_scoping(self, test_db_path, tmp_path):
        storage = MemoryStorage(db_path=test_db_path)
        ws_a = str(tmp_path / "project_a")
        ws_b = str(tmp_path / "project_b")

        turn_a = storage.add_turn("user", "Hello Project A", workspace=ws_a)
        turn_b = storage.add_turn("user", "Hello Project B", workspace=ws_b)

        assert turn_a > 0
        assert turn_b > 0

        turns_a = storage.get_turns(workspace=ws_a)
        assert len(turns_a) == 1
        assert turns_a[0]["content"] == "Hello Project A"

        turns_b = storage.get_turns(workspace=ws_b)
        assert len(turns_b) == 1
        assert turns_b[0]["content"] == "Hello Project B"

    def test_storage_facts(self, test_db_path, tmp_path):
        storage = MemoryStorage(db_path=test_db_path)
        ws = str(tmp_path / "project_facts")

        fact_id = storage.add_fact(
            category="architecture",
            fact_key="state_management",
            fact_value="Use Redux Toolkit for centralized state",
            workspace=ws,
            confidence=0.95
        )
        assert fact_id > 0

        facts = storage.get_facts(workspace=ws)
        assert len(facts) == 1
        assert facts[0]["fact_key"] == "state_management"
        assert facts[0]["confidence"] == 0.95

    def test_storage_procedural_rules(self, test_db_path):
        storage = MemoryStorage(db_path=test_db_path)
        rule_id = storage.record_procedural_rule(
            error_sig="modulenotfound_requests",
            error_snippet="ModuleNotFoundError: No module named 'requests'",
            fix_action="pip install requests",
            file_type=".py"
        )
        assert rule_id > 0

        rules = storage.get_procedural_rules("modulenotfound_requests")
        assert len(rules) == 1
        assert rules[0]["fix_action"] == "pip install requests"


class TestHybridRetrieval:
    def test_bm25_turn_search(self, test_db_path, tmp_path):
        storage = MemoryStorage(db_path=test_db_path)
        ws = str(tmp_path / "search_ws")
        storage.add_turn("user", "Configure PostgreSQL connection pool in config.py", workspace=ws)
        storage.add_turn("assistant", "Database connection established with max 20 connections", workspace=ws)
        storage.add_turn("user", "Update the CSS stylesheet colors for dark mode", workspace=ws)

        engine = HybridRetrievalEngine(storage)
        results = engine.search_conversation_memory("PostgreSQL database", workspace=ws, limit=5)
        assert len(results) > 0
        assert any("PostgreSQL" in r["content"] or "Database" in r["content"] for r in results)

    def test_bm25_fact_search(self, test_db_path, tmp_path):
        storage = MemoryStorage(db_path=test_db_path)
        ws = str(tmp_path / "fact_search_ws")
        storage.add_fact("database", "db_engine", "Always use SQLite WAL mode for concurrency", workspace=ws)
        storage.add_fact("ui", "color_scheme", "Use slate and zinc dark theme", workspace=ws)

        engine = HybridRetrievalEngine(storage)
        results = engine.search_knowledge_facts("SQLite WAL concurrency", workspace=ws)
        assert len(results) > 0
        assert results[0]["fact_key"] == "db_engine"


class TestLongMemoryAdapter:
    def test_backward_compatibility(self, test_db_path, tmp_path):
        ws = str(tmp_path / "adapter_ws")
        with patch("memory.storage.DEFAULT_DB_PATH", Path(test_db_path)):
            storage = MemoryStorage(db_path=test_db_path)
            lm = LongMemory(workspace=ws, storage=storage)

            # Test legacy add and get_turns
            lm.add("user", "Legacy turn 1")
            lm.add("assistant", "Legacy turn 2")
            lm.save()

            turns = lm.get_turns(limit=10)
            assert len(turns) == 2
            assert turns[0]["role"] == "user"
            assert turns[1]["role"] == "assistant"

            # Test get_context
            ctx = lm.get_context(max_chars=200)
            assert "Legacy turn 1" in ctx
            assert "Legacy turn 2" in ctx

            # Test stats
            stats = lm.stats()
            assert stats["total_turns"] == 2

            # Test clear
            lm.clear()
            assert lm.stats()["total_turns"] == 0

    def test_query_driven_context_and_facts(self, test_db_path, tmp_path):
        ws = str(tmp_path / "query_ws")
        storage = MemoryStorage(db_path=test_db_path)
        lm = LongMemory(workspace=ws, storage=storage)

        lm.add("user", "Configure Redis cache for session storage")
        lm.add("user", "Set up Docker compose file for nginx")
        lm.add_fact("cache", "session_store", "Use Redis db=1 for sessions")

        # Query relevant context
        ctx = lm.get_context(query="Redis cache", max_chars=300)
        assert "Redis" in ctx

        # Query facts
        facts = lm.get_facts(query="Redis")
        assert len(facts) > 0
        assert facts[0]["fact_key"] == "session_store"


class TestEpisodicMemory:
    def test_record_and_retrieve_episodes(self, test_db_path, tmp_path):
        ws = str(tmp_path / "ep_ws")
        storage = MemoryStorage(db_path=test_db_path)
        em = EpisodicMemory(storage=storage)

        steps = [
            {"thought": "Inspect file", "action": "read_file", "observation": "file content"},
            {"thought": "Patch bug", "action": "write_file", "observation": "saved"}
        ]
        ep_id = em.record_episode(
            task="Fix null pointer exception in auth.py",
            task_type="react",
            success=True,
            steps=steps,
            workspace=ws,
            duration_secs=3.5,
            git_commit="abc1234"
        )
        assert bool(ep_id)

        episodes = em.get_episodes(workspace=ws)
        assert len(episodes) == 1
        assert episodes[0].task == "Fix null pointer exception in auth.py"
        assert len(episodes[0].steps) == 2

        search_res = em.search_episodes("auth null pointer", workspace=ws)
        assert len(search_res) == 1
        assert search_res[0].git_commit == "abc1234"


class TestFactExtractor:
    def test_extract_facts_from_text(self):
        text = """
        ADR-004: We decided to use FastAPI instead of Flask for higher throughput.
        Tech stack: Python 3.11 with SQLAlchemy 2.0.
        Convention: always use snake_case for private functions.
        Constraint: never execute raw shell commands directly.
        """
        facts = extract_facts_from_text(text)
        keys = [f["fact_key"] for f in facts]
        assert "adr-004" in keys
        assert any("python" in k.lower() or "tech_stack" in k.lower() for k in keys)

    def test_auto_record_turn_facts(self, test_db_path, tmp_path):
        ws = str(tmp_path / "auto_facts_ws")
        storage = MemoryStorage(db_path=test_db_path)
        lm = LongMemory(workspace=ws, storage=storage)

        with patch("memory.fact_extractor.LongMemory", return_value=lm):
            count = auto_record_turn_facts(ws, "Architecture rule: use JWT with RS256 for user tokens")
            assert count >= 1
            facts = lm.get_facts()
            assert len(facts) >= 1


class TestMemoryApiEndpoints:
    @pytest.fixture(autouse=True)
    def setup_api_client(self, test_db_path, tmp_path):
        self.client = TestClient(app)
        self.ws = str(tmp_path / "api_ws")
        self.storage = MemoryStorage(db_path=test_db_path)
        self.lm = LongMemory(workspace=self.ws, storage=self.storage)

    def test_memory_search_and_fact_endpoints(self):
        with patch("server.api.LongMemory", return_value=self.lm):
            # Test POST /memory/fact
            resp = self.client.post("/memory/fact", json={
                "category": "convention",
                "fact_key": "api_naming",
                "fact_value": "Use plural nouns for resource endpoints",
                "workspace": self.ws
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert "fact_id" in data

            # Test GET /memory/search
            search_resp = self.client.get(f"/memory/search?q=plural+nouns&workspace={self.ws}")
            assert search_resp.status_code == 200
            search_data = search_resp.json()
            assert len(search_data["facts"]) > 0
            assert search_data["facts"][0]["fact_key"] == "api_naming"

    def test_memory_episodes_endpoint(self, test_db_path):
        em = EpisodicMemory(storage=self.storage)
        em.record_episode(
            task="Refactor database schema",
            task_type="tdd",
            success=True,
            steps=[{"thought": "Plan", "action": "migrate", "observation": "ok"}],
            workspace=self.ws,
            duration_secs=2.0
        )
        with patch("server.api.EpisodicMemory", return_value=em):
            resp = self.client.get(f"/memory/episodes?workspace={self.ws}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] >= 1
            assert data["episodes"][0]["task"] == "Refactor database schema"
