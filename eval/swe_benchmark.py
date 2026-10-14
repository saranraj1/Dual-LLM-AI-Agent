"""
eval/swe_benchmark.py — Automated SWE Benchmark & Evaluation Suite.

Evaluates coding performance across standardized SWE challenges:
  - Algorithmic & data structures
  - Decorators & system patterns
  - Nested data access & validation
  - Resilient rate limiting & concurrency
Measures test pass rate, execution latency, and token efficiency.
"""

import os
import sys
import time
import tempfile
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

from core.llm import ask, get_backend
from tools.preflight_tools import validate_python_syntax
from agent.executor import _extract_file_blocks


@dataclass
class SWEChallenge:
    id: str
    title: str
    category: str
    prompt: str
    test_code: str


BENCHMARK_CHALLENGES: List[SWEChallenge] = [
    SWEChallenge(
        id="lru_cache",
        title="O(1) LRU Cache",
        category="algorithm",
        prompt="""Implement an LRUCache class in Python with capacity: int.
Methods:
- get(key: int) -> int: Returns value if key exists, else -1. Updates usage.
- put(key: int, value: int) -> None: Inserts or updates key. If capacity exceeded, evicts least recently used.
Both get and put must run in O(1) average time complexity.
Return FILE: solution.py with clean implementation.""",
        test_code="""from solution import LRUCache

def test_lru_basic():
    cache = LRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    assert cache.get(1) == 1
    cache.put(3, 3)  # evicts 2
    assert cache.get(2) == -1
    cache.put(4, 4)  # evicts 1
    assert cache.get(1) == -1
    assert cache.get(3) == 3
    assert cache.get(4) == 4
"""
    ),
    SWEChallenge(
        id="retry_decorator",
        title="Exponential Backoff Retry Decorator",
        category="system",
        prompt="""Implement a @retry decorator in Python with:
retry(max_attempts: int = 3, delay: float = 0.01, backoff: float = 2.0, exceptions: tuple = (Exception,))
It should catch specified exceptions and retry the wrapped function up to max_attempts times, multiplying delay by backoff each attempt.
If all attempts fail, re-raise the final exception.
Return FILE: solution.py.""",
        test_code="""from solution import retry
import pytest

def test_retry_success():
    calls = []
    @retry(max_attempts=3, delay=0.001)
    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("temporary error")
        return "success"

    assert flaky() == "success"
    assert len(calls) == 2

def test_retry_exhausted():
    calls = []
    @retry(max_attempts=3, delay=0.001, exceptions=(KeyError,))
    def always_fails():
        calls.append(1)
        raise KeyError("permanent")

    with pytest.raises(KeyError):
        always_fails()
    assert len(calls) == 3
"""
    ),
    SWEChallenge(
        id="json_path_extractor",
        title="Nested Key Path Extractor",
        category="data",
        prompt="""Implement get_by_path(data: dict, path: str, default: Any = None) -> Any in Python.
Path supports dot notation and list indexing, e.g. "users.items[0].id".
If key or index is missing or types mismatch, return default.
Return FILE: solution.py.""",
        test_code="""from solution import get_by_path

def test_nested_lookup():
    data = {"users": {"items": [{"id": 42, "name": "Alice"}], "total": 1}}
    assert get_by_path(data, "users.total") == 1
    assert get_by_path(data, "users.items[0].id") == 42
    assert get_by_path(data, "users.items[0].name") == "Alice"
    assert get_by_path(data, "users.items[1].id", default="none") == "none"
    assert get_by_path(data, "invalid.path", default=None) is None
"""
    ),
    SWEChallenge(
        id="token_bucket_limiter",
        title="Token Bucket Rate Limiter",
        category="concurrency",
        prompt="""Implement a TokenBucket rate limiter in Python:
class TokenBucket:
    def __init__(self, capacity: int, fill_rate: float): ...
    def consume(self, tokens: int = 1) -> bool: ...
Tokens refill monotonically based on time.time() elapsed.
Returns True if enough tokens were available and consumed, else False.
Return FILE: solution.py.""",
        test_code="""from solution import TokenBucket
import time

def test_token_bucket():
    tb = TokenBucket(capacity=5, fill_rate=10.0) # 10 tokens/sec
    assert tb.consume(5) is True
    assert tb.consume(1) is False
    time.sleep(0.15) # refills ~1.5 tokens
    assert tb.consume(1) is True
"""
    ),
]


def _extract_solution_code(response: str) -> str:
    blocks = _extract_file_blocks(response)
    if blocks:
        return blocks[0]["content"]
    import re
    m = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", response, re.IGNORECASE)
    if m:
        return m.group(1)
    return response.strip()


