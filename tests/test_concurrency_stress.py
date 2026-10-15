"""
tests/test_concurrency_stress.py — Concurrency & High-Load Stress Testing Suite.

Benchmarks:
1. Concurrent SSE streaming chat under multi-client load.
2. Concurrent subagent delegation (Researcher, Test Runner, Reviewer).
3. Concurrent ReAct loop executions with multi-turn tool calling.
4. High-throughput SQLite memory & cost tracker writes with 0 database locks.
"""

import sys
import os
import time
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.api import app, get_agent
from memory.short_memory import ShortMemory
from memory.long_memory import LongMemory
from memory.fix_memory import FixMemory
from core.cost_tracker import CostTracker
from agent.subagent_pool import run_subagent, WorkerRole


@pytest.fixture
def api_client(tmp_path):
    """Isolated TestClient with a fresh temporary workspace."""
    from server import api
    mock_agent = MagicMock()
    mock_agent.workspace = str(tmp_path)
    mock_agent.short_mem = ShortMemory()
    mock_agent.long_mem = LongMemory(workspace=str(tmp_path))
    api._agent = mock_agent
    return TestClient(app)


class TestConcurrentSSEChat:
    """Stress test concurrent SSE streaming chat."""

    def test_concurrent_sse_chat_under_load(self, api_client):
        concurrency = 8
        tokens_per_stream = ["Hello ", "world, ", "this ", "is ", "stream ", "output."]

        def mock_stream(*args, **kwargs):
            for t in tokens_per_stream:
                time.sleep(0.01)
                yield t

        results_queue = queue.Queue()

        def worker_request(client_id: int):
            try:
                t0 = time.time()
                with api_client.stream("POST", "/chat", json={"message": f"Query {client_id}"}) as resp:
                    assert resp.status_code == 200
                    lines = [line for line in resp.iter_lines() if line]
                    elapsed = time.time() - t0
                    results_queue.put({
                        "client_id": client_id,
                        "lines": lines,
                        "elapsed": elapsed,
                        "error": None
                    })
            except Exception as e:
                results_queue.put({
                    "client_id": client_id,
                    "error": str(e)
                })

        with patch("agent.tool_interceptor.resolve_tool_calls_stream", side_effect=mock_stream):
            threads = [
                threading.Thread(target=worker_request, args=(i,))
                for i in range(concurrency)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert results_queue.qsize() == concurrency
        while not results_queue.empty():
            item = results_queue.get()
            assert item["error"] is None, f"Client {item['client_id']} encountered error: {item['error']}"
            assert len(item["lines"]) > 0
            # Confirm presence of event: done or token data
            raw_text = "\n".join(item["lines"])
            assert "event: token" in raw_text or "data:" in raw_text


class TestConcurrentSubagents:
    """Stress test concurrent subagent pool execution."""

    def test_concurrent_multi_role_delegation(self, tmp_path):
        concurrency = 6
        roles = ["researcher", "test_runner", "reviewer"]

        # Create temporary dummy file for researcher
        auth_file = tmp_path / "auth_service.py"
        auth_file.write_text("def verify_session(): return True\n", encoding="utf-8")

        def worker_subagent(idx: int):
            role = roles[idx % len(roles)]
            if role == "researcher":
                return run_subagent(role, "verify_session", workspace=str(tmp_path))
            elif role == "test_runner":
                with patch("subprocess.run") as mock_sub:
                    mock_sub.return_value = MagicMock(returncode=0, stdout="1 passed in 0.1s", stderr="")
                    return run_subagent(role, "test_auth.py", workspace=str(tmp_path))
            else: # reviewer
                with patch("agent.subagent_pool.ask", return_value="LGTM: clean diff"):
                    return run_subagent(role, "diff --git a/a.py b/a.py", workspace=str(tmp_path))

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(worker_subagent, i) for i in range(concurrency)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == concurrency
        for res in results:
            assert res["ok"] is True
            assert len(res["summary"]) > 0


class TestConcurrentReActHarness:
    """Stress test concurrent ReAct loop task execution."""

    def test_concurrent_react_runs(self, api_client):
        concurrency = 4

        mock_answer = {
            "ok": True,
            "answer": "Concurrent task resolved successfully",
            "turns": 2,
            "history": [{"thought": "Analyzed", "action": "test", "observation": "ok"}]
        }

        def post_react(task_id: int):
            resp = api_client.post("/api/react/run", json={"task": f"Concurrent task {task_id}"})
            return resp.status_code, resp.json()

        with patch("agent.react_harness.run_react_loop", return_value=mock_answer):
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(post_react, i) for i in range(concurrency)]
                results = [f.result() for f in as_completed(futures)]

        assert len(results) == concurrency
        for status_code, body in results:
            assert status_code == 200
            assert body["ok"] is True
            assert "Concurrent task resolved" in body["answer"]


class TestHighThroughputDatabaseAndState:
    """Stress test memory and tracker databases with heavy parallel writes."""

    def test_parallel_memory_and_cost_writes(self, tmp_path):
        num_threads = 10
        ops_per_thread = 20

        cost_tracker = CostTracker()
        fix_memory = FixMemory()
        short_mem = ShortMemory()
        long_mem = LongMemory(workspace=str(tmp_path))

        errors = []

        def worker_writer(thread_id: int):
            try:
                for step in range(ops_per_thread):
                    # Cost Tracker
                    cost_tracker.record("local", "llama", prompt_tokens=10, completion_tokens=5)
                    # Fix Memory
                    fix_memory.record(f"SyntaxError in thread {thread_id}", f"Fixed in step {step}")
                    # Short Term Memory
                    short_mem.add("user", f"Thread {thread_id} step {step}")
                    short_mem.add("assistant", f"Response {thread_id} {step}")
                    # Long Term Memory
                    long_mem.add("user", f"Long prompt {thread_id}-{step}")
                long_mem.save()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker_writer, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert cost_tracker.session.ollama_calls >= (num_threads * ops_per_thread)
        assert len(short_mem._turns) > 0
        hints = fix_memory.get_hints("SyntaxError in thread 0")
        assert len(hints) > 0