def run_swe_benchmark(
    challenges: Optional[List[SWEChallenge]] = None,
    backend: Optional[str] = None,
    llm_fn: Optional[Callable] = None,
    timeout_per_challenge: int = 40
) -> Dict[str, Any]:
    """
    Run evaluation suite against a target LLM backend.
    Measures pass rate, latency, syntax accuracy, and error traces.
    """
    active_challenges = challenges or BENCHMARK_CHALLENGES
    fn = llm_fn or ask
    t_suite_start = time.time()
    results = []

    for ch in active_challenges:
        t0 = time.time()
        try:
            # 1. Prompt model
            prompt = f"{ch.prompt}\n\nImportant: Write production-ready Python without external dependencies."
            raw_response = fn(prompt, backend=backend) if backend else fn(prompt)
            gen_time = time.time() - t0

            code = _extract_solution_code(raw_response)

            # 2. Syntax preflight check
            syntax = validate_python_syntax(code, filename="solution.py")
            if not syntax["valid"]:
                results.append({
                    "id": ch.id,
                    "title": ch.title,
                    "category": ch.category,
                    "passed": False,
                    "syntax_valid": False,
                    "error": f"SyntaxError: {syntax.get('message')}",
                    "latency": round(gen_time, 2)
                })
                continue

            # 3. Isolated test execution
            with tempfile.TemporaryDirectory(prefix=f"bench_{ch.id}_") as tmpdir:
                sol_path = Path(tmpdir) / "solution.py"
                test_path = Path(tmpdir) / "test_solution.py"

                sol_path.write_text(code, encoding="utf-8")
                test_path.write_text(ch.test_code, encoding="utf-8")

                cmd = [sys.executable, "-m", "pytest", "test_solution.py", "-q"]
                proc = subprocess.run(
                    cmd,
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=timeout_per_challenge
                )

                passed = proc.returncode == 0
                err_output = (proc.stderr + "\n" + proc.stdout).strip() if not passed else ""

                results.append({
                    "id": ch.id,
                    "title": ch.title,
                    "category": ch.category,
                    "passed": passed,
                    "syntax_valid": True,
                    "error": err_output[:300] if not passed else None,
                    "latency": round(gen_time, 2)
                })

        except subprocess.TimeoutExpired:
            results.append({
                "id": ch.id,
                "title": ch.title,
                "category": ch.category,
                "passed": False,
                "syntax_valid": True,
                "error": "Pytest execution timed out",
                "latency": round(time.time() - t0, 2)
            })
        except Exception as e:
            results.append({
                "id": ch.id,
                "title": ch.title,
                "category": ch.category,
                "passed": False,
                "syntax_valid": False,
                "error": str(e),
                "latency": round(time.time() - t0, 2)
            })

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    pass_rate = round((passed_count / total) * 100, 1) if total > 0 else 0.0
    total_duration = round(time.time() - t_suite_start, 2)
    avg_latency = round(sum(r["latency"] for r in results) / total, 2) if total > 0 else 0.0

    return {
        "backend": backend or get_backend(),
        "total": total,
        "passed": passed_count,
        "failed": total - passed_count,
        "pass_rate_percent": pass_rate,
        "total_duration": total_duration,
        "avg_latency_seconds": avg_latency,
        "challenges": results
    }


def run_comparative_benchmark(challenges: Optional[List[SWEChallenge]] = None) -> Dict[str, Any]:
    """
    Run SWE benchmark across both Local (Ollama) and Groq Cloud,
    producing comparative metrics and acceleration factor.
    """
    from core.llm import is_running, is_groq_available

    local_report = None
    groq_report = None

    if is_running():
        local_report = run_swe_benchmark(challenges=challenges, backend="local")

    if is_groq_available():
        groq_report = run_swe_benchmark(challenges=challenges, backend="groq")

    speedup = 1.0
    if local_report and groq_report and groq_report["avg_latency_seconds"] > 0:
        speedup = round(local_report["avg_latency_seconds"] / groq_report["avg_latency_seconds"], 1)

    return {
        "local": local_report,
        "groq": groq_report,
        "speedup_factor": speedup,
    }


def format_benchmark_report(report: Dict[str, Any]) -> str:
    """Format benchmark report into human-readable terminal table."""
    lines = [
        "",
        "🏆 SWE Benchmark & Evaluation Report",
        "═" * 68,
        f"Backend     : {report.get('backend', 'unknown').upper()}",
        f"Pass Rate   : {report.get('pass_rate_percent', 0.0)}% ({report.get('passed', 0)}/{report.get('total', 0)} passed)",
        f"Avg Latency : {report.get('avg_latency_seconds', 0.0)}s per task",
        f"Total Time  : {report.get('total_duration', 0.0)}s",
        "─" * 68,
        f"{'Challenge':<28} {'Category':<14} {'Time':>7}   Status",
        "─" * 68,
    ]

    for ch in report.get("challenges", []):
        status_ico = "✅ PASS" if ch.get("passed") else "❌ FAIL"
        lines.append(f"{ch.get('title', '')[:27]:<28} {ch.get('category', ''):<14} {ch.get('latency', 0.0):>6.1f}s   {status_ico}")
        if not ch.get("passed") and ch.get("error"):
            lines.append(f"   ↳ Error: {ch.get('error')[:60]}")

    lines.append("═" * 68)
    return "\n".join(lines)
